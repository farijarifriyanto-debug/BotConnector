import { execFile } from 'node:child_process';
import { mkdir, rm, readdir, stat, readFile, writeFile, realpath } from 'node:fs/promises';
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
  private readonly workspaces = new Map<string, ExecutionWorkspace>();

  constructor(
    private readonly workspaceRoot: string,
    private readonly sourceRepoRoot: string,
  ) {}

  async initialize(): Promise<void> {
    await mkdir(this.workspaceRoot, { recursive: true });
    for (const entry of await readdir(this.workspaceRoot)) {
      if (!entry.endsWith('.workspace.json')) continue;
      try {
        const metadata = JSON.parse(await readFile(join(this.workspaceRoot, entry), 'utf8')) as {
          id: string;
          projectId: string;
          taskId: string;
          repoPath: string;
          worktreePath: string;
          baseCommit: string;
          createdAt: string;
        };
        if (!metadata.id || !metadata.projectId || !metadata.taskId ||
            !metadata.repoPath || !metadata.worktreePath || !metadata.baseCommit) {
          continue;
        }
        const root = await realpath(this.workspaceRoot);
        const worktreePath = await realpath(metadata.worktreePath);
        if (!(worktreePath.startsWith(root + '/') || worktreePath === root)) continue;
        const repoPath = await this.validateSourceRepo(metadata.repoPath);
        this.workspaces.set(metadata.id, { ...metadata, repoPath, worktreePath, createdAt: new Date(metadata.createdAt) });
      } catch {
        // Ignore incomplete metadata; reconciliation can remove stale resources.
      }
    }
  }

  async create(params: CreateWorkspaceParams): Promise<ExecutionWorkspace> {
    const worktreePath = join(this.workspaceRoot, params.id);

    // Validate worktree destination is within workspace root
    this.validateWithinRoot(worktreePath);
    // Validate workspace ID has no traversal components
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(params.id) || isAbsolute(params.id)) {
      throw new Error(`Invalid workspace ID: ${params.id}`);
    }

    // Ensure workspace root exists
    await mkdir(this.workspaceRoot, { recursive: true });

    // Resolve full commit SHA
    const repoPath = await this.validateSourceRepo(params.repoPath);
    const fullCommit = await this.resolveCommit(repoPath, params.baseCommit);

    // Create worktree
    await execFileAsync('git', [
      'worktree', 'add', '--detach', worktreePath, fullCommit,
    ], { cwd: repoPath });

    const workspace: ExecutionWorkspace = {
      id: params.id,
      projectId: params.projectId,
      taskId: params.taskId,
      repoPath,
      worktreePath,
      baseCommit: fullCommit,
      createdAt: new Date(),
    };
    try {
      await writeFile(this.metadataPath(workspace.id), JSON.stringify(workspace) + '\n', { mode: 0o600 });
    } catch (err) {
      const cleanupErrors: unknown[] = [];
      try {
        await rm(worktreePath, { recursive: true, force: true });
      } catch (cleanupErr) {
        cleanupErrors.push(cleanupErr);
      }
      try {
        await execFileAsync('git', ['worktree', 'prune'], { cwd: repoPath });
      } catch (cleanupErr) {
        cleanupErrors.push(cleanupErr);
      }
      if (cleanupErrors.length > 0) {
        throw new AggregateError([err, ...cleanupErrors], 'Workspace rollback failed');
      }
      throw err;
    }
    this.workspaces.set(workspace.id, workspace);
    return workspace;
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

      const workspace = this.workspaces.get(id);
      if (workspace?.repoPath) {
        try {
          await execFileAsync('git', ['worktree', 'prune'], { cwd: workspace.repoPath });
        } catch {
          // The source repository may already have been removed.
        }
      }
      await rm(this.metadataPath(id), { force: true });
      this.workspaces.delete(id);
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

  get(id: string): ExecutionWorkspace | undefined {
    return this.workspaces.get(id);
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

  getWorkspaceRoot(): string {
    return this.workspaceRoot;
  }

  private metadataPath(id: string): string {
    return join(this.workspaceRoot, `${id}.workspace.json`);
  }

  private async resolveCommit(repoPath: string, ref: string): Promise<string> {
    const { stdout } = await execFileAsync('git', ['rev-parse', ref], { cwd: repoPath });
    return stdout.trim();
  }

  private async validateSourceRepo(repoPath: string): Promise<string> {
    const root = await realpath(this.sourceRepoRoot);
    const resolvedRepo = await realpath(repoPath);
    if (!(resolvedRepo.startsWith(root + '/') || resolvedRepo === root)) {
      throw new Error(`Repository path ${repoPath} is not within the configured source repository root`);
    }
    return resolvedRepo;
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
