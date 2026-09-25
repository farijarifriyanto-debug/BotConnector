const fs=require('node:fs');
const fsp=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const {pipeline}=require('node:stream/promises');
const {execFile}=require('node:child_process');
const yauzl=require('yauzl');

const UA='BotConnectorAI/0.4';
const RELEASES_URL='https://api.github.com/repos/ggml-org/llama.cpp/releases';

function digestOf(a){const d=a?.digest||'';return d.replace(/^sha256:/i,'')||null;}

function normRelease(r){
  return {
    tag:r.tag_name,
    name:r.name||r.tag_name,
    prerelease:Boolean(r.prerelease),
    publishedAt:r.published_at||r.created_at||null,
    assets:(r.assets||[]).map(a=>({name:a.name,url:a.browser_download_url,size:a.size,sha256:digestOf(a)}))
  };
}

async function sha256File(p){return await new Promise((resolve,reject)=>{const h=crypto.createHash('sha256'),rs=fs.createReadStream(p);rs.on('data',d=>h.update(d));rs.on('error',reject);rs.on('end',()=>resolve(h.digest('hex')));});}

function verifyBinary(binary,timeout=30000){
  return new Promise((resolve,reject)=>{
    execFile(binary,['--version'],{shell:false,windowsHide:true,timeout},(err,stdout,stderr)=>{
      const out=String(stdout||stderr||'').trim();
      if(err)return reject(new Error(`llama-server.exe --version failed: ${err.message}${out?` — ${out.slice(0,300)}`:''}`));
      resolve(out.slice(0,500));
    });
  });
}

const ARCHIVE_LIMITS=Object.freeze({
  maxArchiveBytes:512*1024*1024,
  maxEntryCount:5000,
  maxSingleEntryUncompressedBytes:512*1024*1024,
  maxTotalUncompressedBytes:2*1024*1024*1024,
  maxCompressionRatio:100,
  maxPathLength:1024
});

function safeEntryName(name){
  const raw=String(name??'');
  if(!raw||raw.includes('\u0000'))return null;
  const n=raw.replace(/\\/g,'/');
  if(n.startsWith('/')||n.startsWith('//')||/^[a-zA-Z]:/.test(n))return null;
  const directory=n.endsWith('/'),body=directory?n.slice(0,-1):n;
  if(!body)return null;
  const parts=body.split('/');
  if(parts.some(part=>!part||part==='.'||part==='..'))return null;
  return parts.join('/')+(directory?'/':'');
}

