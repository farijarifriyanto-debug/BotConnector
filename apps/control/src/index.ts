import { randomUUID } from 'node:crypto';
import Fastify from 'fastify';
import cors from '@fastify/cors';
import { sendSuccess, sendError } from './errors/response.js';
import { createRequestContext, type PrincipalContext } from './request-context/index.js';
import { registerProjectRoutes } from './project/routes.js';
import { registerArtifactRoutes } from './artifact/routes.js';
import { registerArtifactVersionRoutes } from './artifact-version/routes.js';
import { registerPhaseRoutes } from './phase/routes.js';
import { registerBacklogRoutes } from './backlog/routes.js';
import { registerOpenApiRoutes } from './openapi/index.js';
import { closePool } from './db/pool.js';

export type PrincipalResolver = (headers: Record<string, string | string[] | undefined>) => PrincipalContext;

function createFailClosedResolver(): PrincipalResolver {
  return () => {
    throw new Error(
      'No PrincipalResolver configured. Production must inject auth middleware via AppOptions.principalResolver.',
    );
  };
}

export interface AppOptions {
  principalResolver: PrincipalResolver;
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

    sendSuccess(reply, requestCtx, { status: 'healthy', phase: 3 });
  });

  await registerProjectRoutes(app, resolvePrincipal);
  await registerArtifactRoutes(app, resolvePrincipal);
  await registerArtifactVersionRoutes(app, resolvePrincipal);
  await registerPhaseRoutes(app, resolvePrincipal);
  await registerBacklogRoutes(app, resolvePrincipal);
  await registerOpenApiRoutes(app);

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

main();
