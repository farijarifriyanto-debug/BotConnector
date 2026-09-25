#!/usr/bin/env bash
set -euo pipefail

export PATH="/home/botadmin/.nvm/versions/node/v24.20.0/bin:/usr/bin:/bin"
ROOT="/home/botadmin/newbotconnector/worktrees/provider-routing-registry"
ARTIFACTS="/home/botadmin/newbotconnector/production-candidate/artifacts"
NODE="/home/botadmin/.nvm/versions/node/v24.20.0/bin/node"
LOCK="/tmp/botconnector-effective-cost-report.lock"

mkdir -p "$ARTIFACTS"
exec 9>"$LOCK"
/usr/bin/flock -n 9 || exit 0

for HOURS in 24 168; do
  FINAL="$ARTIFACTS/effective-cost-${HOURS}h.json"
  TMP="$ARTIFACTS/.effective-cost-${HOURS}h.json.tmp.$$"
  trap 'rm -f "$TMP"' EXIT
  cd "$ROOT"
  "$NODE" --experimental-strip-types scripts/effective-cost-report.mjs     --hours="$HOURS"     --output="$TMP" >/dev/null
  mv -f "$TMP" "$FINAL"
  trap - EXIT
done

printf '{"status":"ok","generatedAt":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"   > "$ARTIFACTS/effective-cost-report-status.json"
echo "EFFECTIVE_COST_REPORTS=PASS $(date -u +%Y-%m-%dT%H:%M:%SZ)"
