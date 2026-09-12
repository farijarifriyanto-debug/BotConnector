const {app,BrowserWindow,ipcMain,dialog,shell,safeStorage}=require('electron');
const path=require('node:path');
const fs=require('node:fs');
const fsp=require('node:fs/promises');
const {detectHardware}=require('../runtime/hardware.cjs');
const llama=require('../runtime/llama.cjs');
const hf=require('../runtime/hf.cjs');
const {DownloadManager}=require('../runtime/downloads.cjs');
const {RuntimeManager}=require('../runtime/runtime-manager.cjs');
const {Store}=require('../runtime/store.cjs');
const {scanInstalled}=require('../runtime/installed.cjs');

let win=null, store=null, downloads=null, runtimes=null;
function emit(channel,payload){if(win&&!win.isDestroyed())win.webContents.send(channel,payload);}
function getToken(){
  const enc=store?.get('hfTokenEncrypted');
  if(!enc||!safeStorage.isEncryptionAvailable())return '';
  try{return safeStorage.decryptString(Buffer.from(enc,'base64'));}catch{return '';}
}
function publicSettings(){const d=store.public();delete d.hfToken;delete d.hfTokenEncrypted;return {...d,hfTokenConfigured:Boolean(store.get('hfTokenEncrypted'))};}
function createWindow(){
  win=new BrowserWindow({width:1460,height:920,minWidth:1100,minHeight:720,backgroundColor:'#080b10',title:'BotConnector AI',autoHideMenuBar:true,webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:false}});
  win.loadFile(path.join(__dirname,'index.html'));
}
function isSafeExternal(raw){try{const u=new URL(String(raw));return u.protocol==='https:'&&['huggingface.co','github.com','lmstudio.ai'].includes(u.hostname);}catch{return false;}}

app.whenReady().then(async()=>{
  store=new Store(app.getPath('userData'));store.load();
  downloads=new DownloadManager({getModelsDir:()=>store.get('modelsDir'),getToken,emit});
  runtimes=new RuntimeManager({baseDir:path.join(app.getPath('userData'),'runtimes','llama.cpp'),emit});
  createWindow();
  app.on('activate',()=>{if(BrowserWindow.getAllWindows().length===0)createWindow();});
});
app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit();});

ipcMain.handle('system:overview',async()=>{
  const hardware=await detectHardware();
  return {hardware,runtime:llama.status(),preferredLanguages:app.getPreferredSystemLanguages(),settings:publicSettings(),managedRuntime:await runtimes.installed(),installed:await scanInstalled(store.get('modelsDir')),downloads:downloads.list()};
});
ipcMain.handle('system:open-external',async(_e,url)=>{if(!isSafeExternal(url))throw new Error('External URL is not allowed');await shell.openExternal(String(url));return true;});

ipcMain.handle('settings:get',async()=>publicSettings());
ipcMain.handle('settings:set',async(_e,input)=>{const allowed=['runtimeBackend','language'];for(const k of allowed)if(k in(input||{}))await store.set(k,input[k]);return publicSettings();});
ipcMain.handle('settings:set-hf-token',async(_e,token)=>{token=String(token||'').trim();if(!token){await store.set('hfTokenEncrypted','');return {configured:false};}if(!safeStorage.isEncryptionAvailable())throw new Error('Windows credential encryption is unavailable');const enc=safeStorage.encryptString(token).toString('base64');await store.set('hfTokenEncrypted',enc);return {configured:true};});
ipcMain.handle('settings:pick-models-dir',async()=>{const r=await dialog.showOpenDialog({properties:['openDirectory','createDirectory'],title:'Choose model storage directory'});if(r.canceled)return null;await store.set('modelsDir',r.filePaths[0]);return {modelsDir:r.filePaths[0],installed:await scanInstalled(r.filePaths[0])};});

ipcMain.handle('models:search-online',async(_e,input)=>{const hardware=await detectHardware();return hf.searchModels({...input,hardware,token:getToken()});});
ipcMain.handle('models:details',async(_e,id)=>{const hardware=await detectHardware();return hf.modelDetails({id,hardware,token:getToken()});});
ipcMain.handle('models:installed',async()=>scanInstalled(store.get('modelsDir')));
ipcMain.handle('models:reveal',async(_e,p)=>{if(!p)return false;shell.showItemInFolder(String(p));return true;});
ipcMain.handle('models:delete',async(_e,dir)=>{const root=path.resolve(store.get('modelsDir'));const target=path.resolve(String(dir||''));if(!target.startsWith(root+path.sep))throw new Error('Refusing to delete outside model directory');if(llama.status().running&&path.resolve(llama.status().modelPath||'').startsWith(target+path.sep))throw new Error('Stop the runtime before deleting this model');await fsp.rm(target,{recursive:true,force:true});return scanInstalled(root);});
ipcMain.handle('models:download',async(_e,payload)=>downloads.start(payload));
ipcMain.handle('downloads:list',async()=>downloads.list());
ipcMain.handle('downloads:pause',async(_e,id)=>({ok:downloads.pause(id)}));
ipcMain.handle('downloads:resume',async(_e,id)=>({ok:downloads.resume(id)}));
ipcMain.handle('downloads:cancel',async(_e,id)=>({ok:downloads.cancel(id)}));

