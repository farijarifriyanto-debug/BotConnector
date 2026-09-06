"""M3 acceptance: flat/hourly/progressive tariffs, grace, daily max,
lost ticket, complimentary, money precision, snapshot stability, determinism."""

from __future__ import annotations

import pytest

from parking.domain.errors import ErrorCode, ParkingError
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
    return tenant, site, gate, lane


def _entry(db, tenant, site, gate, lane, plate="B1234ABC", vehicle_type="CAR", entry_at=None):
    return EntryService(db, scope(tenant)).create_entry(
        site_id=site.id,
        gate_id=gate.id,
        lane_id=lane.id,
        plate=plate,
        vehicle_type=vehicle_type,
        entry_at=entry_at or hours_ago(2),
    )


def _plan(db, tenant, site, *, vehicle_type="CAR", rules, grace=0, daily_max=None, code="P1"):
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(
        site_id=site.id, code=code, name=code, grace_period_minutes=grace, daily_max_amount=daily_max
    )
    for rule_type, config in rules:
        repo.add_rule(plan_id=plan.id, vehicle_type=vehicle_type, rule_type=rule_type, config=config)
    return plan


def test_flat_tariff(db):
    tenant, site, gate, lane = _site(db)
    _plan(db, tenant, site, rules=[("FLAT", {"amount": 5000})])
    session = _entry(db, tenant, site, gate, lane)
    result = SessionService(db, scope(tenant)).calculate(session.public_reference)
    assert result["amount"] == 5000
    assert result["duration_minutes"] == 120
    assert result["currency"] == "IDR"


def test_hourly_first_hour_then_each_hour(db):
    """Spec example: first hour 5000, additional started hour 3000; 1h20m -> 8000."""
    tenant, site, gate, lane = _site(db)
    _plan(
        db,
        tenant,
        site,
        rules=[
            (
                "HOURLY",
                {
                    "mode": "FIRST_HOUR_THEN_EACH_HOUR",
                    "first_hour_amount": 5000,
                    "additional_hour_amount": 3000,
                    "first_hour_minutes": 60,
                    "rounding": "CEIL",
                },
            )
        ],
    )
    entry_at = hours_ago(4 / 3)  # ~80 minutes
    session = _entry(db, tenant, site, gate, lane, entry_at=entry_at)
    result = SessionService(db, scope(tenant)).calculate(session.public_reference)
    assert result["duration_minutes"] == 80
    assert result["amount"] == 8000


def test_hourly_per_started_hour(db):
    tenant, site, gate, lane = _site(db)
    _plan(
        db,
        tenant,
        site,
        rules=[("HOURLY", {"mode": "PER_STARTED_HOUR", "amount": 3000, "rounding": "CEIL"})],
    )
    session = _entry(db, tenant, site, gate, lane, entry_at=hours_ago(1.3333333))  # 80 min -> 2 started hours
    result = SessionService(db, scope(tenant)).calculate(session.public_reference)
    assert result["amount"] == 6000


def test_progressive_tariff(db):
    """Tiers: 0-1h fixed 5000; >1-3h 3000/started hour; >3h 5000/started hour."""
    tenant, site, gate, lane = _site(db)
    _plan(
        db,
        tenant,
        site,
        rules=[
            (
                "PROGRESSIVE",
                {
                    "rounding": "CEIL",
                    "tiers": [
                        {"lower_minutes": 0, "upper_minutes": 60, "amount": 5000, "mode": "FIXED"},
                        {"lower_minutes": 60, "upper_minutes": 180, "amount": 3000, "mode": "PER_STARTED_HOUR"},
                        {"lower_minutes": 180, "upper_minutes": None, "amount": 5000, "mode": "PER_STARTED_HOUR"},
                    ],
                },
            )
        ],
    )
    svc = SessionService(db, scope(tenant))
    s45 = _entry(db, tenant, site, gate, lane, plate="A1", entry_at=hours_ago(0.75))  # 45 min
    assert svc.calculate(s45.public_reference)["amount"] == 5000
    s80 = _entry(db, tenant, site, gate, lane, plate="A2", entry_at=hours_ago(4 / 3))  # 80 min
    assert svc.calculate(s80.public_reference)["amount"] == 8000
    s200 = _entry(db, tenant, site, gate, lane, plate="A3", entry_at=hours_ago(10 / 3))  # 200 min
    assert svc.calculate(s200.public_reference)["amount"] == 16000


def test_grace_period(db):
    tenant, site, gate, lane = _site(db)
    _plan(db, tenant, site, rules=[("FLAT", {"amount": 5000})], grace=10)
    svc = SessionService(db, scope(tenant))
    inside = _entry(db, tenant, site, gate, lane, plate="G1", entry_at=hours_ago(5 / 60))  # 5 min
    assert svc.calculate(inside.public_reference)["amount"] == 0
    outside = _entry(db, tenant, site, gate, lane, plate="G2", entry_at=hours_ago(11 / 60))  # 11 min
    assert svc.calculate(outside.public_reference)["amount"] == 5000


def test_daily_maximum(db):
    tenant, site, gate, lane = _site(db)
    _plan(
        db,
        tenant,
        site,
        rules=[
            (
                "HOURLY",
                {"mode": "FIRST_HOUR_THEN_EACH_HOUR", "first_hour_amount": 5000, "additional_hour_amount": 3000},
            )
        ],
        daily_max=7000,
    )
    session = _entry(db, tenant, site, gate, lane, entry_at=hours_ago(5))  # 5000 + 4*3000 = 17000 -> capped 7000
    result = SessionService(db, scope(tenant)).calculate(session.public_reference)
    assert result["amount"] == 7000
    labels = [b["label"] for b in result["breakdown"]]
    assert "daily_maximum" in labels


