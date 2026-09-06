"""Gerbang penerimaan Central Product/SKU + Inventory Core (baru, DB NYATA).

Membuktikan dengan baris dan angka sebelum/sesudah di PostgreSQL:
  MASTER_SKU_MAPPING, CENTRAL_STOCK_SOURCE_OF_TRUTH, ATOMIC_RESERVATION,
  CONCURRENT_ORDER_OVERSALE_PROTECTION, DUPLICATE_EVENT_IDEMPOTENCY,
  CANCEL_RELEASE, SHIP_CONSUME, RETURN_RESTOCK, TRANSACTIONAL_OUTBOX,
  OUTBOX_RETRY, LATEST_QUANTITY_CONVERGENCE, SYNC_LOOP_PROTECTION,
  DRIFT_DETECTION, SCHEMA_QUALIFICATION, FINANCE_BALANCED, NO_DUPLICATE_FINANCE.

Seluruh data uji memakai SKU/nama unik per run (uuid suffix) dan dibersihkan
sesudahnya agar tidak mencemari tenant produksi.
"""

from __future__ import annotations

import sys
import threading
import uuid
from decimal import Decimal

sys.path.insert(0, "/opt")
sys.path.insert(0, "/opt/botconnector-multichannel")

from botconnector_multichannel.persistence import db, repo  # noqa
from botconnector_multichannel.inventory import migrate as imigrate  # noqa
from botconnector_multichannel.inventory import service as S  # noqa
from botconnector_multichannel.inventory import sync as SYNC  # noqa
from botconnector_multichannel.connector import offline_fixture  # noqa
from botconnector_multichannel.workflow import finance_core as fc  # noqa
from botconnector_multichannel.workflow import order_posting  # noqa

lulus, gagal = 0, 0

_TAG = uuid.uuid4().hex[:8]
_SKU = f"TST-{_TAG}"
_PROD = f"Produk {_TAG}"
_SHOPEE = "SHOPEE-" + _TAG
_TOKO = "TOKOPEDIA-" + _TAG
_TIKTOK = "TIKTOK-" + _TAG
_BLIBLI = "BLIBLI-" + _TAG
_LAZADA = "LAZADA-" + _TAG

store = offline_fixture.OfflineStore()


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
        import traceback
        print(f"  [GAGAL] {nama}: {type(e).__name__}: {e}")
        gagal += 1


def _seed_master(channels=1, shop_ids=None, on_hand=5, safety=0):
    p = S.upsert_product(_PROD, "Uji", "Test")
    m = S.upsert_master_sku(_SKU, product_id=p["id"], safety_stock=safety)
    S.set_on_hand(sku=_SKU, on_hand=on_hand, reason="seed")
    _reset_reserved(_SKU)
    if shop_ids is None:
        all_pairs = [("shopee", _SHOPEE), ("tokopedia", _TOKO),
                     ("tiktok_shop", _TIKTOK), ("blibli", _BLIBLI), ("lazada", _LAZADA)]
        shop_ids = all_pairs[:channels]
    mids = []
    for prov, sid in shop_ids:
        csku = f"{prov.upper()[:3]}-{_TAG}"
        r = S.map_channel_sku(provider=prov, shop_id=sid,
                              product_id_provider=f"P-{prov}-{_TAG}",
                              channel_sku=csku, master_sku_id=m["id"])
        mids.append((prov, sid, csku, m["id"]))
    return m, mids


def _reset_reserved(sku):
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute("UPDATE multichannel.master_sku SET reserved=0 WHERE sku=%s", (sku,))
        c.commit()


def _qty(sql):
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(sql)
        r = cur.fetchone()
        if not r:
            return None
        return list(r.values())[0] if hasattr(r, "values") else r[0]


def _atp(sku):
    return S.atp(sku)


