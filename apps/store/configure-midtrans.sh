#!/usr/bin/env bash
set -Eeuo pipefail
ENVF="/etc/botconnector-store/.env"
MODE="${1:-production}"
[ "$(id -u)" -eq 0 ] || { echo "Jalankan dengan sudo" >&2; exit 1; }
[ -s "$ENVF" ] || { echo "$ENVF tidak ditemukan" >&2; exit 1; }
case "$MODE" in production|sandbox) ;; *) echo "Mode: production|sandbox" >&2; exit 1;; esac
KEY="${MIDTRANS_SERVER_KEY:-}"
if [ -z "$KEY" ]; then read -r -s -p "Midtrans Server Key: " KEY; echo; fi
[ -n "$KEY" ] || { echo "Server Key kosong" >&2; exit 1; }
cp -a "$ENVF" "$ENVF.bak.$(date -u +%Y%m%dT%H%M%SZ)"
python3 - "$ENVF" "$MODE" "$KEY" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); mode=sys.argv[2]; key=sys.argv[3]
rows=[]
for line in p.read_text().splitlines():
    if not line.startswith(('PAYMENT_MODE=','MIDTRANS_ENV=','MIDTRANS_SERVER_KEY=')): rows.append(line)
rows += ['PAYMENT_MODE=midtrans','MIDTRANS_ENV='+mode,'MIDTRANS_SERVER_KEY='+key]
p.write_text('\n'.join(rows)+'\n')
PY
chmod 640 "$ENVF"; chown root:botconnector-store "$ENVF"
systemctl restart botconnector-store.service
sleep 2
curl -fsS http://127.0.0.1:18194/health
echo
echo "MIDTRANS=$MODE ACTIVE"
echo "Notification URL di-override otomatis per transaksi: https://botconnector.id/store/api/payment/midtrans"
echo "Finish URL dibuat otomatis oleh Store untuk setiap pesanan."
