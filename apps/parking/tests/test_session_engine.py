"""M2 acceptance: entry flow, duplicate guard (sequential + concurrent),
cross-tenant blocking, state machine, event ledger, audit log."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from parking.domain.enums import EventType, SessionState
from parking.domain.errors import ErrorCode, ParkingError
from parking.services.entry import EntryService
from parking.services.session_service import SessionService

from tests.helpers import (
    hours_ago,
    new_gate,
    new_lane,
    new_operator,
    new_site,
    new_tenant,
    scope,
    utcnow,
)


def _make_site(db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    exit_gate = new_gate(db, tenant, site, code="G-EXIT", direction="EXIT")
    exit_lane = new_lane(db, tenant, site, exit_gate, code="L-EXIT", direction="EXIT")
    return tenant, site, gate, lane, exit_gate, exit_lane


def test_entry_creates_active_session(db):
    tenant, site, gate, lane, _, _ = _make_site(db)
    at = hours_ago(1)
    session = EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate=" B 1234 ABC ", vehicle_type="CAR", entry_at=at
    )
    assert session.state == SessionState.PARKED.value
    assert session.plate_normalized == "B1234ABC"
    assert session.plate_display == "B 1234 ABC"
    assert session.public_reference.startswith("PK-")
    assert session.entry_at.replace(tzinfo=timezone.utc) == at


def test_duplicate_active_session_blocked_sequential(db):
    tenant, site, gate, lane, _, _ = _make_site(db)
    EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate="B1234ABC", vehicle_type="CAR"
    )
    with pytest.raises(ParkingError) as exc:
        EntryService(db, scope(tenant)).create_entry(
            site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate="b 1234 abc", vehicle_type="CAR"
        )
    assert exc.value.code == ErrorCode.ACTIVE_SESSION_ALREADY_EXISTS and exc.value.status == 409


def test_duplicate_active_session_blocked_concurrent(db, session_factory):
    """Two simultaneous entries for the same vehicle/site: exactly one wins."""
    tenant, site, gate, lane, _, _ = _make_site(db)
    db.commit()

    barrier = threading.Barrier(2)
    outcomes: list = []

    def worker(plate: str):
        with session_factory() as s:
            entry = EntryService(s, scope(tenant))
            try:
                barrier.wait()
                entry.create_entry(
                    site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate=plate, vehicle_type="CAR"
                )
                s.commit()
                outcomes.append("ok")
            except ParkingError as exc:
                outcomes.append(exc.code)
            except Exception as exc:  # pragma: no cover
                outcomes.append(f"unexpected:{type(exc).__name__}")

    t1 = threading.Thread(target=worker, args=("B1234ABC",))
    t2 = threading.Thread(target=worker, args=("B 1234 ABC",))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert outcomes.count("ok") == 1
    assert outcomes.count(ErrorCode.ACTIVE_SESSION_ALREADY_EXISTS) == 1

    active = SessionService(db, scope(tenant)).list_active(site.id)
    assert len(active) == 1


def test_reentry_allowed_after_close(db):
    """A vehicle can visit many times; the plate is not globally unique forever."""
    tenant, site, gate, lane, exit_gate, exit_lane = _make_site(db)
    service = EntryService(db, scope(tenant))
    s1 = service.create_entry(site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate="B1234ABC", vehicle_type="CAR")
    svc = SessionService(db, scope(tenant))
    svc.cancel(s1.public_reference)
    s2 = service.create_entry(site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate="b1234abc", vehicle_type="CAR")
    assert s2.public_reference != s1.public_reference
    assert s2.plate_normalized == "B1234ABC"


def test_cross_tenant_session_blocked(db):
    tenant_a, site_a, gate_a, lane_a, _, _ = _make_site(db)
    tenant_b = new_tenant(db, code="TB")
    session = EntryService(db, scope(tenant_a)).create_entry(
        site_id=site_a.id, gate_id=gate_a.id, lane_id=lane_a.id, plate="B1234ABC", vehicle_type="CAR"
    )
    # Foreign tenant cannot read the session (404, no existence leak).
    with pytest.raises(ParkingError) as exc:
        SessionService(db, scope(tenant_b)).get(session.public_reference)
    assert exc.value.code == ErrorCode.SESSION_NOT_FOUND and exc.value.status == 404
    # Foreign tenant cannot create an entry at tenant A's site.
    with pytest.raises(ParkingError) as exc2:
        EntryService(db, scope(tenant_b)).create_entry(
            site_id=site_a.id, gate_id=gate_a.id, lane_id=lane_a.id, plate="B9999ZZ", vehicle_type="CAR"
        )
    assert exc2.value.code == ErrorCode.PARKING_SITE_NOT_FOUND


def test_invalid_state_transition_rejected(db):
    tenant, site, gate, lane, _, _ = _make_site(db)
    svc = SessionService(db, scope(tenant))
    s1 = EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate="B1234ABC", vehicle_type="CAR"
    )
    # PARKED -> PAID is a jump: must go through PAYMENT_PENDING.
    with pytest.raises(ParkingError) as exc:
        svc.confirm_payment(s1.public_reference)
    assert exc.value.code == ErrorCode.INVALID_SESSION_STATE
    # PARKED -> EXIT_AUTHORIZED is a jump.
    with pytest.raises(ParkingError) as exc2:
        svc.authorize_exit(s1.public_reference)
    assert exc2.value.code == ErrorCode.INVALID_SESSION_STATE
    # Cancelled session cannot be recalculated.
    svc.cancel(s1.public_reference)
    with pytest.raises(ParkingError) as exc3:
        svc.calculate(s1.public_reference)
    assert exc3.value.code == ErrorCode.INVALID_SESSION_STATE


def test_event_ledger(db):
    tenant, site, gate, lane, _, _ = _make_site(db)
    session = EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate="B1234ABC", vehicle_type="CAR"
    )
    events = SessionService(db, scope(tenant)).list_events(session)
    types = [e.event_type for e in events]
    assert EventType.SESSION_CREATED.value in types
    assert EventType.VEHICLE_ENTERED.value in types
    assert types.count(EventType.STATE_CHANGED.value) == 2  # CREATED->ENTERED->PARKED
    assert all(e.tenant_id == tenant.id for e in events)
    assert all(e.session_id == session.id for e in events)


def test_audit_log_written_for_manual_actions(db):
    from parking.models import ParkingAuditLog
    from parking.repositories.tariff_repo import TariffPlanRepository

    tenant, site, gate, lane, _, _ = _make_site(db)
    TariffPlanRepository(db, tenant.id).create(site_id=site.id, code="P1", name="P1")
    session = EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate="B1234ABC", vehicle_type="CAR"
    )
    svc = SessionService(db, scope(tenant))
    svc.cancel(session.public_reference)
    audit = db.query(ParkingAuditLog).filter_by(tenant_id=tenant.id).all()
    assert len(audit) >= 1
    assert audit[0].object_type == "parking_session"
    assert audit[0].object_id == session.public_reference
