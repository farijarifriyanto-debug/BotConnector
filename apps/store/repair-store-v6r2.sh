#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
PORT=18194
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/botconnector-store/nginx-route-v6r2-$STAMP"
TARGET=""
RESTORE_NEEDED=0
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
command -v python3 >/dev/null || fail "python3 tidak ditemukan"
command -v nginx >/dev/null || fail "nginx tidak ditemukan"
command -v curl >/dev/null || fail "curl tidak ditemukan"
systemctl is-active --quiet botconnector-store.service || fail "botconnector-store.service tidak aktif"

curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || fail "Backend Store /health tidak sehat"
curl -fsS "http://127.0.0.1:$PORT/store/" -o /tmp/botconnector-store-v6r2-backend-home.html || fail "Backend /store/ tidak dapat dibaca"
grep -Fq 'BotConnector Store' /tmp/botconnector-store-v6r2-backend-home.html || fail "Backend /store/ tidak sesuai"

TARGET="$(grep -RslE '^[[:space:]]*server_name[[:space:]]+botconnector\.id[[:space:]]*;' /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -1 || true)"
[ -n "$TARGET" ] || fail "File Nginx dengan server_name botconnector.id tidak ditemukan"

mkdir -p "$BACKUP"; chmod 700 "$BACKUP"
cp -L "$TARGET" "$BACKUP/botconnector-cutover.conf"
RESTORE_NEEDED=1

TARGET="$TARGET" python3 - <<'PY'
from pathlib import Path
import os,re
p=Path(os.environ['TARGET'])
s=p.read_text()
marker='# BOTCONNECTOR_STORE_V6R2'

# Remove Store V6/V6R2 blocks if a previous repair attempt left one behind.
def remove_marked(text):
    while True:
        m=re.search(r'(?m)^\s*# BOTCONNECTOR_STORE_V6(?:R1)?\s*$', text)
        if not m:
            return text
        start=m.start()
        pos=m.end()
        removed=0
        end=None
        # marker is followed by exactly two location blocks
        while removed < 2:
            lm=re.search(r'\blocation\b[^\{]*\{', text[pos:])
            if not lm:
                raise SystemExit('GAGAL: marker Store ditemukan tetapi location tidak lengkap')
            brace=pos+lm.end()-1
            depth=0
            block_end=None
            for i in range(brace,len(text)):
                if text[i]=='{': depth+=1
                elif text[i]=='}':
                    depth-=1
                    if depth==0:
                        block_end=i+1
                        break
            if block_end is None:
                raise SystemExit('GAGAL: location Store tidak dapat diparse')
            removed += 1
            pos=block_end
            end=block_end
        text=text[:start]+text[end:].lstrip('\n')

s=remove_marked(s)
starts=[m.start() for m in re.finditer(r'\bserver\s*\{',s)]
candidates=[]
for st in starts:
    brace=s.find('{',st)
    depth=0; end=None
    for i in range(brace,len(s)):
        if s[i]=='{': depth+=1
        elif s[i]=='}':
            depth-=1
            if depth==0:
                end=i
                break
    if end is None:
        continue
    block=s[st:end+1]
    exact_apex=re.search(r'(?m)^\s*server_name\s+botconnector\.id\s*;',block)
    https=re.search(r'(?m)^\s*listen\s+(?:\[::\]:)?443\b[^;]*;',block)
    if exact_apex and https:
        candidates.append((st,end,block))

if len(candidates)!=1:
    print(f'HTTPS_APEX_CANDIDATES={len(candidates)}')
    for i,(st,end,block) in enumerate(candidates,1):
        names=re.findall(r'(?m)^\s*server_name\s+([^;]+);',block)
        listens=re.findall(r'(?m)^\s*listen\s+([^;]+);',block)
        print(f'CANDIDATE_{i}_SERVER_NAMES={names}')
        print(f'CANDIDATE_{i}_LISTENS={listens}')
    raise SystemExit('GAGAL: target server HTTPS apex tidak unik; tidak ada perubahan yang ditulis')

st,end,_=candidates[0]
snippet='''\n    # BOTCONNECTOR_STORE_V6R2\n    location = /store { return 308 /store/; }\n    location ^~ /store/ {\n        proxy_pass http://127.0.0.1:18194;\n        proxy_http_version 1.1;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto $scheme;\n        proxy_connect_timeout 5s;\n        proxy_read_timeout 30s;\n        proxy_send_timeout 30s;\n        client_max_body_size 2m;\n    }\n'''
s=s[:end]+snippet+s[end:]
p.write_text(s)
print('NGINX_TARGET='+str(p))
print('HTTPS_APEX_CANDIDATES=1')
PY

nginx -t || fail "nginx -t gagal"
systemctl reload nginx

curl -fsS --resolve botconnector.id:443:127.0.0.1 https://botconnector.id/store/ \
  -o /tmp/botconnector-store-v6r2-https-home.html || fail "HTTPS /store/ tidak dapat dibaca"
grep -Fq 'BotConnector Store' /tmp/botconnector-store-v6r2-https-home.html || fail "HTTPS /store/ masih gagal"

for slug in restaurant vehicle-wash workshop retail; do
  curl -fsS --resolve botconnector.id:443:127.0.0.1 \
    "https://botconnector.id/store/$slug/" >/dev/null || fail "Produk $slug gagal"
  curl -fsS --resolve botconnector.id:443:127.0.0.1 -o /dev/null \
    "https://botconnector.id/store/download/$slug.apk" || fail "APK $slug gagal"
done

curl -fsS --resolve botconnector.id:443:127.0.0.1 https://botconnector.id/store/panduan/ >/dev/null || fail "Panduan gagal"
curl -fsS --resolve botconnector.id:443:127.0.0.1 https://botconnector.id/store/status/ >/dev/null || fail "Status gagal"

RESTORE_NEEDED=0
trap - EXIT

echo "============================================================"
echo " BOTCONNECTOR STORE V6R2 — NGINX REPAIR PASS"
echo "============================================================"
echo "STORE=https://botconnector.id/store/"
echo "BACKUP=$BACKUP"
echo "NGINX_TARGET=$TARGET"
echo "NEXT=Gunakan production-check V6R2; jangan production-check V6 lama yang masih memakai HEAD untuk APK."
