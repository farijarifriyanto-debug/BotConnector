# External Provider Readiness Gate

Purpose: before any capability is claimed as available on the public
botconnector.id site, this registry says whether the external dependency
behind it is actually live, or just present in code. Built 2026-09-06 from
static evidence only — config file presence (variable NAMES only, no
values read), in-repo acceptance/contract documents, and source code. **No
live calls were made to any external provider during this audit** — where
"proven" appears below, it cites an acceptance artifact already produced by
prior work, not a check performed in this pass. This list is not
necessarily complete; it covers what surfaced during source consolidation.

Classification rule applied throughout: one blocked optional integration
does not block the capability it's optional to. Example: a vertical's core
flow can be LIVE while one of its integrations is PARTIAL_PROVIDER_BLOCKED
— the site may show the vertical, just not claim the blocked integration.

---

CAPABILITY=Shipping cost lookup
COMPONENT=services/shipping/rajaongkir-cost
PROVIDER=RajaOngkir (Komerce)
API_REQUIRED=YES
PROVIDER_CREDENTIAL_REQUIRED=YES
CREDENTIAL_CONFIGURED=YES (RAJAONGKIR_SHIPPING_COST_API_KEY present in /etc/botconnector/rajaongkir-shipping-cost.env; value not read)
SANDBOX_OR_LIVE=LIVE (evidenced — see below)
ACCOUNT_OR_PLAN_REQUIRED=RajaOngkir/Komerce API plan
ACCOUNT_OR_PLAN_READY=YES
LIVE_ACCESS_ENABLED=YES
REAL_E2E_REQUEST_PROVEN=YES — cites this component's own
  acceptance/STATE_EVIDENCE.txt: RATE_REQUEST_ROWS=2, PROVIDER_CALL_ROWS=1,
  SUCCESS_PROVIDER_CALLS=1, SQLITE_INTEGRITY=ok. This is prior evidence
  produced by the team, not a call made during this audit, and its date is
  not newer than the release itself — not re-verified live today.
QUOTA_OR_RATE_LIMIT_KNOWN=NO (not documented in-repo)
BILLING_OR_COST_MODEL_KNOWN=NO (not documented in-repo)
FAILURE_HANDLING_PRESENT=YES (idempotency_key, persistent SQLite request ledger, a cache path alongside the live provider path per contract)
STATUS=LIVE
PUBLIC_READY=YES

---

CAPABILITY=Store checkout — manual payment
COMPONENT=apps/store
PROVIDER=none (manual/offline confirmation)
API_REQUIRED=NO
PROVIDER_CREDENTIAL_REQUIRED=NO
CREDENTIAL_CONFIGURED=N/A
SANDBOX_OR_LIVE=LIVE
ACCOUNT_OR_PLAN_REQUIRED=N/A
ACCOUNT_OR_PLAN_READY=YES
LIVE_ACCESS_ENABLED=YES
REAL_E2E_REQUEST_PROVEN=N/A (no external call involved)
QUOTA_OR_RATE_LIMIT_KNOWN=N/A
BILLING_OR_COST_MODEL_KNOWN=N/A
FAILURE_HANDLING_PRESENT=UNKNOWN (not audited)
STATUS=LIVE
PUBLIC_READY=YES
NOTES=/etc/botconnector-store/.env has PAYMENT_MODE=manual — this is the
  active mode today (config value read directly; not a secret).

---

