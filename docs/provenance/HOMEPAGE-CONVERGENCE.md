# Homepage Convergence Audit

2026-09-06. Corrects a real provenance error from an earlier phase (which
treated the live botconnector.id apex as static/no-source) and determines
the actual relationship between the live homepage runtime and the
imported `apps/public-site` candidate. No production mutation was made to
produce this document — everything below is read-only investigation, plus
one isolated static-file-server preview of the candidate on a disposable
port.

## Live homepage provenance — revalidated

```
LIVE_CONTAINER=botconnector-platform-home
LIVE_IMAGE=botconnector-platform-home:tenantization-v1-20260828
LIVE_PORT=127.0.0.1:8020 (proxied from nginx `location /` on botconnector.id's HTTPS apex)
LIVE_WORKING_DIR=/app (in-container)
LIVE_SOURCE=/opt/botconnector-platform-starter-v0.3/homepage
LIVE_SOURCE_DELIVERY_MODE=baked into the image at build time — NOT a live bind-mount; the running container does not mount the source directory, only runtime data and credential files (`/var/lib/botconnector-platform`, `/etc/botconnector/credentials/homepage-db-password` → `/run/secrets/postgres_password`, `/etc/botconnector/credentials/redis-password` → `/run/secrets/redis_password`)
```

**Hash verification**: extracted the live image's `/app/app` contents via
a throwaway, read-only `docker run --rm --entrypoint sh ... sha256sum`
(the running container itself was never touched) and compared against
`/opt/botconnector-platform-starter-v0.3/homepage/app` on disk. **All 94
files in the source's `app/` directory have an exact SHA256 match in the
running image.** (The image had 3 additional hashed files not compared —
`requirements.txt` and two `tests/*.py` files that live at `/app/`
root/`/app/tests/`, outside the `app/` subdirectory this check scoped to;
not a discrepancy, just outside what was hashed.)

```
LIVE_HOMEPAGE_PROVENANCE=PASS
```

## 1. Live homepage capability inventory

Read from `main.py` (9,478 lines) route declarations, `core_bridge.py`,
and `config.py` — not inferred from filenames. This is a genuine
application, not a marketing page: real auth with session cookies, a
product-routing gateway to other backend services, Postgres and Redis in
active use, a support ticketing system with its own API, and a large
Drive-sharing/preview feature set.

```
POSTGRES_USED_BY_HOMEPAGE=YES (credential mount confirmed: /run/secrets/postgres_password; DB-backed login/register/tickets confirmed by route bodies)
REDIS_USED_BY_HOMEPAGE=YES (confirmed in code: `check_redis_rate_limit(...)` gates ticket creation; credential mount also present)
SESSION_USAGE=YES — issues `bc_session` cookie (config.py: `core_cookie_name = "bc_session"`). This is the SAME cookie name used elsewhere in the platform (seen earlier in packages/multichannel's own test fixtures) — meaning this app is very likely the platform's actual session-issuing authority, not an independent login system.
DYNAMIC_WRITES_EXIST=YES (login/register write user records; support tickets are created and stored; Drive-sharing routes include PUT/DELETE, i.e. real mutations)
```

### Route inventory (grouped by function — not exhaustive to every line of a 9,478-line file, but every `@app.get/post/put/delete` declaration was read)

