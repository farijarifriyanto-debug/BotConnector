// Live end-to-end acceptance for BotConnector AI v0.4 (Phase Z).
// Usage: node scripts/live-acceptance.mjs [--backend vulkan] [--port 11435]
// Proves: resolver, verify gate, start, readiness, non-stream + streaming chat,
// stop-generation abort, /v1/models, stop, restart. Exits non-zero on failure.
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const llama=require('../runtime/llama.cjs');
const {RuntimeManager}=require('../runtime/runtime-manager.cjs');
const os=require('node:os');

const args=Object.fromEntries(process.argv.slice(2).map((a,i,arr)=>a.startsWith('--')?[a.slice(2),arr[i+1]&&!arr[i+1].startsWith('--')?arr[i+1]:'true']:[]).filter(x=>x.length));
const backend=args.backend||'vulkan';
const port=Number(args.port||11435);
const results={};
function check(name,ok,extra=''){results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?`  — ${extra}`:''}`);if(!ok)process.exitCode=1;}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const userData='C:\\Users\\farij\\AppData\\Roaming\\botconnector-ai-local-cloud';
const rt=new RuntimeManager({baseDir:userData+'\\runtimes\\llama.cpp'});
const model='C:\\Users\\farij\\BotConnector AI\\models\\XHToken__Spark-X2.5-4B-GGUF\\Q4_K_M\\Spark-X2.5-4B-Q4_K_M.gguf';

try{
  // 1. resolver finds official win-x64 asset
  const res=await rt.resolveBackend(backend);
  check('RUNTIME_ASSET_RESOLVER',!!res.primaryAsset,`${res.releaseTag}/${res.backend}/${res.primaryAsset.name}`);
  // 2. installed + verified
  const v=await rt.verifyInstalled();
  check('LLAMA_SERVER_VERSION',v.verified,`${v.binary} :: ${(v.version||'').split('\n')[0]}`);
  // 3. start
  const started=llama.startLlama({binary:v.binary,modelPath:model,port,gpuLayers:backend==='cpu'?0:999,context:4096});
  check('MODEL_START',!!started.pid,`pid=${started.pid}`);
  // 4. readiness
  let ready=false;const t0=Date.now();
  for(let i=0;i<60&&!ready;i++){await sleep(2000);try{const h=await fetch(`http://127.0.0.1:${port}/health`);ready=h.ok;}catch{}}
  check('SERVER_HEALTH',ready,`ready in ${Math.round((Date.now()-t0)/1000)}s`);
  if(!ready){console.log('LOGS:',llama.logs().slice(-15).join('\n'));process.exit(2);}
  // 5. /v1/models
  try{
    const m=await (await fetch(`http://127.0.0.1:${port}/v1/models`)).json();
    check('OPENAI_MODELS',Array.isArray(m.data),`models=${(m.data||[]).length}`);
  }catch(e){check('OPENAI_MODELS',false,e.message);}
  // 6. non-stream chat (reasoning models may put tokens in reasoning_content first)
  const t1=Date.now();
  const r1=await fetch(`http://127.0.0.1:${port}/v1/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-model',messages:[{role:'user',content:'Reply with exactly: OK-LOCAL'}],temperature:0,max_tokens:128,stream:false})});
  const j1=await r1.json();
  const msg1=j1?.choices?.[0]?.message||{};
  const txt=msg1.content||msg1.reasoning_content||'';
  check('CHAT_NONSTREAM',r1.ok&&txt.length>0,`"${txt.slice(0,80)}" in ${Date.now()-t1}ms (content=${(msg1.content||'').length}ch, reasoning=${(msg1.reasoning_content||'').length}ch)`);
  // 7. streaming chat + tokens/sec
  const t2=Date.now();let toks=0,streamTxt='';
  const r2=await fetch(`http://127.0.0.1:${port}/v1/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-model',messages:[{role:'user',content:'Count from 1 to 5, one per line.'}],temperature:0,max_tokens:64,stream:true})});
  const reader=r2.body.getReader(),dec=new TextDecoder();let buf='';
  while(true){const{done,value}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});const lines=buf.split('\n');buf=lines.pop()||'';for(const ln of lines){if(!ln.startsWith('data:'))continue;const raw=ln.slice(5).trim();if(!raw||raw==='[DONE]')continue;try{const d=JSON.parse(raw)?.choices?.[0]?.delta?.content||'';if(d){toks++;streamTxt+=d;}}catch{}}}
  const secs=(Date.now()-t2)/1000;
  check('CHAT_STREAMING',toks>0,`${toks} chunks in ${secs.toFixed(1)}s (~${(toks/Math.max(secs,0.1)).toFixed(1)} tok/s) :: "${streamTxt.slice(0,60)}"`);
  // 8. stop generation (abort mid-stream while consuming body)
  const ctl=new AbortController();
  let aborted=false,gotChunk=false;
  const abortPromise=(async()=>{try{
    const ra=await fetch(`http://127.0.0.1:${port}/v1/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json'},signal:ctl.signal,body:JSON.stringify({model:'local-model',messages:[{role:'user',content:'Write a 500 word essay about the sea.'}],max_tokens:500,stream:true})});
    const rd=ra.body.getReader();
    while(true){const{done}=await rd.read();if(done)break;gotChunk=true;}
  }catch(e){aborted=/abort/i.test(String(e.message||e));}})();
  await sleep(2000);ctl.abort();
  await abortPromise;
  check('STOP_GENERATION',aborted&&gotChunk,`abort error seen=${aborted}, chunks seen=${gotChunk}, server alive=`+(llama.status().running?'yes':'NO'));
  // 9. server still healthy after abort
  try{const h=await fetch(`http://127.0.0.1:${port}/health`);check('HEALTH_AFTER_ABORT',h.ok,`status=${h.status}`);}catch(e){check('HEALTH_AFTER_ABORT',false,e.message);}
  // 10. stop runtime
  const stopped=llama.stopLlama();
  await sleep(1500);
  check('RUNTIME_STOP',stopped===true&&!llama.status().running,'process terminated');
  // 11. restart runtime
  const r3=llama.startLlama({binary:v.binary,modelPath:model,port,gpuLayers:backend==='cpu'?0:999,context:4096});
  let ready2=false;for(let i=0;i<60&&!ready2;i++){await sleep(2000);try{const h=await fetch(`http://127.0.0.1:${port}/health`);ready2=h.ok;}catch{}}
  check('RUNTIME_RESTART',ready2,`pid=${r3.pid}`);
  llama.stopLlama();
  console.log(`\nFree RAM at end: ${(os.freemem()/1024**3).toFixed(1)} GB`);
}catch(e){
  console.error('ACCEPTANCE ERROR:',e.message);
  try{llama.stopLlama();}catch{}
  process.exit(2);
}
const fails=Object.entries(results).filter(([,v])=>v!=='PASS');
console.log(`\n${fails.length?'ACCEPTANCE: FAIL':'ACCEPTANCE: ALL PASS'} (${Object.keys(results).length} checks)`);
process.exit(fails.length?1:0);
