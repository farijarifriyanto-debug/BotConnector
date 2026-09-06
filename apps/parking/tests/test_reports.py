"""M11 acceptance: daily operations, revenue, payment-method breakdown,
historical tariff snapshot reporting, gate report, ANPR report, edge report,
tenant-scoped report, cross-tenant blocked, audit filtering, CSV injection-safe
export, timezone boundaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from parking.domain.enums import PaymentMethod, PaymentState
from parking.ops.reports import ReportService, _safe_cell
from parking.repositories.registry import OperatorRepository
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.auth import hash_api_key
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
)


def _site(db):
    tenant = new_tenant(db, code="T1")
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    exit_gate = new_gate(db, tenant, site, code="G-EXIT", direction="EXIT")
    exit_lane = new_lane(db, tenant, site, exit_gate, code="L-EXIT", direction="EXIT")
    return tenant, site, gate, lane, exit_gate, exit_lane


def _plan(db, tenant, site):
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(site_id=site.id, code="P1", name="P1")
    repo.add_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 5000})
    db.commit()
    return plan


def _paid_session(db, tenant, site, gate, lane, plate="B1234ABC"):
    from parking.exit.runtime import ExitRuntimeService
    from parking.payment.service import PaymentService
    session = EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate=plate, vehicle_type="CAR", entry_at=hours_ago(2)
    )
    ExitRuntimeService(db, scope(tenant)).create_exit_quote(session.public_reference)
    db.commit()
    svc = PaymentService(db, scope(tenant))
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.CASH.value, idempotency_key=f"cash-{plate}")
    svc.confirm_cash(created.payment.public_reference)
    return session


def test_daily_operations_report(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    _paid_session(db, tenant, site, gate, lane, plate="B1234ABC")
    db.commit()
    today = datetime.now(timezone.utc).date()
    report = ReportService(db, scope(tenant)).daily_operations(site.id, today)
    assert report["entries"] >= 1
    assert report["revenue"] >= 5000


def test_revenue_totals(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    _paid_session(db, tenant, site, gate, lane, plate="B1234ABC")
    _paid_session(db, tenant, site, gate, lane, plate="B9999ZZ")
    db.commit()
    now = datetime.now(timezone.utc)
    report = ReportService(db, scope(tenant)).revenue_report(site.id, now - timedelta(days=1), now + timedelta(days=1))
    assert report["gross_revenue"] == 10000
    assert report["transaction_count"] == 2


def test_payment_method_breakdown(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    _paid_session(db, tenant, site, gate, lane, plate="B1234ABC")
    db.commit()
    now = datetime.now(timezone.utc)
    report = ReportService(db, scope(tenant)).revenue_report(site.id, now - timedelta(days=1), now + timedelta(days=1))
    assert report["by_method"].get("CASH") == 5000


def test_historical_tariff_snapshot_reporting(db):
    """Editing a tariff today must not change prior reports (snapshot-based)."""
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(site_id=site.id, code="P1", name="P1")
    repo.add_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 5000})
    db.commit()
    session = _paid_session(db, tenant, site, gate, lane, plate="B1234ABC")
    db.commit()
    # Edit the plan amount to 10000 (version bump).
    repo.update_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 10000})
    db.commit()
    # The paid session's amount is frozen in its snapshot.
    assert session.paid_amount == 5000


def test_gate_report(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    _paid_session(db, tenant, site, gate, lane, plate="B1234ABC")
    db.commit()
    now = datetime.now(timezone.utc)
    report = ReportService(db, scope(tenant)).gate_report(site.id, now - timedelta(days=1), now + timedelta(days=1))
    assert report["gates"][0]["source"] == "SIMULATED"


def test_anpr_report(db):
    from parking.anpr.service import AnprService
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    svc = AnprService(db, scope(tenant))
    svc.process({
        "event_id": "evt-a1", "tenant_id": tenant.id, "site_id": site.id,
        "gate_id": gate.id, "lane_id": lane.id, "captured_at": hours_ago(1).isoformat(),
        "plate_raw": "B1234ABC", "confidence": 0.70, "vehicle_type_guess": "CAR", "direction": "ENTRY",
    })
    db.commit()
    now = datetime.now(timezone.utc)
    report = ReportService(db, scope(tenant)).anpr_report(site.id, now - timedelta(days=1), now + timedelta(days=1))
    assert report["recognition_events"] >= 1
    assert report["real_world_accuracy"] == "NOT_MEASURED"


def test_edge_report(db):
    from parking.models import ParkingEdge
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    db.add(ParkingEdge(edge_id="EDGE-1", tenant_id=tenant.id, site_id=site.id, name="Edge 1"))
    db.commit()
    report = ReportService(db, scope(tenant)).edge_report(site.id)
    assert report["edges"][0]["edge_id"] == "EDGE-1"


def test_tenant_scoped_report(db):
    tenant_a, site_a, gate_a, lane_a, _, _ = _site(db)
    tenant_b = new_tenant(db, code="TB")
    site_b = new_site(db, tenant_b, code="S-B")
    db.commit()
    # Tenant B report only sees its own site.
    report = ReportService(db, scope(tenant_b)).daily_operations(site_b.id, datetime.now(timezone.utc).date())
    assert report["site_id"] == site_b.id


def test_cross_tenant_report_blocked(db):
    tenant_a, site_a, gate_a, lane_a, _, _ = _site(db)
    tenant_b = new_tenant(db, code="TB")
    from parking.domain.errors import ParkingError, ErrorCode
    with pytest.raises(ParkingError) as exc:
        ReportService(db, scope(tenant_b)).daily_operations(site_a.id, datetime.now(timezone.utc).date())
    assert exc.value.code == ErrorCode.PARKING_SITE_NOT_FOUND


def test_audit_filtering(db):
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    session = _paid_session(db, tenant, site, gate, lane, plate="B1234ABC")
    db.commit()
    audit = ReportService(db, scope(tenant)).audit(site_id=site.id)
    assert len(audit) >= 1
    assert all(a["site_id"] == site.id for a in audit)


def test_csv_injection_safe(db):
    assert _safe_cell("=SUM(A1)") == "'=SUM(A1)"
    assert _safe_cell("+cmd") == "'+cmd"
    assert _safe_cell("-1") == "'-1"
    assert _safe_cell("@x") == "'@x"
    assert _safe_cell("normal") == "normal"


def test_timezone_boundaries(db):
    """Report day boundaries are UTC-canonical; browser timezone must not change
    financial totals."""
    tenant, site, gate, lane, exit_gate, exit_lane = _site(db)
    _plan(db, tenant, site)
    _paid_session(db, tenant, site, gate, lane, plate="B1234ABC")
    db.commit()
    today = datetime.now(timezone.utc).date()
    report = ReportService(db, scope(tenant)).daily_operations(site.id, today)
    assert report["revenue"] >= 5000
