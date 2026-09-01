import { randomBytes } from 'node:crypto';
import { ContainerProvider } from '../sandbox/provider.js';
import { getProfile } from '../sandbox/profiles.js';
import { detectStack, type DetectedStack } from './stack-detector.js';
import type { ExecutionWorkspace } from '../workspace/manager.js';

export interface LastKnownGood {
  previewId: string;
  containerId: string;
  image: string;
  command: string[];
  detectedStack: StackType;
  snapshotAt: Date;
  sourceRevision?: string;
}

export type StackType = 'node' | 'python' | 'go' | 'rust' | 'static' | 'unknown';

export interface Preview {
  id: string;
  workspaceId: string;
  projectId: string;
  taskId: string;
  containerId: string;
  containerIp: string | undefined;
  devPort: number;
  state: 'creating' | 'running' | 'starting' | 'stopping' | 'stopped' | 'failed' | 'destroyed';
  createdAt: Date;
  destroyedAt?: Date;
  lastValidState: string | undefined;
  detectedStack: StackType;
  image: string;
}

export interface CreatePreviewParams {
  workspaceId: string;
  projectId: string;
  taskId: string;
  command?: string[];
  devPort?: number;
  image?: string;
}

export class PreviewManager {
  private readonly previews = new Map<string, Preview>();
  private readonly lkg = new Map<string, LastKnownGood>(); // projectId -> LKG
  private readonly containerProvider: ContainerProvider;
  private readonly networkPrefix: string;
  private readonly lifecycleOperations = new Map<string, Promise<void>>();
  private readonly projectOperations = new Map<string, Promise<unknown>>();
  private readonly pendingNetworkCleanup = new Set<string>();
  private reconciliationOperation?: Promise<{ destroyed: number; kept: number }>;
  private static readonly DEFAULT_DEV_PORT = 3000;

  constructor() {
    this.containerProvider = new ContainerProvider();
    this.networkPrefix = 'botconnector-preview';
  }

  async initialize(): Promise<void> {
    // No global network needed — per-project networks created on demand
  }

