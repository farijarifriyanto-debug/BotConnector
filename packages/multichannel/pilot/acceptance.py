"""Gerbang penerimaan lapisan persistence & workflow (baru).

Menguji dengan basis data NYATA:
  - migrasi schema multichannel
  - idempotensi pesanan & toko
  - posting pesanan -> Finance Core (POSTED, debit=credit)
  - replay pesanan -> duplicate
  - settlement + varians + rekonsiliasi
  - API integrasi (read-only)

Membersihkan data uji sesudahnya (hanya baris yang dibuat tes ini).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "/opt")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from botconnector_multichannel.persistence import db, repo  # noqa
from botconnector_multichannel.workflow import order_posting, settlement  # noqa
from botconnector_multichannel.workflow import finance_core as fc  # noqa

lulus, gagal = 0, 0
TENANT = "acceptance-tenant"
PROVIDER = "shopee"
SHOP = "ACCEPT-SHOP"
ORDER_SN = "ACCEPT-ORDER-001"
STL_REF = "ACCEPT-STL-001"


def uji(nama, fn):
    global lulus, gagal
    try:
        fn()
        print(f"  [OK]    {nama}")
        lulus += 1
    except AssertionError as e:
        print(f"  [GAGAL] {nama}: {e}")
        gagal += 1
    except Exception as e:
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


def _bersihkan():
    for t in ("order_finance", "settlement_finance", "settlement", "order"):
        db.jalankan(f"DELETE FROM multichannel.{t} WHERE shop_id=%s", (SHOP,))
    db.jalankan("DELETE FROM multichannel.shop WHERE shop_id=%s", (SHOP,))
    # sejajarkan urutan (bigserial) setelah penghapusan
    db.jalankan(
        "SELECT setval(pg_get_serial_sequence('multichannel.order','id'), "
        "COALESCE((SELECT MAX(id) FROM multichannel.order),1), true);")
    db.jalankan(
        "SELECT setval(pg_get_serial_sequence('multichannel.audit_log','id'), "
        "COALESCE((SELECT MAX(id) FROM multichannel.audit_log),1), true);")


def _persist_migrasi():
    db.migrasi()
    assert db.tabel_ada("shop"), "schema shop belum ada"


def _test_shop_idempoten():
    s1 = repo.simpan_shop(tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP,
                          status="TERHUBUNG")
    s2 = repo.simpan_shop(tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP)
    assert s1["id"] == s2["id"], "shop tidak idempoten"


def _test_order_idempoten():
    repo.simpan_order(tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP,
                      order_sn=ORDER_SN, order_status="COMPLETED",
                      order_status_normalized="selesai", total_amount=100000)
    o2 = repo.simpan_order(tenant_id=TENANT, provider=PROVIDER, shop_id=SHOP,
                           order_sn=ORDER_SN, order_status="COMPLETED",
                           order_status_normalized="selesai", total_amount=100000)
    assert o2["duplicate"] is True, "order replay harus duplicate"


def _test_audit():
    n_before = len(repo.baca_audit())
    repo.catat_audit("uji_tes", tenant_id=TENANT, provider=PROVIDER,
                     shop_id=SHOP, payload={"x": 1})
    assert len(repo.baca_audit()) > n_before, "audit tidak tercatat"


def _test_finance_posting_balanced():
    # Gunakan pesanan pilot yang SUDAH ada (idempoten, tidak menambah
    # baris Finance baru). Mengecek kanonik: pesanan PLT-1001 sudah POSTED.
    res = order_posting.post_invoice_order(
        tenant_id="pilot-tenant", provider="shopee", shop_id="PILOT-SHOP-001",
        order_sn="PLT-1001", order_date="2026-08-15", total=Decimal("250000"))
    assert res["status"] == "POSTED", res
    assert res["journal_id"], "tidak ada journal id"


def _test_finance_replay():
    res = order_posting.post_invoice_order(
        tenant_id="pilot-tenant", provider="shopee", shop_id="PILOT-SHOP-001",
        order_sn="PLT-1001", order_date="2026-08-15", total=Decimal("250000"))
    assert res["duplicate"] is True, "replay harus duplicate"


def _test_neraca():
    n = fc.neraca()
    assert n.get("balanced") is True, "neraca Finance tidak seimbang"


def _test_settlement():
    r = settlement.proses_settlement(
        tenant_id="pilot-tenant", provider="shopee", shop_id="PILOT-SHOP-001",
        settlement_ref="STL-9001", trans_id="TXN-9001",
        transaction_date="2026-08-18",
        gross=Decimal("250000"), fee=Decimal("5000"),
        net=Decimal("245000"), expected_ar=Decimal("250000"))
    assert r["variance"] == Decimal("5000"), r["variance"]
    r2 = settlement.proses_settlement(
        tenant_id="pilot-tenant", provider="shopee", shop_id="PILOT-SHOP-001",
        settlement_ref="STL-9001", trans_id="TXN-9001",
        transaction_date="2026-08-18",
        gross=Decimal("250000"), fee=Decimal("5000"),
        net=Decimal("245000"), expected_ar=Decimal("250000"))
    assert r2["duplicate"] is True, "replay settlement harus duplicate"


def _test_api_state():
    from fastapi.testclient import TestClient
    from botconnector_multichannel.api.integration import APP
    c = TestClient(APP)
    r = c.get("/api/integrasi/state")
    assert r.status_code == 200 and r.json()["ok"], "state gagal"


def main():
    db.migrasi()
    _bersihkan()
    print("\n=== PERSISTENCE & WORKFLOW (baru) ===")
    uji("migrasi schema multichannel", _persist_migrasi)
    uji("shop idempoten", _test_shop_idempoten)
    uji("order idempoten", _test_order_idempoten)
    uji("audit tercatat", _test_audit)
    uji("posting pesanan -> Finance POSTED", _test_finance_posting_balanced)
    uji("replay pesanan -> duplicate", _test_finance_replay)
    uji("neraca Finance seimbang", _test_neraca)
    uji("settlement + varians", _test_settlement)
    uji("API state integrasi", _test_api_state)
    _bersihkan()
    print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
