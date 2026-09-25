#!/usr/bin/env bash
set -u

export PATH="/home/botadmin/.nvm/versions/node/v24.20.0/bin:/usr/bin:/bin"
ROOT="/home/botadmin/newbotconnector/worktrees/provider-routing-registry"
ARTIFACTS="/home/botadmin/newbotconnector/production-candidate/artifacts"
NODE="/home/botadmin/.nvm/versions/node/v24.20.0/bin/node"
LOCK="/tmp/botconnector-nara-shadow-refresh.lock"
STATUS="$ARTIFACTS/nara-shadow-refresh-status.json"

mkdir -p "$ARTIFACTS"
exec 9>"$LOCK"
/usr/bin/flock -n 9 || exit 0

cd "$ROOT"
code=0

"$NODE" scripts/nara-runtime-overlap.mjs   --output="$ARTIFACTS/nara-runtime-overlap.json" >/dev/null || code=$?

if [ "$code" -eq 0 ]; then
  "$NODE" scripts/nara-model-metadata.mjs     --output="$ARTIFACTS/nara-model-metadata.json" >/dev/null || code=$?
fi

if [ "$code" -eq 0 ]; then
  "$NODE" scripts/nara-public-plans.mjs     --output="$ARTIFACTS/nara-public-plans.json" >/dev/null || code=$?
fi

if [ "$code" -eq 0 ]; then
  "$NODE" scripts/update-nara-shadow-evidence.mjs >/dev/null || code=$?
fi

if [ "$code" -eq 0 ]; then
  "$NODE" scripts/provider-opportunity-matrix.mjs     --output="$ARTIFACTS/provider-opportunity-matrix.json" >/dev/null || code=$?
fi

state="pass"
if [ "$code" -ne 0 ]; then state="fail"; fi

printf '{"status":"%s","exitCode":%d,"generatedAt":"%s","activationPolicy":"SHADOW_ONLY"}\n'   "$state" "$code" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATUS"

echo "NARA_SHADOW_REFRESH=$state $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit "$code"
