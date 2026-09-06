#!/usr/bin/env bash
set -Eeuo pipefail

set -a
source "/etc/botconnector-finance-core/finance-core.env"
set +a

PG_IP="$(
  docker inspect     -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'     "botconnector-core-postgres"
)"

export FINANCE_DB_HOST="$PG_IP"
export FINANCE_DB_PORT=5432

exec "/opt/botconnector-finance-core/candidates/finance-core-r7b-bank-api-20260813T130256Z/venv/bin/python"   -m uvicorn   app.main:app   --app-dir "/opt/botconnector-finance-core/candidates/finance-core-r7b-bank-api-20260813T130256Z"   --host 127.0.0.1   --port 18201
