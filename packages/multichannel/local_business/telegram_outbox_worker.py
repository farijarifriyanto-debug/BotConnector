"""BC Bisnis low-stock Telegram outbox worker.

Only LOW_STOCK and OUT_OF_STOCK rows are polled here.
Actual delivery and atomic exact-ID claim remain owned by
telegram_outbound.dispatch_one().
"""

from __future__ import annotations

import logging
import os
import signal
import threading

from persistence.db import koneksi
from .telegram_outbound import dispatch_one


LOG = logging.getLogger("bc.bisnis.telegram.lowstock.worker")


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except Exception:
        value = default
    return max(lo, min(hi, value))


def _float_env(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except Exception:
        value = default
    return max(lo, min(hi, value))


def _due_ids(limit: int) -> list[int]:
    with koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """
            SELECT id
            FROM local_business.telegram_alert_outbox
            WHERE notification_type IN ('LOW_STOCK','OUT_OF_STOCK')
              AND status='PENDING'
              AND next_attempt_at <= now()
            ORDER BY id
            LIMIT %s
            """,
            (limit,),
        )
        return [int(row["id"]) for row in cur.fetchall()]


def main() -> int:
    interval = _float_env(
        "BC_BISNIS_LOW_STOCK_WORKER_INTERVAL_SECONDS",
        2.0,
        0.5,
        60.0,
    )

    max_rows = _int_env(
        "BC_BISNIS_LOW_STOCK_WORKER_MAX_ROWS",
        10,
        1,
        100,
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    stopping = threading.Event()

    def _stop(signum, frame):
        stopping.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    LOG.info(
        "low_stock_outbox_worker_started interval=%s max_rows=%s",
        interval,
        max_rows,
    )

    db_ready_logged = False

    while not stopping.is_set():
        try:
            ids = _due_ids(max_rows)

            if not db_ready_logged:
                LOG.info("low_stock_outbox_db_poll_ready")
                db_ready_logged = True

            sent = 0
            skipped = 0

            for outbox_id in ids:
                try:
                    result = dispatch_one(outbox_id=outbox_id)

                    if int(result.get("sent", 0) or 0):
                        sent += 1
                    else:
                        skipped += 1

                except Exception as exc:
                    LOG.warning(
                        "low_stock_dispatch_error outbox_id=%s type=%s",
                        outbox_id,
                        type(exc).__name__,
                    )

            if ids:
                LOG.info(
                    "low_stock_outbox_activity selected=%s sent=%s skipped=%s",
                    len(ids),
                    sent,
                    skipped,
                )

        except Exception as exc:
            LOG.warning(
                "low_stock_outbox_poll_error type=%s",
                type(exc).__name__,
            )

        stopping.wait(interval)

    LOG.info("low_stock_outbox_worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
