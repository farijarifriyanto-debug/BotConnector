import type { SandboxManager } from '../sandbox/manager.js';

export class Reconciler {
  private readonly sandboxManager: SandboxManager;
  private readonly intervalMs: number;
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(sandboxManager: SandboxManager, intervalMs = 60000) {
    this.sandboxManager = sandboxManager;
    this.intervalMs = intervalMs;
  }

  start(): void {
    if (this.timer) {
      return; // Already running
    }

    this.timer = setInterval(async () => {
      try {
        await this.run();
      } catch (err) {
        console.error('[Reconciler] Error during reconciliation:', err);
      }
    }, this.intervalMs);
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  async run(): Promise<{ destroyed: number; kept: number }> {
    console.log('[Reconciler] Running reconciliation...');
    const result = await this.sandboxManager.reconcile();
    console.log(`[Reconciler] Reconciliation complete: destroyed=${result.destroyed}, kept=${result.kept}`);
    return result;
  }
}
