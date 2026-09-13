const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {calculate,executeAllowedTool,TOOL_DEFINITIONS}=require('../runtime/tools.cjs');
const {claimOwnership,setChild,readOwnership,releaseOwnership}=require('../runtime/ownership.cjs');

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
