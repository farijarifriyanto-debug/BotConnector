import os from 'node:os';import {execFileSync,execFile} from 'node:child_process';import {mkdir,writeFile,rm,stat,readdir,readFile} from 'node:fs/promises';import path from 'node:path';import {fileURLToPath} from 'node:url';
function nvidia(){try{const out=execFileSync('nvidia-smi',['--query-gpu=name,memory.total,driver_version','--format=csv,noheader,nounits'],{encoding:'utf8',timeout:5000});return out.trim().split(/\r?\n/).filter(Boolean).map(line=>{const[name,memoryMb,driver]=line.split(',').map(x=>x.trim());return{name,memoryGb:+(Number(memoryMb)/1024).toFixed(1),driver}})}catch{return[]}}
async function probe(name,url){const t=Date.now();try{const r=await fetch(url,{headers:{'User-Agent':'BotConnectorAI-Doctor/0.4'},signal:AbortSignal.timeout(15000)});return{name,ok:r.ok,status:r.status,ms:Date.now()-t}}catch(e){return{name,ok:false,error:String(e.message||e),ms:Date.now()-t}}}
async function findServerExe(base){const stack=[base];while(stack.length){const d=stack.pop();let items=[];try{items=await readdir(d,{withFileTypes:true});}catch{continue;}for(const x of items){const p=path.join(d,x.name);if(x.isDirectory()){if(path.basename(p).startsWith('.staging-'))continue;stack.push(p);}else if(x.name.toLowerCase()==='llama-server.exe')return p;}}return null;}
function versionOf(exe){return new Promise(resolve=>{execFile(exe,['--version'],{shell:false,windowsHide:true,timeout:30000},(err,stdout,stderr)=>{const out=String(stdout||stderr||'').trim();if(err)resolve({verified:false,error:err.message});else resolve({verified:true,version:out.split(/\r?\n/)[0].slice(0,160)})});});}
async function portBusy(port){try{const r=await fetch(`http://127.0.0.1:${port}/health`,{signal:AbortSignal.timeout(3000)});return{busy:true,http:r.status};}catch(e){const msg=String(e.cause?.message||e.message||'');if(/ECONNREFUSED|Failed to fetch|connect/i.test(msg))return{busy:false};return{busy:null,note:msg.slice(0,120)}}}
export async function runDoctor(){
  const checks=[];
  const push=(name,status,detail='')=>checks.push({name,status,detail});
  const defaultModels=path.join(os.homedir(),'BotConnector AI','models');
  const userData=path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'botconnector-ai-local-cloud');
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
  const exe=await findServerExe(rtBase);
  if(!exe)push('managed-runtime','FAIL','no llama-server.exe under '+rtBase);
  else{const v=await versionOf(exe);push('managed-runtime',v.verified?'PASS':'FAIL',v.verified?`${exe} :: ${v.version}`:(v.error||'verify failed'));}
  const pb=await portBusy(11435);
  push('port-11435',pb.busy?'WARN':'PASS',pb.busy?`occupied (HTTP ${pb.http??'?'}) — a runtime may already be running`:'free');
  let cfg={ok:false};try{const raw=await readFile(path.join(userData,'settings.json'),'utf8');const j=JSON.parse(raw);cfg={ok:true,modelsDir:j.modelsDir||null,runtimeBackend:j.runtimeBackend||null,language:j.language||null};push('config-integrity','PASS',`backend=${cfg.runtimeBackend||'?'} modelsDir=${cfg.modelsDir||'?'}`);}catch(e){push('config-integrity','WARN','no settings yet (defaults will be used)');}
  const result={version:'0.4.0',os:`${os.type()} ${os.release()}`,arch:os.arch(),cpu:os.cpus()[0]?.model||'unknown',logicalCores:os.cpus().length,ramGb:+(os.totalmem()/1024**3).toFixed(1),freeRamGb:+(os.freemem()/1024**3).toFixed(1),nvidia:nv,storage:{...storage,freeGb},network,runtime:{installed:Boolean(exe),binary:exe},port11435:pb,config:cfg,checks};
  return result;
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  const r=await runDoctor();
  console.log(JSON.stringify(r,null,2));
  const fails=r.checks.filter(c=>c.status==='FAIL').length;
  process.exit(fails?1:0);
}
