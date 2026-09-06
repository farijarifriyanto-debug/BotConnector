# External Provider Readiness Gate

Evidence-first: source existing ≠ live. Service running ≠ live. Credential
configured ≠ provider ready. Every row below states exactly what evidence
backs it and what evidence is still missing. Updated 2026-09-06 (deepened
per follow-up instruction — RajaOngkir/shipping now has a real live
request proof from this session; Telegram was investigated further and
remains unproven for delivery specifically, with an operational note).

Schema per row:
```
PROVIDER=
CAPABILITY=
CODE_EXISTS=
CONFIGURED=
SANDBOX_OR_LIVE=
REAL_E2E_PROVEN=
ACCOUNT_PLAN_READY=
FAILURE_HANDLING=
PUBLIC_READY=
STATUS=
```
Allowed STATUS: LIVE, PARTIAL_UNPROVEN, PARTIAL_PROVIDER_BLOCKED,
BETA_SANDBOX, MOCK_ONLY, LEGACY, REMOVE_OR_REPLACE.

---

PROVIDER=RajaOngkir (Komerce)
CAPABILITY=Shipping cost lookup
CODE_EXISTS=YES (services/shipping/rajaongkir-cost, services/shipping/public-gateway, services/shipping/integration)
CONFIGURED=YES (RAJAONGKIR_SHIPPING_COST_API_KEY present in /etc/botconnector/rajaongkir-shipping-cost.env; value not read)
SANDBOX_OR_LIVE=LIVE
REAL_E2E_PROVEN=YES — **proven twice, independently**: (1) the component's own prior acceptance/STATE_EVIDENCE.txt records SUCCESS_PROVIDER_CALLS=1; (2) THIS SESSION performed a real, non-destructive `POST http://127.0.0.1:18244/api/shipping/rates` (origin "Jakarta Pusat", destination "Bandung", weight 1000g, courier JNE) and received real resolved addresses (postal codes 10520, 40614) and real JNE tariffs (REG 12000 IDR, YES 24000 IDR, SPS 403000 IDR, etc.) in ~1.5s. This is a live call made during this audit, not just cited evidence.
ACCOUNT_PLAN_READY=YES (a live call succeeded, which requires a working account/plan)
FAILURE_HANDLING=YES (idempotency_key + bucketed dedup at public-gateway, persistent SQLite request ledger, distinct 502/503/504 error paths for upstream failure/timeout/bad-response)
PUBLIC_READY=YES
STATUS=LIVE

---

PROVIDER=Midtrans
CAPABILITY=Store checkout — automated/QRIS payment
CODE_EXISTS=YES (apps/store/configure-midtrans.sh + app)
CONFIGURED=YES (MIDTRANS_SERVER_KEY present in /etc/botconnector-store/.env; value not read)
SANDBOX_OR_LIVE=SANDBOX (MIDTRANS_ENV=sandbox — read directly, not a secret)
REAL_E2E_PROVEN=NO (no acceptance evidence found for a real charge; also not the active path — see below)
ACCOUNT_PLAN_READY=UNKNOWN
FAILURE_HANDLING=UNKNOWN
PUBLIC_READY=NO
STATUS=BETA_SANDBOX
NOTES=The store's actual active payment mode today is PAYMENT_MODE=manual — Midtrans isn't even switched on as the live path right now, sandbox status aside.

---

PROVIDER=none (manual/offline confirmation)
CAPABILITY=Store checkout — manual payment
CODE_EXISTS=YES
CONFIGURED=N/A
SANDBOX_OR_LIVE=LIVE
REAL_E2E_PROVEN=N/A (no external call involved)
ACCOUNT_PLAN_READY=YES
FAILURE_HANDLING=UNKNOWN (not audited)
PUBLIC_READY=YES
STATUS=LIVE
NOTES=This, not Midtrans, is the store's real active checkout path today.

---

PROVIDER=none (deterministic simulator only)
CAPABILITY=Parking payment
CODE_EXISTS=YES (apps/parking/parking/payment/{adapters,gateway,simulator}.py — code explicitly documents "the only concrete adapter is the deterministic simulator; real providers (Midtrans, ...) [not yet implemented]", gateway.py hardcodes provider="SIMULATOR")
CONFIGURED=NO (/etc/botconnector/parking.env has only DB variables, no payment provider key)
SANDBOX_OR_LIVE=SANDBOX (simulator only — no real provider selected yet)
REAL_E2E_PROVEN=NO
ACCOUNT_PLAN_READY=NO
FAILURE_HANDLING=N/A
PUBLIC_READY=NO
STATUS=BETA_SANDBOX
NOTES=Parking's non-payment flows (sessions, gate/exit, ANPR/edge) were not re-audited here and may be LIVE independent of this — don't let this block the rest of Parking.

---

PROVIDER=Google Sheets API (via internal "google-sheets-bridge" hop)
CAPABILITY=Spreadsheet export
CODE_EXISTS=YES (services/connector-core)
CONFIGURED=YES (BC_GS_BRIDGE_SECRET, BC_GS_CENTRAL_EMAIL, BC_GOOGLE_SHEETS_BRIDGE_SECRET present; values not read)
SANDBOX_OR_LIVE=neither — routes through a mock sink, never reached a real/sandbox Google endpoint
REAL_E2E_PROVEN=NO — the component's own acceptance/GATE_A_GATE_B_ACCEPTANCE.txt states outright: `STATUS=CANDIDATE, PROMOTED=NO, REAL_GOOGLE_WRITE=NO`, architecture explicitly named "-> mock append sink"
ACCOUNT_PLAN_READY=UNKNOWN
FAILURE_HANDLING=UNKNOWN
PUBLIC_READY=NO
STATUS=MOCK_ONLY
NOTES=**This is the one clear public-site overclaim found in this audit.** The public site's `/konektor/` page marks Google Sheets with a "Tersedia" (Available) badge. The team's own gate record says the opposite. See PUBLIC-SURFACE.md.

