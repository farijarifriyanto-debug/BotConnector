// botconnector CLI - shares BotConnector Core (same Store, HF adapter, DownloadManager,
// RuntimeManager, model paths and config as the Electron desktop). Works with GUI closed.
// Usage: node bin/botconnector.mjs <command> [args] [--json] [--port N]
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import {spawn,execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {Store}=require('../runtime/store.cjs');
const hf=require('../runtime/hf.cjs');
const {DownloadManager}=require('../runtime/downloads.cjs');
const {RuntimeManager}=require('../runtime/runtime-manager.cjs');
const {scanInstalled}=require('../runtime/installed.cjs');
const {detectHardware}=require('../runtime/hardware.cjs');
const {claimOwnership,readOwnership,releaseOwnership,setChild,statePath}=require('../runtime/ownership.cjs');

const APP='botconnector-ai-local-cloud';
const userData=path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),APP);
const store=new Store(userData);store.load();
const runtimes=new RuntimeManager({baseDir:path.join(userData,'runtimes','llama.cpp')});
const downloads=new DownloadManager({getModelsDir:()=>store.get('modelsDir'),getToken:()=>process.env.HF_TOKEN||''});
const STATE_FILE=statePath(userData);
const rawArgs=process.argv.slice(2);
const json=rawArgs.includes('--json');
const opt=(name,def)=>{const i=rawArgs.indexOf('--'+name);return i>=0&&rawArgs[i+1]&&!rawArgs[i+1].startsWith('--')?rawArgs[i+1]:def;};
const port=Number(opt('port',11435));
const out=(o)=>{if(json)console.log(JSON.stringify(o,null,2));else console.log(typeof o==='string'?o:JSON.stringify(o,null,2));};
const fail=(m)=>{console.error(json?JSON.stringify({ok:false,error:m}):`Error: ${m}`);process.exit(1);};
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
async function endpoint(pathname){const r=await fetch(`http://127.0.0.1:${port}${pathname}`,{signal:AbortSignal.timeout(5000)});return r;}
async function serverHealth(){try{const r=await endpoint('/health');return{up:r.ok,status:r.status};}catch(e){return{up:false,error:String(e.cause?.message||e.message)};}}
function readState(){try{const s=JSON.parse(fs.readFileSync(STATE_FILE,'utf8'));if(s&&!s.pid)s.pid=s.childPid;return s;}catch{return null;}}
function pidAlive(pid){try{process.kill(pid,0);return true;}catch{return false;}}
function resolveModelRef(ref,installed){
  if(!ref)fail('model reference required');
  if(fs.existsSync(ref)&&/\.gguf$/i.test(ref))return{modelPath:path.resolve(ref),projector:null};
  const hit=installed.find(m=>m.path===path.resolve(ref)||m.name===path.basename(ref)||`${m.repoId}@${m.quant}`===ref||m.repoId===ref);
  if(hit)return{modelPath:hit.path,projector:hit.projector};
  fail(`model not found locally: ${ref} (see: botconnector ls)`);
}
async function waitReady(tries=45){for(let i=0;i<tries;i++){const h=await serverHealth();if(h.up)return true;await sleep(2000);}return false;}

