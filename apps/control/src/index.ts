import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import Fastify from 'fastify';
import cors from '@fastify/cors';
import { sendSuccess, sendError } from './errors/response.js';
import { createRequestContext, type PrincipalContext } from './request-context/index.js';
import { registerProjectRoutes } from './project/routes.js';
import { registerArtifactRoutes } from './artifact/routes.js';
import { registerArtifactVersionRoutes } from './artifact-version/routes.js';
import { registerPhaseRoutes } from './phase/routes.js';
import { registerBacklogRoutes } from './backlog/routes.js';
import { registerTaskRoutes } from './task/routes.js';
import { registerFocusLockRoutes } from './focus-lock/routes.js';
import { registerGenerationRunRoutes } from './generation/routes.js';
import { registerOpenApiRoutes } from './openapi/index.js';
import { registerPreviewRoutes } from './preview/routes.js';
import { registerSandboxRoutes } from './sandbox/routes.js';
import { registerWorkspaceRoutes } from './workspace/routes.js';
import { SandboxManagerClient } from './sandbox-manager/client.js';
import { closePool } from './db/pool.js';
import { createTransientRedis } from './realtime/redis.js';
import { LiveHub } from './realtime/hub.js';
import { OutboxDispatcher } from './events/dispatcher.js';
import { registerRealtimeGateway } from './realtime/gateway.js';

export type PrincipalResolver = (headers: Record<string, string | string[] | undefined>) => PrincipalContext;

function createFailClosedResolver(): PrincipalResolver {
  return () => {
    throw new Error(
      'No PrincipalResolver configured. Production must inject auth middleware via AppOptions.principalResolver.',
    );
  };
}

export interface RealtimeOptions {
  redisUrl: string;
  dispatchIntervalMs?: number;
  autoStartDispatcher?: boolean;
}

export interface AppOptions {
  principalResolver: PrincipalResolver;
  realtime?: RealtimeOptions;
}

export interface RealtimeHandle {
  hub: LiveHub;
  dispatcher: OutboxDispatcher;
  redis: ReturnType<typeof createTransientRedis>;
}

export async function buildApp(options: AppOptions) {
  if (!options.principalResolver) {
    throw new Error(
      'No PrincipalResolver configured. Production must inject auth middleware via AppOptions.principalResolver.',
    );
  }
  const resolvePrincipal = options.principalResolver;

  const app = Fastify({
    logger: {
      level: 'info',
      formatters: {
        level(label) {
          return { level: label };
        },
        bindings(bindings) {
          return { pid: bindings.pid };
        },
      },
      serializers: {
        req(request) {
          return {
            method: request.method,
            url: request.url,
            request_id: (request as any).requestId,
          };
        },
        res(reply) {
          return {
            statusCode: reply.statusCode,
          };
        },
      },
    },
    genReqId() {
      return randomUUID();
    },
  });

  await app.register(cors, { origin: true });

  app.decorate('resolvePrincipal', resolvePrincipal);

  app.addHook('onRequest', async (request) => {
    (request as any).startTime = Date.now();
  });

  app.addHook('onResponse', async (request, reply) => {
    const duration = Date.now() - ((request as any).startTime || Date.now());
    app.log.info({
      request_id: request.id,
      method: request.method,
      url: request.url,
      status: reply.statusCode,
      duration_ms: duration,
    });
  });

  app.setErrorHandler((error, request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal, request.id);
    sendError(reply, requestCtx, error);
  });

  app.get('/api/v1/health', async (_request, reply) => {
    const requestCtx = createRequestContext({
      userId: 'system',
      workspaceId: 'system',
    });

    sendSuccess(reply, requestCtx, { status: 'healthy', phase: 7 });
  });

  await registerProjectRoutes(app, resolvePrincipal);
  await registerArtifactRoutes(app, resolvePrincipal);
  await registerArtifactVersionRoutes(app, resolvePrincipal);
  await registerPhaseRoutes(app, resolvePrincipal);
  await registerBacklogRoutes(app, resolvePrincipal);
  await registerTaskRoutes(app, resolvePrincipal);
  await registerFocusLockRoutes(app, resolvePrincipal);
  await registerGenerationRunRoutes(app, resolvePrincipal);
  await registerOpenApiRoutes(app);

  // Preview routes (via SandboxManager)
  const sandboxManagerUrl = process.env.SANDBOX_MANAGER_URL;
  const sandboxManagerSecret = process.env.SANDBOX_MANAGER_SECRET;
  const sandboxPreviewUrl = process.env.SANDBOX_PREVIEW_URL;
  if (!sandboxManagerUrl || !sandboxManagerSecret) {
    throw new Error(
      'SANDBOX_MANAGER_URL and SANDBOX_MANAGER_SECRET must be set. ' +
      'Preview routes are disabled without Sandbox Manager configuration.',
    );
  }
  if (!sandboxPreviewUrl) {
    throw new Error(
      'SANDBOX_PREVIEW_URL must be set (e.g. http://127.0.0.1:4100). ' +
      'Browser preview gateway requires the PreviewProxy URL.',
    );
  }
  const sandboxManagerClient = new SandboxManagerClient({
    url: sandboxManagerUrl,
    secret: sandboxManagerSecret,
  });
  await registerPreviewRoutes(app, resolvePrincipal, sandboxManagerClient, {
    previewProxyUrl: sandboxPreviewUrl,
    previewProxySecret: sandboxManagerSecret,
  });
  await registerSandboxRoutes(app, sandboxManagerClient, resolvePrincipal);
  await registerWorkspaceRoutes(app, sandboxManagerClient, resolvePrincipal);

  if (options.realtime) {
    const redis = createTransientRedis(options.realtime.redisUrl);
    const hub = new LiveHub(redis);
    const dispatcher = new OutboxDispatcher({
      redis,
      intervalMs: options.realtime.dispatchIntervalMs ?? 1000,
    });
    await registerRealtimeGateway(app, { principalResolver: resolvePrincipal, hub });
    await hub.start();

    const handle: RealtimeHandle = { hub, dispatcher, redis };
    app.decorate('realtime', handle);

    if (options.realtime.autoStartDispatcher !== false) {
      dispatcher.start();
    }

    app.addHook('onClose', async () => {
      dispatcher.stop();
      await hub.stop();
      await redis.close();
    });
  }

  return app;
}

async function main() {
  const port = parseInt(process.env.PORT || '3100', 10);
  const host = process.env.HOST || '0.0.0.0';

  console.error(
    '[FATAL] No PrincipalResolver configured. ' +
    'Production requires auth middleware via AppOptions.principalResolver. ' +
    'See apps/control/src/index.ts for PrincipalResolver type.',
  );
  process.exit(1);
}

// Only invoke the production entrypoint when executed directly (node dist/index.js).
// Importing the module (tests, realtime gateway, tooling) must not exit the process.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
