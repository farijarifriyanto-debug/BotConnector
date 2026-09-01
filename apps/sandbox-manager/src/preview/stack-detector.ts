import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

export type StackType = 'node' | 'python' | 'go' | 'rust' | 'static' | 'unknown';

export interface DetectedStack {
  type: StackType;
  image: string;
  command: string[];
  installCmd?: string;
}

const STACK_DETECTORS: Array<{
  marker: string;
  stack: StackType;
  image: string;
  command: string[];
  installCmd?: string;
}> = [
  {
    marker: 'package.json',
    stack: 'node',
    image: 'node:20-slim',
    command: ['sh', '-c', 'rm -rf /tmp/preview-exec/node-workspace && mkdir -p /tmp/preview-exec/node-workspace && cp -a /workspace/. /tmp/preview-exec/node-workspace/ && cd /tmp/preview-exec/node-workspace && npm install && npm run dev'],
    installCmd: 'npm install',
  },
  {
    marker: 'go.mod',
    stack: 'go',
    image: 'golang:1.22-slim',
    command: ['sh', '-c', 'rm -rf /tmp/preview-exec/go-workspace && mkdir -p /tmp/preview-exec/go-workspace /tmp/preview-exec/go-cache /tmp/preview-exec/go-mod /tmp/preview-exec/go-path && cp -a /workspace/. /tmp/preview-exec/go-workspace/ && cd /tmp/preview-exec/go-workspace && TMPDIR=/tmp/preview-exec GOCACHE=/tmp/preview-exec/go-cache GOMODCACHE=/tmp/preview-exec/go-mod GOPATH=/tmp/preview-exec/go-path go mod download && TMPDIR=/tmp/preview-exec GOCACHE=/tmp/preview-exec/go-cache GOMODCACHE=/tmp/preview-exec/go-mod GOPATH=/tmp/preview-exec/go-path go run .'],
    installCmd: 'go mod download',
  },
  {
    marker: 'requirements.txt',
    stack: 'python',
    image: 'python:3.12-slim',
    command: ['sh', '-c', 'rm -rf /tmp/preview-python-deps && pip install --target /tmp/preview-python-deps -r /workspace/requirements.txt && PYTHONPATH=/tmp/preview-python-deps python -m http.server "$PORT" --directory /workspace'],
  },
  {
    marker: 'pyproject.toml',
    stack: 'python',
    image: 'python:3.12-slim',
    command: ['sh', '-c', 'rm -rf /tmp/preview-python-deps && pip install --target /tmp/preview-python-deps /workspace && PYTHONPATH=/tmp/preview-python-deps python -m http.server "$PORT" --directory /workspace'],
  },
  {
    marker: 'Cargo.toml',
    stack: 'rust',
    image: 'rust:slim',
    command: ['sh', '-c', 'rm -rf /tmp/preview-exec/rust-workspace && mkdir -p /tmp/preview-exec/rust-workspace /tmp/preview-exec/rust-target && cp -a /workspace/. /tmp/preview-exec/rust-workspace/ && cd /tmp/preview-exec/rust-workspace && TMPDIR=/tmp/preview-exec CARGO_HOME=/tmp/preview-exec/cargo CARGO_TARGET_DIR=/tmp/preview-exec/rust-target cargo run'],
  },
  {
    marker: 'index.html',
    stack: 'static',
    image: 'python:3.12-slim',
    command: ['sh', '-c', 'exec python3 -m http.server "$PORT" --directory /workspace'],
  },
];

export async function detectStack(workspacePath: string): Promise<DetectedStack> {
  for (const detector of STACK_DETECTORS) {
    try {
      await readFile(join(workspacePath, detector.marker));
      // If marker file exists, this is likely the stack
      return {
        type: detector.stack,
        image: detector.image,
        command: detector.command,
        installCmd: detector.installCmd,
      };
    } catch {
      // File doesn't exist, try next
    }
  }

  // Fallback: static file server using PORT env var
  return {
    type: 'static',
    image: 'python:3.12-slim',
    command: ['sh', '-c', 'exec python3 -m http.server "$PORT" --directory /workspace'],
  };
}
