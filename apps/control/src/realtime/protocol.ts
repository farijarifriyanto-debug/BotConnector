import { z } from 'zod';
import { SequenceSchema } from '@botconnector/contracts';

/**
 * Minimal WebSocket transport protocol for /ws/v1.
 *
 * These are transport framing schemas ONLY. The canonical domain event is
 * carried intact inside the `event` field of a server frame using the locked
 * EventEnvelope domain_event variant — we do not redefine EventEnvelope here.
 */

export const SubscribeFrameSchema = z.strictObject({
  op: z.literal('subscribe'),
  project_id: z.string().min(1),
  after_sequence: SequenceSchema.optional(),
});

export const UnsubscribeFrameSchema = z.strictObject({
  op: z.literal('unsubscribe'),
  project_id: z.string().min(1),
});

export const ReplayFrameSchema = z.strictObject({
  op: z.literal('replay'),
  project_id: z.string().min(1),
  after_sequence: SequenceSchema,
});

export const PingFrameSchema = z.strictObject({
  op: z.literal('ping'),
});

export const ClientFrameSchema = z.discriminatedUnion('op', [
  SubscribeFrameSchema,
  UnsubscribeFrameSchema,
  ReplayFrameSchema,
  PingFrameSchema,
]);

export type ClientFrame = z.infer<typeof ClientFrameSchema>;
export type SubscribeFrame = z.infer<typeof SubscribeFrameSchema>;
export type ReplayFrame = z.infer<typeof ReplayFrameSchema>;

export interface SubscribedFrame {
  type: 'subscribed';
  project_id: string;
  high_water_sequence: string;
}

export interface UnsubscribedFrame {
  type: 'unsubscribed';
  project_id: string;
}

export interface EventFrame {
  type: 'event';
  event: unknown;
}

export interface ReplayCompleteFrame {
  type: 'replay_complete';
  project_id: string;
  high_water_sequence: string;
  replayed: number;
}

export interface SnapshotRequiredFrame {
  type: 'snapshot_required';
  project_id: string;
  reason: string;
}

export interface ErrorFrame {
  type: 'error';
  code: string;
  message: string;
  request_id?: string;
}

export interface PongFrame {
  type: 'pong';
}

export type ServerFrame =
  | SubscribedFrame
  | UnsubscribedFrame
  | EventFrame
  | ReplayCompleteFrame
  | SnapshotRequiredFrame
  | ErrorFrame
  | PongFrame;

export const PROTOCOL_VERSION = 1;
