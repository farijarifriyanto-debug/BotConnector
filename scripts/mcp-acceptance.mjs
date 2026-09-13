// Minimal MCP acceptance: one explicit stdio server, allowlisted tool, timeout,
// provenance, disabled-server behavior, and no shell execution.
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);const {McpClient}=require('../runtime/mcp.cjs');
const results={};const check=(n,ok,e='')=>{results[n]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${n}${e?`  — ${e}`:''}`);};
const fixture=fileURLToPath(new URL('../tests/fixtures/mcp-calculator-server.mjs',import.meta.url));
const server=new McpClient({name:'fixture-calculator',command:process.execPath,args:[fixture],enabled:true,allowedTools:['calculator'],timeoutMs:3000});
try{
  const listed=await server.listTools();check('MCP_SERVER_LIST',listed.length===1&&listed[0].name==='calculator',`tools=${listed.map(x=>x.name).join(',')}`);
  const result=await server.callTool('calculator',{expression:'27 + 15'});check('MCP_CONTROLLED_INVOCATION',result.server==='fixture-calculator'&&result.tool==='calculator'&&result.result?.content?.[0]?.text==='42',`result=${JSON.stringify(result)}`);
  await Promise.all([server.callTool('not-allowed',{}).then(()=>false,e=>/not allowlisted/.test(e.message)).then(ok=>check('MCP_ALLOWLIST',ok)),server.callTool('calculator',{expression:'27 + 15'}).then(r=>r.server==='fixture-calculator').then(ok=>check('MCP_PROVENANCE',ok))]);
}catch(error){console.error(error);check('MCP_UNEXPECTED_ERROR',false,error.message)}finally{await server.stop();}
const disabled=new McpClient({name:'disabled',command:process.execPath,args:[fixture],enabled:false,allowedTools:['calculator']});await disabled.callTool('calculator',{expression:'27 + 15'}).then(()=>check('MCP_DISABLED',false),e=>check('MCP_DISABLED',/disabled/.test(e.message)));
const failures=Object.values(results).filter(x=>x!=='PASS').length;console.log(`\n${failures?'MCP MINIMAL: FAIL':'MCP MINIMAL: ALL PASS'} (${Object.keys(results).length} checks)`);process.exit(failures?1:0);
