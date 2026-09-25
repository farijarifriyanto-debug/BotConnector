import fs from "node:fs";
const raw = fs.readFileSync("/home/botadmin/.config/botconnector/free-providers.env","utf8");
const env = Object.fromEntries(raw.split(/\r?\n/).map(x=>x.trim()).filter(x=>x && !x.startsWith("#") && x.includes("=")).map(x=>{const i=x.indexOf("="); return [x.slice(0,i).trim(),x.slice(i+1).trim()]}));
const key=env.NARAROUTER_API_KEY;
if(!key) throw new Error("NARAROUTER_API_KEY missing");
const res=await fetch("https://router.bynara.id/v1/models",{headers:{Authorization:"Bearer "+key,Accept:"application/json"}});
const body=await res.json().catch(()=>({}));
if(!res.ok) throw new Error("models http "+res.status);
const wanted=new Set(["claude-opus-5","claude-sonnet-5","deepseek-v4.1-flash","glm-5.2","glm-5.3-flash","gpt-5.6-luna","gpt-5.6-sol","gpt-5.6-terra","kimi-k3","minimax-m3","qwen3.8-flash"]);
const rows=(body.data??[]).filter(x=>wanted.has(x.id)).map(m=>({
 id:m.id,
 keys:Object.keys(m).sort(),
 owned_by:m.owned_by??null,
 inputIdrPer1m:m.input_idr_per_1m??null,
 outputIdrPer1m:m.output_idr_per_1m??null,
 cacheReadIdrPer1m:m.cache_read_idr_per_1m??null,
 paygEnabled:m.payg_enabled??null,
 vision:m.vision??null,
 reasoning:m.reasoning??null,
 context_length:m.context_length??null
}));
const report={schema:"botconnector.nara-model-metadata.v1",checkedAt:new Date().toISOString(),http:res.status,rows};
const out=process.argv.find(x=>x.startsWith("--output="));
if(out) fs.writeFileSync(out.slice(9),JSON.stringify(report,null,2)+"\n");
console.log(JSON.stringify(report,null,2));
