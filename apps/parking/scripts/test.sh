#!/usr/bin/env bash
# Run the M1-M3 acceptance suite against the dedicated Parking TEST database.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -r "$HOME/.botconnector/parking.env" ]; then
  set -a; source "$HOME/.botconnector/parking.env"; set +a
elif [ -r /etc/botconnector/parking.env ]; then
  set -a; source /etc/botconnector/parking.env; set +a
else
  echo "ERROR: no parking.env found" >&2; exit 1
fi
exec .venv/bin/python -m pytest "$@"
