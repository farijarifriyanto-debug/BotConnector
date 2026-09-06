# Current State — BotConnector Platform

Documents what is actually deployed and running today, as of the
2026-09-06 consolidation pass. This is a description of reality, not a
target design. No system was changed to produce this document.

## Deployment topology

Every module below runs as its own OS-level process (systemd unit or
Docker container) on the single VPS this platform lives on. There is no
shared application runtime — "module" here means a source tree with its
own process, not a library boundary within one binary.

| Module | Live runtime | Canonical target |
|---|---|---|
| Public Site | none (static POC only, not deployed) | `apps/public-site` |
| Store | `botconnector-store.service` | `apps/store` |
| Restaurant | Docker container `restaurant-seller-control` | `apps/restaurant` |
| Parking | `botconnector-parking.service` | `apps/parking` |
| Drive | `botconnector-drive.service` | `apps/drive` |
| AI Preview | `botconnector-ai-chat-core.service` | `apps/ai-chat-preview` |
| AI Workspace | `ai-workspace.service` | `apps/ai-workspace` |
| Admin Gate | `admin-gate.service` | `apps/admin-gate` |
| Multichannel | (shared package — see below) | `packages/multichannel` |
| Connector Core | `botconnector-connector-core.service` | `services/connector-core` |
| Finance Core | `botconnector-finance-core.service` | `services/finance-core` |
| Shipping (6 services) | see below | `services/shipping/*` |

Full per-component detail (exact paths, nginx routes, confidence) is in
`docs/provenance/SOURCE-MAP.md` — this document is the shape, that one is
the evidence.

## Seams

**Admin Gate is the platform's one cross-cutting seam.** Every panel route
for every other module (`/panel/restaurant/`, `/panel/ai/`, etc.) sits
behind an nginx `auth_request` call into Admin Gate. Callers (nginx, and
transitively every vertical's admin UI) only need to know one thing about
this seam: does this request get a 2xx or a 401/403. None of them know how
Admin Gate decides that. That's a deep module by this platform's own
`codebase-design` vocabulary — worth preserving as the single seam if this
platform is ever restructured, rather than letting individual verticals
grow their own auth checks.

**Shipping is not one module — it's a cluster of six adapters behind no
shared interface yet.** `router`, `location-resolver`,
`location-public-gateway`, `public-gateway`, `integration`, and
`rajaongkir-cost` are six independently deployed processes, each with its
own systemd unit and port. `public-gateway` is the one exposed to the
public internet (`/pengiriman/`, `/konektor/rajaongkir/`); the other five
are internal. There is currently no single "Shipping" interface a caller
goes through — callers (nginx, or other modules) reach whichever of the
six they need directly. Two live non-live siblings (`core-legacy`,
`stack-legacy`) and one draft (`location-index-archive-candidate`) exist on
disk with no active unit — see LEGACY-PATHS.md. This fragmentation is
recorded as observed reality, not endorsed; if this platform is
restructured later, whether these six belong behind one Shipping interface
or stay independently deployed is an open design question, not answered
here.

**Multichannel is depended on, not deployed.** `packages/multichannel`
backs the separately-running `botconnector-bisnis*` and
`botconnector-integrasi` services (different `WorkingDirectory`s), but the
exact mechanism connecting the package to those deployments was not traced
in this pass (NEEDS_DECISION, see SOURCE-MAP.md). Treat it as this
platform's shared domain package until that link is confirmed.

## Known gaps (not invented, not resolved)

- **Business Suite**: named in provenance decisions and referenced in the
  public-site POC, but no standalone source repo was found. It may be
  capability that already lives inside Multichannel rather than its own
  deployable — unconfirmed.
- **Public Site vs. live homepage**: the live botconnector.id root
  (`/var/www/botconnector`) has no discoverable source or generator. The
  imported `apps/public-site` (from the `full-site-poc`) is a candidate for
  becoming that source, not a proven replica of what's live today.
