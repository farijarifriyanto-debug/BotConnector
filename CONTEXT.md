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
The umbrella product name covering the Retail/Restaurant point-of-sale
capabilities a Business operates under. NEEDS_DECISION: no dedicated
source repository was found for this as a standalone app — it may be
capability delivered from within Multichannel rather than a separate
deployable. See docs/provenance/SOURCE-MAP.md.
_Avoid_: Bisnis (Indonesian UI label for the same concept)

**Retail**:
The point-of-sale vertical for a Business selling physical goods —
products, SKUs, inventory, and sales.
_Avoid_: Store (Store is the separate storefront/checkout app; Retail is
the operational POS concept it may share data with)

**Restaurant**:
The point-of-sale vertical for a Business running dine-in food service —
tables, kitchen order tickets (KOT), and menu items.
_Avoid_: F&B

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
The broader business-process area covering inventory, local business
operations, workflow, and reconciliation that ties a Business's verticals
together. Backed by the Multichannel shared package.
_Avoid_: Business process automation

**Shipping**:
The logistics vertical: resolving shipping options, routing between
providers, calculating cost (e.g. via the RajaOngkir provider), and
exposing a public shipping-lookup gateway. Composed of multiple live
services (router, resolver, gateway, integration, provider adapters)
rather than one monolith — see docs/architecture/CURRENT-STATE.md.

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
