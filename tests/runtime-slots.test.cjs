const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
// Isolated lock so this file can run in parallel with tools-ownership.test.cjs.
process.env.BOTCONNECTOR_RUNTIME_LOCK=path.join(os.tmpdir(),`botconnector-test-lock-${process.pid}.lock`);
const {claimOwnership,claimModelSlot,readOwnership,setChild,releaseOwnership,releaseModelSlot,listModelSlots,normalizeState}=require('../runtime/ownership.cjs');

async function tmpFile(){
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'botconnector-slots-'));
  return {dir,file:path.join(dir,'runtime-process.json')};
}

test('per-model slots: second model is rejected with a switch hint',async()=>{
  const {dir,file}=await tmpFile();
  await claimModelSlot({file,ownerType:'cli',ownerPid:process.pid,port:11435,modelPath:'/models/a.gguf',backend:'cpu'});
  await assert.rejects(
    ()=>claimModelSlot({file,ownerType:'cli',ownerPid:process.pid+1,port:11435,modelPath:'/models/b.gguf',backend:'cpu'}),
    /server switch/
  );
  await fs.rm(dir,{recursive:true,force:true});
});

test('per-model slots: same-model foreign owner keeps legacy message',async()=>{
  const {dir,file}=await tmpFile();
  await claimOwnership({file,ownerType:'cli',ownerPid:process.pid,port:11435,modelPath:'/models/a.gguf'});
  await assert.rejects(
    ()=>claimOwnership({file,ownerType:'desktop',ownerPid:process.pid+1,port:11435,modelPath:'/models/a.gguf'}),
    /owned by cli/
  );
  await fs.rm(dir,{recursive:true,force:true});
});

test('per-model slots: release one model frees the other to claim',async()=>{
  const {dir,file}=await tmpFile();
  await claimModelSlot({file,ownerType:'cli',ownerPid:process.pid,port:11435,modelPath:'/models/a.gguf'});
  await setChild(file,process.pid);
  assert.equal((await listModelSlots(file)).length,1);
  assert.equal(await releaseModelSlot(file,'/models/a.gguf',process.pid),true);
  await claimModelSlot({file,ownerType:'cli',ownerPid:process.pid,port:11435,modelPath:'/models/b.gguf'});
  const slots=await listModelSlots(file);
  assert.equal(slots.length,1);
  assert.equal(slots[0].modelPath,'/models/b.gguf');
  await fs.rm(dir,{recursive:true,force:true});
});

test('per-model slots: legacy top-level fields mirror the active slot',async()=>{
  const {dir,file}=await tmpFile();
  await claimModelSlot({file,ownerType:'desktop',ownerPid:process.pid,port:11435,modelPath:'/models/a.gguf',backend:'vulkan'});
  const s=await readOwnership(file);
  assert.equal(s.ownerType,'desktop');
  assert.equal(s.modelPath,'/models/a.gguf');
  assert.equal(s.activeModel,'/models/a.gguf');
  assert.ok(s.models['/models/a.gguf']);
  await fs.rm(dir,{recursive:true,force:true});
});

test('per-model slots: legacy files without a map are migrated',()=>{
  const s=normalizeState({ownerType:'cli',ownerPid:123,port:11435,modelPath:'/models/old.gguf'});
  assert.ok(s.models['/models/old.gguf']);
  assert.equal(s.activeModel,'/models/old.gguf');
});

test('per-model slots: release only removes the caller-owned slot',async()=>{
  const {dir,file}=await tmpFile();
  await claimModelSlot({file,ownerType:'cli',ownerPid:process.pid,port:11435,modelPath:'/models/a.gguf'});
  assert.equal(await releaseModelSlot(file,'/models/a.gguf',process.pid+1),false);
  assert.equal(await releaseModelSlot(file,'/models/missing.gguf',process.pid),false);
  assert.equal(await releaseOwnership(file,process.pid+1),false);
  assert.equal(await releaseOwnership(file,process.pid),true);
  assert.deepEqual(await listModelSlots(file),[]);
  await fs.rm(dir,{recursive:true,force:true});
});