---

PROVIDER=Google Drive API (OAuth2)
CAPABILITY=File storage / My Drive
CODE_EXISTS=YES (apps/drive)
CONFIGURED=YES (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI, GOOGLE_TOKEN_ENCRYPTION_KEY present; values not read)
SANDBOX_OR_LIVE=UNKNOWN — not documented in-repo
REAL_E2E_PROVEN=NO — no acceptance/evidence artifact found in apps/drive; the live systemd unit is active (something runs), but that's not proof of a working OAuth round-trip
ACCOUNT_PLAN_READY=UNKNOWN
FAILURE_HANDLING=UNKNOWN
PUBLIC_READY=NO (for the OAuth-backed "connected to your Google account" claim specifically — see notes)
STATUS=PARTIAL_UNPROVEN
NOTES=The public-site My Drive page already hedges appropriately ("Aktif" for the core storage service, "masih dalam pengembangan" for advanced sharing) — it does not specifically claim a proven Google OAuth integration, so no overclaim was found here, just missing proof.

---

PROVIDER=Google Picker API
CAPABILITY=File selection UI (likely paired with Drive)
CODE_EXISTS=UNKNOWN — which app actually consumes GOOGLE_PICKER_API_KEY was not traced
CONFIGURED=YES (GOOGLE_PICKER_API_KEY, GOOGLE_CLOUD_PROJECT_NUMBER present; values not read)
SANDBOX_OR_LIVE=UNKNOWN
REAL_E2E_PROVEN=NO
ACCOUNT_PLAN_READY=UNKNOWN
FAILURE_HANDLING=UNKNOWN
PUBLIC_READY=NO
STATUS=PARTIAL_UNPROVEN
NOTES=NEEDS_DECISION — owner app not identified.

---

PROVIDER=Telegram Bot API
CAPABILITY=Business notifications (low-stock alerts, daily summary, outbound messaging)
CODE_EXISTS=YES (packages/multichannel local_business/telegram_*.py, backing 3 live services: outbox, daily-summary, main bisnis-telegram)
CONFIGURED=YES (BC_BISNIS_TELEGRAM_BOT_TOKEN present in /etc/botconnector/bisnis-telegram.env; value not read)
SANDBOX_OR_LIVE=LIVE by construction (the Telegram Bot API has no sandbox mode — a configured token talks to the real API)
REAL_E2E_PROVEN=NO, deepened this pass and still unproven for actual message delivery: the in-repo test suite mocks the bot client throughout (normal for unit tests, proves nothing about production). Read-only journalctl inspection of `botconnector-bisnis-telegram-outbox.service` found it logging `low_stock_outbox_poll_error (OperationalError)` roughly every 2s for about a minute earlier today, then a restart at 09:35:37 (timed with an observed Postgres/Redis credential rotation), after which it reports `db_poll_ready` with no further errors in the visible log window. This shows the worker is alive and DB-connected post-restart, but is still not proof a Telegram message was actually delivered.
ACCOUNT_PLAN_READY=YES (token configured; Telegram bots are free)
FAILURE_HANDLING=YES (dedicated outbox worker implies a queue/retry design; not traced in code detail)
PUBLIC_READY=NO (pending an actual delivery confirmation)
STATUS=PARTIAL_UNPROVEN
NOTES=Strongest circumstantial case among the "unproven" rows — three live, enabled, currently-healthy systemd units and a real credential — but this audit stops short of claiming proof without a delivery log or send confirmation, and did not attempt a live send itself (unlike the shipping cost lookup, sending a real Telegram message has a real user-facing side effect, so this pass deliberately did not trigger one).

---

PROVIDER=none found
CAPABILITY=WhatsApp messaging
CODE_EXISTS=NO — zero WhatsApp-shaped code, config, or credentials found anywhere in the imported source
CONFIGURED=NO
SANDBOX_OR_LIVE=N/A
REAL_E2E_PROVEN=NO
ACCOUNT_PLAN_READY=NO
FAILURE_HANDLING=N/A
PUBLIC_READY=NO
STATUS=PARTIAL_PROVIDER_BLOCKED
NOTES=The public site's `/konektor/` page already labels this "Segera Hadir" (Coming Soon) — correctly, not an overclaim. Listed here only for completeness of the registry, since the site does surface the name.

---

## Categories checked with no dependency found

Maps/Places/Geocoding, SMS, email (SMTP/Twilio/SendGrid-shaped), and any
object-storage API distinct from Google Drive — none found in the imported
source. Absence here means "not found during this pass," not "confirmed
absent."

## AI Preview — no direct external AI provider

apps/ai-chat-preview does not call an external LLM API directly — it
forwards to an internal `ORCHESTRATOR_URL` (127.0.0.1:18130) and an
optional `LOCAL_INTELLIGENCE_URL`. Whatever model actually answers a chat
lives inside the excluded internal AI cluster (ai-console,
ai-tool-platform, ai-mission-runner, etc.), per your Phase 1 provenance
decision. AI Preview's true external-provider dependency, if any, is
inside excluded scope and wasn't auditable from this repo alone.
