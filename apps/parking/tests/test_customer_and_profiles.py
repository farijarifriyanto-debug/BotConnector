"""Tests for BotConnector Parking — 3 Deployment Profiles, Customer Onboarding & Payment Gateway."""

import os
import secrets
import unittest.mock
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from parking.api.app import create_app
from parking.models import ParkingPayment, ParkingSession, ParkingSite, ParkingTenant
from parking.services.auth import hash_api_key
from tests.helpers import new_operator, new_tenant


@pytest.fixture
def app_and_db(db):
    app = create_app()
    return app, db


def test_anonymous_parking_redirect():
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/parking/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/parking/"


def test_onboarding_full_stack(db):
    app = create_app()
    uid = f"usr_fs_{secrets.token_hex(4)}"
    mock_user = {"id": uid, "email": f"{uid}@example.com", "name": "Full Stack Admin"}

    with unittest.mock.patch("parking.services.customer_service.fetch_core_user", return_value=mock_user), \
         unittest.mock.patch("parking.services.customer_service.fetch_core_entitled", return_value=True), \
         unittest.mock.patch("parking.services.auth.fetch_core_user", return_value=mock_user), \
         unittest.mock.patch("parking.services.auth.fetch_core_entitled", return_value=True):
        
        with TestClient(app, cookies={"bc_session": f"sess_{uid}"}) as client:
            # 1. Check initial context (unprovisioned)
            ctx = client.get("/parking/api/customer/me").json()
            assert ctx["authenticated"] is True
            assert ctx["provisioned"] is False

            # 2. Provision FULL_STACK
            payload = {
                "deployment_profile": "FULL_STACK",
                "organization_name": "Mall Nusantara Parking",
                "site_code": "SITE-MN",
                "capacity": 200,
                "tariff_type": "FLAT",
                "rate": 5000,
            }
            prov = client.post("/parking/api/customer/provision", json=payload).json()
            assert prov["status"] == "ok"
            assert prov["deployment_profile"] == "FULL_STACK"

            # 3. Verify context is now provisioned
            ctx2 = client.get("/parking/api/customer/me").json()
            assert ctx2["provisioned"] is True
            assert ctx2["deployment_profile"] == "FULL_STACK"
            assert ctx2["site"]["code"] == "SITE-MN"
            assert ctx2["site"]["capacity_total"] == 200


def test_onboarding_payment_only_and_gateway_flow(db):
    app = create_app()
    uid = f"usr_po_{secrets.token_hex(4)}"
    mock_user = {"id": uid, "email": f"merchant_{uid}@parkingapp.com", "name": "Merchant PMS"}

    with unittest.mock.patch("parking.services.customer_service.fetch_core_user", return_value=mock_user), \
         unittest.mock.patch("parking.services.customer_service.fetch_core_entitled", return_value=True), \
         unittest.mock.patch("parking.services.auth.fetch_core_user", return_value=mock_user), \
         unittest.mock.patch("parking.services.auth.fetch_core_entitled", return_value=True):

        with TestClient(app, cookies={"bc_session": f"sess_{uid}"}) as client:
            # 1. Provision PAYMENT_ONLY
            payload = {
                "deployment_profile": "PAYMENT_ONLY",
                "organization_name": "External PMS Partner",
                "webhook_url": "https://example.com/webhook",
            }
            prov = client.post("/parking/api/customer/provision", json=payload).json()
            assert prov["status"] == "ok"
            assert prov["deployment_profile"] == "PAYMENT_ONLY"

            # 2. Create Payment Order via Gateway
            order_payload = {
                "merchant_order_ref": "EXT-PARK-001",
                "amount": 15000,
                "currency": "IDR",
                "payment_method": "QRIS_MPM_DYNAMIC",
            }
            order = client.post("/parking/api/payment-gateway/orders", json=order_payload).json()
            assert order["state"] == "PENDING"
            assert order["merchant_order_ref"] == "EXT-PARK-001"
            assert order["amount"] == 15000
            assert "00020101021226" in order["qr_string"]
            pay_ref = order["payment_reference"]

            # 3. Check Order Status
            fetched = client.get(f"/parking/api/payment-gateway/orders/{pay_ref}").json()
            assert fetched["payment_reference"] == pay_ref
            assert fetched["state"] == "PENDING"

            # 4. Simulate Payment Settlement
            with unittest.mock.patch("urllib.request.urlopen") as mock_webhook:
                mock_webhook.return_value.__enter__.return_value.status = 200
                settle = client.post(f"/parking/api/payment-gateway/orders/{pay_ref}/simulate-pay").json()
                assert settle["state"] == "PAID"
                assert settle["paid_at"] is not None

            # 5. Check Reconciliation
            recon = client.get("/parking/api/payment-gateway/reconciliation").json()
            assert recon["paid_transactions_count"] >= 1
            assert recon["total_settled_volume_idr"] >= 15000


