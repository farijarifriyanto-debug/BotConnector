"""
Targeted UI and Support AI integration test for BotConnector Parking.
Verifies premium UI structures, readiness checklist, and Support AI widget inclusion.
"""
from fastapi.testclient import TestClient
from parking.api.app import app

client = TestClient(app)

def test_parking_console_serves_html_and_support_ai():
    res = client.get("/parking/console/")
    assert res.status_code == 200
    html = res.text

    # Verify Support AI Widget integration
    assert '/static/css/support_ai_widget.css' in html
    assert '/static/js/support_ai_widget.js' in html

    # Verify Premium UI components
    assert 'dash-hero' in html
    assert 'readiness-list' in html
    assert 'flow-step-bar' in html
    assert 'sim-feedback-card' in html
    assert 'empty-teach-card' in html
    assert 'STATUS KESIAPAN OPERASIONAL' in html or 'Status Kesiapan Operasional' in html
    assert 'Status Kesiapan Hardware' in html
    assert 'Status Metode Pembayaran' in html

def test_parking_health():
    res = client.get("/parking/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "botconnector-parking"
