#!/usr/bin/env bash
set -u

export PATH="/home/botadmin/.nvm/versions/node/v24.20.0/bin:/usr/bin:/bin"
ROOT="/home/botadmin/newbotconnector/worktrees/provider-routing-registry"
ARTIFACTS="/home/botadmin/newbotconnector/production-candidate/artifacts"
NODE="/home/botadmin/.nvm/versions/node/v24.20.0/bin/node"
LOCK="/tmp/botconnector-provider-opportunity-matrix.lock"
FINAL="$ARTIFACTS/provider-opportunity-matrix.json"
STATUS="$ARTIFACTS/provider-opportunity-matrix-status.json"
TMP="$ARTIFACTS/.provider-opportunity-matrix.json.tmp.$$"

mkdir -p "$ARTIFACTS"
exec 9>"$LOCK"
/usr/bin/flock -n 9 || exit 0

cd "$ROOT"
"$NODE" scripts/provider-opportunity-matrix.mjs --output="$TMP" >/dev/null
code=$?

if [ -s "$TMP" ]; then
  mv -f "$TMP" "$FINAL"
else
  rm -f "$TMP"
fi

state="pass"
if [ "$code" -ne 0 ]; then
  state="fail"
fi

printf '{"status":"%s","exitCode":%d,"generatedAt":"%s"}\n'   "$state" "$code" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATUS"

echo "PROVIDER_OPPORTUNITY_MATRIX=$state $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit "$code"
