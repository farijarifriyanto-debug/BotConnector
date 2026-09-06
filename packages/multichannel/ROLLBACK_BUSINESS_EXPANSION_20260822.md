# ROLLBACK REFERENCE — Business Expansion (lapisan baru)

Tanggal: 2026-08-22
Pengarang: opencode (deepseek-v4-flash)

## Yang dibangun (baru, DI ATAS checkpoint Local Business Suite)

Foundation BEKU tidak diubah:
- Business Core SHA: a6fc9df8147db86c93ecb4733e2a1319e758326d09d35dddf948a674f9efd13a
- Shopee offline provider SHA: 531b670d047f4ca731daad6ef16b693177757b990a9654f336682d511f969056

Checkpoint lama (117 gerbang) TIDAK diubah strukturnya; hanya bertambah kolom
dan tabel baru.

## File baru

```
local_business/schema_expansion.sql   skema Business Expansion (17 tabel baru)
local_business/business_reporting.py  laporan bisnis (restaurant/retail/hybrid)
local_business/delivery.py            generic delivery order core + lineage + settlement
local_business/delivery_connector.py  base contract delivery connector
local_business/connectors/           GoFood, GrabFood, ShopeeFood adapters
local_business/pos_connector.py      base contract third-party POS
local_business/pos/                  Moka, Pawoon adapters
local_business/file_connector.py     Universal File Connector (CSV/XLSX)
local_business/watched_folder.py     watched-folder automation
local_business/barcode.py            barcode lookup + alias
local_business/print_receipt.py      receipt print (58/80mm)
local_business/device_bridge.py      digital scale / local device bridge
local_business/qr_self_order.py     QR menu / self-order + queue display
local_business/webhook_connector.py  generic webhook/REST (no SSRF)
local_business/acceptance_expansion.py  19 gerbang penerimaan (DB NYATA)
```

## Perubahan pada skema local_business (existing tables)

- `menu_item`: + reporting_category
- `restaurant_order`: + sales_channel, source_provider, external_order_id,
  service_charge, provider_fee, merchant_promo_cost, platform_promo,
  local_discount, other_adjustment, payment_state, expected_settlement,
  actual_settlement, settlement_variance, scheduled_at, provider_status,
  raw_payload
- `restaurant_order_line`: + channel_item_id, modifier_json
- `sale`: + sales_channel, source_provider, external_order_id, service_charge,
  provider_fee, merchant_promo_cost, platform_promo, local_discount,
  other_adjustment, payment_state, expected_settlement, actual_settlement,
  settlement_variance
- `sale_line`: + reporting_category, cost

## Website (baru, di atas visual identity existing)

```
/var/www/botconnector-business-suite/current/index.html   /business-suite/
/var/www/botconnector-restaurant/current/index.html       /restaurant/
/var/www/botconnector-retail/current/index.html           /retail/
/var/www/botconnector-integrations/current/index.html     /integrations/
/var/www/botconnector-automation-home/current/index.html  (diperbarui: nav + hero + footer)
/var/www/botconnector-automation-docs/current/index.html  (diperbarui: title + nav)
```

## Nginx

- Ditambah blok `BOTCONNECTOR_BUSINESS_EXPANSION_MARKETING_V1_BEGIN/END`
  untuk /business-suite/, /restaurant/, /retail/, /integrations/.
- Cadangan: /etc/nginx/botconnector-cutover.conf.bak-expansion-20260822T011139

## Rollback

### 1. Kembalikan nginx
```bash
sudo cp /etc/nginx/botconnector-cutover.conf.bak-expansion-20260822T011139 \
        /etc/nginx/sites-enabled/botconnector-cutover.conf
sudo nginx -t && sudo systemctl reload nginx
```

### 2. Kembalikan website
```bash
sudo rm -rf /var/www/botconnector-business-suite /var/www/botconnector-restaurant \
            /var/www/botconnector-retail /var/www/botconnector-integrations
sudo cp -r /var/www/botconnector-automation-home/current.bak-expansion-20260822T011139 \
           /var/www/botconnector-automation-home/current
```

### 3. Hapus tabel expansion (opsional, biarkan additif)
```bash
DROP TABLE IF EXISTS local_business.barcode_alias, device_bridge, queue_ticket,
  qr_menu, webhook_event, webhook_connector, watched_file, watched_folder,
  file_import, pos_connector, delivery_settlement, order_lineage,
  delivery_order_line, delivery_order, channel_menu_mapping, sales_channel,
  reporting_category CASCADE;
```

### 4. Hapus file
```bash
sudo rm -rf /opt/botconnector-multichannel/local_business/schema_expansion.sql \
  /opt/botconnector-multichannel/local_business/business_reporting.py \
  /opt/botconnector-multichannel/local_business/delivery.py \
  /opt/botconnector-multichannel/local_business/delivery_connector.py \
  /opt/botconnector-multichannel/local_business/connectors \
  /opt/botconnector-multichannel/local_business/pos_connector.py \
  /opt/botconnector-multichannel/local_business/pos \
  /opt/botconnector-multichannel/local_business/file_connector.py \
  /opt/botconnector-multichannel/local_business/watched_folder.py \
  /opt/botconnector-multichannel/local_business/barcode.py \
  /opt/botconnector-multichannel/local_business/print_receipt.py \
  /opt/botconnector-multichannel/local_business/device_bridge.py \
  /opt/botconnector-multichannel/local_business/qr_self_order.py \
  /opt/botconnector-multichannel/local_business/webhook_connector.py \
  /opt/botconnector-multichannel/local_business/acceptance_expansion.py
```

## Cadangan

```
/opt/botconnector-multichannel/backup/business-expansion-20260822T011139/
```

Restore drill dibuktikan ke DB sekali pakai `botconnector_restore_drill_exp`
(skema + baris + kendala/idempotensi) lalu dibuang.

## Konsistensi

- Trial balance Finance Core: balanced=True, difference=0.00 (diverifikasi).
- GLOBAL_MULTICHANNEL_STOCK_WRITE=OFF, REAL_MARKETPLACE_STOCK_WRITE=OFF,
  PAYMENT_CAPTURE=OFF.
- GOFOOD/GRABFOOD/SHOPEEFOOD_REAL=BLOCKED_EXTERNAL, MOKA/PAWOON_REAL=BLOCKED_EXTERNAL.
- Website publik TIDAK menampilkan label internal (BLOCKED_EXTERNAL, approval,
  credential absent); hanya TERSEDIA/BETA/SEGERA HADIR/ROADMAP.
