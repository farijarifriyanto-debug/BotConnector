const fs=require('node:fs');
const fsp=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');

function pidAlive(pid){if(!Number.isInteger(Number(pid))||Number(pid)<=0)return false;try{process.kill(Number(pid),0);return true;}catch{return false;}}
function lockPath(){return process.env.BOTCONNECTOR_RUNTIME_LOCK||path.join(os.tmpdir(),'botconnector-ai-local-cloud-runtime.lock');}
function slotAlive(slot){if(!slot)return false;return slot.childPid!=null?pidAlive(slot.childPid):pidAlive(slot.ownerPid);}
function shortName(p){try{return String(p||'?').split(/[\\/]/).pop()||String(p);}catch{return String(p);}}
// Per-model registry (item 1: multi-model swap, opsi A). The state file keeps
// legacy top-level fields mirroring the ACTIVE slot so older readers
// (desktop/main.cjs, surface-consistency, CLI readState) keep working:
//   { ownerType, ownerPid, childPid, pid, port, modelPath, backend, auth,
//     startedAt, activeModel, models: { [modelPath]: slot } }
function normalizeState(raw){
  const s=(raw&&typeof raw==='object')?{...raw}:{};
  if(!s.models||typeof s.models!=='object'||Array.isArray(s.models))s.models={};
  if(!Object.keys(s.models).length&&s.modelPath){
    s.models[s.modelPath]={ownerType:s.ownerType,ownerPid:s.ownerPid,childPid:s.childPid??null,pid:s.pid??null,port:s.port,modelPath:s.modelPath,backend:s.backend,auth:s.auth,startedAt:s.startedAt};
  }
  if(!('activeModel' in s)||!(s.activeModel in s.models))s.activeModel=s.modelPath||Object.keys(s.models)[0]||null;
  return s;
}
function mirrorActive(s){
  const slot=s.activeModel?s.models[s.activeModel]:null;
  for(const k of ['ownerType','ownerPid','childPid','pid','port','modelPath','backend','auth','startedAt'])s[k]=slot?slot[k]??null:null;
  return s;
}
// Process state is ephemeral and shared by GUI/CLI on this machine. Keeping it
// in temp avoids mutating legacy state files owned by older installations and
// works on managed profiles that deny new files below Electron userData.
function statePath(){return process.env.BOTCONNECTOR_RUNTIME_STATE||path.join(os.tmpdir(),'botconnector-ai-local-cloud-runtime-process.json');}
async function readOwnership(file){try{return JSON.parse(await fsp.readFile(file,'utf8'));}catch{return null;}}
async function writeAtomic(file,value){const data=JSON.stringify(value,null,2);const tmp=`${file}.tmp-${process.pid}-${Date.now()}`;try{await fsp.writeFile(tmp,data,{mode:0o600});await fsp.rename(tmp,file);}catch(error){try{await fsp.rm(tmp,{force:true});}catch{}if(error.code!=='EPERM'&&error.code!=='EACCES')throw error;await fsp.writeFile(file,data);}}

async function claimOwnership({file,ownerType,ownerPid=process.pid,port,modelPath,backend,auth=false}){
  return claimModelSlot({file,ownerType,ownerPid,port,modelPath,backend,auth});
}

async function claimModelSlot({file,ownerType,ownerPid=process.pid,port,modelPath,backend,auth=false}){
  if(!modelPath)throw new Error('modelPath is required');
  await fsp.mkdir(path.dirname(file),{recursive:true});
  let handle;
  const lock=lockPath();
  try{handle=await fsp.open(lock,'wx');}
  catch(error){
    if(error.code==='EEXIST'){
      try{const owner=JSON.parse(await fsp.readFile(lock,'utf8'));if(!pidAlive(owner.pid)){await fsp.rm(lock,{force:true});handle=await fsp.open(lock,'wx');}}
      catch(retry){if(!handle)throw new Error('Runtime ownership is busy; another interface is starting or stopping the server');}
    }
    if(!handle)throw new Error('Runtime ownership is busy; another interface is starting or stopping the server');
  }
  try{
    const state=normalizeState(await readOwnership(file));
    const active=state.activeModel?state.models[state.activeModel]:null;
    if(slotAlive(active)){
      if(active.modelPath===modelPath){
        if(Number(active.ownerPid)!==Number(ownerPid))throw new Error(`Runtime is owned by ${active.ownerType||'another process'} (pid ${active.ownerPid})`);
      }else{
        throw new Error(`Model ${shortName(active.modelPath)} is running (owned by ${active.ownerType||'another process'}, pid ${active.ownerPid}). Stop it first with 'botconnector server stop', or switch with 'botconnector server switch <model-ref>'.`);
      }
    }
    const next={ownerType,ownerPid:Number(ownerPid),childPid:null,pid:null,port:Number(port),modelPath,backend,auth:Boolean(auth),startedAt:new Date().toISOString()};
    state.models[modelPath]=next;
    state.activeModel=modelPath;
    mirrorActive(state);
    await handle.truncate(0);await handle.writeFile(JSON.stringify({pid:Number(ownerPid)}));
    await writeAtomic(file,state);return {...next};
  }finally{try{await handle?.close();}catch{}try{await fsp.rm(lock,{force:true});}catch{}}
}

async function listModelSlots(file){
  const state=normalizeState(await readOwnership(file));
  return Object.values(state.models).map(s=>({...s,alive:slotAlive(s),active:state.activeModel===s.modelPath}));
}

async function releaseModelSlot(file,modelPath,ownerPid=process.pid){
  const state=normalizeState(await readOwnership(file));
  const slot=modelPath?state.models[modelPath]:(state.activeModel?state.models[state.activeModel]:null);
  if(!slot)return false;
  if(Number(slot.ownerPid)!==Number(ownerPid))return false;
  delete state.models[slot.modelPath];
  if(state.activeModel===slot.modelPath)state.activeModel=Object.keys(state.models)[0]||null;
  mirrorActive(state);
  await writeAtomic(file,state);return true;
}

async function setChild(file,childPid,extra={}){const state=normalizeState(await readOwnership(file));const key=state.activeModel;const current=key?state.models[key]:null;if(!current)return null;const next={...current,childPid:Number(childPid),...extra};state.models[key]=next;mirrorActive(state);await writeAtomic(file,state);return {...next};}
async function releaseOwnership(file,ownerPid=process.pid){const state=normalizeState(await readOwnership(file));const key=state.activeModel;const current=key?state.models[key]:null;if(!current)return false;if(Number(current.ownerPid)!==Number(ownerPid))return false;delete state.models[key];state.activeModel=Object.keys(state.models)[0]||null;mirrorActive(state);await writeAtomic(file,state);return true;}
function isOwner(file,ownerPid=process.pid){return readOwnership(file).then(s=>Boolean(s&&Number(s.ownerPid)===Number(ownerPid)));}

module.exports={claimOwnership,claimModelSlot,readOwnership,releaseOwnership,releaseModelSlot,listModelSlots,setChild,statePath,lockPath,pidAlive,slotAlive,normalizeState};
