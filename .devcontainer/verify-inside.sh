#!/usr/bin/env bash
set -Eeuo pipefail

echo "============================================================"
echo " BOTCONNECTOR DEV CONTAINER - INSIDE ACCEPTANCE"
echo "============================================================"

fail=0

check() {
  local name="$1"
  shift
  if command -v "$name" >/dev/null 2>&1; then
    printf '%s=PASS :: ' "$name"
    "$@" 2>&1 | head -n 1
  else
    echo "$name=FAIL_NOT_FOUND"
    fail=1
  fi
}

check dotnet dotnet --version
check node node --version
check npm npm --version
check python3 python3 --version
check rg rg --version
check ast-grep ast-grep --version
check serena serena --version
check semgrep semgrep --version
check playwright-cli playwright-cli --version

echo
echo "===== WORKSPACE ====="
git rev-parse --show-toplevel
git branch --show-current
git status --short

echo
echo "===== WPF POLICY ====="
if grep -RIl --include='*.csproj' -E '<UseWPF>[[:space:]]*true[[:space:]]*</UseWPF>' . >/dev/null 2>&1; then
  echo "WPF_DETECTED=TRUE"
  echo "WPF_FINAL_BUILD=WINDOWS_HOST_REQUIRED"
else
  echo "WPF_DETECTED=FALSE"
fi

echo
echo "===== HERMES HOST NETWORK ====="
HERMES_URL="${BOTCONNECTOR_HERMES_BASE_URL:-http://host.docker.internal:18642/v1}/models"
code="$(curl -sS --max-time 5 -o /tmp/hermes-models.out -w '%{http_code}' "$HERMES_URL" || true)"
rm -f /tmp/hermes-models.out
if [ "$code" = "000" ] || [ -z "$code" ]; then
  echo "HERMES_NETWORK_REACHABLE=FAIL"
  fail=1
else
  echo "HERMES_NETWORK_REACHABLE=PASS"
  echo "HERMES_HTTP_CODE=$code"
  echo "HERMES_AUTH_TEST=NOT_RUN_NO_SECRET_IN_REPO"
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "RESULT=FAIL"
  exit 1
fi

echo "RESULT=PASS"
echo "DEV_CONTAINER_INSIDE_ACCEPTANCE=PASS"