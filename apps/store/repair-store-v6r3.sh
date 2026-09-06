#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C

PORT=18194
HOST=botconnector.id
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/botconnector-store/nginx-route-v6r3-$STAMP"
TARGET=""
RESTORE_NEEDED=0
TMP_HOME="/tmp/botconnector-store-v6r3-backend-home.html"
TMP_HTTPS="/tmp/botconnector-store-v6r3-https-home.html"

fail(){ echo; echo "GAGAL: $*" >&2; exit 1; }
restore(){
  rc=$?
  if [ "$rc" -ne 0 ] && [ "$RESTORE_NEEDED" -eq 1 ] && [ -n "$TARGET" ] && [ -s "$BACKUP/botconnector-cutover.conf" ]; then
    echo "Memulihkan Nginx karena validasi gagal..." >&2
    cat "$BACKUP/botconnector-cutover.conf" > "$TARGET" || true
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap restore EXIT

[ "$(id -u)" -eq 0 ] || fail "Jalankan dengan sudo"
for c in python3 nginx curl systemctl grep; do command -v "$c" >/dev/null || fail "$c tidak ditemukan"; done
systemctl is-active --quiet botconnector-store.service || fail "botconnector-store.service tidak aktif"

curl --noproxy '*' -fsS "http://127.0.0.1:$PORT/health" >/dev/null || fail "Backend Store /health tidak sehat"
curl --noproxy '*' -fsS "http://127.0.0.1:$PORT/store/" -o "$TMP_HOME" || fail "Backend /store/ tidak dapat dibaca"
grep -Fq 'BotConnector Store' "$TMP_HOME" || fail "Backend /store/ tidak sesuai"

TARGET="$(grep -RslE '^[[:space:]]*server_name[[:space:]]+botconnector\.id[[:space:]]*;' /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1 || true)"
[ -n "$TARGET" ] || fail "File Nginx dengan server_name botconnector.id tidak ditemukan"

echo "NGINX_TARGET=$TARGET"
mkdir -p "$BACKUP"
chmod 700 "$BACKUP"
cp -L "$TARGET" "$BACKUP/botconnector-cutover.conf"
RESTORE_NEEDED=1

TARGET="$TARGET" python3 - <<'PY'
from pathlib import Path
import os,re

p=Path(os.environ['TARGET'])
text=p.read_text(encoding='utf-8')
lines=text.splitlines(keepends=True)

server_starts=[i for i,l in enumerate(lines) if re.match(r'^\s*server\s*\{\s*(?:#.*)?$',l)]
apex=[i for i,l in enumerate(lines) if re.match(r'^\s*server_name\s+botconnector\.id\s*;\s*(?:#.*)?$',l)]

if not server_starts:
    raise SystemExit('GAGAL: deklarasi server { tidak ditemukan')
if not apex:
    raise SystemExit('GAGAL: server_name botconnector.id; tidak ditemukan')

candidates=[]
for name_i in apex:
    starts=[s for s in server_starts if s < name_i]
    if not starts:
        continue
    st=starts[-1]
    next_st=next((s for s in server_starts if s > st), len(lines))
    if not (st < name_i < next_st):
        continue
    segment=''.join(lines[st:next_st])
    if re.search(r'(?m)^\s*listen\s+(?:\[::\]:)?443\b[^;]*;', segment):
        candidates.append((st,name_i,next_st))

print(f'APEX_DECLARATIONS={len(apex)}')
print(f'HTTPS_APEX_CANDIDATES={len(candidates)}')
if len(candidates) != 1:
    for n,(st,name_i,next_st) in enumerate(candidates,1):
        print(f'CANDIDATE_{n}_SERVER_LINE={st+1}')
        print(f'CANDIDATE_{n}_SERVER_NAME_LINE={name_i+1}')
    raise SystemExit('GAGAL: blok HTTPS apex tidak unik; tidak ada perubahan yang ditulis')

st,name_i,next_st=candidates[0]
segment=''.join(lines[st:next_st])
if 'BOTCONNECTOR_STORE_' in segment or re.search(r'(?m)^\s*location\s+(?:=\s*)?/store/?\b',segment):
    raise SystemExit('GAGAL: blok Store sudah ada pada server HTTPS apex; audit dulu sebelum menambah lagi')

snippet = '''\n    # BOTCONNECTOR_STORE_V6R3\n    location = /store {\n        return 308 /store/;\n    }\n\n    location ^~ /store/ {\n        proxy_pass http://127.0.0.1:18194;\n        proxy_http_version 1.1;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto $scheme;\n        proxy_connect_timeout 5s;\n        proxy_read_timeout 30s;\n        proxy_send_timeout 30s;\n        client_max_body_size 2m;\n    }\n'''

# Insert immediately after the exact server_name line. This avoids guessing the
# closing brace of a very large production server block.
lines.insert(name_i+1, snippet)
p.write_text(''.join(lines), encoding='utf-8')
print(f'HTTPS_APEX_SERVER_LINE={st+1}')
print(f'HTTPS_APEX_SERVER_NAME_LINE={name_i+1}')
print('INSERT_MODE=AFTER_EXACT_SERVER_NAME')
PY

nginx -t || fail "nginx -t gagal"

grep -n -A20 -B3 'BOTCONNECTOR_STORE_V6R3' "$TARGET" || fail "Marker Store V6R3 tidak ditemukan setelah penulisan"

systemctl reload nginx
sleep 1

curl --noproxy '*' -fsS \
  --resolve "$HOST:443:127.0.0.1" \
  "https://$HOST/store/" -o "$TMP_HTTPS" \
  || fail "HTTPS /store/ tidak dapat dibaca"
grep -Fq 'BotConnector Store' "$TMP_HTTPS" || fail "HTTPS /store/ tidak menuju Store"

for slug in restaurant vehicle-wash workshop retail; do
  curl --noproxy '*' -fsS --resolve "$HOST:443:127.0.0.1" \
    "https://$HOST/store/$slug/" -o /dev/null || fail "Produk $slug gagal"
done

for slug in restaurant vehicle-wash workshop retail; do
  curl --noproxy '*' -fsS --resolve "$HOST:443:127.0.0.1" \
    "https://$HOST/store/download/$slug.apk" -o /dev/null || fail "APK $slug gagal"
done

curl --noproxy '*' -fsS --resolve "$HOST:443:127.0.0.1" "https://$HOST/store/panduan/" -o /dev/null || fail "Panduan gagal"
curl --noproxy '*' -fsS --resolve "$HOST:443:127.0.0.1" "https://$HOST/store/status/" -o /dev/null || fail "Status gagal"

RESTORE_NEEDED=0
trap - EXIT

echo "============================================================"
echo " BOTCONNECTOR STORE V6R3 — NGINX REPAIR PASS"
echo "============================================================"
echo "STORE=https://botconnector.id/store/"
echo "BACKUP=$BACKUP"
echo "NGINX_TARGET=$TARGET"
echo "NEXT=sudo bash production-check.sh"
