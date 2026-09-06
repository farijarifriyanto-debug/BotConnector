#!/usr/bin/env bash
set -Eeuo pipefail

export LC_ALL=C

# Canonical-relative start script: the app directory and venv are resolved
# from this script's own location in the repo, never from a fixed release
# checkout path. Only the secret/config sources below remain
# environment-specific (documented config, not old source).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPDIR="$SCRIPT_DIR"

# Build once with: python3 -m venv services/finance-core/venv && \
#   services/finance-core/venv/bin/pip install -r services/finance-core/requirements.lock.txt
VENV="${FINANCE_CORE_VENV:-$SCRIPT_DIR/venv}"

# Documented external config — where this deployment's secrets/env live.
# Not part of the canonical source tree; every environment (prod, staging,
# a fresh redeploy) supplies its own.
ENVFILE="${FINANCE_CORE_ENVFILE:-/etc/botconnector-finance-core/finance-core.env}"
if [ -f "$ENVFILE" ]; then
  set -a
  source "$ENVFILE"
  set +a
fi

# FINANCE_DB_HOST: either set directly in the env file above, or resolved
# dynamically from a named Postgres container (production's current
# pattern). Both are documented config choices, not source dependencies.
if [ -z "${FINANCE_DB_HOST:-}" ] && [ -n "${FINANCE_CORE_POSTGRES_CONTAINER:-}" ]; then
  FINANCE_DB_HOST="$(
    docker inspect \
      -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
      "$FINANCE_CORE_POSTGRES_CONTAINER"
  )"
  export FINANCE_DB_HOST
fi

test -n "${FINANCE_DB_HOST:-}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18200}"

exec "$VENV/bin/python" \
  -m uvicorn \
  app.main:app \
  --app-dir "$APPDIR" \
  --host "$HOST" \
  --port "$PORT"
