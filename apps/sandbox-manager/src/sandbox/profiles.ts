export interface SandboxProfile {
  id: string;
  name: string;
  image: string;
  cpuLimit: string;
  memoryLimit: string;
  pidsLimit: number;
  networkDisabled: boolean;
  readOnlyRootfs: boolean;
  timeoutMs: number;
  maxOutputBytes: number;
}

export const SANDBOX_PROFILES: Record<string, SandboxProfile> = {
  'default': {
    id: 'default',
    name: 'Default Sandbox',
    image: 'python:3.12-slim',
    cpuLimit: '0.5',
    memoryLimit: '256m',
    pidsLimit: 64,
    networkDisabled: true,
    readOnlyRootfs: true,
    timeoutMs: 30000,
    maxOutputBytes: 1048576,
  },
  'lightweight': {
    id: 'lightweight',
    name: 'Lightweight Sandbox',
    image: 'python:3.12-slim',
    cpuLimit: '0.25',
    memoryLimit: '128m',
    pidsLimit: 32,
    networkDisabled: true,
    readOnlyRootfs: true,
    timeoutMs: 15000,
    maxOutputBytes: 524288,
  },
  'preview': {
    id: 'preview',
    name: 'Preview Runtime',
    image: 'python:3.12-slim',
    cpuLimit: '1.0',
    memoryLimit: '512m',
    pidsLimit: 128,
    networkDisabled: false,
    readOnlyRootfs: true,
    timeoutMs: 300000,
    maxOutputBytes: 2097152,
  },
};

export function getProfile(profileId: string): SandboxProfile {
  const profile = SANDBOX_PROFILES[profileId];
  if (!profile) {
    throw new Error(`Unknown sandbox profile: ${profileId}`);
  }
  return profile;
}

export function listProfiles(): SandboxProfile[] {
  return Object.values(SANDBOX_PROFILES);
}
