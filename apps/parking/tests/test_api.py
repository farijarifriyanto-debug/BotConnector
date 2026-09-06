"""API smoke tests: route namespace, stable error codes, no generic PATCH,
cross-tenant 404, controlled commands."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from parking.api.app import create_app
from parking.repositories.registry import OperatorRepository, SiteRepository
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.auth import hash_api_key

from tests.helpers import new_gate, new_lane, new_operator, new_site, new_tenant, utcnow


@pytest.fixture(scope="module")
def client(test_url):
    app = create_app(test_url)
    with TestClient(app) as c:
        yield c


def _seed(db, token="admin-token", role="ADMIN"):
    tenant = new_tenant(db, code="T1")
    operator = new_operator(db, tenant, username="admin", token=token, role=role)
    return tenant


def _auth(token="admin-token"):
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    resp = client.get("/parking/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_entry_and_duplicate_via_api(client, db):
    tenant = _seed(db)
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    db.commit()

    body = {
        "site_id": site.id,
        "gate_id": gate.id,
        "lane_id": lane.id,
        "plate": "B1234ABC",
        "vehicle_type": "CAR",
    }
    resp = client.post("/parking/api/sessions/entry", json=body, headers=_auth())
    assert resp.status_code == 201
    data = resp.json()
    assert data["public_reference"].startswith("PK-")
    assert data["state"] == "PARKED"

    dup = client.post("/parking/api/sessions/entry", json=body, headers=_auth())
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "ACTIVE_SESSION_ALREADY_EXISTS"


def test_invalid_gate_direction_via_api(client, db):
    tenant = _seed(db)
    site = new_site(db, tenant, code="S1")
    exit_gate = new_gate(db, tenant, site, code="G-EXIT", direction="EXIT")
    lane = new_lane(db, tenant, site, exit_gate, code="L-EXIT", direction="EXIT")
    db.commit()
    resp = client.post(
        "/parking/api/sessions/entry",
        json={
            "site_id": site.id,
            "gate_id": exit_gate.id,
            "lane_id": lane.id,
            "plate": "B1234ABC",
            "vehicle_type": "CAR",
        },
        headers=_auth(),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_GATE_DIRECTION"


def test_cross_tenant_404_via_api(client, db):
    tenant_a = _seed(db)
    site = new_site(db, tenant_a, code="S1")
    gate = new_gate(db, tenant_a, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant_a, site, gate, code="L-ENTRY", direction="ENTRY")
    db.commit()
    entry = client.post(
        "/parking/api/sessions/entry",
        json={"site_id": site.id, "gate_id": gate.id, "lane_id": lane.id, "plate": "B1234ABC", "vehicle_type": "CAR"},
        headers=_auth(),
    )
    ref = entry.json()["public_reference"]

    tenant_b = new_tenant(db, code="TB")
    new_operator(db, tenant_b, username="intruder", token="intruder-token")
    db.commit()

    resp = client.get(f"/parking/api/sessions/{ref}", headers=_auth("intruder-token"))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_no_generic_patch_endpoint(client, db):
    tenant = _seed(db)
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    db.commit()
    entry = client.post(
        "/parking/api/sessions/entry",
        json={"site_id": site.id, "gate_id": gate.id, "lane_id": lane.id, "plate": "B1234ABC", "vehicle_type": "CAR"},
        headers=_auth(),
    )
    ref = entry.json()["public_reference"]
    resp = client.patch(f"/parking/api/sessions/{ref}", json={"state": "CLOSED"}, headers=_auth())
    assert resp.status_code == 405


def test_full_flow_via_api(client, db):
    tenant = _seed(db)
    site = new_site(db, tenant, code="S1")
    gate = new_gate(db, tenant, site, code="G-ENTRY", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L-ENTRY", direction="ENTRY")
    exit_gate = new_gate(db, tenant, site, code="G-EXIT", direction="EXIT")
    exit_lane = new_lane(db, tenant, site, exit_gate, code="L-EXIT", direction="EXIT")
    repo = TariffPlanRepository(db, tenant.id)
    plan = repo.create(site_id=site.id, code="P1", name="P1")
    repo.add_rule(plan_id=plan.id, vehicle_type="CAR", rule_type="FLAT", config={"amount": 5000})
    db.commit()

    entry_at = (utcnow() - timedelta(hours=2)).isoformat()
    entry = client.post(
        "/parking/api/sessions/entry",
        json={
            "site_id": site.id,
            "gate_id": gate.id,
            "lane_id": lane.id,
            "plate": "B1234ABC",
            "vehicle_type": "CAR",
            "entry_at": entry_at,
        },
        headers=_auth(),
    )
    ref = entry.json()["public_reference"]

    calc = client.post(f"/parking/api/sessions/{ref}/calculate", headers=_auth())
    assert calc.status_code == 200
    assert calc.json()["amount"] == 5000

    pay = client.post(f"/parking/api/sessions/{ref}/initiate-payment", headers=_auth())
    assert pay.json()["state"] == "PAYMENT_PENDING"
    paid = client.post(f"/parking/api/sessions/{ref}/confirm-payment", headers=_auth())
    assert paid.json()["payment_state"] == "PAID"
    auth = client.post(f"/parking/api/sessions/{ref}/authorize-exit", headers=_auth())
    assert auth.json()["state"] == "EXIT_AUTHORIZED"
    exited = client.post(
        f"/parking/api/sessions/{ref}/exit",
        json={"exit_gate_id": exit_gate.id, "exit_lane_id": exit_lane.id},
        headers=_auth(),
    )
    assert exited.json()["state"] == "CLOSED"

    events = client.get(f"/parking/api/sessions/{ref}/events", headers=_auth())
    assert events.status_code == 200
    assert len(events.json()) >= 8


def test_unauthenticated_rejected(client):
    resp = client.post(
        "/parking/api/sessions/entry",
        json={"site_id": 1, "gate_id": 1, "lane_id": 1, "plate": "B1", "vehicle_type": "CAR"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_viewer_mutation_blocked(client, db):
    tenant = new_tenant(db, code="T_VIEW")
    new_operator(db, tenant, username="viewer_user", token="viewer-tok", role="VIEWER")
    site = new_site(db, tenant, code="S_VIEW")
    gate = new_gate(db, tenant, site, code="G1", direction="ENTRY")
    lane = new_lane(db, tenant, site, gate, code="L1", direction="ENTRY")
    db.commit()

    resp = client.post(
        "/parking/api/sessions/entry",
        json={"site_id": site.id, "gate_id": gate.id, "lane_id": lane.id, "plate": "B9999ZZ", "vehicle_type": "CAR"},
        headers=_auth("viewer-tok"),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_operator_admin_mutation_blocked(client, db):
    tenant = new_tenant(db, code="T_OP")
    new_operator(db, tenant, username="op_user", token="op-tok", role="OPERATOR")
    db.commit()

    resp = client.post(
        "/parking/api/sites",
        json={"code": "S_OP", "name": "Site Op"},
        headers=_auth("op-tok"),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_role_escalation_via_api_blocked(client, db):
    tenant = new_tenant(db, code="T_ESC")
    new_operator(db, tenant, username="admin_user", token="admin-tok", role="ADMIN")
    db.commit()

    # ADMIN attempting to create OWNER -> 403
    resp = client.post(
        "/parking/api/operators",
        json={"username": "new_owner", "display_name": "New Owner", "role": "OWNER"},
        headers=_auth("admin-tok"),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"
    assert "role escalation" in resp.json()["error"]["message"]
