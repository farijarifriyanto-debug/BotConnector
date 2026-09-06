"""Comprehensive automated test suite for BotConnector Telegram V2.

Verifies:
  1. Token encryption / decryption and ciphertext security at rest.
  2. Exception traceback token sanitization in BotApiClient.
  3. Dynamic Execution Context resolution and tenant boundary isolation.
  4. Multi-business switching via /bisnis and /cabang.
  5. RBAC role enforcement (Owner/Admin vs Cashier/Staff).
  6. Multi-destination pairing (Private & Group) and Notification Rules.
  7. Multi-tenant daily summary scheduler (run_daily_final_all).
  8. BYOB Webhook secret token validation (constant-time verification).
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/opt")

from botconnector_multichannel.persistence.db import koneksi as _pg, ambil, semua
from botconnector_multichannel.local_business import (
    crypto,
    bot_client,
    telegram_intake as ti,
    telegram_registry as reg,
    telegram_outbound as out_mod,
    bot_poller,
)


class TestTelegramV2CryptoAndSecurity(unittest.TestCase):
    def test_encryption_at_rest(self):
        sample_token = "987654321:AAFakeBotFatherTokenForTesting12345_XYZ"
        ciphertext = crypto.encrypt_token(sample_token)
        self.assertNotEqual(sample_token, ciphertext)
        self.assertNotIn("987654321", ciphertext)
        self.assertNotIn("AAFake", ciphertext)

        decrypted = crypto.decrypt_token(ciphertext)
        self.assertEqual(sample_token, decrypted)

    def test_webhook_secret_constant_time_verification(self):
        secret = "super-secret-token-xyz-123456"
        secret_hash = crypto.hash_secret(secret)
        self.assertTrue(crypto.verify_secret(secret, secret_hash))
        self.assertFalse(crypto.verify_secret("wrong-secret", secret_hash))
        self.assertFalse(crypto.verify_secret("", secret_hash))

    def test_bot_client_token_traceback_sanitization(self):
        fake_token = "123456:SECRET_TELEGRAM_BOT_TOKEN_DO_NOT_LEAK"
        client = bot_client.BotApiClient(fake_token)
        # Verify __repr__ and __str__ do not leak token body
        self.assertNotIn("SECRET_TELEGRAM_BOT_TOKEN_DO_NOT_LEAK", repr(client))
        self.assertNotIn("SECRET_TELEGRAM_BOT_TOKEN_DO_NOT_LEAK", str(client))

        # Mock httpx post to raise HTTPError with URL
        with patch.object(client._http, "post", side_effect=bot_client.httpx.ConnectError("Connection failed")):
            try:
                client.get_me()
                self.fail("Expected TelegramError")
            except bot_client.TelegramError as exc:
                # Token must NEVER appear in exception message
                self.assertNotIn("SECRET_TELEGRAM_BOT_TOKEN_DO_NOT_LEAK", str(exc))
                # Traceback cause must be None (from None sanitization)
                self.assertIsNone(exc.__cause__)


class TestTelegramV2ContextAndTenancy(unittest.TestCase):
    def setUp(self):
        # Find or ensure test business
        with _pg() as c:
            cur = c.cursor()
            cur.execute("SELECT id FROM local_business.business WHERE status='ACTIVE' ORDER BY id LIMIT 2")
            rows = cur.fetchall()
            self.biz1_id = rows[0]["id"]
            self.biz2_id = rows[1]["id"] if len(rows) > 1 else rows[0]["id"]

    def test_dynamic_context_resolution(self):
        test_tg_user = 9990001
        # Pair test user to biz1
        with _pg() as c:
            cur = c.cursor()
            cur.execute(
                """
                INSERT INTO local_business.telegram_account
                (owner_id, business_id, telegram_user_id, role)
                VALUES (%s, %s, %s, 'owner')
                ON CONFLICT (owner_id, telegram_user_id)
                DO UPDATE SET business_id=EXCLUDED.business_id, role='owner'
                """,
                (self.biz1_id, self.biz1_id, test_tg_user),
            )
            c.commit()

        ctx = reg.resolve_execution_context(test_tg_user, test_tg_user)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.business_id, self.biz1_id)
        self.assertEqual(ctx.role, "owner")
        self.assertTrue(ctx.is_admin)

    def test_multi_business_switching(self):
        test_tg_user = 9990002
        # Pair user to both biz1 and biz2
        with _pg() as c:
            cur = c.cursor()
            cur.execute(
                """
                INSERT INTO local_business.telegram_account
                (owner_id, business_id, telegram_user_id, role)
                VALUES (%s, %s, %s, 'owner')
                ON CONFLICT (owner_id, telegram_user_id) DO NOTHING
                """,
                (self.biz1_id, self.biz1_id, test_tg_user),
            )
            if self.biz2_id != self.biz1_id:
                cur.execute(
                    """
                    INSERT INTO local_business.telegram_account
                    (owner_id, business_id, telegram_user_id, role)
                    VALUES (%s, %s, %s, 'staff')
                    ON CONFLICT (owner_id, telegram_user_id) DO NOTHING
                    """,
                    (self.biz2_id, self.biz2_id, test_tg_user),
                )
            c.commit()

        # Switch to biz1
        sw1 = reg.switch_user_business(test_tg_user, self.biz1_id)
        self.assertTrue(sw1["ok"])
        ctx1 = reg.resolve_execution_context(test_tg_user, test_tg_user)
        self.assertEqual(ctx1.business_id, self.biz1_id)

        if self.biz2_id != self.biz1_id:
            # Switch to biz2
            sw2 = reg.switch_user_business(test_tg_user, self.biz2_id)
            self.assertTrue(sw2["ok"])
            ctx2 = reg.resolve_execution_context(test_tg_user, test_tg_user)
            self.assertEqual(ctx2.business_id, self.biz2_id)
            self.assertEqual(ctx2.role, "staff")
            self.assertFalse(ctx2.is_admin)


class TestTelegramV2DestinationsAndRules(unittest.TestCase):
    def test_private_and_group_destination_pairing(self):
        biz_id = 336
        pair_res = reg.create_destination_pairing(
            business_id=biz_id,
            destination_type="GROUP",
            purpose="ALERTS",
        )
        self.assertTrue(pair_res["ok"])
        self.assertIn("startgroup=", pair_res["pairing_url"])

        # Resolve pairing for a test group
        group_chat_id = -1001987654321
        test_user_id = 88877766
        resolve_res = reg.resolve_destination_pairing(
            raw_token=pair_res["pairing_token"],
            chat_id=group_chat_id,
            telegram_user_id=test_user_id,
            chat_title="Grup Manajemen Toko",
            chat_type="supergroup",
        )
        self.assertTrue(resolve_res["ok"])
        self.assertEqual(resolve_res["business_id"], biz_id)
        self.assertEqual(resolve_res["destination_type"], "GROUP")

        # Verify destination exists in list
        dests = reg.list_destinations(biz_id)
        matched = [d for d in dests if d["chat_id"] == group_chat_id]
        self.assertTrue(len(matched) > 0)
        self.assertEqual(matched[0]["display_name"], "Grup Manajemen Toko")

        # Configure notification rules
        dest_id = matched[0]["id"]
        rule_res = reg.set_destination_rules(
            business_id=biz_id,
            destination_id=dest_id,
            rules=[
                {"event_type": "LOW_STOCK", "enabled": True},
                {"event_type": "DAILY_SUMMARY_FINAL", "enabled": True},
            ],
        )
        self.assertTrue(rule_res["ok"])

        # Verify destination matches for LOW_STOCK event
        event_dests = out_mod.resolve_destinations_for_event(
            business_id=biz_id,
            event_type="LOW_STOCK",
        )
        self.assertTrue(any(d["chat_id"] == group_chat_id for d in event_dests))

        # Cleanup test destination
        reg.delete_destination(biz_id, dest_id)


class TestTelegramV2DailySummaryScheduler(unittest.TestCase):
    def test_multi_tenant_daily_summary_all(self):
        res = out_mod.run_daily_final_all(tz="Asia/Jakarta")
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["total_businesses"], 1)
        self.assertIn("processed_businesses", res)
        self.assertIn("total_sent", res)


if __name__ == "__main__":
    unittest.main()