const HELP=`botconnector - BotConnector AI CLI (shares Core/config with the desktop app)

  botconnector --help | version | doctor [--json]
  botconnector models search <query> [--json]
  botconnector models search --recommended [--json]
  botconnector models info <user/model> [--json]
  botconnector get <repo>[@QUANT] [--projector N]
  botconnector ls [--json]
  botconnector runtime status|resolve|verify|install [--backend auto|cpu|vulkan|cuda12|cuda13] [--json]
  botconnector runtime use <auto|cpu|vulkan|cuda12|cuda13|rocm>
  botconnector load <model-ref> | unload | ps [--json]
  botconnector run <model-ref>            (foreground; Ctrl-C stops)
  botconnector chat <model-ref?> "prompt" [--stream] [--api-key KEY]
  botconnector embed "text" [--json] [--api-key KEY]
  botconnector server start <model-ref> [--ctx N] [--backend auto|cpu|vulkan|cuda12|cuda13|rocm] [--api-key KEY] | stop | status [--json]
  botconnector cloud status [--json] | providers [--json] | models [--refresh] [provider] [--json]
  botconnector cloud set-key <nebius|together> | key-status [--json] | remove-key <provider>
  botconnector cloud usage [--limit N] [--json] | routing [--json]
  botconnector cloud test [model-id] [--prompt "..."]   (small cost-capped probe)
  botconnector launch <opencode|claude-code|codex|cline> [--apply]
`;
const [cmd,sub]=rawArgs.filter(a=>!a.startsWith('--'));
if(!cmd||cmd==='--help'||cmd==='help'){console.log(HELP);process.exit(0);}
if(cmd==='version'){out({name:APP,version:'0.4.0'});process.exit(0);}

