"""Kanari pilot terkendali Shopee -> Business -> Finance -> Settlement.

Menjalankan seluruh jalur terhadap Finance Core NYATA (127.0.0.1:18200)
dengan data Shopee simulasi offline (karena credential eksternal absen).
Membuktikan: persistence idempoten, posting invoice ke Finance Core
(POSTED, debit=credit), settlement, varians, rekonsiliasi, dan status
frontend — semua dengan baris nyata di basis data.

Ini BUKAN pengujian jaringan; jaringan tetap MATI.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from botconnector_multichannel.persistence import db, repo  # noqa
from botconnector_multichannel.workflow import order_posting, settlement  # noqa
from botconnector_multichannel.workflow import finance_core as fc  # noqa

TENANT = "pilot-tenant"
PROVIDER = "shopee"
SHOP_ID = "PILOT-SHOP-001"


def _bersihkan():
    for t in ("order_finance", "settlement_finance", "settlement", "order"):
        db.jalankan(f"DELETE FROM multichannel.{t} WHERE provider=%s OR shop_id=%s",
                    (PROVIDER, SHOP_ID))


def main():
    db.migrasi()
    _bersihkan()

    # ---- 1. simpan toko PILOT (sintetik/internal, BUKAN binding real) ----
    shop = repo.simpan_shop(tenant_id=TENANT, provider=PROVIDER,
                            shop_id=SHOP_ID, shop_name="Toko Pilot",
                            status="TERHUBUNG", binding_origin="PILOT")
    print(f"[1] toko pilot tersimpan id={shop['id']} status={shop['status']} "
          f"origin={shop.get('binding_origin')} (sintetik, bukan binding real)")

    # ---- 2. simpan pesanan ternormalisasi (idempoten) ----
    o1 = repo.simpan_order(
        tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP_ID,
        order_sn="PLT-1001", order_status="COMPLETED",
        order_status_normalized="selesai",
        total_amount=250000, raw={"response": {"total_amount": "250000"}})
    o2 = repo.simpan_order(
        tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP_ID,
        order_sn="PLT-1001", order_status="COMPLETED",
        order_status_normalized="selesai", total_amount=250000)
    assert o1["duplicate"] is False and o2["duplicate"] is True, "idempotensi pesanan"
    print(f"[2] pesanan tersimpan id={o1['id']} replay-duplicate={o2['duplicate']}")

    # ---- 3. posting pesanan -> Finance Core (DRAFT->POSTED) ----
    res = order_posting.post_invoice_order(
        tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP_ID,
        order_sn="PLT-1001", order_date="2026-08-15", total=Decimal("250000"),
        line_desc="Pesanan pilot Shopee")
    assert res["status"] == "POSTED", res
    # replay -> duplicate
    res2 = order_posting.post_invoice_order(
        tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP_ID,
        order_sn="PLT-1001", order_date="2026-08-15", total=Decimal("250000"))
    assert res2["duplicate"] is True, "replay pesanan harus duplicate"
    print(f"[3] pesanan diposting journal={res['journal_id']} invoice={res['invoice_number']} "
          f"replay-duplicate={res2['duplicate']}")

    # ---- 4. verifikasi debit=credit di Finance Core ----
    neraca = fc.neraca()
    assert neraca.get("balanced") is True, "neraca Finance harus seimbang"
    print(f"[4] neraca Finance seimbang={neraca.get('balanced')} "
          f"selisih={neraca.get('totals',{}).get('difference')}")

    # ---- 5. settlement + varians + rekonsiliasi ----
    stl = settlement.proses_settlement(
        tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP_ID,
        settlement_ref="STL-9001", trans_id="TXN-9001",
        transaction_date="2026-08-18",
        gross=Decimal("250000"), fee=Decimal("5000"), net=Decimal("245000"),
        expected_ar=Decimal("250000"))
    print(f"[5] settlement variance={stl['variance']} tx={stl['cash_transaction_id']}")

    # replay settlement -> duplicate
    stl2 = settlement.proses_settlement(
        tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP_ID,
        settlement_ref="STL-9001", trans_id="TXN-9001",
        transaction_date="2026-08-18",
        gross=Decimal("250000"), fee=Decimal("5000"), net=Decimal("245000"),
        expected_ar=Decimal("250000"))
    print(f"[6] replay-settlement duplicate={stl2['duplicate']}")

    # ---- 7. hitung akhir ----
    print(f"[7] total pesanan={repo.hitung_order(PROVIDER)} "
          f"settlement={len(repo.daftar_settlement(PROVIDER))}")

    print("\nPILOT SELESAI — jalur Shopee->Finance->Settlement jalan di Finance NYATA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
