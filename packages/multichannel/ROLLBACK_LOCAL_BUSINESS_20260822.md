# ROLLBACK REFERENCE — Local Business Suite (lapisan baru)

Tanggal: 2026-08-22
Pengarang: opencode (deepseek-v4-flash)

## Yang dibangun (baru, DI ATAS foundation beku + checkpoint multichannel + inventory)

Foundation BEKU tidak diubah:
- Business Core SHA: a6fc9df8147db86c93ecb4733e2a1319e758326d09d35dddf948a674f9efd13a
- Shopee offline provider SHA: 531b670d047f4ca731daad6ef16b693177757b990a9654f336682d511f969056

Checkpoint lama (91 gerbang + skema multichannel + inventory 13 gerbang) TIDAK
diubah strukturnya; hanya bertambah kolom/constraint dan tabel baru.

## File baru

```
local_business/schema.sql        skema Local Business Suite (30 tabel + 6 sequence)
local_business/migrate.py        migrasi schema
local_business/core.py           business/branch/register/cashier/shift/customer/audit
local_business/inventory.py      operasi stok location-aware (reuse Central Inventory)
local_business/retail.py         Retail POS atomic sale + void
local_business/returns.py        return/refund workflow
local_business/transfer.py       multi-branch transfer lifecycle + konservasi
local_business/restaurant.py     menu/recipe/BOM/ingredient + order + KOT
local_business/offline.py        offline queue + allowance + idempotent sync
local_business/finance.py        integrasi Finance Core (reuse kontrak kanonik)
local_business/procurement.py    goods receipt / receiving
local_business/marketplace.py    proyeksi stok marketplace (write OFF)
local_business/reporting.py      multi-branch reporting + dashboard
local_business/acceptance.py     13 gerbang penerimaan (DB NYATA)
local_business/scenario.py       skenario 10 langkah + konservasi
local_business/seed_pilot.py     seed data PILOT (tenant LOCAL-PILOT)
server/bisnis.py                 server /bisnis/ (PWA offline-first)
```

## Perubahan pada skema multichannel (inventory core)

- `inventory_balance`: unique `(master_sku_id)` -> `(master_sku_id, warehouse_id)`,
  tambah kolom `in_transit`.
- `inventory_movement`: tambah kolom `warehouse_id, tenant_id, actor, device_id,
  source_document, idempotency_key`.

## Service baru

```
botconnector-bisnis.service  (127.0.0.1:18199, uvicorn)
```

## Basis data

- Schema `local_business` di basis data `botconnector` (kontainer
  `botconnector-core-postgres`). Dapat dijatuhkan utuh:
  `DROP SCHEMA local_business CASCADE;`
- Finance Core TIDAK diubah strukturnya; hanya bertambah data kanonik
  (invoice PILOT LB-SALE-*, LB-GR-*, COGS) yang seimbang.

## Rollback

### 1. Hapus service + nginx proxy
```bash
sudo systemctl stop botconnector-bisnis.service
sudo systemctl disable botconnector-bisnis.service
sudo rm /etc/systemd/system/botconnector-bisnis.service
sudo systemctl daemon-reload
# kembalikan nginx dari cadangan
sudo cp /etc/nginx/botconnector-cutover.conf.bak-bisnis-20260822T002307 \
        /etc/nginx/sites-enabled/botconnector-cutover.conf
sudo nginx -t && sudo systemctl reload nginx
```

### 2. Hapus schema + file
```bash
sudo docker exec botconnector-core-postgres psql -U botconnector_app -d botconnector \
  -c "DROP SCHEMA local_business CASCADE;"
sudo rm -rf /opt/botconnector-multichannel/local_business \
            /opt/botconnector-multichannel/server/bisnis.py \
            /opt/botconnector-bisnis
```

### 3. Kembalikan kolom inventory (opsional, biarkan)
Kolom baru di `inventory_balance.in_transit` dan `inventory_movement.*` bersifat
additif dan tidak mengganggu. Bila ingin dihapus:
```bash
ALTER TABLE multichannel.inventory_balance DROP COLUMN IF EXISTS in_transit;
ALTER TABLE multichannel.inventory_movement DROP COLUMN IF EXISTS warehouse_id,
  DROP COLUMN IF EXISTS tenant_id, DROP COLUMN IF EXISTS actor,
  DROP COLUMN IF EXISTS device_id, DROP COLUMN IF EXISTS source_document,
  DROP COLUMN IF EXISTS idempotency_key;
```

### 4. Data Finance kanon (opsional, biarkan seimbang)
Pilot menghasilkan invoice LB-SALE-*, LB-GR-*, COGS-* yang seimbang. Bila ingin
dihapus, balikkan lewat `finance_reverse_journal` lalu hapus baris.

## Cadangan

```
/opt/botconnector-multichannel/backup/local-business-20260821T235749/
/opt/botconnector-multichannel/backup/local-business-drill-20260822T004144/
```

Restore drill dibuktikan ke DB sekali pakai `botconnector_restore_drill_lb`
(skema + baris + kendala/idempotensi + finance linkage) lalu dibuang.

## Konsistensi

- Trial balance Finance Core: balanced=True, difference=0.00 (diverifikasi).
- GLOBAL_MULTICHANNEL_STOCK_WRITE=OFF, REAL_MARKETPLACE_STOCK_WRITE=OFF,
  PAYMENT_CAPTURE=OFF.
- Seluruh provider stock-write = BLOCKED_EXTERNAL / NOT_ACCEPTED.
