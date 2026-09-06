#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
NAME="restaurant-seller-control"
BASE="/opt/$NAME"
APP="$BASE/app/app.py"
ENVF="/etc/$NAME/.env"
KEY="/etc/$NAME/license-private.pem"
DATA="/var/lib/$NAME"
PORT="18192"
CONTAINER="$NAME"
IMAGE="$NAME:1.3.2-store-api-v2"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/$NAME/store-api-v2-$STAMP"
SECRET="${STORE_API_SECRET:-}"
fail(){ echo "GAGAL: $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "Jalankan sebagai root/sudo"
command -v docker >/dev/null || fail "docker tidak ditemukan"
command -v python3 >/dev/null || fail "python3 tidak ditemukan"
command -v curl >/dev/null || fail "curl tidak ditemukan"
[ -n "$SECRET" ] || fail "STORE_API_SECRET wajib diberikan oleh deploy Store"
test -s "$APP" || fail "$APP tidak ditemukan"
test -s "$ENVF" || fail "$ENVF tidak ditemukan"
test -s "$KEY" || fail "$KEY tidak ditemukan"
grep -q 'UNIVERSAL_LICENSE_ENGINE_V1' "$APP" || fail "Universal License Engine V1 belum terpasang"
grep -q 'def issue_universal_token' "$APP" || fail "issue_universal_token tidak ditemukan"
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || fail "Seller Control tidak sehat sebelum patch"

mkdir -p "$BACKUP"; chmod 700 "$BACKUP"
cp -a "$APP" "$BACKUP/app.py"; cp -a "$ENVF" "$BACKUP/env"
if [ -f "$DATA/licenses.db" ]; then
  SRC_DB="$DATA/licenses.db" DST_DB="$BACKUP/licenses.db" python3 - <<'PY'
import os, sqlite3
src=os.environ['SRC_DB']; dst=os.environ['DST_DB']
a=sqlite3.connect(src); b=sqlite3.connect(dst)
with b: a.backup(b)
b.close(); a.close()
PY
fi

APP_PATH="$APP" python3 - <<'PY'
from pathlib import Path
import os
p=Path(os.environ['APP_PATH'])
s=p.read_text(encoding='utf-8')
anchor='@APP.get("/health")\ndef health():'
if anchor not in s:
    raise SystemExit('GAGAL: anchor health tidak ditemukan')

issue='''# STORE_LICENSE_API_V1\n@APP.post("/api/store/issue")\nasync def store_license_issue(request: Request):\n    expected = __import__("os").environ.get("STORE_API_SECRET", "")\n    supplied = request.headers.get("X-Store-Secret", "")\n    if not expected or not secrets.compare_digest(supplied, expected):\n        raise HTTPException(403, "Forbidden")\n    try:\n        body = await request.json()\n        lid, token, expires_at = issue_universal_token(\n            str(body.get("customer", "")),\n            str(body.get("product", "")),\n            str(body.get("license_type", "")),\n            str(body.get("edition", "")),\n            str(body.get("device", "")),\n            str(body.get("note", "")),\n        )\n    except HTTPException:\n        raise\n    except Exception as e:\n        raise HTTPException(400, str(e))\n    return {"ok": True, "license_id": lid, "token": token, "expires_at": expires_at}\n\n'''
if 'STORE_LICENSE_API_V1' not in s:
    s=s.replace(anchor,issue+anchor,1)

status='''# STORE_LICENSE_API_V2\n@APP.post("/api/store/status")\nasync def store_license_status(request: Request):\n    expected = __import__("os").environ.get("STORE_API_SECRET", "")\n    supplied = request.headers.get("X-Store-Secret", "")\n    if not expected or not secrets.compare_digest(supplied, expected):\n        raise HTTPException(403, "Forbidden")\n    body = await request.json()\n    product = str(body.get("product", "")).strip().lower()\n    device = "".join(ch for ch in str(body.get("device", "")).strip().upper() if ch.isalnum())\n    if product not in UNIVERSAL_PRODUCTS:\n        raise HTTPException(400, "Produk tidak valid")\n    if len(device) != 16:\n        raise HTTPException(400, "ID perangkat harus 16 karakter")\n    product_label = UNIVERSAL_PRODUCTS[product]\n    levels = {"Essential":0,"Lengkap":1,"Professional":2,"Multi Outlet":3}\n    has_trial = False\n    current = None\n    current_level = -1\n    last_issued_at = None\n    with conn() as con:\n        rows = con.execute(\n            "SELECT edition,issued_at FROM licenses WHERE device=? ORDER BY issued_at DESC",\n            (device,),\n        ).fetchall()\n    for row in rows:\n        label = str(row[0] or "")\n        parts = [x.strip() for x in label.split("|")]\n        if len(parts) < 3 or parts[0] != product_label:\n            continue\n        kind, edition = parts[1], parts[2]\n        if last_issued_at is None:\n            last_issued_at = str(row[1] or "")\n        if kind == UNIVERSAL_LICENSE_TYPES.get("trial"):\n            has_trial = True\n            continue\n        if kind in {UNIVERSAL_LICENSE_TYPES.get("full"), UNIVERSAL_LICENSE_TYPES.get("upgrade")} and edition in levels:\n            if levels[edition] > current_level:\n                current, current_level = edition, levels[edition]\n    return {\n        "ok": True,\n        "product": product,\n        "device": device,\n        "has_trial": has_trial,\n        "has_paid": current is not None,\n        "current_edition": current,\n        "last_issued_at": last_issued_at,\n    }\n\n'''
if 'STORE_LICENSE_API_V2' not in s:
    s=s.replace(anchor,status+anchor,1)
p.write_text(s,encoding='utf-8')
PY

python3 -m py_compile "$APP"
grep -q 'STORE_LICENSE_API_V2' "$APP" || fail "marker Store API V2 gagal"

python3 - "$ENVF" "$SECRET" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); secret=sys.argv[2]
lines=p.read_text(encoding='utf-8').splitlines()
lines=[x for x in lines if not x.startswith('STORE_API_SECRET=')]
lines.append('STORE_API_SECRET='+secret)
p.write_text('\n'.join(lines)+'\n',encoding='utf-8')
PY
chmod 600 "$ENVF"

echo "Rebuild Seller Control dengan source, database, dan private key yang sama..."
docker build -t "$IMAGE" "$BASE/app" >/dev/null
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" --restart unless-stopped --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m --cap-drop ALL --security-opt no-new-privileges:true \
  --env-file "$ENVF" -e LICENSE_DB=/data/licenses.db -e LICENSE_PRIVATE_KEY=/run/secrets/license-private.pem \
  -v "$DATA:/data" -v "$KEY:/run/secrets/license-private.pem:ro" -p "127.0.0.1:${PORT}:8080" "$IMAGE" >/dev/null
for _ in $(seq 1 35); do curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || fail "Seller Control gagal sehat setelah patch"
code="$(curl -sS -o /tmp/store-seller-unauth.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/api/store/status" -H 'Content-Type: application/json' -d '{}' || true)"
[ "$code" = "403" ] || fail "Auth guard status tidak menghasilkan 403 (got $code)"
status="$(curl -fsS -X POST "http://127.0.0.1:$PORT/api/store/status" -H 'Content-Type: application/json' -H "X-Store-Secret: $SECRET" -d '{"product":"retail","device":"AAAAAAAAAAAAAAAA"}')"
printf '%s' "$status" | grep -q '"ok":true' || printf '%s' "$status" | grep -q '"ok": true' || fail "Status endpoint tidak sehat"
echo "SELLER_STORE_API_V2=PASS"
echo "BACKUP=$BACKUP"