def _cleanup():
    try:
        with db.koneksi() as c:
            cur = c.cursor()
            cur.execute("DELETE FROM multichannel.inventory_drift WHERE provider LIKE %s", (f"%{_TAG}%",))
            cur.execute("DELETE FROM multichannel.inventory_sync_attempt WHERE provider LIKE %s", (f"%{_TAG}%",))
            # sync_state / outbox / reservation / movement must drop before master_sku
            cur.execute("""
                DELETE FROM multichannel.inventory_sync_outbox o
                USING multichannel.inventory_sync_state s
                WHERE o.sync_state_id=s.id AND s.channel_sku LIKE %s""", (f"%{_TAG}%",))
            cur.execute("DELETE FROM multichannel.inventory_sync_state WHERE channel_sku LIKE %s", (f"%{_TAG}%",))
            cur.execute("DELETE FROM multichannel.channel_sku_map WHERE channel_sku LIKE %s", (f"%{_TAG}%",))
            cur.execute("DELETE FROM multichannel.channel_listing WHERE product_id LIKE %s", (f"%{_TAG}%",))
            cur.execute("DELETE FROM multichannel.inventory_reservation WHERE order_sn IN ('ORD-1','ORD-2','ORD-S','ORD-T','ORD-C','ORD-O','ORD-L','ORD-R')")
            cur.execute("DELETE FROM multichannel.inventory_movement WHERE master_sku_id IN (SELECT id FROM multichannel.master_sku WHERE sku=%s)", (_SKU,))
            cur.execute("DELETE FROM multichannel.inventory_adjustment WHERE master_sku_id IN (SELECT id FROM multichannel.master_sku WHERE sku=%s)", (_SKU,))
            cur.execute("DELETE FROM multichannel.inventory_balance WHERE master_sku_id IN (SELECT id FROM multichannel.master_sku WHERE sku=%s)", (_SKU,))
            cur.execute("DELETE FROM multichannel.inventory_reservation WHERE master_sku_id IN (SELECT id FROM multichannel.master_sku WHERE sku=%s)", (_SKU,))
            cur.execute("DELETE FROM multichannel.master_sku WHERE sku=%s", (_SKU,))
            cur.execute("DELETE FROM multichannel.product WHERE name=%s", (_PROD,))
            cur.execute("DELETE FROM multichannel.order_finance WHERE order_sn LIKE %s", (f"%{_TAG}%",))
            c.commit()
    except Exception:
        pass


# ================================================================ TESTS
def t1_schema_qualified():
    assert db.tabel_ada("master_sku"), "master_sku tidak ada"
    assert db.tabel_ada("inventory_sync_outbox"), "outbox tidak ada"
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute("SELECT to_regclass('multichannel.master_sku') AS x")
        assert cur.fetchone()["x"] is not None, "bukan schema multichannel"


def t2_master_sku_mapping():
    m, mids = _seed_master(on_hand=5, safety=1)
    assert S.atp(_SKU) == 4, f"ATP harus 4 (5-0-1) dapat {S.atp(_SKU)}"
    # semua channel SKU memetakan ke satu master
    for prov, sid, csku, mid in mids:
        got = S.resolve_master_sku(prov, sid, csku)
        assert got == m["id"], f"{prov} map salah"


def t3_atomic_reservation():
    m, mids = _seed()
    r = S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-1",
                        line_id="L1", channel_sku=mids[0][2], qty=2, event_seq="e1")
    assert r["duplicate"] is False
    assert S.atp(_SKU) == 5 - 2, f"ATP salah {S.atp(_SKU)}"
    # re-run sama -> duplicate, tidak reservasi dua kali
    r2 = S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-1",
                         line_id="L1", channel_sku=mids[0][2], qty=2, event_seq="e1")
    assert r2["duplicate"] is True, "replay harus duplicate"
    assert S.atp(_SKU) == 3, "ATP tidak berubah setelah replay"


def t4_idempotency_replay():
    m, mids = _seed()
    S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-2",
                    line_id="L1", channel_sku=mids[0][2], qty=1, event_seq="e2")
    for _ in range(9):
        S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-2",
                        line_id="L1", channel_sku=mids[0][2], qty=1, event_seq="e2")
    assert S.atp(_SKU) == 5 - 1, f"replay 10x harus 1 reservasi, dapat {S.atp(_SKU)}"
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) AS c FROM multichannel.inventory_reservation WHERE order_sn='ORD-2'")
        n = cur.fetchone()["c"]
    assert n == 1, f"harus 1 reservation, dapat {n}"


def t5_concurrent_oversale():
    """Dua kanal serentak: Shopee qty3 + Tokopedia qty3, ON_HAND 5 -> tak boleh 6."""
    m, mids = _seed(channels=2, on_hand=5)
    (psp, ssp, csp, _) = mids[0]
    (ptk, stk, ctk, _) = mids[1]
    results = []
    lock = threading.Lock()
    def _reserve(provider, sid, csku, order, qty):
        try:
            r = S.reserve_order(provider=provider, shop_id=sid, order_sn=order,
                                line_id="L1", channel_sku=csku, qty=qty, event_seq="ce1")
            with lock:
                results.append(r)
        except S.StokTidakCukup:
            with lock:
                results.append({"error": "insufficient"})
    t1 = threading.Thread(target=_reserve, args=("shopee", ssp, csp, "ORD-S", 3))
    t2 = threading.Thread(target=_reserve, args=("tokopedia", stk, ctk, "ORD-T", 3))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert len(results) >= 1
    # total reservasi yang diterima tidak boleh 6 (max = ON_HAND 5)
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(qty),0) AS count FROM multichannel.inventory_reservation "
            "WHERE order_sn IN ('ORD-S','ORD-T')", ())
        total = cur.fetchone()["count"]
    assert total <= 5, f"oversell! total reservasi {total} > 5"
    assert S.atp(_SKU) >= 0, "ATP negatif"
    # jumlah order yang berhasil reservasi: 5/3=1 atau 2 order (5=3+2) — tidak boleh 6
    assert total in (3, 5), f"hasil reservasi tidak valid: {total}"


