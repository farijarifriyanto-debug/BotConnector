import fs from "node:fs";

const envPath = "/home/botadmin/.config/botconnector/free-providers.env";
const raw = fs.readFileSync(envPath, "utf8");
const env = Object.fromEntries(
  raw.split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#") && line.includes("="))
    .map((line) => {
      const i = line.indexOf("=");
      return [line.slice(0, i).trim(), line.slice(i + 1).trim()];
    }),
);

const apiKey = env.NARAROUTER_API_KEY;
if (!apiKey) {
  console.log("KEY_STATUS=MISSING");
  process.exit(2);
}

const modelsRes = await fetch("https://router.bynara.id/v1/models", {
  headers: { Authorization: "Bearer " + apiKey, Accept: "application/json" },
});
console.log("MODELS_HTTP=" + modelsRes.status);
const modelsBody = await modelsRes.json().catch(() => ({}));
if (!modelsRes.ok) {
  console.log("MODELS_ERROR=" + JSON.stringify(modelsBody).slice(0, 400));
  process.exit(3);
}

const models = Array.isArray(modelsBody.data) ? modelsBody.data : [];
console.log("MODEL_COUNT=" + models.length);
for (const m of models.slice(0, 80)) {
  console.log(JSON.stringify({
    id: m.id,
    reasoning: m.reasoning ?? null,
    vision: m.vision ?? null,
    context_length: m.context_length ?? null,
    owned_by: m.owned_by ?? null,
  }));
}

const preferred = [
  "laguna-s-2.1",
  "mimo-v2.5",
  "muse-spark-1.3-contributor",
].find((id) => models.some((m) => m.id === id)) ?? models[0]?.id;

if (!preferred) process.exit(0);

const t0 = Date.now();
const chatRes = await fetch("https://router.bynara.id/v1/chat/completions", {
  method: "POST",
  headers: {
    Authorization: "Bearer " + apiKey,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: preferred,
    messages: [{ role: "user", content: "Reply with exactly: NARA_SMOKE_OK" }],
    max_tokens: 32,
    temperature: 0,
  }),
});
const elapsed = Date.now() - t0;
console.log("SMOKE_MODEL=" + preferred);
console.log("CHAT_HTTP=" + chatRes.status);
console.log("LATENCY_MS=" + elapsed);

const chatBody = await chatRes.json().catch(() => ({}));
if (!chatRes.ok) {
  console.log("CHAT_ERROR=" + JSON.stringify(chatBody).slice(0, 500));
  process.exit(4);
}

const msg = chatBody?.choices?.[0]?.message?.content ?? "";
console.log("CONTENT_MATCH=" + (String(msg).trim() === "NARA_SMOKE_OK" ? "YES" : "NO"));
console.log("RESPONSE_MODEL=" + (chatBody.model ?? ""));
console.log("USAGE=" + JSON.stringify(chatBody.usage ?? {}));
