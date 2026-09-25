import fs from "node:fs";

const ENV = "/home/botadmin/.config/botconnector/free-providers.env";
const OVERLAP =
  "/home/botadmin/newbotconnector/production-candidate/artifacts/nara-runtime-overlap.json";

const env = Object.fromEntries(
  fs.readFileSync(ENV, "utf8")
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter((x) => x && !x.startsWith("#") && x.includes("="))
    .map((x) => {
      const i = x.indexOf("=");
      return [x.slice(0, i).trim(), x.slice(i + 1).trim()];
    }),
);
const key = env.NARAROUTER_API_KEY;
if (!key) throw new Error("NARAROUTER_API_KEY missing");

const overlap = JSON.parse(fs.readFileSync(OVERLAP, "utf8"));
const requestedArg = process.argv.find((x) => x.startsWith("--models="));
const requested = requestedArg
  ? new Set(requestedArg.slice("--models=".length).split(",").map((x) => x.trim()).filter(Boolean))
  : null;
const models = (overlap.overlap ?? [])
  .map((x) => x.providerModelId)
  .filter((id) => !requested || requested.has(id));
const rows = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

for (let i = 0; i < models.length; i++) {
  const model = models[i];
  const started = Date.now();
  let http = 0;
  let body = {};
  let retryAfter = null;
  try {
    const res = await fetch("https://router.bynara.id/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: "Bearer " + key,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "Reply: OK" }],
        max_tokens: 1,
        temperature: 0,
      }),
    });
    http = res.status;
    retryAfter = res.headers.get("retry-after");
    body = await res.json().catch(() => ({}));
  } catch (error) {
    body = { error: { type: "network_error", message: String(error?.message ?? error) } };
  }

  const responseModel = body?.model ?? null;
  const usage = body?.usage ?? {};
  const row = {
    canonicalModelId: model,
    providerModelId: model,
    http,
    executable: http === 200,
    exactResponseModel: http === 200 && responseModel === model,
    responseModel,
    latencyMs: Date.now() - started,
    promptTokens: usage.prompt_tokens ?? null,
    cachedTokens: usage?.prompt_tokens_details?.cached_tokens ?? null,
    completionTokens: usage.completion_tokens ?? null,
    errorType: body?.error?.type ?? null,
    retryAfter,
  };
  rows.push(row);
  console.log(JSON.stringify(row));
  if (i < models.length - 1) await sleep(4500);
}

const report = {
  schema: "botconnector.nara-runtime-entitlement-smoke.v1",
  checkedAt: new Date().toISOString(),
  requestMaxTokens: 1,
  rows,
  executableCount: rows.filter((x) => x.executable).length,
  exactResponseModelCount: rows.filter((x) => x.exactResponseModel).length,
};
const out = process.argv.find((x) => x.startsWith("--output="));
if (out) fs.writeFileSync(out.slice(9), JSON.stringify(report, null, 2) + "\n");
