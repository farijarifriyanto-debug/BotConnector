export interface SandboxManagerConfig {
  port: number;
  host: string;
  secret: string;
  workspaceRoot: string;
  sourceRepoRoot: string;
  defaultImage: string;
  defaultTimeoutMs: number;
  maxTimeoutMs: number;
  maxOutputBytes: number;
  previewPort: number;
}

export function loadConfig(overrides?: Partial<SandboxManagerConfig>): SandboxManagerConfig {
  // Merge overrides first to allow test overrides to satisfy required fields
  const merged = {
    port: parseInt(process.env.SANDBOX_MANAGER_PORT ?? '0', 10),
    host: process.env.SANDBOX_MANAGER_HOST ?? '127.0.0.1',
    secret: process.env.SANDBOX_MANAGER_SECRET,
    workspaceRoot: process.env.EXECUTION_WORKSPACE_ROOT ?? '/tmp/botconnector-workspaces',
    sourceRepoRoot: process.env.SOURCE_REPO_ROOT,
    defaultImage: process.env.SANDBOX_DEFAULT_IMAGE ?? 'python:3.12-slim',
    defaultTimeoutMs: parseInt(process.env.SANDBOX_DEFAULT_TIMEOUT_MS ?? '30000', 10),
    maxTimeoutMs: parseInt(process.env.SANDBOX_MAX_TIMEOUT_MS ?? '300000', 10),
    maxOutputBytes: parseInt(process.env.SANDBOX_MAX_OUTPUT_BYTES ?? '1048576', 10),
    previewPort: parseInt(process.env.SANDBOX_PREVIEW_PORT ?? '4100', 10),
    ...overrides,
  };

  // D4: Fail-closed — secret must be explicitly provided (env var or override)
  const secret = merged.secret;
  if (!secret) {
    throw new Error(
      'SANDBOX_MANAGER_SECRET must be set. ' +
      'Sandbox Manager refuses to start without an explicit secret.',
    );
  }

  if (!merged.sourceRepoRoot) {
    throw new Error(
      'SOURCE_REPO_ROOT must be set. ' +
      'Sandbox Manager refuses to accept caller-selected repository paths without an explicit root.',
    );
  }

  return { ...merged, secret, sourceRepoRoot: merged.sourceRepoRoot };
}
