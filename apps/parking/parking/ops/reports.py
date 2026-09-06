"""M11: Reports service — server-side operational/financial reports.

All calculations are server-side. Historical monetary reporting derives from
payment records, tariff snapshots, and session state — never from current tariff
plan values. Money is integer IDR (no floats).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select

from parking.domain.enums import ACTIVE_SESSION_STATES, PaymentState, SessionState
from parking.models import (
    ParkingAnprCorrection,
    ParkingAnprEvent,
    ParkingAuditLog,
    ParkingDevice,
    ParkingDeviceRuntime,
    ParkingEdge,
    ParkingEdgeSyncEvent,
    ParkingEvent,
    ParkingGate,
    ParkingPayment,
    ParkingSession,
    ParkingSite,
)
from parking.repositories.registry import SiteRepository
from parking.services.auth import Scope


def _day_bounds_utc(date: datetime.date) -> tuple[datetime, datetime]:
    start = datetime.combine(date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


class ReportService:
    def __init__(self, session, scope: Scope):
        self.session = session
        self.scope = scope
        self.tenant_id = scope.tenant_id

    def _site(self, site_id: int) -> ParkingSite:
        return SiteRepository(self.session, self.tenant_id).get(site_id)

    def daily_operations(self, site_id: int, day: datetime.date) -> dict:
        self._site(site_id)
        start, end = _day_bounds_utc(day)
        entries = self.session.scalar(
            select(func.count(ParkingSession.id)).where(
                ParkingSession.tenant_id == self.tenant_id, ParkingSession.site_id == site_id,
                ParkingSession.entry_at >= start, ParkingSession.entry_at < end,
            )
        ) or 0
        exits = self.session.scalar(
            select(func.count(ParkingSession.id)).where(
                ParkingSession.tenant_id == self.tenant_id, ParkingSession.site_id == site_id,
                ParkingSession.exit_at >= start, ParkingSession.exit_at < end,
            )
        ) or 0
        # Revenue for the day = paid sessions whose entry fell in the day.
        revenue = self.session.scalar(
            select(func.coalesce(func.sum(ParkingSession.paid_amount), 0)).where(
                ParkingSession.tenant_id == self.tenant_id, ParkingSession.site_id == site_id,
                ParkingSession.payment_state.in_([PaymentState.PAID.value, PaymentState.COMPLIMENTARY.value]),
                ParkingSession.entry_at >= start, ParkingSession.entry_at < end,
            )
        ) or 0
        manual_review = self.session.scalar(
            select(func.count(ParkingAnprEvent.id)).where(
                ParkingAnprEvent.tenant_id == self.tenant_id, ParkingAnprEvent.site_id == site_id,
                ParkingAnprEvent.state == "MANUAL_REVIEW",
            )
        ) or 0
        return {
            "date": day.isoformat(), "site_id": site_id,
            "entries": entries, "exits": exits,
            "revenue": int(revenue), "manual_review": manual_review,
        }

    def revenue_report(self, site_id: int, start: datetime, end: datetime) -> dict:
        self._site(site_id)
        payments = list(
            self.session.scalars(
                select(ParkingPayment).where(
                    ParkingPayment.tenant_id == self.tenant_id, ParkingPayment.site_id == site_id,
                    ParkingPayment.state == "PAID",
                    ParkingPayment.paid_at >= start, ParkingPayment.paid_at < end,
                )
            )
        )
        by_method: dict[str, int] = {}
        total = 0
        for p in payments:
            by_method[p.method] = by_method.get(p.method, 0) + p.expected_amount
            total += p.expected_amount
        return {
            "site_id": site_id, "start": start.isoformat(), "end": end.isoformat(),
            "gross_revenue": total, "transaction_count": len(payments),
            "by_method": by_method,
        }

    def payment_report(self, site_id: int, start: datetime, end: datetime) -> dict:
        self._site(site_id)
        payments = list(
            self.session.scalars(
                select(ParkingPayment).where(
                    ParkingPayment.tenant_id == self.tenant_id, ParkingPayment.site_id == site_id,
                    ParkingPayment.created_at >= start, ParkingPayment.created_at < end,
                )
            )
        )
        states: dict[str, int] = {}
        for p in payments:
            states[p.state] = states.get(p.state, 0) + 1
        return {"site_id": site_id, "payment_count": len(payments), "by_state": states}

    def gate_report(self, site_id: int, start: datetime, end: datetime) -> dict:
        self._site(site_id)
        gates = list(
            self.session.scalars(
                select(ParkingGate).where(ParkingGate.tenant_id == self.tenant_id, ParkingGate.site_id == site_id)
            )
        )
        out = []
        for g in gates:
            allowed = self.session.scalar(
                select(func.count(ParkingEvent.id)).where(
                    ParkingEvent.tenant_id == self.tenant_id, ParkingEvent.site_id == site_id,
                    ParkingEvent.event_type == "ENTRY_ALLOWED",
                    ParkingEvent.occurred_at >= start, ParkingEvent.occurred_at < end,
                )
            ) or 0
            denied = self.session.scalar(
                select(func.count(ParkingEvent.id)).where(
                    ParkingEvent.tenant_id == self.tenant_id, ParkingEvent.site_id == site_id,
                    ParkingEvent.event_type == "ENTRY_DENIED",
                    ParkingEvent.occurred_at >= start, ParkingEvent.occurred_at < end,
                )
            ) or 0
            out.append({"gate_id": g.id, "code": g.code, "direction": g.direction,
                        "allowed": allowed, "denied": denied, "source": "SIMULATED"})
        return {"site_id": site_id, "gates": out}

    def anpr_report(self, site_id: int, start: datetime, end: datetime) -> dict:
        self._site(site_id)
        total = self.session.scalar(
            select(func.count(ParkingAnprEvent.id)).where(
                ParkingAnprEvent.tenant_id == self.tenant_id, ParkingAnprEvent.site_id == site_id,
                ParkingAnprEvent.created_at >= start, ParkingAnprEvent.created_at < end,
            )
        ) or 0
        manual = self.session.scalar(
            select(func.count(ParkingAnprEvent.id)).where(
                ParkingAnprEvent.tenant_id == self.tenant_id, ParkingAnprEvent.site_id == site_id,
                ParkingAnprEvent.state == "MANUAL_REVIEW",
                ParkingAnprEvent.created_at >= start, ParkingAnprEvent.created_at < end,
            )
        ) or 0
        rejected = self.session.scalar(
            select(func.count(ParkingAnprEvent.id)).where(
                ParkingAnprEvent.tenant_id == self.tenant_id, ParkingAnprEvent.site_id == site_id,
                ParkingAnprEvent.state == "REJECTED",
                ParkingAnprEvent.created_at >= start, ParkingAnprEvent.created_at < end,
            )
        ) or 0
        corrections = self.session.scalar(
            select(func.count(ParkingAnprCorrection.id)).where(
                ParkingAnprCorrection.tenant_id == self.tenant_id, ParkingAnprCorrection.site_id == site_id,
                ParkingAnprCorrection.created_at >= start, ParkingAnprCorrection.created_at < end,
            )
        ) or 0
        return {
            "site_id": site_id, "recognition_events": total, "manual_reviews": manual,
            "rejected": rejected, "manual_corrections": corrections,
            "real_world_accuracy": "NOT_MEASURED",  # simulator only
        }

    def edge_report(self, site_id: int) -> dict:
        self._site(site_id)
        edges = list(
            self.session.scalars(
                select(ParkingEdge).where(ParkingEdge.tenant_id == self.tenant_id, ParkingEdge.site_id == site_id)
            )
        )
        out = []
        for e in edges:
            synced = self.session.scalar(
                select(func.count(ParkingEdgeSyncEvent.id)).where(
                    ParkingEdgeSyncEvent.tenant_id == self.tenant_id,
                    ParkingEdgeSyncEvent.edge_id == e.edge_id,
                )
            ) or 0
            out.append({"edge_id": e.edge_id, "name": e.name, "synced_events": synced,
                        "last_seen_at": e.last_seen_at})
        return {"site_id": site_id, "edges": out}

    def audit(self, site_id: int | None = None, actor: str | None = None,
              action: str | None = None, limit: int = 200) -> list[dict]:
        if site_id is not None:
            self._site(site_id)
        stmt = select(ParkingAuditLog).where(ParkingAuditLog.tenant_id == self.tenant_id)
        if site_id is not None:
            stmt = stmt.where(ParkingAuditLog.site_id == site_id)
        if actor is not None:
            stmt = stmt.where(ParkingAuditLog.actor == actor)
        if action is not None:
            stmt = stmt.where(ParkingAuditLog.action == action)
        stmt = stmt.order_by(ParkingAuditLog.occurred_at.desc()).limit(limit)
        rows = list(self.session.scalars(stmt))
        return [
            {"id": r.id, "site_id": r.site_id, "actor": r.actor, "action": r.action,
             "object_type": r.object_type, "object_id": r.object_id, "occurred_at": r.occurred_at}
            for r in rows
        ]

    def export_csv(self, rows: list[dict], columns: list[str]) -> str:
        """CSV export with spreadsheet formula-injection protection."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_safe_cell(row.get(c, "")) for c in columns])
        return buf.getvalue()


def _safe_cell(value) -> str:
    """Escape spreadsheet formula injection for cells starting with =, +, -, @, tab, or newline."""
    s = str(value) if value is not None else ""
    stripped = s.lstrip()
    if stripped.startswith(("=", "+", "-", "@")) or s.startswith(("\t", "\r", "\n")):
        return "'" + s
    return s
