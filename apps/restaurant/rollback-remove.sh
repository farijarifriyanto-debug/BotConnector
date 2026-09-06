#!/usr/bin/env bash
set -Eeuo pipefail
NAME="restaurant-seller-control"
docker rm -f "$NAME" 2>/dev/null || true
echo "Container Seller Control dihentikan/dihapus. Data dan key TIDAK dihapus."