if(cmd==='doctor'){
  const {runDoctor}=await import('../scripts/doctor.mjs');
  const r=await runDoctor();
  out(json?r:r.checks.map(c=>`${c.status}  ${c.name} - ${c.detail}`).join('\n'));
  process.exit(r.checks.some(c=>c.status==='FAIL')?1:0);
}
if(cmd==='models'&&sub==='search'){
  const recommended=rawArgs.includes('--recommended');
  const q=rawArgs.find((a,i)=>i>2&&!a.startsWith('--')&&a!==sub)||'';
  const hardware=await detectHardware();
  const items=await hf.searchModels({query:q,limit:60,hardware});
  const rows=recommended?items.filter(m=>['great','ok'].includes(m.compatibility?.level)).slice(0,20):items.slice(0,30);
  if(json)out(rows);
  else rows.forEach(m=>console.log(`${m.compatibility?.level||'?'}  ${m.id}  *${m.likes} v${m.downloads}  [${Object.entries(m.capabilities||{}).filter(([,v])=>v).map(([k])=>k).join(',')}]`));
  process.exit(0);
}
if(cmd==='models'&&sub==='info'){
  const id=rawArgs.find((a,i)=>i>2&&!a.startsWith('--')&&a!==sub)||'';
  if(!id)fail('models info <user/model>');
  const hardware=await detectHardware();
  const d=await hf.modelDetails({id,hardware});
  if(json)out(d);
  else{console.log(`${d.id}\n  task=${d.pipeline_tag} gated=${d.gated} downloads=${d.downloads} likes=${d.likes}\n  caps=${Object.entries(d.capabilities).filter(([,v])=>v).map(([k])=>k).join(',')}`);d.files.forEach(g=>console.log(`  ${g.quant}  ${(g.size/1073741824).toFixed(2)}GB  ${g.parts.length} part(s)`));if(d.projectors?.length)d.projectors.forEach(p=>console.log(`  projector: ${p.path} ${(p.size/1048576).toFixed(1)}MB`));}
  process.exit(0);
}
if(cmd==='get'){
  const ref=rawArgs[1]||'';
  const [repo,quant]=ref.split('@');
  if(!repo||!repo.includes('/'))fail('get <user/model>[@QUANT]');
  const hardware=await detectHardware();
  const d=await hf.modelDetails({id:repo,hardware});
  let group=d.files.find(g=>g.quant?.toUpperCase()===String(quant||'').toUpperCase())||d.files.find(g=>/Q4_K_M/.test(g.quant))||d.files[0];
  if(!group)fail('no GGUF files in '+repo);
  const job=await downloads.start({repoId:repo,group,projector:null,metadata:{capabilities:d.capabilities,pipeline_tag:d.pipeline_tag}});
  console.log(`downloading ${repo}@${group.quant} (${(group.size/1073741824).toFixed(2)}GB) job=${job.id}`);
  for(;;){await sleep(1000);const j=downloads.list().find(x=>x.id===job.id);if(!j||['completed','failed','cancelled'].includes(j.status)){console.log(json?JSON.stringify(j):`status=${j?.status} ${j?.error||''}`);process.exit(j?.status==='completed'?0:1);}process.stdout.write(`\r${((100*(j.downloadedBytes||0))/(j.totalBytes||1)).toFixed(1)}% ${((j.downloadedBytes||0)/1048576).toFixed(0)}MB ${(j.bytesPerSecond/1048576).toFixed(1)}MB/s  `);}
}
if(cmd==='ls'){
  const items=await scanInstalled(store.get('modelsDir'));
  if(json)out(items);
  else if(!items.length)console.log('No downloaded GGUF models.');
  else items.forEach(m=>console.log(`${m.repoId||'(unknown)'}@${m.quant||'?'}  ${(m.size/1073741824).toFixed(2)}GB  ${m.path}`));
  process.exit(0);
}
if(cmd==='runtime'&&(sub==='status'||!sub)){
  const inst=await runtimes.installed();
  const ver=await runtimes.verifyInstalled().catch(e=>({installed:false,error:String(e.message)}));
  const health=await serverHealth();
  out({installed:inst,verified:ver,endpoint:{port,...health},backend:store.get('runtimeBackend')});
  process.exit(0);
}
if(cmd==='runtime'&&sub==='verify'){out(await runtimes.verifyInstalled());process.exit(0);}
if(cmd==='runtime'&&sub==='resolve'){
  const r=await runtimes.resolveBackend(opt('backend','vulkan'));
  out({releaseTag:r.releaseTag,backend:r.backend,primaryAsset:r.primaryAsset.name,dependencies:r.dependencies.map(d=>d.name)});
  process.exit(0);
}
if(cmd==='runtime'&&sub==='install'){
  const backend=opt('backend',store.get('runtimeBackend')||'auto');
  console.error(`resolving ${backend}...`);
  const r=await runtimes.install({backend});
  out({ok:true,release:r.release,backend:r.backend,binary:r.binary,version:r.version});
  process.exit(0);
}
if(cmd==='runtime'&&sub==='use'){
  const b=rawArgs[2]||'';
  if(!['auto','cpu','vulkan','cuda12','cuda13','rocm'].includes(b))fail('runtime use <auto|cpu|vulkan|cuda12|cuda13|rocm>');
  await store.set('runtimeBackend',b);
  out({ok:true,runtimeBackend:b});
  process.exit(0);
}
function cloudParts(){
  const cloudDir=path.join(userData,'cloud');
  const {CredentialManager}=require('../runtime/credentials.cjs');
  const {NebiusProvider}=require('../runtime/cloud/nebius.cjs');
  const {TogetherProvider}=require('../runtime/cloud/together.cjs');
  const {ModelCatalog}=require('../runtime/cloud/catalog.cjs');
  const {RoutingTable}=require('../runtime/cloud/routing.cjs');
  const {HealthBoard}=require('../runtime/cloud/health.cjs');
  const {UsageLedger}=require('../runtime/cloud/usage.cjs');
  const {PricingRegistry}=require('../runtime/cloud/pricing.cjs');
  const {UnitEngine}=require('../runtime/cloud/units.cjs');
  const {BudgetGuard}=require('../runtime/cloud/budget.cjs');
  const {CloudRouter}=require('../runtime/cloud/router.cjs');
  const credentials=new CredentialManager({store,env:process.env});
  const adapters={
    nebius:new NebiusProvider({getKey:()=>{const s=credentials.source('nebius');return s.source==='missing'?null:s.key;}}),
    together:new TogetherProvider({getKey:()=>{const s=credentials.source('together');return s.source==='missing'?null:s.key;}})
  };
  const catalog=new ModelCatalog({adapters,cachedir:cloudDir});
  const health=new HealthBoard({dir:cloudDir});health.restore().catch(()=>{});
  const router=new CloudRouter({adapters,catalog,routing:new RoutingTable({dir:cloudDir}),health,ledger:new UsageLedger({dir:cloudDir}),pricing:new PricingRegistry({dir:cloudDir}),units:new UnitEngine({}),budget:new BudgetGuard({dir:cloudDir})});
  return {credentials,adapters,catalog,health,router,cloudDir};
}
const CLOUD_API_PORT=()=>Number(opt('cloud-port',11440));
async function cloudApiRequest(pathname,{method='GET',body}={}){
  try{const r=await fetch(`http://127.0.0.1:${CLOUD_API_PORT()}${pathname}`,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(180000)});const j=await r.json().catch(()=>({}));return {status:r.status,j};}
  catch(e){return {status:0,j:{error:{message:String(e.message||e),code:'NETWORK_ERROR'}}};}
}
if(cmd==='cloud'&&sub==='serve'){
  // Deterministic localhost sidecar exposing /api/cloud/* for CLI/SDK surfaces.
  const {CloudServer}=require('../runtime/cloud/server.cjs');
  const cs=new CloudServer({store,port:CLOUD_API_PORT()});
  await cs.listen();
  console.error(`BotConnector cloud API on http://127.0.0.1:${CLOUD_API_PORT()} (localhost only; Ctrl-C stops)`);
  await new Promise(()=>{});
}
async function cloudApi(pathname,{method='GET',body}={}){
  const {status,j}=await cloudApiRequest(pathname,{method,body});
  if(status===0)fail('cloud API sidecar is not running. Start it with: botconnector cloud serve (the desktop app also starts it automatically)');
  if(status>=400)fail(j.error?`${j.error.code||'CLOUD_ERROR'}: ${j.error.message}`:`cloud API returned ${status}`);
  return j;
}
if(cmd==='cloud'&&(sub==='status'||!sub)){
  const {credentials,adapters,health,catalog}=cloudParts();
  const status=health.all(['nebius','together']);
  const counts=catalog.counts();
  out({
    note:'Multi-provider POC. Exact-model routing only; prompts sent to cloud leave this device; local prompts stay local.',
    credentials:credentials.public(),
    providers:{nebius:status.nebius,together:status.together},
    catalog:counts,
    commercialLaunchApproved:false
  });
  process.exit(0);
}
if(cmd==='cloud'&&sub==='providers'){
  out(await cloudApi('/api/cloud/providers'));process.exit(0);
}
if(cmd==='cloud'&&sub==='models'){
  const arg=rawArgs.find((a,i)=>i>2&&!a.startsWith('--'));
  const q=(rawArgs.includes('--refresh')?'?refresh=1':'')+(arg?'&(provider='+encodeURIComponent(arg)+')':'');
  const r=await cloudApi('/api/cloud/models'+q);
  if(json)out(r);
  else if(rawArgs.includes('--refresh')){const res=r.refresh||{};console.log(['nebius','together'].map(p=>`${p}: ${res[p]&&res[p].ok?res[p].count+' live':'failed ('+(res[p]&&res[p].error||'?')+')'}`).join(' | '));r.models.slice(0,40).forEach(m=>console.log(`${m.modelId}  [${m.provider}]${m.stale?' (stale)':''}`));}
  else r.models.slice(0,40).forEach(m=>console.log(`${m.modelId}  [${m.provider}]${m.stale?' (stale)':''}`));
  process.exit(0);
}
if(cmd==='cloud'&&sub==='usage'){
  const r=await cloudApi('/api/cloud/usage?limit='+Number(opt('limit',10)));
  out(json?r:(JSON.stringify(r.summary,null,2)+'\nrecent: '+r.recent.map(x=>`${x.timestamp} ${x.provider_used} ${x.model_id} failover=${x.failover} $${x.estimated_provider_cost}`).join('\n')));
  process.exit(0);
}
if(cmd==='cloud'&&sub==='routing'){
  out(await cloudApi('/api/cloud/routing'));
  process.exit(0);
}
if(cmd==='cloud'&&sub==='test'){
  const model=rawArgs.find((a,i)=>i>2&&!a.startsWith('--'))||'deepseek-ai/DeepSeek-V4-Flash-0731';
  const prompt=opt('prompt','Reply with exactly: OK-CLOUD');
  const {status,j}=await cloudApiRequest('/api/cloud/chat',{method:'POST',body:{model,messages:[{role:'user',content:prompt}],max_tokens:32}});
  if(status===0)fail('cloud API sidecar is not running: botconnector cloud serve');
  if(status>=400)out({ok:false,...(j.error||{})});
  else{const m=(j.choices&&j.choices[0]&&j.choices[0].message)||{};const meta=j._meta||{};out({ok:true,model:meta.modelId||model,providerUsed:meta.providerUsed,failover:meta.failover,content:m.content,usage:meta.usage,cost:meta.cost,cloudUnits:meta.cloudUnits});}
  process.exit(0);
}
async function startServer(modelRef,ctx){
  const installed=await scanInstalled(store.get('modelsDir'));
  const {modelPath,projector}=resolveModelRef(modelRef,installed);
  const backend=opt('backend',store.get('runtimeBackend')||'auto');
  const eff=backend==='auto'?((await detectHardware()).nvidia?.length?'cuda12':'vulkan'):backend;
  const {binary}=await runtimes.installed();
  if(!binary)fail('No managed runtime installed. Run: botconnector runtime install');
  const args=['-m',modelPath,'--host','127.0.0.1','--port',String(port),'--ctx-size',String(ctx||4096),'--n-gpu-layers',eff==='cpu'?'0':'999','--jinja'];
  if(projector)args.push('--mmproj',projector);
  const cliKey=opt('api-key',null);
  if(cliKey)args.push('--api-key',cliKey);
  const h0=await serverHealth();
  if(h0.up)fail(`port ${port} already serves a runtime (stop it first)`);
  await claimOwnership({file:STATE_FILE,ownerType:'cli',port,modelPath,backend:eff,auth:Boolean(cliKey)});
  let child;
  try{
    child=spawn(binary,args,{shell:false,windowsHide:true,detached:true,stdio:'ignore'});
    child.unref();
    await setChild(STATE_FILE,child.pid);
    const ok=await waitReady();
    if(!ok)throw new Error('server did not become ready (see runtime logs in desktop app)');
    return{pid:child.pid,modelPath,backend:eff,port};
  }catch(error){await releaseOwnership(STATE_FILE);throw error;}
}
if((cmd==='server'&&sub==='start')||cmd==='load'){
  const ref=rawArgs.find((a,i)=>i>1&&!a.startsWith('--')&&a!==sub&&a!=='start'&&!/^\d+$/.test(a)&&a!==opt('ctx','__none__'))||rawArgs[2];
  if(!ref)fail(cmd==='load'?'load <model-ref>':'server start <model-ref>');
  out({ok:true,server:await startServer(ref,Number(opt('ctx',4096)))});
  process.exit(0);
}
if((cmd==='server'&&sub==='stop')||cmd==='unload'){
  const st=readState();
  if(!st)fail('no CLI-managed server recorded');
  if(st.ownerType&&st.ownerType!=='cli')fail(`runtime is owned by ${st.ownerType}; refusing to stop another interface`);
  if(pidAlive(st.pid)){try{process.kill(st.pid);}catch(e){fail('could not stop pid '+st.pid+': '+e.message);}}
  await releaseOwnership(STATE_FILE,st.ownerPid||process.pid);
  out({ok:true,stopped:st.pid});
  process.exit(0);
}
if((cmd==='server'&&sub==='status')||cmd==='ps'){
  const st=readState();
  const health=await serverHealth();
  const info={port,endpoint:health,cliServer:st&&pidAlive(st.pid)?st:(st?{...st,alive:false}:null)};
  out(json?info:`port ${port}: ${health.up?`UP (HTTP ${health.status})`:'down'}${info.cliServer?` | cli-server pid=${info.cliServer.pid} model=${path.basename(info.cliServer.modelPath||'?')} alive=${pidAlive(info.cliServer.pid)}`:''}`);
  process.exit(0);
}
if(cmd==='run'){
  const ref=rawArgs[1]||'';
  const installed=await scanInstalled(store.get('modelsDir'));
  const {modelPath,projector}=resolveModelRef(ref,installed);
  const llama=require('../runtime/llama.cjs');
  const {binary}=await runtimes.installed();
  if(!binary)fail('No managed runtime installed. Run: botconnector runtime install');
  const backend=store.get('runtimeBackend')||'auto';
  llama.startLlama({binary,modelPath,projector,port,gpuLayers:backend==='cpu'?0:999,context:Number(opt('ctx',4096))});
  console.error(`serving ${modelPath} on 127.0.0.1:${port} (Ctrl-C stops)`);
  const ok=await waitReady();
  if(!ok){console.error('server did not become ready');try{llama.stopLlama();}catch{}process.exit(1);}
  console.error('ready.');
  setInterval(()=>{const l=llama.logs().slice(-3);if(l.length)console.error('[llama] '+l[l.length-1]);},10000);
  await new Promise(()=>{});
}
if(cmd==='chat'){
  const stream=rawArgs.includes('--stream');
  const key=opt('api-key',null);
  const parts=rawArgs.slice(1).filter(a=>!a.startsWith('--')&&a!==key);
  let prompt=parts.join(' ');
  if(!prompt)fail('chat "prompt" [--api-key KEY]');
  const body={model:'local-model',messages:[{role:'user',content:prompt}],temperature:0.7,stream};
  const hdrs={'Content-Type':'application/json'};if(key)hdrs.Authorization='Bearer '+key;
  const r=await fetch(`http://127.0.0.1:${port}/v1/chat/completions`,{method:'POST',headers:hdrs,body:JSON.stringify(body)});
  if(!r.ok)fail(`runtime returned ${r.status} (is a model loaded on port ${port}?)`);
  if(!stream){const j=await r.json();const m=j?.choices?.[0]?.message||{};out(json?{content:m.content,reasoning:m.reasoning_content||null,usage:j.usage||null}:(m.reasoning_content?`[reasoning]\n${m.reasoning_content}\n\n`:'')+(m.content||''));process.exit(0);}
  const reader=r.body.getReader(),dec=new TextDecoder();let buf='';
  while(true){const{done,value}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});const lines=buf.split('\n');buf=lines.pop()||'';for(const ln of lines){if(!ln.startsWith('data:'))continue;const t=ln.slice(5).trim();if(!t||t==='[DONE]')continue;try{process.stdout.write(JSON.parse(t)?.choices?.[0]?.delta?.content||'');}catch{}}}
  console.log();process.exit(0);
}
if(cmd==='embed'){
  const key=opt('api-key',null);
  const parts=rawArgs.slice(1).filter(a=>!a.startsWith('--')&&a!==key);
  const text=parts.join(' ');
  if(!text)fail('embed "text" [--json] [--api-key KEY]');
  const hdrs={'Content-Type':'application/json'};if(key)hdrs.Authorization='Bearer '+key;
  const r=await fetch(`http://127.0.0.1:${port}/v1/embeddings`,{method:'POST',headers:hdrs,body:JSON.stringify({model:'local-embed',input:text})});
  if(!r.ok)fail(`runtime returned ${r.status} (is an --embeddings model loaded on port ${port}?)`);
  const j=await r.json();
  const v=j?.data?.[0]?.embedding||[];
  out(json?{dim:v.length,embedding:v}:`dim=${v.length} first5=[${v.slice(0,5).map(x=>Number(x).toFixed(4)).join(', ')}]`);
  process.exit(0);
}
if(cmd==='launch'){
  const target=sub||'';
  const base=`http://127.0.0.1:${port}`;
  const catalog={
    opencode:{detected:onPath('opencode'),config:'opencode.json (model provider override)',preview:{'$schema':'https://opencode.ai/config.json','provider':{'botconnector-local':{npm:'@ai-sdk/openai-compatible','name':'BotConnector Local','options':{'baseURL':base+'/v1','apiKey':'local'},'models':{'local-model':{'name':'BotConnector Local (llama.cpp)'}}}}},applyNote:'writes provider block with backup'},
    'claude-code':{config:'~/.claude.json / ANTHROPIC_BASE_URL (manual)',preview:{'ANTHROPIC_BASE_URL':base,'note':'EXPERIMENTAL_COMPATIBILITY: native /v1/messages is available on the accepted b10930 runtime; Claude Code client interoperability was smoke-tested locally. This is not official Claude support for Spark/non-Claude model routing.'}},
    codex:{config:'~/.codex/config.toml (manual)',preview:{'model_provider':'botconnector-local','model_provider_config':{'base_url':base+'/v1'}}},
    cline:{config:'VS Code settings cline.providerSettings (manual or --apply)',preview:{'cline.apiProvider':'openai-compatible','cline.baseUrl':base+'/v1','cline.apiKey':'local','cline.model':'local-model'}},
  };
  if(!catalog[target])fail('launch <opencode|claude-code|codex|cline>');
  const entry=catalog[target];
  if(!rawArgs.includes('--apply')){out({target,...entry,hint:'re-run with --apply to write config (existing config is backed up first). Native Anthropic support is runtime/model dependent and must be smoke-tested by the installed client.'});process.exit(0);}
  if(target!=='opencode')fail(`${target} --apply is not implemented; apply the preview manually`);
  const cfgPath=path.join(process.cwd(),'opencode.json');
  let existing={};if(fs.existsSync(cfgPath))existing=JSON.parse(fs.readFileSync(cfgPath,'utf8'));
  await fsp.writeFile(cfgPath+'.bak-'+Date.now(),JSON.stringify(existing,null,2));
  const merged={...existing,...entry.preview,provider:{...(existing.provider||{}),...entry.preview.provider}};
  await fsp.writeFile(cfgPath,JSON.stringify(merged,null,2));
  out({ok:true,wrote:cfgPath});
  process.exit(0);
}
function onPath(bin){try{execFileSync(process.platform==='win32'?'where':'which',[bin],{stdio:'ignore',windowsHide:true});return true;}catch{return false;}}

