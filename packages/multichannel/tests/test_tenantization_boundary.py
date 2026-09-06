"""Live synthetic tenant boundary tests for Business Suite."""

from __future__ import annotations

import httpx
import pytest

from botconnector_multichannel.persistence.db import koneksi
from botconnector_multichannel.local_business import tenant
from tenantization_fixture import PASSWORD, USERS, _login, create_fixtures


BUSINESS_URL = "http://127.0.0.1:18199"
CORE_URL = "http://127.0.0.1:8050"
HOME_URL = "http://127.0.0.1:8020"


@pytest.fixture(scope="session")
def fixture_data():
    return create_fixtures()


@pytest.fixture(scope="session")
def clients(fixture_data):
    result = {key: _login(value[1]) for key, value in USERS.items()}
    yield result
    for client in result.values():
        client.close()


def _resource_ids(fixture_data, key: str) -> dict[str, int]:
    return fixture_data["resources"][key]


def test_anonymous_private_routes_are_denied():
    with httpx.Client(base_url=BUSINESS_URL, follow_redirects=False) as client:
        assert client.get("/bisnis/api/products").status_code == 401
        shell = client.get("/bisnis/")
        assert shell.status_code == 303
        assert shell.headers["location"].startswith("/login")


def test_invalid_session_is_denied():
    with httpx.Client(base_url=BUSINESS_URL, cookies={"bc_session": "invalid-test-token"}) as client:
        assert client.get("/bisnis/api/state").status_code == 401


def test_user_without_entitlement_is_denied(clients):
    response = clients["no_access"].get(f"{BUSINESS_URL}/bisnis/api/state")
    assert response.status_code == 403


def test_each_user_sees_only_own_business(fixture_data, clients):
    for key in ("a", "b"):
        client = clients[key]
        state = client.get(f"{BUSINESS_URL}/bisnis/api/state")
        products = client.get(f"{BUSINESS_URL}/bisnis/api/products")
        assert state.status_code == 200
        assert products.status_code == 200
        assert state.json()["business"]["id"] == fixture_data["resources"][key]["business_id"]
        assert len(products.json()["products"]) == 1
        assert products.json()["products"][0]["sku"].startswith(f"TENANT-{key.upper()}")
        query_state = client.get(
            f"{BUSINESS_URL}/bisnis/api/state",
            params={"business_id": fixture_data["resources"]["b"]["business_id"]},
        )
        assert query_state.status_code == 200
        assert query_state.json()["business"]["id"] == fixture_data["resources"][key]["business_id"]


def test_representative_business_resources_are_available_per_tenant(fixture_data, clients):
    for key in ("a", "b"):
        client = clients[key]
        for path in (
            "/bisnis/api/inventory",
            "/bisnis/api/sales",
            "/bisnis/api/transfers",
            "/bisnis/api/restaurant",
            "/bisnis/api/kitchen",
            "/bisnis/api/orders",
            "/bisnis/api/reports",
            "/bisnis/api/business-integrasi",
        ):
            response = client.get(BUSINESS_URL + path)
            assert response.status_code == 200, (key, path, response.text)


@pytest.mark.parametrize("key,foreign", [("a", "b"), ("b", "a")])
def test_object_level_foreign_resources_are_denied(fixture_data, clients, key, foreign):
    own = _resource_ids(fixture_data, key)
    other = _resource_ids(fixture_data, foreign)
    client = clients[key]
    for path in (
        f"/bisnis/api/sale/{other['sale_id']}",
        f"/bisnis/api/receipt/{other['sale_id']}",
    ):
        response = client.get(BUSINESS_URL + path)
        assert response.status_code in (403, 404)
        assert str(other["sale_id"]) not in response.text

    response = client.get(
        f"{BUSINESS_URL}/bisnis/api/barcode",
        params={"barcode": f"8999{other['business_id']:08d}"},
    )
    assert response.status_code == 200
    assert str(other["sale_id"]) not in response.text

    sale_body = {
        "branch_id": other["branch_id"],
        "register_id": own["register_id"],
        "warehouse_id": own["warehouse_id"],
        "lines": [{"master_sku_id": own["master_sku_id"], "quantity": 1, "unit_price": 125000}],
    }
    assert client.post(f"{BUSINESS_URL}/bisnis/api/sale", json=sale_body).status_code in (403, 404)

    transfer_body = {
        "source_branch_id": other["branch_id"],
        "dest_branch_id": own["branch_id"],
        "lines": [{"master_sku_id": own["master_sku_id"], "quantity": 1}],
    }
    assert client.post(f"{BUSINESS_URL}/bisnis/api/transfer", json=transfer_body).status_code in (403, 404)

    order_body = {
        "branch_id": other["branch_id"],
        "register_id": own["register_id"],
        "warehouse_id": own["warehouse_id"],
        "table_id": own["table_id"],
        "lines": [{"menu_item_id": own["menu_item_id"], "quantity": 1}],
    }
    assert client.post(f"{BUSINESS_URL}/bisnis/api/restaurant/order", json=order_body).status_code in (403, 404)

    assert client.post(
        f"{BUSINESS_URL}/bisnis/api/kitchen/status",
        json={"kot_id": other["kot_id"], "status": "READY"},
    ).status_code in (403, 404)


