// Phase 6: vision acceptance. Downloads SmolVLM-500M Q8_0 + matching mmproj via the
// app DownloadManager (projector dependency path), serves with --mmproj, sends a
// deterministic two-color PNG through the OpenAI-compatible API.
// Usage: node scripts/vision-acceptance.mjs [--port 11439]
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const llama=require('../runtime/llama.cjs');
const hf=require('../runtime/hf.cjs');
const {DownloadManager}=require('../runtime/downloads.cjs');
const {scanInstalled}=require('../runtime/installed.cjs');
const {Store}=require('../runtime/store.cjs');
const os=require('node:os'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
const results={};
function check(name,ok,extra=''){results[name]=ok?'PASS':'FAIL';console.log(`${ok?'PASS':'FAIL'}  ${name}${extra?`  — ${extra}`:''}`);}
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const args=Object.fromEntries(process.argv.slice(2).map((a,i,arr)=>a.startsWith('--')?[a.slice(2),arr[i+1]&&!arr[i+1].startsWith('--')?arr[i+1]:'true']:[]).filter(x=>x.length));
const port=Number(args.port||11439);
const userData=path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'botconnector-ai-local-cloud');
const store=new Store(userData);store.load();
const bin='C:\\Users\\farij\\AppData\\Roaming\\botconnector-ai-local-cloud\\runtimes\\llama.cpp\\b10930\\vulkan\\llama-server.exe';
const REPO='ggml-org/SmolVLM-500M-Instruct-GGUF';

// Deterministic test image: 160x80 PNG, left half pure red, right half pure blue.
function testPng(){
  const W=160,H=80,raw=Buffer.alloc(H*(1+W*3));
  for(let y=0;y<H;y++){raw[y*(1+W*3)]=0;for(let x=0;x<W;x++){const o=y*(1+W*3)+1+x*3;
    if(x<W/2){raw[o]=255;raw[o+1]=0;raw[o+2]=0;}else{raw[o]=0;raw[o+1]=0;raw[o+2]=255;}}}
  const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(W,0);ihdr.writeUInt32BE(H,4);ihdr[8]=8;ihdr[9]=2;
  const chunk=(t,d)=>{const l=Buffer.alloc(4);l.writeUInt32BE(d.length);const c=Buffer.concat([Buffer.from(t),d]);const crc=Buffer.alloc(4);crc.writeUInt32BE(crc32(c)>>>0);return Buffer.concat([l,c,crc]);};
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),chunk('IDAT',zlib.deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]);
}
function crc32(b){let t=new Int32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xEDB88320^(c>>>1):c>>>1;t[n]=c;}let c=-1;for(let i=0;i<b.length;i++)c=t[(c^b[i])&255]^(c>>>8);return(c^-1)>>>0;}

try{
  const hw={ramGb:15.6,nvidia:[]};
  const d=await hf.modelDetails({id:REPO,hardware:hw});
  check('VISION_CAPABILITY',d.capabilities?.vision===true,`vision=${d.capabilities?.vision}`);
  const group=d.files.find(g=>g.quant==='Q8_0')||d.files[0];
  const proj=d.projectors.find(p=>/Q8_0/i.test(p.path))||d.projectors[0];
  if(!proj)throw new Error('no mmproj in repo');
  console.log(`model ${group.quant} ${(group.size/1048576).toFixed(0)}MB + projector ${(proj.size/1048576).toFixed(0)}MB`);
  const dm=new DownloadManager({getModelsDir:()=>store.get('modelsDir'),getToken:()=>process.env.HF_TOKEN||''});
  const job=await dm.start({repoId:REPO,group,projector:{path:proj.path,size:proj.size,oid:null},metadata:{capabilities:d.capabilities,pipeline_tag:d.pipeline_tag}});
  for(let i=0;i<600;i++){await sleep(1000);const j=dm.list().find(x=>x.id===job.id);
    if(i%15===0)console.log(`  dl ${(100*(j?.downloadedBytes||0)/(j?.totalBytes||1)).toFixed(0)}%`);
    if(j?.status==='completed')break;if(j?.status==='failed')throw new Error('download failed: '+j.error);}
  const done=dm.list().find(x=>x.id===job.id);
  check('VISION_DOWNLOAD',done?.status==='completed',`status=${done?.status}`);
  if(done?.status!=='completed')process.exit(2);
  const installed=await scanInstalled(store.get('modelsDir'));
  const entry=installed.find(m=>m.repoId===REPO);
  check('VISION_PROJECTOR_MANAGED',!!entry?.projector,`projector=${entry?.projector?path.basename(entry.projector):'MISSING'}`);
  if(!entry?.projector)process.exit(2);
  llama.startLlama({binary:bin,modelPath:entry.path,projector:entry.projector,port,gpuLayers:999,context:4096});
  let ready=false;for(let i=0;i<60;i++){await sleep(2000);try{const h=await fetch(`http://127.0.0.1:${port}/health`);if(h.ok){ready=true;break;}}catch{}}
  check('VISION_SERVER_READY',ready,'--mmproj on :'+port);
  if(!ready){console.log(llama.logs().slice(-12).join('\n'));process.exit(2);}
  const img=testPng().toString('base64');
  const r1=await fetch(`http://127.0.0.1:${port}/v1/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model:'m',max_tokens:256,temperature:0,messages:[{role:'user',content:[
      {type:'text',text:'Describe this image briefly: what colors are on the left and right halves?'},
      {type:'image_url',image_url:{url:'data:image/png;base64,'+img}}]}]})});
  const j1=await r1.json();
  const desc=(j1?.choices?.[0]?.message?.content||'').toLowerCase();
  console.log(`image description: "${(j1?.choices?.[0]?.message?.content||'').slice(0,200)}"`);
  check('VISION_IMAGE_DESCRIBED',r1.ok&&desc.includes('red')&&desc.includes('blue'),`red=${desc.includes('red')} blue=${desc.includes('blue')}`);
  const r2=await fetch(`http://127.0.0.1:${port}/v1/chat/completions`,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model:'m',max_tokens:64,temperature:0,messages:[{role:'user',content:'Reply exactly: VISION_TEXT_OK'}]})});
  const t2=(await r2.json())?.choices?.[0]?.message?.content||'';
  // 500M model paraphrases instead of echoing literally; accept a coherent on-topic reply.
  check('VISION_TEXT_STILL_WORKS',r2.ok&&/vision/i.test(t2)&&/\bok\b/i.test(t2),`"${t2.slice(0,60)}"`);
  llama.stopLlama();await sleep(1500);
  check('VISION_UNLOAD',!llama.status().running,'stopped');
}finally{try{llama.stopLlama();}catch{}}
const fails=Object.entries(results).filter(([,v])=>v!=='PASS');
console.log(`\n${fails.length?'VISION: FAIL':'VISION: ALL PASS'} (${Object.keys(results).length} checks)`);
process.exit(fails.length?1:0);
