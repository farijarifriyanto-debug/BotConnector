import fs from "node:fs";

const ROOT="/home/botadmin/newbotconnector";
const policy=JSON.parse(fs.readFileSync(ROOT+"/production-candidate/artifacts/starter-route-policy.json","utf8"));
const candidates=JSON.parse(fs.readFileSync(ROOT+"/worktrees/provider-routing-registry/config/provider-route-candidates.json","utf8"));
const expected=(policy.routes??[]).filter(x=>x.starterFreeEligible===true);
const response=await fetch("http://127.0.0.1:49260/v1/models");
const body=await response.json();
const exposed=(body.data??[]).filter(x=>x.starterFreeEligible===true);
const exposedById=new Map(exposed.map(x=>[x.id,x]));
const routeById=new Map((candidates.routes??[]).map(x=>[x.canonicalModelId,x]));

const rows=expected.map(route=>{
 const model=exposedById.get(route.modelId);
 const authority=routeById.get(route.modelId);
 const exactCandidate=(authority?.candidates??[]).find(c=>
   c.provider===route.provider &&
   c.providerModelId===route.providerModelId
 );
 const checks={
   exposedToStarter:Boolean(model),
   providerMatches:model?.owned_by===route.provider,
   providerModelMatches:model?.real_name===route.providerModelId,
   routeAuthorityPresent:Boolean(authority),
   exactCandidatePresent:Boolean(exactCandidate),
   pricingTrusted:exactCandidate?.pricingTrusted===true,
   costSwitchEligible:exactCandidate?.costSwitchEligible===true,
 };
 return {
   modelId:route.modelId,
   provider:route.provider,
   providerModelId:route.providerModelId,
   checks,
   ready:Object.values(checks).every(Boolean),
 };
});

const expectedIds=new Set(expected.map(x=>x.modelId));
const unexpectedStarterModels=exposed.map(x=>x.id).filter(id=>!expectedIds.has(id));
const status=
 response.ok &&
 rows.length===policy.eligibleRouteCount &&
 rows.every(x=>x.ready) &&
 unexpectedStarterModels.length===0
 ? "PASS":"FAIL";

const report={
 schema:"botconnector.starter-wiring-readiness.v1",
 checkedAt:new Date().toISOString(),
 status,
 policyEligibleCount:policy.eligibleRouteCount,
 exposedStarterCount:exposed.length,
 unexpectedStarterModels,
 rows,
};
const out=process.argv.find(x=>x.startsWith("--output="));
if(out) fs.writeFileSync(out.slice(9),JSON.stringify(report,null,2)+"\n");
console.log(JSON.stringify(report,null,2));
if(status!=="PASS") process.exitCode=1;
