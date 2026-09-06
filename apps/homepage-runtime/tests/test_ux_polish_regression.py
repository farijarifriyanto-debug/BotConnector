"""
Targeted Regression Test Suite for Support AI V3 UX Polish:
- Multi-turn Action Link Relevance
- Multi-turn Source Attribution Relevance
- Elimination of Stale Action / Source Reuse
"""
import pytest
import time
from starlette.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_case_a_inventory_two_branches():
    sess_id = f"test_ux_a_{int(time.time())}"
    r1 = client.post("/v1/support-ai/chat", json={"session_id": sess_id, "message": "cara tambah stok?"}).json()
    assert r1["ok"] is True
    assert any("inventory" in a["url"] for a in r1["action_links"])

    # Follow-up
    r2 = client.post("/v1/support-ai/chat", json={"session_id": sess_id, "message": "kalau dua cabang gimana"}).json()
    assert r2["ok"] is True
    # Verify response explains transfer
    assert "transfer" in r2["response"].lower() or "cabang" in r2["response"].lower()
    # Verify source points to Transfer Stok
    assert any("business-transfers" in s["url"] for s in r2["sources"])
    # Verify action links point to Transfer Stok
    assert any("transfers" in a["url"] for a in r2["action_links"])
    # Verify no stale POS action
    assert not any("pos" in a["url"] for a in r2["action_links"])

def test_case_b_kot_to_kds():
    sess_id = f"test_ux_b_{int(time.time())}"
    r1 = client.post("/v1/support-ai/chat", json={"session_id": sess_id, "message": "apa itu KOT?"}).json()
    assert r1["ok"] is True

    # Follow-up
    r2 = client.post("/v1/support-ai/chat", json={"session_id": sess_id, "message": "KDS?"}).json()
    assert r2["ok"] is True
    assert "kitchen display system" in r2["response"].lower() or "layar" in r2["response"].lower() or "dapur" in r2["response"].lower()
    # Verify source points to Restaurant & KDS
    assert any("business-restaurant" in s["url"] for s in r2["sources"])
    # Verify action link points to KDS/Restaurant
    assert any("restaurant" in a["url"] for a in r2["action_links"])

def test_case_c_payment_only_no_hardware():
    sess_id = f"test_ux_c_{int(time.time())}"
    r1 = client.post("/v1/support-ai/chat", json={"session_id": sess_id, "message": "saya cuma mau payment parkir"}).json()
    assert r1["ok"] is True

    # Follow-up
    r2 = client.post("/v1/support-ai/chat", json={"session_id": sess_id, "message": "hardware masih perlu nggak?"}).json()
    assert r2["ok"] is True
    # Verify response clearly explains no camera/barrier/Edge required for Payment Only
    assert "tidak" in r2["response"].lower() or "tanpa hardware" in r2["response"].lower() or "pms" in r2["response"].lower()
    # Verify source is Payment Only
    assert any("parking-payment-only" in s["url"] or "parking-api-ref" in s["url"] for s in r2["sources"])
    # Verify action link is Payment / API
    assert any("parking" in a["url"] or "parking-api-ref" in a["url"] for a in r2["action_links"])

def test_case_d_qris_not_live_test_what():
    sess_id = f"test_ux_d_{int(time.time())}"
    r1 = client.post("/v1/support-ai/chat", json={"session_id": sess_id, "message": "QRIS belum aktif?"}).json()
    assert r1["ok"] is True

    # Follow-up
    r2 = client.post("/v1/support-ai/chat", json={"session_id": sess_id, "message": "jadi sekarang bisa test apa?"}).json()
    assert r2["ok"] is True
    assert "simulasi" in r2["response"].lower() or "sandbox" in r2["response"].lower()
    # Verify source is Simulation
    assert any("parking-simulation" in s["url"] for s in r2["sources"])
    # Verify action link is Simulation
    assert any("parking" in a["url"] or "simulation" in a["url"] for a in r2["action_links"])
