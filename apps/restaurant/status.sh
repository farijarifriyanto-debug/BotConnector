#!/usr/bin/env bash
set -Eeuo pipefail
docker ps --filter name=^/restaurant-seller-control$
echo
curl -fsS http://127.0.0.1:18192/health; echo
