#!/usr/bin/env bash
set -Eeuo pipefail
PORT=18194
BASE="https://botconnector.id"
APPROOT="/opt/botconnector-store/current"
[ "$(id -u)" -eq 0 ] || { echo "Jalankan dengan sudo" >&2; exit 1; }
echo "===== BOTCONNECTOR STORE V6R2 — PRODUCTION CHECK ====="
systemctl is-active --quiet botconnector-store.service && echo "SERVICE=PASS"
curl -fsS http://127.0.0.1:$PORT/health | tee /tmp/store-v6r2-health.json; echo
nginx -t >/dev/null && echo "NGINX=PASS"

home="$(curl -fsS --resolve botconnector.id:443:127.0.0.1 "$BASE/store/")"
printf '%s' "$home" | grep -q 'BotConnector Store' || { echo "HOME_TITLE=FAIL"; exit 1; }
printf '%s' "$home" | grep -q 'BotConnector Business' && { echo "HOME_COPY=FAIL"; exit 1; } || true
echo "HOME_COPY=PASS"

for path in /store/ /store/restaurant/ /store/vehicle-wash/ /store/workshop/ /store/retail/ /store/panduan/ /store/status/; do
  curl -fsS --resolve botconnector.id:443:127.0.0.1 "$BASE$path" >/dev/null
  echo "ROUTE $path=PASS"
done
for slug in restaurant vehicle-wash workshop retail; do
  curl -fsS --resolve botconnector.id:443:127.0.0.1 -o /dev/null "$BASE/store/download/$slug.apk"
  echo "APK_ROUTE $slug=PASS"
done

python3 - "$APPROOT/app/static/downloads" <<'PY'
from pathlib import Path
import hashlib,sys
root=Path(sys.argv[1])
expected={
'Vehicle-Wash-2.0.0-Universal-License.apk':'2daa8ed707b71a87f36c5392bec844ee9b546c54140fe4bd961b8a295378cb47',
'Workshop-2.0.0-Universal-License.apk':'19a59250a4c0a4725577ede93617ce1cf01bdd3c3137b2b324985c35f0104e71',
'Retail-2.0.0-Universal-License.apk':'48c7d6c3cdc6c2ace97d6673f40c5ed84caf26b6861ebdb9e3a64f185658bb8b',
'Restaurant-All-in-One-R8-Universal-License.apk':'4f0598ea53e4ccbcb54ad1e22254d663fe9023e02ab91897dd351d4777d54256',
}
for n,w in expected.items():
    p=root/n
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=w:
        raise SystemExit('APK_SHA=FAIL '+n)
print('APK_SHA=PASS')
PY

ENVF=/etc/botconnector-store/.env
secret="$(sed -n 's/^SELLER_SECRET=//p' "$ENVF" | tail -1)"
[ -n "$secret" ]
unauth="$(curl -sS -o /tmp/store-v6r2-seller-unauth.json -w '%{http_code}' -X POST http://127.0.0.1:18192/api/store/status -H 'Content-Type: application/json' -d '{}' || true)"
[ "$unauth" = "403" ] || { echo "SELLER_AUTH_GUARD=FAIL HTTP=$unauth"; exit 1; }
echo "SELLER_AUTH_GUARD=PASS"
curl -fsS -X POST http://127.0.0.1:18192/api/store/status -H 'Content-Type: application/json' -H "X-Store-Secret: $secret" -d '{"product":"retail","device":"AAAAAAAAAAAAAAAA"}' >/tmp/store-v6r2-seller-status.json
grep -q '"ok"' /tmp/store-v6r2-seller-status.json && echo "SELLER_STATUS=PASS"

admin_code="$(curl -sS -o /tmp/store-v6r2-admin-unauth.json -w '%{http_code}' --resolve botconnector.id:443:127.0.0.1 "$BASE/store/api/admin/orders" || true)"
[ "$admin_code" = "401" ] || { echo "ADMIN_AUTH_GUARD=FAIL HTTP=$admin_code"; exit 1; }
echo "ADMIN_AUTH_GUARD=PASS"
echo "PRODUCTION_CHECK=PASS"
