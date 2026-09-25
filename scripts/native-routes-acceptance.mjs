// Phase 2+3: native Anthropic /v1/messages + /v1/responses acceptance against b10930.
// Usage: node scripts/native-routes-acceptance.mjs [--port 11435]
// Starts the accepted Spark model via llama.cjs, probes native routes, stops.
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const llama=require('../runtime/llama.cjs');
const results={};
function check(name,ok,extra=''){results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?`  — ${extra}`:''}`);}
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const args=Object.fromEntries(process.argv.slice(2).map((a,i,arr)=>a.startsWith('--')?[a.slice(2),arr[i+1]&&!arr[i+1].startsWith('--')?arr[i+1]:'true']:[]).filter(x=>x.length));
const port=Number(args.port||11435);
const bin='C:\\Users\\farij\\AppData\\Roaming\\botconnector-ai-local-cloud\\runtimes\\llama.cpp\\b10930\\vulkan\\llama-server.exe';
const model='C:\\Users\\farij\\BotConnector AI\\models\\XHToken__Spark-X2.5-4B-GGUF\\Q4_K_M\\Spark-X2.5-4B-Q4_K_M.gguf';
async function waitReady(){for(let i=0;i<60;i++){await sleep(2000);try{const h=await fetch(`http://127.0.0.1:${port}/health`);if(h.ok)return true;}catch{}}return false;}
function sseText(s){return s.slice(0,120).replace(/\n/g,'\\n');}
try{
  llama.startLlama({binary:bin,modelPath:model,port,gpuLayers:999,context:4096});
  if(!await waitReady()){check('SERVER_READY',false,'health never ok');console.log(llama.logs().slice(-10).join('\n'));process.exit(2);}
  check('SERVER_READY',true,'Spark-X2.5-4B on :'+port);

  // --- /v1/messages non-stream (reasoning model needs headroom for thinking blocks) ---
  const mBody={model:'local-model',max_tokens:256,messages:[{role:'user',content:'Reply exactly: BOTCONNECTOR_ANTHROPIC_OK'}]};
  const r1=await fetch(`http://127.0.0.1:${port}/v1/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(mBody)});
  const t1=await r1.text();
  let j1=null;try{j1=JSON.parse(t1);}catch{}
  console.log(`POST /v1/messages -> ${r1.status} ${sseText(t1)}`);
  const blocks=j1?.content||[];
  const textOut=blocks.filter(b=>b.type==='text').map(b=>b.text||'').join('');
  check('ANTHROPIC_MESSAGES',r1.ok&&j1?.type==='message'&&j1?.role==='assistant'&&Array.isArray(blocks)&&textOut.includes('BOTCONNECTOR_ANTHROPIC_OK'),
    `type=${j1?.type} role=${j1?.role} stop=${j1?.stop_reason} text="${textOut.slice(0,60)}"`);

  // --- /v1/messages streaming ---
  const r2=await fetch(`http://127.0.0.1:${port}/v1/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...mBody,stream:true,max_tokens:32})});
  let evts=[],buf='',sok=r2.ok;
  if(sok){const rd=r2.body.getReader(),dec=new TextDecoder();let b='';
    while(true){const{done,value}=await rd.read();if(done)break;b+=dec.decode(value,{stream:true});const ls=b.split('\n');b=ls.pop()||'';
      for(const ln of ls){const t=ln.trim();if(t.startsWith('event:'))evts.push(t.slice(6).trim());}}
    buf=b;}
  const hasStart=evts.includes('message_start'),hasDelta=evts.some(e=>e.includes('content_block_delta')),hasStop=evts.includes('message_stop');
  console.log(`stream events: ${[...new Set(evts)].join(',')||'(none)'}`);
  check('ANTHROPIC_STREAMING',sok&&hasStart&&hasDelta&&hasStop,`events message_start/content_block_delta/message_stop present`);

  // --- /v1/messages/count_tokens ---
  const r3=await fetch(`http://127.0.0.1:${port}/v1/messages/count_tokens`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-model',messages:[{role:'user',content:'Hello world'}]})});
  const t3=await r3.text();let j3=null;try{j3=JSON.parse(t3);}catch{}
  console.log(`POST /v1/messages/count_tokens -> ${r3.status} ${sseText(t3)}`);
  check('ANTHROPIC_COUNT_TOKENS',r3.ok&&Number.isInteger(j3?.input_tokens||j3?.tokens),`input_tokens=${j3?.input_tokens ?? j3?.tokens ?? '?'}`);

  // --- /v1/responses basic ---
  const r4=await fetch(`http://127.0.0.1:${port}/v1/responses`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-model',input:'Reply exactly: BOTCONNECTOR_RESPONSES_OK',max_output_tokens:64})});
  const t4=await r4.text();let j4=null;try{j4=JSON.parse(t4);}catch{}
  console.log(`POST /v1/responses -> ${r4.status} ${sseText(t4)}`);
  const r4text=JSON.stringify(j4||{}).includes('BOTCONNECTOR_RESPONSES_OK');
  check('RESPONSES_API',r4.ok&&r4text,`status=${r4.status} marker_found=${r4text} id=${j4?.id||'?'}`);

  // --- /v1/responses streaming probe ---
  const r5=await fetch(`http://127.0.0.1:${port}/v1/responses`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-model',input:'Say hi.',max_output_tokens:16,stream:true})});
  let r5evt=[],r5ok=r5.ok;
  if(r5ok){const rd=r5.body.getReader(),dec=new TextDecoder();let b='';const end=Date.now()+25000;
    while(Date.now()<end){const{done,value}=await rd.read();if(done)break;b+=dec.decode(value,{stream:true});const ls=b.split('\n');b=ls.pop()||'';
      for(const ln of ls){const t=ln.trim();if(t.startsWith('event:'))r5evt.push(t.slice(6).trim());}}
    try{await r5.body.cancel();}catch{}}
  console.log(`responses stream events: ${[...new Set(r5evt)].join(',')||'(none)'}`);
  check('RESPONSES_STREAMING',r5ok&&r5evt.length>0,`events=${r5evt.length}`);

  // --- /v1/responses error structure probe (malformed body must not fake success) ---
  // NOTE: llama.cpp is a single-model server: unknown `model` names are ignored and the
  // loaded model serves (upstream behavior, same as its OpenAI endpoints) — so probe with
  // a malformed body instead.
  const r6=await fetch(`http://127.0.0.1:${port}/v1/responses`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'local-model'})});
  const t6=await r6.text();
  console.log(`malformed /v1/responses -> ${r6.status} ${sseText(t6)}`);
  check('RESPONSES_ERROR_SHAPE',!r6.ok,`status=${r6.status} (explicit error, no fake success)`);
}finally{
  try{llama.stopLlama();}catch{}
}
const fails=Object.entries(results).filter(([,v])=>v!=='PASS');
console.log(`\n${fails.length?'NATIVE ROUTES: FAIL':'NATIVE ROUTES: ALL PASS'} (${Object.keys(results).length} checks)`);
process.exit(fails.length?1:0);
