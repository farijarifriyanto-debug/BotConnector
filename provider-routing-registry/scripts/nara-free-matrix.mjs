import fs from "node:fs";

const envPath = "/home/botadmin/.config/botconnector/free-providers.env";
const raw = fs.readFileSync(envPath, "utf8");
const env = Object.fromEntries(
  raw.split(/\r?\n/).map((x) => x.trim())
    .filter((x) => x && !x.startsWith("#") && x.includes("="))
    .map((x) => {
      const i = x.indexOf("=");
      return [x.slice(0, i).trim(), x.slice(i + 1).trim()];
    }),
);
const key = env.NARAROUTER_API_KEY;
if (!key) throw new Error("NARAROUTER_API_KEY missing");

const candidates = [
  "agnes-2.5-flash",
  "laguna-s-2.1",
  "ling-3.0-flash-fin-free",
  "ling-3.0-flash-sante-free",
  "ling-3.0-flash-vl-free",
  "mimo-v2.5-free",
  "mimo-v2.6-flash-free",
  "muse-spark-1.3-contributor-free",
  "nemotron-3-super-free",
  "nemotron-3-ultra-free",
  "nemotron-3.5-lightning-free",
  "stepfun-3.7-flash",
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

for (let i = 0; i < candidates.length; i++) {
  const model = candidates[i];
  const started = Date.now();
  let status = 0;
  let data = {};
  try {
    const res = await fetch("https://router.bynara.id/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: "Bearer " + key,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "Reply with OK." }],
        max_tokens: 16,
        temperature: 0,
      }),
    });
    status = res.status;
    data = await res.json().catch(() => ({}));
  } catch (error) {
    data = { error: { type: "network_error", message: String(error?.message || error) } };
  }

  const usage = data?.usage ?? {};
  const err = data?.error ?? {};
  console.log(JSON.stringify({
    model,
    http: status,
    executable_free: status === 200,
    latency_ms: Date.now() - started,
    response_model: data?.model ?? null,
    prompt_tokens: usage?.prompt_tokens ?? null,
    cached_tokens: usage?.prompt_tokens_details?.cached_tokens ?? null,
    completion_tokens: usage?.completion_tokens ?? null,
    error_type: err?.type ?? null,
    error_message: err?.message ? String(err.message).slice(0, 140) : null,
  }));

  if (i < candidates.length - 1) await sleep(7000);
}
