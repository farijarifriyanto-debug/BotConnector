import { describe, it, beforeAll, afterAll, expect } from 'vitest';
import { execFile } from 'node:child_process';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { randomBytes } from 'node:crypto';
import { createSandboxManager, type SandboxManagerApp } from '../src/index.js';

const execFileAsync = promisify(execFile);

let app: SandboxManagerApp;
let fixtureRepoPath: string;
let fixtureWorktreePath: string;

const WORKSPACE_ROOT = '/tmp/botconnector-phase6-test';

beforeAll(async () => {
  // Create workspace root
  await mkdir(WORKSPACE_ROOT, { recursive: true });

  // Create test fixture git repository
  fixtureRepoPath = join(WORKSPACE_ROOT, 'fixture-repo');
  await mkdir(fixtureRepoPath, { recursive: true });

  await execFileAsync('git', ['init'], { cwd: fixtureRepoPath });
  await execFileAsync('git', ['config', 'user.email', 'test@test.com'], { cwd: fixtureRepoPath });
  await execFileAsync('git', ['config', 'user.name', 'Test'], { cwd: fixtureRepoPath });

  // Create initial commit
  await writeFile(join(fixtureRepoPath, 'README.md'), '# Test Repository\n');
  await mkdir(join(fixtureRepoPath, 'src'), { recursive: true });
  await writeFile(join(fixtureRepoPath, 'src/index.ts'), 'console.log("hello");\n');
  await execFileAsync('git', ['add', '.'], { cwd: fixtureRepoPath });
  await execFileAsync('git', ['commit', '-m', 'Initial commit'], { cwd: fixtureRepoPath });

  // Create sandbox manager
  app = await createSandboxManager({
    workspaceRoot: join(WORKSPACE_ROOT, 'workspaces'),
    port: 0,
    host: '127.0.0.1',
  });

  await app.start();
});

afterAll(async () => {
  await app?.stop();

  // Cleanup fixture repo
  try {
    await execFileAsync('rm', ['-rf', WORKSPACE_ROOT]);
  } catch {
    // Ignore cleanup errors
  }
});

