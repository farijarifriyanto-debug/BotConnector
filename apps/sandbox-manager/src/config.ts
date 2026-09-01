import { randomBytes } from 'node:crypto';

export interface SandboxManagerConfig {
  port: number;
  host: string;
  secret: string;
  workspaceRoot: string;
  defaultImage: string;
  defaultTimeoutMs: number;
  maxTimeoutMs: number;
  maxOutputBytes: number;
}

function requireEnv(name: string, fallback?: string): string {
  const value = process.env[name] ?? fallback;
  if (value === undefined) {
    throw new Error(`Required environment variable ${name} is not set`);
  }
  return value;
}

export function loadConfig(overrides?: Partial<SandboxManagerConfig>): SandboxManagerConfig {
  return {
    port: parseInt(requireEnv('SANDBOX_MANAGER_PORT', '0'), 10),
    host: requireEnv('SANDBOX_MANAGER_HOST', '127.0.0.1'),
    secret: requireEnv('SANDBOX_MANAGER_SECRET', randomBytes(32).toString('hex')),
    workspaceRoot: requireEnv('EXECUTION_WORKSPACE_ROOT', '/tmp/botconnector-workspaces'),
    defaultImage: requireEnv('SANDBOX_DEFAULT_IMAGE', 'python:3.12-slim'),
    defaultTimeoutMs: parseInt(requireEnv('SANDBOX_DEFAULT_TIMEOUT_MS', '30000'), 10),
    maxTimeoutMs: parseInt(requireEnv('SANDBOX_MAX_TIMEOUT_MS', '300000'), 10),
    maxOutputBytes: parseInt(requireEnv('SANDBOX_MAX_OUTPUT_BYTES', '1048576'), 10),
    ...overrides,
  };
}
