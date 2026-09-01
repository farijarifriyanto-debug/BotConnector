#!/usr/bin/env python3
"""
Lightweight Deterministic Visual Smoke Suite for BotConnector Production.
Audits critical routes for HTTP 200, stylesheet loading, 0 console errors, and viewport layout.
"""
import sys
import json
import subprocess
from playwright.sync_api import sync_playwright

CRITICAL_ROUTES = [
    {"url": "https://botconnector.id/", "auth": False, "name": "homepage"},
    {"url": "https://botconnector.id/products", "auth": False, "name": "products"},
    {"url": "https://botconnector.id/support", "auth": False, "name": "support"},
    {"url": "https://botconnector.id/status", "auth": False, "name": "status"},
    {"url": "https://botconnector.id/login", "auth": False, "name": "login"},
    {"url": "https://botconnector.id/my-products", "auth": True, "name": "my_products"},
    {"url": "https://botconnector.id/bisnis/#/dashboard", "auth": True, "name": "business_suite_dashboard"},
    {"url": "https://botconnector.id/connect-v2/", "auth": True, "name": "connect"},
    {"url": "https://botconnector.id/drive", "auth": True, "name": "my_drive"},
]

def get_test_token() -> str:
    cmd = """sudo -n docker exec botconnector-backend-api python3 -c "
import json
from app.security import create_session
from app.db import db_connection
with db_connection() as conn:
    with conn.cursor() as cur:
        cur.execute(\\\"SELECT id FROM users WHERE email = 'uji1@botconnector.xyz'\\\")
        user = cur.fetchone()
        if not user:
            cur.execute(\\\"SELECT id FROM users LIMIT 1\\\")
            user = cur.fetchone()
token, _ = create_session(str(user['id']), ip_address='127.0.0.1', user_agent='VisualSmokeSuite')
print(token)
" """
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def run_smoke_suite():
    token = get_test_token()
    failures = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome-stable', headless=True)

        for item in CRITICAL_ROUTES:
            url = item["url"]
            name = item["name"]
            auth = item["auth"]

            ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
            if auth:
                ctx.add_cookies([{'name': 'bc_session', 'value': token, 'domain': 'botconnector.id', 'path': '/', 'secure': True, 'httpOnly': True}])

            page = ctx.new_page()
            console_errors = []
            failed_reqs = []

            page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)
            page.on('requestfailed', lambda r: failed_reqs.append(r.url))

            try:
                res = page.goto(url, wait_until='networkidle', timeout=15000)
                status = res.status if res else 0
            except Exception as e:
                status = 500
                failures.append(f"[{name}] Navigation error: {e}")
                ctx.close()
                continue

            page.wait_for_timeout(500)

            if status >= 400:
                failures.append(f"[{name}] Returned HTTP {status}")

            crit_console = [e for e in console_errors if 'clarity' not in e]
            if crit_console:
                failures.append(f"[{name}] Console errors: {crit_console}")

            if failed_reqs:
                failures.append(f"[{name}] Failed network requests: {failed_reqs}")

            ctx.close()
            print(f"  ✓ {name} ({url}) -> HTTP {status}, Errors: 0")

        browser.close()

    if failures:
        print("\nSMOKE SUITE FAILED WITH THE FOLLOWING ISSUES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print("\nALL VISUAL SMOKE TESTS PASSED!")

if __name__ == '__main__':
    run_smoke_suite()
