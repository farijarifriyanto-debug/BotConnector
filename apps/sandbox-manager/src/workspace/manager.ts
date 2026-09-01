import { execFile } from 'node:child_process';
import { mkdir, rm, readdir, stat } from 'node:fs/promises';
import { join, resolve, isAbsolute, relative } from 'node:path';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

export interface ExecutionWorkspace {
  id: string;
  projectId: string;
  taskId: string;
  repoPath: string;
  worktreePath: string;
  baseCommit: string;
  createdAt: Date;
}

export interface CreateWorkspaceParams {
  id: string;
  projectId: string;
  taskId: string;
  repoPath: string;
  baseCommit: string;
}

export class WorkspaceManager {
  constructor(private readonly workspaceRoot: string) {}

  async initialize(): Promise<void> {
    await mkdir(this.workspaceRoot, { recursive: true });
  }

  async create(params: CreateWorkspaceParams): Promise<ExecutionWorkspace> {
    const worktreePath = join(this.workspaceRoot, params.id);

    // Validate worktree destination is within workspace root
    this.validateWithinRoot(worktreePath);
    // Validate workspace ID has no traversal components
    if (params.id.includes('..') || isAbsolute(params.id)) {
      throw new Error(`Invalid workspace ID: ${params.id}`);
    }

    // Ensure workspace root exists
    await mkdir(this.workspaceRoot, { recursive: true });

    // Resolve full commit SHA
    const fullCommit = await this.resolveCommit(params.repoPath, params.baseCommit);

    // Create worktree
    await execFileAsync('git', [
      'worktree', 'add', '--detach', worktreePath, fullCommit,
    ], { cwd: params.repoPath });

    return {
      id: params.id,
      projectId: params.projectId,
      taskId: params.taskId,
      repoPath: params.repoPath,
      worktreePath,
      baseCommit: fullCommit,
      createdAt: new Date(),
    };
  }

  async destroy(id: string): Promise<void> {
    const worktreePath = join(this.workspaceRoot, id);

    // Validate path is within workspace root
    if (!this.isWithinRoot(worktreePath)) {
      throw new Error(`Workspace path ${worktreePath} is not within workspace root`);
    }

    try {
      // Remove worktree directory
      await rm(worktreePath, { recursive: true, force: true });

      // Prune stale worktree metadata
      // Find the repo that owns this worktree by reading .git file
      const gitFile = join(worktreePath, '.git');
      try {
        const { stdout } = await execFileAsync('cat', [gitFile]);
        const repoPath = stdout.trim().replace(/^gitdir: /, '').replace(/\/\.git\/worktrees\/.*$/, '');
        await execFileAsync('git', ['worktree', 'prune'], { cwd: repoPath });
      } catch {
        // Git file may not exist if worktree was already removed
      }
    } catch (err: unknown) {
      // Idempotent: ignore if already removed
      if (err && typeof err === 'object' && 'code' in err && (err as { code: string }).code === 'ENOENT') {
        return;
      }
      throw err;
    }
  }

  async exists(id: string): Promise<boolean> {
    const worktreePath = join(this.workspaceRoot, id);
    try {
      await stat(worktreePath);
      return true;
    } catch {
      return false;
    }
  }

  async diff(id: string): Promise<string> {
    const worktreePath = join(this.workspaceRoot, id);
    this.validateWithinRoot(worktreePath);

    const { stdout } = await execFileAsync('git', ['diff'], { cwd: worktreePath });
    return stdout;
  }

  async status(id: string): Promise<string> {
    const worktreePath = join(this.workspaceRoot, id);
    this.validateWithinRoot(worktreePath);

    const { stdout } = await execFileAsync('git', ['status', '--porcelain'], { cwd: worktreePath });
    return stdout;
  }

  async list(): Promise<string[]> {
    try {
      const entries = await readdir(this.workspaceRoot);
      return entries;
    } catch {
      return [];
    }
  }

  private async resolveCommit(repoPath: string, ref: string): Promise<string> {
    const { stdout } = await execFileAsync('git', ['rev-parse', ref], { cwd: repoPath });
    return stdout.trim();
  }

  private validateWithinRoot(path: string): void {
    if (!this.isWithinRoot(path)) {
      throw new Error(`Path ${path} is not within workspace root`);
    }
  }

  private isWithinRoot(path: string): boolean {
    const resolved = resolve(path);
    const root = resolve(this.workspaceRoot);
    return resolved.startsWith(root + '/') || resolved === root;
  }
}
