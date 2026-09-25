import fs from "node:fs";

const ROOT="/home/botadmin/newbotconnector";
const gatesPath=ROOT+"/worktrees/provider-routing-registry/config/provider-shadow-activation-gates.json";
const overlapPath=ROOT+"/production-candidate/artifacts/nara-runtime-overlap.json";
const metadataPath=ROOT+"/production-candidate/artifacts/nara-model-metadata.json";
const plansPath=ROOT+"/production-candidate/artifacts/nara-public-plans.json";

const gates=JSON.parse(fs.readFileSync(gatesPath,"utf8"));
const overlap=JSON.parse(fs.readFileSync(overlapPath,"utf8"));
const metadata=JSON.parse(fs.readFileSync(metadataPath,"utf8"));
const plans=JSON.parse(fs.readFileSync(plansPath,"utf8"));

const listed=new Set((overlap.overlap??[]).map(x=>x.providerModelId));
const meta=new Map((metadata.rows??[]).map(x=>[x.id,x]));
const planMap=new Map();
for(const plan of plans.plans??[]){
  for(const model of plan.models??[]){
    if(!planMap.has(model)) planMap.set(model,[]);
    planMap.get(model).push({
      id:plan.id,
      tokenCapDaily:plan.tokenCapDaily??null,
      rpmLimit:plan.rpmLimit??null,
    });
  }
}

for(const [model,gate] of Object.entries(gates.models??{})){
  const m=meta.get(model);
  const modelListed=listed.has(model);
  const pricingVerified=Boolean(
    m &&
    Number.isFinite(Number(m.inputIdrPer1m)) &&
    Number.isFinite(Number(m.outputIdrPer1m)) &&
    typeof m.paygEnabled==="boolean"
  );
  gate.modelListed=modelListed;
  gate.pricingVerified=pricingVerified;
  gate.evidence={
    ...(gate.evidence??{}),
    modelListCheckedAt:overlap.checkedAt??null,
    modelMetadataCheckedAt:metadata.checkedAt??null,
    publicPlansCheckedAt:plans.checkedAt??null,
    paygEnabled:m?.paygEnabled??null,
    inputIdrPer1m:m?.inputIdrPer1m??null,
    outputIdrPer1m:m?.outputIdrPer1m??null,
    cacheReadIdrPer1m:m?.cacheReadIdrPer1m??null,
    publicPlans:planMap.get(model)??[],
    vision:m?.vision??null,
    reasoning:m?.reasoning??null,
  };
  // Deliberately do not infer these gates from model-list metadata.
  // They require separate evidence.
  gate.entitlementVerified=gate.entitlementVerified===true;
  gate.commercialScopeVerified=gate.commercialScopeVerified===true;
  gate.capabilitiesVerified=gate.capabilitiesVerified===true;
  gate.executionClientReady=gate.executionClientReady===true;
}

gates.updatedAt=new Date().toISOString();
gates.evidencePolicy={
  modelListed:"authenticated /v1/models exact id",
  pricingVerified:"authenticated /v1/models explicit IDR input/output prices and payg_enabled",
  entitlementVerified:"requires successful exact-model execution under the credential/plan intended for BotConnector",
  commercialScopeVerified:"requires provider terms or explicit provider authorization for intended shared/commercial use",
  capabilitiesVerified:"requires workload-specific verification; model metadata alone is insufficient for tools",
  executionClientReady:"requires candidate gateway client + secret boundary + smoke",
};
fs.writeFileSync(gatesPath,JSON.stringify(gates,null,2)+"\n");
console.log(JSON.stringify({
  status:"PASS",
  updatedAt:gates.updatedAt,
  models:Object.entries(gates.models??{}).map(([model,g])=>({
    model,
    modelListed:g.modelListed,
    pricingVerified:g.pricingVerified,
    publicPlans:g.evidence?.publicPlans?.map(x=>x.id)??[],
    entitlementVerified:g.entitlementVerified,
    commercialScopeVerified:g.commercialScopeVerified,
    capabilitiesVerified:g.capabilitiesVerified,
    executionClientReady:g.executionClientReady,
  }))
},null,2));
