#!/bin/bash
set -euo pipefail

echo "=== BotConnector Canary Build ==="
echo "Starting at $(date)"

cd /home/botadmin/ai-workspaces/BotConnector

# Node/npm/npx and the opencode CLI are not on the default non-interactive PATH.
export PATH="/home/botadmin/.hermes/node/bin:/home/botadmin/.opencode/bin:$PATH"

# Load and EXPORT the production provider/server environment that the OpenCode
# service uses, WITHOUT printing any secret value. The env file is root-owned
# (600), so read it through sudo. set -a ensures sourced vars are exported to
# child processes (node/vitest).
set -a
if [ -r /etc/botconnector/opencode-vps.env ]; then
  . /etc/botconnector/opencode-vps.env
elif sudo -n true 2>/dev/null; then
  eval "$(sudo -n cat /etc/botconnector/opencode-vps.env 2>/dev/null)"
else
  echo "WARNING: could not read /etc/botconnector/opencode-vps.env" >&2
fi

# The server stores its Basic Auth creds as OPENCODE_SERVER_USERNAME/PASSWORD;
# the canary test expects the BotConnector env names. Map them without printing
# values so both are available to the test process.
export BOTCONNECTOR_OPENCODE_USERNAME="${BOTCONNECTOR_OPENCODE_USERNAME:-${OPENCODE_SERVER_USERNAME:-}}"
export BOTCONNECTOR_OPENCODE_PASSWORD="${BOTCONNECTOR_OPENCODE_PASSWORD:-${OPENCODE_SERVER_PASSWORD:-}}"
set +a

echo "Installing dependencies..."
npm ci

echo "Building TypeScript..."
npm run build

echo "Running tests..."
npm run test

echo "=== Canary Build Complete ==="
echo "Finished at $(date)"
