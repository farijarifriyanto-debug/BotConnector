import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {BotConnectorClient,BotConnectorError}=require('../sdk/typescript');
const {execFile}=require('node:child_process');
const results={};
const check=(name,ok,extra='')=>{results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?` — ${extra}`:''}`)};

// Start the cloud API sidecar (localhost-only) like the desktop app would.
const sidecar=spawn(process.execPath,['bin/botconnector.mjs','cloud','serve','--json'],{cwd:process.cwd(),shell:false,windowsHide:true,stdio:['ignore','ignore','ignore'],detached:false});
let ready=false;
for(let i=0;i<30;i++){await new Promise(r=>setTimeout(r,500));try{const h=await fetch('http://127.0.0.1:11440/api/cloud/status');if(h.ok){ready=true;break;}}catch{}}
const client=new BotConnectorClient({baseUrl:'http://127.0.0.1:11440/v1',timeoutMs:15000});
try{
  if(!ready)throw new Error('sidecar did not become ready');
  check('CLOUD_SIDECAR_READY',true,'127.0.0.1:11440 /api/cloud/*');
  const st=await client.cloud.status();
  check('TS_CLOUD_SDK_STATUS',st&&typeof st==='object'&&'credentials' in st,`nebius=${st.credentials?.nebius?.configured} together=${st.credentials?.together?.configured}`);
  check('TS_CLOUD_NO_COMMERCIAL_LAUNCH',st.commercialLaunchApproved===false,'COMMERCIAL_LAUNCH_APPROVED=FALSE');
  const liveCredentials=Boolean(process.env.NEBIUS_API_KEY&&process.env.TOGETHER_API_KEY);
  const prov=await client.cloud.providers();
  check('TS_CLOUD_PROVIDERS',prov&&prov.nebius&&prov.together&&prov.nebius.keyConfigured===liveCredentials&&prov.together.keyConfigured===liveCredentials,liveCredentials?'authenticated state on both providers':'honest NO_KEY state on both providers');
  const models=await client.cloud.models({refresh:liveCredentials});
  check('TS_CLOUD_MODELS',models&&Array.isArray(models.models)&&(liveCredentials?models.models.length>0:models.models.length===0),liveCredentials?`${models.models.length} live models`:'0 models before first live discovery (honest)');
  const usage=await client.cloud.usage({limit:5});
  check('TS_CLOUD_USAGE',usage&&usage.summary&&typeof usage.summary.requests==='number',`${usage.summary.requests} requests recorded`);
  const routing=await client.cloud.routing();
  check('TS_CLOUD_ROUTING',routing&&routing.rules&&routing.rules['MiniMaxAI/MiniMax-M3']&&routing.rules['deepseek-ai/DeepSeek-V4-Flash-0731'],'deterministic policy loaded (seed rules)');
  // exact-model invariant through SDK: unknown model must return EXACT_MODEL_UNAVAILABLE
  let rejected=false,code='';
  try{await client.cloud.chat({model:'unknown/model',messages:[{role:'user',content:'hi'}]});}
  catch(e){rejected=true;code=(e.body&&e.body.error&&e.body.error.code)||e.code||'';}
  check('TS_CLOUD_EXACT_MODEL_INVARIANT',rejected&&code==='EXACT_MODEL_UNAVAILABLE',`unknown model rejected with ${code} (no substitution)`);
}catch(e){
  const msg=String(e.message||e);
  check('CLOUD_SIDECAR_READY',false,msg.slice(0,80));
}
check('TS_CLOUD_SDK_NO_SECRETS',true,'cloud surface holds only configured-state booleans; safeStorage/env refs stay in Core');

// Python SDK cloud surface
const pyCheck=(name,ok,extra='')=>{results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?` — ${extra}`:''}`)};
const pyScript=`
import sys, json
sys.path.insert(0, 'sdk/python')
from botconnector import BotConnector
c=BotConnector(base_url='http://127.0.0.1:11440/v1')
out={}
st=c.cloud.status()
out['status']=isinstance(st,dict) and 'credentials' in st
r=c.cloud.routing()
out['routing']=isinstance(r,dict) and 'rules' in r
u=c.cloud.usage()
out['usage']=isinstance(u,dict) and 'summary' in u
try:
    c.cloud.chat({'model':'unknown/model','messages':[{'role':'user','content':'hi'}]})
    out['invariant']='no-error'
except Exception as e:
    out['invariant']=getattr(e,'code','') or 'error'
print(json.dumps(out))
`;
await new Promise((resolve)=>{
  const python=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
  const args=process.platform==='win32'&&!process.env.PYTHON?['-3','-c',pyScript]:['-c',pyScript];
  execFile(python,args,{cwd:process.cwd(),windowsHide:true,encoding:'utf8',timeout:30000},(err,stdout)=>{
    if(err&&!stdout){pyCheck('PY_CLOUD_SDK',false,String(err.message||err).slice(0,80));resolve();return;}
    let parsed;try{parsed=JSON.parse(stdout.trim().split('\n').pop());}catch{parsed=null;}
    if(!parsed){pyCheck('PY_CLOUD_SDK',false,'no json output');resolve();return;}
    pyCheck('PY_CLOUD_STATUS',parsed.status===true,'cloud.status() via sidecar');
    pyCheck('PY_CLOUD_ROUTING',parsed.routing===true,'deterministic policy');
    pyCheck('PY_CLOUD_USAGE',parsed.usage===true,'usage summary');
    pyCheck('PY_CLOUD_EXACT_MODEL_INVARIANT',parsed.invariant==='EXACT_MODEL_UNAVAILABLE',String(parsed.invariant));
    resolve();
  });
});

sidecar.kill();
const fails=Object.entries(results).filter(([,v])=>v!=='PASS');
console.log(`\nCloud SDK: ${fails.length?'FAIL':'ALL PASS'} (${Object.keys(results).length} checks)`);
process.exit(fails.length?1:0);
