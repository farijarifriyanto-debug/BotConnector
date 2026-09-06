# Capability Reality Registry

Evidence-first audit of what actually works, built 2026-09-06 from source
code, live health checks, one real non-destructive shipping E2E call, and
read-only systemd/journal inspection. Source existing, a service running,
or a credential being configured are each individually NOT sufficient for
STATUS=LIVE — see docs/capability-registry/EXTERNAL-PROVIDERS.md for the
provider-level version of this same rule.

Schema:
```
CAPABILITY=
PRODUCT_AREA=
UI_EXISTS=
API_EXISTS=
DATA_MODEL_EXISTS=
WRITE_PATH=
READ_PATH=
LIVE_RUNTIME=
EXTERNAL_PROVIDER=
PROVIDER_READY=
REAL_E2E_PROVEN=
STATUS=
PUBLIC_READY=
RECOMMENDATION=
```
RECOMMENDATION values: KEEP, EXPOSE, FINISH, HIDE, REMOVE_FROM_PUBLIC_IA, BETA_ONLY, MOVE_TO_EXTERNAL_ECOSYSTEM.

---

## Business Suite (apps/business-suite, thin entrypoint over packages/multichannel)

CAPABILITY=Retail POS (products, barcode, sale, returns)
PRODUCT_AREA=Business Suite / Retail
UI_EXISTS=YES (offline-first PWA shell at `/bisnis/`)
API_EXISTS=YES (`/bisnis/api/products`, `/bisnis/api/sale`, `POST /bisnis/api/return`)
DATA_MODEL_EXISTS=YES (`multichannel.product`, `multichannel.master_sku`, `local_business.sale`, `local_business.sale_line` — confirmed by reading the package's own test fixture schema, not invented)
WRITE_PATH=YES (POST endpoints exist in source)
READ_PATH=YES
LIVE_RUNTIME=botconnector-bisnis.service — confirmed healthy, `database: connected`
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=PARTIAL — health check proves the service and DB connection are live; an actual sale write was NOT exercised in this audit (would create real transactional rows — out of scope for a read-only audit)
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Inventory (central stock, location-aware)
PRODUCT_AREA=Business Suite / Retail
UI_EXISTS=YES
API_EXISTS=YES (`/bisnis/api/inventory`)
DATA_MODEL_EXISTS=YES (`multichannel.inventory_balance`)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-bisnis.service
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=PARTIAL (same basis as Retail POS above)
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Transfers (inter-branch/warehouse stock movement)
PRODUCT_AREA=Business Suite
UI_EXISTS=YES
API_EXISTS=YES (`/bisnis/api/transfers`, `POST /bisnis/api/transfer`)
DATA_MODEL_EXISTS=YES (inferred from module import `local_business.transfer`, not independently schema-verified)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-bisnis.service
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=NO (code/route exists; not exercised)
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Restaurant POS (recipe/BOM, tables, dine-in & takeaway, COGS)
PRODUCT_AREA=Business Suite / Restaurant — NOT `apps/restaurant` (see naming
  collision note in CURRENT-STATE.md)
UI_EXISTS=YES
API_EXISTS=YES (`/bisnis/api/restaurant`, `POST /bisnis/api/restaurant/order`)
DATA_MODEL_EXISTS=YES (`local_business.restaurant_order`, `restaurant_table`, `menu_item` — confirmed via the package's own test fixture)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-bisnis.service
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=PARTIAL (service+DB proven live; an order write wasn't exercised)
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Kitchen Display / Kitchen Order Tickets (KDS/KOT)
PRODUCT_AREA=Business Suite / Restaurant
UI_EXISTS=YES
API_EXISTS=YES (`/bisnis/api/kitchen`, `POST /bisnis/api/kitchen/status`)
DATA_MODEL_EXISTS=YES (`local_business.kot`)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-bisnis.service
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=NO (route exists; not exercised)
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Reports / Dashboard
PRODUCT_AREA=Business Suite
UI_EXISTS=YES
API_EXISTS=YES (`/bisnis/api/state`)
DATA_MODEL_EXISTS=UNKNOWN — depends on Finance Core's ledger, not independently verified this pass
WRITE_PATH=N/A (read-only capability)
READ_PATH=YES
LIVE_RUNTIME=botconnector-bisnis.service + botconnector-finance-core.service (a hard `Requires=`)
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=NO
STATUS=LIVE (both dependencies confirmed healthy independently)
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Offline-first sync (POS keeps working through network interruption)
PRODUCT_AREA=Business Suite
UI_EXISTS=YES (PWA/service worker: `/bisnis/manifest`, `/bisnis/sw.js`)
API_EXISTS=YES (`POST /bisnis/api/offline/sync`)
DATA_MODEL_EXISTS=YES (`local_business.offline_queue`)
WRITE_PATH=YES
READ_PATH=N/A
LIVE_RUNTIME=botconnector-bisnis.service
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=NO (route/queue exists in source; a real offline→online sync round-trip wasn't exercised)
STATUS=LIVE (code path exists and is wired; unverified in practice)
PUBLIC_READY=YES — this is presented as a headline feature ("POS tetap
  berjalan saat jaringan terganggu") on the public site; the claim is
  plausible from source but this audit did not prove it under an actual
  network interruption
RECOMMENDATION=KEEP

---

## Integrasi (apps/integrasi, thin entrypoint over packages/multichannel)

CAPABILITY=Marketplace connector cards (Shopee, Tokopedia, TikTok Shop, Blibli, Lazada)
PRODUCT_AREA=Integrasi
UI_EXISTS=YES (`/integrasi/`)
API_EXISTS=YES (`/api/public/state`, `/api/public/inventory` — both explicitly public-safe/read-only)
DATA_MODEL_EXISTS=NO real connection state — cards are hardcoded
WRITE_PATH=NO — source docstring: "Tidak memanggil keluar. Tidak membuka token."
READ_PATH=YES (static/hardcoded)
LIVE_RUNTIME=botconnector-integrasi.service (the page itself is live; what it shows is not)
EXTERNAL_PROVIDER=Shopee, Tokopedia, TikTok Shop, Blibli, Lazada — none connected
PROVIDER_READY=NO for all five
REAL_E2E_PROVEN=NO
STATUS=MOCK_ONLY (the app itself already labels every card "SEGERA_HADIR" — this is the code being honest about its own state)
PUBLIC_READY=NO
RECOMMENDATION=BETA_ONLY — the page is fine to show as a roadmap/coming-soon
  teaser (which is what it already does), just don't let a different page
  claim these are live.

---

## Konektor (services/connector-core + the public /konektor/ marketing page)

CAPABILITY=Webhook ingestion
PRODUCT_AREA=Konektor
UI_EXISTS=YES (public marketing card, "Tersedia")
API_EXISTS=YES — this is connector-core's core job (webhook → action pipeline; see acceptance/GATE_A_GATE_B_ACCEPTANCE.txt architecture diagram: "Webhook -> Connector Core Candidate -> action")
DATA_MODEL_EXISTS=YES
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-connector-core.service — confirmed enabled/active
EXTERNAL_PROVIDER=none (this is the platform receiving webhooks, not calling out)
PROVIDER_READY=N/A
REAL_E2E_PROVEN=NO (not exercised this pass, but this is core platform plumbing, not an optional third-party integration — different risk profile than the provider rows below)
STATUS=LIVE (high confidence, not proven by a live call in this pass)
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=HTTP/API generic outbound action
PRODUCT_AREA=Konektor
UI_EXISTS=YES ("Tersedia")
API_EXISTS=YES
DATA_MODEL_EXISTS=YES
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-connector-core.service
EXTERNAL_PROVIDER=none (generic — the "provider" is whatever URL the user configures)
PROVIDER_READY=N/A
REAL_E2E_PROVEN=NO
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Telegram connector (workflow → Telegram alert)
PRODUCT_AREA=Konektor
UI_EXISTS=YES ("Tersedia")
API_EXISTS=YES
DATA_MODEL_EXISTS=YES
WRITE_PATH=YES (outbox worker)
READ_PATH=N/A
LIVE_RUNTIME=3 live services (main, outbox, daily-summary)
EXTERNAL_PROVIDER=Telegram Bot API
PROVIDER_READY=YES (token configured, account free/always-ready)
REAL_E2E_PROVEN=NO (see EXTERNAL-PROVIDERS.md — deepened, still unproven for actual delivery; a real send wasn't attempted, deliberately, since it has a real user-facing side effect)
STATUS=PARTIAL_UNPROVEN
PUBLIC_READY=NO (until a delivery is confirmed)
RECOMMENDATION=FINISH — get one confirmed delivery logged, then this can move to LIVE with real evidence instead of circumstantial evidence.

CAPABILITY=Google Sheets connector (workflow ↔ spreadsheet)
PRODUCT_AREA=Konektor
UI_EXISTS=YES ("Tersedia" — **this is the overclaim**, see PUBLIC-SURFACE.md)
API_EXISTS=YES (candidate code exists)
DATA_MODEL_EXISTS=YES (candidate)
WRITE_PATH=NO real path — writes go to a "mock append sink" per the component's own acceptance doc
READ_PATH=UNKNOWN
LIVE_RUNTIME=services/connector-core (the candidate never got promoted into the running release)
EXTERNAL_PROVIDER=Google Sheets API
PROVIDER_READY=NO (`REAL_GOOGLE_WRITE=NO`, `PROMOTED=NO` per the team's own gate record)
REAL_E2E_PROVEN=NO
STATUS=MOCK_ONLY
PUBLIC_READY=NO
RECOMMENDATION=HIDE — the public badge should not say "Tersedia" for this until it's promoted past mock.

CAPABILITY=WhatsApp connector
PRODUCT_AREA=Konektor
UI_EXISTS=YES ("Segera Hadir" — correctly labeled, not an overclaim)
API_EXISTS=NO
DATA_MODEL_EXISTS=NO
WRITE_PATH=NO
READ_PATH=NO
LIVE_RUNTIME=N/A
EXTERNAL_PROVIDER=WhatsApp Business API (never integrated)
PROVIDER_READY=NO
REAL_E2E_PROVEN=NO
STATUS=PARTIAL_PROVIDER_BLOCKED
PUBLIC_READY=NO
RECOMMENDATION=KEEP (as labeled — the site is already correct here)

CAPABILITY=Payment Gateway connector (transaction-status trigger)
PRODUCT_AREA=Konektor
UI_EXISTS=YES ("Segera Hadir" — correctly labeled)
API_EXISTS=NO general-purpose payment-gateway trigger found; Midtrans exists but scoped to Store checkout specifically, not this generic connector
DATA_MODEL_EXISTS=NO
WRITE_PATH=NO
READ_PATH=NO
LIVE_RUNTIME=N/A
EXTERNAL_PROVIDER=none wired as a generic connector yet
PROVIDER_READY=NO
REAL_E2E_PROVEN=NO
STATUS=PARTIAL_PROVIDER_BLOCKED
PUBLIC_READY=NO
RECOMMENDATION=KEEP (as labeled)

---

## Shipping (services/shipping/*)

CAPABILITY=Shipping cost lookup (public rate quote)
PRODUCT_AREA=Shipping
UI_EXISTS=UNKNOWN — the consumer-facing UI for this wasn't traced (public-site `/konektor/rajaongkir/` route exists per nginx, page content not audited here)
API_EXISTS=YES (`POST /api/shipping/rates`)
DATA_MODEL_EXISTS=YES (SQLite request ledger at public-gateway; provider-call ledger at rajaongkir-cost)
WRITE_PATH=YES (audit-log inserts only, not customer data)
READ_PATH=YES
LIVE_RUNTIME=6 live services, full chain confirmed
EXTERNAL_PROVIDER=RajaOngkir
PROVIDER_READY=YES
REAL_E2E_PROVEN=YES — real call made this session, real quotes returned
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=EXPOSE (already the platform's best-evidenced capability — safe to market plainly)

---

## Parking (apps/parking)

CAPABILITY=Parking payment (QRIS/gateway)
PRODUCT_AREA=Parking
UI_EXISTS=UNKNOWN
API_EXISTS=YES (simulator-backed)
DATA_MODEL_EXISTS=YES
WRITE_PATH=YES (to the simulator only)
READ_PATH=YES
LIVE_RUNTIME=botconnector-parking.service
EXTERNAL_PROVIDER=none wired (Midtrans anticipated in code, not implemented)
PROVIDER_READY=NO
REAL_E2E_PROVEN=NO
STATUS=BETA_SANDBOX
PUBLIC_READY=NO
RECOMMENDATION=HIDE the payment claim specifically from any "live" framing; BETA_ONLY if shown at all.

CAPABILITY=Parking core (vehicle sessions, gate/exit, edge/ANPR)
PRODUCT_AREA=Parking
UI_EXISTS=UNKNOWN
API_EXISTS=YES (`parking/edge/runtime.py`, `parking/payment/adapters.py` reference gate/exit flows; alembic migrations for `gate_exit_payment_runtime`, `device_anpr_barrier_edge` exist)
DATA_MODEL_EXISTS=YES (multiple alembic migrations present)
WRITE_PATH=UNKNOWN — not exercised
READ_PATH=UNKNOWN
LIVE_RUNTIME=botconnector-parking.service — unit is active, not independently health-checked this pass
EXTERNAL_PROVIDER=none identified
PROVIDER_READY=N/A
REAL_E2E_PROVEN=NO
STATUS=PARTIAL_UNPROVEN — real migrations and code exist, but this pass did not verify the running service against them
PUBLIC_READY=UNKNOWN
RECOMMENDATION=FINISH the audit before making a public claim either way — do not assume LIVE just because payment is the only piece proven not-live.

---

## Drive (apps/drive)

CAPABILITY=File storage (My Drive)
PRODUCT_AREA=Drive
UI_EXISTS=YES (public-site `/my-drive/` page, already appropriately hedged)
API_EXISTS=YES (app.py exists)
DATA_MODEL_EXISTS=UNKNOWN — not traced
WRITE_PATH=UNKNOWN
READ_PATH=UNKNOWN
LIVE_RUNTIME=botconnector-drive.service — enabled/active
EXTERNAL_PROVIDER=Google Drive API (OAuth2), Google Picker
PROVIDER_READY=UNKNOWN (credentials configured, no proof)
REAL_E2E_PROVEN=NO
STATUS=PARTIAL_UNPROVEN
PUBLIC_READY=PARTIAL — the site's own hedged language ("core service Aktif, advanced sharing masih dalam pengembangan") is already a reasonably honest framing; don't strengthen it further without proof
RECOMMENDATION=FINISH (get a real OAuth round-trip proof), otherwise KEEP the current hedged public framing as-is.

---

## Store (apps/store)

CAPABILITY=Storefront checkout
PRODUCT_AREA=Store
UI_EXISTS=YES (`/store/` route, live)
API_EXISTS=YES (app/app.py, product/order templates)
DATA_MODEL_EXISTS=YES (products.json + order flow)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-store.service — enabled/active
EXTERNAL_PROVIDER=none required for the active manual-payment path; Midtrans configured but inactive (see EXTERNAL-PROVIDERS.md)
PROVIDER_READY=YES (for manual mode, which needs no provider); NO (for Midtrans)
REAL_E2E_PROVEN=NO (not exercised this pass)
STATUS=LIVE (manual-payment checkout)
PUBLIC_READY=YES (manual-payment checkout only — do not claim automated/QRIS payment)
RECOMMENDATION=KEEP; do not market automated payment until Midtrans is switched to production and proven.

---

## AI Preview (apps/ai-chat-preview)

CAPABILITY=AI chat
PRODUCT_AREA=AI Preview
UI_EXISTS=UNKNOWN — the frontend is a separate static build (`/var/www/botconnector-ai-chat-web-r17-...`), not audited here
API_EXISTS=YES (session/message endpoints implied by the file, not enumerated in full)
DATA_MODEL_EXISTS=YES (Postgres via DATABASE_URL/AI_CHAT_SCHEMA)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-ai-chat-core.service — enabled/active
EXTERNAL_PROVIDER=UNKNOWN — this component only proxies to an internal `ORCHESTRATOR_URL`/`LOCAL_INTELLIGENCE_URL`; whatever actually generates responses lives in the excluded AI cluster (see EXTERNAL-PROVIDERS.md)
PROVIDER_READY=UNKNOWN (out of scope — the real dependency is inside an explicitly excluded internal system)
REAL_E2E_PROVEN=NO
STATUS=PARTIAL_UNPROVEN
PUBLIC_READY=YES, labeled as BETA/preview only — matches your Phase 1 decision to scope this component to BETA/preview status regardless of the underlying provider question
RECOMMENDATION=BETA_ONLY

---

## Hidden capability found (not on your minimal list — not invented, found by tracing `apps/restaurant`)

CAPABILITY=Seller license/entitlement management (edition tiers: Essential, Lengkap, Professional, Multi Outlet)
PRODUCT_AREA=Restaurant Seller Control — a back-office admin product, not a customer-facing vertical
UI_EXISTS=YES (`/panel/restaurant/`, admin-gated)
API_EXISTS=YES
DATA_MODEL_EXISTS=YES (`licenses.db`, EC-signed license issuance)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=Docker container `restaurant-seller-control`, up 7 days at time of check
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=NO (not exercised — this is an internal admin tool, not something to probe casually)
STATUS=LIVE (container healthy at audit time)
PUBLIC_READY=N/A — this is not a customer-facing product-page capability, it's how the business licenses restaurant sellers internally; it should not appear as a public feature card at all
RECOMMENDATION=KEEP, but make sure nothing on the public site conflates this with the Restaurant POS capability (see naming collision note, CURRENT-STATE.md)

---

## Homepage Runtime (apps/homepage-runtime, imported 2026-09-06)

Runtime existence does not imply public readiness — each row below is
classified on its own evidence, not on "the route exists so it must be
fine."

CAPABILITY=Authentication (login, register, session)
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=YES
API_EXISTS=YES (`/login`, `/register`, `/logout`, `/api/auth/check`)
DATA_MODEL_EXISTS=YES (Postgres users table, implied by route bodies)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-platform-home (Docker, port 8020) — this is the platform's actual, currently-serving auth system
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=PARTIAL — proven to LOAD (GET routes return 200) against an isolated instance; a real login was not exercised against production, and this session deliberately did not submit any live form
STATUS=LIVE (this is real production traffic today, not a candidate)
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Product catalog
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=YES
API_EXISTS=YES (`/products`, `/api/products`, `/api/public-products`)
DATA_MODEL_EXISTS=YES (Postgres)
WRITE_PATH=UNKNOWN (admin-side product management not traced)
READ_PATH=YES — confirmed to render cleanly even against an empty ephemeral database in this session's isolated proof
LIVE_RUNTIME=botconnector-platform-home
EXTERNAL_PROVIDER=none
PROVIDER_READY=N/A
REAL_E2E_PROVEN=PARTIAL (load-tested in isolation, not against real data)
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=KEEP

CAPABILITY=Application gateway (`/app/{slug}/...` → Business Suite, Parking, etc.)
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=YES
API_EXISTS=YES
DATA_MODEL_EXISTS=YES (session + proxy routing table in `core_bridge.py`)
WRITE_PATH=YES (proxied writes reach the real backend products)
READ_PATH=YES
LIVE_RUNTIME=botconnector-platform-home
EXTERNAL_PROVIDER=none (internal platform routing, not a third party)
PROVIDER_READY=N/A
REAL_E2E_PROVEN=PARTIAL — confirmed the auth gate itself works correctly (unauthenticated `GET /app` → 303 redirect to `/login`, proven this session); the full authenticated proxy hop to Business Suite/Parking was not exercised
STATUS=LIVE — this is how real customers reach Business Suite/Parking through the homepage today
PUBLIC_READY=YES
RECOMMENDATION=KEEP — this is core platform plumbing, not a marketing feature; do not let a future public-site redesign accidentally drop this gateway

CAPABILITY=Support ticketing
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=YES
API_EXISTS=YES (`/support`, `/support/tickets`, `/api/support/tickets*`)
DATA_MODEL_EXISTS=YES (Postgres tickets table)
WRITE_PATH=YES
READ_PATH=YES
LIVE_RUNTIME=botconnector-platform-home
EXTERNAL_PROVIDER=none direct; SMTP is used for notification (see EXTERNAL-PROVIDERS.md note below)
PROVIDER_READY=N/A
REAL_E2E_PROVEN=PARTIAL (GET route loaded in isolation; ticket creation not exercised against real data)
STATUS=LIVE
PUBLIC_READY=YES
RECOMMENDATION=KEEP
NOTES=Redis-backed rate limiting fails open (allows the request) if Redis is unreachable — a deliberate, safe degradation, not a bug.

CAPABILITY=Health/status API
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=NO (API only)
API_EXISTS=YES (`/health`, `/api/health`, `/api/status`)
DATA_MODEL_EXISTS=NO
WRITE_PATH=NO
READ_PATH=YES
LIVE_RUNTIME=botconnector-platform-home
REAL_E2E_PROVEN=YES (confirmed stateless, returns a clean JSON payload with zero DB dependency — verified in this session's isolated proof)
STATUS=LIVE
PUBLIC_READY=N/A (operational endpoint, not a customer feature)
RECOMMENDATION=KEEP

CAPABILITY=Drive sharing/preview suite
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=YES (10 templates, dedicated CSS/JS)
API_EXISTS=YES (GET/PUT/POST/DELETE across ~7 modules)
DATA_MODEL_EXISTS=UNKNOWN
WRITE_PATH=UNKNOWN
READ_PATH=UNKNOWN
LIVE_RUNTIME=botconnector-platform-home
EXTERNAL_PROVIDER=possibly `apps/drive`'s storage API, or a separate unidentified backend — see the Duplication Check in HOMEPAGE-CONVERGENCE.md
PROVIDER_READY=UNKNOWN
REAL_E2E_PROVEN=NO
STATUS=UNKNOWN — genuinely unresolved, not rounded to LIVE or LEGACY
PUBLIC_READY=UNKNOWN
RECOMMENDATION=FINISH the backend-identification investigation before making any public claim about this either way

CAPABILITY=SmartBiz dashboard/operations/AI studio
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=YES (4 templates + 3 modules)
API_EXISTS=UNKNOWN (routes not individually itemized this pass)
DATA_MODEL_EXISTS=UNKNOWN
WRITE_PATH=UNKNOWN
READ_PATH=UNKNOWN
LIVE_RUNTIME=botconnector-platform-home
REAL_E2E_PROVEN=NO
STATUS=UNKNOWN
PUBLIC_READY=UNKNOWN
RECOMMENDATION=FINISH — needs its own dedicated audit; possible overlap with Business Suite not checked

CAPABILITY=AI support widget
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=YES
API_EXISTS=UNKNOWN
DATA_MODEL_EXISTS=UNKNOWN
LIVE_RUNTIME=botconnector-platform-home
EXTERNAL_PROVIDER=possibly the excluded internal AI cluster (ai-console/ai-tool-platform/etc.) — not confirmed
REAL_E2E_PROVEN=NO
STATUS=UNKNOWN
PUBLIC_READY=UNKNOWN
RECOMMENDATION=FINISH — if this calls the excluded AI cluster, its public status is tied to that exclusion decision, not this audit

CAPABILITY=Visual builder tools
PRODUCT_AREA=Homepage Runtime
UI_EXISTS=UNKNOWN
API_EXISTS=UNKNOWN
LIVE_RUNTIME=botconnector-platform-home
REAL_E2E_PROVEN=NO
STATUS=UNKNOWN
PUBLIC_READY=UNKNOWN
RECOMMENDATION=FINISH — not traced beyond file presence (`visual_wizard.py`, `visual_composer.py`, `creator_visual.py`)
