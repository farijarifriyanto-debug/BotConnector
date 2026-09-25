import fs from "node:fs";
import yaml from "yaml";

const envPath = "/home/botadmin/.config/botconnector/free-providers.env";
const gatewayPath =
  "/home/botadmin/newbotconnector/production-candidate/build/gateway/config.yaml";

const env = Object.fromEntries(
  fs.readFileSync(envPath, "utf8")
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

const gateway = yaml.parse(fs.readFileSync(gatewayPath, "utf8"));
const runtime = new Set(
  (gateway.clients ?? []).flatMap((client) =>
    (client.models ?? []).map((model) => model.name).filter(Boolean),
  ),
);

const res = await fetch("https://router.bynara.id/v1/models", {
  headers: { Authorization: "Bearer " + key, Accept: "application/json" },
});
const body = await res.json().catch(() => ({}));
if (!res.ok) {
  console.log(JSON.stringify({ status: "FAIL", http: res.status }));
  process.exit(1);
}
const models = Array.isArray(body.data) ? body.data : [];
const byId = new Map(models.map((m) => [m.id, m]));
const overlap = [...runtime]
  .filter((id) => byId.has(id))
  .sort()
  .map((id) => {
    const m = byId.get(id);
    return {
      canonicalModelId: id,
      providerModelId: id,
      listed: true,
      ownedBy: m.owned_by ?? null,
      contextLength: m.context_length ?? null,
      reasoning: m.reasoning ?? null,
      vision: m.vision ?? null,
    };
  });

const report = {
  schema: "botconnector.nara-runtime-overlap.v1",
  checkedAt: new Date().toISOString(),
  http: res.status,
  providerModelCount: models.length,
  runtimeModelCount: runtime.size,
  exactOverlapCount: overlap.length,
  overlap,
};
const out = process.argv.find((x) => x.startsWith("--output="));
if (out) fs.writeFileSync(out.slice(9), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report, null, 2));