function archiveIsDirectory(entry){return entry.fileName.endsWith('/')||Boolean(Number(entry.externalFileAttributes||0)&0x10);}
function archiveIsSymlink(entry){return ((Number(entry.externalFileAttributes||0)>>>16)&0xf000)===0xa000;}
function archiveIsUnsupportedSpecial(entry){
  const platform=Number(entry.versionMadeBy||0)>>>8;
  if(platform!==3)return false;
  const type=((Number(entry.externalFileAttributes||0)>>>16)&0xf000);
  return type!==0&&type!==0x4000&&type!==0x8000;
}
function archiveLimit(value,fallback){const n=Number(value);return Number.isFinite(n)&&n>0?n:fallback;}
function archiveOptions(options={}){return {
  maxArchiveBytes:archiveLimit(options.maxArchiveBytes,process.env.BOTCONNECTOR_MAX_ARCHIVE_BYTES||ARCHIVE_LIMITS.maxArchiveBytes),
  maxEntryCount:archiveLimit(options.maxEntryCount,process.env.BOTCONNECTOR_MAX_ENTRY_COUNT||ARCHIVE_LIMITS.maxEntryCount),
  maxSingleEntryUncompressedBytes:archiveLimit(options.maxSingleEntryUncompressedBytes,process.env.BOTCONNECTOR_MAX_SINGLE_ENTRY_UNCOMPRESSED_BYTES||ARCHIVE_LIMITS.maxSingleEntryUncompressedBytes),
  maxTotalUncompressedBytes:archiveLimit(options.maxTotalUncompressedBytes,process.env.BOTCONNECTOR_MAX_TOTAL_UNCOMPRESSED_BYTES||ARCHIVE_LIMITS.maxTotalUncompressedBytes),
  maxCompressionRatio:archiveLimit(options.maxCompressionRatio,process.env.BOTCONNECTOR_MAX_COMPRESSION_RATIO||ARCHIVE_LIMITS.maxCompressionRatio),
  maxPathLength:archiveLimit(options.maxPathLength,process.env.BOTCONNECTOR_MAX_PATH_LENGTH||ARCHIVE_LIMITS.maxPathLength)
};}
function inside(root,target){const rel=path.relative(root,target);return rel!==''&&!rel.startsWith(`..${path.sep}`)&&rel!=='..'&&!path.isAbsolute(rel);}
async function assertSafeComponents(root,target){
  const rootStat=await fsp.lstat(root);
  if(!rootStat.isDirectory()||rootStat.isSymbolicLink())throw new Error('Extraction root is not a private directory');
  const relative=path.relative(root,path.dirname(target));
  let current=root;
  for(const part of relative?relative.split(path.sep):[]){
    current=path.join(current,part);
    try{
      const stat=await fsp.lstat(current);
      if(stat.isSymbolicLink()||!stat.isDirectory())throw new Error(`Unsafe extraction component: ${part}`);
    }catch(error){
      if(error.code!=='ENOENT')throw error;
      await fsp.mkdir(current);
      const stat=await fsp.lstat(current);
      if(stat.isSymbolicLink()||!stat.isDirectory())throw new Error(`Unsafe extraction component: ${part}`);
    }
  }
}
function openArchive(zipPath){return yauzl.openPromise(zipPath,{lazyEntries:true,validateEntrySizes:true,decodeStrings:true});}
async function extractZipSecure(zipPath,extractionRoot,options={}){
  const limits=archiveOptions(options),archiveStat=await fsp.lstat(zipPath);
  if(!archiveStat.isFile()||archiveStat.isSymbolicLink())throw new Error('Archive must be a regular file');
  if(archiveStat.size>limits.maxArchiveBytes)throw new Error('Archive size limit exceeded');
  const root=path.resolve(extractionRoot);try{await fsp.mkdir(root);}catch(error){if(error.code!=='EEXIST')throw error;}
  const rootStat=await fsp.lstat(root);if(rootStat.isSymbolicLink()||!rootStat.isDirectory())throw new Error('Extraction root is unsafe');
  const zip=await openArchive(zipPath),seen=new Set();let count=0,total=0;
  try{
    return await new Promise((resolve,reject)=>{
      let settled=false;
      const fail=error=>{if(settled)return;settled=true;try{zip.close();}catch{}reject(error);};
      zip.on('error',fail);
      zip.on('end',()=>{if(!settled){settled=true;resolve({entries:count,totalUncompressedBytes:total});}});
      zip.on('entry',entry=>{
        (async()=>{
          const name=safeEntryName(entry.fileName);
          if(!name||name.length>limits.maxPathLength)throw new Error(`Unsafe archive entry blocked: ${entry.fileName}`);
          count++;if(count>limits.maxEntryCount)throw new Error('Archive entry count limit exceeded');
          if(archiveIsSymlink(entry)||archiveIsUnsupportedSpecial(entry))throw new Error(`Unsupported archive entry blocked: ${entry.fileName}`);
          const uncompressed=Number(entry.uncompressedSize),compressed=Number(entry.compressedSize);
          if(!Number.isSafeInteger(uncompressed)||uncompressed>limits.maxSingleEntryUncompressedBytes)throw new Error(`Archive entry size limit exceeded: ${entry.fileName}`);
          total+=uncompressed;if(total>limits.maxTotalUncompressedBytes)throw new Error('Archive total expansion limit exceeded');
          if(uncompressed>0&&(!compressed||uncompressed/compressed>limits.maxCompressionRatio))throw new Error(`Archive compression ratio limit exceeded: ${entry.fileName}`);
          const key=process.platform==='win32'?name.toLowerCase():name;
          if(seen.has(key))throw new Error(`Duplicate archive entry blocked: ${entry.fileName}`);seen.add(key);
          const target=path.resolve(root,name.replace(/\//g,path.sep));
          if(!inside(root,target))throw new Error(`Archive entry escapes extraction root: ${entry.fileName}`);
          if(archiveIsDirectory(entry)){
            if(await fsp.lstat(target).then(s=>s.isDirectory()&&!s.isSymbolicLink()).catch(e=>e.code==='ENOENT'?false:Promise.reject(e))){}else{
              await assertSafeComponents(root,target);
              await fsp.mkdir(target);
            }
            zip.readEntry();return;
          }
          await assertSafeComponents(root,target);
          try{await fsp.lstat(target);throw new Error(`Archive destination collision: ${entry.fileName}`);}catch(error){if(error.code!=='ENOENT')throw error;}
          const flags=fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_WRONLY|(fs.constants.O_NOFOLLOW||0);
          const handle=await fsp.open(target,flags,0o600);
          try{
            const stream=await new Promise((res,rej)=>zip.openReadStream(entry,(error,readable)=>error?rej(error):res(readable)));
            await pipeline(stream,handle.createWriteStream());
          }finally{await handle.close();}
          zip.readEntry();
        })().catch(fail);
      });
      zip.readEntry();
    });
  }finally{try{zip.close();}catch{}}
}

class RuntimeManager{
  constructor({baseDir,emit}){this.baseDir=baseDir;this.emit=emit||(()=>{});}

  async listReleases(limit=15){
    const url=`${RELEASES_URL}?per_page=${Math.min(30,Math.max(1,limit))}`;
    const res=await fetch(url,{headers:{'User-Agent':UA,'Accept':'application/vnd.github+json'}});
    if(!res.ok)throw new Error(`GitHub ${res.status} listing llama.cpp releases`);
    const arr=await res.json();
    return arr.map(normRelease);
  }

  // Newest release first that contains ANY official Windows x64 zip (excludes arm64-only, source tarballs).
  async latest(){
    const releases=await this.listReleases(15);
    const usable=releases.find(r=>(r.assets||[]).some(a=>/-win-.*-x64\.zip$/i.test(a.name)));
    if(!usable)throw new Error('No recent llama.cpp release contains an official Windows x64 asset');
    return usable;
  }

  normalizeBackend(b){
    const v=String(b||'auto').toLowerCase();
    if(v==='hip')return 'rocm';
    if(v==='cuda')return 'cuda12';
    return v;
  }

  chooseAssets(release,backend){
    backend=this.normalizeBackend(backend);
    if(backend==='auto')throw new Error('Use resolveBackend() for backend "auto" (tries vulkan, then cpu fallback)');
    const a=(release.assets||[]).filter(x=>!/-arm64\./i.test(x.name));
    const find=re=>a.find(x=>re.test(x.name));
    let primary=null;
    if(backend==='cuda12')primary=find(/^llama-.*-bin-win-cuda-12(?:\.[0-9.]+)?-x64\.zip$/i);
    if(backend==='cuda13')primary=find(/^llama-.*-bin-win-cuda-13(?:\.[0-9.]+)?-x64\.zip$/i);
    if(backend==='vulkan')primary=find(/^llama-.*-bin-win-vulkan-x64\.zip$/i);
    if(backend==='rocm')primary=find(/^llama-.*-bin-win-(rocm|hip).*x64\.zip$/i);
    if(backend==='cpu')primary=find(/^llama-.*-bin-win-cpu-x64\.zip$/i);
    if(!primary){
      const cands=a.filter(x=>/^llama-.*-bin-win-.*\.zip$/i.test(x.name)).map(x=>x.name).slice(0,8);
      throw new Error(`No official Windows x64 llama.cpp asset found for backend ${backend} in ${release.tag}${cands.length?` (win assets: ${cands.join(', ')})`:''}`);
    }
    const out=[primary];
    if(backend==='cuda12'){const c=find(/^cudart-llama-bin-win-cuda-12.*-x64\.zip$/i);if(c)out.push(c);}
    if(backend==='cuda13'){const c=find(/^cudart-llama-bin-win-cuda-13.*-x64\.zip$/i);if(c)out.push(c);}
    return out;
  }

  // Phase G structured resolution: scan multiple recent releases, newest-first.
  async resolveBackend(backend='vulkan',limit=15){
    backend=this.normalizeBackend(backend);
    const candidates=backend==='auto'?['vulkan','cpu']:[backend];
    const releases=await this.listReleases(limit);
    const tried=[];
    for(const b of candidates){
      for(const rel of releases){
        try{
          const assets=this.chooseAssets(rel,b);
          return {releaseTag:rel.tag,releaseName:rel.name,backend:b,primaryAsset:assets[0],dependencies:assets.slice(1),triedReleases:tried.slice()};
        }catch(e){tried.push(`${rel.tag}/${b}: ${e.message.slice(0,120)}`);}
      }
    }
    throw new Error(`No compatible official Windows x64 asset for backend(s) ${candidates.join(', ')} in the ${releases.length} most recent llama.cpp releases`);
  }

  async downloadAsset(asset,zipPath,meta){
    const res=await fetch(asset.url,{headers:{'User-Agent':UA},redirect:'follow'});
    if(!res.ok)throw new Error(`Runtime download ${res.status} for ${asset.name}`);
    const total=Number(res.headers.get('content-length')||asset.size||0);
    await fsp.mkdir(path.dirname(zipPath),{recursive:true});
    const tmp=zipPath+'.part';
    try{await fsp.rm(tmp,{force:true});}catch{}
    const ws=fs.createWriteStream(tmp),reader=res.body.getReader();
    let got=0;
    try{
      while(true){
        const{done,value}=await reader.read();
        if(done)break;
        if(!ws.write(Buffer.from(value)))await new Promise(r=>ws.once('drain',r));
        got+=value.byteLength;
        this.emit('runtime:install-progress',{...meta,asset:asset.name,downloadedBytes:got,totalBytes:total,status:'downloading'});
      }
      await new Promise((resolve,reject)=>ws.end(err=>err?reject(err):resolve()));
    }catch(e){try{await fsp.rm(tmp,{force:true});}catch{}throw e;}
    if(asset.sha256){
      this.emit('runtime:install-progress',{...meta,asset:asset.name,status:'verifying',downloadedBytes:total,totalBytes:total});
      const actual=await sha256File(tmp);
      if(actual.toLowerCase()!==String(asset.sha256).toLowerCase()){await fsp.rm(tmp,{force:true});throw new Error(`SHA256 verification failed for ${asset.name}`);}
    }
    await fsp.rename(tmp,zipPath);
    return {zipPath,bytes:got||total};
  }

  async install({backend='vulkan'}={}){
    if(process.platform!=='win32')throw new Error('Managed runtime installation currently targets Windows x64.');
    const norm=this.normalizeBackend(backend);
    const order=norm==='auto'?['vulkan','cpu']:[norm];
    let lastError=null;
    for(const b of order){
      try{
        return await this.installBackend(b);
      }catch(e){
        lastError=e;
        this.emit('runtime:install-progress',{backend:b,release:null,status:'backend-failed',error:String(e.message||e),fallback:b==='vulkan'&&order.includes('cpu')?'cpu':null});
        if(b!=='vulkan'||!order.includes('cpu'))throw e;
        // fall through to cpu fallback, preserving vulkan diagnostic
      }
    }
    throw lastError||new Error('Runtime installation failed');
  }

  async installBackend(backend){
    const resolved=await this.resolveBackend(backend);
    const {releaseTag,primaryAsset,dependencies}=resolved;
    const assets=[primaryAsset,...dependencies];
    const finalDir=path.join(this.baseDir,releaseTag,backend);
    await fsp.mkdir(this.baseDir,{recursive:true});
    const stagingDir=await fsp.mkdtemp(path.join(this.baseDir,`.staging-${releaseTag}-${backend}-${process.pid}-`));
    let prevBackup=null;
    try{
      let assetIndex=0;
      for(const asset of assets){
        assetIndex++;
        const meta={backend,release:releaseTag,asset:asset.name,assetIndex,assetCount:assets.length};
        const zipPath=path.join(stagingDir,asset.name);
        await this.downloadAsset(asset,zipPath,meta);
        this.emit('runtime:install-progress',{...meta,status:'extracting',downloadedBytes:asset.size||0,totalBytes:asset.size||0});
        await extractZipSecure(zipPath,stagingDir);
        await fsp.rm(zipPath,{force:true});
      }
      const exe=await this.findServer(stagingDir);
      if(!exe)throw new Error('llama-server.exe was not found after extraction');
      // Verification gate (shell:false) BEFORE promotion.
      this.emit('runtime:install-progress',{backend,release:releaseTag,status:'verifying-binary'});
      const versionOutput=await verifyBinary(exe);
      // Atomic promotion: keep previous working runtime until replacement is verified.
      await assertSafeComponents(this.baseDir,finalDir);
      try{
        const st=await fsp.lstat(finalDir);
        if(st.isSymbolicLink()||!st.isDirectory())throw new Error('Existing runtime target is unsafe');
        prevBackup=path.join(this.baseDir,`.prev-${releaseTag}-${backend}-${Date.now()}`);await fsp.rename(finalDir,prevBackup);
      }catch(error){if(error.code!=='ENOENT')throw error;}
      await fsp.mkdir(path.dirname(finalDir),{recursive:true});
      try{await fsp.rename(stagingDir,finalDir);}catch(error){if(prevBackup){try{await fsp.rename(prevBackup,finalDir);prevBackup=null;}catch{}}throw error;}
      const promotedExe=await this.findServer(finalDir);
      if(prevBackup){try{await fsp.rm(prevBackup,{recursive:true,force:true});}catch{}}
      const out={backend,release:releaseTag,binary:promotedExe||exe,dir:finalDir,version:versionOutput,resolution:{releaseTag,backend,primaryAsset:primaryAsset.name,dependencies:dependencies.map(d=>d.name)}};
      this.emit('runtime:install-progress',{backend,release:releaseTag,status:'completed',binary:out.binary});
      return out;
    }catch(e){
      try{await fsp.rm(stagingDir,{recursive:true,force:true});}catch{}
      throw e;
    }
  }

  async findServer(dir=this.baseDir){const stack=[dir];while(stack.length){const d=stack.pop();let items=[];try{items=await fsp.readdir(d,{withFileTypes:true});}catch{continue;}for(const x of items){const p=path.join(d,x.name);if(x.isDirectory()){if(path.basename(p).startsWith('.staging-'))continue;stack.push(p);}else if(x.name.toLowerCase()==='llama-server.exe')return p;}}return null;}
  async installed(){const exe=await this.findServer();return exe?{installed:true,binary:exe}:{installed:false,binary:null};}
  async verifyInstalled(){const s=await this.installed();if(!s.installed)return{installed:false,verified:false};try{const out=await verifyBinary(s.binary);return{installed:true,binary:s.binary,verified:true,version:out};}catch(e){return{installed:true,binary:s.binary,verified:false,error:String(e.message||e)};}}
}
module.exports={ARCHIVE_LIMITS,RuntimeManager,verifyBinary,safeEntryName,extractZipSecure};
