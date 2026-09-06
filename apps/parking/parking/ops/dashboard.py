"""M10: Dashboard service — derives KPIs from actual Parking runtime data.

Occupancy is derived from active session state, never from a manually
incremented counter. Capacity is only shown if configured.
"""

from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import func, select

from parking.domain.enums import ACTIVE_SESSION_STATES, PaymentState, SessionState
from parking.models import (
    ParkingAnprEvent,
    ParkingDevice,
    ParkingDeviceRuntime,
    ParkingEdge,
    ParkingEvent,
    ParkingGate,
    ParkingGateRuntime,
    ParkingPayment,
    ParkingSession,
    ParkingSite,
)
from parking.repositories.registry import SiteRepository
from parking.services.auth import Scope


def _day_start_utc(now: datetime) -> datetime:
    return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)


class DashboardService:
    def __init__(self, session, scope: Scope):
        self.session = session
        self.scope = scope
        self.tenant_id = scope.tenant_id

    def site_summary(self, site_id: int) -> dict:
        site = SiteRepository(self.session, self.tenant_id).get(site_id)
        now = datetime.now(timezone.utc)
        day_start = _day_start_utc(now)

        active = self.session.scalar(
            select(func.count(ParkingSession.id)).where(
                ParkingSession.tenant_id == self.tenant_id,
                ParkingSession.site_id == site_id,
                ParkingSession.state.in_(ACTIVE_SESSION_STATES),
            )
        ) or 0

        entries_today = self.session.scalar(
            select(func.count(ParkingSession.id)).where(
                ParkingSession.tenant_id == self.tenant_id,
                ParkingSession.site_id == site_id,
                ParkingSession.entry_at >= day_start,
            )
        ) or 0

        exits_today = self.session.scalar(
            select(func.count(ParkingSession.id)).where(
                ParkingSession.tenant_id == self.tenant_id,
                ParkingSession.site_id == site_id,
                ParkingSession.exit_at >= day_start,
            )
        ) or 0

        revenue_today = self.session.scalar(
            select(func.coalesce(func.sum(ParkingSession.paid_amount), 0)).where(
                ParkingSession.tenant_id == self.tenant_id,
                ParkingSession.site_id == site_id,
                ParkingSession.payment_state.in_([PaymentState.PAID.value, PaymentState.COMPLIMENTARY.value]),
                ParkingSession.exit_at >= day_start,
            )
        ) or 0

        unpaid = self.session.scalar(
            select(func.count(ParkingSession.id)).where(
                ParkingSession.tenant_id == self.tenant_id,
                ParkingSession.site_id == site_id,
                ParkingSession.state.in_(ACTIVE_SESSION_STATES),
                ParkingSession.payment_state == PaymentState.NONE.value,
            )
        ) or 0

        manual_review = self.session.scalar(
            select(func.count(ParkingAnprEvent.id)).where(
                ParkingAnprEvent.tenant_id == self.tenant_id,
                ParkingAnprEvent.site_id == site_id,
                ParkingAnprEvent.state == "MANUAL_REVIEW",
            )
        ) or 0

        offline_devices = self.session.scalar(
            select(func.count(ParkingDeviceRuntime.id)).where(
                ParkingDeviceRuntime.tenant_id == self.tenant_id,
                ParkingDeviceRuntime.site_id == site_id,
                ParkingDeviceRuntime.state == "OFFLINE",
            )
        ) or 0

        gates = list(
            self.session.scalars(
                select(ParkingGate).where(ParkingGate.tenant_id == self.tenant_id, ParkingGate.site_id == site_id)
            )
        )
        gate_status = []
        for g in gates:
            rt = self.session.scalar(
                select(ParkingGateRuntime).where(
                    ParkingGateRuntime.tenant_id == self.tenant_id,
                    ParkingGateRuntime.site_id == site_id,
                    ParkingGateRuntime.gate_id == g.id,
                )
            )
            gate_status.append({"gate_id": g.id, "code": g.code, "direction": g.direction,
                                "config_status": g.status, "runtime_state": rt.state if rt else "UNKNOWN"})

        occupancy = {"active": active}
        if site.capacity_total is not None:
            occupancy["capacity_total"] = site.capacity_total
            occupancy["available_total"] = max(0, site.capacity_total - active)
        if site.capacity_car is not None:
            occupancy["capacity_car"] = site.capacity_car
        if site.capacity_motorcycle is not None:
            occupancy["capacity_motorcycle"] = site.capacity_motorcycle

        return {
            "site_id": site.id,
            "site_code": site.code,
            "occupancy": occupancy,
            "entries_today": entries_today,
            "exits_today": exits_today,
            "revenue_today": int(revenue_today),
            "unpaid": unpaid,
            "manual_review": manual_review,
            "offline_devices": offline_devices,
            "gate_status": gate_status,
        }

    def live_parking(self, site_id: int) -> list[dict]:
        """Operational live session list."""
        rows = list(
            self.session.scalars(
                select(ParkingSession)
                .where(
                    ParkingSession.tenant_id == self.tenant_id,
                    ParkingSession.site_id == site_id,
                    ParkingSession.state.in_(ACTIVE_SESSION_STATES),
                )
                .order_by(ParkingSession.entry_at.desc())
                .limit(200)
            )
        )
        return [
            {
                "public_reference": s.public_reference,
                "plate_normalized": s.plate_normalized,
                "plate_display": s.plate_display,
                "vehicle_type": s.vehicle_type,
                "entry_at": s.entry_at,
                "state": s.state,
                "payment_state": s.payment_state,
                "calculated_amount": s.calculated_amount,
                "paid_amount": s.paid_amount,
                "lost_ticket": s.lost_ticket,
            }
            for s in rows
        ]

    def device_health(self, site_id: int) -> list[dict]:
        devices = list(
            self.session.scalars(
                select(ParkingDevice).where(ParkingDevice.tenant_id == self.tenant_id, ParkingDevice.site_id == site_id)
            )
        )
        out = []
        for d in devices:
            rt = self.session.scalar(
                select(ParkingDeviceRuntime).where(
                    ParkingDeviceRuntime.tenant_id == self.tenant_id,
                    ParkingDeviceRuntime.site_id == site_id,
                    ParkingDeviceRuntime.device_id == d.id,
                )
            )
            out.append({
                "device_id": d.device_id, "name": d.name, "device_type": d.device_type,
                "adapter_type": d.adapter_type, "config_status": d.status, "enabled": d.enabled,
                "runtime_state": rt.state if rt else "UNKNOWN",
                "last_seen_at": rt.last_seen_at if rt else None,
            })
        return out

    def edge_status(self, site_id: int) -> list[dict]:
        edges = list(
            self.session.scalars(
                select(ParkingEdge).where(ParkingEdge.tenant_id == self.tenant_id, ParkingEdge.site_id == site_id)
            )
        )
        return [{"edge_id": e.edge_id, "name": e.name, "last_seen_at": e.last_seen_at} for e in edges]