  private getProjectNetwork(projectId: string): string {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(projectId)) {
      throw new Error('Invalid project id for preview network');
    }
    return `${this.networkPrefix}-${projectId}`;
  }

  private async ensureProjectNetwork(projectId: string): Promise<string> {
    const networkName = this.getProjectNetwork(projectId);
    await this.containerProvider.createNetwork(networkName, projectId);
    return networkName;
  }

  async createPreview(params: CreatePreviewParams, workspace: ExecutionWorkspace): Promise<Preview> {
    return this.withProjectLock(params.projectId, () => this.createPreviewUnsafe(params, workspace));
  }

  private async createPreviewUnsafe(params: CreatePreviewParams, workspace: ExecutionWorkspace): Promise<Preview> {
    const previewId = `preview-${randomBytes(8).toString('hex')}`;
    const profile = getProfile('preview');

    // Auto-detect stack from workspace files
    const detected = await detectStack(workspace.worktreePath);
    const image = params.image ?? detected.image;
    const command = params.command ?? detected.command;

    const preview: Preview = {
      id: previewId,
      workspaceId: params.workspaceId,
      projectId: params.projectId,
      taskId: params.taskId,
      containerId: '',
      containerIp: undefined,
      devPort: params.devPort ?? PreviewManager.DEFAULT_DEV_PORT,
      state: 'creating',
      createdAt: new Date(),
      lastValidState: undefined,
      detectedStack: detected.type,
      image,
    };

    this.previews.set(previewId, preview);
    let releaseProvisioning!: () => void;
    const provisioning = new Promise<void>((resolve) => {
      releaseProvisioning = resolve;
    });
    this.lifecycleOperations.set(previewId, provisioning);

    let networkName: string | undefined;
    try {
      const devPort = params.devPort ?? PreviewManager.DEFAULT_DEV_PORT;
      networkName = await this.ensureProjectNetwork(params.projectId);

      const labels: Record<string, string> = {
        'botconnector.preview': 'true',
        'botconnector.preview.id': previewId,
        'botconnector.preview.workspace_id': params.workspaceId,
        'botconnector.preview.project_id': params.projectId,
        'botconnector.preview.task_id': params.taskId,
        'botconnector.preview.stack': detected.type,
      };

      const container = await this.containerProvider.create({
        image,
        command,
        args: [],
        env: { PORT: String(devPort) },
        workspaceMount: workspace.worktreePath,
        workingDir: '/workspace',
        cpuLimit: profile.cpuLimit,
        memoryLimit: profile.memoryLimit,
        pidsLimit: profile.pidsLimit,
        networkDisabled: false,
        networkName,
        readOnlyRootfs: profile.readOnlyRootfs,
        timeoutMs: profile.timeoutMs,
      }, labels);

      preview.containerId = container.id;

      // Wait for container to get IP on the network
      for (let i = 0; i < 10; i++) {
        await new Promise(resolve => setTimeout(resolve, 300));
        preview.containerIp = await this.containerProvider.getContainerIp(
          container.id,
          networkName,
        );
        if (preview.containerIp) break;
      }

      // C1: Don't claim running without confirmed connectivity
      if (!preview.containerIp) {
        preview.state = 'failed';
        await this.containerProvider.destroy(container.id);
        throw new Error('Preview container failed to get IP address');
      }

      preview.state = 'running';
      preview.lastValidState = 'running';

      // A new running preview supersedes the previous project preview.
      const previousLkg = this.lkg.get(params.projectId);
      if (previousLkg && previousLkg.previewId !== previewId) {
        await this.destroyPreview(previousLkg.previewId);
      }

      // Update LKG — this preview is now the last known good for this project
      this.lkg.set(params.projectId, {
        previewId,
        containerId: container.id,
        image,
        command,
        detectedStack: detected.type,
        snapshotAt: new Date(),
      });

      return preview;
    } catch (err) {
      preview.state = 'failed';
      if (preview.containerId) {
        let containerCleanupFailed = false;
        try {
          await this.containerProvider.destroy(preview.containerId);
        } catch (cleanupErr) {
          containerCleanupFailed = true;
          console.error(`[PreviewManager] Failed to clean up failed preview ${previewId}:`, cleanupErr);
        }
        if (containerCleanupFailed) {
          // Keep the failed record so reconciliation can retry the container cleanup.
          if (networkName) this.pendingNetworkCleanup.add(params.projectId);
          throw err;
        }
      }
      this.previews.delete(previewId);
      if (networkName) {
        await this.cleanupProjectNetworkIfUnused(params.projectId);
      }
      throw err;
    } finally {
      releaseProvisioning();
      if (this.lifecycleOperations.get(previewId) === provisioning) {
        this.lifecycleOperations.delete(previewId);
      }
    }
  }

  async stopPreview(previewId: string): Promise<void> {
    return this.withLifecycleLock(previewId, async () => this.stopPreviewUnsafe(previewId));
  }

  private async stopPreviewUnsafe(previewId: string): Promise<void> {
    const preview = this.previews.get(previewId);
    if (!preview) {
      return; // Idempotent
    }

    // C2: Guard against concurrent stop/destroy
    if (preview.state === 'stopping' || preview.state === 'stopped' || preview.state === 'destroyed') {
      return;
    }

    const previousState = preview.state;
    preview.state = 'stopping';

    try {
      if (preview.containerId) {
        preview.lastValidState = previousState;
        await this.containerProvider.stop(preview.containerId);
        await this.containerProvider.destroy(preview.containerId);
      }
    } catch (err) {
      preview.state = previousState;
      throw err;
    }

    preview.state = 'stopped';
    preview.destroyedAt = new Date();

    // If this was the LKG, remove it
    const lkg = this.lkg.get(preview.projectId);
    if (lkg?.previewId === previewId) {
      this.lkg.delete(preview.projectId);
    }

    await this.cleanupProjectNetworkIfUnused(preview.projectId);
  }

  async destroyPreview(previewId: string): Promise<void> {
    return this.withLifecycleLock(previewId, async () => this.destroyPreviewUnsafe(previewId));
  }

  private async destroyPreviewUnsafe(previewId: string): Promise<void> {
    const preview = this.previews.get(previewId);
    if (!preview) {
      return; // Idempotent
    }

    // C2: Guard against concurrent stop/destroy
    if (preview.state === 'destroyed') {
      return;
    }

    const previousState = preview.state;
    preview.state = 'stopping';

    try {
      if (preview.containerId) {
        preview.lastValidState = previousState;
        await this.containerProvider.destroy(preview.containerId);
      }
    } catch (err) {
      preview.state = previousState;
      throw err;
    }

    preview.state = 'destroyed';
    preview.destroyedAt = new Date();
    this.previews.delete(previewId);

    // If this was the LKG, remove it
    const lkg = this.lkg.get(preview.projectId);
    if (lkg?.previewId === previewId) {
      this.lkg.delete(preview.projectId);
    }

    await this.cleanupProjectNetworkIfUnused(preview.projectId);
  }

  private async withLifecycleLock(
    previewId: string,
    operation: () => Promise<void>,
  ): Promise<void> {
    const previous = this.lifecycleOperations.get(previewId);
    const current = (previous ?? Promise.resolve()).catch(() => undefined).then(operation);
    this.lifecycleOperations.set(previewId, current);
    try {
      await current;
    } finally {
      if (this.lifecycleOperations.get(previewId) === current) {
        this.lifecycleOperations.delete(previewId);
      }
    }
  }

  private async withProjectLock<T>(projectId: string, operation: () => Promise<T>): Promise<T> {
    const previous = this.projectOperations.get(projectId);
    const current = (previous ?? Promise.resolve()).catch(() => undefined).then(operation);
    this.projectOperations.set(projectId, current);
    try {
      return await current;
    } finally {
      if (this.projectOperations.get(projectId) === current) {
        this.projectOperations.delete(projectId);
      }
    }
  }

  private async cleanupProjectNetworkIfUnused(projectId: string): Promise<void> {
    const active = Array.from(this.previews.values()).some(
      (preview) => preview.projectId === projectId &&
        ['creating', 'starting', 'running', 'stopping'].includes(preview.state),
    );
    if (!active) {
      try {
        await this.containerProvider.removeNetwork(this.getProjectNetwork(projectId), projectId);
        this.pendingNetworkCleanup.delete(projectId);
      } catch (err) {
        this.pendingNetworkCleanup.add(projectId);
        throw err;
      }
    }
  }

  async getLastKnownGood(projectId: string): Promise<LastKnownGood | undefined> {
    return this.lkg.get(projectId);
  }

  async getPreview(previewId: string): Promise<Preview | undefined> {
    return this.previews.get(previewId);
  }

  async listPreviews(): Promise<Preview[]> {
    return Array.from(this.previews.values());
  }

  async listPreviewsByProject(projectId: string): Promise<Preview[]> {
    return Array.from(this.previews.values()).filter(p => p.projectId === projectId);
  }

  async reconcile(): Promise<{ destroyed: number; kept: number }> {
    const previous = this.reconciliationOperation;
    const current = (previous ?? Promise.resolve()).catch(() => undefined).then(() => this.reconcileUnsafe());
    this.reconciliationOperation = current;
    try {
      return await current;
    } finally {
      if (this.reconciliationOperation === current) {
        this.reconciliationOperation = undefined;
      }
    }
  }

  private async reconcileUnsafe(): Promise<{ destroyed: number; kept: number }> {
    const ownedContainers = await this.containerProvider.listOwned({
      'botconnector.preview': 'true',
    });

    let destroyed = 0;
    let kept = 0;
    const projectIdsToClean = new Set<string>(this.pendingNetworkCleanup);
    const ownedPreviewIds = new Set<string>();

    for (const container of ownedContainers) {
      const previewId = container.labels['botconnector.preview.id'];
      if (!previewId) {
        continue;
      }
      ownedPreviewIds.add(previewId);

      const preview = this.previews.get(previewId);
      if (!preview || preview.state === 'failed' || preview.state === 'destroyed') {
        // Orphaned container - destroy it
        await this.containerProvider.destroy(container.id);
        const projectId = container.labels['botconnector.preview.project_id'];
        if (projectId) {
          projectIdsToClean.add(projectId);
        }
        if (preview?.state === 'failed') this.previews.delete(previewId);
        destroyed++;
      } else {
        kept++;
      }
    }

    for (const projectId of projectIdsToClean) {
      await this.cleanupProjectNetworkIfUnused(projectId);
    }

    for (const preview of this.previews.values()) {
      if (preview.state === 'failed' && !ownedPreviewIds.has(preview.id)) {
        this.previews.delete(preview.id);
      }
    }

    return { destroyed, kept };
  }
}
