#!/usr/bin/env bash
set -Eeuo pipefail

# Canonical-relative start script: resolves purely from this script's own
# location in the repo, never from a fixed checkout path or /opt.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Dependency owner is packages/multichannel (see docs/deployment/REDEPLOY-MAP.md).
# Build once with: python3 -m venv packages/multichannel/venv && \
#   packages/multichannel/venv/bin/pip install -r packages/multichannel/requirements.lock.txt
VENV="${MULTICHANNEL_VENV:-$REPO_ROOT/packages/multichannel/venv}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18199}"

exec "$VENV/bin/python" -m uvicorn \
  app:APP --app-dir "$SCRIPT_DIR" \
  --host "$HOST" --port "$PORT" --workers 1
