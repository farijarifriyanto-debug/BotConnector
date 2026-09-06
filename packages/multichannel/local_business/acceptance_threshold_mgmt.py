"""Deterministic Acceptance Test Suite for Telegram Low-Stock Threshold Management V1.

Tests the complete lifecycle using disposable business & product fixtures:
A. /stokminimum with no config -> empty message ("Belum ada batas stok minimum yang diatur.")
B. valid SKU threshold -> preview, zero pre-confirm mutation
C. Confirm -> threshold created exactly once
D. duplicate Confirm -> no duplicate threshold (idempotent)
E. change threshold 3 -> 5 works through preview & confirm
F. "off" -> preview -> threshold removed
G. duplicate off confirm -> idempotent
H. negative/non-integer rejected with usage hint
I. unknown SKU rejected
J. wrong Telegram user cannot confirm
K. stale/expired callback cannot mutate
L. /stokrendah returns correct configured low-stock product
M. product above threshold not listed in /stokrendah
N. zero unexpected inventory mutation
O. zero Finance mutation
P. Low-Stock worker remains healthy
Q. Daily Summary remains untouched

Preserves all real production fixtures (TG-TEST-002, TG-CSV-001, TG-XLSX-001, TG-BC-001).
Cleans all disposable acceptance data afterward.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

sys.path.insert(0, "/opt")
sys.path.insert(0, "/opt/botconnector-multichannel")

from botconnector_multichannel.persistence import db
from botconnector_multichannel.inventory import service as S
from botconnector_multichannel.local_business import (
    core, inventory as inv, low_stock, bot_poller
)

TAG = uuid.uuid4().hex[:6]
TENANT = f"DISP-TM-TENANT-{TAG}"
BIZ_CODE = f"DISP-TM-BIZ-{TAG}"
SKU_1 = f"DISP-TM-SKU1-{TAG}"
SKU_2 = f"DISP-TM-SKU2-{TAG}"

passed, failed = 0, 0


def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  [OK]    {name}")
        passed += 1
    except AssertionError as e:
        import traceback
        traceback.print_exc()
        print(f"  [GAGAL] {name}: {e}")
        failed += 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  [GAGAL] {name}: {type(e).__name__}: {e}")
        failed += 1


class MockBotClient:
    def __init__(self):
        self.sent_messages = []
        self.callback_answers = []
        self.commands_set = []

    def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        msg_id = len(self.sent_messages) + 1000
        msg = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "message_id": msg_id,
        }
        self.sent_messages.append(msg)
        return {"message_id": msg_id}

    def answer_callback_query(self, callback_query_id: str, text: str = ""):
        self.callback_answers.append({"callback_query_id": callback_query_id, "text": text})
        return True

    def edit_message_reply_markup(self, chat_id: str, message_id: int, reply_markup=None):
        return True

    def set_my_commands(self, commands: list[dict]):
        self.commands_set = commands
        return True

    def get_my_commands(self):
        return self.commands_set


def setup_fixtures():
    wh_code = f"DISP-TM-WH-{TAG}"
    db.jalankan(
        "INSERT INTO multichannel.warehouse (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING",
        (wh_code, wh_code),
    )
    wh_row = db.ambil("SELECT id FROM multichannel.warehouse WHERE code=%s", (wh_code,))
    wh_id = wh_row["id"]

    biz = core.upsert_business(tenant_id=TENANT, code=BIZ_CODE, name=f"Disposable TM {TAG}", business_type="RETAIL")
    biz_id = biz["id"]

    br = core.upsert_branch(business_id=biz_id, code=f"DISP-TM-BR-{TAG}", name="Cabang TM", warehouse_id=wh_id, branch_type="RETAIL")
    branch_id = br["id"]

    tg_user_id = 9980001
    db.jalankan(
        "INSERT INTO local_business.telegram_account (owner_id, telegram_user_id) VALUES (%s, %s) ON CONFLICT (owner_id, telegram_user_id) DO NOTHING",
        (biz_id, tg_user_id),
    )

    # Product 1: Initial stock = 2
    prod1 = S.upsert_product(name=f"Produk Satu {TAG}", category="Test", brand="")
    master1 = S.upsert_master_sku(sku=SKU_1, product_id=prod1["id"])
    m_id1 = master1["id"]

    # Product 2: Initial stock = 10
    prod2 = S.upsert_product(name=f"Produk Dua {TAG}", category="Test", brand="")
    master2 = S.upsert_master_sku(sku=SKU_2, product_id=prod2["id"])
    m_id2 = master2["id"]

    inv.receive_stock(
        tenant_id=TENANT, business_id=biz_id, branch_id=branch_id,
        warehouse_id=wh_id, master_sku_id=m_id1, sku=SKU_1,
        quantity=2, reference="init1", source_document="INIT1",
        idempotency_key=f"init1-{TAG}",
    )
    inv.receive_stock(
        tenant_id=TENANT, business_id=biz_id, branch_id=branch_id,
        warehouse_id=wh_id, master_sku_id=m_id2, sku=SKU_2,
        quantity=10, reference="init2", source_document="INIT2",
        idempotency_key=f"init2-{TAG}",
    )

    return {
        "biz_id": biz_id,
        "wh_id": wh_id,
        "branch_id": branch_id,
        "m_id1": m_id1,
        "sku1": SKU_1,
        "m_id2": m_id2,
        "sku2": SKU_2,
        "tg_user_id": tg_user_id,
        "chat_id": 8880001,
    }


def cleanup_fixtures(f):
    biz_id = f["biz_id"]
    m_id1 = f["m_id1"]
    m_id2 = f["m_id2"]
    wh_id = f["wh_id"]
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute("DELETE FROM local_business.telegram_threshold_draft WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.low_stock_threshold WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.low_stock_alert_state WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_alert_outbox WHERE business_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.telegram_account WHERE owner_id=%s", (biz_id,))
        cur.execute("DELETE FROM local_business.branch WHERE id=%s", (f["branch_id"],))
        cur.execute("DELETE FROM local_business.business WHERE id=%s", (biz_id,))
        cur.execute("DELETE FROM multichannel.inventory_movement WHERE master_sku_id IN (%s, %s)", (m_id1, m_id2))
        cur.execute("DELETE FROM multichannel.inventory_balance WHERE master_sku_id IN (%s, %s)", (m_id1, m_id2))
        cur.execute("DELETE FROM multichannel.master_sku WHERE id IN (%s, %s)", (m_id1, m_id2))
        cur.execute("DELETE FROM multichannel.warehouse WHERE id=%s", (wh_id,))
        c.commit()


def run_all_cases():
    print(f"=== Starting Telegram Low-Stock Threshold Management Acceptance (Tag: {TAG}) ===")
    f = setup_fixtures()
    biz_id = f["biz_id"]
    branch_id = f["branch_id"]
    wh_id = f["wh_id"]
    m_id1 = f["m_id1"]
    sku1 = f["sku1"]
    m_id2 = f["m_id2"]
    sku2 = f["sku2"]
    user_id = f["tg_user_id"]
    chat_id = f["chat_id"]
    scope = (biz_id, biz_id, branch_id, wh_id, f"Disposable TM {TAG}")

    try:
        # A. /stokminimum with no config -> empty message
        def case_a():
            bot = MockBotClient()
            msg_upd = {
                "update_id": 101,
                "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": "/stokminimum"}
            }
            bot_poller._handle_message(bot, msg_upd, scope)
            assert len(bot.sent_messages) == 1
            assert "Belum ada batas stok minimum yang diatur." in bot.sent_messages[0]["text"]
        test("Case A: /stokminimum with no config => Empty message", case_a)

        # B. valid SKU threshold -> preview, zero pre-confirm mutation
        last_token = None
        def case_b():
            nonlocal last_token
            bot = MockBotClient()
            msg_upd = {
                "update_id": 102,
                "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/stokminimum {sku1} 3"}
            }
            bot_poller._handle_message(bot, msg_upd, scope)
            assert len(bot.sent_messages) == 1
            sent = bot.sent_messages[0]
            assert "⚙️ ATUR STOK MINIMUM" in sent["text"]
            assert f"SKU: {sku1}" in sent["text"]
            assert "Stok sekarang: 2" in sent["text"]
            assert "Batas lama: Belum diatur" in sent["text"]
            assert "Batas baru: 3" in sent["text"]
            assert sent["reply_markup"] is not None
            buttons = sent["reply_markup"]["inline_keyboard"][0]
            assert buttons[0]["text"] == "✅ Simpan"
            assert buttons[1]["text"] == "❌ Batal"
            cb_data = buttons[0]["callback_data"]
            assert cb_data.startswith("th_confirm:")
            last_token = cb_data.split(":", 1)[1]

            # Prove ZERO pre-confirm mutation
            t = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_id1)
            assert t is None, f"Expected no threshold before confirm, got {t}"
        test("Case B: /stokminimum SKU 3 => Preview rendered with zero pre-confirm mutation", case_b)

        # C. Confirm -> threshold created exactly once
        def case_c():
            bot = MockBotClient()
            cb_upd = {
                "update_id": 103,
                "callback_query": {
                    "id": "cb-103",
                    "from": {"id": user_id},
                    "message": {"chat": {"id": chat_id}, "message_id": 1001},
                    "data": f"th_confirm:{last_token}",
                }
            }
            bot_poller._handle_callback(bot, cb_upd, scope)
            assert len(bot.callback_answers) == 1
            assert "berhasil disimpan" in bot.callback_answers[0]["text"]
            assert len(bot.sent_messages) == 1
            assert f"berhasil diatur ke 3" in bot.sent_messages[0]["text"]

            # Verify in DB
            t = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_id1)
            assert t == 3, f"Expected threshold 3, got {t}"
            # Check table rows count for this SKU
            rows = db.semua("SELECT * FROM local_business.low_stock_threshold WHERE business_id=%s AND master_sku_id=%s", (biz_id, m_id1))
            assert len(rows) == 1
        test("Case C: Confirm callback => Threshold created exactly once in DB", case_c)

        # D. Duplicate Confirm -> idempotent (no duplicate rows, safe answer)
        def case_d():
            bot = MockBotClient()
            cb_upd = {
                "update_id": 104,
                "callback_query": {
                    "id": "cb-104",
                    "from": {"id": user_id},
                    "message": {"chat": {"id": chat_id}, "message_id": 1001},
                    "data": f"th_confirm:{last_token}",
                }
            }
            bot_poller._handle_callback(bot, cb_upd, scope)
            assert len(bot.callback_answers) == 1
            assert "sudah disimpan" in bot.callback_answers[0]["text"]
            assert len(bot.sent_messages) == 0  # No duplicate message sent

            rows = db.semua("SELECT * FROM local_business.low_stock_threshold WHERE business_id=%s AND master_sku_id=%s", (biz_id, m_id1))
            assert len(rows) == 1
        test("Case D: Duplicate Confirm callback => Idempotent without duplicate rows", case_d)

        # E. Change threshold 3 -> 5 through preview & confirm
        token_change = None
        def case_e():
            nonlocal token_change
            # Preview
            bot = MockBotClient()
            msg_upd = {
                "update_id": 105,
                "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/stokminimum {sku1} 5"}
            }
            bot_poller._handle_message(bot, msg_upd, scope)
            assert "Batas lama: 3" in bot.sent_messages[0]["text"]
            assert "Batas baru: 5" in bot.sent_messages[0]["text"]
            token_change = bot.sent_messages[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":", 1)[1]

            # Confirm
            bot_cb = MockBotClient()
            cb_upd = {
                "update_id": 106,
                "callback_query": {
                    "id": "cb-106",
                    "from": {"id": user_id},
                    "message": {"chat": {"id": chat_id}, "message_id": 1002},
                    "data": f"th_confirm:{token_change}",
                }
            }
            bot_poller._handle_callback(bot_cb, cb_upd, scope)
            t = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_id1)
            assert t == 5
        test("Case E: Update threshold 3 -> 5 => Preview shows old=3 new=5 and commits to 5", case_e)

        # F. "off" -> preview -> threshold removed
        token_off = None
        def case_f():
            nonlocal token_off
            bot = MockBotClient()
            msg_upd = {
                "update_id": 107,
                "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/stokminimum {sku1} off"}
            }
            bot_poller._handle_message(bot, msg_upd, scope)
            assert "Batas lama: 5" in bot.sent_messages[0]["text"]
            assert "Batas baru: Nonaktif (off)" in bot.sent_messages[0]["text"]
            token_off = bot.sent_messages[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":", 1)[1]

            # Verify not removed before confirm
            t_before = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_id1)
            assert t_before == 5

            # Confirm removal
            bot_cb = MockBotClient()
            cb_upd = {
                "update_id": 108,
                "callback_query": {
                    "id": "cb-108",
                    "from": {"id": user_id},
                    "message": {"chat": {"id": chat_id}, "message_id": 1003},
                    "data": f"th_confirm:{token_off}",
                }
            }
            bot_poller._handle_callback(bot_cb, cb_upd, scope)
            assert "dinonaktifkan" in bot_cb.sent_messages[0]["text"]

            # Verify in DB
            t_after = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_id1)
            assert t_after is None
        test("Case F: /stokminimum SKU off => Preview & confirmation removes threshold", case_f)

        # G. Duplicate off confirm -> idempotent
        def case_g():
            bot = MockBotClient()
            cb_upd = {
                "update_id": 109,
                "callback_query": {
                    "id": "cb-109",
                    "from": {"id": user_id},
                    "message": {"chat": {"id": chat_id}, "message_id": 1003},
                    "data": f"th_confirm:{token_off}",
                }
            }
            bot_poller._handle_callback(bot, cb_upd, scope)
            assert "sudah disimpan" in bot.callback_answers[0]["text"]
            t = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_id1)
            assert t is None
        test("Case G: Duplicate off confirm => Idempotent", case_g)

        # H. Negative / non-integer rejected
        def case_h():
            bot1 = MockBotClient()
            bot_poller._handle_message(bot1, {"update_id": 110, "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/stokminimum {sku1} -2"}}, scope)
            assert "non-negatif" in bot1.sent_messages[0]["text"]

            bot2 = MockBotClient()
            bot_poller._handle_message(bot2, {"update_id": 111, "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/stokminimum {sku1} abc"}}, scope)
            assert "berupa angka bulat" in bot2.sent_messages[0]["text"]
        test("Case H: Negative / non-integer threshold => Rejected with clear hint", case_h)

        # I. Unknown SKU rejected
        def case_i():
            bot = MockBotClient()
            bot_poller._handle_message(bot, {"update_id": 112, "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": "/stokminimum NON-EXISTENT-SKU 5"}}, scope)
            assert "tidak ditemukan" in bot.sent_messages[0]["text"]
        test("Case I: Unknown SKU => Rejected gracefully", case_i)

        # J. Wrong Telegram user cannot confirm
        def case_j():
            # Create a draft with owner user_id
            bot = MockBotClient()
            bot_poller._handle_message(bot, {"update_id": 113, "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/stokminimum {sku1} 4"}}, scope)
            tok = bot.sent_messages[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":", 1)[1]

            # Attacker user 7779999 attempts confirmation
            bot_attacker = MockBotClient()
            cb_upd = {
                "update_id": 114,
                "callback_query": {
                    "id": "cb-114",
                    "from": {"id": 7779999},
                    "message": {"chat": {"id": chat_id}, "message_id": 1004},
                    "data": f"th_confirm:{tok}",
                }
            }
            bot_poller._handle_callback(bot_attacker, cb_upd, scope)
            assert "tidak berhak" in bot_attacker.callback_answers[0]["text"]
            t = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_id1)
            assert t is None, "Attacker must not mutate threshold"
        test("Case J: Wrong Telegram user => Blocked from confirming draft", case_j)

        # K. Stale / expired callback cannot mutate
        def case_k():
            bot = MockBotClient()
            bot_poller._handle_message(bot, {"update_id": 115, "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": f"/stokminimum {sku1} 4"}}, scope)
            tok = bot.sent_messages[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].split(":", 1)[1]

            # Manually expire the draft
            db.jalankan(
                "UPDATE local_business.telegram_threshold_draft SET expires_at=now() - INTERVAL '1 hour' WHERE draft_token=%s",
                (tok,)
            )

            bot_exp = MockBotClient()
            cb_upd = {
                "update_id": 116,
                "callback_query": {
                    "id": "cb-116",
                    "from": {"id": user_id},
                    "message": {"chat": {"id": chat_id}, "message_id": 1005},
                    "data": f"th_confirm:{tok}",
                }
            }
            bot_poller._handle_callback(bot_exp, cb_upd, scope)
            assert "kedaluwarsa" in bot_exp.callback_answers[0]["text"]
            t = low_stock.get_threshold(business_id=biz_id, master_sku_id=m_id1)
            assert t is None, "Expired draft must not mutate threshold"
        test("Case K: Stale / expired callback => Blocked from mutating", case_k)

        # L. /stokrendah returns correct configured low-stock product
        def case_l():
            # Set threshold = 3 for SKU1 (stock is 2 <= 3 -> LOW)
            low_stock.set_threshold(business_id=biz_id, threshold=3, master_sku_id=m_id1)
            # Set threshold = 5 for SKU2 (stock is 10 > 5 -> NORMAL)
            low_stock.set_threshold(business_id=biz_id, threshold=5, master_sku_id=m_id2)

            bot = MockBotClient()
            bot_poller._handle_message(bot, {"update_id": 117, "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": "/stokrendah"}}, scope)
            assert len(bot.sent_messages) == 1
            text = bot.sent_messages[0]["text"]
            assert "⚠️ STOK MENIPIS" in text
            assert f"SKU: {sku1}" in text
            assert "Stok: 2" in text
            assert "Minimum: 3" in text
        test("Case L: /stokrendah => Lists product with available stock <= threshold", case_l)

        # M. Product above threshold not listed in /stokrendah
        def case_m():
            bot = MockBotClient()
            bot_poller._handle_message(bot, {"update_id": 118, "message": {"chat": {"id": chat_id}, "from": {"id": user_id}, "text": "/stokrendah"}}, scope)
            text = bot.sent_messages[0]["text"]
            assert f"SKU: {sku2}" not in text, "Product above threshold must not be listed"
        test("Case M: Product with stock > threshold is excluded from /stokrendah", case_m)

        # N. Zero inventory mutation occurred from threshold commands
        def case_n():
            b1 = inv.location_balance(m_id1, wh_id)
            b2 = inv.location_balance(m_id2, wh_id)
            assert b1["available"] == 2
            assert b2["available"] == 10
        test("Case N: Inventory balances remain completely untouched by threshold commands", case_n)

        # O. Zero Finance mutation
        def case_o():
            fin_rows = db.semua("SELECT * FROM local_business.sale_finance WHERE sale_id IN (SELECT id FROM local_business.sale WHERE business_id=%s)", (biz_id,))
            assert len(fin_rows) == 0
        test("Case O: Finance records remain zero", case_o)

        # P. Low-Stock worker remains healthy & compatible
        def case_p():
            # Consuming stock 10 -> 4 for SKU2 (threshold 5) triggers normal low-stock alert hook
            res = inv.consume_location(
                tenant_id=TENANT, business_id=biz_id, branch_id=branch_id,
                warehouse_id=wh_id, master_sku_id=m_id2, sku=sku2,
                quantity=6, reference="test-p", source_document="TEST-P",
                idempotency_key=f"test-p-{TAG}",
            )
            assert res["available_after"] == 4
            outbox_rows = db.semua("SELECT * FROM local_business.telegram_alert_outbox WHERE business_id=%s AND notification_type='LOW_STOCK'", (biz_id,))
            assert len(outbox_rows) == 1
        test("Case P: Low-Stock event engine seamlessly integrates with configured threshold", case_p)

        # Q. Daily summary remains untouched
        def case_q():
            timer_rows = db.semua("SELECT * FROM local_business.telegram_alert_outbox WHERE notification_type LIKE %s AND business_id=%s", ("DAILY_SUMMARY%", biz_id))
            assert len(timer_rows) == 0
        test("Case Q: Daily Summary outbox remains untouched", case_q)

    finally:
        cleanup_fixtures(f)
        print("=== Cleanup of disposable acceptance fixtures complete ===")

    print(f"\nRESULTS: Passed: {passed}, Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all_cases())