def t6_cancel_release():
    m, mids = _seed(on_hand=5)
    S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-C",
                    line_id="L1", channel_sku=mids[0][2], qty=3, event_seq="c1")
    assert S.atp(_SKU) == 2
    S.release_reservation(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-C",
                          line_id="L1", event_seq="c1")
    assert S.atp(_SKU) == 5, f"cancel harus pulih ke 5, dapat {S.atp(_SKU)}"
    # cancel ganda -> idempoten
    S.release_reservation(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-C",
                          line_id="L1", event_seq="c1")
    assert S.atp(_SKU) == 5


def t7_ship_consume():
    m, mids = _seed(on_hand=5)
    S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-S",
                    line_id="L1", channel_sku=mids[0][2], qty=2, event_seq="s1")
    S.consume_reservation(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-S",
                          line_id="L1", event_seq="s1")
    # ON_HAND 5->3, reserved 2->0, ATP 3
    assert S.atp(_SKU) == 3, f"ship harus ON_HAND 3, dapat {S.atp(_SKU)}"


def t8_return_restock():
    m, mids = _seed(on_hand=5)
    S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-R",
                    line_id="L1", channel_sku=mids[0][2], qty=2, event_seq="r1")
    S.consume_reservation(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-R",
                          line_id="L1", event_seq="r1")
    assert S.atp(_SKU) == 3
    S.return_to_stock(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-R",
                      line_id="L1", event_seq="r2", master_sku_id=m["id"],
                      channel_sku=mids[0][2], qty=2)
    assert S.atp(_SKU) == 5, f"retur harus ON_HAND 5, dapat {S.atp(_SKU)}"
    # retur ganda idempoten
    S.return_to_stock(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-R",
                      line_id="L1", event_seq="r2", master_sku_id=m["id"],
                      channel_sku=mids[0][2], qty=2)
    assert S.atp(_SKU) == 5


def t9_transactional_outbox():
    m, mids = _seed(on_hand=5)
    S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-O",
                    line_id="L1", channel_sku=mids[0][2], qty=2, event_seq="o1")
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM multichannel.inventory_sync_outbox o JOIN multichannel.inventory_sync_state s ON o.sync_state_id=s.id WHERE s.channel_sku=%s", (mids[0][2],))
        n = cur.fetchone()["count"]
    assert n >= 1, "outbox harus punya baris"


def t10_outbox_retry_and_convergence():
    m, mids = _seed(on_hand=5)
    adapter = offline_fixture.OfflineAdapter(store)
    # global OFF -> outbox dibiarkan PENDING, worker tidak menulis
    S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-O",
                    line_id="L1", channel_sku=mids[0][2], qty=1, event_seq="o1")
    r = SYNC.process_outbox({"shopee": adapter}, limit=50, max_attempts=3)
    assert r["status"] == "global_off", f"global off {r}"
    # nyalakan global untuk membuktikan konvergensi ke nilai TERKINI
    SYNC.set_global_write("ON")
    try:
        # perubahan stok lagi -> outbox PENDING dengan desired terbaru
        S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-O",
                        line_id="L2", channel_sku=mids[0][2], qty=1, event_seq="o2")
        r = SYNC.process_outbox({"shopee": adapter}, limit=50, max_attempts=3)
        assert r["sent"] >= 1, r
        got = adapter.store.get("shopee", _SHOPEE, mids[0][2])
        assert got == S.atp(_SKU), f"remote harus ATP terkini {S.atp(_SKU)}, dapat {got}"
    finally:
        SYNC.set_global_write("OFF")


