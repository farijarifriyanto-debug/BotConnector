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
  networkName?: string;
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
    let containerId = '';
    try {
      const { stdout } = await execFileAsync('sudo', ['docker', 'create', ...args]);
      containerId = stdout.trim();

      // Start the container
      await execFileAsync('sudo', ['docker', 'start', containerId]);

      // Get container info
      return await this.inspect(containerId);
    } catch (err) {
      if (containerId) {
        await this.destroy(containerId);
      }
      throw err;
    }
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
    } catch (err: unknown) {
      const stderr = (err as { stderr?: string }).stderr ?? '';
      if (/no such container|not found/i.test(stderr)) {
        return;
      }
      throw err;
    }
  }

  async createNetwork(name: string, projectId: string): Promise<void> {
    const inspectNetwork = async (): Promise<Record<string, string> | undefined> => {
      try {
        const { stdout } = await execFileAsync('sudo', [
          'docker', 'network', 'inspect', '--format', '{{json .Labels}}', name,
        ]);
        return JSON.parse(stdout.trim()) as Record<string, string>;
      } catch {
        return undefined;
      }
    };

    const existingLabels = await inspectNetwork();
    if (existingLabels) {
      if (existingLabels['botconnector.preview.network'] !== 'true' ||
          existingLabels['botconnector.preview.project_id'] !== projectId) {
        throw new Error(`Network ${name} is not owned by this project`);
      }
      return;
    }

    try {
      await execFileAsync('sudo', [
        'docker', 'network', 'create', '--driver', 'bridge',
        '--label', 'botconnector.preview.network=true',
        '--label', `botconnector.preview.project_id=${projectId}`,
        name,
      ]);
    } catch (err: unknown) {
      const stderr = (err as { stderr?: string }).stderr ?? '';
      if (stderr.includes('already exists')) {
        const labels = await inspectNetwork();
        if (labels?.['botconnector.preview.network'] === 'true' &&
            labels['botconnector.preview.project_id'] === projectId) {
          return;
        }
        throw new Error(`Network ${name} is not owned by this project`);
      }
      throw err;
    }
  }

  async removeNetwork(name: string, projectId: string): Promise<void> {
    try {
      const { stdout } = await execFileAsync('sudo', [
        'docker', 'network', 'inspect', '--format', '{{json .Labels}}', name,
      ]);
      const labels = JSON.parse(stdout.trim()) as Record<string, string>;
      if (labels['botconnector.preview.network'] !== 'true' ||
          labels['botconnector.preview.project_id'] !== projectId) {
        return;
      }
      await execFileAsync('sudo', ['docker', 'network', 'rm', name]);
    } catch (err: unknown) {
      const stderr = (err as { stderr?: string }).stderr ?? '';
      if (/no such network|not found/i.test(stderr)) {
        return;
      }
      throw err;
    }
  }

  async getContainerIp(containerId: string, networkName: string): Promise<string | undefined> {
    try {
      const { stdout } = await execFileAsync('sudo', [
        'docker', 'inspect', '--format',
        `{{(index .NetworkSettings.Networks "${networkName}").IPAddress}}`,
        containerId,
      ]);
      const ip = stdout.trim();
      return ip || undefined;
    } catch {
      return undefined;
    }
  }

  async listOwned(labels: Record<string, string>): Promise<ContainerInfo[]> {
    const filterArgs = Object.entries(labels)
      .flatMap(([k, v]) => [`--filter=label=${k}=${v}`]);

    const { stdout } = await execFileAsync('sudo', [
      'docker', 'ps', '-a', '--format', '{{.ID}}', ...filterArgs,
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
    if (spec.networkName) {
      args.push('--network', spec.networkName);
    } else if (spec.networkDisabled !== false) {
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
      args.push('--tmpfs', '/tmp/preview-exec:rw,exec,nosuid,size=256m');
    }

    // Workspace mount (read-only for preview containers, read-write for sandbox exec)
    const mountMode = spec.networkDisabled === false ? 'ro' : 'rw';
    args.push('--volume', `${spec.workspaceMount}:/workspace:${mountMode}`);

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
