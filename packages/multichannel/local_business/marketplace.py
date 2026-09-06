"""Marketplace stock projection from Local Business fulfillment pool.

LOCAL SALE -> CENTRAL INVENTORY CHANGE -> marketplace desired stock
projection/outbox updates.

The fulfillment pool is an explicit configurable set of locations (branches/
warehouses). Marketplace desired quantity = sum of available across the
fulfillment pool for a master SKU. This is written to the existing
`multichannel.inventory_sync_state.desired_qty` and outbox.

REAL_MARKETPLACE_STOCK_WRITE stays OFF: we only update the projection/outbox,
never call the provider. Actual provider remote write remains OFF until
credentials/approval exist.
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg
from . import inventory as inv


def fulfillment_pool_available(master_sku_id: int, warehouse_ids: list[int]) -> int:
    """Sum of available across the fulfillment pool locations."""
    if not warehouse_ids:
        return 0
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT COALESCE(SUM(on_hand - reserved - safety_stock),0) AS a
               FROM multichannel.inventory_balance
               WHERE master_sku_id=%s AND warehouse_id = ANY(%s)""",
            (master_sku_id, warehouse_ids))
        r = cur.fetchone()
        return max(int(r["a"]), 0)


def project_to_marketplace(*, master_sku_id: int, warehouse_ids: list[int]) -> dict:
    """Update marketplace desired_qty projection for a master SKU.

    Uses the existing transactional outbox. Does NOT write to any provider.
    Returns the desired quantity and affected channel mappings.
    """
    desired = fulfillment_pool_available(master_sku_id, warehouse_ids)
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT ss.id AS sync_state_id, ss.provider, ss.shop_id, ss.channel_sku
               FROM multichannel.inventory_sync_state ss
               WHERE ss.master_sku_id=%s""", (master_sku_id,))
        states = cur.fetchall()
        for st in states:
            cur.execute(
                """UPDATE multichannel.inventory_sync_state
                   SET desired_qty=%s, updated_at=now() WHERE id=%s""",
                (desired, st["sync_state_id"]))
            cur.execute(
                """INSERT INTO multichannel.inventory_sync_outbox
                   (sync_state_id, provider, shop_id, channel_sku, master_sku_id,
                    desired_qty, origin)
                   VALUES (%s,%s,%s,%s,%s,%s,'local_business')
                   ON CONFLICT (sync_state_id) DO UPDATE SET
                     desired_qty=EXCLUDED.desired_qty, status='PENDING',
                     attempts=0, created_at=now()""",
                (st["sync_state_id"], st["provider"], st["shop_id"],
                 st["channel_sku"], master_sku_id, desired))
        c.commit()
    return {"desired_qty": desired, "channel_mappings": len(states),
            "real_marketplace_stock_write": "OFF"}
