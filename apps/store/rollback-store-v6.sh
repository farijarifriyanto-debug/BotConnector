#!/usr/bin/env bash
set -Eeuo pipefail
APPROOT="/opt/botconnector-store"
SERVICE="botconnector-store.service"
[ "$(id -u)" -eq 0 ] || { echo "Jalankan dengan sudo" >&2; exit 1; }
PREV="$(readlink -f "$APPROOT/previous" 2>/dev/null || true)"
[ -n "$PREV" ] && [ -d "$PREV" ] || { echo "Release sebelumnya tidak tersedia di $APPROOT/previous" >&2; exit 1; }
CUR="$(readlink -f "$APPROOT/current" 2>/dev/null || true)"
ln -sfn "$PREV" "$APPROOT/current"
if [ -n "$CUR" ] && [ -d "$CUR" ]; then ln -sfn "$CUR" "$APPROOT/previous"; fi
systemctl restart "$SERVICE"
for _ in $(seq 1 20); do curl -fsS http://127.0.0.1:18194/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:18194/health >/dev/null
echo "ROLLBACK=PASS"
echo "CURRENT=$PREV"
