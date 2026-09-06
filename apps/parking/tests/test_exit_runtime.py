"""M5 acceptance: exit quote, expiry, payment-required flow, authorization,
completion, idempotency, cross-tenant blocking."""

from __future__ import annotations

from datetime import timedelta

import pytest

from parking.domain.enums import PaymentState, SessionState
from parking.domain.errors import ErrorCode, ParkingError
from parking.exit.runtime import ExitRuntimeService
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.entry import EntryService
from parking.services.session_service import SessionService

from tests.helpers import (
    hours_ago,
    new_gate,
    new_lane,
    new_site,
    new_tenant,
    scope,
    utcnow,
)


def _site(db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    exit_gate = new_gate(db, tenant, site, code="G-EXIT", direction="EXIT")
    exit_lane = new_lane(db, tenant, site, exit_gate, code="L-EXIT", direction="EXIT")
    return tenant, site, gate, lane, exit_gate, exit_lane


def _entry(db, tenant, site, gate, lane, plate="B1234ABC"):
    return EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate=plate, vehicle_type="CAR", entry_at=hours_ago(2)
    )


def _plan(db, tenant, site):
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(site_id=site.id, code="P1", name="P1")
    repo.add_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 5000})
    db.commit()
    return plan


def _pay(db, tenant, session):
    svc = SessionService(db, scope(tenant))
    svc.calculate(session.public_reference)
    svc.initiate_payment(session.public_reference)
    svc.confirm_payment(session.public_reference)


def test_active_session_creates_exit_quote(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session = _entry(db, tenant, site, gate, lane)
    result = ExitRuntimeService(db, scope(tenant)).create_exit_quote(session.public_reference)
    assert result.quote is not None
    assert result.quote.session_id == session.id
    assert result.quote.status == "ACTIVE"
    assert result.amount == 5000


def test_quote_amount_from_tariff_engine(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session = _entry(db, tenant, site, gate, lane)
    result = ExitRuntimeService(db, scope(tenant)).create_exit_quote(session.public_reference)
    assert result.amount == 5000
    assert result.currency == "IDR"
    assert result.quote.tariff_version == 1


def test_quote_expiry_causes_recalculation(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session = _entry(db, tenant, site, gate, lane)
    svc = ExitRuntimeService(db, scope(tenant))
    now = utcnow()
    first = svc.create_exit_quote(session.public_reference, now=now)
    # Expire the quote by advancing time past TTL.
    later = now + timedelta(minutes=10)
    with pytest.raises(ParkingError) as exc:
        svc.exit_decision(session.public_reference, now=later)
    assert exc.value.code == ErrorCode.QUOTE_EXPIRED
    # Recalculate issues a new quote.
    second = svc.create_exit_quote(session.public_reference, now=later)
    assert second.quote.public_reference != first.quote.public_reference
    assert second.quote.status == "ACTIVE"


def test_unpaid_exit_returns_payment_required(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session = _entry(db, tenant, site, gate, lane)
    svc = ExitRuntimeService(db, scope(tenant))
    svc.create_exit_quote(session.public_reference)
    decision = svc.exit_decision(session.public_reference)
    assert decision.allowed is False
    assert decision.reason == "PAYMENT_REQUIRED"
    assert decision.barrier_action == "KEEP_CLOSED"


def test_paid_session_becomes_exit_authorized(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session = _entry(db, tenant, site, gate, lane)
    _pay(db, tenant, session)
    svc = ExitRuntimeService(db, scope(tenant))
    decision = svc.exit_decision(session.public_reference)
    assert decision.allowed is True
    assert decision.reason == "PAYMENT_SATISFIED"
    authorized = svc.authorize_exit(session.public_reference)
    assert authorized.state == SessionState.EXIT_AUTHORIZED.value


def test_exit_completion_closes_session(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    session = _entry(db, tenant, site, gate, lane)
    _pay(db, tenant, session)
    svc = ExitRuntimeService(db, scope(tenant))
    svc.authorize_exit(session.public_reference)
    closed = svc.record_vehicle_exited(
        session.public_reference, exit_gate_id=exit_gate.id, exit_lane_id=exit_lane.id
    )
    assert closed.state == SessionState.CLOSED.value
    assert closed.exit_gate_id == exit_gate.id
    assert closed.exit_lane_id == exit_lane.id
    assert closed.exit_at is not None


def test_repeated_exit_completion_idempotent(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    session = _entry(db, tenant, site, gate, lane)
    _pay(db, tenant, session)
    svc = ExitRuntimeService(db, scope(tenant))
    svc.authorize_exit(session.public_reference)
    first = svc.record_vehicle_exited(session.public_reference, exit_gate_id=exit_gate.id, exit_lane_id=exit_lane.id)
    second = svc.record_vehicle_exited(session.public_reference, exit_gate_id=exit_gate.id, exit_lane_id=exit_lane.id)
    assert first.state == SessionState.CLOSED.value
    assert second.state == SessionState.CLOSED.value
    assert first.id == second.id


def test_foreign_tenant_exit_blocked(db):
    tenant_a, site_a, gate_a, lane_a, _, _ = _site(db)
    _plan(db, tenant_a, site_a)
    session = _entry(db, tenant_a, site_a, gate_a, lane_a)
    tenant_b = new_tenant(db, code="TB")
    with pytest.raises(ParkingError) as exc:
        ExitRuntimeService(db, scope(tenant_b)).create_exit_quote(session.public_reference)
    assert exc.value.code == ErrorCode.SESSION_NOT_FOUND
    assert exc.value.status == 404
