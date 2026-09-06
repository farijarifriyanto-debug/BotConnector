#!/usr/bin/env bash
set -Eeuo pipefail

export LC_ALL=C

ENVFILE="/etc/botconnector-finance-core/finance-core.env"
PG="botconnector-core-postgres"
APPDIR="/opt/botconnector-finance-core/releases/finance-core-r8-period-close-foundation-20260813T143444Z"

set -a
source "$ENVFILE"
set +a

PG_IP="$(
    docker inspect \
      -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
      "$PG"
)"

test -n "$PG_IP"

export FINANCE_DB_HOST="$PG_IP"

exec "$APPDIR/venv/bin/python" \
  -m uvicorn \
  app.main:app \
  --app-dir "$APPDIR" \
  --host 127.0.0.1 \
  --port 18200
