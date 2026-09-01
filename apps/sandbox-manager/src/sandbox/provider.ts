import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

export interface ContainerSpec {
  image: string;
  command: string[];
  args: string[];
  env: Record<string, string>;
  workspaceMount: string;
  workingDir: string;
  cpuLimit?: string;
  memoryLimit?: string;
  pidsLimit?: number;
  networkDisabled?: boolean;
  readOnlyRootfs?: boolean;
  timeoutMs?: number;
}

export interface ContainerInfo {
  id: string;
  name: string;
  state: string;
  image: string;
  labels: Record<string, string>;
  createdAt: string;
}

export interface ExecResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  durationMs: number;
}

export class ContainerProvider {
  private readonly ownershipPrefix = 'botconnector.sandbox';

  async create(spec: ContainerSpec, labels: Record<string, string>): Promise<ContainerInfo> {
    const args = this.buildCreateArgs(spec, labels);
    const { stdout } = await execFileAsync('sudo', ['docker', 'create', ...args]);
    const containerId = stdout.trim();

    // Start the container
    await execFileAsync('sudo', ['docker', 'start', containerId]);

    // Get container info
    return this.inspect(containerId);
  }

  async inspect(containerId: string): Promise<ContainerInfo> {
    const { stdout } = await execFileAsync('sudo', [
      'docker', 'inspect', '--format',
      '{{.Id}}\t{{.Name}}\t{{.State.Status}}\t{{.Config.Image}}\t{{json .Config.Labels}}\t{{.Created}}',
      containerId,
    ]);

    const [id, name, state, image, labelsJson, createdAt] = stdout.trim().split('\t');
    const labels = JSON.parse(labelsJson) as Record<string, string>;

    return { id, name, state, image, labels, createdAt };
  }

  async exec(containerId: string, command: string[], options: {
    timeoutMs?: number;
    maxOutputBytes?: number;
    workDir?: string;
  } = {}): Promise<ExecResult> {
    const startTime = Date.now();
    const timeout = options.timeoutMs ?? 30000;
    const maxOutput = options.maxOutputBytes ?? 1048576;

    const execArgs = ['docker', 'exec'];
    if (options.workDir) {
      execArgs.push('-w', options.workDir);
    }
    execArgs.push(containerId, ...command);

    try {
      const { stdout, stderr } = await execFileAsync('sudo', execArgs, {
        timeout,
        maxBuffer: maxOutput,
      });

      return {
        exitCode: 0,
        stdout,
        stderr,
        timedOut: false,
        durationMs: Date.now() - startTime,
      };
    } catch (err: unknown) {
      const durationMs = Date.now() - startTime;
      if (err && typeof err === 'object' && 'killed' in err && (err as { killed: boolean }).killed) {
        return {
          exitCode: -1,
          stdout: '',
          stderr: 'Command timed out',
          timedOut: true,
          durationMs,
        };
      }

      const execErr = err as { code?: number; stdout?: string; stderr?: string };
      return {
        exitCode: execErr.code ?? -1,
        stdout: execErr.stdout ?? '',
        stderr: execErr.stderr ?? 'Unknown error',
        timedOut: false,
        durationMs,
      };
    }
  }

  async stop(containerId: string, timeoutSeconds = 10): Promise<void> {
    try {
      await execFileAsync('sudo', ['docker', 'stop', '-t', String(timeoutSeconds), containerId]);
    } catch {
      // Container may already be stopped
    }
  }

  async destroy(containerId: string): Promise<void> {
    try {
      await execFileAsync('sudo', ['docker', 'rm', '-f', containerId]);
    } catch {
      // Container may already be removed
    }
  }

  async listOwned(labels: Record<string, string>): Promise<ContainerInfo[]> {
    const filterArgs = Object.entries(labels)
      .map(([k, v]) => `--filter=label=${k}=${v}`)
      .join(' ');

    const { stdout } = await execFileAsync('sudo', [
      'docker', 'ps', '-a', '--format', '{{.ID}}', ...filterArgs.split(' '),
    ]);

    const containerIds = stdout.trim().split('\n').filter(Boolean);
    const containers: ContainerInfo[] = [];

    for (const id of containerIds) {
      try {
        const info = await this.inspect(id);
        containers.push(info);
      } catch {
        // Container may have been removed between list and inspect
      }
    }

    return containers;
  }

  private buildCreateArgs(spec: ContainerSpec, labels: Record<string, string>): string[] {
    const args: string[] = [];

    // Name
    args.push('--name', `botconnector-sandbox-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);

    // Security
    args.push('--security-opt', 'no-new-privileges:true');
    args.push('--cap-drop', 'ALL');
    args.push('--privileged=false');

    // Network
    if (spec.networkDisabled !== false) {
      args.push('--network', 'none');
    }

    // Resource limits
    if (spec.cpuLimit) {
      args.push('--cpus', spec.cpuLimit);
    }
    if (spec.memoryLimit) {
      args.push('--memory', spec.memoryLimit);
    }
    if (spec.pidsLimit) {
      args.push('--pids-limit', String(spec.pidsLimit));
    }

    // Read-only root filesystem
    if (spec.readOnlyRootfs) {
      args.push('--read-only');
      // Add tmpfs for writable locations
      args.push('--tmpfs', '/tmp:rw,noexec,nosuid,size=64m');
    }

    // Workspace mount
    args.push('--volume', `${spec.workspaceMount}:/workspace:rw`);

    // Environment
    for (const [key, value] of Object.entries(spec.env)) {
      args.push('-e', `${key}=${value}`);
    }

    // Working directory
    args.push('-w', spec.workingDir || '/workspace');

    // Labels
    for (const [key, value] of Object.entries(labels)) {
      args.push('--label', `${key}=${value}`);
    }

    // Image and command
    args.push(spec.image);
    args.push(...spec.command, ...spec.args);

    return args;
  }
}
