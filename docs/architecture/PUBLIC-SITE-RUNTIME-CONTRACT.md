# Public Site / Homepage Runtime Contract

Purpose: so a future nginx routing decision can be designed without
losing functionality. Built 2026-09-06 from the actual route declarations
in `apps/homepage-runtime/app/main.py` (not inferred from filenames) and
the confirmed content of `apps/public-site`. No routing decision is made
here — no nginx was touched.

Two owners:
- **PUBLIC_SITE** = `apps/public-site` — static marketing/presentation, zero backend
- **HOMEPAGE_RUNTIME** = `apps/homepage-runtime` — the live FastAPI app, real auth/session/gateway/data

Schema per route:
```
PATH=
OWNER=
METHODS=
STATEFUL=
AUTH_REQUIRED=
PUBLIC_SITE_DEPENDENCY=
RUNTIME_DEPENDENCY=
```

---

PATH=`/`
OWNER=CONTESTED — both have a page at this path today (live homepage app renders it dynamically; `apps/public-site/index.html` is a static alternative). This is the one collision that matters most for any future routing decision.
METHODS=GET
STATEFUL=UNKNOWN (not traced whether the live `/` does a DB read for personalization)
AUTH_REQUIRED=NO
PUBLIC_SITE_DEPENDENCY=N/A
RUNTIME_DEPENDENCY=N/A

