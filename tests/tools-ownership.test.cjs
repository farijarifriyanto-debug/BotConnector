const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const fsSync=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {calculate,executeAllowedTool,TOOL_DEFINITIONS}=require('../runtime/tools.cjs');
const {claimOwnership,setChild,readOwnership,releaseOwnership}=require('../runtime/ownership.cjs');
const {appUrl,isSafeExternal,isTrustedNavigation,isTrustedSender}=require('../desktop/security.cjs');

test('allowlisted calculator is structured, safe, and deterministic',()=>{
  assert.equal(TOOL_DEFINITIONS[0].function.name,'calculator');
  assert.equal(calculate('27 + 15'),42);
  assert.equal(calculate('(10 - 4) * 3'),18);
  assert.equal(executeAllowedTool({function:{name:'calculator',arguments:'{"expression":"27 + 15"}'}}).result.value,42);
  assert.equal(executeAllowedTool({function:{name:'powershell',arguments:'{"command":"dir"}'}}).ok,false);
  assert.equal(executeAllowedTool({function:{name:'calculator',arguments:'{"expression":"process.exit()"}'}}).ok,false);
  assert.equal(executeAllowedTool({function:{name:'calculator',arguments:'not-json'} }).ok,false);
  assert.throws(()=>calculate('1/0'),/Division by zero/);
});

test('runtime ownership is atomic and releases only its owner',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'botconnector-owner-'));const file=path.join(dir,'runtime-process.json');
  await claimOwnership({file,ownerType:'test',ownerPid:process.pid,port:19999,modelPath:'model'});
  await assert.rejects(()=>claimOwnership({file,ownerType:'other',ownerPid:process.pid+1,port:19999,modelPath:'model'}),/owned by test/);
  await setChild(file,process.pid);assert.equal((await readOwnership(file)).childPid,process.pid);
  assert.equal(await releaseOwnership(file,process.pid+1),false);
  assert.equal(await releaseOwnership(file,process.pid),true);
  await fs.rm(dir,{recursive:true,force:true});
});

test('Electron security invariants and narrow IPC boundary',()=>{
  const main=fsSync.readFileSync(path.join(__dirname,'..','desktop','main.cjs'),'utf8');
  const preload=fsSync.readFileSync(path.join(__dirname,'..','desktop','preload.cjs'),'utf8');
  const html=fsSync.readFileSync(path.join(__dirname,'..','desktop','index.html'),'utf8');
  assert.match(main,/contextIsolation:true/);assert.match(main,/nodeIntegration:false/);assert.match(main,/sandbox:true/);assert.match(main,/webSecurity:true/);assert.match(main,/allowRunningInsecureContent:false/);
  assert.doesNotMatch(main,/sandbox:false|nodeIntegration:true|contextIsolation:false|unsafe-eval|unsafe-inline/);
  assert.doesNotMatch(main,/ipcMain\.handle\(/);assert.match(main,/function handle\(channel,listener\)/);assert.match(main,/isTrustedSender\(event,win\?\.webContents\)/);
  assert.match(preload,/contextBridge\.exposeInMainWorld/);assert.doesNotMatch(preload,/exposeInMainWorld\([^,]+,\s*\{[^}]*fs|exposeInMainWorld\([^,]+,\s*\{[^}]*child_process/);
  assert.match(main,/providerName\(provider\)/);assert.match(main,/plainObject\(input\)/);assert.match(main,/plainObject\(partial\)/);
  assert.match(html,/Content-Security-Policy/);assert.doesNotMatch(html,/unsafe-eval|unsafe-inline|default-src \*/);
  assert.equal(isSafeExternal('https://github.com/ggml-org/llama.cpp'),true);assert.equal(isSafeExternal('https://evil.github.com/'),false);assert.equal(isSafeExternal('file:///etc/passwd'),false);assert.equal(isSafeExternal('javascript:alert(1)'),false);assert.equal(isSafeExternal('data:text/html,x'),false);
  assert.equal(isTrustedNavigation(appUrl()),true);assert.equal(isTrustedNavigation('file:///tmp/other.html'),false);
  const sender={};assert.equal(isTrustedSender({sender,senderFrame:{url:appUrl()}},sender),true);assert.equal(isTrustedSender({sender:{},senderFrame:{url:appUrl()}},sender),false);assert.equal(isTrustedSender({sender,senderFrame:{url:'file:///tmp/other.html'}},sender),false);
});
