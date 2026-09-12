// Phase 7: API auth acceptance. Starts MiniLM with --api-key (fast load), proves:
// no-auth -> 401, wrong key -> 401, Bearer -> 200, x-api-key behavior recorded,
// /health public-or-not recorded. Auth is OFF by default (this script opts in explicitly).
// Usage: node scripts/api-auth-acceptance.mjs [--port 11440]
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {spawn}=require('node:child_process');
const {scanInstalled}=require('../runtime/installed.cjs');
const {Store}=require('../runtime/store.cjs');
const os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const results={};
function check(name,ok,extra=''){results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?`  — ${extra}`:''}`);}
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const args=Object.fromEntries(process.argv.slice(2).map((a,i,arr)=>a.startsWith('--')?[a.slice(2),arr[i+1]&&!arr[i+1].startsWith('--')?arr[i+1]:'true']:[]).filter(x=>x.length));
const port=Number(args.port||11440);
const userData=path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'botconnector-ai-local-cloud');
const store=new Store(userData);store.load();
const bin='C:\\Users\\farij\\AppData\\Roaming\\botconnector-ai-local-cloud\\runtimes\\llama.cpp\\b10930\\vulkan\\llama-server.exe';
const KEY='bc-test-'+crypto.randomBytes(16).toString('hex');
let child=null;
async function waitReady(){for(let i=0;i<45;i++){await sleep(2000);try{const h=await fetch(`http://127.0.0.1:${port}/health`);if(h.ok)return true;}catch{}}return false;}
try{
  const inst=await scanInstalled(store.get('modelsDir'));
  const e=inst.find(m=>m.capabilities?.embeddings);
  if(!e)throw new Error('no embedding model installed (run embeddings acceptance first)');
  check('AUTH_DEFAULT_OFF',store.get('apiAuthEnabled')!==true,'desktop default apiAuthEnabled='+store.get('apiAuthEnabled'));
  child=spawn(bin,['-m',e.path,'--host','127.0.0.1','--port',String(port),'--ctx-size','2048','--n-gpu-layers','999','--embeddings','--api-key',KEY],{shell:false,windowsHide:true,stdio:'ignore'});
  if(!await waitReady())throw new Error('server did not start');
  check('AUTH_SERVER_READY',true,'--api-key set on :'+port);
  const emb={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'m',input:'hello'})};
  const r0=await fetch(`http://127.0.0.1:${port}/v1/embeddings`,emb);
  check('AUTH_UNAUTHORIZED_BLOCKED',r0.status===401,`no-auth status=${r0.status}`);
  const r1=await fetch(`http://127.0.0.1:${port}/v1/embeddings`,{...emb,headers:{...emb.headers,Authorization:'Bearer wrong'}});
  check('AUTH_WRONG_KEY_BLOCKED',r1.status===401,`wrong-key status=${r1.status}`);
  const r2=await fetch(`http://127.0.0.1:${port}/v1/embeddings`,{...emb,headers:{...emb.headers,Authorization:'Bearer '+KEY}});
  const j2=await r2.json().catch(()=>null);
  check('AUTH_BEARER_ACCEPTED',r2.ok&&(j2?.data?.[0]?.embedding||[]).length>0,`bearer status=${r2.status} dim=${(j2?.data?.[0]?.embedding||[]).length}`);
  const r3=await fetch(`http://127.0.0.1:${port}/v1/embeddings`,{...emb,headers:{...emb.headers,'x-api-key':KEY}});
  console.log(`x-api-key probe -> ${r3.status} (llama.cpp native behavior)`);
  results['AUTH_X_API_KEY_INFO']=(r3.ok?'PASS':'FAIL');
  console.log(`${r3.ok?'PASS':'FAIL'}  AUTH_X_API_KEY_INFO  — x-api-key ${r3.ok?'accepted natively':'NOT accepted by b10930 (Bearer required)'}`);
  const h=await fetch(`http://127.0.0.1:${port}/health`);
  console.log(`/health with --api-key -> ${h.status} (recorded; public health is a deliberate choice)`);
  check('AUTH_HEALTH_RECORDED',true,`/health status=${h.status}`);
}finally{if(child){try{child.kill();}catch{}}}
const fails=Object.entries(results).filter(([k,v])=>v!=='PASS'&&k!=='AUTH_X_API_KEY_INFO');
console.log(`\n${fails.length?'API AUTH: FAIL':'API AUTH: ALL PASS'} (${Object.keys(results).length} checks)`);
process.exit(fails.length?1:0);
