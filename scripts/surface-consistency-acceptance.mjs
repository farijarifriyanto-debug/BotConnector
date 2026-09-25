import {createRequire} from 'node:module';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const require=createRequire(import.meta.url);const {Store}=require('../runtime/store.cjs');const {scanInstalled}=require('../runtime/installed.cjs');const {readOwnership,statePath}=require('../runtime/ownership.cjs');
const os=require('node:os'),path=require('node:path');const execFileAsync=promisify(execFile);const results={};const check=(name,ok,extra='')=>{results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?`  — ${extra}`:''}`)};
const userData=path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'botconnector-ai-local-cloud'),store=new Store(userData);store.load();
try{
 const [modelsRes,health,cli]=await Promise.all([fetch('http://127.0.0.1:11435/v1/models'),fetch('http://127.0.0.1:11435/health'),execFileAsync(process.execPath,['bin/botconnector.mjs','runtime','status','--json'],{cwd:process.cwd(),shell:false,windowsHide:true})]);const models=await modelsRes.json();const installed=await scanInstalled(store.get('modelsDir'));const ownership=await readOwnership(statePath(userData));
 check('SURFACE_HTTP_API',modelsRes.ok&&health.ok,'local HTTP + /health');check('SURFACE_SHARED_MODEL_STORE',installed.some(m=>m.repoId==='XHToken/Spark-X2.5-4B-GGUF'),'Store modelsDir used by CLI/Desktop');check('SURFACE_CLI_STATE',JSON.parse(cli.stdout)?.installed?.installed===true,'CLI runtime status uses same managed runtime');check('SURFACE_OWNERSHIP',!ownership||ownership.ownerType==='cli'||ownership.ownerType==='desktop','shared ownership state is readable and typed');check('SURFACE_MCP_STORE',Array.isArray(store.get('mcpServers')),'MCP config is in shared Store');
}catch(e){console.error(e.stack||e);for(const name of ['SURFACE_HTTP_API','SURFACE_SHARED_MODEL_STORE','SURFACE_CLI_STATE','SURFACE_OWNERSHIP','SURFACE_MCP_STORE'])if(!results[name])results[name]='FAIL'}
const fails=Object.entries(results).filter(([,v])=>v!=='PASS');console.log(`\nDEVELOPER SURFACE CONSISTENCY: ${fails.length?'FAIL':'ALL PASS'} (${Object.keys(results).length} checks)`);process.exit(fails.length?1:0);
