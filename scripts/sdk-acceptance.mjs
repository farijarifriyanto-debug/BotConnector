import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {BotConnectorClient,BotConnectorError}=require('../sdk/typescript');
const {scanInstalled}=require('../runtime/installed.cjs');
const {RuntimeManager}=require('../runtime/runtime-manager.cjs');
const llama=require('../runtime/llama.cjs');
const {Store}=require('../runtime/store.cjs');
const os=require('node:os'),path=require('node:path'),fs=require('node:fs');
const results={};const check=(name,ok,extra='')=>{results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?`  — ${extra}`:''}`)};const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const chat=new BotConnectorClient();
try{
  check('TS_SDK_BUILD',fs.existsSync(path.join('sdk','typescript','index.d.ts'))&&fs.existsSync(path.join('sdk','typescript','client.js')),'declaration + runtime boundary present');
  const models=await chat.models.list();check('TS_SDK_MODELS',Array.isArray(models?.data),'GET /v1/models');
  const completion=await chat.chat.create({model:'local-model',messages:[{role:'user',content:'Reply with SDK-CHAT-OK'}],max_tokens:32});check('TS_SDK_CHAT',Boolean(completion?.choices?.[0]?.message),'POST /v1/chat/completions');
  let events=0;for await(const event of chat.chat.stream({model:'local-model',messages:[{role:'user',content:'Reply briefly with SDK-STREAM-OK'}],max_tokens:32})){if(event?.choices?.[0]?.delta)events++;}check('TS_SDK_STREAM',events>0,`${events} SSE events`);
  const tools=await chat.tools.list();check('TS_SDK_TOOLS',tools.some(t=>t.name==='calculator'),'BotConnector Core allowlist');
  const bad=new BotConnectorClient({baseUrl:'http://127.0.0.1:1/v1',timeoutMs:300});try{await bad.models.list();check('TS_SDK_ERROR_HANDLING',false,'expected normalized network error')}catch(e){check('TS_SDK_ERROR_HANDLING',e instanceof BotConnectorError&&e.code==='NETWORK_ERROR',`${e.code}`)}
  const userData=path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'botconnector-ai-local-cloud');const store=new Store(userData);store.load();const installed=await scanInstalled(store.get('modelsDir'));const embed=installed.find(m=>m.capabilities?.embeddings&&!m.capabilities?.chat);const runtime=await new RuntimeManager({baseDir:path.join(userData,'runtimes','llama.cpp')}).installed();
  if(!embed||!runtime.installed)throw new Error('accepted embedding model or runtime is unavailable');
  const port=11436;llama.startLlama({binary:runtime.binary,modelPath:embed.path,port,gpuLayers:999,context:2048,embedding:true,jinja:false});let ready=false;for(let i=0;i<30;i++){await sleep(1000);try{if((await fetch(`http://127.0.0.1:${port}/health`)).ok){ready=true;break}}catch{}}
  check('TS_SDK_EMBEDDINGS_SERVER',ready,`embedding runtime :${port}`);if(ready){const emb=new BotConnectorClient({baseUrl:`http://127.0.0.1:${port}/v1`});const result=await emb.embeddings.create({model:'local-embed',input:['sdk first','sdk second']});const vectors=result?.data?.map(x=>x.embedding)||[];check('TS_SDK_EMBEDDINGS',vectors.length===2&&vectors.every(v=>Array.isArray(v)&&v.length>0&&v.every(Number.isFinite)),`n=${vectors.length} dim=${vectors[0]?.length||0}`)}
}catch(e){console.error(`SDK acceptance error: ${e.stack||e}`);for(const name of ['TS_SDK_BUILD','TS_SDK_MODELS','TS_SDK_CHAT','TS_SDK_STREAM','TS_SDK_TOOLS','TS_SDK_ERROR_HANDLING','TS_SDK_EMBEDDINGS'])if(!results[name])results[name]='FAIL'}finally{try{llama.stopLlama()}catch{}}
const fails=Object.entries(results).filter(([,v])=>v!=='PASS');console.log(`\nTS SDK: ${fails.length?'FAIL':'ALL PASS'} (${Object.keys(results).length} checks)`);process.exit(fails.length?1:0);