describe('Phase 6: Git Workspace & Sandbox', () => {
  describe('Workspace Creation', () => {
    it('creates isolated workspace from fixture repo', async () => {
      // Get base commit
      const { stdout: baseCommit } = await execFileAsync('git', ['rev-parse', 'HEAD'], {
        cwd: fixtureRepoPath,
      });

      const workspace = await app.workspaceManager.create({
        id: `test-ws-${randomBytes(4).toString('hex')}`,
        projectId: 'test-project',
        taskId: 'test-task',
        repoPath: fixtureRepoPath,
        baseCommit: baseCommit.trim(),
      });

      expect(workspace).toBeDefined();
      expect(workspace.baseCommit).toBe(baseCommit.trim());
      expect(workspace.worktreePath).toContain(WORKSPACE_ROOT);

      fixtureWorktreePath = workspace.worktreePath;
    });

    it('workspace has correct files', async () => {
      const readme = await readFile(join(fixtureWorktreePath, 'README.md'), 'utf-8');
      expect(readme).toContain('Test Repository');

      const index = await readFile(join(fixtureWorktreePath, 'src/index.ts'), 'utf-8');
      expect(index).toContain('console.log("hello")');
    });

    it('workspace modifications do not affect canonical repo', async () => {
      // Modify workspace
      await writeFile(join(fixtureWorktreePath, 'README.md'), '# Modified\n');

      // Check canonical repo is unchanged
      const canonicalReadme = await readFile(join(fixtureRepoPath, 'README.md'), 'utf-8');
      expect(canonicalReadme).toContain('Test Repository');

      // Check workspace has modification
      const workspaceReadme = await readFile(join(fixtureWorktreePath, 'README.md'), 'utf-8');
      expect(workspaceReadme).toContain('Modified');
    });

    it('workspace shows git diff', async () => {
      const diff = await app.workspaceManager.diff(
        fixtureWorktreePath.split('/').pop()!,
      );
      expect(diff).toContain('Modified');
    });
  });

  describe('Sandbox Creation', () => {
    it('creates sandbox with correct security profile', async () => {
      const sandbox = await app.sandboxManager.createSandbox({
        workspaceId: 'test-workspace',
        projectId: 'test-project',
        taskId: 'test-task',
        profile: 'default',
      });

      expect(sandbox).toBeDefined();
      expect(sandbox.state).toBe('ready');
      expect(sandbox.profile).toBe('default');
    });

    it('sandbox profile has security restrictions', async () => {
      const profiles = await import('../src/sandbox/profiles.js');
      const profile = profiles.getProfile('default');

      expect(profile.networkDisabled).toBe(true);
      expect(profile.readOnlyRootfs).toBe(true);
      expect(profile.pidsLimit).toBeLessThanOrEqual(64);
      expect(profile.cpuLimit).toBeDefined();
      expect(profile.memoryLimit).toBeDefined();
    });
  });

  describe('Git Isolation', () => {
    it('two workspaces from same base are independent', async () => {
      const { stdout: baseCommit } = await execFileAsync('git', ['rev-parse', 'HEAD'], {
        cwd: fixtureRepoPath,
      });

      const ws1 = await app.workspaceManager.create({
        id: `test-ws1-${randomBytes(4).toString('hex')}`,
        projectId: 'test-project',
        taskId: 'task-1',
        repoPath: fixtureRepoPath,
        baseCommit: baseCommit.trim(),
      });

      const ws2 = await app.workspaceManager.create({
        id: `test-ws2-${randomBytes(4).toString('hex')}`,
        projectId: 'test-project',
        taskId: 'task-2',
        repoPath: fixtureRepoPath,
        baseCommit: baseCommit.trim(),
      });

      // Modify ws1
      await writeFile(join(ws1.worktreePath, 'README.md'), '# Workspace 1\n');

      // ws2 should be unchanged
      const ws2Readme = await readFile(join(ws2.worktreePath, 'README.md'), 'utf-8');
      expect(ws2Readme).toContain('Test Repository');

      // Canonical repo should be unchanged
      const canonicalReadme = await readFile(join(fixtureRepoPath, 'README.md'), 'utf-8');
      expect(canonicalReadme).toContain('Test Repository');

      // Cleanup
      await app.workspaceManager.destroy(ws1.id);
      await app.workspaceManager.destroy(ws2.id);
    });
  });

  describe('Workspace Cleanup', () => {
    it('destroys workspace idempotently', async () => {
      const { stdout: baseCommit } = await execFileAsync('git', ['rev-parse', 'HEAD'], {
        cwd: fixtureRepoPath,
      });

      const ws = await app.workspaceManager.create({
        id: `test-cleanup-${randomBytes(4).toString('hex')}`,
        projectId: 'test-project',
        taskId: 'cleanup-task',
        repoPath: fixtureRepoPath,
        baseCommit: baseCommit.trim(),
      });

      // Destroy once
      await app.workspaceManager.destroy(ws.id);

      // Destroy again (idempotent)
      await app.workspaceManager.destroy(ws.id);

      // Verify workspace is gone
      const exists = await app.workspaceManager.exists(ws.id);
      expect(exists).toBe(false);
    });

    it('rejects path traversal', async () => {
      // Try to destroy a path outside workspace root
      await expect(
        app.workspaceManager.destroy('../../etc/passwd'),
      ).rejects.toThrow('not within workspace root');
    });
  });

  describe('Pre-existing Container Safety', () => {
    it('reconciliation ignores unrelated containers', async () => {
      const result = await app.sandboxManager.reconcile();

      // Should not destroy any pre-existing containers
      expect(result.destroyed).toBe(0);
    });
  });
});