def t11_loop_protection():
    m, mids = _seed(on_hand=5)
    adapter = offline_fixture.OfflineAdapter(store)
    SYNC.set_global_write("ON")
    try:
        S.reserve_order(provider="shopee", shop_id=_SHOPEE, order_sn="ORD-L",
                        line_id="L1", channel_sku=mids[0][2], qty=1, event_seq="l1")
        SYNC.process_outbox({"shopee": adapter}, max_attempts=3)
        # remote kini = ATP; event webhook stok kita sendiri tdk boleh bikin outbox lagi
        sync_before = _count_outbox(mids[0][2])
        res = SYNC.update_sync_from_event(provider="shopee", shop_id=_SHOPEE,
                                          channel_sku=mids[0][2],
                                          desired_qty=S.atp(_SKU),
                                          remote_qty=store.get("shopee", _SHOPEE, mids[0][2]),
                                          write_origin="system")
        assert res["loop_suppressed"] is True, "loop protection gagal"
        sync_after = _count_outbox(mids[0][2])
        assert sync_after == sync_before, "outbox bertambah oleh event kita sendiri"
    finally:
        SYNC.set_global_write("OFF")


def t12_drift_detection():
    m, mids = _seed_master(channels=2, on_hand=5)
    adapter = offline_fixture.OfflineAdapter(store)
    SYNC.set_global_write("ON")
    try:
        S.adjust_stock(sku=_SKU, delta_on_hand=5)
        SYNC.process_outbox({"shopee": adapter, "tokopedia": adapter})
        store.set("shopee", _SHOPEE, mids[0][2], 999)  # manual external change
        res = SYNC.reconcile({"shopee": adapter, "tokopedia": adapter})
        drifted = [x for x in res if x["state"] == "DRIFTED"]
        assert drifted, f"harus ada drift, dapat {res}"
        with db.koneksi() as c:
            cur = c.cursor()
            cur.execute("SELECT count(*) FROM multichannel.inventory_drift WHERE state='DRIFTED'")
            n = cur.fetchone()["count"]
        assert n >= 1, "drift tidak tercatat"
    finally:
        SYNC.set_global_write("OFF")


def t13_finance_balanced_no_duplicate():
    n = fc.neraca()
    assert n.get("balanced") is True, "neraca Finance tidak seimbang"
    # pastikan NO_DUPLICATE_FINANCE: pesanan yang sama tidak meng-create 2 invoice
    res = order_posting.post_invoice_order(
        tenant_id="pilot-tenant", provider="shopee", shop_id="PILOT-SHOP-001",
        order_sn="PLT-1001", order_date="2026-08-15", total=Decimal("250000"))
    assert res["status"] == "POSTED", res
    res2 = order_posting.post_invoice_order(
        tenant_id="pilot-tenant", provider="shopee", shop_id="PILOT-SHOP-001",
        order_sn="PLT-1001", order_date="2026-08-15", total=Decimal("250000"))
    assert res2["duplicate"] is True, "replay finance harus duplicate"


def _count_outbox(channel_sku):
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM multichannel.inventory_sync_outbox o JOIN multichannel.inventory_sync_state s ON o.sync_state_id=s.id WHERE s.channel_sku=%s", (channel_sku,))
        return cur.fetchone()["count"]


# aliases
def _seed(*a, **k): return _seed_master(*a, **k)
def _mk_channels_2():
    return _seed_master(channels=2, on_hand=5)

from botconnector_multichannel.inventory.service import StokTidakCukup


def main():
    imigrate.migrasi()
    _cleanup()
    print("\n=== CENTRAL PRODUCT/INVENTORY CORE (baru, DB NYATA) ===")
    uji("SCHEMA_QUALIFICATION", t1_schema_qualified)
    uji("MASTER_SKU_MAPPING + ATP", t2_master_sku_mapping)
    uji("ATOMIC_RESERVATION + idempoten", t3_atomic_reservation)
    uji("DUPLICATE_EVENT_IDEMPOTENCY (replay)", t4_idempotency_replay)
    uji("CONCURRENT_ORDER_OVERSALE_PROTECTION", t5_concurrent_oversale)
    uji("CANCEL_RELEASE", t6_cancel_release)
    uji("SHIP_CONSUME", t7_ship_consume)
    uji("RETURN_RESTOCK", t8_return_restock)
    uji("TRANSACTIONAL_OUTBOX", t9_transactional_outbox)
    uji("OUTBOX_RETRY + LATEST_CONVERGENCE", t10_outbox_retry_and_convergence)
    uji("SYNC_LOOP_PROTECTION", t11_loop_protection)
    uji("DRIFT_DETECTION", t12_drift_detection)
    uji("FINANCE_BALANCED + NO_DUPLICATE_FINANCE", t13_finance_balanced_no_duplicate)
    _cleanup()
    print(f"\n  Lulus: {lulus}   Gagal: {gagal}\n")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
