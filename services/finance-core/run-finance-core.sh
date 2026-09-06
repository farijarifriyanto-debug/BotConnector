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

# FINANCE_DB_HOST: this process runs on the host, not inside the Docker
# network, so it cannot resolve a bare container name via DNS the way a
# container could. Production sets FINANCE_DB_HOST to a Docker container
# name (e.g. "botconnector-core-postgres") — if the configured value isn't
# already a real IP address, resolve it via `docker inspect` using that
# exact name (no hardcoded container name, no new env var required: this
# reuses whatever FINANCE_DB_HOST is already set to). If it's already an
# IP (a different deployment might set one directly), leave it alone.
if [ -n "${FINANCE_DB_HOST:-}" ] && ! [[ "$FINANCE_DB_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  RESOLVED_IP="$(
    docker inspect \
      -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
      "$FINANCE_DB_HOST" 2>/dev/null || true
  )"
  if [ -n "$RESOLVED_IP" ]; then
    FINANCE_DB_HOST="$RESOLVED_IP"
    export FINANCE_DB_HOST
  fi
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
