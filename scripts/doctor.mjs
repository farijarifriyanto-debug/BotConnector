import os from 'node:os';import {execFileSync,execFile} from 'node:child_process';import {mkdir,writeFile,rm,stat,readdir,readFile} from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';import {createRequire} from 'node:module';
import * as platformPaths from '../runtime/platform-paths.cjs';
const require=createRequire(import.meta.url);
const {RuntimeManager,SERVER_BIN}=require('../runtime/runtime-manager.cjs');
const {version:PKG_VERSION}=require('../package.json');
function nvidia(){try{const out=execFileSync('nvidia-smi',['--query-gpu=name,memory.total,driver_version','--format=csv,noheader,nounits'],{encoding:'utf8',timeout:5000});return out.trim().split(/\r?\n/).filter(Boolean).map(line=>{const[name,memoryMb,driver]=line.split(',').map(x=>x.trim());return{name,memoryGb:+(Number(memoryMb)/1024).toFixed(1),driver}})}catch{return[]}}
async function probe(name,url){const t=Date.now();try{const r=await fetch(url,{headers:{'User-Agent':'BotConnectorAI-Doctor/0.4'},signal:AbortSignal.timeout(15000)});return{name,ok:r.ok,status:r.status,ms:Date.now()-t}}catch(e){return{name,ok:false,error:String(e.message||e),ms:Date.now()-t}}}
// Finding the installed managed-runtime binary reuses RuntimeManager's own
// findServer()/SERVER_BIN (runtime/runtime-manager.cjs) rather than
// re-walking the directory tree here — this file used to duplicate that
// exact tree-walk with a Windows-only "llama-server.exe" name hardcoded,
// which is exactly the kind of duplicated runtime logic this project's own
// NO_DUPLICATE_RUNTIME_LOGIC structural check exists to catch, and which
// also meant this doctor check never worked on Linux at all until this fix.
function versionOf(exe){return new Promise(resolve=>{execFile(exe,['--version'],{shell:false,windowsHide:true,timeout:30000},(err,stdout,stderr)=>{const out=String(stdout||stderr||'').trim();if(err)resolve({verified:false,error:err.message});else resolve({verified:true,version:out.split(/\r?\n/)[0].slice(0,160)})});});}
async function portBusy(port){try{const r=await fetch(`http://127.0.0.1:${port}/health`,{signal:AbortSignal.timeout(3000)});return{busy:true,http:r.status};}catch(e){const msg=String(e.cause?.message||e.message||'');if(/ECONNREFUSED|Failed to fetch|connect/i.test(msg))return{busy:false};return{busy:null,note:msg.slice(0,120)}}}
export async function runDoctor(){
  const checks=[];
  const push=(name,status,detail='')=>checks.push({name,status,detail});
  const defaultModels=platformPaths.modelsDir();
  const userData=platformPaths.isWindows()?path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'botconnector-ai-local-cloud'):platformPaths.dataDir();
  let storage={path:defaultModels,writable:false,error:null};
  try{await mkdir(defaultModels,{recursive:true});const p=path.join(defaultModels,'.write-test');await writeFile(p,'ok');await rm(p,{force:true});storage.writable=true;push('model-dir-writable','PASS',defaultModels);}catch(e){storage.error=String(e.message||e);push('model-dir-writable','FAIL',storage.error);}
  let freeGb=null;try{const s=await import('node:fs').then(m=>m.statfsSync(defaultModels));freeGb=+(Number(s.bfree)*Number(s.bsize)/1024**3).toFixed(1);push('disk-space',freeGb>10?'PASS':'WARN',`${freeGb} GB free`);}catch(e){push('disk-space','WARN','statfs unavailable');}
  const nv=nvidia();
  push('os-arch','PASS',`${os.type()} ${os.release()} ${os.arch()}`);
  push('cpu','PASS',`${os.cpus()[0]?.model||'unknown'} x${os.cpus().length}`);
  push('ram',os.totalmem()/1024**3>=6?'PASS':'WARN',`${+(os.totalmem()/1024**3).toFixed(1)} GB total`);
  push('gpu',nv.length?'PASS':'WARN',nv.length?nv.map(g=>`${g.name} ${g.memoryGb}GB`).join('; '):'no NVIDIA GPU (Vulkan/CPU path expected)');
  const network=await Promise.all([probe('huggingface','https://huggingface.co/api/models?filter=gguf&limit=1'),probe('llama.cpp releases','https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=1')]);
  for(const n of network)push(`net-${n.name}`,n.ok?'PASS':'FAIL',n.ok?`${n.status} in ${n.ms}ms`:(n.error||String(n.status)));
  const rtBase=path.join(userData,'runtimes','llama.cpp');
  const runtimeMgr=new RuntimeManager({baseDir:rtBase});
  const exe=await runtimeMgr.findServer();
  if(!exe)push('managed-runtime','FAIL',`no ${SERVER_BIN} under `+rtBase);
  else{const v=await versionOf(exe);push('managed-runtime',v.verified?'PASS':'FAIL',v.verified?`${exe} :: ${v.version}`:(v.error||'verify failed'));}
  const pb=await portBusy(11435);
  push('port-11435',pb.busy?'WARN':'PASS',pb.busy?`occupied (HTTP ${pb.http??'?'}) — a runtime may already be running`:'free');
  let cfg={ok:false};try{const raw=await readFile(path.join(userData,'settings.json'),'utf8');const j=JSON.parse(raw);cfg={ok:true,modelsDir:j.modelsDir||null,runtimeBackend:j.runtimeBackend||null,language:j.language||null};push('config-integrity','PASS',`backend=${cfg.runtimeBackend||'?'} modelsDir=${cfg.modelsDir||'?'}`);}catch(e){push('config-integrity','WARN','no settings yet (defaults will be used)');}
  const result={version:PKG_VERSION,os:`${os.type()} ${os.release()}`,arch:os.arch(),cpu:os.cpus()[0]?.model||'unknown',logicalCores:os.cpus().length,ramGb:+(os.totalmem()/1024**3).toFixed(1),freeRamGb:+(os.freemem()/1024**3).toFixed(1),nvidia:nv,storage:{...storage,freeGb},network,runtime:{installed:Boolean(exe),binary:exe},port11435:pb,config:cfg,checks};
  return result;
}
// import.meta.url is empty when this file is bundled to CJS (the SEA build)
// — guard against fileURLToPath(undefined) throwing, which would otherwise
// crash even a plain `import` of this module from the bundled botconnector
// CLI. This block only ever matters for the real standalone `node
// scripts/doctor.mjs` usage, where import.meta.url is always a real URL.
if(import.meta.url&&process.argv[1]===fileURLToPath(import.meta.url)){
  // Wrapped in an async IIFE (not top-level await) so this file can be
  // bundled to CommonJS for the botconnector.exe SEA build. Behavior when
  // run directly (`node scripts/doctor.mjs`) is unchanged.
  (async()=>{
    const r=await runDoctor();
    console.log(JSON.stringify(r,null,2));
    const fails=r.checks.filter(c=>c.status==='FAIL').length;
    process.exit(fails?1:0);
  })();
}
