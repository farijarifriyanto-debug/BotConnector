# ROLLBACK REFERENCE — Central Product/SKU Master + Inventory Core (lapisan baru)

Tanggal: 2026-08-21
Pengarang: opencode (deepseek-v4-flash)

## Yang dibangun (baru, DI ATAS foundation beku + checkpoint multichannel)

Foundation BEKU tidak diubah:
- Business Core SHA: a6fc9df8147db86c93ecb4733e2a1319e758326d09d35dddf948a674f9efd13a
- Shopee offline provider SHA: 531b670d047f4ca731daad6ef16b693177757b990a9654f336682d511f969056

Checkpoint lama (91 gerbang + skema multichannel existing) TIDAK diubah
strukturnya; hanya bertambah tabel baru.

## File baru

connector/__init__.py                     kontrak konektor ternormalisasi
connector/{shopee,tiktok_tokopedia,blibli,lazada}.py   adapter provider (BLOCKED_EXTERNAL)
connector/registry.py                     daftar provider + status NYATA
connector/offline_fixture.py               adapter OFFLINE (uji runtime saja)
inventory/schema.sql                       skema Product/SKU Master + Inventory Core
inventory/{__init__,migrate,service,sync}.py
inventory/acceptance.py                    13 gerbang baru (DB NYATA)
server/integrasi.py                        (diperbarui: multi-provider + stok pusat)
api/integration.py                         (diperbarui: /inventory)

## Basis data
Tabel baru di schema multichannel database botconnector:
product, product_variant, master_sku, channel_listing, channel_sku_map,
warehouse, inventory_balance, inventory_reservation, inventory_movement,
inventory_adjustment, inventory_sync_state, inventory_sync_outbox,
inventory_sync_attempt, inventory_drift, inventory_config, provider_canary.

## Rollback (kembali ke checkpoint 91 gates)
DROP TABLE IF EXISTS multichannel.inventory_drift, inventory_sync_attempt,
inventory_sync_outbox, inventory_sync_state, inventory_adjustment,
inventory_movement, inventory_reservation, inventory_balance,
channel_sku_map, channel_listing, master_sku, product_variant, product,
warehouse, inventory_config, provider_canary CASCADE;
sudo rm -rf /opt/botconnector-multichannel/inventory /opt/botconnector-multichannel/connector

## Cadangan
/opt/botconnector-multichannel/backup/inventory-20260821T233300/
/opt/botconnector-multichannel/backup/inventory-20260821T235000/
Restore drill dibuktikan ke DB sekali pakai botconnector_restore_drill2 lalu dibuang.

## Konsistensi
- Finance Core: balanced=True (diverifikasi), tidak disentuh.
- GLOBAL_MULTICHANNEL_STOCK_WRITE=OFF, AUTO_STOCK_DRIFT_REPAIR=OFF.
- Seluruh provider stock-write = BLOCKED_EXTERNAL / NOT_ACCEPTED.