@pytest.mark.parametrize("key", ["a", "b"])
def test_provisioning_is_idempotent(fixture_data, clients, key):
    business_id = fixture_data["resources"][key]["business_id"]
    client = clients[key]
    first = client.post(
        f"{BUSINESS_URL}/bisnis/api/provision",
        json={"name": f"ignored-repeat-{key}", "business_type": "HYBRID"},
    )
    second = client.post(
        f"{BUSINESS_URL}/bisnis/api/provision",
        json={"name": f"ignored-repeat-{key}", "business_type": "HYBRID"},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["created"] is False
    assert second.json()["created"] is False
    assert first.json()["business_id"] == second.json()["business_id"] == business_id
    with koneksi() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM local_business.business WHERE id=%s", (business_id,))
            assert cur.fetchone()["n"] == 1
            cur.execute(
                "SELECT count(*) AS n FROM local_business.business_membership WHERE business_id=%s AND role='OWNER'",
                (business_id,),
            )
            assert cur.fetchone()["n"] == 1


def test_staff_cannot_perform_owner_action(fixture_data, clients):
    client = clients["staff"]
    state = client.get(f"{BUSINESS_URL}/bisnis/api/state")
    assert state.status_code == 200
    assert state.json()["business"]["id"] == fixture_data["resources"]["a"]["business_id"]
    response = client.post(
        f"{BUSINESS_URL}/bisnis/api/products",
        json={"sku": "SHOULD-NOT-CREATE", "name": "Should Not Create", "price": 1000},
    )
    assert response.status_code == 403


def test_homepage_and_my_products_are_auth_aware(fixture_data, clients):
    anonymous = httpx.Client(base_url=HOME_URL, follow_redirects=False)
    try:
        assert anonymous.get("/my-products").status_code == 303
        homepage = anonymous.get("/")
        assert homepage.status_code == 200
        assert "/business-suite/" in homepage.text
        assert "Segera Hadir" in homepage.text
        assert "Buka Business Suite" not in homepage.text
    finally:
        anonymous.close()
    client = clients["a"]
    response = client.get(f"{HOME_URL}/my-products")
    assert response.status_code == 200
    assert "Business Suite" in response.text
    assert "/bisnis/" in response.text
    assert str(fixture_data["resources"]["b"]["business_id"]) not in response.text


def test_platform_and_admin_regression():
    with httpx.Client(base_url=HOME_URL, follow_redirects=False) as client:
        assert client.get("/login").status_code == 200
        assert client.get("/register").status_code == 200
    with httpx.Client(verify=False, follow_redirects=False) as client:
        headers = {"Host": "botconnector.id"}
        assert client.get("https://103.58.101.207/panel/", headers=headers).status_code == 200
        assert client.get("https://103.58.101.207/connect-v2/dashboard", headers=headers).status_code in (200, 302, 303)


def test_pilot_is_not_resolved_for_customers(fixture_data, clients):
    assert fixture_data["resources"]["a"]["business_id"] != 336
    state = clients["a"].get(f"{BUSINESS_URL}/bisnis/api/state")
    assert state.status_code == 200
    assert state.json()["business"]["id"] != 336
    assert "LOCAL-PILOT" not in state.text


def test_scope_guard_rejects_every_foreign_object_kind(fixture_data):
    own = fixture_data["resources"]["a"]
    foreign = fixture_data["resources"]["b"]
    foreign_business = fixture_data["provision"]["b"]["business_id"]
    object_ids = {
        "business": foreign_business,
        "branch": foreign["branch_id"],
        "register": foreign["register_id"],
        "cashier": foreign["cashier_id"],
        "warehouse": foreign["warehouse_id"],
        "product": foreign["master_sku_id"],
        "sale": foreign["sale_id"],
        "order": foreign["order_id"],
        "kot": foreign["kot_id"],
        "connector": foreign["connector_id"],
        "menu_item": foreign["menu_item_id"],
        "table": foreign["table_id"],
    }
    for kind, object_id in object_ids.items():
        with pytest.raises(Exception) as exc_info:
            tenant.assert_object(kind, object_id, own["business_id"])
        assert getattr(exc_info.value, "status_code", None) in (403, 404)


def test_offline_sync_does_not_touch_other_business(fixture_data, clients):
    ids = fixture_data["resources"]
    with koneksi() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM local_business.offline_queue WHERE business_id=%s", (ids["b"]["business_id"],))
            before = cur.fetchall()
    response = clients["a"].post(f"{BUSINESS_URL}/bisnis/api/offline/sync", json={})
    assert response.status_code == 200
    with koneksi() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM local_business.offline_queue WHERE business_id=%s", (ids["b"]["business_id"],))
            assert cur.fetchall() == before


def test_relevant_tenant_indexes_exist():
    expected = {
        "idx_business_membership_user_business",
        "idx_business_membership_business_role",
        "idx_business_product_sku_business",
        "idx_business_sale_created",
        "idx_business_order_created",
        "idx_business_offline_status",
    }
    with koneksi() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname='local_business' AND indexname = ANY(%s)",
                (list(expected),),
            )
            assert {row["indexname"] for row in cur.fetchall()} == expected
