import type { FastifyInstance } from 'fastify';
import type { WebSocket } from 'ws';
import websocket from '@fastify/websocket';
import { randomUUID } from 'node:crypto';
import type { PrincipalResolver } from '../index.js';
import { createRequestContext } from '../request-context/index.js';
import { LiveHub, type LiveConnection } from './hub.js';
import type { ServerFrame } from './protocol.js';

export interface RealtimeGatewayOptions {
  principalResolver: PrincipalResolver;
  hub: LiveHub;
}

export async function registerRealtimeGateway(
  app: FastifyInstance,
  options: RealtimeGatewayOptions,
): Promise<void> {
  const { principalResolver, hub } = options;

  await app.register(websocket, {
    options: { maxPayload: 64 * 1024 },
  });

  app.get('/ws/v1', { websocket: true }, (socket, request) => {
    handleSocket(socket, request.headers, principalResolver, hub);
  });
}

function handleSocket(
  socket: WebSocket,
  headers: Record<string, string | string[] | undefined>,
  principalResolver: PrincipalResolver,
  hub: LiveHub,
): void {
  // Trusted principal resolution (fail-closed in production).
  let principal: ReturnType<PrincipalResolver>;
  try {
    principal = principalResolver(headers);
  } catch {
    sendRaw(socket, {
      type: 'error',
      code: 'UNAUTHORIZED',
      message: 'Trusted principal could not be resolved',
    });
    socket.close(4401, 'unauthorized');
    return;
  }

  const conn: LiveConnection = {
    id: randomUUID(),
    principal,
    send(frame: ServerFrame) {
      sendRaw(socket, frame);
    },
    buffered() {
      return socket.bufferedAmount;
    },
    close(code: number, reason: string) {
      try {
        socket.close(code, reason);
      } catch {
        // already closed
      }
    },
  };

  hub.register(conn);

  socket.on('message', (data) => {
    const raw = data.toString();
    void hub.handleRawMessage(conn, raw);
  });

  socket.on('close', () => {
    hub.unregister(conn);
  });

  socket.on('error', () => {
    hub.unregister(conn);
  });

  // Minimal heartbeat: server ping every 30s; client may respond with ping op.
  const heartbeat = setInterval(() => {
    if (socket.readyState === socket.OPEN) {
      try {
        socket.ping();
      } catch {
        // ignore
      }
    }
  }, 30_000);

  socket.on('close', () => clearInterval(heartbeat));

  // Seed the request context for correlation only; events carry their own ids.
  void createRequestContext(principal);
}

function sendRaw(socket: WebSocket, frame: ServerFrame): void {
  if (socket.readyState === socket.OPEN) {
    socket.send(JSON.stringify(frame));
  }
}
