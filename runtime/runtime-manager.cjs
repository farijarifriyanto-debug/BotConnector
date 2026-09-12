const fs=require('node:fs');
const fsp=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const {execFile}=require('node:child_process');
const AdmZip=require('adm-zip');

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

function safeEntryName(name){
  const n=String(name||'').replace(/\\/g,'/');
  if(!n||n.startsWith('/')||/^[a-zA-Z]:/.test(n)||n.split('/').includes('..'))return null;
  return n;
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
    const stagingDir=path.join(this.baseDir,`.staging-${releaseTag}-${backend}-${process.pid}`);
    await fsp.rm(stagingDir,{recursive:true,force:true});
    await fsp.mkdir(stagingDir,{recursive:true});
    try{
      let assetIndex=0;
      for(const asset of assets){
        assetIndex++;
        const meta={backend,release:releaseTag,asset:asset.name,assetIndex,assetCount:assets.length};
        const zipPath=path.join(stagingDir,asset.name);
        await this.downloadAsset(asset,zipPath,meta);
        this.emit('runtime:install-progress',{...meta,status:'extracting',downloadedBytes:asset.size||0,totalBytes:asset.size||0});
        const zip=new AdmZip(zipPath);
        for(const entry of zip.getEntries()){
          if(safeEntryName(entry.entryName)===null)throw new Error(`Unsafe archive entry blocked: ${entry.entryName}`);
        }
        zip.extractAllTo(stagingDir,true);
        await fsp.rm(zipPath,{force:true});
      }
      const exe=await this.findServer(stagingDir);
      if(!exe)throw new Error('llama-server.exe was not found after extraction');
      // Verification gate (shell:false) BEFORE promotion.
      this.emit('runtime:install-progress',{backend,release:releaseTag,status:'verifying-binary'});
      const versionOutput=await verifyBinary(exe);
      // Atomic promotion: keep previous working runtime until replacement is verified.
      let prevBackup=null;
      try{
        const st=await fsp.stat(finalDir);
        if(st.isDirectory()){prevBackup=path.join(this.baseDir,`.prev-${releaseTag}-${backend}-${Date.now()}`);await fsp.rename(finalDir,prevBackup);}
      }catch{}
      await fsp.mkdir(path.dirname(finalDir),{recursive:true});
      await fsp.rename(stagingDir,finalDir);
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
module.exports={RuntimeManager,verifyBinary,safeEntryName};
