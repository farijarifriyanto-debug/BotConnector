// Phase 4: embeddings acceptance. Downloads a small embedding GGUF via BotConnector
// DownloadManager, serves with --embeddings, probes POST /v1/embeddings.
// Usage: node scripts/embeddings-acceptance.mjs [--port 11436]
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const llama=require('../runtime/llama.cjs');
const hf=require('../runtime/hf.cjs');
const {DownloadManager}=require('../runtime/downloads.cjs');
const {scanInstalled}=require('../runtime/installed.cjs');
const {Store}=require('../runtime/store.cjs');
const os=require('node:os'),path=require('node:path');
const results={};
function check(name,ok,extra=''){results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?`  — ${extra}`:''}`);}
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const args=Object.fromEntries(process.argv.slice(2).map((a,i,arr)=>a.startsWith('--')?[a.slice(2),arr[i+1]&&!arr[i+1].startsWith('--')?arr[i+1]:'true']:[]).filter(x=>x.length));
const port=Number(args.port||11436);
const userData=path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'botconnector-ai-local-cloud');
const store=new Store(userData);store.load();
const bin='C:\\Users\\farij\\AppData\\Roaming\\botconnector-ai-local-cloud\\runtimes\\llama.cpp\\b10930\\vulkan\\llama-server.exe';
const REPO='leliuga/all-MiniLM-L6-v2-GGUF';
try{
  const hw={ramGb:15.6,nvidia:[]};
  const d=await hf.modelDetails({id:REPO,hardware:hw});
  check('EMBED_CAPABILITY',d.capabilities?.embeddings===true&&d.capabilities?.chat!==true,`embeddings=${d.capabilities?.embeddings} chat=${d.capabilities?.chat}`);
  const group=d.files.find(g=>g.quant==='Q8_0')||d.files[0];
  console.log(`selected ${REPO}@${group.quant} (${(group.size/1048576).toFixed(1)}MB)`);
  const dm=new DownloadManager({getModelsDir:()=>store.get('modelsDir'),getToken:()=>process.env.HF_TOKEN||''});
  const job=await dm.start({repoId:REPO,group,metadata:{capabilities:d.capabilities,pipeline_tag:d.pipeline_tag}});
  for(let i=0;i<120;i++){await sleep(1000);const j=dm.list().find(x=>x.id===job.id);if(j?.status==='completed')break;if(j?.status==='failed')throw new Error('download failed: '+j.error);}
  const done=dm.list().find(x=>x.id===job.id);
  check('EMBED_DOWNLOAD',done?.status==='completed',`status=${done?.status}`);
  if(done?.status!=='completed')process.exit(2);
  const installed=await scanInstalled(store.get('modelsDir'));
  const entry=installed.find(m=>m.repoId===REPO);
  check('EMBED_INSTALLED_AS_EMBEDDINGS',!!entry&&entry.capabilities?.embeddings===true&&!entry.capabilities?.chat,`repo=${entry?.repoId} embeddings=${entry?.capabilities?.embeddings}`);
  const modelPath=entry?.path||group.parts.map(p=>p.path)[0];
  llama.startLlama({binary:bin,modelPath,port,gpuLayers:999,context:2048,embedding:true,jinja:false});
  let ready=false;for(let i=0;i<45;i++){await sleep(2000);try{const h=await fetch(`http://127.0.0.1:${port}/health`);if(h.ok){ready=true;break;}}catch{}}
  check('EMBED_SERVER_READY',ready,'--embeddings on :'+port);
  if(!ready){console.log(llama.logs().slice(-12).join('\n'));process.exit(2);}
  const e1=await fetch(`http://127.0.0.1:${port}/v1/embeddings`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-embed',input:'BotConnector local AI platform'})});
  const j1=await e1.json();
  const v1=j1?.data?.[0]?.embedding||[];
  check('EMBEDDINGS_SINGLE',e1.ok&&v1.length>0,`dim=${v1.length}`);
  const e2=await fetch(`http://127.0.0.1:${port}/v1/embeddings`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-embed',input:['first sentence','second sentence']})});
  const j2=await e2.json();
  const okArr=e2.ok&&Array.isArray(j2?.data)&&j2.data.length===2&&j2.data.every(x=>(x.embedding||[]).length===v1.length);
  check('EMBEDDINGS_ARRAY',okArr,`n=${j2?.data?.length} stable_dim=${v1.length}`);
  // determinism spot-check: same input twice -> identical vector
  const e3=await fetch(`http://127.0.0.1:${port}/v1/embeddings`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-embed',input:'BotConnector local AI platform'})});
  const v3=(await e3.json())?.data?.[0]?.embedding||[];
  check('EMBEDDINGS_STABLE',v3.length===v1.length&&v3.every((x,i)=>x===v1[i]),'identical input -> identical vector');
  llama.stopLlama();await sleep(1500);
  check('EMBED_UNLOAD',!llama.status().running,'stopped, port released');
}finally{try{llama.stopLlama();}catch{}}
const fails=Object.entries(results).filter(([,v])=>v!=='PASS');
console.log(`\n${fails.length?'EMBEDDINGS: FAIL':'EMBEDDINGS: ALL PASS'} (${Object.keys(results).length} checks)`);
process.exit(fails.length?1:0);
