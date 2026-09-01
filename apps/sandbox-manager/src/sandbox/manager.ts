import { randomBytes } from 'node:crypto';
import { WorkspaceManager, type ExecutionWorkspace } from '../workspace/manager.js';
import { ContainerProvider, type ContainerInfo, type ExecResult } from './provider.js';
import { getProfile, type SandboxProfile } from './profiles.js';

export interface Sandbox {
  id: string;
  workspaceId: string;
  containerId: string;
  profile: string;
  state: 'creating' | 'ready' | 'executing' | 'stopping' | 'stopped' | 'destroyed';
  createdAt: Date;
  destroyedAt?: Date;
}

export interface CreateSandboxParams {
  workspaceId: string;
  projectId: string;
  taskId: string;
  profile?: string;
}

export interface ExecParams {
  command: string[];
  timeoutMs?: number;
  workDir?: string;
}

export class SandboxManager {
  private readonly sandboxes = new Map<string, Sandbox>();
  private readonly workspaceManager: WorkspaceManager;
  private readonly containerProvider: ContainerProvider;

  constructor(workspaceRoot: string) {
    this.workspaceManager = new WorkspaceManager(workspaceRoot);
    this.containerProvider = new ContainerProvider();
  }

  async initialize(): Promise<void> {
    await this.workspaceManager.initialize();
  }

  async createSandbox(params: CreateSandboxParams): Promise<Sandbox> {
    const sandboxId = `sandbox-${randomBytes(8).toString('hex')}`;
    const profileId = params.profile ?? 'default';
    const profile = getProfile(profileId);

    // Create sandbox record
    const sandbox: Sandbox = {
      id: sandboxId,
      workspaceId: params.workspaceId,
      containerId: '',
      profile: profileId,
      state: 'creating',
      createdAt: new Date(),
    };

    this.sandboxes.set(sandboxId, sandbox);

    try {
      // Container will be created with workspace mount
      // For now, just track the sandbox
      sandbox.state = 'ready';
      return sandbox;
    } catch (err) {
      sandbox.state = 'destroyed';
      throw err;
    }
  }

  async startSandbox(sandboxId: string, workspace: ExecutionWorkspace): Promise<Sandbox> {
    const sandbox = this.sandboxes.get(sandboxId);
    if (!sandbox) {
      throw new Error(`Sandbox ${sandboxId} not found`);
    }

    const profile = getProfile(sandbox.profile);

    // Build ownership labels
    const labels: Record<string, string> = {
      'botconnector.sandbox': 'true',
      'botconnector.sandbox.id': sandboxId,
      'botconnector.sandbox.workspace_id': workspace.id,
      'botconnector.sandbox.project_id': workspace.projectId,
      'botconnector.sandbox.task_id': workspace.taskId,
    };

    // Create container
    const container = await this.containerProvider.create({
      image: profile.image,
      command: ['sleep', 'infinity'],
      args: [],
      env: {},
      workspaceMount: workspace.worktreePath,
      workingDir: '/workspace',
      cpuLimit: profile.cpuLimit,
      memoryLimit: profile.memoryLimit,
      pidsLimit: profile.pidsLimit,
      networkDisabled: profile.networkDisabled,
      readOnlyRootfs: profile.readOnlyRootfs,
      timeoutMs: profile.timeoutMs,
    }, labels);

    sandbox.containerId = container.id;
    sandbox.state = 'ready';

    return sandbox;
  }

  async exec(sandboxId: string, params: ExecParams): Promise<ExecResult> {
    const sandbox = this.sandboxes.get(sandboxId);
    if (!sandbox) {
      throw new Error(`Sandbox ${sandboxId} not found`);
    }

    if (sandbox.state !== 'ready') {
      throw new Error(`Sandbox ${sandboxId} is not ready (state: ${sandbox.state})`);
    }

    // Validate workDir is workspace-relative (defense in depth)
    const workDir = params.workDir ?? '/workspace';
    if (workDir.includes('..')) {
      throw new Error(`Path traversal in workDir: ${workDir}`);
    }
    if (workDir.startsWith('/') && !workDir.startsWith('/workspace')) {
      throw new Error(`workDir must be within /workspace: ${workDir}`);
    }

    const profile = getProfile(sandbox.profile);
    const timeoutMs = Math.min(params.timeoutMs ?? profile.timeoutMs, profile.timeoutMs);

    sandbox.state = 'executing';

    try {
      const result = await this.containerProvider.exec(sandbox.containerId, params.command, {
        timeoutMs,
        maxOutputBytes: profile.maxOutputBytes,
        workDir: params.workDir ?? '/workspace',
      });
      return result;
    } finally {
      sandbox.state = 'ready';
    }
  }

  async stopSandbox(sandboxId: string): Promise<void> {
    const sandbox = this.sandboxes.get(sandboxId);
    if (!sandbox) {
      return; // Idempotent
    }

    sandbox.state = 'stopping';

    if (sandbox.containerId) {
      await this.containerProvider.stop(sandbox.containerId);
      await this.containerProvider.destroy(sandbox.containerId);
    }

    sandbox.state = 'stopped';
    sandbox.destroyedAt = new Date();
  }

  async destroySandbox(sandboxId: string): Promise<void> {
    const sandbox = this.sandboxes.get(sandboxId);
    if (!sandbox) {
      return; // Idempotent
    }

    sandbox.state = 'stopping';

    if (sandbox.containerId) {
      await this.containerProvider.destroy(sandbox.containerId);
    }

    sandbox.state = 'destroyed';
    sandbox.destroyedAt = new Date();
    this.sandboxes.delete(sandboxId);
  }

  async getSandbox(sandboxId: string): Promise<Sandbox | undefined> {
    return this.sandboxes.get(sandboxId);
  }

  async listSandboxes(): Promise<Sandbox[]> {
    return Array.from(this.sandboxes.values());
  }

  async reconcile(): Promise<{ destroyed: number; kept: number }> {
    const ownedContainers = await this.containerProvider.listOwned({
      'botconnector.sandbox': 'true',
    });

    let destroyed = 0;
    let kept = 0;

    for (const container of ownedContainers) {
      const sandboxId = container.labels['botconnector.sandbox.id'];
      if (!sandboxId) {
        continue;
      }

      const sandbox = this.sandboxes.get(sandboxId);
      if (!sandbox || sandbox.state === 'destroyed') {
        // Orphaned container - destroy it
        await this.containerProvider.destroy(container.id);
        destroyed++;
      } else {
        kept++;
      }
    }

    return { destroyed, kept };
  }
}
