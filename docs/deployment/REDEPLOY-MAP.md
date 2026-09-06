# Redeploy Map

Canonical deployment recipe per component, so a future operator can
rebuild from `/home/botadmin/ai-workspaces/BotConnector-Platform` alone,
without opening an old source directory. Built 2026-09-06 from the actual
build/redeploy proof in `docs/build-proof/BUILD-REDEPLOY-PROOF.md`. No
secret values appear below — only variable/secret NAMES.

Where a component has a CANONICAL_LEAK (see build-proof doc), the
BUILD_COMMAND/START_COMMAND here are the **corrected** recipe — not what's
currently shipped in the repo's own `run.sh`/deploy scripts. That
distinction is called out explicitly in each entry.

---

### apps/public-site
SOURCE_PATH=apps/public-site
DEPENDENCY_MANIFEST=none (static HTML/CSS/JS)
BUILD_COMMAND=none
START_COMMAND=serve the directory with any static file server (e.g. `python -m http.server` for a dev preview; nginx `root` for production)
REQUIRED_ENV_NAMES=none
REQUIRED_SECRET_NAMES=none
PERSISTENT_DATA_PATH=none
HEALTH_CHECK=HTTP GET `/` → 200
ROLLBACK_ARTIFACT_TYPE=git revert (no release/version scheme of its own yet — it's a POC, not yet live)

### packages/shared-design
SOURCE_PATH=packages/shared-design
DEPENDENCY_MANIFEST=none (docs + reference images)
BUILD_COMMAND=none
START_COMMAND=N/A — not a running component
REQUIRED_ENV_NAMES=none
REQUIRED_SECRET_NAMES=none
PERSISTENT_DATA_PATH=none
HEALTH_CHECK=N/A
ROLLBACK_ARTIFACT_TYPE=git revert

### apps/store
SOURCE_PATH=apps/store/app
DEPENDENCY_MANIFEST=apps/store/requirements.txt (already exact-pinned)
BUILD_COMMAND=`python3 -m venv venv && venv/bin/pip install -r requirements.txt`
START_COMMAND=`venv/bin/python -m uvicorn app.app:APP --host 127.0.0.1 --port <port> --app-dir apps/store`
REQUIRED_ENV_NAMES=STORE_DATA, PUBLIC_BASE, STORE_ENABLED, PAYMENT_MODE, MIDTRANS_ENV, SELLER_URL, STORE_ADMIN_SECRET, STORE_COOKIE_SECRET, TRIAL_AUTO_ISSUE
REQUIRED_SECRET_NAMES=MIDTRANS_SERVER_KEY, SELLER_SECRET
PERSISTENT_DATA_PATH=`$STORE_DATA/store.db` (SQLite)
HEALTH_CHECK=process liveness via any served route (no dedicated `/health`; `docs_url`-style routes are disabled)
ROLLBACK_ARTIFACT_TYPE=release directory with a `current` symlink flip (production's existing pattern — `/opt/botconnector-store/releases/<ts>` + `current` symlink); do not reuse `apps/store/rollback-store-v6.sh` as-is, it hardcodes the old `/opt` path (DEPLOYMENT_CURRENT_STATE_REFERENCE only)

### apps/business-suite
SOURCE_PATH=apps/business-suite
DEPENDENCY_MANIFEST=packages/multichannel/requirements.lock.txt (**shared owner — see BUSINESS_SUITE_DEPENDENCY_OWNER**)
BUILD_COMMAND=`python3 -m venv packages/multichannel/venv && packages/multichannel/venv/bin/pip install -r packages/multichannel/requirements.lock.txt`
START_COMMAND=`apps/business-suite/run.sh` (canonical-relative as of 2026-09-06 — resolves its own script directory and the venv at `packages/multichannel/venv`; override with `HOST`/`PORT`/`MULTICHANNEL_VENV` env vars if needed). Proven by running this exact file unmodified from the canonical repo.
REQUIRED_ENV_NAMES=(DB host/port/name — exact names not enumerated in this pass; inferred from `botconnector_multichannel.persistence.db`)
REQUIRED_SECRET_NAMES=BC_BOTCONNECTOR_DB_PASSWORD (loaded via systemd `LoadCredential` in production, not a plain env var)
PERSISTENT_DATA_PATH=Postgres (shared platform database — no dedicated local path)
HEALTH_CHECK=HTTP GET `/health` → `{"ok":..., "database":"connected"|"disconnected"}`
ROLLBACK_ARTIFACT_TYPE=single-file entrypoint — git revert is sufficient; no release/candidate directory scheme exists for this component today
BLOCKER=none (CANONICAL_LEAK fixed 2026-09-06 — see SOURCE-MAP.md closure note)

### apps/integrasi
SOURCE_PATH=apps/integrasi
DEPENDENCY_MANIFEST=packages/multichannel/requirements.lock.txt (**shared owner**)
BUILD_COMMAND=same as business-suite
START_COMMAND=`apps/integrasi/run.sh` (canonical-relative, same shape as business-suite). Proven by running this exact file unmodified from the canonical repo.
REQUIRED_ENV_NAMES=none required (this component makes no outbound/DB calls)
REQUIRED_SECRET_NAMES=none
PERSISTENT_DATA_PATH=none
HEALTH_CHECK=HTTP GET `/health` → `{"ok":true,...}`
ROLLBACK_ARTIFACT_TYPE=git revert
BLOCKER=none (CANONICAL_LEAK fixed 2026-09-06)

```
BUSINESS_SUITE_DEPENDENCY_OWNER=packages/multichannel
INTEGRASI_DEPENDENCY_OWNER=packages/multichannel
```

### apps/restaurant
SOURCE_PATH=apps/restaurant/app
DEPENDENCY_MANIFEST=apps/restaurant/app/requirements.txt
BUILD_COMMAND=`docker build -t botconnector-restaurant:<tag> apps/restaurant/app`
START_COMMAND=`docker run -p 127.0.0.1:<port>:8080 -v <data-volume>:/data -e LICENSE_DB=/data/licenses.db -e SELLER_ADMIN_PASSWORD_HASH=... -e SELLER_SESSION_SECRET=... botconnector-restaurant:<tag>`
REQUIRED_ENV_NAMES=PANEL_MODE, BASE_PATH, COOKIE_SECURE, LICENSE_DB, LICENSE_PRIVATE_KEY
REQUIRED_SECRET_NAMES=SELLER_ADMIN_PASSWORD_HASH, SELLER_SESSION_SECRET
PERSISTENT_DATA_PATH=`$LICENSE_DB` (SQLite), `$LICENSE_PRIVATE_KEY` (EC key file)
HEALTH_CHECK=HTTP GET `/` → 200 (no dedicated `/health` route found)
ROLLBACK_ARTIFACT_TYPE=Docker image tag (production uses versioned tags, e.g. `1.3.2-store-api-v2`)

### apps/parking
SOURCE_PATH=apps/parking
DEPENDENCY_MANIFEST=apps/parking/requirements.txt (loose ranges — not yet an exact lock)
BUILD_COMMAND=`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/alembic upgrade head`
START_COMMAND=`.venv/bin/uvicorn parking.api.app:create_app --factory --host 127.0.0.1 --port <port>`
REQUIRED_ENV_NAMES=PARKING_LOG_LEVEL, PARKING_HOST, PARKING_PORT, PARKING_PAYMENT_ADAPTER, PARKING_ALLOWED_ORIGINS (see `apps/parking/.env.example` for the full documented set)
REQUIRED_SECRET_NAMES=PARKING_DATABASE_URL, PARKING_DB_PASSWORD
PERSISTENT_DATA_PATH=Postgres (dedicated `botconnector_parking` database, per its own `.env.example`)
HEALTH_CHECK=HTTP GET `/parking/api/health` → `{"status":"ok",...}` — proven 2026-09-06 against an ephemeral Postgres with all 5 canonical migrations applied
ROLLBACK_ARTIFACT_TYPE=git revert + `alembic downgrade` (alembic migration history exists under `apps/parking/alembic/versions/`)

### apps/drive
SOURCE_PATH=apps/drive
DEPENDENCY_MANIFEST=apps/drive/requirements.txt
BUILD_COMMAND=`docker build -t botconnector-drive:<tag> apps/drive`
START_COMMAND=`docker run -p 127.0.0.1:<port>:8000 -v <drive-data>:/data/drive -v <meta-data>:/data/meta -e DRIVE_INTERNAL_TOKEN=... botconnector-drive:<tag>` (production additionally uses `docker-compose.yml`'s read-only rootfs, capability drops, and a shared `botconnector-core-net` network — see that file for the hardened production shape)
REQUIRED_ENV_NAMES=DRIVE_ROOT, DRIVE_META_DB, DRIVE_MAX_UPLOAD_MB
REQUIRED_SECRET_NAMES=DRIVE_INTERNAL_TOKEN
PERSISTENT_DATA_PATH=`$DRIVE_ROOT` (file storage), `$DRIVE_META_DB` (SQLite)
HEALTH_CHECK=HTTP GET `/health` → `{"status":"ok",...}`
ROLLBACK_ARTIFACT_TYPE=Docker image tag (`docker-compose.yml` pins `botconnector-drive:0.2.0`)

### apps/ai-chat-preview
SOURCE_PATH=apps/ai-chat-preview
DEPENDENCY_MANIFEST=apps/ai-chat-preview/requirements.lock.txt
BUILD_COMMAND=`python3 -m venv venv && venv/bin/pip install -r requirements.lock.txt`
START_COMMAND=`venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port <port> --app-dir apps/ai-chat-preview`
REQUIRED_ENV_NAMES=AI_CHAT_SCHEMA, ORCHESTRATOR_URL, LOCAL_INTELLIGENCE_URL
REQUIRED_SECRET_NAMES=DATABASE_URL (contains embedded DB credential), LOCAL_INTELLIGENCE_TOKEN
PERSISTENT_DATA_PATH=Postgres (schema named by `AI_CHAT_SCHEMA`)
HEALTH_CHECK=no dedicated `/health` found; `/openapi.json` → 200 used as a liveness signal in this proof
ROLLBACK_ARTIFACT_TYPE=release directory (production path shows a dated release, e.g. `ai-chat-core-r6-20260814T035154Z`, with no `current` symlink layer — systemd points at the dated directory directly)

### apps/ai-workspace
SOURCE_PATH=apps/ai-workspace
DEPENDENCY_MANIFEST=apps/ai-workspace/requirements.lock.txt
BUILD_COMMAND=`python3 -m venv venv && venv/bin/pip install -r requirements.lock.txt`
START_COMMAND=`venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port <port> --app-dir apps/ai-workspace`
REQUIRED_ENV_NAMES=none required at import time (not fully enumerated for request-time behavior)
REQUIRED_SECRET_NAMES=none identified
PERSISTENT_DATA_PATH=not identified this pass
HEALTH_CHECK=`/openapi.json` → 200 (no dedicated `/health` found)
ROLLBACK_ARTIFACT_TYPE=git revert

### apps/admin-gate
SOURCE_PATH=apps/admin-gate
DEPENDENCY_MANIFEST=apps/admin-gate/requirements.lock.txt
BUILD_COMMAND=`python3 -m venv venv && venv/bin/pip install -r requirements.lock.txt`
START_COMMAND=`venv/bin/python -m uvicorn admin_gate:app --host 127.0.0.1 --port <port> --app-dir apps/admin-gate`
REQUIRED_ENV_NAMES=none required at import time
REQUIRED_SECRET_NAMES=not enumerated this pass (this is the platform's auth seam — likely session-signing/shared-secret material; treat as sensitive pending full audit)
PERSISTENT_DATA_PATH=not identified this pass
HEALTH_CHECK=`/openapi.json` → 200 (no dedicated `/health` found)
ROLLBACK_ARTIFACT_TYPE=git revert

### packages/multichannel
SOURCE_PATH=packages/multichannel
DEPENDENCY_MANIFEST=packages/multichannel/requirements.lock.txt
BUILD_COMMAND=`python3 -m venv venv && venv/bin/pip install -r requirements.lock.txt`
START_COMMAND=N/A — library, not directly deployed; consumed by apps/business-suite and apps/integrasi
REQUIRED_ENV_NAMES=(DB connection vars — see business-suite entry)
REQUIRED_SECRET_NAMES=BC_BOTCONNECTOR_DB_PASSWORD
PERSISTENT_DATA_PATH=Postgres (shared platform database)
HEALTH_CHECK=N/A directly — proven indirectly via business-suite/integrasi health checks
ROLLBACK_ARTIFACT_TYPE=git revert
BLOCKER=Several of this package's own acceptance/test scripts
  (`local_business/acceptance*.py`, `inventory/acceptance.py`,
  `tests/run_acceptance.sh`) hardcode `sys.path.insert(0, "/opt/botconnector-multichannel")`
  or `REPO="/opt/botconnector-multichannel"`. These do not affect the
  package's own importability (proven clean), only its own test-running —
  flagged, not fixed, in this pass.

### services/connector-core
SOURCE_PATH=services/connector-core
DEPENDENCY_MANIFEST=services/connector-core/requirements.txt (loose, declared intent) + services/connector-core/requirements.lock.txt (exact pins — **also the shared runtime for all 6 shipping services**)
BUILD_COMMAND=`python3 -m venv venv && venv/bin/pip install -r requirements.lock.txt`
START_COMMAND=`venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port <port> --app-dir services/connector-core`
REQUIRED_ENV_NAMES=not fully enumerated this pass
REQUIRED_SECRET_NAMES=not fully enumerated this pass
PERSISTENT_DATA_PATH=not identified this pass
HEALTH_CHECK=not enumerated this pass (import proof only)
ROLLBACK_ARTIFACT_TYPE=release directory + `current` symlink (production pattern: `releases/connector-core-v1-...` + `current`)

### services/finance-core
SOURCE_PATH=services/finance-core/app
DEPENDENCY_MANIFEST=services/finance-core/requirements.lock.txt
BUILD_COMMAND=`python3 -m venv services/finance-core/venv && services/finance-core/venv/bin/pip install -r services/finance-core/requirements.lock.txt`
START_COMMAND=`services/finance-core/run-finance-core.sh` (canonical-relative as of 2026-09-06 — resolves `APPDIR` and its venv from the script's own location; `FINANCE_DB_HOST` can be set directly, or resolved via `docker inspect` only if `FINANCE_CORE_POSTGRES_CONTAINER` is explicitly set). Proven by running this exact file unmodified from the canonical repo.
REQUIRED_ENV_NAMES=FINANCE_DB_HOST (or FINANCE_CORE_POSTGRES_CONTAINER to resolve it dynamically), FINANCE_CORE_ENVFILE (optional override for the external secret file location)
REQUIRED_SECRET_NAMES=FINANCE_DB_NAME, FINANCE_DB_USER, FINANCE_DB_PASSWORD
PERSISTENT_DATA_PATH=Postgres, container `botconnector-core-postgres` in production
HEALTH_CHECK=`/openapi.json` → 200 (no dedicated `/health` found)
ROLLBACK_ARTIFACT_TYPE=release directory (`releases/finance-core-r8-...`), with historical candidate releases kept under `evidence/` for reference
BLOCKER=none (CANONICAL_LEAK fixed 2026-09-06 — the application itself, `app/main.py`, never had a leak)

### services/shipping/integration
SOURCE_PATH=services/shipping/integration
DEPENDENCY_MANIFEST=services/connector-core/requirements.lock.txt (**shared runtime — see SHARED_PYTHON_RUNTIME_OWNER**)
BUILD_COMMAND=(shared venv — build once, reuse for all 7)
START_COMMAND=`venv/bin/python -m uvicorn app:APP --host 127.0.0.1 --port <port> --app-dir services/shipping/integration`
REQUIRED_ENV_NAMES=BC_LOCATION_RESOLVER_URL, BC_PROVIDER_ROUTER_URL
REQUIRED_SECRET_NAMES=none directly (peers hold their own secrets)
PERSISTENT_DATA_PATH=`$BC_SHIPPING_INTEGRATION_DB` (SQLite)
HEALTH_CHECK=not enumerated (import proof only)
ROLLBACK_ARTIFACT_TYPE=release directory (`releases/shipping-integration-v1-...`)

### services/shipping/location-resolver
SOURCE_PATH=services/shipping/location-resolver
DEPENDENCY_MANIFEST=services/connector-core/requirements.lock.txt (shared)
BUILD_COMMAND=(shared venv)
START_COMMAND=`venv/bin/python -m uvicorn app:APP --host 127.0.0.1 --port <port> --app-dir services/shipping/location-resolver`
REQUIRED_ENV_NAMES=(RajaOngkir base URL — see source for exact name)
REQUIRED_SECRET_NAMES=RAJAONGKIR_SHIPPING_COST_API_KEY
PERSISTENT_DATA_PATH=`$BC_LOCATION_RESOLVER_DB` (SQLite)
HEALTH_CHECK=not enumerated (import proof only)
ROLLBACK_ARTIFACT_TYPE=release directory

### services/shipping/location-public-gateway
SOURCE_PATH=services/shipping/location-public-gateway
DEPENDENCY_MANIFEST=services/connector-core/requirements.lock.txt (shared)
BUILD_COMMAND=(shared venv)
START_COMMAND=`venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port <port> --app-dir services/shipping/location-public-gateway`
REQUIRED_ENV_NAMES=BC_LOCATION_PUBLIC_DB (has a working default), plus a resolver base URL
REQUIRED_SECRET_NAMES=none identified
PERSISTENT_DATA_PATH=SQLite (see `BC_LOCATION_PUBLIC_DB` default path)
HEALTH_CHECK=confirmed live in production earlier this session (port 18245)
ROLLBACK_ARTIFACT_TYPE=release directory (production: `.../current` symlink → `releases/location-public-gateway-v1.1-failsoft-...`)

### services/shipping/public-gateway
SOURCE_PATH=services/shipping/public-gateway
DEPENDENCY_MANIFEST=services/connector-core/requirements.lock.txt (shared)
BUILD_COMMAND=(shared venv)
START_COMMAND=`venv/bin/python -m uvicorn app:APP --host 127.0.0.1 --port <port> --app-dir services/shipping/public-gateway`
REQUIRED_ENV_NAMES=BC_SHIPPING_INTEGRATION_URL, BC_SHIPPING_PUBLIC_TIMEOUT, BC_SHIPPING_IDEMPOTENCY_BUCKET_SECONDS
REQUIRED_SECRET_NAMES=none directly
PERSISTENT_DATA_PATH=`$BC_SHIPPING_PUBLIC_DB` (SQLite audit-log table)
HEALTH_CHECK=`GET /api/shipping/health` → `{"ok":true,...}`; real end-to-end proven via `POST /api/shipping/rates` (see EXTERNAL-PROVIDERS.md)
ROLLBACK_ARTIFACT_TYPE=release directory (production: `.../current` symlink)

### services/shipping/router
SOURCE_PATH=services/shipping/router
DEPENDENCY_MANIFEST=services/connector-core/requirements.lock.txt (shared)
BUILD_COMMAND=(shared venv)
START_COMMAND=`venv/bin/python -m uvicorn app:APP --host 127.0.0.1 --port <port> --app-dir services/shipping/router`
REQUIRED_ENV_NAMES=BC_PROVIDER_RAJAONGKIR_URL
REQUIRED_SECRET_NAMES=none directly
PERSISTENT_DATA_PATH=`$BC_SHIPPING_ROUTER_DB` (SQLite)
HEALTH_CHECK=not enumerated (import proof only)
ROLLBACK_ARTIFACT_TYPE=release directory

### services/shipping/rajaongkir-cost
SOURCE_PATH=services/shipping/rajaongkir-cost
DEPENDENCY_MANIFEST=services/connector-core/requirements.lock.txt (shared)
BUILD_COMMAND=(shared venv)
START_COMMAND=`venv/bin/python -m uvicorn app:APP --host 127.0.0.1 --port <port> --app-dir services/shipping/rajaongkir-cost`
REQUIRED_ENV_NAMES=none beyond the secret below
REQUIRED_SECRET_NAMES=RAJAONGKIR_SHIPPING_COST_API_KEY (per its own `security/SECRET_POLICY.txt`: must be supplied externally, mode 600, root:root, never embedded in source/release/logs)
PERSISTENT_DATA_PATH=`$BC_RO_DB` (SQLite request/provider-call ledger)
HEALTH_CHECK=proven live end-to-end this session (real RajaOngkir call, real quotes)
ROLLBACK_ARTIFACT_TYPE=release directory

```
SHARED_PYTHON_RUNTIME_OWNER=services/connector-core
DIRECT_REQUIREMENTS=services/connector-core/requirements.txt
EXACT_LOCK=services/connector-core/requirements.lock.txt
```
