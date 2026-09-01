import Fastify from 'fastify';
import { loadConfig, type SandboxManagerConfig } from './config.js';
import { WorkspaceManager } from './workspace/manager.js';
import { SandboxManager } from './sandbox/manager.js';
import { Reconciler } from './reconciliation/reconciler.js';
import { registerWorkspaceRoutes } from './workspace/routes.js';
import { registerSandboxRoutes } from './sandbox/routes.js';

export interface SandboxManagerApp {
  app: ReturnType<typeof Fastify>;
  config: SandboxManagerConfig;
  workspaceManager: WorkspaceManager;
  sandboxManager: SandboxManager;
  reconciler: Reconciler;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

export async function createSandboxManager(configOverrides?: Partial<SandboxManagerConfig>): Promise<SandboxManagerApp> {
  const config = loadConfig(configOverrides);

  const workspaceManager = new WorkspaceManager(config.workspaceRoot);
  const sandboxManager = new SandboxManager(config.workspaceRoot);
  const reconciler = new Reconciler(sandboxManager);

  const app = Fastify({
    logger: true,
    bodyLimit: 10485760, // 10MB
  });

  // Initialize
  await workspaceManager.initialize();
  await sandboxManager.initialize();

  // Authentication hook
  app.addHook('onRequest', async (request, reply) => {
    // Skip auth for health check
    if (request.url === '/health') {
      return;
    }

    const authHeader = request.headers.authorization;
    if (!authHeader || authHeader !== `Bearer ${config.secret}`) {
      reply.code(401).send({
        error: { code: 'UNAUTHORIZED', message: 'Invalid or missing authorization' },
      });
    }
  });

  // Health check
  app.get('/health', async () => {
    return { status: 'ok' };
  });

  // Register routes
  await registerWorkspaceRoutes(app, workspaceManager);
  await registerSandboxRoutes(app, sandboxManager);

  return {
    app,
    config,
    workspaceManager,
    sandboxManager,
    reconciler,
    start: async () => {
      await app.listen({ port: config.port, host: config.host });
      reconciler.start();
      console.log(`[SandboxManager] Listening on ${config.host}:${config.port}`);
    },
    stop: async () => {
      reconciler.stop();
      await app.close();
    },
  };
}

// Start if run directly
if (import.meta.url === `file://${process.argv[1]}`) {
  const manager = await createSandboxManager();
  await manager.start();
}