| FUNCTION | ROUTE(S) | BACKEND_DEPENDENCY | CUSTOMER_IMPACT | REQUIRED_ON_FUTURE_PUBLIC_SITE |
|---|---|---|---|---|
| Homepage / marketing landing | `GET /` | none (or light DB for personalization — not confirmed) | High — first impression | YES, but content-wise `apps/public-site`'s `/` already covers this differently |
| Product catalog | `GET /products`, `GET /api/products`, `GET /api/public-products` | Postgres (product records) | Medium | YES — no static equivalent exists in the candidate today |
| Choose/select a product | `GET /choose/{slug}` | Postgres | Medium | YES |
| **Authentication** | `GET/POST /login`, `GET/POST /register`, `GET /logout`, `GET /api/auth/check` | Postgres (users), session cookie issuance, CSRF | **Critical** — this is real login/registration for the whole platform | **YES, mandatory** — no static site can replace this |
| Onboarding flow | `GET/POST /onboarding/{slug}` | Postgres, session | High (new customer activation) | YES |
| My products / per-product app hosting | `GET /my-products`, `GET /app`, `GET /app/{slug}`, `GET /app/{slug}/{section_slug}`, `GET/POST /app/{slug}/{section_slug}/create`, `GET/POST .../project`, `.../project/action` | Postgres, session, and (via `core_bridge.py`'s `CANDIDATE_TO_CORE` map) **proxies through to real backend products**: `business-suite`, `parking`, `webhook-connector`, `langkah`, `business-automation`, `personal-automation`, `monitor-resolve` | **Critical** — this is literally how a logged-in customer reaches Business Suite/Parking/etc. through the homepage | **YES, mandatory** — this is a live application gateway, not content |
| Business/personal automation panels | `GET /business`, `GET /app/business/operations/export.csv`, `GET /business/open/operations`, `GET /business/open/whatsapp-ai-admin`, `GET /personal`, `GET /personal/open/{assistant_slug}` | Postgres, proxied to `business-automation`/`personal-automation` per `core_bridge.py` | High | YES |
| Monitoring | `GET /monitor`, `GET /webhook` | proxied to `monitor-resolve`/`webhook-connector` | Medium | UNKNOWN — scope/audience not established from route alone |
| Static/informational pages | `GET /docs`, `/status`, `/privacy`, `/terms`, `/security`, `/.well-known/security.txt` | mostly static rendering, `/status` likely live-checks something | Low-medium | PARTIAL — `apps/public-site` has a `/docs/` page already; content parity not verified |
| **Support ticketing** | `GET/POST /support`, `GET /support/tickets`, `GET /support/ticket/{public_reference}`, `POST/GET /api/support/tickets`, `GET /api/support/tickets/{identifier}` | Postgres (tickets), Redis (rate limiting — confirmed in code) | High — real customer support channel | **YES, mandatory** if this is the platform's actual support intake |
| Health/status API | `GET /health`, `GET /api/health`, `GET /api/status` | light — dependency checks | Low (operational) | YES (ops necessity, not marketing) |
| **Drive sharing/preview suite** | multiple GET/PUT/POST/DELETE routes around lines 5100–9400 (paired with `drive_ui.py`, `drive_shared_ui.py`, `drive_preview_ui.py`, `drive_public_share_ui.py`, `drive_file_request_ui.py`, `google_drive_*_ui.py`, `admin_storage.py`) | Postgres + file storage; overlaps conceptually with `apps/drive` | High for any customer using file sharing | **CANONICAL_COMPONENT_GAP candidate** — see Section 7; may substantially overlap with `apps/drive`, relationship unverified |
| SmartBiz dashboard/operations/AI studio | `smartbiz_dashboard.py`, `smartbiz_operations_ui.py`, `smartbiz_ai_studio.py` (routes embedded among the PUT/POST/DELETE block, not individually itemized here) | Postgres, likely proxied products | Medium-high | UNKNOWN — may overlap with Business Suite; not verified this pass |
| AI-powered support widget | `support_ai_knowledge.py`, `support_ai_tools.py`, `support_ai_inference.py`, `support_ai_service.py`, `support_ai_routes.py`, `ai_bridge.py` | likely calls the internal AI cluster (excluded scope per your Phase 1 decision) | Medium | UNKNOWN — if it calls the excluded AI cluster, its fate is tied to that exclusion decision, not this convergence |
| Visual builder tools | `visual_wizard.py`, `visual_composer.py`, `creator_visual.py` | Postgres, likely proxied | UNKNOWN | UNKNOWN — not enough evidence this pass to classify |

**What was NOT individually traced**: the ~20 PUT/POST/DELETE routes in
the 5100–9400 line range (mostly Drive/admin/SmartBiz CRUD, based on
surrounding file names) were catalogued by declaration only, not read
line-by-line — a 9,478-line file's full behavior wasn't exhaustively
audited in this pass. Treat the Drive/SmartBiz/AI-widget rows above as
"real and substantial, exact scope unresolved," not "fully understood."

## 2. Public-site candidate inventory

```
PAGES=index, business-suite, retail, restaurant, parking, my-drive, konektor, resep, solusi, docs, integrations (11 static HTML pages)
ROUTES=N/A (static files only, no server-side routing)
FORMS=0 (confirmed: zero `<form>` elements anywhere in the candidate)
JS_INTERACTIONS=0 (confirmed: zero `fetch`/`XMLHttpRequest`/`axios` calls anywhere)
APPLICATION_CTAS=login/register links point to absolute `https://botconnector.id/login` and `.../register` — i.e., the candidate ALREADY defers auth to the live app rather than attempting to reimplement it
DYNAMIC_FUNCTIONS=none
STATIC_ONLY_FUNCTIONS=all of it — marketing copy, product descriptions, navigation, CTAs
```

**What the candidate does NOT contain, confirmed by absence, not
inference**: authentication, session issuance, product catalog API, the
`/app/{slug}/...` gateway to backend products, support ticketing, Drive
sharing/preview, SmartBiz dashboards, health/status APIs, or any
Postgres/Redis usage of any kind.

## 3. Feature-parity matrix

| FUNCTION | LIVE_HOMEPAGE | PUBLIC_SITE_CANDIDATE | PARITY |
|---|---|---|---|
| Marketing landing / product storytelling | Present, different IA (Products/Bisnis/Connect-v2/Docs/Status/Support/Login/Register nav) | Present, different IA (Business Suite/Retail/Restaurant/Parking/My Drive/Integrations/Konektor/Resep/Solusi/Docs nav) | CANDIDATE_BETTER for presentation depth per vertical (the candidate has a dedicated page per product with far more marketing detail); LIVE_ONLY for the actual live nav structure |
| Authentication (login/register/logout/session) | Present, real | Absent (defers to live via absolute link) | LIVE_ONLY_REQUIRED — SHOULD_PRESERVE=YES |
| Product catalog API | Present, real (Postgres-backed) | Absent | LIVE_ONLY_REQUIRED — SHOULD_PRESERVE=YES |
| Application gateway (`/app/{slug}/...` → business-suite/parking/etc.) | Present, real | Absent | LIVE_ONLY_REQUIRED — SHOULD_PRESERVE=YES, this is core platform plumbing |
| Support ticketing | Present, real (Postgres+Redis) | Absent | LIVE_ONLY_REQUIRED — SHOULD_PRESERVE=YES if this is the platform's actual support channel (not verified against any alternative) |
| Health/status API | Present | Absent | LIVE_ONLY_REQUIRED (operational necessity) |
| Drive sharing/preview suite | Present, extensive | Absent (candidate only markets Drive via `/my-drive/` static page) | LIVE_ONLY_REQUIRED or CANDIDATE_ONLY overlap with `apps/drive` — UNKNOWN, needs a dedicated comparison against `apps/drive`'s actual routes before deciding if this is duplicate or additive |
| SmartBiz dashboard/operations/AI studio | Present | Absent | UNKNOWN — possible overlap with Business Suite, not verified |
| AI support widget | Present | Absent | UNKNOWN — may be tied to the excluded internal AI cluster |
| Visual builder tools | Present | Absent | UNKNOWN |
| Static informational pages (docs/status/privacy/terms/security) | Present | Partial (candidate has `/docs/`, not the others) | PARITY for docs concept; MISSING_IN_CANDIDATE for privacy/terms/security/status |

```
LIVE_FUNCTIONS_COUNT=~17 distinct functional groups identified from route declarations (see table above)
PUBLIC_SITE_FUNCTIONS_COUNT=1 (static marketing presentation — everything else is absent)
PARITY_FUNCTIONS=0 (no function exists identically in both; the marketing/landing concept exists in both but with materially different IA and depth, not true parity)
LIVE_ONLY_REQUIRED_FUNCTIONS=6 (auth, product catalog API, application gateway, support ticketing, health/status API, and — pending verification — Drive sharing if it's not truly redundant with apps/drive)
LIVE_ONLY_LEGACY_FUNCTIONS=0 identified — no live function was found to be safely dismissible as legacy; several are UNKNOWN rather than confirmed-safe-to-drop, which is different and should not be rounded down to "legacy"
CANDIDATE_ONLY_FUNCTIONS=0 (the candidate's per-vertical marketing depth is CANDIDATE_BETTER, not something the live site lacks structurally — it's a presentation upgrade, not a new function)
```

## 4. Browser comparison (read-only — no form was submitted against the live site)

Ran Playwright across desktop (1440×900), laptop (1280×800), and mobile
(390×844), navigating the real `https://botconnector.id/` (read-only GET
only — no login/register form was filled or submitted, deliberately, to
avoid any state-mutating interaction with a live authentication system)
against the candidate served locally on a disposable port. Cleaned up
(browser, venv, cache) after.

- Live nav (all viewports): `/`, `/products`, `/bisnis/`, `/connect-v2`, `/docs`, `/status`, `/support`, `/login`, `/register`
- Candidate nav (all viewports): `/`, `business-suite/`, `retail/`, `restaurant/`, `parking/`, `my-drive/`, `integrations/`, `konektor/`, `resep/`, `solusi/`, `docs/`, plus absolute links to `https://botconnector.id/login` and `.../register`
- Live title: "BotConnector — Platform Operasional Bisnis, POS Kasir & Otomasi Terhubung"
- Candidate title: "BotConnector — Satu Platform untuk Operasional Bisnis Anda"
- Zero console errors on either site, all three viewports
- Both had zero `<form>` elements on their respective homepages specifically (live's login/register forms live on their own sub-pages, not the root — consistent, not a discrepancy)

No screenshots were retained (kept out of the repo and out of any
directory, per your instruction to keep evidence outside Git unless
intentionally documented — none was intentionally documented as an image
asset this pass; the JSON comparison data above is the documented
evidence instead).

## 6. Canonical structure decision

```
CONVERGENCE_DECISION=OPTION_B_FRONTEND_BACKEND_SPLIT
```

Reasoning: the candidate is a well-built, more thorough marketing
presentation layer with zero functional overlap risk (it does nothing
dynamic today), and it already shows the right instinct — its
login/register CTAs point at the live app rather than trying to
reimplement auth. The live homepage's actual *application* behavior
(auth, session issuance, product-routing gateway, support ticketing,
health checks, and — pending its own review — Drive sharing/SmartBiz/AI
widget/visual builder) is real, load-bearing platform infrastructure, not
decorative content, and none of it exists in the candidate. Neither
OPTION_A (the candidate can't safely replace something it doesn't
implement) nor doing nothing (OPTION_D) fits the evidence — a split is the
honest, minimal-risk structure: keep the candidate as the future
`apps/public-site` presentation layer, and give the live runtime's real
capability its own canonical home before ever routing the apex through
the candidate alone.

## 7. Monorepo gap

```
CANONICAL_COMPONENT_GAP=YES
```

Proposed canonical target (ponytail: smallest structure that preserves
the real functionality, not a redesign):

```
apps/homepage-runtime/
```

This would house what's currently `/opt/botconnector-platform-starter-v0.3/homepage`
— the FastAPI app (`main.py`, `config.py`, `core_bridge.py`,
`ai_bridge.py`, `automation_proxy.py`, the `support_ai_*` modules, the
`drive_*_ui.py`/`google_drive_*_ui.py`/`admin_storage.py` modules,
`smartbiz_*` modules, `visual_*`/`creator_visual.py`, `public_products.py`,
`public_trial.py`, and their templates/static assets) — i.e., import it
the same way every other component in this consolidation was imported:
COPY, dependency-lock it, prove it builds/imports/starts in isolation,
document its provenance — **not done in this turn**, this section only
proposes the target, per your explicit instruction not to implement the
merge now.

Before that import happens, two things need resolving (flagged, not
assumed):
1. Whether the Drive sharing suite here is genuinely additional to
   `apps/drive`, or a duplicate/overlapping implementation that should be
   reconciled rather than imported twice.
2. Whether the SmartBiz dashboard/AI-studio and AI support widget
   functionality overlaps with Business Suite or the excluded internal AI
   cluster, respectively.

## 8. Wave 1 replan (conceptual only — not executed)

The original Wave 1 ("point an nginx location at `apps/public-site`,
additive, zero downtime") is retired. A corrected Wave 1 cannot safely
touch the apex at all until `apps/homepage-runtime` (or equivalent) exists
and is proven, because the apex currently carries real auth/session/
gateway/support traffic that `apps/public-site` alone cannot serve.

Two honest options going forward, neither executed here:
- Preview `apps/public-site` in isolation (localhost/high port) for design
  review — safe, already demonstrated in this audit, no nginx change.
- Any actual production-facing placement (a new path, a subdomain, or
  eventually the apex) is a separate nginx mutation requiring its own
  explicit approval, exactly as you flagged — not something to default
  into just because a preview looked good.

```
READY_FOR_APEX_CUTOVER=NO
```