CAPABILITY=Store checkout — automated Midtrans/QRIS payment
COMPONENT=apps/store
PROVIDER=Midtrans
API_REQUIRED=YES
PROVIDER_CREDENTIAL_REQUIRED=YES
CREDENTIAL_CONFIGURED=YES (MIDTRANS_SERVER_KEY present in /etc/botconnector-store/.env; value not read)
SANDBOX_OR_LIVE=SANDBOX (MIDTRANS_ENV=sandbox, read directly — not a secret)
ACCOUNT_OR_PLAN_REQUIRED=Midtrans merchant account, production activation
ACCOUNT_OR_PLAN_READY=UNKNOWN
LIVE_ACCESS_ENABLED=NO (env pinned to sandbox; PAYMENT_MODE=manual means this path isn't even the active one)
REAL_E2E_REQUEST_PROVEN=NO (no acceptance evidence found for a real Midtrans charge)
QUOTA_OR_RATE_LIMIT_KNOWN=NO
BILLING_OR_COST_MODEL_KNOWN=NO
FAILURE_HANDLING_PRESENT=UNKNOWN
STATUS=BETA_SANDBOX
PUBLIC_READY=NO
NOTES=Do not claim automated/QRIS payment is live on the public site —
  only manual payment is the active path today.

---

CAPABILITY=Parking payment
COMPONENT=apps/parking (parking/payment/)
PROVIDER=none live — code is provider-neutral (adapters.py explicitly
  documents "the only concrete adapter is the deterministic simulator;
  real providers (Midtrans, ...) [are not yet implemented]"); gateway.py
  hardcodes provider="SIMULATOR"
API_REQUIRED=NO (not yet — architecture anticipates it)
PROVIDER_CREDENTIAL_REQUIRED=NO (not configured, none expected yet)
CREDENTIAL_CONFIGURED=NO (/etc/botconnector/parking.env has only DB
  variables, no payment provider key)
SANDBOX_OR_LIVE=SANDBOX (simulator only)
ACCOUNT_OR_PLAN_REQUIRED=UNKNOWN — no real provider selected yet
ACCOUNT_OR_PLAN_READY=NO
LIVE_ACCESS_ENABLED=NO
REAL_E2E_REQUEST_PROVEN=NO
QUOTA_OR_RATE_LIMIT_KNOWN=N/A
BILLING_OR_COST_MODEL_KNOWN=N/A
FAILURE_HANDLING_PRESENT=N/A
STATUS=BETA_SANDBOX
PUBLIC_READY=NO
NOTES=Parking's non-payment flows (session/vehicle tracking etc.) were not
  audited here and may be LIVE independent of this finding — don't let
  this block claiming the rest of Parking works.

---

CAPABILITY=Spreadsheet export (Google Sheets)
COMPONENT=services/connector-core
PROVIDER=Google Sheets API (via an internal "google-sheets-bridge" hop)
API_REQUIRED=YES
PROVIDER_CREDENTIAL_REQUIRED=YES
CREDENTIAL_CONFIGURED=YES (BC_GS_BRIDGE_SECRET, BC_GS_CENTRAL_EMAIL,
  BC_GOOGLE_SHEETS_BRIDGE_SECRET present across
  /etc/botconnector/google-sheets-bridge.env and
  /etc/botconnector/connector-core-google-sheets.env; values not read)
SANDBOX_OR_LIVE=SANDBOX/MOCK per the component's own evidence
ACCOUNT_OR_PLAN_REQUIRED=Google Workspace/Cloud account with Sheets API enabled
ACCOUNT_OR_PLAN_READY=UNKNOWN
LIVE_ACCESS_ENABLED=NO
REAL_E2E_REQUEST_PROVEN=NO — cites this component's own
  acceptance/GATE_A_GATE_B_ACCEPTANCE.txt: "STATUS=CANDIDATE, GATE_A=PASS,
  GATE_B=PASS, PROMOTED=NO, REAL_GOOGLE_WRITE=NO", architecture explicitly
  routes through a "mock append sink" rather than the real Sheets API.
QUOTA_OR_RATE_LIMIT_KNOWN=NO
BILLING_OR_COST_MODEL_KNOWN=NO
FAILURE_HANDLING_PRESENT=UNKNOWN
STATUS=PARTIAL_UNPROVEN
PUBLIC_READY=NO
NOTES=Do not claim Google Sheets export is live — the team's own gate
  record says it was never promoted past mock.

---

CAPABILITY=Google Drive file storage (OAuth)
COMPONENT=apps/drive
PROVIDER=Google Drive API (OAuth2)
API_REQUIRED=YES
PROVIDER_CREDENTIAL_REQUIRED=YES
CREDENTIAL_CONFIGURED=YES (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
  GOOGLE_OAUTH_REDIRECT_URI, GOOGLE_TOKEN_ENCRYPTION_KEY present in
  /etc/botconnector/google-drive.env; values not read)
SANDBOX_OR_LIVE=UNKNOWN — not documented in-repo
ACCOUNT_OR_PLAN_REQUIRED=Google Cloud project with Drive API + OAuth consent screen
ACCOUNT_OR_PLAN_READY=UNKNOWN
LIVE_ACCESS_ENABLED=UNKNOWN
REAL_E2E_REQUEST_PROVEN=NO — no acceptance/evidence artifact found in apps/drive
QUOTA_OR_RATE_LIMIT_KNOWN=NO
BILLING_OR_COST_MODEL_KNOWN=NO
FAILURE_HANDLING_PRESENT=UNKNOWN
STATUS=PARTIAL_UNPROVEN
PUBLIC_READY=NO
NOTES=The live systemd unit (botconnector-drive.service) is active, so
  something is running — this finding is about proof of a working real
  Google OAuth round-trip, which wasn't found on disk. Confirm with the
  team before claiming this publicly; may simply be undocumented rather
  than actually broken.

---

CAPABILITY=Google Picker (file selection UI, likely paired with Drive)
COMPONENT=apps/drive (inferred — not confirmed which app consumes this)
PROVIDER=Google Picker API
API_REQUIRED=YES
PROVIDER_CREDENTIAL_REQUIRED=YES
CREDENTIAL_CONFIGURED=YES (GOOGLE_PICKER_API_KEY, GOOGLE_CLOUD_PROJECT_NUMBER present in /etc/botconnector/google-picker.env; values not read)
SANDBOX_OR_LIVE=UNKNOWN
ACCOUNT_OR_PLAN_READY=UNKNOWN
LIVE_ACCESS_ENABLED=UNKNOWN
REAL_E2E_REQUEST_PROVEN=NO
QUOTA_OR_RATE_LIMIT_KNOWN=NO
BILLING_OR_COST_MODEL_KNOWN=NO
FAILURE_HANDLING_PRESENT=UNKNOWN
STATUS=PARTIAL_UNPROVEN
PUBLIC_READY=NO
NOTES=NEEDS_DECISION — which app actually owns this credential wasn't traced.

---

CAPABILITY=Telegram business notifications (bot messaging)
COMPONENT=packages/multichannel (local_business/telegram_*.py), backing
  botconnector-bisnis-telegram.service / -outbox.service / -daily-summary.service
PROVIDER=Telegram Bot API
API_REQUIRED=YES
PROVIDER_CREDENTIAL_REQUIRED=YES
CREDENTIAL_CONFIGURED=YES (BC_BISNIS_TELEGRAM_BOT_TOKEN present in
  /etc/botconnector/bisnis-telegram.env; value not read)
SANDBOX_OR_LIVE=LIVE (real Telegram Bot API has no separate sandbox mode; a
  configured token talks to the real service by construction)
ACCOUNT_OR_PLAN_REQUIRED=A registered Telegram bot (free)
ACCOUNT_OR_PLAN_READY=YES (token configured)
LIVE_ACCESS_ENABLED=YES
REAL_E2E_REQUEST_PROVEN=UNKNOWN — the in-repo test suite
  (tests/test_telegram_v2.py) mocks the bot client throughout
  (unittest.mock), which is normal for unit tests and proves nothing
  either way about production sends. No production send log/evidence was
  reviewed in this pass.
QUOTA_OR_RATE_LIMIT_KNOWN=NO
BILLING_OR_COST_MODEL_KNOWN=N/A (Telegram Bot API is free)
FAILURE_HANDLING_PRESENT=YES (dedicated outbox worker service
  suggests a queue/retry design, not traced in detail)
STATUS=PARTIAL_UNPROVEN
PUBLIC_READY=NO (pending confirmation of a real send — this is the
  weakest-evidence case in this registry: three live, enabled systemd
  units strongly suggest it works, but this audit found no direct proof)

---

## Categories checked with no dependency found

Checked for and NOT found in the imported source: WhatsApp provider, email/SMS
provider (no SMTP/Twilio/SendGrid-shaped config), a dedicated Maps/Places/
Geocoding integration, any cloud object-storage API (S3-shaped or
otherwise) distinct from Google Drive, and a direct external AI provider
call from apps/ai-chat-preview (see next section). Absence here means "not
found during this pass," not "confirmed absent" — this was a source-code
and config audit, not exhaustive.

## AI Preview — no direct external AI provider

apps/ai-chat-preview (app.py) does not call an external LLM API directly.
It reads `DATABASE_URL`, `AI_CHAT_SCHEMA`, and forwards to
`ORCHESTRATOR_URL` (default `http://127.0.0.1:18130`, internal) and an
optional `LOCAL_INTELLIGENCE_URL`/`LOCAL_INTELLIGENCE_TOKEN`. Whatever
model actually answers a chat lives inside the internal AI cluster
(ai-console / ai-tool-platform / ai-mission-runner / etc.) — which your
Phase 1 provenance decision explicitly excluded from this platform. This
means AI Preview's true external-provider dependency, if any, is inside
excluded scope and wasn't auditable from this repo alone. Flagging rather
than guessing: don't classify AI Preview's provider readiness without also
deciding whether that internal orchestrator is in scope.

---

## Pending: shipping-specific check

Your message asking for a "SPECIFIC CHECK — SHIPPING" addition to this
gate was cut off before the detail arrived. RajaOngkir (above) is the only
shipping-related external provider found; the other five shipping services
(router, location-resolver, location-public-gateway, public-gateway,
integration) are internal composition, not external-provider dependent, as
far as this pass found. Resend the cut-off instruction if there was a more
specific check intended here.
