"""Migrasi schema Local Business and the customer tenant boundary."""

from __future__ import annotations

from pathlib import Path

from ..persistence.db import koneksi


def _run_intake_schema() -> None:
    sql = Path(__file__).resolve().parent / "intake_schema.sql"
    try:
        with koneksi() as c:
            with c.cursor() as cur:
                cur.execute(sql.read_text(encoding="utf-8"))
                c.commit()
    except Exception as exc:
        # Do not silently swallow migration failures; log loudly but do not
        # crash unrelated startup.
        print(f"[migrate] intake_schema failed: {type(exc).__name__}: {exc}", flush=True)
        raise


def migrasi() -> list[str]:
    log = []
    _run_intake_schema()
    for fname in ("schema.sql", "schema_expansion.sql", "umkm_schema.sql",
                  "sales_schema.sql", "tenantization_v1.sql", "telegram_v2_schema.sql"):
        sql = Path(__file__).resolve().parent / fname
        teks = sql.read_text(encoding="utf-8")
        try:
            with koneksi() as c:
                with c.cursor() as cur:
                    cur.execute(teks)
                    if fname == "schema.sql":
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS created_at_client TIMESTAMPTZ"
                        )
                        for seq in ["sale_receipt_seq", "restaurant_order_seq", "transfer_seq",
                                    "return_seq", "goods_receipt_seq", "kot_seq"]:
                            cur.execute(
                                "CREATE SEQUENCE IF NOT EXISTS local_business.%s" % seq
                            )
                    if fname == "schema_expansion.sql":
                        # reporting dimensions on existing tables
                        cur.execute(
                            "ALTER TABLE local_business.menu_item "
                            "ADD COLUMN IF NOT EXISTS reporting_category TEXT NOT NULL DEFAULT 'FOOD'"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS sales_channel TEXT NOT NULL DEFAULT 'DINE_IN'"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS source_provider TEXT NOT NULL DEFAULT 'LOCAL'"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS external_order_id TEXT NOT NULL DEFAULT ''"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS service_charge NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS provider_fee NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS merchant_promo_cost NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS platform_promo NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS local_discount NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS other_adjustment NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS payment_state TEXT NOT NULL DEFAULT 'UNPAID'"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS expected_settlement NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS actual_settlement NUMERIC(20,2)"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS settlement_variance NUMERIC(20,2)"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS provider_status TEXT NOT NULL DEFAULT ''"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order "
                            "ADD COLUMN IF NOT EXISTS raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order_line "
                            "ADD COLUMN IF NOT EXISTS channel_item_id TEXT NOT NULL DEFAULT ''"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.restaurant_order_line "
                            "ADD COLUMN IF NOT EXISTS modifier_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS sales_channel TEXT NOT NULL DEFAULT 'POS'"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS source_provider TEXT NOT NULL DEFAULT 'LOCAL'"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS external_order_id TEXT NOT NULL DEFAULT ''"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS service_charge NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS provider_fee NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS merchant_promo_cost NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS platform_promo NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS local_discount NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS other_adjustment NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS payment_state TEXT NOT NULL DEFAULT 'PAID'"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS expected_settlement NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS actual_settlement NUMERIC(20,2)"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale "
                            "ADD COLUMN IF NOT EXISTS settlement_variance NUMERIC(20,2)"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale_line "
                            "ADD COLUMN IF NOT EXISTS reporting_category TEXT NOT NULL DEFAULT 'RETAIL'"
                        )
                        cur.execute(
                            "ALTER TABLE local_business.sale_line "
                            "ADD COLUMN IF NOT EXISTS cost NUMERIC(20,2) NOT NULL DEFAULT 0"
                        )
                c.commit()
            log.append(f"{fname} ok")
        except Exception as e:
            log.append(f"skip:{fname}:{type(e).__name__}:{str(e)[:200]}")
    return log
