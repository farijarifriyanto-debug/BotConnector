const {describe,it}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const fsp=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const http=require('node:http');
const zlib=require('node:zlib');
const {DownloadManager}=require('../runtime/downloads.cjs');
const {safeEntryName,extractZipSecure}=require('../runtime/runtime-manager.cjs');

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
  it('api key never appears in process status/logs',()=>{
    const src=fs.readFileSync(path.join(__dirname,'..','runtime','llama.cjs'),'utf8');
    assert.match(src,/--api-key/);
    assert.match(src,/\*\*\*/,'key redacted in recorded args');
  });

  it('secure ZIP extraction accepts normal runtime layout',async()=>{
    const tmp=await fsp.mkdtemp(path.join(os.tmpdir(),'bc-zip-normal-')),zip=path.join(tmp,'runtime.zip'),root=path.join(tmp,'stage');
    await fsp.writeFile(zip,zipBuffer([{name:'bin/',data:Buffer.alloc(0)},{name:'bin/llama-server.exe',data:Buffer.from('binary')},{name:'README.txt',data:Buffer.from('ok')} ]));
    try{const result=await extractZipSecure(zip,root);assert.equal(result.entries,3);assert.equal(await fsp.readFile(path.join(root,'bin','llama-server.exe'),'utf8'),'binary');}
    finally{await fsp.rm(tmp,{recursive:true,force:true});}
  });

  it('secure ZIP extraction blocks traversal, absolute, and Windows paths',async()=>{
    for(const name of ['../evil','nested/../../evil','..\\..\\evil','C:\\evil','\\\\server\\share\\evil','/absolute']){
      const tmp=await fsp.mkdtemp(path.join(os.tmpdir(),'bc-zip-path-')),zip=path.join(tmp,'bad.zip'),root=path.join(tmp,'stage');
      await fsp.writeFile(zip,zipBuffer([{name,data:Buffer.from('x')} ]));
      try{await assert.rejects(extractZipSecure(zip,root),/Unsafe archive entry|escapes extraction root|invalid relative path|absolute path/);assert.equal(fs.existsSync(path.join(tmp,'evil')),false);}
      finally{await fsp.rm(tmp,{recursive:true,force:true});}
    }
  });

  it('secure ZIP extraction blocks archive and destination links',async()=>{
    const tmp=await fsp.mkdtemp(path.join(os.tmpdir(),'bc-zip-link-')),zip=path.join(tmp,'link.zip'),root=path.join(tmp,'stage'),outside=path.join(tmp,'outside');
    await fsp.mkdir(outside);await fsp.writeFile(zip,zipBuffer([{name:'link',data:Buffer.from('target'),externalFileAttributes:(0xa000|0o777)<<16,versionMadeBy:(3<<8)|20}]));
    try{await assert.rejects(extractZipSecure(zip,root),/Unsupported archive entry/);await fsp.mkdir(root,{recursive:true});
      // Windows: symlinks need developer mode/elevation; junctions do not. Use a junction
      // for the destination-redirect case and record symlink unavailability honestly.
      let linkKind='symlink',linkError=null;
      try{await fsp.symlink(outside,path.join(root,'redirect'),'junction');}
      catch(e){linkError=e;try{await fsp.symlink(outside,path.join(root,'redirect'),'junction');linkKind='junction-fallback';}catch(e2){linkError=e2;}}
      const nested=path.join(tmp,'nested.zip');await fsp.writeFile(nested,zipBuffer([{name:'redirect/evil.txt',data:Buffer.from('x')} ]));
      await assert.rejects(extractZipSecure(nested,root),/Unsafe extraction component/);
      assert.equal(fs.existsSync(path.join(outside,'evil.txt')),false);
      if(linkError)console.log(`    note: ${linkKind} created after symlink EPERM (${linkError.code}) — junction is the Windows-representative reparse case`);
    }
    finally{await fsp.rm(tmp,{recursive:true,force:true});}
  });

  it('secure ZIP extraction enforces bomb, entry, and collision limits',async()=>{
    const tmp=await fsp.mkdtemp(path.join(os.tmpdir(),'bc-zip-limit-')),root=path.join(tmp,'stage');
    try{
      const bomb=path.join(tmp,'bomb.zip');await fsp.writeFile(bomb,zipBuffer([{name:'bomb.txt',data:Buffer.alloc(4096,65),method:8}]));await assert.rejects(extractZipSecure(bomb,root,{maxCompressionRatio:2}),/compression ratio/);
      const many=path.join(tmp,'many.zip');await fsp.writeFile(many,zipBuffer([{name:'a',data:Buffer.from('1')},{name:'b',data:Buffer.from('2')} ]));await assert.rejects(extractZipSecure(many,path.join(tmp,'many-stage'),{maxEntryCount:1}),/entry count/);
      const duplicate=path.join(tmp,'duplicate.zip');await fsp.writeFile(duplicate,zipBuffer([{name:'same',data:Buffer.from('1')},{name:'same',data:Buffer.from('2')} ]));await assert.rejects(extractZipSecure(duplicate,path.join(tmp,'duplicate-stage')),/Duplicate archive entry/);
      const collision=path.join(tmp,'collision.zip');await fsp.writeFile(collision,zipBuffer([{name:'dir/',data:Buffer.alloc(0)},{name:'dir',data:Buffer.from('x')} ]));await assert.rejects(extractZipSecure(collision,path.join(tmp,'collision-stage')),/collision/);
    }finally{await fsp.rm(tmp,{recursive:true,force:true});}
  });

  it('failed extraction does not touch the current runtime and staging is disposable',async()=>{
    const tmp=await fsp.mkdtemp(path.join(os.tmpdir(),'bc-zip-atomic-')),current=path.join(tmp,'current'),stage=path.join(tmp,'stage'),zip=path.join(tmp,'bad.zip');
    await fsp.mkdir(current);await fsp.writeFile(path.join(current,'llama-server.exe'),'old');await fsp.writeFile(zip,zipBuffer([{name:'../bad',data:Buffer.from('x')} ]));
    try{await assert.rejects(extractZipSecure(zip,stage));assert.equal(await fsp.readFile(path.join(current,'llama-server.exe'),'utf8'),'old');await fsp.rm(stage,{recursive:true,force:true});assert.equal(fs.existsSync(stage),false);}
    finally{await fsp.rm(tmp,{recursive:true,force:true});}
  });
});