def test_lost_ticket(db):
    tenant, site, gate, lane = _site(db)
    _plan(db, tenant, site, rules=[("FLAT", {"amount": 5000}), ("LOST_TICKET_FEE", {"amount": 20000})])
    session = _entry(db, tenant, site, gate, lane)
    svc = SessionService(db, scope(tenant))
    svc.calculate(session.public_reference)
    lost = svc.declare_lost_ticket(session.public_reference, reason="ticket lost by customer")
    assert lost.lost_ticket is True
    assert lost.state == "LOST_TICKET"
    assert lost.calculated_amount == 20000
    snapshot = lost.tariff_snapshot
    assert snapshot["lost_ticket"]["original_amount"] == 5000
    assert snapshot["lost_ticket"]["fee"] == 20000
    assert snapshot["lost_ticket"]["final_amount"] == 20000
    # Complete the lost-ticket flow through payment.
    svc.initiate_payment(session.public_reference)
    paid = svc.confirm_payment(session.public_reference)
    assert paid.paid_amount == 20000 and paid.payment_state == "PAID"


def test_lost_ticket_without_fee_rule_rejected(db):
    tenant, site, gate, lane = _site(db)
    _plan(db, tenant, site, rules=[("FLAT", {"amount": 5000})])
    session = _entry(db, tenant, site, gate, lane)
    with pytest.raises(ParkingError) as exc:
        SessionService(db, scope(tenant)).declare_lost_ticket(session.public_reference)
    assert exc.value.code == ErrorCode.LOST_TICKET_FEE_NOT_CONFIGURED


def test_complimentary(db):
    tenant, site, gate, lane = _site(db)
    _plan(db, tenant, site, rules=[("FLAT", {"amount": 5000})])
    session = _entry(db, tenant, site, gate, lane)
    svc = SessionService(db, scope(tenant))
    svc.calculate(session.public_reference)
    comp = svc.apply_complimentary(session.public_reference, reason="guest of management")
    assert comp.payment_state == "COMPLIMENTARY"
    assert comp.state == "PAID"
    assert comp.calculated_amount == 5000
    assert comp.tariff_snapshot["complimentary"]["final_amount"] == 0
    assert comp.tariff_snapshot["complimentary"]["original_amount"] == 5000


def test_money_precision(db):
    tenant, site, gate, lane = _site(db)
    _plan(
        db,
        tenant,
        site,
        rules=[
            (
                "HOURLY",
                {"mode": "FIRST_HOUR_THEN_EACH_HOUR", "first_hour_amount": 5000, "additional_hour_amount": 3000},
            )
        ],
        daily_max=7000,
    )
    session = _entry(db, tenant, site, gate, lane, entry_at=hours_ago(5))
    result = SessionService(db, scope(tenant)).calculate(session.public_reference)
    assert isinstance(result["amount"], int) and not isinstance(result["amount"], bool)
    assert isinstance(result["amount"], int) and not isinstance(result["amount"], float)
    for item in result["breakdown"]:
        assert isinstance(item["amount"], int) and not isinstance(item["amount"], float)
    assert result["breakdown"][-1]["amount"] == result["amount"]  # final part == capped total


def test_tariff_snapshot_stable_after_plan_edit(db):
    tenant, site, gate, lane = _site(db)
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(site_id=site.id, code="P1", name="P1")
    repo.add_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 5000})
    session = _entry(db, tenant, site, gate, lane)
    at = utcnow()
    svc = SessionService(db, scope(tenant))
    first = svc.calculate(session.public_reference, calculation_at=at)
    assert first["amount"] == 5000
    assert first["plan"]["version"] == 1

    # Admin edits today's plan: amount 5000 -> 10000 (version 2).
    repo.update_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 10000})
    db.commit()
    assert repo.get(plan.id).version == 2

    # Historical session recalculated at the SAME time keeps the old amount.
    second = svc.calculate(session.public_reference, calculation_at=at)
    assert second["amount"] == 5000
    assert second["plan"]["version"] == 1


def test_tariff_determinism(db):
    tenant, site, gate, lane = _site(db)
    _plan(
        db,
        tenant,
        site,
        rules=[
            (
                "HOURLY",
                {"mode": "FIRST_HOUR_THEN_EACH_HOUR", "first_hour_amount": 5000, "additional_hour_amount": 3000},
            )
        ],
    )
    session = _entry(db, tenant, site, gate, lane)
    at = utcnow()
    svc = SessionService(db, scope(tenant))
    r1 = svc.calculate(session.public_reference, calculation_at=at)
    r2 = svc.calculate(session.public_reference, calculation_at=at)
    assert r1["amount"] == r2["amount"]
    assert r1["breakdown"] == r2["breakdown"]


def test_progressive_config_validation(db):
    tenant, site, gate, lane = _site(db)
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(site_id=site.id, code="P1", name="P1")
    with pytest.raises(ParkingError) as exc:
        repo.add_rule(
            plan_id=plan.id,
            vehicle_type="CAR",
            rule_type="PROGRESSIVE",
            config={
                "tiers": [
                    {"lower_minutes": 0, "upper_minutes": 60, "amount": 5000},
                    {"lower_minutes": 90, "upper_minutes": 180, "amount": 3000},  # gap
                ]
            },
        )
    assert exc.value.code == ErrorCode.TARIFF_CONFIGURATION_INVALID
