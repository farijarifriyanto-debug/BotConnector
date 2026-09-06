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
IMAGE="$NAME:1.3.0-universal-license"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/$NAME/universal-license-$STAMP"

fail(){ echo; echo "GAGAL: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "$1 tidak ditemukan"; }

[ "$(id -u)" -eq 0 ] || fail "Jalankan dengan sudo bash"
need docker; need python3; need curl

echo "============================================================"
echo " APPLICATION LICENSE CONTROL — UNIVERSAL LICENSE ENGINE V1"
echo " RESTAURANT + VEHICLE WASH + WORKSHOP + RETAIL"
echo " TRIAL -> FULL -> UPGRADE = KODE SAJA"
echo "============================================================"
echo "HOST=$(hostname)"
echo "UTC=$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo

test -s "$APP" || fail "$APP tidak ditemukan"
test -s "$ENVF" || fail "$ENVF tidak ditemukan"
test -s "$KEY" || fail "$KEY tidak ditemukan"
grep -q 'RESTAURANT_SELLER_PANEL_V1' "$APP" || fail "Seller Control belum terintegrasi ke /panel/"
grep -q 'BUSINESS_TRIAL_3D_V1' "$APP" || fail "Baseline Trial 3 Hari sebelumnya tidak ditemukan"
curl -fsS "http://127.0.0.1:${PORT}/health" >/tmp/universal-license-health-before.json || fail "Seller Control :$PORT tidak sehat"

echo "===== 1. BACKUP ====="
mkdir -p "$BACKUP"
chmod 700 "$BACKUP"
cp -a "$APP" "$BACKUP/app.py"
cp -a "$ENVF" "$BACKUP/env"
if [ -f "$DATA/licenses.db" ]; then
  SRC_DB="$DATA/licenses.db" DST_DB="$BACKUP/licenses.db" python3 - <<'PY'
import os, sqlite3
src=os.environ['SRC_DB']; dst=os.environ['DST_DB']
a=sqlite3.connect(src); b=sqlite3.connect(dst)
with b: a.backup(b)
b.close(); a.close()
PY
fi
printf 'APP_SHA_BEFORE='; sha256sum "$APP" | awk '{print $1}'
printf 'KEY_SHA_BEFORE='; sha256sum "$KEY" | awk '{print $1}'
echo "BACKUP=$BACKUP"
echo

echo "===== 2. PATCH SOURCE ====="
if grep -q 'UNIVERSAL_LICENSE_ENGINE_V1' "$APP"; then
  echo "PATCH=ALREADY_PRESENT"
else
  APP_PATH="$APP" python3 - <<'PY'
from pathlib import Path
import os
p=Path(os.environ['APP_PATH'])
s=p.read_text(encoding='utf-8')

# Current baseline normally already imports timedelta from the 3-day trial patch.
if 'from datetime import datetime, timezone, timedelta\n' not in s:
    if 'from datetime import datetime, timezone\n' not in s:
        raise SystemExit('GAGAL: datetime import tidak dikenali')
    s=s.replace('from datetime import datetime, timezone\n','from datetime import datetime, timezone, timedelta\n',1)

anchor='@APP.get("/health")\ndef health():'
if anchor not in s:
    raise SystemExit('GAGAL: health anchor tidak ditemukan')

engine=r'''# UNIVERSAL_LICENSE_ENGINE_V1
UNIVERSAL_PRODUCTS = {
    "restaurant": "Restaurant",
    "vehicle_wash": "Vehicle Wash",
    "workshop": "Workshop",
    "retail": "Retail",
}
UNIVERSAL_LICENSE_TYPES = {
    "trial": "Trial 3 Hari",
    "full": "Full",
    "upgrade": "Upgrade",
}
UNIVERSAL_TRIAL_HOURS = 72

def issue_universal_token(customer: str, product: str, license_type: str, edition: str, device: str, note: str = ""):
    customer = customer.strip()
    product = product.strip().lower()
    license_type = license_type.strip().lower()
    edition = edition.strip()
    device = "".join(ch for ch in device.strip().upper() if ch.isalnum())
    note = note.strip()
    if not customer or len(customer) > 100:
        raise ValueError("Nama customer tidak valid")
    if product not in UNIVERSAL_PRODUCTS:
        raise ValueError("Produk tidak valid")
    if license_type not in UNIVERSAL_LICENSE_TYPES:
        raise ValueError("Jenis lisensi tidak valid")
    if edition not in ED:
        raise ValueError("Paket tidak valid")
    if len(device) != 16:
        raise ValueError("ID perangkat harus 16 karakter")
    if not KEY.is_file():
        raise RuntimeError("Private key lisensi tidak ditemukan")

    prefix = {"restaurant":"RST", "vehicle_wash":"VWH", "workshop":"WSH", "retail":"RTL"}[product]
    kind = {"trial":"TRL", "full":"FUL", "upgrade":"UPG"}[license_type]
    lid = f"{prefix}-{kind}-" + secrets.token_hex(5).upper()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    at = now.isoformat().replace("+00:00", "Z")
    payload = {
        "v": 2,
        "license_id": lid,
        "customer": customer,
        "product": product,
        "license_type": license_type,
        "edition": edition,
        "device": device,
        # Native verifier keeps backward-compatible perpetual=true; JS Universal Engine
        # enforces trial expiry and upgrade semantics after cryptographic verification.
        "perpetual": True,
        "issued_at": at,
        "note": note,
    }
    expires_at = ""
    if license_type == "trial":
        exp = now + timedelta(hours=UNIVERSAL_TRIAL_HOURS)
        expires_at = exp.isoformat().replace("+00:00", "Z")
        payload.update({"trial_days": 3, "expires_at": expires_at})

    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
    priv = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    sig = priv.sign(raw, ec.ECDSA(hashes.SHA256()))
    token = "RAI1." + b64u(raw) + "." + b64u(sig)

    label = f"{UNIVERSAL_PRODUCTS[product]} | {UNIVERSAL_LICENSE_TYPES[license_type]} | {edition}"
    db_note = note
    if expires_at:
        db_note = (f"expires={expires_at}" + (f"; {note}" if note else ""))[:200]
    with conn() as con:
        con.execute(
            'INSERT INTO licenses(license_id,customer,edition,device,issued_at,note,token) VALUES(?,?,?,?,?,?,?)',
            (lid, customer, label, device, at, db_note, token),
        )
        con.commit()
    return lid, token, expires_at

'''
s=s.replace(anchor,engine+anchor,1)

# Replace both older issuance cards (old Restaurant form + old shared 3-app trial form)
# with a single product-specific Universal License form. Old routes/functions remain only
# for backward compatibility with already-issued tokens, but are no longer shown.
ui_start=s.find('<div class="card"><h2>Terbitkan Lisensi</h2>')
history_anchor='<div class="card"><div class="top"><div><h2 style="margin:0">Riwayat Lisensi</h2>'
ui_end=s.find(history_anchor, ui_start)
if ui_start < 0 or ui_end < 0:
    raise SystemExit(f'GAGAL: UI issuance anchor tidak ditemukan start={ui_start} end={ui_end}')

universal_ui=r'''<div class="card hero"><h2>Universal License Engine</h2><p class="muted">Pilih aplikasi dan jenis lisensi. <b>Trial → Full → Upgrade cukup memakai kode baru pada APK yang sama.</b></p><form method="post" action="{u('/issue-universal')}"><input type="hidden" name="csrf" value="{csrf}"><div class="grid"><div><label>Produk</label><select name="product"><option value="restaurant">Restaurant</option><option value="vehicle_wash">Vehicle Wash</option><option value="workshop">Workshop</option><option value="retail">Retail</option></select></div><div><label>Jenis Lisensi</label><select name="license_type"><option value="trial">Trial 3 Hari</option><option value="full">Full</option><option value="upgrade">Upgrade</option></select></div><div><label>Paket / Edition</label><select name="edition">{opts}</select></div><div><label>ID Perangkat</label><input name="device" maxlength="19" required placeholder="16 karakter dari aplikasi" autocapitalize="characters"></div><div style="grid-column:1/-1"><label>Nama Customer / Usaha</label><input name="customer" maxlength="100" required placeholder="Nama usaha / pemilik"></div><div style="grid-column:1/-1"><label>Catatan</label><input name="note" maxlength="200" placeholder="Opsional"></div></div><br><button>BUAT KODE LISENSI</button></form><div class="notice" style="margin-top:14px"><b>Penting:</b> ID perangkat berbeda untuk setiap aplikasi. Ambil ID dari aplikasi yang akan diaktifkan. Trial berlaku 72 jam sejak kode diterbitkan. Full bersifat permanen. Upgrade membuka paket yang sama atau lebih tinggi tanpa instal APK baru.</div></div>
'''
s=s[:ui_start]+universal_ui+s[ui_end:]

# Insert the new route before the legacy trial route if present.
route_anchor='@APP.post("/issue-trial", response_class=HTMLResponse)'
if route_anchor not in s:
    route_anchor='@APP.post("/show-token", response_class=HTMLResponse)'
if route_anchor not in s:
    raise SystemExit('GAGAL: route insertion anchor tidak ditemukan')

route=r'''@APP.post("/issue-universal", response_class=HTMLResponse)
def issue_universal(request: Request, csrf: str = Form(...), customer: str = Form(...), product: str = Form(...), license_type: str = Form(...), edition: str = Form(...), device: str = Form(...), note: str = Form("")):
    verify_csrf(request, csrf)
    try:
        lid, token, expires_at = issue_universal_token(customer, product, license_type, edition, device, note)
    except Exception as e:
        raise HTTPException(400, str(e))
    product_label = UNIVERSAL_PRODUCTS[product]
    type_label = UNIVERSAL_LICENSE_TYPES[license_type]
    expiry = f'<br><b>Berakhir:</b> {escape(expires_at)}' if expires_at else ''
    return page(f"""<div class="card hero"><h2>Kode lisensi berhasil dibuat</h2><p><b>{escape(lid)}</b></p><div class="notice"><b>Produk:</b> {escape(product_label)}<br><b>Jenis:</b> {escape(type_label)}<br><b>Paket:</b> {escape(edition)}<br><b>Customer:</b> {escape(customer)}<br><b>ID Perangkat:</b> {escape("".join(ch for ch in device.upper() if ch.isalnum()))}{expiry}</div><br><div id="token" class="token">{escape(token)}</div><br><button onclick="navigator.clipboard.writeText(document.getElementById('token').innerText);this.innerText='TERSALIN ✓'">SALIN KODE</button> <a class="btn secondary" href="{u('/')}">KEMBALI</a></div>""", "Kode Lisensi")

'''
s=s.replace(route_anchor,route+route_anchor,1)

# Generalize visible branding. Keep path and service name stable to avoid touching Nginx.
s=s.replace('Restaurant - Seller Control','Application License Control')
s=s.replace('Penerbit kode aktivasi jual lepas','Restaurant • Vehicle Wash • Workshop • Retail')

p.write_text(s,encoding='utf-8')
PY
fi

python3 -m py_compile "$APP"
grep -q 'UNIVERSAL_LICENSE_ENGINE_V1' "$APP" || fail "Marker universal tidak ditemukan"
grep -q '/issue-universal' "$APP" || fail "Route universal tidak ditemukan"
grep -q 'value="vehicle_wash"' "$APP" || fail "Pilihan Vehicle Wash tidak ditemukan"
grep -q 'value="workshop"' "$APP" || fail "Pilihan Workshop tidak ditemukan"
grep -q 'value="retail"' "$APP" || fail "Pilihan Retail tidak ditemukan"
echo "SOURCE_PATCH=PASS"
echo

echo "===== 3. REBUILD SELLER ONLY ====="
docker build -t "$IMAGE" "$BASE/app"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --env-file "$ENVF" \
  -e LICENSE_DB=/data/licenses.db \
  -e LICENSE_PRIVATE_KEY=/run/secrets/license-private.pem \
  -v "$DATA:/data" \
  -v "$KEY:/run/secrets/license-private.pem:ro" \
  -p "127.0.0.1:${PORT}:8080" \
  "$IMAGE" >/dev/null

for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/tmp/universal-license-health-after.json 2>/dev/null; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/health" >/tmp/universal-license-health-after.json || fail "Health Seller Control gagal"
echo "SELLER_HEALTH=$(cat /tmp/universal-license-health-after.json)"
echo "SELLER_CONTAINER=$(docker ps --filter name=^/${CONTAINER}$ --format '{{.Status}} | {{.Ports}}')"
echo

echo "===== 4. CRYPTO + CONSTANT VERIFY ====="
docker exec -i "$CONTAINER" python - <<'PY'
import app
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
p=app.KEY.read_bytes()
k=serialization.load_pem_private_key(p,password=None)
msg=b'universal-license-health-test'
sig=k.sign(msg,ec.ECDSA(hashes.SHA256()))
k.public_key().verify(sig,msg,ec.ECDSA(hashes.SHA256()))
print('PRODUCTS=',','.join(app.UNIVERSAL_PRODUCTS.keys()))
print('LICENSE_TYPES=',','.join(app.UNIVERSAL_LICENSE_TYPES.keys()))
print('TRIAL_HOURS=',app.UNIVERSAL_TRIAL_HOURS)
print('KEY_READ_PARSE_SIGN_VERIFY=PASS')
PY

echo
echo "===== 5. FINAL INTEGRITY ====="
printf 'APP_SHA_AFTER='; sha256sum "$APP" | awk '{print $1}'
printf 'KEY_SHA_AFTER='; sha256sum "$KEY" | awk '{print $1}'
printf 'NGINX='; systemctl is-active nginx
printf 'ADMIN_GATE='; systemctl is-active admin-gate.service

echo
echo "============================================================"
echo " UNIVERSAL LICENSE ENGINE = PASS"
echo "============================================================"
echo "PANEL=https://botconnector.id/panel/restaurant/"
echo "PRODUCTS=Restaurant, Vehicle Wash, Workshop, Retail"
echo "LICENSES=Trial 3 Hari, Full, Upgrade"
echo "TRIAL=72 jam"
echo "APK_CHANGE_AFTER_THIS=NO untuk perubahan lisensi/paket"
echo "PRIVATE_KEY_CHANGED=NO"
echo "NGINX_CHANGED=NO"
echo "ADMIN_GATE_CHANGED=NO"
echo "BACKUP=$BACKUP"
echo "============================================================"
