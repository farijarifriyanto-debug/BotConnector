// Versioned pricing registry. Effective-dated; never invents prices; UNKNOWN
// fails safe (cost_status=UNKNOWN) instead of fabricating $0.
const fsp=require('node:fs/promises');
const path=require('node:path');

const REGISTRY_VERSION=1;

// Verified price baseline (source: account UI / live metadata, verified 2026-09-13).
// Effective-dated; new verified values append new effectiveFrom entries.
const SEED={
  version:REGISTRY_VERSION,
  entries:[
    {provider:'together',modelId:'deepseek-ai/DeepSeek-V4-Flash-0731',inputPerMillion:0.14,cachedInputPerMillion:0.03,outputPerMillion:0.28,effectiveFrom:'2026-09-13',source:'together /v1/models pricing (live metadata, verified)',verifiedAt:'2026-09-13'},
    {provider:'together',modelId:'MiniMaxAI/MiniMax-M3',inputPerMillion:0.30,cachedInputPerMillion:0.06,outputPerMillion:1.20,effectiveFrom:'2026-09-13',source:'together /v1/models pricing (live metadata, verified)',verifiedAt:'2026-09-13'},
    {provider:'nebius',modelId:'MiniMaxAI/MiniMax-M3',inputPerMillion:0.30,cachedInputPerMillion:null,outputPerMillion:1.20,effectiveFrom:'2026-09-13',source:'Nebius account UI (verified)',verifiedAt:'2026-09-13'}
  ]
};

class PricingRegistry{
  constructor({dir}={}){this.file=path.join(dir,'pricing.json');}
  async load(){
    try{
      const disk=JSON.parse(await fsp.readFile(this.file,'utf8'));
      if(Number(disk.version)>=REGISTRY_VERSION)return disk;
    }catch{}
    await this.save(SEED);
    return SEED;
  }
  async save(registry){
    await fsp.mkdir(path.dirname(this.file),{recursive:true});
    await fsp.writeFile(this.file,JSON.stringify(registry,null,2));
  }
  async upsert(entry){
    const reg=await this.load();
    const i=reg.entries.findIndex(e=>e.provider===entry.provider&&e.modelId===entry.modelId&&e.effectiveFrom===entry.effectiveFrom);
    if(i>=0)reg.entries[i]={...reg.entries[i],...entry};else reg.entries.push(entry);
    await this.save(reg);
    return reg;
  }
  // Find the newest effective-dated rate for (provider, modelId) as of a date.
  async rate(provider,modelId,asOf=new Date()){
    const reg=await this.load();
    const today=asOf.toISOString().slice(0,10);
    const matches=reg.entries.filter(e=>e.provider===provider&&e.modelId===modelId&&e.effectiveFrom<=today)
      .sort((a,b)=>a.effectiveFrom<b.effectiveFrom?1:-1);
    return matches[0]||null;
  }
  // Cost in USD for a usage record; null when pricing unknown (fail-safe).
  async estimate({provider,modelId,inputTokens=0,cachedInputTokens=0,outputTokens=0,asOf=new Date()}){
    const rate=await this.rate(provider,modelId,asOf);
    if(!rate||rate.inputPerMillion==null||rate.outputPerMillion==null)return {cost:null,costStatus:'UNKNOWN',pricingVersion:rate?`v${(await this.load()).version}/${rate?rate.effectiveFrom:'none'}`:null,rate};
    const cachedRate=rate.cachedInputPerMillion;
    let cost;
    if(cachedInputTokens>0&&cachedRate!=null){
      cost=(inputTokens-cachedInputTokens)/1e6*rate.inputPerMillion+cachedInputTokens/1e6*cachedRate+outputTokens/1e6*rate.outputPerMillion;
    }else{
      cost=inputTokens/1e6*rate.inputPerMillion+outputTokens/1e6*rate.outputPerMillion;
    }
    return {cost:+cost.toFixed(8),costStatus:'KNOWN',pricingVersion:`v${(await this.load()).version}:${rate.effectiveFrom}`,rate};
  }
  public(){return this.#sync();}
  #sync(){try{return JSON.parse(require('node:fs').readFileSync(this.file,'utf8'));}catch{return SEED;}}
}
module.exports={PricingRegistry,SEED,REGISTRY_VERSION};