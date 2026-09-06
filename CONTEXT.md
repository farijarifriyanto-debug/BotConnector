# BotConnector Platform

A multi-vertical commerce/operations platform: several customer-facing
verticals (retail, food service, parking, storage) share a common
integration and finance layer, gated behind one auth/admin surface. This
glossary captures only terms proven true by the 2026-09-06 source
consolidation (filesystem, live systemd units, live nginx routes) — nothing
here is aspirational.

## Language

**Business**:
A tenant of the platform — one merchant/operator using one or more
verticals (Retail, Restaurant, etc.) under their own branches, registers,
and staff.
_Avoid_: Tenant, account, customer (Customer is the Business's own
end-buyer, a different concept)

**Business Suite**:
RESOLVED (2026-09-06): a thin FastAPI entrypoint (`apps/business-suite`,
one file, `/opt/botconnector-bisnis/app.py` in production) running as
`botconnector-bisnis.service`, serving `/bisnis/` — offline-first PWA POS
covering Retail, Restaurant, Inventory, Transfers, Reports. It imports its
entire domain implementation from the Multichannel shared package (via
`sys.path.insert(0, "/opt")` + the `/opt/botconnector_multichannel` symlink
to Multichannel's own directory) — the entrypoint itself has no deep
implementation of its own. Confirmed live: health check reports
`database: connected`.
_Avoid_: Bisnis (Indonesian UI label for the same concept)

**Retail**:
The point-of-sale vertical for a Business selling physical goods —
products, SKUs, inventory, and sales. Delivered as part of Business
Suite's `/bisnis/api/*` surface.
_Avoid_: Store (Store is the separate storefront/checkout app; Retail is
the operational POS concept it may share data with)

**Restaurant**:
AMBIGUOUS TERM — resolves to two different, unrelated things on this
platform, disambiguate by context:
1. The dine-in food-service POS capability (menu, recipe/BOM, tables,
   Kitchen Display/Order tickets) — this is a sub-feature of **Business
   Suite** (`/bisnis/api/restaurant`, `/bisnis/api/kitchen`), not a
   separate app. This is what the public-site `/restaurant/` marketing
   page describes.
2. **Restaurant Seller Control** (`apps/restaurant`, Docker container
   `restaurant-seller-control`, route `/panel/restaurant/`) — a licensing
   and plan-entitlement admin panel (edition tiers: Essential, Lengkap,
   Professional, Multi Outlet; EC-signed license issuance) for restaurant
   sellers. This has nothing to do with POS/kitchen operations — it is a
   back-office licensing gate.
_Avoid_: F&B; "Restaurant app" (ambiguous — say "Restaurant POS" for #1 or
"Restaurant Seller Control" for #2)

**Store**:
The customer-facing storefront/checkout application (product v6r3), live
at the `/store/` route, distinct from the internal Retail POS vertical.

**Parking**:
The vertical for a Business operating paid parking — vehicle sessions and
payment reconciliation.

**Drive**:
The file storage/document vertical.

**Konektor (Connector)**:
The marketplace/adapter layer that lets a Business connect external
services (e.g. shipping providers, spreadsheets) to their operations.
_Avoid_: Integration (see Integrasi below — related but the Indonesian
"Integrasi" is the broader business-process term; Konektor is the
technical adapter concept)

**Integrasi**:
RESOLVED (2026-09-06): a second thin FastAPI entrypoint
(`apps/integrasi`, one file, `/opt/botconnector-integrasi/app.py` in
production), sibling to Business Suite — same pattern (imports
Multichannel via the same `/opt` symlink), same required dependency on
Finance Core, different port. Today it serves exactly one thing: a
public, read-only, no-outbound-call marketplace status page
(`/integrasi/`) showing Shopee/Tokopedia/TikTok Shop/Blibli/Lazada as
"Segera Hadir" (Coming Soon) — the source code's own docstring says
"Read-only. Tidak memanggil keluar. Tidak membuka token." None of those
marketplace connections are live; this is a placeholder, not an
integration.
_Avoid_: Business process automation; do not read "Integrasi" as implying
live marketplace connectivity — it explicitly does not have any yet.

**Multichannel**:
The shared domain package (`packages/multichannel`) both Business Suite
and Integrasi import their entire implementation from — persistence,
local_business (POS/inventory/restaurant/procurement/telegram), workflow,
connector registry. It is not itself deployed; it's a library two separate
processes share via a `/opt/botconnector_multichannel` (underscore) →
`/opt/botconnector-multichannel` (hyphen) symlink so Python's import
system can resolve it despite the hyphenated directory name.

**Shipping**:
The logistics vertical: resolving shipping options, routing between
providers, and calculating cost via the RajaOngkir provider. Composed of
six independently deployed services (public-gateway, integration, router,
location-resolver, location-public-gateway, rajaongkir-cost) rather than
one monolith. CONFIRMED LIVE end-to-end 2026-09-06: a real request through
public-gateway → integration → RajaOngkir returned real courier quotes
(JNE Jakarta→Bandung) in ~1.5s — see docs/capability-registry/EXTERNAL-PROVIDERS.md.

**Finance**:
The accounting/ledger vertical — invoices, journals, and period close —
shared across verticals.

**AI Preview**:
The single AI chat capability included in this platform, explicitly scoped
to BETA/preview status. Other AI services on this box (console,
mission-runner, tool-platform, desktop gateway, Windows tool adapter) are
a separate, excluded AI cluster — not part of this platform.
_Avoid_: AI Chat Core (implementation name; AI Preview is the product-level
term)

**Public Site**:
The marketing/informational website for the platform, presented at
botconnector.id. NEEDS_DECISION: the live site today is a deployment
artifact with no discoverable source; the imported apps/public-site is a
proof-of-concept designated as the future canonical source, not yet
proven equivalent to what's live.

**Admin Gate**:
The shared authentication/authorization surface every panel route sits
behind (`auth_request` checks in front of each vertical's admin panel).
_Avoid_: Auth, login
