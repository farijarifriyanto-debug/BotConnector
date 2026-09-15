// POC 2: hardware detection beyond nvidia-smi (llmfit-inspired, dependency-free).
// Every probe is guarded: failure => null/[], never throws.
// Confidence is honest: 'estimated' (formula/probe) or 'override' (env-provided).
import os from 'node:os';
import fsp from 'node:fs/promises';
import { execFile } from 'node:child_process';

function run(bin, args, timeout = 5000) {
  return new Promise((resolve) => {
    execFile(bin, args, { timeout, windowsHide: true }, (err, stdout) => {
      if (err) return resolve(null);
      resolve(String(stdout || ''));
    });
  });
}

export async function detectNvidia() {
  const out = await run('nvidia-smi', ['--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits']);
  if (!out) return [];
  return out.trim().split(/\r?\n/).filter(Boolean).map((line) => {
    const [name, memoryMb, driver] = line.split(',').map((s) => s.trim());
    return { vendor: 'nvidia', name, memoryGb: +(Number(memoryMb) / 1024).toFixed(1), driver };
  });
}

export async function detectAmd() {
  // Presence + count via rocm-smi; VRAM parsing varies per version, so report
  // vramGb only when the meminfo query succeeds, else null (honest unknown).
  const ids = await run('rocm-smi', ['--showid']);
  if (!ids) return [];
  const count = (ids.match(/^\s*\d+\s*$/gm) || []).length || (ids.match(/GPU/g) || []).length || 1;
  const mem = await run('rocm-smi', ['--showmeminfo', 'vram', '--csv']);
  let vramGb = null;
  if (mem) {
    const nums = [...mem.matchAll(/(\d+(?:\.\d+)?)\s*MB/i)].map((m) => Number(m[1]));
    if (nums.length) vramGb = +(Math.max(...nums) / 1024).toFixed(1);
  }
  return Array.from({ length: count }, (_, i) => ({ vendor: 'amd', name: `AMD GPU ${i}`, memoryGb: vramGb }));
}

export async function detectIntel() {
  // Discrete VRAM via sysfs; integrated => shared memory (null = unknown/shared).
  try {
    const cards = await fsp.readdir('/sys/class/drm');
    const discret = [];
    for (const c of cards) {
      if (!/^card\d+$/.test(c)) continue;
      try {
        const raw = await fsp.readFile(`/sys/class/drm/${c}/device/mem_info_vram_total`, 'utf8');
        discret.push({ vendor: 'intel', name: `Intel ${c}`, memoryGb: +(Number(raw.trim()) / 1024 ** 3).toFixed(1) });
      } catch { /* integrated/no sysfs: skip */ }
    }
    if (discret.length) return discret;
  } catch { /* no sysfs (Windows/macOS): fall through */ }
  const lspci = await run('lspci', []);
  if (lspci && /vga|3d|display/i.test(lspci) && /intel/i.test(lspci)) {
    return [{ vendor: 'intel', name: 'Intel iGPU (shared memory)', memoryGb: null }];
  }
  return [];
}

export async function detectAppleUnifiedGb() {
  if (process.platform !== 'darwin') return null;
  const out = await run('system_profiler', ['SPHardwareDataType']);
  const m = out && out.match(/Memory:\s*(\d+(?:\.\d+)?)\s*GB/i);
  return m ? Number(m[1]) : null;
}

export async function detectHardware() {
  const cpus = os.cpus();
  const override =
    process.env.POC_RAM_GB || process.env.POC_VRAM_GB || process.env.POC_CPU_CORES ? true : false;
  const hw = {
    platform: process.platform,
    arch: os.arch(),
    cpu: cpus[0]?.model || 'Unknown CPU',
    logicalCores: Number(process.env.POC_CPU_CORES) || cpus.length,
    ramGb: Number(process.env.POC_RAM_GB) || +(os.totalmem() / 1024 ** 3).toFixed(1),
    freeRamGb: +(os.freemem() / 1024 ** 3).toFixed(1),
    nvidia: await detectNvidia(),
    amd: await detectAmd(),
    intel: await detectIntel(),
    appleUnifiedGb: await detectAppleUnifiedGb(),
    override,
  };
  const vram = Number(process.env.POC_VRAM_GB);
  hw.vramGb = Number.isFinite(vram) && vram > 0 ? vram : maxKnownVram(hw);
  return hw;
}

export function maxKnownVram(hw) {
  const all = [...(hw.nvidia || []), ...(hw.amd || []), ...(hw.intel || [])]
    .map((g) => g.memoryGb)
    .filter((v) => typeof v === 'number' && v > 0);
  return all.length ? Math.max(...all) : 0;
}

const LABEL = { great: 'Sangat cocok', ok: 'Bisa dijalankan', warn: 'Bisa, lebih lambat', no: 'Tidak disarankan' };

// req: { kind: 'local'|'cloud', minRamGb, recRamGb, recVramGb }
export function assessFit(req, hw) {
  if (req.kind === 'cloud') {
    return { level: 'cloud', label: 'Cloud only', reason: 'Dijalankan via cloud, bukan hardware lokal.', confidence: 'n/a' };
  }
  const confidence = hw.override ? 'override' : 'estimated';
  if (hw.ramGb < req.minRamGb) {
    return { level: 'no', label: LABEL.no, reason: `Butuh minimal ${req.minRamGb} GB RAM (terdeteksi ${hw.ramGb} GB).`, confidence };
  }
  const vram = typeof hw.vramGb === 'number' ? hw.vramGb : maxKnownVram(hw);
  if (vram >= req.recVramGb && hw.ramGb >= req.recRamGb) {
    return { level: 'great', label: LABEL.great, reason: `VRAM ${vram} GB + RAM ${hw.ramGb} GB memenuhi target.`, confidence };
  }
  if (hw.ramGb >= req.recRamGb) {
    return { level: 'ok', label: LABEL.ok, reason: 'RAM cukup; gunakan CPU + partial GPU offload.', confidence };
  }
  return { level: 'warn', label: LABEL.warn, reason: 'RAM cukup minimal tapi headroom terbatas.', confidence };
}