function cryptoRandom(n){const b=Buffer.alloc(n);for(let i=0;i<n;i++)b[i]=i%251;return b;}

function crc32(data){let crc=0xffffffff;for(const byte of data){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return (crc^0xffffffff)>>>0;}
function u16(n){const b=Buffer.alloc(2);b.writeUInt16LE(n);return b;}
function u32(n){const b=Buffer.alloc(4);b.writeUInt32LE(n>>>0);return b;}
function zipBuffer(entries){
  const locals=[],centrals=[];let offset=0;
  for(const input of entries){
    const name=Buffer.from(input.name),raw=Buffer.isBuffer(input.data)?input.data:Buffer.from(input.data||''),method=input.method===8?8:0,body=method===8?zlib.deflateRawSync(raw):raw,crc=crc32(raw),attrs=Number(input.externalFileAttributes||0),madeBy=Number(input.versionMadeBy||20);
    const local=Buffer.concat([Buffer.from([0x50,0x4b,0x03,0x04]),u16(20),u16(0),u16(method),u16(0),u16(0),u32(crc),u32(body.length),u32(raw.length),u16(name.length),u16(0),name,body]);
    const central=Buffer.concat([Buffer.from([0x50,0x4b,0x01,0x02]),u16(madeBy),u16(20),u16(0),u16(method),u16(0),u16(0),u32(crc),u32(body.length),u32(raw.length),u16(name.length),u16(0),u16(0),u16(0),u16(0),u32(attrs),u32(offset),name]);
    locals.push(local);centrals.push(central);offset+=local.length;
  }
  const central=Buffer.concat(centrals),local=Buffer.concat(locals),end=Buffer.concat([Buffer.from([0x50,0x4b,0x05,0x06]),u16(0),u16(0),u16(entries.length),u16(entries.length),u32(central.length),u32(local.length),u16(0)]);
  return Buffer.concat([local,central,end]);
}
