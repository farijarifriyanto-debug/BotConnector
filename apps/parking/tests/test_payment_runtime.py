"""M6 acceptance: cash, complimentary, simulated QRIS MPM/CPM, callback security,
idempotency, double-payment guard, payment-to-exit transactionality, cross-tenant."""

from __future__ import annotations

import pytest

from parking.domain.enums import PaymentEntityState, PaymentMethod, PaymentState, SessionState
from parking.domain.errors import ErrorCode, ParkingError
from parking.exit.runtime import ExitRuntimeService
from parking.payment.service import PaymentService
from parking.payment.simulator import SimulatedPaymentAdapter
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.entry import EntryService

from tests.helpers import (
    hours_ago,
    new_gate,
    new_lane,
    new_site,
    new_tenant,
    scope,
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


def _quoted(db, tenant, site, gate, lane):
    session = _entry(db, tenant, site, gate, lane)
    quote = ExitRuntimeService(db, scope(tenant)).create_exit_quote(session.public_reference)
    return session, quote


def test_cash_payment(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    svc = PaymentService(db, scope(tenant))
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.CASH.value, idempotency_key="cash-1")
    assert created.payment.method == "CASH"
    assert created.payment.expected_amount == 5000
    paid = svc.confirm_cash(created.payment.public_reference)
    assert paid.payment.state == PaymentEntityState.PAID.value
    assert session.payment_state == PaymentState.PAID.value
    assert session.paid_amount == 5000


def test_complimentary_settlement(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    svc = PaymentService(db, scope(tenant))
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.COMPLIMENTARY.value, idempotency_key="comp-1")
    paid = svc.apply_complimentary(created.payment.public_reference, reason="guest of management")
    assert paid.payment.state == PaymentEntityState.PAID.value
    assert session.payment_state == PaymentState.COMPLIMENTARY.value
    assert session.paid_amount == 0


def test_simulated_qris_mpm_payment(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    adapter = SimulatedPaymentAdapter()
    svc = PaymentService(db, scope(tenant), adapter=adapter)
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.QRIS_MPM_DYNAMIC.value, idempotency_key="qris-1")
    assert created.payment.state == PaymentEntityState.PENDING.value
    assert created.payload.get("qr_payload")
    # Simulate provider confirming payment, then callback.
    adapter.mark_paid(created.provider_reference)
    callback = adapter.make_callback(provider_reference=created.provider_reference, amount=5000)
    result = svc.handle_callback("SIMULATOR", callback)
    assert result.payment.state == PaymentEntityState.PAID.value
    assert session.payment_state == PaymentState.PAID.value


def test_simulated_qris_cpm_contract(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    adapter = SimulatedPaymentAdapter()
    svc = PaymentService(db, scope(tenant), adapter=adapter)
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.QRIS_CPM.value, idempotency_key="cpm-1")
    assert created.payment.method == "QRIS_CPM"
    assert created.payment.state == PaymentEntityState.PENDING.value
    adapter.mark_paid(created.provider_reference)
    callback = adapter.make_callback(provider_reference=created.provider_reference, amount=5000)
    result = svc.handle_callback("SIMULATOR", callback)
    assert result.payment.state == PaymentEntityState.PAID.value


def test_payment_amount_mismatch_blocked(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    adapter = SimulatedPaymentAdapter()
    svc = PaymentService(db, scope(tenant), adapter=adapter)
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.QRIS_MPM_DYNAMIC.value, idempotency_key="qris-2")
    adapter.mark_paid(created.provider_reference)
    callback = adapter.make_callback(provider_reference=created.provider_reference, amount=9999)
    with pytest.raises(ParkingError) as exc:
        svc.handle_callback("SIMULATOR", callback)
    assert exc.value.code == ErrorCode.PAYMENT_AMOUNT_MISMATCH


def test_invalid_callback_blocked(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    adapter = SimulatedPaymentAdapter()
    svc = PaymentService(db, scope(tenant), adapter=adapter)
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.QRIS_MPM_DYNAMIC.value, idempotency_key="qris-3")
    adapter.mark_paid(created.provider_reference)
    # Tampered callback (bad signature).
    bad = adapter.make_callback(provider_reference=created.provider_reference, amount=5000, tamper=True)
    with pytest.raises(ParkingError) as exc:
        svc.handle_callback("SIMULATOR", bad)
    assert exc.value.code == ErrorCode.PAYMENT_CALLBACK_INVALID


def test_duplicate_callback_idempotent(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    adapter = SimulatedPaymentAdapter()
    svc = PaymentService(db, scope(tenant), adapter=adapter)
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.QRIS_MPM_DYNAMIC.value, idempotency_key="qris-4")
    adapter.mark_paid(created.provider_reference)
    callback = adapter.make_callback(provider_reference=created.provider_reference, amount=5000)
    first = svc.handle_callback("SIMULATOR", callback)
    second = svc.handle_callback("SIMULATOR", callback)
    assert first.payment.state == PaymentEntityState.PAID.value
    assert second.payment.state == PaymentEntityState.PAID.value
    assert first.payment.id == second.payment.id


def test_callback_replay_safely_ignored(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    adapter = SimulatedPaymentAdapter()
    svc = PaymentService(db, scope(tenant), adapter=adapter)
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.QRIS_MPM_DYNAMIC.value, idempotency_key="qris-5")
    adapter.mark_paid(created.provider_reference)
    callback = adapter.make_callback(provider_reference=created.provider_reference, amount=5000)
    svc.handle_callback("SIMULATOR", callback)
    # Replay after already PAID -> safe no-op, no double settlement.
    again = svc.handle_callback("SIMULATOR", callback)
    assert again.payment.state == PaymentEntityState.PAID.value
    assert session.paid_amount == 5000


def test_double_payment_prevented(db):
    tenant, site, gate, lane, _, _ = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    svc = PaymentService(db, scope(tenant))
    p1 = svc.create_payment(session_reference=session.public_reference,
                            method=PaymentMethod.CASH.value, idempotency_key="cash-2")
    svc.confirm_cash(p1.payment.public_reference)
    # A second, different payment attempt must not settle again.
    with pytest.raises(ParkingError) as exc:
        svc.create_payment(session_reference=session.public_reference,
                           method=PaymentMethod.CASH.value, idempotency_key="cash-3")
    assert exc.value.code == ErrorCode.PAYMENT_ALREADY_SETTLED


def test_payment_to_exit_transactional_flow(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    session, quote = _quoted(db, tenant, site, gate, lane)
    svc = PaymentService(db, scope(tenant))
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.CASH.value, idempotency_key="cash-4")
    svc.confirm_cash(created.payment.public_reference)
    # Payment settled -> exit can be authorized -> completed -> closed.
    exit_svc = ExitRuntimeService(db, scope(tenant))
    decision = exit_svc.exit_decision(session.public_reference)
    assert decision.allowed is True
    authorized = exit_svc.authorize_exit(session.public_reference)
    assert authorized.state == SessionState.EXIT_AUTHORIZED.value
    closed = exit_svc.record_vehicle_exited(
        session.public_reference, exit_gate_id=exit_gate.id, exit_lane_id=exit_lane.id
    )
    assert closed.state == SessionState.CLOSED.value


def test_foreign_tenant_payment_blocked(db):
    tenant_a, site_a, gate_a, lane_a, _, _ = _site(db)
    _plan(db, tenant_a, site_a)
    session, quote = _quoted(db, tenant_a, site_a, gate_a, lane_a)
    tenant_b = new_tenant(db, code="TB")
    with pytest.raises(ParkingError) as exc:
        PaymentService(db, scope(tenant_b)).create_payment(
            session_reference=session.public_reference,
            method=PaymentMethod.CASH.value, idempotency_key="cash-x",
        )
    assert exc.value.code == ErrorCode.SESSION_NOT_FOUND
    assert exc.value.status == 404
