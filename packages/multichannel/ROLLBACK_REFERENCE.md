# ROLLBACK REFERENCE — BotConnector Multichannel (lapisan baru)

Tanggal: 2026-08-21
Pengarang: opencode (deepseek-v4-flash)

## Yang dibangun (baru, di ATAS foundation beku)

Tidak ada foundation yang dipatch. SHA foundation UTUH:
- Business Core: a6fc9df8147db86c93ecb4733e2a1319e758326d09d35dddf948a674f9efd13a
- Shopee offline provider: 531b670d047f4ca731daad6ef16b693177757b990a9654f336682d511f969056

## File baru

```
/opt/botconnector-multichannel/persistence/{__init__,runtime,db,repo}.py
/opt/botconnector-multichannel/persistence/schema.sql
/opt/botconnector-multichannel/shop/{__init__,signing,transport,client}.py
/opt/botconnector-multichannel/workflow/{__init__,shop_binding,finance_core,order_posting,settlement}.py
/opt/botconnector-multichannel/api/{__init__,integration}.py
/opt/botconnector-multichannel/server/integrasi.py
/opt/botconnector-multichannel/pilot/{pipeline,acceptance}.py
```

## Service baru

```
botconnector-integrasi.service  (127.0.0.1:18198, uvicorn)
```

## Basis data

- Schema `multichannel` di basis data `botconnector` (kontainer
  `botconnector-core-postgres`). Dapat dijatuhkan utuh:
  `DROP SCHEMA multichannel CASCADE;`
- Finance Core TIDAK diubah strukturnya; hanya bertambah data kanonik
  (invoice PILOT, settlement STL-9001) yang seimbang.

## Rollback

### 1. Hapus service + nginx proxy
```bash
sudo systemctl stop botconnector-integrasi.service
sudo systemctl disable botconnector-integrasi.service
sudo rm /etc/systemd/system/botconnector-integrasi.service
sudo systemctl daemon-reload
# kembalikan nginx dari cadangan
sudo cp /etc/nginx/botconnector-cutover.conf.bak-integrasi-20260821221826 \
        /etc/nginx/sites-enabled/botconnector-cutover.conf
sudo nginx -t && sudo systemctl reload nginx
```

### 2. Hapus schema + file
```bash
sudo docker exec botconnector-core-postgres psql -U botconnector_app -d botconnector \
  -c "DROP SCHEMA multichannel CASCADE;"
sudo rm -rf /opt/botconnector-multichannel/persistence \
            /opt/botconnector-multichannel/shop \
            /opt/botconnector-multichannel/workflow \
            /opt/botconnector-multichannel/api \
            /opt/botconnector-multichannel/server \
            /opt/botconnector-multichannel/pilot
```

### 3. Data Finance kanon (opsional, biarkan seimbang)

Pilot menghasilkan invoice `SP-sho-PLT-1001` (journal POSTED) dan
settlement `STL-9001` (cash receipt RCPT-STL-9001). Keduanya seimbang dan
merupakan bukti kanari; bila ingin dihapus, balikkan lewat
`finance_reverse_journal` lalu hapus baris.

## Konsistensi

Trial balance Finance Core: balanced=True, difference=0.00 (diverifikasi).

## KOREKSI INTEGRITAS FINAL (2026-08-21, sesi lanjutan)

1. Semantik binding Shopee dikoreksi: `multichannel.shop.binding_origin`
   = 'REAL' (dari OAuth+identitas toko nyata) atau 'PILOT' (sintetik/uji
   internal). Keadaan antarmuka produksi hanya menampilkan 'Terhubung'
   untuk binding REAL. PILOT-SHOP-001 adalah PILOT, tidak pernah tampil
   sebagai Shopee asli terhubung.
2. Frontend /integrasi selalu 'Belum terhubung' tanpa binding REAL.
3. 8 tabel Codex (connections, journals, journal_lines, oauth_requests,
   postings, stock_buffers, stock_movements, schema_versions) dibiarkan
   utuh; runtime memakai nama skema multichannel.* penuh, tak ada risiko
   resolusi search_path. Provenance: schema_versions R10C1/R10D-R1.
4. Restore drill dibuktikan ke DB sekali pakai `botconnector_restore_drill`
   (skema + baris + kendala/idempotensi) lalu dibuang.

Rollback tambahan: untuk menghapus kolom binding_origin:
  ALTER TABLE multichannel.shop DROP COLUMN IF EXISTS binding_origin;
