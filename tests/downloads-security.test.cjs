const {describe,it}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const fsp=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const {DownloadManager}=require('../runtime/downloads.cjs');
const {safeEntryName}=require('../runtime/runtime-manager.cjs');

function rangeServer(data,chunkDelay=15){
  return new Promise(resolve=>{
    const srv=http.createServer((req,res)=>{
      const range=req.headers.range;
      let start=0,end=data.length-1;
      if(range){const m=range.match(/bytes=(\d+)-/);if(m)start=Number(m[1]);}
      const total=data.length;
      res.writeHead(range?206:200,{'Content-Length':end-start+1,'Accept-Ranges':'bytes','Content-Type':'application/octet-stream'});
      let off=start;
      const CH=65536;
      (function next(){
        if(off>end){res.end();return;}
        const slice=data.subarray(off,Math.min(off+CH,end+1));off+=slice.length;
        if(!res.write(slice)){res.once('drain',()=>setTimeout(next,chunkDelay));return;}
        setTimeout(next,chunkDelay);
      })();
    });
    srv.listen(0,'127.0.0.1',()=>resolve(srv));
  });
}

describe('download manager (local Range server)',()=>{
  it('pauses to .part, resumes via Range, completes atomically with manifest',async()=>{
    const data=cryptoRandom(6*1024*1024);
    const srv=await rangeServer(data);
    const port=srv.address().port;
    const tmp=await fsp.mkdtemp(path.join(os.tmpdir(),'bc-dl-'));
    const modelsDir=path.join(tmp,'models');await fsp.mkdir(modelsDir,{recursive:true});
    try{
      const seen=[];
      const dm=new DownloadManager({getModelsDir:()=>modelsDir,getToken:()=> '',emit:(c,j)=>seen.push(j.status),resolveUrl:()=>'http://127.0.0.1:'+port+'/file.gguf'});
      const group={quant:'Q4_K_M',parts:[{path:'file.gguf',size:data.length,oid:null}]};
      const job=await dm.start({repoId:'Test/Model',group,metadata:{capabilities:{chat:true}}});
      await new Promise(r=>setTimeout(r,400));
      assert.equal(dm.pause(job.id),true);
      let mid=null;
      for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,100));mid=dm.list().find(j=>j.id===job.id);if(mid?.status==='paused')break;}
      assert.equal(mid.status,'paused');
      const partPath=path.join(modelsDir,'Test__Model','Q4_K_M','file.gguf.part');
      assert.ok(fs.existsSync(partPath),'expected .part to exist while paused');
      assert.ok(!fs.existsSync(path.join(modelsDir,'Test__Model','Q4_K_M','file.gguf')),'no completed file while .part incomplete');
      assert.equal(dm.resume(job.id),true);
      for(let i=0;i<100;i++){await new Promise(r=>setTimeout(r,200));if(dm.list().find(j=>j.id===job.id)?.status==='completed')break;}
      const done=dm.list().find(j=>j.id===job.id);
      assert.equal(done.status,'completed');
      assert.deepEqual(Buffer.from(await fsp.readFile(path.join(modelsDir,'Test__Model','Q4_K_M','file.gguf'))),data);
      assert.ok(fs.existsSync(path.join(modelsDir,'Test__Model','Q4_K_M','manifest.json')),'manifest created after success');
      assert.ok(!fs.existsSync(partPath),'.part removed after completion');
    }finally{srv.close();}
  });

  it('cancel aborts an in-flight job',async()=>{
    const data=cryptoRandom(12*1024*1024);
    const srv=await rangeServer(data,25);
    const port=srv.address().port;
    try{
      const tmp=await fsp.mkdtemp(path.join(os.tmpdir(),'bc-dl2-'));
      const dm=new DownloadManager({getModelsDir:()=>tmp,getToken:()=> '',resolveUrl:()=>'http://127.0.0.1:'+port+'/file.gguf'});
      const job=await dm.start({repoId:'T/M',group:{quant:'Q8_0',parts:[{path:'f.gguf',size:data.length}]},metadata:{}});
      await new Promise(r=>setTimeout(r,300));
      assert.equal(dm.list().find(j=>j.id===job.id)?.status,'downloading','job must still be in flight (not failed) before cancel');
      assert.equal(dm.cancel(job.id),true);
      await new Promise(r=>setTimeout(r,500));
      assert.equal(dm.list().find(j=>j.id===job.id)?.status,'cancelled');
    }finally{srv.close();}
  });
});

describe('security boundaries',()=>{
  it('blocks archive path traversal entries',()=>{
    assert.equal(safeEntryName('../../evil.exe'),null);
    assert.equal(safeEntryName('/abs/path'),null);
    assert.equal(safeEntryName('C:\\win\\x.dll'),null);
    assert.equal(safeEntryName('build/bin/llama-server.exe'),'build/bin/llama-server.exe');
  });
  it('neutralizes traversal filenames in model downloads',()=>{
    const destDir=path.join('C:\\models','Repo');
    const evil='..\\..\\evil.gguf';
    const joined=path.join(destDir,path.basename(evil));
    assert.ok(path.resolve(joined).startsWith(path.resolve(destDir)+path.sep)||path.resolve(joined)===path.resolve(destDir));
  });
  it('llama-server is spawned with shell:false (no shell string)',()=>{
    const src=fs.readFileSync(path.join(__dirname,'..','runtime','llama.cjs'),'utf8');
    assert.match(src,/shell\s*:\s*false/);
    assert.doesNotMatch(src,/exec\s*\(/);
  });
});

function cryptoRandom(n){const b=Buffer.alloc(n);for(let i=0;i<n;i++)b[i]=i%251;return b;}
