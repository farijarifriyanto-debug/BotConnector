export interface SandboxManagerClientConfig {
  url: string;
  secret: string;
}

export interface WorkspaceInfo {
  id: string;
  projectId: string;
  taskId: string;
  repoPath: string;
  worktreePath: string;
  baseCommit: string;
  createdAt: string;
}

export interface SandboxInfo {
  id: string;
  workspaceId: string;
  containerId: string;
  profile: string;
  state: string;
  createdAt: string;
}

export interface ExecResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  durationMs: number;
}

export class SandboxManagerClient {
  private readonly config: SandboxManagerClientConfig;

  constructor(config: SandboxManagerClientConfig) {
    this.config = config;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const url = `${this.config.url}${path}`;
    const headers: Record<string, string> = {
      'Authorization': `Bearer ${this.config.secret}`,
      'Content-Type': 'application/json',
    };

    const response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      const error = await response.json() as { error?: { code: string; message: string } };
      throw new Error(error.error?.message ?? `HTTP ${response.status}`);
    }

    const result = await response.json() as { data: T };
    return result.data;
  }

  // Workspace operations
  async createWorkspace(params: {
    projectId: string;
    taskId: string;
    repoPath: string;
    baseCommit: string;
  }): Promise<WorkspaceInfo> {
    return this.request<WorkspaceInfo>('POST', '/internal/v1/workspaces', params);
  }

  async getWorkspace(workspaceId: string): Promise<WorkspaceInfo> {
    return this.request<WorkspaceInfo>('GET', `/internal/v1/workspaces/${workspaceId}`);
  }

  async destroyWorkspace(workspaceId: string): Promise<void> {
    await this.request<{ destroyed: boolean }>('DELETE', `/internal/v1/workspaces/${workspaceId}`);
  }

  async getWorkspaceDiff(workspaceId: string): Promise<string> {
    const result = await this.request<{ diff: string }>('GET', `/internal/v1/workspaces/${workspaceId}/diff`);
    return result.diff;
  }

  // Sandbox operations
  async createSandbox(params: {
    workspaceId: string;
    projectId: string;
    taskId: string;
    profile?: string;
  }): Promise<SandboxInfo> {
    return this.request<SandboxInfo>('POST', '/internal/v1/sandboxes', params);
  }

  async getSandbox(sandboxId: string): Promise<SandboxInfo> {
    return this.request<SandboxInfo>('GET', `/internal/v1/sandboxes/${sandboxId}`);
  }

  async exec(sandboxId: string, params: {
    command: string[];
    timeoutMs?: number;
    workDir?: string;
  }): Promise<ExecResult> {
    return this.request<ExecResult>('POST', `/internal/v1/sandboxes/${sandboxId}/exec`, {
      command: params.command,
      timeout_ms: params.timeoutMs,
      work_dir: params.workDir,
    });
  }

  async stopSandbox(sandboxId: string): Promise<void> {
    await this.request<{ stopped: boolean }>('POST', `/internal/v1/sandboxes/${sandboxId}/stop`);
  }

  async destroySandbox(sandboxId: string): Promise<void> {
    await this.request<{ destroyed: boolean }>('DELETE', `/internal/v1/sandboxes/${sandboxId}`);
  }

  // Health check
  async health(): Promise<boolean> {
    try {
      await fetch(`${this.config.url}/health`);
      return true;
    } catch {
      return false;
    }
  }
}
