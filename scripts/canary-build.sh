#!/bin/bash
set -euo pipefail

echo "=== BotConnector Canary Build ==="
echo "Starting at $(date)"

cd /home/botadmin/ai-workspaces/BotConnector

echo "Installing dependencies..."
npm ci

echo "Building TypeScript..."
npm run build

echo "Running tests..."
npm run test

echo "=== Canary Build Complete ==="
echo "Finished at $(date)"