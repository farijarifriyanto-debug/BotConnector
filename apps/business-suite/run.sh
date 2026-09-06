#!/usr/bin/env bash
set -Eeuo pipefail
exec /opt/botconnector-multichannel/venv/bin/python -m uvicorn \
  app:APP --app-dir /opt/botconnector-bisnis \
  --host 127.0.0.1 --port 18199 --workers 1