ipcMain.handle('runtime:pick-binary',async()=>{const r=await dialog.showOpenDialog({properties:['openFile'],filters:[{name:'llama-server',extensions:['exe']} ]});return r.canceled?null:r.filePaths[0];});
ipcMain.handle('runtime:pick-model',async()=>{const r=await dialog.showOpenDialog({properties:['openFile'],filters:[{name:'GGUF',extensions:['gguf']} ]});return r.canceled?null:r.filePaths[0];});
ipcMain.handle('runtime:latest',async()=>runtimes.latest());
ipcMain.handle('runtime:resolve',async(_e,cfg)=>runtimes.resolveBackend(cfg?.backend||'vulkan'));
ipcMain.handle('runtime:verify',async()=>runtimes.verifyInstalled());
ipcMain.handle('runtime:managed-status',async()=>runtimes.installed());
ipcMain.handle('runtime:install',async(_e,cfg)=>runtimes.install(cfg||{}));
ipcMain.handle('runtime:start',async(_e,cfg)=>llama.startLlama(cfg));
ipcMain.handle('runtime:start-installed',async(_e,cfg)=>{
  const managed=await runtimes.installed();const binary=cfg.binary||managed.binary;if(!binary)throw new Error('No llama.cpp runtime installed. Install a managed runtime first.');
  const backend=cfg.backend||store.get('runtimeBackend')||'auto';const gpuLayers=backend==='cpu'?0:999;
  return llama.startLlama({binary,modelPath:cfg.modelPath,projector:cfg.projector||null,port:Number(cfg.port||11435),gpuLayers,context:Number(cfg.context||8192),embedding:Boolean(cfg.embedding),jinja:true});
});
ipcMain.handle('runtime:stop',async()=>({stopped:llama.stopLlama()}));
ipcMain.handle('runtime:status',async()=>llama.status());
ipcMain.handle('runtime:logs',async()=>llama.logs());

ipcMain.handle('chat:complete',async(_e,messages)=>{
  const rt=llama.status();if(!rt.running)throw new Error('Local runtime is not running');const res=await fetch(`http://127.0.0.1:${rt.port||11435}/v1/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer local'},body:JSON.stringify({model:'local-model',messages,temperature:.7,stream:false})});const data=await res.json().catch(()=>({}));if(!res.ok)throw new Error(data?.error?.message||`Runtime returned ${res.status}`);const msg=data?.choices?.[0]?.message||{};return {content:msg.content||'',reasoning:msg.reasoning_content||null,usage:data?.usage||null};
});
ipcMain.handle('chat:pick-image',async()=>{const r=await dialog.showOpenDialog({properties:['openFile'],filters:[{name:'Images',extensions:['png','jpg','jpeg','webp','gif']} ]});if(r.canceled)return null;const p=r.filePaths[0],b=await fsp.readFile(p);const ext=path.extname(p).slice(1).toLowerCase().replace('jpg','jpeg');return {name:path.basename(p),dataUrl:`data:image/${ext};base64,${b.toString('base64')}`};});

ipcMain.on('chat:stream',async(event,{requestId,messages,options={}})=>{
  const rt=llama.status();if(!rt.running){event.sender.send('chat:error',{requestId,error:'Local runtime is not running'});return;}
  try{
    const res=await fetch(`http://127.0.0.1:${rt.port||11435}/v1/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer local'},body:JSON.stringify({model:'local-model',messages,temperature:Number(options.temperature??.7),stream:true})});
    if(!res.ok)throw new Error(`Runtime returned ${res.status}`);
    const reader=res.body.getReader();const dec=new TextDecoder();let buf='';
    while(true){const {done,value}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});const lines=buf.split(/\r?\n/);buf=lines.pop()||'';for(const line of lines){if(!line.startsWith('data:'))continue;const raw=line.slice(5).trim();if(!raw||raw==='[DONE]')continue;try{const j=JSON.parse(raw);const delta=j?.choices?.[0]?.delta||{};if(delta.content)event.sender.send('chat:delta',{requestId,delta:delta.content});if(delta.reasoning_content)event.sender.send('chat:reasoning',{requestId,delta:String(delta.reasoning_content)});if(Array.isArray(delta.tool_calls))for(const tc of delta.tool_calls)event.sender.send('chat:toolcall',{requestId,toolCall:tc});}catch{}}}
    event.sender.send('chat:done',{requestId});
  }catch(e){event.sender.send('chat:error',{requestId,error:String(e.message||e)});}
});
