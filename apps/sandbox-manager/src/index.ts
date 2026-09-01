import Fastify from 'fastify';
import { loadConfig, type SandboxManagerConfig } from './config.js';
import { WorkspaceManager } from './workspace/manager.js';
import { SandboxManager } from './sandbox/manager.js';
import { Reconciler } from './reconciliation/reconciler.js';
import { PreviewManager } from './preview/manager.js';
import { PreviewProxy } from './preview/proxy.js';
import { registerWorkspaceRoutes } from './workspace/routes.js';
import { registerSandboxRoutes } from './sandbox/routes.js';
import { registerPreviewRoutes } from './preview/routes.js';

export interface SandboxManagerApp {
  app: ReturnType<typeof Fastify>;
  config: SandboxManagerConfig;
  workspaceManager: WorkspaceManager;
  sandboxManager: SandboxManager;
  reconciler: Reconciler;
  previewManager: PreviewManager;
  previewProxy: PreviewProxy;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

export async function createSandboxManager(configOverrides?: Partial<SandboxManagerConfig>): Promise<SandboxManagerApp> {
  const config = loadConfig(configOverrides);

  const workspaceManager = new WorkspaceManager(config.workspaceRoot, config.sourceRepoRoot);
  const sandboxManager = new SandboxManager(workspaceManager);
  const reconciler = new Reconciler(sandboxManager);
  const previewManager = new PreviewManager();
  const previewProxy = new PreviewProxy(previewManager, {
    port: config.previewPort,
    host: config.host,
    secret: config.secret,
  });

  const app = Fastify({
    logger: true,
    bodyLimit: 10485760, // 10MB
  });

  // Initialize
  await workspaceManager.initialize();
  await sandboxManager.initialize();
  await previewManager.initialize();

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
  await registerPreviewRoutes(app, previewManager, workspaceManager);

  let previewReconcileTimer: ReturnType<typeof setInterval> | undefined;
  let previewProxyStarted = false;

  return {
    app,
    config,
    workspaceManager,
    sandboxManager,
    reconciler,
    previewManager,
    previewProxy,
    start: async () => {
      try {
        await app.listen({ port: config.port, host: config.host });
        await previewProxy.start();
        previewProxyStarted = true;
        await previewManager.reconcile();
        previewReconcileTimer = setInterval(() => {
          void previewManager.reconcile().catch((err: unknown) => {
            console.error('[SandboxManager] Preview reconciliation failed:', err);
          });
        }, 60_000);
        previewReconcileTimer.unref();
        reconciler.start();
        console.log(`[SandboxManager] Listening on ${config.host}:${config.port}`);
        console.log(`[PreviewProxy] Listening on ${config.host}:${config.previewPort}`);
      } catch (err) {
        if (previewReconcileTimer) {
          clearInterval(previewReconcileTimer);
          previewReconcileTimer = undefined;
        }
        if (previewProxyStarted) {
          await previewProxy.stop().catch(() => undefined);
          previewProxyStarted = false;
        }
        await app.close().catch(() => undefined);
        throw err;
      }
    },
    stop: async () => {
      if (previewReconcileTimer) {
        clearInterval(previewReconcileTimer);
        previewReconcileTimer = undefined;
      }
      reconciler.stop();
      if (previewProxyStarted) {
        await previewProxy.stop();
        previewProxyStarted = false;
      }
      await app.close();
    },
  };
}

// Start if run directly
if (import.meta.url === `file://${process.argv[1]}`) {
  const manager = await createSandboxManager();
  await manager.start();
}
