"""M10 acceptance: dashboard aggregates, occupancy, gate/device status, role
permissions, viewer read-only, ANPR review, cash confirmation, complimentary
reason, no arbitrary state patch."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from parking.api.app import create_app
from parking.ops.dashboard import DashboardService
from parking.repositories.registry import OperatorRepository, SiteRepository
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
    site.capacity_total = 100
    site.capacity_car = 80
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    db.commit()
    return tenant, site, gate, lane


def _entry(db, tenant, site, gate, lane, plate="B1234ABC"):
    return EntryService(db, scope(tenant)).create_entry(
        site_id=site.id, gate_id=gate.id, lane_id=lane.id, plate=plate, vehicle_type="CAR", entry_at=hours_ago(1)
    )


def test_dashboard_aggregate_correctness(db):
    tenant, site, gate, lane = _site(db)
    _entry(db, tenant, site, gate, lane, plate="B1234ABC")
    _entry(db, tenant, site, gate, lane, plate="B9999ZZ")
    db.commit()
    summary = DashboardService(db, scope(tenant)).site_summary(site.id)
    assert summary["occupancy"]["active"] == 2
    assert summary["occupancy"]["capacity_total"] == 100
    assert summary["occupancy"]["available_total"] == 98
    assert summary["entries_today"] == 2


def test_occupancy_derived_from_active_sessions(db):
    tenant, site, gate, lane = _site(db)
    s1 = _entry(db, tenant, site, gate, lane, plate="B1234ABC")
    _entry(db, tenant, site, gate, lane, plate="B9999ZZ")
    db.commit()
    # Close one session -> occupancy drops.
    SessionService(db, scope(tenant)).cancel(s1.public_reference)
    db.commit()
    summary = DashboardService(db, scope(tenant)).site_summary(site.id)
    assert summary["occupancy"]["active"] == 1


def test_gate_device_status(db):
    tenant, site, gate, lane = _site(db)
    from parking.gate.runtime_repo import GateRuntimeRepository
    GateRuntimeRepository(db, tenant.id).set_state(site_id=site.id, gate_id=gate.id, state="ONLINE", actor="operator:test")
    db.commit()
    summary = DashboardService(db, scope(tenant)).site_summary(site.id)
    assert summary["gate_status"][0]["runtime_state"] == "ONLINE"


def test_operator_role_permissions(db):
    tenant, site, gate, lane = _site(db)
    # OPERATOR can view dashboard.
    summary = DashboardService(db, scope(tenant)).site_summary(site.id)
    assert summary["site_id"] == site.id


def test_viewer_cannot_mutate(db):
    from parking.services.auth import require_role, Scope
    viewer = Scope(tenant_id=1, actor="operator:viewer", role="VIEWER")
    with pytest.raises(Exception):
        require_role(viewer, "OPERATOR")


def test_anpr_manual_correction_api(db):
    from parking.anpr.service import AnprService
    tenant, site, gate, lane = _site(db)
    svc = AnprService(db, scope(tenant))
    svc.process({
        "event_id": "evt-review", "tenant_id": tenant.id, "site_id": site.id,
        "gate_id": gate.id, "lane_id": lane.id, "captured_at": hours_ago(1).isoformat(),
        "plate_raw": "B1234ABC", "confidence": 0.70, "vehicle_type_guess": "CAR", "direction": "ENTRY",
    })
    db.commit()
    review = svc.list_review(site_id=site.id)
    assert len(review) == 1
    assert review[0]["plate_normalized"] == "B1234ABC"
    corrected = svc.correct_plate("evt-review", corrected_plate="B1234ABD", actor="operator:op1", reason="misread")
    assert corrected.plate_normalized == "B1234ABD"


def test_cash_confirmation_uses_backend_command(db):
    from parking.exit.runtime import ExitRuntimeService
    from parking.payment.service import PaymentService
    from parking.domain.enums import PaymentMethod, PaymentEntityState
    tenant, site, gate, lane = _site(db)
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(site_id=site.id, code="P1", name="P1")
    repo.add_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 5000})
    db.commit()
    session = _entry(db, tenant, site, gate, lane)
    ExitRuntimeService(db, scope(tenant)).create_exit_quote(session.public_reference)
    db.commit()
    svc = PaymentService(db, scope(tenant))
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.CASH.value, idempotency_key="cash-m10")
    paid = svc.confirm_cash(created.payment.public_reference)
    assert paid.payment.state == PaymentEntityState.PAID.value


def test_complimentary_requires_reason(db):
    from parking.exit.runtime import ExitRuntimeService
    from parking.payment.service import PaymentService
    from parking.domain.enums import PaymentMethod
    tenant, site, gate, lane = _site(db)
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(site_id=site.id, code="P1", name="P1")
    repo.add_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 5000})
    db.commit()
    session = _entry(db, tenant, site, gate, lane)
    ExitRuntimeService(db, scope(tenant)).create_exit_quote(session.public_reference)
    db.commit()
    svc = PaymentService(db, scope(tenant))
    created = svc.create_payment(session_reference=session.public_reference,
                                 method=PaymentMethod.COMPLIMENTARY.value, idempotency_key="comp-m10")
    # Reason is required by the domain command signature.
    with pytest.raises(TypeError):
        svc.apply_complimentary(created.payment.public_reference)


def test_no_arbitrary_state_patch(db):
    from fastapi.testclient import TestClient
    from parking.api.app import create_app
    tenant, site, gate, lane = _site(db)
    operator = new_operator(db, tenant, username="op1", token="op-token")
    db.commit()
    app = create_app()
    with TestClient(app) as client:
        resp = client.patch(
            f"/parking/api/sessions/whatever",
            json={"state": "CLOSED"},
            headers={"Authorization": "Bearer op-token"},
        )
        assert resp.status_code == 405  # no generic PATCH


def test_liveness_readiness(db):
    from fastapi.testclient import TestClient
    from parking.api.app import create_app
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/parking/api/liveness").status_code == 200
        assert client.get("/parking/api/readiness").status_code == 200
