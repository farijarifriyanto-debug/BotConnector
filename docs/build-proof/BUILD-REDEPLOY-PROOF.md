# Build / Redeploy Proof

Executed 2026-09-06. Every install/build/start below used ONLY the
canonical repo (this checkout, HEAD `d8ecb9a` at start of this phase) plus
a fresh disposable venv/container/temp directory — never an old source
tree, except where explicitly marked CANONICAL_LEAK below. No production
process was restarted, no production config changed, no production
database written to, no old source deleted.

Schema:
```
COMPONENT=
SOURCE_ONLY_FROM_CANONICAL=YES|NO
DEPENDENCY_INSTALL=
BUILD=
ENTRYPOINT=
ISOLATED_RUNTIME=
HEALTH=
CAN_REDEPLOY=
BLOCKER=
```

---

## Group: packages/multichannel (shared runtime for business-suite + integrasi)

COMPONENT=packages/multichannel
SOURCE_ONLY_FROM_CANONICAL=YES (the package itself has no /opt path in its main import surface)
DEPENDENCY_INSTALL=PASS (fresh venv, `requirements.lock.txt`, Python 3.12.3, 50 packages)
BUILD=N/A (library, not a running process)
ENTRYPOINT=N/A
ISOLATED_RUNTIME=N/A
HEALTH=N/A
CAN_REDEPLOY=YES as a library
BLOCKER=(none for the package itself — see business-suite/integrasi below for how they consume it)

