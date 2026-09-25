import fs from "node:fs";
import path from "node:path";

const outputPath = process.argv[2] ||
  "/home/botadmin/newbotconnector/production-candidate/artifacts/provider-model-presence-snapshot.json";
const verbose = process.argv.includes("--verbose");

const targets = [
  {
    provider: "deepinfra",
    keyFile: process.env.DEEPINFRA_API_KEY_FILE,
    url: "https://api.deepinfra.com/v1/openai/models",
    modelIds: ["Qwen/Qwen3.5-397B-A17B", "MiniMaxAI/MiniMax-M3"],
  },
  {
    provider: "alibaba_global",
    keyFile: process.env.ALIBABA_GLOBAL_API_KEY_FILE,
    url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
    modelIds: ["qwen3.5-397b-a17b"],
  },
];

function readKey(file) {
  if (!file || !fs.existsSync(file)) return "";
  return fs.readFileSync(file, "utf8").trim();
}

async function probe(target) {
  const key = readKey(target.keyFile);
  if (!key) {
    return { status: "NO_CREDENTIAL", httpStatus: null, models: {} };
  }

  let response;
  try {
    response = await fetch(target.url, {
      headers: {
        Authorization: "Bearer " + key,
        Accept: "application/json",
        "User-Agent": "BotConnector-Model-Presence/1.0",
      },
      signal: AbortSignal.timeout(8_000),
    });
  } catch (error) {
    return {
      status: "PROBE_ERROR",
      httpStatus: null,
      errorClass: error?.name || "Error",
      models: {},
    };
  }

  let body = null;
  try {
    body = await response.json();
  } catch {}

  const rows = Array.isArray(body?.data) ? body.data : null;
  const ids = rows ? new Set(rows.map((item) => item?.id).filter(Boolean)) : null;
  const models = Object.fromEntries(
    target.modelIds.map((id) => [id, ids ? ids.has(id) : null]),
  );

  const allPresent = ids && target.modelIds.every((id) => ids.has(id));
  const status = response.ok
    ? allPresent ? "AVAILABLE" : ids ? "MODEL_MISSING" : "UNKNOWN_RESPONSE"
    : response.status === 401 || response.status === 403
      ? "AUTH_ERROR"
      : "ENDPOINT_ERROR";

  return {
    status,
    httpStatus: response.status,
    models,
    source: new URL(target.url).host + new URL(target.url).pathname,
  };
}

const providers = {};
for (const target of targets) {
  providers[target.provider] = await probe(target);
}

const snapshot = {
  schema: "botconnector.provider-model-presence-snapshot.v1",
  checkedAt: new Date().toISOString(),
  providers,
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(snapshot, null, 2) + "\n", { mode: 0o644 });

if (verbose) {
  console.log("PROVIDER_MODEL_PRESENCE=PASS");
  for (const [provider, value] of Object.entries(providers)) {
    console.log(provider + "=" + value.status + " HTTP=" + String(value.httpStatus));
    for (const [model, present] of Object.entries(value.models)) {
      console.log("  " + model + "=" + String(present));
    }
  }
  console.log("OUTPUT=" + outputPath);
}
