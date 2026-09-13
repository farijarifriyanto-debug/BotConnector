// Cost estimation helper combining pricing registry + unit engine.
// Never invents prices: unknown pricing -> cost null, costStatus UNKNOWN.
async function estimateCost(pricing,units,provider,modelId,usage){
  const r=await pricing.estimate({
    provider,modelId,
    inputTokens:usage.input_tokens||0,
    cachedInputTokens:usage.cached_input_tokens||0,
    outputTokens:usage.output_tokens||0
  });
  if(r.cost==null)return {usd:null,cost:null,costStatus:'UNKNOWN',pricingVersion:r.pricingVersion,rate:r.rate};
  const usd=r.cost;
  return {usd,cost:usd,costStatus:'KNOWN',pricingVersion:r.pricingVersion,cloudUnits:units?units.units(usd):null,rate:r.rate};
}
module.exports={estimateCost};