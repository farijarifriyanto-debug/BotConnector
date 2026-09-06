"""Migrasi schema Central Inventory (inventory/schema.sql)."""

from __future__ import annotations

from pathlib import Path

from ..persistence.db import koneksi


def migrasi() -> list[str]:
    sql = Path(__file__).resolve().parent / "schema.sql"
    teks = sql.read_text(encoding="utf-8")
    log = []
    try:
        with koneksi() as c:
            with c.cursor() as cur:
                cur.execute(teks)
                # location-aware balance: ganti unique master_sku -> (master_sku, warehouse)
                cur.execute(
                    "ALTER TABLE multichannel.inventory_balance "
                    "DROP CONSTRAINT IF EXISTS uq_balance_master_sku"
                )
                cur.execute(
                    "ALTER TABLE multichannel.inventory_balance "
                    "DROP CONSTRAINT IF EXISTS uq_balance_master_sku_warehouse"
                )
                cur.execute(
                    "ALTER TABLE multichannel.inventory_balance "
                    "ADD CONSTRAINT uq_balance_master_sku_warehouse "
                    "UNIQUE (master_sku_id, warehouse_id)"
                )
                cur.execute(
                    "ALTER TABLE multichannel.inventory_balance "
                    "ADD COLUMN IF NOT EXISTS in_transit INTEGER NOT NULL DEFAULT 0"
                )
                # location/audit columns on movement
                for col, ddl in [
                    ("warehouse_id", "BIGINT REFERENCES multichannel.warehouse(id)"),
                    ("tenant_id", "TEXT NOT NULL DEFAULT ''"),
                    ("actor", "TEXT NOT NULL DEFAULT ''"),
                    ("device_id", "TEXT NOT NULL DEFAULT ''"),
                    ("source_document", "TEXT NOT NULL DEFAULT ''"),
                    ("idempotency_key", "TEXT NOT NULL DEFAULT ''"),
                ]:
                    cur.execute(
                        "ALTER TABLE multichannel.inventory_movement "
                        "ADD COLUMN IF NOT EXISTS %s %s" % (col, ddl)
                    )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_movement_wh "
                    "ON multichannel.inventory_movement(warehouse_id, created_at)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_movement_idem "
                    "ON multichannel.inventory_movement(idempotency_key)"
                )
            c.commit()
        log.append("inventory schema ok")
    except Exception as e:
        log.append(f"skip:{type(e).__name__}:{str(e)[:200]}")
    return log
