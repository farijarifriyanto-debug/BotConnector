# Public Surface — Source of Truth for botconnector.id

This is the gate: nothing goes on the public site as production-ready
unless it appears in PUBLIC_READY_CAPABILITIES below. Built 2026-09-06
from docs/capability-registry/CAPABILITIES.md and
docs/capability-registry/EXTERNAL-PROVIDERS.md, cross-checked against the
actual text of `apps/public-site` page-by-page.

Rule (yours, restated): `STATUS=LIVE` **and** `REAL_E2E_PROVEN=YES` **and**,
if a provider dependency is required, `PROVIDER_READY=YES` → may be
presented as production-ready. Everything else must not be, unless
explicitly labeled Beta/Preview for a real product reason.

## PUBLIC_READY_CAPABILITIES

(STATUS=LIVE, real evidence of working — safe to market as production-ready)

- Shipping cost lookup (RajaOngkir) — the strongest-evidenced capability in
  the platform; a real call was made and returned real quotes this session.
- Business Suite: Retail POS, Inventory, Transfers, Restaurant POS,
  Kitchen/KDS, Reports, Offline-first sync — service confirmed live and
  DB-connected; individual write paths (a sale, an order) weren't
  exercised in this audit but this is core, deeply-evidenced platform
  functionality, not an optional third-party integration.
- Store checkout (manual payment mode) — this is the store's actual active
  payment path today.
- Konektor: Webhook ingestion, HTTP/API generic action — core platform
  plumbing, high confidence, not provider-dependent.

## BETA_CAPABILITIES

(Real, working, explicitly not claimed as full production — label as
Beta/Preview if shown)

- AI Preview (AI chat) — per your standing Phase 1 decision, scope this to
  BETA/preview regardless of what's found about its internal provider.

## HIDDEN_PARTIAL_CAPABILITIES

(Code and infrastructure exist; not proven working end-to-end; do not
present as available yet — needs a FINISH pass, not necessarily broken)

- Telegram notifications (workflow connector + Business Suite low-stock
  alerts) — live, configured, healthy, but no confirmed message delivery.
- Google Drive / Google Picker (Drive app) — credentials configured, no
  proof of a working OAuth round-trip.
- Parking core (sessions, gate/exit, ANPR/edge) — real code and DB
  migrations exist; not independently verified this pass.

## PROVIDER_BLOCKED_CAPABILITIES

(The product/UI exists or is planned; the provider dependency is the
blocker — correctly shown as "coming soon," not as available)

- WhatsApp connector — no integration exists at all; site already labels
  this "Segera Hadir." Correct as-is.
- Payment Gateway generic connector — not wired; site already labels this
  "Segera Hadir." Correct as-is.
- Midtrans/QRIS automated payment (Store) — sandboxed and inactive; store
  currently runs on manual payment instead.
- Parking payment (real provider) — simulator only, no real provider
  wired.

## LEGACY_CAPABILITIES

(Present in source with no live unit, or a role that's now internal/back-office rather than public-facing)

- `services/shipping/{core-legacy,stack-legacy,location-index-archive-candidate}` —
  no active systemd unit; already documented in LEGACY-PATHS.md, not
  public-facing regardless.
- Restaurant Seller Control (`apps/restaurant`) — real and live, but it's a
  back-office licensing/entitlement panel, not a customer feature. Should
  never appear as a public feature card; the public "Restaurant" page
  correctly describes the Business Suite capability instead, not this one.

---

## Public-site truth check — page by page

Compared against CAPABILITIES.md / EXTERNAL-PROVIDERS.md. Only
discrepancies and notable confirmations are listed; pages not mentioned
here weren't found to make a specific claim needing a status check in this
pass.

### `/konektor/` — FIXED 2026-09-06, now consistent

| Card | Site badge | Registry status | Verdict |
|---|---|---|---|
| Webhook | Tersedia (Available) | LIVE | Consistent |
| HTTP/API | Tersedia | LIVE | Consistent |
| Telegram | Tersedia | PARTIAL_UNPROVEN | Borderline — live, configured, healthy, but delivery unproven. Not a clear violation, but don't strengthen this claim further without proof. |
| Google Sheets | ~~Tersedia~~ → **Segera Hadir** (fixed) | MOCK_ONLY (team's own gate: `PROMOTED=NO`, `REAL_GOOGLE_WRITE=NO`) | Was an unsupported claim — corrected in `apps/public-site/konektor/index.html` (badge class `ready`→`soon`, text "Tersedia"→"Segera Hadir"), matching the existing badge vocabulary already used for WhatsApp/Payment Gateway on the same page. No other text on the page or card changed. |
| WhatsApp | Segera Hadir (Coming Soon) | PARTIAL_PROVIDER_BLOCKED | Consistent — correctly hedged |
| Payment Gateway | Segera Hadir | PARTIAL_PROVIDER_BLOCKED | Consistent — correctly hedged |

### `/restaurant/` — consistent, with a naming note

Describes recipe/BOM, tables, KDS/KOT, dine-in/takeaway, COGS reporting —
this matches Business Suite's Restaurant POS capability (LIVE), not
`apps/restaurant` (which is the unrelated Restaurant Seller Control
licensing panel). The page content itself makes no false claim; the risk
is purely in the repository's own naming (`apps/restaurant` ≠ what this
page describes) — already corrected in CONTEXT.md and CURRENT-STATE.md.

### `/business-suite/` — consistent

POS retail/restaurant, central stock, multi-branch, canonical
bookkeeping/reports, offline-first POS, CSV/Excel import-export, QR
menu/self-order, generic webhook/REST — all trace to real code in
`/opt/botconnector-bisnis/app.py` and the Multichannel package it imports.
No unsupported claim found. (QR menu/self-order and CSV/Excel
import-export specifically were not individually verified against source
in this pass — flagging as unaudited, not as a problem.)

### `/my-drive/` — consistent, already appropriately hedged

States the core storage service is "Aktif" and marks advanced sharing as
"masih dalam pengembangan" (still in development). This matches the
registry (core service live, Google OAuth proof missing) without needing
a correction — the page doesn't over-claim the OAuth integration
specifically.

### Pages not checked in this pass

`/store/`, `/parking/`, `/drive/` (root page vs. `/my-drive/`), `/solusi/`,
`/resep/`, `/docs/`, and the homepage `index.html` were not individually
compared claim-by-claim — only the pages most likely to reference the
providers under audit were checked. Recommend the same page-by-page method
be applied to the rest before calling the full site verified.

---

## Action taken on the public site (canonical source only — not deployed)

1. `apps/public-site/konektor/index.html`: Google Sheets card badge
   changed from `badge ready`/"Tersedia" to `badge soon`/"Segera Hadir",
   2026-09-06 — matches this repo's own existing vocabulary (the same
   classes already used for WhatsApp/Payment Gateway), no new wording
   invented, no other card or page element touched.

This edit is in the canonical repo (`apps/public-site`) only. The live
botconnector.id site is a separate deployment artifact (see
docs/provenance/SOURCE-MAP.md, "public-site" entry) and was NOT touched —
this fix has no effect on production until a future, separate deploy step
you haven't asked for yet.

UNSUPPORTED_PUBLIC_CLAIMS=0 (as of this fix, for the pages checked in this
pass — see "Pages not checked in this pass" above for scope limits).