COMPONENT=apps/business-suite
SOURCE_ONLY_FROM_CANONICAL=**YES — FIXED 2026-09-06**
DEPENDENCY_INSTALL=PASS (via packages/multichannel's lockfile)
BUILD=N/A
ENTRYPOINT=PASS on the ACTUAL committed file, no workaround needed anymore.
  `app.py`'s `sys.path.insert(0, "/opt")` was replaced with a repo-relative
  computation (`Path(__file__).resolve().parents[2] / "packages"`) plus a
  `sys.modules` alias, so `import botconnector_multichannel` resolves to
  `packages/multichannel` with zero symlink and zero source duplication.
ISOLATED_RUNTIME=PASS — ran the unmodified `apps/business-suite/run.sh`
  directly (`PORT=19851 ./apps/business-suite/run.sh`), which now resolves
  its venv from `packages/multichannel/venv` (built at that path for this
  proof, then removed) instead of `/opt`.
HEALTH=`{"ok":false,...,"database":"disconnected"}` — correct and expected: no production DB credential was provided.
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=apps/integrasi
SOURCE_ONLY_FROM_CANONICAL=**YES — FIXED 2026-09-06** (identical fix shape to business-suite)
DEPENDENCY_INSTALL=PASS (via packages/multichannel's lockfile)
BUILD=N/A
ENTRYPOINT=PASS on the actual committed file
ISOLATED_RUNTIME=PASS — ran the unmodified `apps/integrasi/run.sh` directly
HEALTH=`{"ok":true,"service":"botconnector-integrasi"}`
CAN_REDEPLOY=YES
BLOCKER=none

```
MULTICHANNEL_ENV_BUILD=PASS
BUSINESS_SUITE_ENTRYPOINT=PASS (unmodified file, no workaround)
INTEGRASI_ENTRYPOINT=PASS (unmodified file, no workaround)
BUSINESS_SUITE_CANONICAL_IMPORT=PASS
BUSINESS_SUITE_RUN_SCRIPT=PASS
INTEGRASI_CANONICAL_IMPORT=PASS
INTEGRASI_RUN_SCRIPT=PASS
```

---

## Group: services/connector-core + 6 shipping services (shared runtime)

All 7 use the exact same venv in production (proven via `ExecStart` in
Phase 9's dependency audit) and, unlike business-suite/integrasi, **none
of their `app.py`/`main.py` files contain any hardcoded `/opt` or
`/home/botadmin` path** — confirmed by direct grep before running anything.

COMPONENT=services/connector-core
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS (fresh venv, `requirements.lock.txt`, Python 3.12.3, 25 packages)
BUILD=N/A
ENTRYPOINT=PASS (`import main; main.app.title == "BotConnector Connector Core"`, run from the canonical directory with no path tricks)
ISOLATED_RUNTIME=NOT STARTED this pass (import proof was sufficient; no env-var/DB requirements were found at module level)
HEALTH=N/A
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=services/shipping/integration
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS (shared venv above)
ENTRYPOINT=PASS (temp SQLite path + dummy peer URLs via env vars — `BC_SHIPPING_INTEGRATION_DB`, `BC_LOCATION_RESOLVER_URL`, `BC_PROVIDER_ROUTER_URL`)
ISOLATED_RUNTIME=NOT STARTED this pass (import sufficient)
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=services/shipping/location-resolver
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS
ENTRYPOINT=PASS (temp SQLite + dummy `RAJAONGKIR_SHIPPING_COST_API_KEY`)
ISOLATED_RUNTIME=NOT STARTED this pass
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=services/shipping/location-public-gateway
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS
ENTRYPOINT=PASS (temp SQLite path via `BC_LOCATION_PUBLIC_DB`)
ISOLATED_RUNTIME=NOT STARTED this pass
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=services/shipping/public-gateway
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS
ENTRYPOINT=PASS (temp SQLite via `BC_SHIPPING_PUBLIC_DB`)
ISOLATED_RUNTIME=PASS — full uvicorn start on a disposable port, with
  `BC_SHIPPING_INTEGRATION_URL` deliberately pointed at an unreachable
  address so no real downstream call could happen
HEALTH=`{"ok":true,"service":"shipping-public-gateway-v1"}` (this endpoint makes no downstream call by itself)
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=services/shipping/router
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS
ENTRYPOINT=PASS (temp SQLite via `BC_SHIPPING_ROUTER_DB`, dummy `BC_PROVIDER_RAJAONGKIR_URL`)
ISOLATED_RUNTIME=NOT STARTED this pass
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=services/shipping/rajaongkir-cost
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS
ENTRYPOINT=PASS (temp SQLite via `BC_RO_DB`, dummy `RAJAONGKIR_SHIPPING_COST_API_KEY`)
ISOLATED_RUNTIME=NOT STARTED this pass
CAN_REDEPLOY=YES
BLOCKER=none

```
CONNECTOR_SHARED_ENV_BUILD=PASS
ALL_SHIPPING_ENTRYPOINTS_LOAD=PASS (7/7: connector-core + 6 shipping services)
```

Note: the real, live, production RajaOngkir E2E chain was already proven
in an earlier phase (real quotes returned). This phase deliberately did
NOT repeat a live external call — it proves each service loads and starts
in isolation, which is a different (and here, additional) kind of
evidence.

---

## Standalone Python components (own venv each)

COMPONENT=apps/ai-chat-preview
SOURCE_ONLY_FROM_CANONICAL=YES (no /opt or old-source path in app.py)
DEPENDENCY_INSTALL=PASS (`requirements.lock.txt`, 21 packages)
ENTRYPOINT=PASS (`DATABASE_URL`/`AI_CHAT_SCHEMA` set to dummy values)
ISOLATED_RUNTIME=PASS (uvicorn started, `/openapi.json` → 200)
HEALTH=not exercised (no `/health` route found; `/openapi.json` used as a liveness signal instead)
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=apps/ai-workspace
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS (`requirements.lock.txt`, 27 packages)
ENTRYPOINT=PASS (no required env vars at module level)
ISOLATED_RUNTIME=PASS (`/openapi.json` → 200)
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=apps/admin-gate
SOURCE_ONLY_FROM_CANONICAL=YES
DEPENDENCY_INSTALL=PASS (`requirements.lock.txt`, 23 packages)
ENTRYPOINT=PASS
ISOLATED_RUNTIME=PASS (`/openapi.json` → 200)
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=services/finance-core
SOURCE_ONLY_FROM_CANONICAL=**YES — FIXED 2026-09-06**
DEPENDENCY_INSTALL=PASS (`requirements.lock.txt`, 15 packages)
ENTRYPOINT=PASS — `app/main.py` itself never had a leak.
ISOLATED_RUNTIME=PASS — ran the unmodified `run-finance-core.sh` directly
  (`FINANCE_DB_HOST=127.0.0.1 FINANCE_DB_NAME=dummy FINANCE_DB_USER=dummy
  FINANCE_DB_PASSWORD=dummy PORT=19853 ./services/finance-core/run-finance-core.sh`),
  which now resolves `APPDIR` and its venv relative to the script's own
  location, and only shells out to `docker inspect` if
  `FINANCE_CORE_POSTGRES_CONTAINER` is explicitly set (opt-in, not
  hardwired). `/openapi.json` → 200.
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=apps/store
SOURCE_ONLY_FROM_CANONICAL=YES (app/app.py has no old-source path; confirmed byte-identical to the live release's `app/` directory except `__pycache__`)
DEPENDENCY_INSTALL=PASS (`requirements.txt`, exact pins already: fastapi==0.128.2, uvicorn[standard]==0.40.0, jinja2==3.1.6)
ENTRYPOINT=PASS (`STORE_DATA` redirected to a temp directory)
ISOLATED_RUNTIME=PASS (uvicorn started on a disposable port; `/docs` returned 404 because this app disables the Swagger UI route, same pattern as other services here — the process itself served the request, proving it's alive)
CAN_REDEPLOY=YES for the application
BLOCKER=`apps/store/deploy-store-v6.sh`, `rollback-store-v6.sh`,
  `production-check.sh`, `configure-midtrans.sh`, `seller-control-store-api-patch-v2.sh`
  are legacy OPERATIONAL scripts that hardcode `/opt/botconnector-store`
  and even `/opt/restaurant-seller-control/app/app.py` — these describe
  how the OLD deployment currently works (DEPLOYMENT_CURRENT_STATE_REFERENCE),
  not how to redeploy from this repo. They were NOT used in this proof and
  should not be used as the future build recipe (see REDEPLOY-MAP.md,
  which defines a clean recipe instead).

COMPONENT=apps/parking
SOURCE_ONLY_FROM_CANONICAL=YES (`parking/` package itself has no old-source path in its main import surface; one unrelated dev utility script, `scripts/capture_ui_previews.py`, hardcodes an old path but is not part of the app — classified TEST_TOOLING)
DEPENDENCY_INSTALL=PASS (`requirements.txt`, loose ranges — not yet an exact lock, matching what was already documented; installed cleanly)
ENTRYPOINT=PASS
ISOLATED_RUNTIME=**PASS — proven with an ephemeral, disposable Postgres**
  (2026-09-06 follow-up): started `postgres:16-alpine` in a throwaway
  Docker container on a random local port with a dummy user/password/db,
  ran all 5 canonical `alembic upgrade head` migrations against it
  (0001→0005, all applied cleanly), then started
  `parking.api.app:create_app --factory` against that same ephemeral
  database.
HEALTH=`GET /parking/api/health` → `{"status":"ok","service":"botconnector-parking","version":"0.1.0-m1m3"}`. Additionally exercised a real DB-backed read path (`GET /parking/api/sites/1/tariff-plans`) → clean `401 UNAUTHORIZED` (correct auth-layer behavior against a live DB connection, not a crash — sufficient evidence of real DB wiring without needing to fabricate auth credentials).
CAN_REDEPLOY=YES
BLOCKER=none. Ephemeral Postgres container, venv, and all temp files were removed after the proof; production's real `botconnector-parking-postgres` container was never touched.

```
PARKING_EPHEMERAL_DB=PASS
PARKING_ENTRYPOINT=PASS
PARKING_HEALTH=PASS
PARKING_PRODUCTION_DB_TOUCHED=NO
```

---

## Docker-native components

COMPONENT=apps/restaurant
SOURCE_ONLY_FROM_CANONICAL=YES (Dockerfile + app.py, no old-source paths in either — verified before building)
BUILD=PASS (`docker build`, python:3.12-slim base, ~20s)
ENTRYPOINT=PASS
ISOLATED_RUNTIME=PASS — ran with a temp bind-mounted `/data` volume and
  dummy `SELLER_ADMIN_PASSWORD_HASH`/`SELLER_SESSION_SECRET`, on a
  disposable port, no network beyond `127.0.0.1`
HEALTH=HTTP 200 on the app's root route
CAN_REDEPLOY=YES
BLOCKER=none. Image and container removed after the proof; nothing retained on disk.

COMPONENT=apps/drive
SOURCE_ONLY_FROM_CANONICAL=YES (Dockerfile + app.py, no old-source paths — `docker-compose.yml`'s production bind mounts to `/mnt/botconnector-storage` etc. were NOT used; a plain `docker run` with temp volumes was used instead)
BUILD=PASS (`docker build`, ~12s)
ENTRYPOINT=PASS
ISOLATED_RUNTIME=PASS — first attempt failed with a permission error
  writing to the temp bind mount (container runs as uid 10001); fixed by
  `chmod 777` on the disposable temp directories (not a production
  concern), then both workers started cleanly.
HEALTH=`{"status":"ok","version":"0.2.0","storage":"available","metadata":"available",...}`
CAN_REDEPLOY=YES
BLOCKER=none. Image and container removed after the proof.

---

## Static components

COMPONENT=apps/public-site
SOURCE_ONLY_FROM_CANONICAL=YES (pure static HTML/CSS/JS, no server-side code)
BUILD=N/A (no build step — static files served as-is)
ENTRYPOINT=N/A
ISOLATED_RUNTIME=PASS (`python -m http.server` on 127.0.0.1, disposable port)
HEALTH=see PUBLIC_SITE_BUILD result below
CAN_REDEPLOY=YES
BLOCKER=none

COMPONENT=packages/shared-design
SOURCE_ONLY_FROM_CANONICAL=YES
BUILD=N/A
ENTRYPOINT=N/A — this is documentation + reference images, not a running
  component (confirmed LIVE_RUNTIME=NONE in SOURCE-MAP.md); nothing to
  build or start
ISOLATED_RUNTIME=N/A
CAN_REDEPLOY=YES (it's just files)
BLOCKER=none

### Public site page/link/claim verification

- All 10 sampled top-level pages returned HTTP 200 from the isolated static server.
- Full internal-link sweep across every `index.html`: 13 unique internal links, 0 broken.
- Confirmed the Google Sheets badge fix is live in the served output: `<span class="badge soon">Segera Hadir</span>` for Google Sheets; the three still-"Tersedia" cards (Webhook, HTTP/API, Telegram) match the current Capability Registry, not a new violation.
### Real browser acceptance (2026-09-06 follow-up — Playwright, Chromium)

Installed Playwright 1.62.0 + Chromium in a disposable venv, served the
static `apps/public-site` directory, and drove the same 10 canonical pages
across three viewports: desktop (1440×900), laptop (1280×800), and mobile
(390×844). Per page: navigated with `networkidle`, checked HTTP status,
console errors, horizontal scroll overflow, and (on `/konektor/`) that the
Google Sheets card's text does not contain "Tersedia". Also exercised the
first dropdown trigger (desktop/laptop) and any hamburger/menu-toggle
element (mobile).

Result — all three viewports clean:
```json
{
  "results": {"desktop": "PASS", "laptop": "PASS", "mobile_390": "PASS"},
  "internal_404": [],
  "fatal_console_errors": [],
  "overflow_pages": [],
  "gsheets_violation": [],
  "network_5xx": []
}
```

Browser, venv, and cache were removed after the run (nothing retained).

```
PLAYWRIGHT_USED=YES
PUBLIC_SITE_BUILD=PASS
PUBLIC_SITE_DESKTOP=PASS
PUBLIC_SITE_LAPTOP=PASS
PUBLIC_SITE_MOBILE_390=PASS
PUBLIC_SITE_INTERNAL_404=0
PUBLIC_SITE_FATAL_CONSOLE_ERRORS=0
PUBLIC_SITE_BROWSER_ACCEPTANCE=PASS
```
