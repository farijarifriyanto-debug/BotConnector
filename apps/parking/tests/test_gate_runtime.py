"""M4 acceptance: gate runtime admission, idempotency, barrier intent, events."""

from __future__ import annotations

import pytest

from parking.domain.enums import AdmissionDecision, BarrierAction, EventType
from parking.domain.errors import ErrorCode, ParkingError
from parking.gate.barrier import BarrierIntent, SimulatedBarrierIntentConsumer
from parking.gate.runtime import GateRuntimeService
from parking.repositories.registry import GateRepository, LaneRepository, SiteRepository
from parking.repositories.session_repo import SessionRepository
from parking.services.auth import Scope

from tests.helpers import new_gate, new_lane, new_site, new_tenant, scope


def _site(db, *, gate_direction="ENTRY", lane_direction="ENTRY", gate_status="ACTIVE", lane_status="ACTIVE"):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction=gate_direction)
    if gate_status != "ACTIVE":
        gate.status = gate_status
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction=lane_direction)
    if lane_status != "ACTIVE":
        lane.status = lane_status
    db.commit()
    return tenant, site, gate, lane


def _entry(db, tenant, site, gate, lane, *, plate="B1234ABC", key="req-1", vehicle_type="CAR"):
    return GateRuntimeService(db, scope(tenant)).entry_request(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate=plate,
        vehicle_type=vehicle_type, idempotency_key=key,
    )


def test_valid_entry_gate_request_allow(db):
    tenant, site, gate, lane = _site(db)
    result = _entry(db, tenant, site, gate, lane)
    assert result.decision == AdmissionDecision.ALLOW.value
    assert result.reason == "ENTRY_ALLOWED"
    assert result.barrier_action == BarrierAction.OPEN_BARRIER.value
    assert result.session is not None
    assert result.session.state == "PARKED"


def test_exit_only_gate_denies_entry(db):
    tenant, site, gate, lane = _site(db, gate_direction="EXIT", lane_direction="EXIT")
    result = _entry(db, tenant, site, gate, lane)
    assert result.decision == AdmissionDecision.DENY.value
    assert result.reason == "INVALID_DIRECTION"
    assert result.barrier_action == BarrierAction.KEEP_CLOSED.value
    assert result.session is None


def test_inactive_gate_denies(db):
    tenant, site, gate, lane = _site(db, gate_status="INACTIVE")
    result = _entry(db, tenant, site, gate, lane)
    assert result.decision == AdmissionDecision.DENY.value
    assert result.reason == "GATE_INACTIVE"


def test_inactive_lane_denies(db):
    tenant, site, gate, lane = _site(db, lane_status="INACTIVE")
    result = _entry(db, tenant, site, gate, lane)
    assert result.decision == AdmissionDecision.DENY.value
    assert result.reason == "LANE_INACTIVE"


def test_duplicate_request_idempotent(db):
    tenant, site, gate, lane = _site(db)
    first = _entry(db, tenant, site, gate, lane, key="req-dup")
    second = _entry(db, tenant, site, gate, lane, key="req-dup")
    assert first.decision == AdmissionDecision.ALLOW.value
    assert second.decision == AdmissionDecision.ALLOW.value
    assert second.session is None  # replay returns stored result, no new session
    # Only one active session exists.
    active = SessionRepository(db, tenant.id).list_active(site.id)
    assert len(active) == 1


def test_idempotency_conflict_blocked(db):
    tenant, site, gate, lane = _site(db)
    _entry(db, tenant, site, gate, lane, key="req-conflict", plate="B1234ABC")
    with pytest.raises(ParkingError) as exc:
        _entry(db, tenant, site, gate, lane, key="req-conflict", plate="B9999ZZ")
    assert exc.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
    assert exc.value.status == 409


def test_gate_event_ledger(db):
    tenant, site, gate, lane = _site(db)
    result = _entry(db, tenant, site, gate, lane)
    from sqlalchemy import select
    from parking.models import ParkingEvent
    events = list(db.scalars(select(ParkingEvent).where(ParkingEvent.tenant_id == tenant.id)))
    types = [e.event_type for e in events]
    assert EventType.ENTRY_REQUESTED.value in types
    assert EventType.ENTRY_ALLOWED.value in types
    assert EventType.BARRIER_OPEN_INTENT_CREATED.value in types
    assert all(e.tenant_id == tenant.id for e in events)


def test_foreign_tenant_gate_blocked(db):
    tenant_a, site_a, gate_a, lane_a = _site(db)
    tenant_b = new_tenant(db, code="TB")
    # Foreign tenant cannot resolve tenant A's site (404, no existence leak).
    with pytest.raises(ParkingError) as exc:
        GateRuntimeService(db, scope(tenant_b)).entry_request(
            site_id=site_a.id, gate_id=gate_a.id, lane_id=lane_a.id,
            plate="B1234ABC", vehicle_type="CAR", idempotency_key="req-x",
        )
    assert exc.value.code == ErrorCode.PARKING_SITE_NOT_FOUND
    assert exc.value.status == 404


def test_barrier_intent_consumer(db):
    consumer = SimulatedBarrierIntentConsumer()
    tenant, site, gate, lane = _site(db)
    result = _entry(db, tenant, site, gate, lane)
    consumer.consume(BarrierIntent(
        decision=result.decision,
        barrier_action=result.barrier_action,
        reason=result.reason,
        details=result.details,
    ))
    assert consumer.last() is not None
    assert consumer.last().barrier_action == BarrierAction.OPEN_BARRIER.value
