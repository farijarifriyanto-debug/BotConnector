#!/usr/bin/env bash
# Apply Parking migrations to the dedicated Parking database.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -r /etc/botconnector/parking.env ]; then
  set -a; source /etc/botconnector/parking.env; set +a
elif [ -r "$HOME/.botconnector/parking.env" ]; then
  set -a; source "$HOME/.botconnector/parking.env"; set +a
else
  echo "ERROR: no parking.env found" >&2; exit 1
fi
exec .venv/bin/alembic upgrade head
