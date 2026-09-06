#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
ROOT="$(cd "$(dirname "$0")" && pwd)"
APPROOT="/opt/botconnector-store"
ETC="/etc/botconnector-store"
DATA="/var/lib/botconnector-store"
PORT=18194
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RELEASE="$APPROOT/releases/store-v6r2-$STAMP"
BACKUP="/var/backups/botconnector-store/v6r2-$STAMP"
SERVICE="botconnector-store.service"
NGINX_TARGET=""
PREVIOUS_RELEASE=""
NGINX_BACKED_UP=0
DEPLOY_COMMITTED=0

fail(){ echo; echo "GAGAL: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "$1 tidak ditemukan"; }
cleanup_on_error(){
  rc=$?
  if [ "$rc" -ne 0 ] && [ "$DEPLOY_COMMITTED" -eq 0 ]; then
    echo
    echo "Deployment gagal. Menjalankan rollback otomatis..." >&2
    if [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
      ln -sfn "$PREVIOUS_RELEASE" "$APPROOT/current" || true
      systemctl restart "$SERVICE" >/dev/null 2>&1 || true
    fi
    if [ "$NGINX_BACKED_UP" -eq 1 ] && [ -n "$NGINX_TARGET" ] && [ -s "$BACKUP/nginx.before-store.conf" ]; then
      cat "$BACKUP/nginx.before-store.conf" > "$NGINX_TARGET" || true
      nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap cleanup_on_error EXIT

[ "$(id -u)" -eq 0 ] || fail "Jalankan: sudo bash deploy-store-v6.sh"
need python3; need curl; need nginx; need systemctl; need openssl; need sha256sum; need ss
[ -s "$ROOT/app/app.py" ] || fail "Paket Store tidak lengkap"
[ -s "$ROOT/seller-control-store-api-patch-v2.sh" ] || fail "Seller API patch V2 tidak ada"

for apk in \
  Vehicle-Wash-2.0.0-Universal-License.apk \
  Workshop-2.0.0-Universal-License.apk \
  Retail-2.0.0-Universal-License.apk \
  Restaurant-All-in-One-R8-Universal-License.apk; do
  test -s "$ROOT/app/static/downloads/$apk" || fail "APK hilang: $apk"
done

python3 -m py_compile "$ROOT/app/app.py"
node_check="SKIP"
if command -v node >/dev/null 2>&1; then node --check "$ROOT/app/static/store.js"; node_check="PASS"; fi
for f in "$ROOT"/*.sh; do bash -n "$f"; done

# Verify the four APK binaries against the original Universal License package.
python3 - "$ROOT" <<'PY'
from pathlib import Path
import hashlib, sys
root=Path(sys.argv[1])
expected={
'Vehicle-Wash-2.0.0-Universal-License.apk':'2daa8ed707b71a87f36c5392bec844ee9b546c54140fe4bd961b8a295378cb47',
'Workshop-2.0.0-Universal-License.apk':'19a59250a4c0a4725577ede93617ce1cf01bdd3c3137b2b324985c35f0104e71',
'Retail-2.0.0-Universal-License.apk':'48c7d6c3cdc6c2ace97d6673f40c5ed84caf26b6861ebdb9e3a64f185658bb8b',
'Restaurant-All-in-One-R8-Universal-License.apk':'4f0598ea53e4ccbcb54ad1e22254d663fe9023e02ab91897dd351d4777d54256',
}
for name,want in expected.items():
    p=root/'app'/'static'/'downloads'/name
    got=hashlib.sha256(p.read_bytes()).hexdigest()
    if got!=want: raise SystemExit(f'GAGAL: SHA APK berbeda {name}: {got}')
print('APK_SHA256=PASS')
PY

echo "============================================================"
echo " BOTCONNECTOR STORE — PRODUCTION V6R2"
echo " UI V6 / 4 APLIKASI / TRIAL / FULL / UPGRADE / MIDTRANS"
echo "============================================================"
echo "HOST=$(hostname)"
echo "UTC=$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "NODE_CHECK=$node_check"
echo

if ss -lnt 2>/dev/null | grep -q ":$PORT "; then
  systemctl is-active --quiet "$SERVICE" || fail "Port $PORT sudah dipakai service lain"
fi

mkdir -p "$APPROOT/releases" "$ETC" "$DATA" "$BACKUP"
chmod 700 "$BACKUP"
if id botconnector-store >/dev/null 2>&1; then :; else useradd --system --home "$DATA" --shell /usr/sbin/nologin botconnector-store; fi

if [ -L "$APPROOT/current" ] || [ -d "$APPROOT/current" ]; then
  PREVIOUS_RELEASE="$(readlink -f "$APPROOT/current" 2>/dev/null || true)"
  if [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
    ln -sfn "$PREVIOUS_RELEASE" "$APPROOT/previous"
    printf '%s\n' "$PREVIOUS_RELEASE" > "$BACKUP/previous-release.txt"
  fi
fi

if [ -s "$DATA/store.db" ]; then
  SRC_DB="$DATA/store.db" DST_DB="$BACKUP/store.db" python3 - <<'PY'
import os, sqlite3
src=os.environ['SRC_DB']; dst=os.environ['DST_DB']
a=sqlite3.connect(src); b=sqlite3.connect(dst)
with b: a.backup(b)
b.close(); a.close()
PY
fi

ADMIN_SECRET="$(openssl rand -hex 18)"
COOKIE_SECRET="$(openssl rand -hex 32)"
SELLER_SECRET="$(openssl rand -hex 32)"
PAYMENT_MODE_VALUE="manual"
MIDTRANS_ENV_VALUE="sandbox"
MIDTRANS_KEY_VALUE=""
if [ -s "$ETC/.env" ]; then
  cp -a "$ETC/.env" "$BACKUP/store.env"
  getv(){ sed -n "s/^$1=//p" "$ETC/.env" | tail -1; }
  v="$(getv STORE_ADMIN_SECRET)"; [ -n "$v" ] && ADMIN_SECRET="$v"
  v="$(getv STORE_COOKIE_SECRET)"; [ -n "$v" ] && COOKIE_SECRET="$v"
  v="$(getv SELLER_SECRET)"; [ -n "$v" ] && SELLER_SECRET="$v"
  v="$(getv PAYMENT_MODE)"; [ -n "$v" ] && PAYMENT_MODE_VALUE="$v"
  v="$(getv MIDTRANS_ENV)"; [ -n "$v" ] && MIDTRANS_ENV_VALUE="$v"
  MIDTRANS_KEY_VALUE="$(getv MIDTRANS_SERVER_KEY)"
fi

cat > "$ETC/.env" <<EOF
STORE_DATA=$DATA
PUBLIC_BASE=https://botconnector.id
STORE_ENABLED=1
PAYMENT_MODE=$PAYMENT_MODE_VALUE
MIDTRANS_ENV=$MIDTRANS_ENV_VALUE
MIDTRANS_SERVER_KEY=$MIDTRANS_KEY_VALUE
SELLER_URL=http://127.0.0.1:18192
SELLER_SECRET=$SELLER_SECRET
STORE_ADMIN_SECRET=$ADMIN_SECRET
STORE_COOKIE_SECRET=$COOKIE_SECRET
TRIAL_AUTO_ISSUE=1
EOF
chown root:botconnector-store "$ETC/.env"; chmod 640 "$ETC/.env"

SELLER_APP="/opt/restaurant-seller-control/app/app.py"
[ -s "$SELLER_APP" ] || fail "Seller Control source tidak ditemukan: $SELLER_APP"
if ! grep -q 'UNIVERSAL_LICENSE_ENGINE_V1' "$SELLER_APP"; then
  ORIGINAL_PATCH="$ROOT/reference/universal-license-seller-patch-v1.sh"
  [ -s "$ORIGINAL_PATCH" ] || fail "Universal License prerequisite patch tidak ada"
  EXPECTED_ORIGINAL="ee1000fce4b0ef7bd7369b0af3ccc390a95a775e3f3dedc7ec9715bf5ebb1066"
  ACTUAL_ORIGINAL="$(sha256sum "$ORIGINAL_PATCH" | awk '{print $1}')"
  [ "$ACTUAL_ORIGINAL" = "$EXPECTED_ORIGINAL" ] || fail "Checksum Universal License prerequisite berbeda"
  echo "Memasang Universal License Engine prerequisite..."
  bash "$ORIGINAL_PATCH"
fi
STORE_API_SECRET="$SELLER_SECRET" bash "$ROOT/seller-control-store-api-patch-v2.sh"

mkdir -p "$RELEASE"
cp -a "$ROOT/app" "$RELEASE/"
cp -a "$ROOT/requirements.txt" "$RELEASE/"
chown -R root:root "$RELEASE"; chmod -R go-w "$RELEASE"
ln -sfn "$RELEASE" "$APPROOT/current"

if [ ! -x "$APPROOT/venv/bin/python" ]; then python3 -m venv "$APPROOT/venv"; fi
"$APPROOT/venv/bin/pip" install --disable-pip-version-check --no-cache-dir -r "$RELEASE/requirements.txt" >/dev/null
chown -R botconnector-store:botconnector-store "$DATA"; chmod 750 "$DATA"

cp -a "$ROOT/systemd/botconnector-store.service" /etc/systemd/system/$SERVICE
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"
for _ in $(seq 1 30); do curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || { journalctl -u "$SERVICE" -n 80 --no-pager; fail "Store service tidak sehat"; }

NGINX_TARGET="$(grep -RslE 'server_name[[:space:]]+([^;[:space:]]+[[:space:]]+)*botconnector\.id([[:space:];]|$)' /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1 || true)"
[ -n "$NGINX_TARGET" ] || fail "Server block botconnector.id tidak ditemukan. Store hidup di 127.0.0.1:$PORT tetapi Nginx belum diubah."
cp -L "$NGINX_TARGET" "$BACKUP/nginx.before-store.conf"
NGINX_BACKED_UP=1

TARGET="$NGINX_TARGET" SNIPPET="$ROOT/nginx/store-location.conf" python3 - <<'PY'
from pathlib import Path
import os,re
p=Path(os.environ['TARGET']); s=p.read_text(); snippet=Path(os.environ['SNIPPET']).read_text().rstrip()+"\n"
# Remove any older BotConnector Store blocks inserted by previous Store releases.
while True:
    m=re.search(r'(?m)^\s*# BOTCONNECTOR_STORE_V\d+(?:R\d+)?\s*$',s)
    if not m: break
    start=m.start(); pos=m.end(); blocks=0; end=None
    while blocks<2:
        lm=re.search(r'\blocation\b[^\{]*\{',s[pos:])
        if not lm: break
        brace=pos+lm.end()-1; depth=0; block_end=None
        for i in range(brace,len(s)):
            if s[i]=='{': depth+=1
            elif s[i]=='}':
                depth-=1
                if depth==0:
                    block_end=i+1; break
        if block_end is None: break
        blocks+=1; pos=block_end; end=block_end
    if end is None: raise SystemExit('GAGAL: marker Store lama ditemukan tetapi block tidak dapat diparse')
    s=s[:start]+s[end:].lstrip('\n')

starts=[m.start() for m in re.finditer(r'\bserver\s*\{',s)]
candidates=[]
for st in starts:
    brace=s.find('{',st); depth=0; end=None
    for i in range(brace,len(s)):
        if s[i]=='{': depth+=1
        elif s[i]=='}':
            depth-=1
            if depth==0: end=i; break
    if end is None: continue
    block=s[st:end+1]
    exact_apex = re.search(r'(?m)^\s*server_name\s+botconnector\.id\s*;', block)
    https = re.search(r'(?m)^\s*listen\s+(?:\[::\]:)?443\b[^;]*;', block)
    if exact_apex and https:
        candidates.append((st,end))
if len(candidates) != 1:
    raise SystemExit(f'GAGAL: harus ada tepat 1 server HTTPS apex botconnector.id; ditemukan {len(candidates)}')
st,end=candidates[0]
indent='    '
insert='\n'+''.join(indent+line+'\n' if line else '\n' for line in snippet.splitlines())
s=s[:end]+insert+s[end:]
p.write_text(s)
PY

if ! nginx -t; then
  cat "$BACKUP/nginx.before-store.conf" > "$NGINX_TARGET"
  nginx -t || true
  fail "nginx -t gagal; konfigurasi dipulihkan"
fi
systemctl reload nginx

curl -fsS --resolve botconnector.id:443:127.0.0.1 https://botconnector.id/store/ >/tmp/botconnector-store-v6-home.html || fail "HTTPS /store/ gagal"
grep -q 'BotConnector Store' /tmp/botconnector-store-v6-home.html || fail "Konten Store tidak sesuai"
for slug in restaurant vehicle-wash workshop retail; do
  page="/tmp/botconnector-store-v6r2-${slug}.html"
  curl -fsS --resolve botconnector.id:443:127.0.0.1 "https://botconnector.id/store/$slug/" -o "$page" || fail "Halaman produk $slug tidak dapat dibaca"
  grep -Eq 'Paket &amp; harga|Paket & harga' "$page" || fail "Halaman produk $slug gagal"
  curl -fsS --resolve botconnector.id:443:127.0.0.1 -o /dev/null "https://botconnector.id/store/download/$slug.apk" || fail "Download $slug gagal"
done
curl -fsS --resolve botconnector.id:443:127.0.0.1 https://botconnector.id/store/panduan/ -o /tmp/botconnector-store-v6r2-panduan.html || fail "Panduan tidak dapat dibaca"
grep -Fq 'Panduan Store' /tmp/botconnector-store-v6r2-panduan.html || fail "Panduan gagal"
curl -fsS --resolve botconnector.id:443:127.0.0.1 https://botconnector.id/store/status/ -o /tmp/botconnector-store-v6r2-status.html || fail "Status Store tidak dapat dibaca"
grep -Fq 'Status Store' /tmp/botconnector-store-v6r2-status.html || fail "Status Store gagal"

DEPLOY_COMMITTED=1
trap - EXIT

echo
echo "=================== DEPLOY PASS ==================="
echo "STORE_URL=https://botconnector.id/store/"
echo "STORE_ADMIN=https://botconnector.id/store/admin/"
echo "STORE_ADMIN_SECRET=$ADMIN_SECRET"
echo "PAYMENT_MODE=$PAYMENT_MODE_VALUE"
echo "RELEASE=$RELEASE"
echo "BACKUP=$BACKUP"
if [ "$PAYMENT_MODE_VALUE" != "midtrans" ]; then
  echo "NEXT=Aktifkan pembayaran online: sudo bash configure-midtrans.sh production"
fi
echo "==================================================="
