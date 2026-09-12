// Phase 5: tool-use acceptance (Spark-X2.5-4B, Jinja on). Proves structured tool_call,
// argument parsing, explicit (non-fake, harness-supplied, labeled) tool result loop,
// and native tool-call probes on /v1/messages + /v1/responses.
// Usage: node scripts/tooluse-acceptance.mjs [--port 11438]
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const llama=require('../runtime/llama.cjs');
const results={};
function check(name,ok,extra=''){results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?`  — ${extra}`:''}`);}
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const args=Object.fromEntries(process.argv.slice(2).map((a,i,arr)=>a.startsWith('--')?[a.slice(2),arr[i+1]&&!arr[i+1].startsWith('--')?arr[i+1]:'true']:[]).filter(x=>x.length));
const port=Number(args.port||11438);
const bin='C:\\Users\\farij\\AppData\\Roaming\\botconnector-ai-local-cloud\\runtimes\\llama.cpp\\b10930\\vulkan\\llama-server.exe';
const model='C:\\Users\\farij\\BotConnector AI\\models\\XHToken__Spark-X2.5-4B-GGUF\\Q4_K_M\\Spark-X2.5-4B-Q4_K_M.gguf';
const TOOLS=[{type:'function',function:{name:'get_weather',description:'Get current weather for a city. Test-only harness tool; no external call is made.',parameters:{type:'object',properties:{city:{type:'string',description:'City name'}},required:['city']}}}];
const BASE='http://127.0.0.1:'+port;
try{
  llama.startLlama({binary:bin,modelPath:model,port,gpuLayers:999,context:8192});
  let ready=false;for(let i=0;i<60;i++){await sleep(2000);try{const h=await fetch(BASE+'/health');if(h.ok){ready=true;break;}}catch{}}
  check('TOOL_SERVER_READY',ready,'Spark-X2.5-4B --jinja on :'+port);
  if(!ready)process.exit(2);

  // 1. OpenAI tool call
  const r1=await fetch(BASE+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model:'m',messages:[{role:'user',content:'What is the weather in Bandung? Use the tool.'}],tools:TOOLS,tool_choice:'auto',temperature:0,max_tokens:256})});
  const j1=await r1.json();
  const tc=j1?.choices?.[0]?.message?.tool_calls?.[0];
  let parsed=null;try{parsed=JSON.parse(tc?.function?.arguments||'');}catch{}
  check('TOOL_USE_OPENAI',r1.ok&&tc?.function?.name==='get_weather'&&parsed?.city==='Bandung',
    `tool=${tc?.function?.name} args=${tc?.function?.arguments}`);
  if(!parsed)process.exit(2);

  // 2. Explicit harness tool result (labeled test observation — NOT a live weather service)
  const toolResult={role:'tool',tool_call_id:tc.id,content:JSON.stringify({city:'Bandung',note:'TEST HARNESS observation, not a live measurement',temp_c:24,condition:'partly cloudy'})};
  const r2=await fetch(BASE+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model:'m',messages:[{role:'user',content:'What is the weather in Bandung? Use the tool.'},{role:'assistant',content:null,tool_calls:[tc]},toolResult],temperature:0,max_tokens:256})});
  const j2=await r2.json();
  const final=j2?.choices?.[0]?.message?.content||'';
  check('TOOL_RESULT_LOOP',r2.ok&&/bandung/i.test(final)&&/24|cloudy/i.test(final),`final="${final.slice(0,100)}"`);

  // 3. Anthropic native tool call probe
  const r3=await fetch(BASE+'/v1/messages',{method:'POST',headers:{'Content-Type':'application/json','anthropic-version':'2023-06-01'},
    body:JSON.stringify({model:'m',max_tokens:256,messages:[{role:'user',content:'What is the weather in Bandung? Use the tool.'}],
      tools:[{name:'get_weather',description:'Get current weather for a city',input_schema:{type:'object',properties:{city:{type:'string'}},required:['city']}}]})});
  const t3=await r3.text();let j3=null;try{j3=JSON.parse(t3);}catch{}
  const use=(j3?.content||[]).find(b=>b.type==='tool_use');
  console.log(`POST /v1/messages+tools -> ${r3.status} tool_use=${use?use.name+' '+JSON.stringify(use.input):'(none)'}`);
  check('TOOL_USE_ANTHROPIC',r3.ok&&use?.name==='get_weather'&&use?.input?.city==='Bandung',
    `tool_use=${use?.name||'none'} stop=${j3?.stop_reason}`);

  // 4. Responses API tool probe
  const r4=await fetch(BASE+'/v1/responses',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model:'m',input:'What is the weather in Bandung? Use the tool.',tools:[{type:'function',name:'get_weather',description:'Get weather',parameters:{type:'object',properties:{city:{type:'string'}},required:['city']}}],max_output_tokens:256})});
  const t4=await r4.text();
  const hasCall=/get_weather/i.test(t4)&&/Bandung/.test(t4);
  console.log(`POST /v1/responses+tools -> ${r4.status} call_present=${hasCall}`);
  check('TOOL_USE_RESPONSES',r4.ok&&hasCall,`status=${r4.status}`);
}finally{try{llama.stopLlama();}catch{}}
const fails=Object.entries(results).filter(([,v])=>v!=='PASS');
console.log(`\n${fails.length?'TOOL USE: FAIL':'TOOL USE: ALL PASS'} (${Object.keys(results).length} checks)`);
process.exit(fails.length?1:0);
