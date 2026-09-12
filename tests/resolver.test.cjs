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
};

describe('runtime asset resolver',()=>{
  const m=new RuntimeManager({baseDir:'C:\\stub'});
  it('resolves cpu backend',()=>{const a=m.chooseAssets(rel('b1',[WIN.cpu,WIN.armCpu,WIN.mac]),'cpu');assert.equal(a[0].name,WIN.cpu);});
  it('resolves vulkan backend',()=>{const a=m.chooseAssets(rel('b1',[WIN.vulkan,WIN.cpu]),'vulkan');assert.equal(a[0].name,WIN.vulkan);});
  it('resolves cuda12 with cudart companion dependency',()=>{const a=m.chooseAssets(rel('b1',[WIN.cuda12,WIN.cudart12,WIN.cpu]),'cuda12');assert.equal(a[0].name,WIN.cuda12);assert.ok(a.some(x=>x.name===WIN.cudart12));});
  it('resolves cuda13',()=>{const a=m.chooseAssets(rel('b1',[WIN.cuda13]),'cuda13');assert.equal(a[0].name,WIN.cuda13);});
  it('rejects arm64 on x64 machine',()=>{assert.throws(()=>m.chooseAssets(rel('b1',[WIN.armCpu]),'cpu'),/No official Windows x64/);});
  it('rejects source tarballs / non-windows assets',()=>{assert.throws(()=>m.chooseAssets(rel('b1',[WIN.mac,WIN.src]),'cpu'),/No official Windows x64/);});
  it('aliases hip to rocm',()=>{const a=m.chooseAssets(rel('b1',['llama-b10930-bin-win-rocm-10.0-x64.zip']),'hip');assert.match(a[0].name,/rocm/i);});
  it('falls back to next release when newest lacks a compatible asset',async()=>{
    const stub=new RuntimeManager({baseDir:'C:\\stub'});
    stub.listReleases=async()=>[
      rel('b-new',[]),                       // e.g. v0.4.0 with only nightly-tag.txt
      rel('b-old',[WIN.vulkan,WIN.cpu]),     // newest usable
    ];
    const r=await stub.resolveBackend('vulkan');
    assert.equal(r.releaseTag,'b-old');
    assert.equal(r.primaryAsset.name,WIN.vulkan);
  });
  it('auto prefers vulkan over cpu',async()=>{
    const stub=new RuntimeManager({baseDir:'C:\\stub'});
    stub.listReleases=async()=>[rel('b1',[WIN.vulkan,WIN.cpu])];
    const r=await stub.resolveBackend('auto');
    assert.equal(r.backend,'vulkan');
  });
  it('auto falls back to cpu when vulkan is absent',async()=>{
    const stub=new RuntimeManager({baseDir:'C:\\stub'});
    stub.listReleases=async()=>[rel('b1',[WIN.cpu])];
    const r=await stub.resolveBackend('auto');
    assert.equal(r.backend,'cpu');
  });
});