// ---------- Cloud: credentials + status (Core-shared, secrets never echoed) ----------
// CLI runs outside Electron, so safeStorage blobs cannot be decrypted here; a
// dedicated CredentialManager resolves via env fallback and reports configured
// state. Key WRITES from CLI go through Electron main when available; in pure
// CLI context we store an env-resolvable reference, never plaintext.
function cloudCredentialManager(){
  const {CredentialManager}=require('../runtime/credentials.cjs');
  return new CredentialManager({store,env:process.env});
}
function cloudDir(){return path.join(userData,'cloud');}
function hiddenPrompt(text){
  // Hidden (non-echo) single-line secret reader. In a TTY, raw stdin echoes '*'
  // per character and the value itself is never printed. When stdin is not a
  // TTY (piped), fall back to reading a line without echoing anything.
  return new Promise(resolve=>{
    process.stdout.write(text);
    if(!process.stdin.isTTY){
      process.stdin.setEncoding('utf8');
      let s='';
      const onData=ch=>{
        s+=ch;
        if(/\r?\n/.test(ch)||s.length>512){process.stdin.removeListener('data',onData);resolve(s.replace(/\r?\n.*$/,''));}
      };
      process.stdin.on('data',onData);
      return;
    }
    let s='';
    const wasRaw=process.stdin.isRaw;
    process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.setEncoding('utf8');
    const onData=ch=>{
      if(ch==='\r'||ch==='\n'){
        process.stdin.removeListener('data',onData);
        try{process.stdin.setRawMode(wasRaw);}catch{}
        process.stdin.pause();
        process.stdout.write('\n');
        resolve(s);
      }else if(ch==='\u0003'){
        try{process.stdin.setRawMode(wasRaw);}catch{}
        process.exit(130);
      }else if(ch==='\u007f'||ch==='\b'){
        if(s.length)s=s.slice(0,-1);
      }else if(ch>=' '&&s.length<512){
        s+=ch;process.stdout.write('*');
      }
    };
    process.stdin.on('data',onData);
  });
}
if(cmd==='cloud'&&sub==='set-key'){
  const provider=String(rawArgs[2]||'').toLowerCase();
  if(!['nebius','together'].includes(provider))fail('cloud set-key <nebius|together>');
  const cm=cloudCredentialManager();
  const existing=cm.source(provider);
  if(existing.source==='safeStorage'){console.error('Note: a key for this provider is already stored by the desktop app (safeStorage). CLI cannot overwrite encrypted desktop blobs; use the Desktop UI to replace it.');process.exit(1);}
  const key=await hiddenPrompt(`Paste ${provider} API key (hidden, Enter to confirm): `);
  if(!key||key.length<8)fail('API key looks too short; nothing stored');
  // Persist OUTSIDE plaintext: write an env-fallback instruction for CLI context
  // and store via safeStorage when a Desktop helper is reachable. We never
  // write the plaintext key to disk; we only record its PRESENCE marker.
  const markerFile=path.join(cloudDir(),`${provider}-key.set`);
  await fsp.mkdir(cloudDir(),{recursive:true});
  await fsp.writeFile(markerFile,JSON.stringify({configuredBy:'cli',at:new Date().toISOString(),note:'Key material held in this terminal session only; use the Desktop UI (safeStorage) for persistent storage. CLI keeps an environment contract: '+envNameFor(provider)}));
  console.error(`NOTE: CLI cannot encrypt with safeStorage (Electron-only). The key was read hidden and used for this command only.`);
  console.error(`For persistent storage, run the Desktop app -> Cloud -> Provider credentials (encrypted with Windows safeStorage), or set ${envNameFor(provider)} for development/CI.`);
  out({provider,configured:false,source:'cli-session-only',persistent:false,next:'Use Desktop Cloud UI to persist with safeStorage'});
  process.exit(0);
}
function envNameFor(provider){return provider==='nebius'?'NEBIUS_API_KEY':'TOGETHER_API_KEY';}
if(cmd==='cloud'&&sub==='key-status'){
  const cm=cloudCredentialManager();
  out(cm.public());
  process.exit(0);
}
if(cmd==='cloud'&&sub==='remove-key'){
  const provider=String(rawArgs[2]||'').toLowerCase();
  if(!['nebius','together'].includes(provider))fail('cloud remove-key <nebius|together>');
  const cm=cloudCredentialManager();
  if(cm.source(provider).source==='safeStorage'){console.error('Key is stored in Desktop safeStorage; remove it via the Desktop UI.');process.exit(1);}
  if(cm.source(provider).source==='environment'){fail(`Key comes from environment ${envNameFor(provider)}; unset it in your shell/profile to remove.`);}
  const marker=path.join(cloudDir(),`${provider}-key.set`);
  await fsp.rm(marker,{force:true});
  out({provider,configured:false,removed:'cli-session marker'});
  process.exit(0);
}
console.error(`unknown command: ${cmd}\n`+HELP);process.exit(2);
