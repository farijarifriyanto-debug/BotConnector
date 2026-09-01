import type { DomainEvent } from '@botconnector/contracts';
import type { PrincipalContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { getProjectHighWaterSequence, replayDomainEventsAfter } from '../events/service.js';
import type { TransientRedis } from './redis.js';
import {
  ClientFrameSchema,
  type ClientFrame,
  type ServerFrame,
  type SubscribeFrame,
  type ReplayFrame,
} from './protocol.js';

/** A transport-agnostic live connection (WebSocket socket in production). */
export interface LiveConnection {
  readonly id: string;
  readonly principal: PrincipalContext;
  send(frame: ServerFrame): void;
  /** Bytes/frames currently queued in the transport's outbound buffer. */
  buffered(): number;
  close(code: number, reason: string): void;
}

const MAX_OUTBOUND_QUEUE = 512;
const REPLAY_LIMIT = 1000;
const BACKPRESSURE_CLOSE_CODE = 1013;

interface SubscriptionState {
  handoffInProgress: boolean;
  /** Bounded handoff buffer for events arriving while replay is pending. */
  buffer: DomainEvent[];
  /** Set when the handoff buffer overflows: handoff aborted deterministically. */
  overflowed: boolean;
}

interface LiveHubOptions {
  maxOutboundQueue?: number;
  replayLimit?: number;
}

/**
 * Realtime hub: receives transient events from Redis (trusted server-side
 * pattern subscriber) and delivers them ONLY to authorized connections.
 * Authorization (project belongs to principal workspace) is enforced via the
 * authoritative RLS-scoped database before any live attach or replay.
 */
export class LiveHub {
  private readonly connections = new Map<string, LiveConnection>();
  private readonly subs = new Map<string, Map<string, SubscriptionState>>();
  private readonly options: Required<LiveHubOptions>;
  private unsubscribePattern: (() => Promise<void>) | null = null;

  constructor(
    private readonly redis: TransientRedis,
    options: LiveHubOptions = {},
  ) {
    this.options = {
      maxOutboundQueue: options.maxOutboundQueue ?? MAX_OUTBOUND_QUEUE,
      replayLimit: options.replayLimit ?? REPLAY_LIMIT,
    };
  }

  get connectionCount(): number {
    return this.connections.size;
  }

  /** Subscribe the hub to Redis transient fanout (trusted server-side). */
  async start(): Promise<void> {
    if (this.unsubscribePattern) {
      return;
    }
    this.unsubscribePattern = await this.redis.subscribePattern((channel, event) => {
      this.onTransientEvent(channel, event);
    });
  }

  async stop(): Promise<void> {
    if (this.unsubscribePattern) {
      await this.unsubscribePattern();
      this.unsubscribePattern = null;
    }
  }

  register(conn: LiveConnection): void {
    this.connections.set(conn.id, conn);
    this.subs.set(conn.id, new Map());
  }

  unregister(conn: LiveConnection): void {
    this.connections.delete(conn.id);
    this.subs.delete(conn.id);
  }

  isSubscribed(conn: LiveConnection, projectId: string): boolean {
    return this.subs.get(conn.id)?.has(projectId) ?? false;
  }

  async handleRawMessage(conn: LiveConnection, raw: string): Promise<void> {
    let frame: ClientFrame;
    try {
      const parsed = JSON.parse(raw);
      frame = ClientFrameSchema.parse(parsed);
    } catch {
      conn.send({
        type: 'error',
        code: 'INVALID_FRAME',
        message: 'Malformed or unsupported frame',
      });
      return;
    }

    try {
      switch (frame.op) {
        case 'subscribe':
          await this.handleSubscribe(conn, frame);
          break;
        case 'unsubscribe':
          await this.handleUnsubscribe(conn, frame);
          break;
        case 'replay':
          await this.handleReplay(conn, frame);
          break;
        case 'ping':
          conn.send({ type: 'pong' });
          break;
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      conn.send({ type: 'error', code: 'INTERNAL', message: message.slice(0, 300) });
    }
  }

  /** Authoritative project authorization: RLS-scoped, workspace-bound. */
  private async authorizeProject(conn: LiveConnection, projectId: string): Promise<boolean> {
    return withTenantTransaction(conn.principal.workspaceId, async (tx) => {
      const { rows } = await tx.client.query(
        `SELECT id FROM core.projects WHERE id = $1`,
        [projectId],
      );
      return rows.length > 0;
    });
  }

  async handleSubscribe(conn: LiveConnection, frame: SubscribeFrame): Promise<void> {
    const { project_id: projectId, after_sequence } = frame;

    const authorized = await this.authorizeProject(conn, projectId);
    if (!authorized) {
      // Non-disclosure: same error regardless of existence vs cross-tenant
      conn.send({
        type: 'error',
        code: 'FORBIDDEN',
        message: 'Project is not available in your workspace',
      });
      return;
    }

    this.subs.get(conn.id)!.set(projectId, { handoffInProgress: false, overflowed: false, buffer: [] });

    if (after_sequence !== undefined) {
      await this.performReplayHandoff(conn, projectId, after_sequence);
    } else {
      const highWater = await this.getHighWater(conn, projectId);
      conn.send({ type: 'subscribed', project_id: projectId, high_water_sequence: highWater });
    }
  }

  async handleUnsubscribe(conn: LiveConnection, frame: { project_id: string }): Promise<void> {
    const { project_id: projectId } = frame;
    this.subs.get(conn.id)?.delete(projectId);
    conn.send({ type: 'unsubscribed', project_id: projectId });
  }

  async handleReplay(conn: LiveConnection, frame: ReplayFrame): Promise<void> {
    const { project_id: projectId, after_sequence: afterSequence } = frame;
    const authorized = await this.authorizeProject(conn, projectId);
    if (!authorized) {
      conn.send({
        type: 'error',
        code: 'FORBIDDEN',
        message: 'Project is not available in your workspace',
      });
      return;
    }
    this.subs.get(conn.id)?.set(projectId, { handoffInProgress: false, overflowed: false, buffer: [] });
    await this.performReplayHandoff(conn, projectId, afterSequence);
  }

  private async getHighWater(conn: LiveConnection, projectId: string): Promise<string> {
    return withTenantTransaction(conn.principal.workspaceId, async (tx) =>
      getProjectHighWaterSequence(tx, projectId),
    );
  }

  /**
   * Replay/live race-safe handoff. Invariant: every durable event with
   * sequence <= high-water is delivered by replay; every event with sequence >
   * high-water is delivered from the live buffer. No silent gap.
   *
   * 1. authorize (caller)
   * 2. mark handoff in progress (live events buffer on the subscription)
   * 3. capture durable high-water
   * 4. replay durable events in (after_sequence, high-water]
   * 5. deduplicate buffered live events already covered by replay (id/sequence)
   * 6. flush remaining buffered live events in sequence order
   * 7. emit replay_complete and switch to normal live mode
   */
  private async performReplayHandoff(
    conn: LiveConnection,
    projectId: string,
    afterSequence: string,
  ): Promise<void> {
    const state = this.subs.get(conn.id)!.get(projectId)!;
    state.handoffInProgress = true;
    state.overflowed = false;
    state.buffer = [];

    const abortHandoff = (reason: string) => {
      conn.send({ type: 'snapshot_required', project_id: projectId, reason });
      state.handoffInProgress = false;
      this.subs.get(conn.id)?.delete(projectId);
    };

    const highWater = await this.getHighWater(conn, projectId);

    if (state.overflowed) {
      // Events arrived faster than the handoff could absorb them.
      abortHandoff('replay handoff buffer overflow; reconnect and replay');
      return;
    }

    if (BigInt(afterSequence) > BigInt(highWater)) {
      conn.send({
        type: 'snapshot_required',
        project_id: projectId,
        reason: `after_sequence ${afterSequence} is ahead of durable high-water ${highWater}`,
      });
      state.handoffInProgress = false;
      return;
    }

    let replayed: DomainEvent[];
    try {
      replayed = await withTenantTransaction(conn.principal.workspaceId, async (tx) =>
        replayDomainEventsAfter(tx, projectId, afterSequence, this.options.replayLimit),
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      conn.send({ type: 'error', code: 'REPLAY_UNAVAILABLE', message: message.slice(0, 300) });
      state.handoffInProgress = false;
      return;
    }

    if (state.overflowed) {
      abortHandoff('replay handoff buffer overflow; reconnect and replay');
      return;
    }

    if (replayed.length === this.options.replayLimit) {
      // The requested range may be truncated; cannot safely satisfy.
      abortHandoff('replay range exceeds safety limit; full snapshot required');
      return;
    }

    const replayedIds = new Set(replayed.map((e) => e.id));
    const replayedSeq = new Set(replayed.map((e) => e.sequence));

    // Drain handoff buffer, dedup against replay, preserve sequence order.
    // Everything below is synchronous: no Redis event can interleave.
    const buffered = state.buffer
      .filter((e) => !replayedIds.has(e.id) && !replayedSeq.has(e.sequence))
      .sort((a, b) => (BigInt(a.sequence) < BigInt(b.sequence) ? -1 : 1));
    state.handoffInProgress = false;

    for (const event of replayed) {
      conn.send({ type: 'event', event });
    }
    for (const event of buffered) {
      conn.send({ type: 'event', event });
    }
    conn.send({
      type: 'replay_complete',
      project_id: projectId,
      high_water_sequence: highWater,
      replayed: replayed.length,
    });
  }

  /** Route a transient event (from Redis) to authorized subscribers. */
  private onTransientEvent(channel: string, event: DomainEvent): void {
    const parts = channel.split(':');
    // channel format: botconnector:events:{workspaceId}:{projectId}
    if (parts.length < 4) {
      return;
    }
    const channelWorkspace = parts[2];
    const channelProject = parts[3];

    for (const [connId, subs] of this.subs) {
      const conn = this.connections.get(connId);
      if (!conn || conn.principal.workspaceId !== channelWorkspace) {
        continue; // cross-workspace: never deliver
      }
      const state = subs.get(channelProject);
      if (!state) {
        continue; // not subscribed to this project
      }
      const frame: ServerFrame = { type: 'event', event };
      if (state.handoffInProgress) {
        if (state.buffer.length < this.options.maxOutboundQueue) {
          state.buffer.push(event);
        } else {
          // Handoff buffer full: never silently drop. Abort the handoff
          // deterministically; the client recovers via durable replay.
          state.overflowed = true;
        }
      } else {
        this.deliver(conn, frame);
      }
    }
  }

  /**
   * Bounded outbound delivery. Backpressure is measured against the
   * transport's actual outbound buffer (ws bufferedAmount). A client that
   * falls behind is closed deterministically and recovers via replay.
   */
  private deliver(conn: LiveConnection, frame: ServerFrame): void {
    if (conn.buffered() >= this.options.maxOutboundQueue) {
      conn.close(
        BACKPRESSURE_CLOSE_CODE,
        'backpressure: client fell behind; reconnect to replay',
      );
      this.unregister(conn);
      return;
    }
    try {
      conn.send(frame);
    } catch {
      this.unregister(conn);
    }
  }
}
