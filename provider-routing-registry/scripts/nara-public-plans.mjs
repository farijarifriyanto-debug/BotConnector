import fs from "node:fs";
const res=await fetch("https://router.bynara.id/api/plans",{headers:{Accept:"application/json"}});
const body=await res.json().catch(()=>({}));
const plans=Array.isArray(body)?body:(body.plans??body.data??[]);
const sanitized=(Array.isArray(plans)?plans:[]).map(p=>({
 id:p.id??p.slug??p.name??null,
 name:p.name??null,
 tokenCapDaily:p.token_cap_daily??p.tokenCapDaily??null,
 rpmLimit:p.rpm_limit??p.rpmLimit??null,
 models:p.models??p.model_ids??null,
 price:p.price??p.price_idr??null
}));
const report={schema:"botconnector.nara-public-plans.v1",checkedAt:new Date().toISOString(),http:res.status,plans:sanitized,rawKeys:body&&typeof body==="object"?Object.keys(body):[]};
const out=process.argv.find(x=>x.startsWith("--output="));
if(out) fs.writeFileSync(out.slice(9),JSON.stringify(report,null,2)+"\n");
console.log(JSON.stringify(report,null,2));
if(!res.ok) process.exitCode=1;