PATH=`/products`, `/api/products`, `/api/public-products`
OWNER=HOMEPAGE_RUNTIME
METHODS=GET
STATEFUL=YES (product records; confirmed to render successfully even against an empty ephemeral DB in this session's proof, so it degrades gracefully)
AUTH_REQUIRED=NO
RUNTIME_DEPENDENCY=Postgres

PATH=`/choose/{slug}`
OWNER=HOMEPAGE_RUNTIME
METHODS=GET
STATEFUL=YES (Postgres)
AUTH_REQUIRED=UNKNOWN

PATH=`/login`, `/register`, `/logout`, `/api/auth/check`
OWNER=HOMEPAGE_RUNTIME — mandatory, cannot move to PUBLIC_SITE
METHODS=GET, POST (login/register), GET (logout, auth/check)
STATEFUL=YES (Postgres users table, session cookie `bc_session`)
AUTH_REQUIRED=NO for GET/login-register forms themselves; YES for `/api/auth/check`
RUNTIME_DEPENDENCY=Postgres, CSRF token, session cookie issuance

PATH=`/onboarding/{slug}`
OWNER=HOMEPAGE_RUNTIME
METHODS=GET, POST
STATEFUL=YES
AUTH_REQUIRED=YES (post-registration flow)

PATH=`/my-products`, `/app`, `/app/{slug}`, `/app/{slug}/{section_slug}`, `/app/{slug}/{section_slug}/create`, `/app/{slug}/{section_slug}/project`, `/app/{slug}/{section_slug}/project/action`
OWNER=HOMEPAGE_RUNTIME — mandatory, this IS the application gateway
METHODS=GET, POST
STATEFUL=YES (confirmed in this session's proof: unauthenticated `GET /app` correctly redirects 303 to `/login` — proves the auth gate is real and functioning)
AUTH_REQUIRED=YES
RUNTIME_DEPENDENCY=Postgres, session, `core_bridge.py` proxying to business-suite/parking/webhook-connector/langkah/business-automation/personal-automation/monitor-resolve

PATH=`/webhook`, `/business`, `/app/business/operations/export.csv`, `/business/open/operations`, `/business/open/whatsapp-ai-admin`, `/personal`, `/personal/open/{assistant_slug}`, `/monitor`
OWNER=HOMEPAGE_RUNTIME
METHODS=GET (mostly)
STATEFUL=YES (proxied per `core_bridge.py`)
AUTH_REQUIRED=YES (assumed — not individually verified)

PATH=`/docs`, `/status`, `/privacy`, `/terms`, `/security`, `/.well-known/security.txt`
OWNER=HOMEPAGE_RUNTIME today; CANDIDATE_FOR_PUBLIC_SITE if content is purely static (not verified — `/status` in particular likely does a live check)
METHODS=GET
STATEFUL=`/status` likely YES, others likely NO
AUTH_REQUIRED=NO
PUBLIC_SITE_DEPENDENCY=`apps/public-site` already has its own `/docs/` page — content parity with the runtime's `/docs` was NOT verified; do not assume they say the same thing

PATH=`/support`, `/support/tickets`, `/support/ticket/{public_reference}`, `/api/support/tickets`, `/api/support/tickets/{identifier}`
OWNER=HOMEPAGE_RUNTIME — mandatory if this is the platform's real support channel
METHODS=GET, POST
STATEFUL=YES (Postgres tickets, Redis rate-limiting — confirmed in code; Redis fails open if unreachable, so this degrades safely rather than blocking support intake)
AUTH_REQUIRED=NO for submitting (identified by email in the form), YES implied for viewing ticket history by user
RUNTIME_DEPENDENCY=Postgres, Redis (optional/fail-open)

PATH=`/health`, `/api/health`, `/api/status`
OWNER=HOMEPAGE_RUNTIME
METHODS=GET
STATEFUL=NO (confirmed: returns a static JSON payload with no DB touch — proven in this session's isolated proof)
AUTH_REQUIRED=NO
PUBLIC_SITE_DEPENDENCY=N/A — this is an operational endpoint, not a marketing concern

PATH=Drive sharing/preview suite (multiple GET/PUT/POST/DELETE routes; backed by `drive_ui.py`, `drive_shared_ui.py`, `drive_preview_ui.py`, `drive_public_share_ui.py`, `drive_file_request_ui.py`, `google_drive_*_ui.py`, `admin_storage.py`)
OWNER=HOMEPAGE_RUNTIME today — **relationship to `apps/drive` UNRESOLVED**, see Duplication Check below
METHODS=GET, PUT, POST, DELETE
STATEFUL=YES
AUTH_REQUIRED=YES (mostly; some `_public_` variants are explicitly for unauthenticated recipients of a shared link)

PATH=SmartBiz dashboard/operations/AI studio (`smartbiz_dashboard.py`, `smartbiz_operations_ui.py`, `smartbiz_ai_studio.py`)
OWNER=HOMEPAGE_RUNTIME today — **relationship to Business Suite UNRESOLVED**
METHODS=GET, POST (exact routes not individually itemized — declarations are interleaved with the Drive CRUD block, lines ~5100-9400)
STATEFUL=YES
AUTH_REQUIRED=YES (assumed)

PATH=AI support widget (`support_ai_*.py`, `ai_bridge.py`)
OWNER=HOMEPAGE_RUNTIME today — **may call the excluded internal AI cluster**, per your Phase 1 decision that cluster is out of scope for this platform
METHODS=GET, POST
STATEFUL=UNKNOWN
AUTH_REQUIRED=UNKNOWN

PATH=Visual builder tools (`visual_wizard.py`, `visual_composer.py`, `creator_visual.py`)
OWNER=HOMEPAGE_RUNTIME today — UNKNOWN scope, not traced beyond file presence
METHODS=UNKNOWN
STATEFUL=UNKNOWN
AUTH_REQUIRED=UNKNOWN

---

## Public-site's own pages (all PUBLIC_SITE, zero backend, confirmed)

`/business-suite/`, `/retail/`, `/restaurant/`, `/parking/`, `/my-drive/`,
`/integrations/`, `/konektor/`, `/resep/`, `/solusi/`, `/docs/` — all
static HTML, zero forms, zero fetch/XHR calls, confirmed by direct
inspection. Their CTAs already correctly point to
`https://botconnector.id/login` / `.../register` (absolute URLs into
HOMEPAGE_RUNTIME) rather than trying to reimplement auth — this candidate
was built with the right instinct for a future split.

```
RUNTIME_ROUTES_COUNT=~17 functional groups / dozens of individual path declarations (see HOMEPAGE-CONVERGENCE.md for the full raw list)
PUBLIC_SITE_ROUTES_COUNT=11 static pages, 0 dynamic routes
ROUTE_COLLISIONS=1 confirmed (`/`) — everything else the two sides currently serve is disjoint, because the candidate implements presentation only and the runtime implements everything dynamic
```

No routing decision is made in this document. The one real collision
(`/`) is exactly the reason `docs/deployment/CUTOVER-PLAN.md`'s Wave 1
was retired rather than executed — resolving it is a future, explicit,
separately-approved nginx change.
