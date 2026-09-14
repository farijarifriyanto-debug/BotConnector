const {describe,it}=require('node:test');
const assert=require('node:assert/strict');
const {RuntimeManager}=require('../runtime/runtime-manager.cjs');

function rel(tag,names){return {tag,name:tag,prerelease:true,assets:names.map(n=>({name:n,url:'https://example.invalid/'+n,size:123,sha256:null}))};}
const WIN={
  cpu:'llama-b10930-bin-win-cpu-x64.zip',
  vulkan:'llama-b10930-bin-win-vulkan-x64.zip',
  cuda12:'llama-b10930-bin-win-cuda-12.4-x64.zip',
  cuda13:'llama-b10930-bin-win-cuda-13.3-x64.zip',
  cudart12:'cudart-llama-bin-win-cuda-12.4-x64.zip',
  armCpu:'llama-b10930-bin-win-cpu-arm64.zip',
  mac:'llama-b10930-bin-macos-arm64.tar.gz',
  src:'llama-b10930.tar.gz',
  rocm:'llama-b10930-bin-win-rocm-10.0-x64.zip',
};
// Names verified live against the real releases API (ggml-org/llama.cpp) —
// no cuda12/cuda13 ubuntu asset currently exists, unlike Windows.
const LINUX={
  cpu:'llama-b10930-bin-ubuntu-x64.tar.gz',
  vulkan:'llama-b10930-bin-ubuntu-vulkan-x64.tar.gz',
  rocm:'llama-b10930-bin-ubuntu-rocm-10.0-x64.tar.gz',
  armCpu:'llama-b10930-bin-ubuntu-arm64.tar.gz',
  mac:'llama-b10930-bin-macos-arm64.tar.gz',
  src:'llama-b10930.tar.gz',
};
// process.platform is read directly inside chooseAssets/latest() (not
// injectable), so this file exercises whichever platform it actually runs
// on with real, platform-correct fixtures instead of asserting Windows
// behavior unconditionally and failing outright on Linux CI/dev machines.
const win=process.platform==='win32';
const A=win?WIN:LINUX;
const notFoundPattern=win?/No official Windows x64/:/No official Linux x64/;

describe('runtime asset resolver',()=>{
  const m=new RuntimeManager({baseDir:win?'C:\\stub':'/tmp/stub'});
  it('resolves cpu backend',()=>{const a=m.chooseAssets(rel('b1',[A.cpu,A.armCpu,A.mac]),'cpu');assert.equal(a[0].name,A.cpu);});
  it('resolves vulkan backend',()=>{const a=m.chooseAssets(rel('b1',[A.vulkan,A.cpu]),'vulkan');assert.equal(a[0].name,A.vulkan);});
  it('rejects arm64 on x64 machine',()=>{assert.throws(()=>m.chooseAssets(rel('b1',[A.armCpu]),'cpu'),notFoundPattern);});
  it('rejects source tarballs / other-OS assets',()=>{assert.throws(()=>m.chooseAssets(rel('b1',[A.mac,A.src]),'cpu'),notFoundPattern);});
  it('aliases hip to rocm',()=>{const a=m.chooseAssets(rel('b1',[A.rocm]),'hip');assert.match(a[0].name,/rocm/i);});
  if(win){
    it('resolves cuda12 with cudart companion dependency',()=>{const a=m.chooseAssets(rel('b1',[WIN.cuda12,WIN.cudart12,WIN.cpu]),'cuda12');assert.equal(a[0].name,WIN.cuda12);assert.ok(a.some(x=>x.name===WIN.cudart12));});
    it('resolves cuda13',()=>{const a=m.chooseAssets(rel('b1',[WIN.cuda13]),'cuda13');assert.equal(a[0].name,WIN.cuda13);});
  }else{
    it('cuda12/cuda13 are not offered on Linux (no such official asset exists)',()=>{
      assert.throws(()=>m.chooseAssets(rel('b1',[LINUX.cpu,LINUX.vulkan]),'cuda12'),notFoundPattern);
    });
  }
  it('falls back to next release when newest lacks a compatible asset',async()=>{
    const stub=new RuntimeManager({baseDir:m.baseDir});
    stub.listReleases=async()=>[
      rel('b-new',[]),                    // e.g. v0.4.0 with only nightly-tag.txt
      rel('b-old',[A.vulkan,A.cpu]),      // newest usable
    ];
    const r=await stub.resolveBackend('vulkan');
    assert.equal(r.releaseTag,'b-old');
    assert.equal(r.primaryAsset.name,A.vulkan);
  });
  it('auto prefers vulkan over cpu',async()=>{
    const stub=new RuntimeManager({baseDir:m.baseDir});
    stub.listReleases=async()=>[rel('b1',[A.vulkan,A.cpu])];
    const r=await stub.resolveBackend('auto');
    assert.equal(r.backend,'vulkan');
  });
  it('auto falls back to cpu when vulkan is absent',async()=>{
    const stub=new RuntimeManager({baseDir:m.baseDir});
    stub.listReleases=async()=>[rel('b1',[A.cpu])];
    const r=await stub.resolveBackend('auto');
    assert.equal(r.backend,'cpu');
  });
});