def test_profile_upgrade_seamless(db):
    app = create_app()
    uid = f"usr_up_{secrets.token_hex(4)}"
    mock_user = {"id": uid, "email": f"upgrade_{uid}@example.com", "name": "Upgrade User"}

    with unittest.mock.patch("parking.services.customer_service.fetch_core_user", return_value=mock_user), \
         unittest.mock.patch("parking.services.customer_service.fetch_core_entitled", return_value=True), \
         unittest.mock.patch("parking.services.auth.fetch_core_user", return_value=mock_user), \
         unittest.mock.patch("parking.services.auth.fetch_core_entitled", return_value=True):

        with TestClient(app, cookies={"bc_session": f"sess_{uid}"}) as client:
            # Start as PAYMENT_ONLY
            client.post("/parking/api/customer/provision", json={
                "deployment_profile": "PAYMENT_ONLY",
                "organization_name": "Upgradable Merchant",
            })

            # Upgrade to FULL_STACK
            upg = client.post("/parking/api/customer/update-profile", json={
                "deployment_profile": "FULL_STACK",
                "webhook_url": "https://example.com/new-hook",
            }).json()
            assert upg["status"] == "ok"
            assert upg["deployment_profile"] == "FULL_STACK"

            ctx = client.get("/parking/api/customer/me").json()
            assert ctx["deployment_profile"] == "FULL_STACK"


def test_full_stack_simulator_workflow(db):
    app = create_app()
    uid = f"usr_sim_{secrets.token_hex(4)}"
    mock_user = {"id": uid, "email": f"sim_{uid}@example.com", "name": "Simulator Tester"}

    with unittest.mock.patch("parking.services.customer_service.fetch_core_user", return_value=mock_user), \
         unittest.mock.patch("parking.services.customer_service.fetch_core_entitled", return_value=True), \
         unittest.mock.patch("parking.services.auth.fetch_core_user", return_value=mock_user), \
         unittest.mock.patch("parking.services.auth.fetch_core_entitled", return_value=True):

        with TestClient(app, cookies={"bc_session": f"sess_{uid}"}) as client:
            client.post("/parking/api/customer/provision", json={
                "deployment_profile": "FULL_STACK",
                "organization_name": "Simulator Site",
                "site_code": "SITE-SIM",
                "capacity": 100,
                "tariff_type": "FLAT",
                "rate": 5000,
            })

            # 1. Simulate Vehicle Entry
            test_plate = f"B {secrets.randbelow(8999) + 1000} {secrets.token_hex(2).upper()}"
            resp = client.post("/parking/api/customer/simulate-entry", json={
                "plate": test_plate,
                "vehicle_type": "CAR",
            })
            entry = resp.json()
            assert resp.status_code == 200, f"entry error: {entry}"
            assert entry["status"] == "ok"
            assert entry["plate"] == test_plate
            assert entry["state"] == "PARKED"
            pub_ref = entry["public_reference"]

            # 2. Simulate Vehicle Exit & Settlement
            exit_res = client.post("/parking/api/customer/simulate-exit", json={
                "public_reference": pub_ref,
            }).json()
            assert exit_res["status"] == "ok"
            assert exit_res["state"] == "CLOSED"
            assert exit_res["payment_state"] == "PAID"
            assert exit_res["barrier_intent"] == "BARRIER_OPEN_INTENT_CREATED"


def test_activate_product_success(db):
    app = create_app()
    uid = f"usr_act_{secrets.token_hex(4)}"
    mock_user = {"id": uid, "email": f"act_{uid}@example.com", "name": "Activation User"}
    mock_csrf = "csrf_token_12345"

    with unittest.mock.patch("parking.services.customer_service.fetch_core_session_info", return_value=(mock_user, mock_csrf)), \
         unittest.mock.patch("urllib.request.urlopen") as mock_open:
        mock_resp = unittest.mock.MagicMock()
        mock_resp.read.return_value = b'{"slug": "parking", "access_status": "active", "role": "owner"}'
        mock_resp.__enter__.return_value = mock_resp
        mock_open.return_value = mock_resp

        with TestClient(app, cookies={"bc_session": f"sess_{uid}"}) as client:
            resp = client.post("/parking/api/customer/activate")
            assert resp.status_code == 200
            data = resp.json()
            assert data["slug"] == "parking"
            assert data["access_status"] == "active"

            # Check that urllib request had X-CSRF-Token header
            call_req = mock_open.call_args[0][0]
            assert call_req.headers["X-csrf-token"] == mock_csrf or call_req.headers.get("X-csrf-token") == mock_csrf


def test_activate_product_unauthenticated(db):
    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/parking/api/customer/activate")
        assert resp.status_code == 401


def test_activate_product_sanitized_errors(db):
    app = create_app()
    uid = f"usr_err_{secrets.token_hex(4)}"
    mock_user = {"id": uid, "email": f"err_{uid}@example.com", "name": "Error User"}
    mock_csrf = "csrf_token_abc"

    import urllib.error
    with unittest.mock.patch("parking.services.customer_service.fetch_core_session_info", return_value=(mock_user, mock_csrf)), \
         unittest.mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 403, "Forbidden", {}, None)):
        with TestClient(app, cookies={"bc_session": f"sess_{uid}"}) as client:
            resp = client.post("/parking/api/customer/activate")
            assert resp.status_code == 403
            err_data = resp.json()
            # Never leak "Core activation error: 403"
            assert "Core activation error" not in str(err_data)
            assert "izin aktivasi" in str(err_data)

