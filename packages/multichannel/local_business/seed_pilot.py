"""Seed data PILOT untuk Local Business Suite (tenant LOCAL-PILOT).

Membuat data terkendali yang jelas berlabel PILOT untuk penerimaan:
  Tenant LOCAL-PILOT
  Warehouse MAIN, Branch A (RETAIL), Branch B (RESTAURANT)
  Master SKU: WATER-600, EGG, RICE, CHICKEN, OIL
  Menu NASI_GORENG dengan resep ingredient
  Register + kasir + shift

Semua data ber-origin PILOT dan tidak tercampur ke tenant produksi.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/opt")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from botconnector_multichannel.persistence import db  # noqa
from botconnector_multichannel.inventory import migrate as imigrate  # noqa
from botconnector_multichannel.inventory import service as S  # noqa
from botconnector_multichannel.local_business import migrate as lmigrate  # noqa
from botconnector_multichannel.local_business import (  # noqa
    core, inventory as inv, restaurant, procurement,
)

TENANT = "LOCAL-PILOT"


def _wh(code, name):
    db.jalankan(
        "INSERT INTO multichannel.warehouse (code,name) VALUES (%s,%s) ON CONFLICT (code) DO NOTHING",
        (code, name))
    return db.ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (code,))["id"]


def _sku(sku, name, cat):
    p = S.upsert_product(name, cat, "")
    return S.upsert_master_sku(sku, product_id=p["id"])


def main():
    imigrate.migrasi()
    lmigrate.migrasi()

    biz = core.upsert_business(tenant_id=TENANT, code="PILOT", name="Pilot Bisnis",
                               business_type="HYBRID")
    wh_main = _wh("WH-MAIN", "Gudang Utama")
    wh_a = _wh("WH-A", "Cabang A")
    wh_b = _wh("WH-B", "Cabang B")
    br_a = core.upsert_branch(business_id=biz["id"], code="A", name="Cabang A (RETAIL)",
                              warehouse_id=wh_a, branch_type="RETAIL")
    br_b = core.upsert_branch(business_id=biz["id"], code="B", name="Cabang B (RESTAURANT)",
                              warehouse_id=wh_b, branch_type="RESTAURANT")
    reg_a = core.upsert_register(branch_id=br_a["id"], code="REG-A", name="Kasir A",
                                 device_id="DEV-PILOT-A")
    reg_b = core.upsert_register(branch_id=br_b["id"], code="REG-B", name="Kasir B",
                                 device_id="DEV-PILOT-B")
    core.upsert_cashier(business_id=biz["id"], code="OWNER", name="Pemilik", role="OWNER")
    core.upsert_cashier(business_id=biz["id"], code="MGR", name="Manajer", role="MANAGER")
    core.upsert_cashier(business_id=biz["id"], code="CSH", name="Kasir", role="CASHIER")
    core.upsert_cashier(business_id=biz["id"], code="KIT", name="Dapur", role="KITCHEN")

    # master SKU
    water = _sku("WATER-600", "Air Mineral 600ml", "Minuman")
    egg = _sku("EGG", "Telur", "Bahan")
    rice = _sku("RICE", "Beras", "Bahan")
    chicken = _sku("CHICKEN", "Ayam", "Bahan")
    oil = _sku("OIL", "Minyak Goreng", "Bahan")

    # receive stock
    inv.receive_stock(tenant_id=TENANT, business_id=biz["id"], branch_id=br_a["id"],
                      warehouse_id=wh_a, master_sku_id=water["id"], sku="WATER-600",
                      quantity=50, idempotency_key="pilot:gr:water", source_document="PILOT-GR-1")
    for sku_id, sku, qty in [(egg["id"], "EGG", 100), (rice["id"], "RICE", 20000),
                             (chicken["id"], "CHICKEN", 10000), (oil["id"], "OIL", 10000)]:
        inv.receive_stock(tenant_id=TENANT, business_id=biz["id"], branch_id=br_b["id"],
                          warehouse_id=wh_b, master_sku_id=sku_id, sku=sku, quantity=qty,
                          idempotency_key=f"pilot:gr:{sku}", source_document="PILOT-GR-2")

    # restaurant menu + recipe
    cat = restaurant.upsert_menu_category(business_id=biz["id"], name="Makanan", sort_order=1)
    nasi = restaurant.upsert_menu_item(business_id=biz["id"], name="NASI_GORENG", price=15000,
                                       category_id=cat["id"])
    restaurant.upsert_recipe(menu_item_id=nasi["id"], version=1, components=[
        {"master_sku_id": rice["id"], "sku": "RICE", "quantity": 200},
        {"master_sku_id": egg["id"], "sku": "EGG", "quantity": 1},
        {"master_sku_id": chicken["id"], "sku": "CHICKEN", "quantity": 50},
        {"master_sku_id": oil["id"], "sku": "OIL", "quantity": 15},
    ])
    restaurant.upsert_table(branch_id=br_b["id"], name="Meja 1", capacity=4)
    restaurant.upsert_table(branch_id=br_b["id"], name="Meja 2", capacity=2)

    print(f"PILOT SEED OK — business={biz['id']} branches A={br_a['id']} B={br_b['id']}")
    print(f"  WATER-600 at A: {inv.location_atp(water['id'], wh_a)}")
    print(f"  NASI_GORENG producible at B: {restaurant.producible_quantity(nasi['id'], wh_b)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
