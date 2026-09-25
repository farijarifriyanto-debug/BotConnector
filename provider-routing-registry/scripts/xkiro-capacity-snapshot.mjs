import fs from "node:fs";
import path from "node:path";

const envPath = process.env.BOTCONNECTOR_FREE_PROVIDER_ENV ||
  "/home/botadmin/.config/botconnector/free-providers.env";
const outputPath = process.argv[2] ||
  "/home/botadmin/newbotconnector/production-candidate/artifacts/provider-capacity-snapshot.json";
const verbose = process.argv.includes("--verbose");

function loadEnv(file) {
  const raw = fs.readFileSync(file, "utf8");
  return Object.fromEntries(
    raw.split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#") && line.includes("="))
      .map((line) => {
        const i = line.indexOf("=");
        return [line.slice(0, i).trim(), line.slice(i + 1).trim()];
      }),
  );
}

const envKey = fs.existsSync(envPath) ? loadEnv(envPath).XKIRO_API_KEY : "";
const keyFile = process.env.XKIRO_API_KEY_FILE ||
  "/home/botadmin/newbotconnector/production-candidate/secrets/xkiro_api_key";
const fileKey = fs.existsSync(keyFile) ? fs.readFileSync(keyFile, "utf8").trim() : "";
const key = (envKey || fileKey).trim();
if (!key) throw new Error("XKIRO_API_KEY_MISSING");

const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), 8_000);
let response;
try {
  response = await fetch("https://api.xkiro.com/v1/usage", {
    headers: {
      Authorization: "Bearer " + key,
      Accept: "application/json",
      "User-Agent": "BotConnector-Capacity-Monitor/1.0",
    },
    signal: controller.signal,
  });
} finally {
  clearTimeout(timer);
}

if (!response.ok) {
  throw new Error("XKIRO_USAGE_HTTP_" + response.status);
}
const body = await response.json();
const free = body?.free_tokens ?? {};
const remaining = Number.isSafeInteger(free.remaining) ? free.remaining : null;
const limit = Number.isSafeInteger(free.limit_per_day) ? free.limit_per_day : null;
const used = Number.isSafeInteger(free.used_today) ? free.used_today : null;

const snapshot = {
  schema: "botconnector.provider-capacity-snapshot.v1",
  checkedAt: new Date().toISOString(),
  providers: {
    xkiro: {
      status: remaining == null ? "UNKNOWN" : remaining > 0 ? "AVAILABLE" : "EXHAUSTED",
      freeTokens: {
        usedToday: used,
        limitPerDay: limit,
        remaining,
        resetBoundary: "00:00 UTC",
      },
      source: "xkiro:/v1/usage",
    },
  },
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(snapshot, null, 2) + "\n", { mode: 0o644 });
if (verbose) {
  console.log("XKIRO_CAPACITY_SNAPSHOT=PASS");
  console.log("STATUS=" + snapshot.providers.xkiro.status);
  console.log("FREE_USED_TODAY=" + String(used));
  console.log("FREE_LIMIT_PER_DAY=" + String(limit));
  console.log("FREE_REMAINING=" + String(remaining));
  console.log("OUTPUT=" + outputPath);
}
