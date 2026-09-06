# Implementation Handoff

## Scope

Implement the supplied visual reference as a candidate UI only. This document does not
authorize production deployment, database mutation, auth changes, API changes, or route
merging.

## Technical guardrails

- Production/repository VPS remains technical source of truth.
- Keep Business, Parking, Connect, Drive, Store, and Integrations services separated.
- Preserve current auth, tenant, entitlement, CSRF, API contracts, and data ownership.
- Replace screenshot demo values with real API-backed values where the current screen supports them.
- If a visual element has no real backend behavior, mark it unavailable or wire it to the existing real route; do not create a dead button.
- Do not copy screenshot names, amounts, customer names, dates, order IDs, payment IDs, or status counts into production.
- Do not infer new product features from labels alone.
- Do not touch OlahDokumen.

## Candidate implementation order

1. Extract shared shell: sidebar, family selector, header, account block, surface tokens.
2. Implement Business Dashboard shell and state components.
3. Implement POS + Orders with real order/product/payment boundaries.
4. Implement Products + Inventory and Transfers with real data tables.
5. Implement Restaurant + Kitchen/KDS with real service/ticket state.
6. Implement Reports / Integrations / Store Setup as separate control-room destinations.
7. Implement Parking Payment Dashboard / Transactions.
8. Implement Payment Controls tabs and only the actual QRIS/API/Reconciliation/Settings behavior available in production.
9. Add responsive layouts, keyboard navigation, focus states, reduced-motion behavior, and error/empty/loading states.
10. Run route/API regression tests and compare candidate screenshots against the supplied PNGs.

## Current VPS route anchors

These are technical route anchors previously verified from the BotConnector VPS and must be
re-verified in the target candidate before implementation is considered complete:

| Visual family/action | Existing route anchor |
|---|---|
| Business Suite | `/bisnis/` |
| Parking | `/parking/` |
| Connect | `/connect-v2/` |
| Drive | `/drive` |
| Store | `/store/` |
| Integrations | `/integrations/` |
| AI supporting tool | `/panel/ai/` |
| Photo supporting tool | `/photo-ai/` |
| Slides supporting tool | `/studio` |

The PNGs do not prove these URLs. They are included here only as an implementation handoff
to be checked against the current production source before wiring navigation.

## Visual acceptance criteria

- Sidebar width, family blocks, active states, header alignment, and canvas hierarchy match the supplied desktop frames.
- Business Dashboard has a clear KPI strip, operating pulse, and dark action queue.
- POS + Orders preserves the intake/detail split and visible handoff stepper.
- Products + Inventory preserves tabs, KPI strip, table toolbar, stock chips, and transfer context.
- Restaurant + KDS preserves floor-plan/table grid beside live ticket flow.
- Reports preserves the control-room subnav, chart, readout, and report library relationship.
- Parking Dashboard preserves payment KPI strip, transaction states, selected-payment context, and reconciliation handoff.
- Payment Controls preserves readiness bars, credential panel, tab strip, and delivery events.
- No screenshot demo content is used as production data.
- All action controls have real routes or existing production behavior.
- Keyboard focus, semantic status text, contrast, and reduced-motion behavior are verified.
- Mobile behavior is designed and tested separately; no desktop-only overflow is accepted.

## Verification checklist

- `DESIGN-INVENTORY.md` is updated when new PNG/source evidence arrives.
- Template/component diff confirms backend files were not changed unintentionally.
- Focused UI tests pass.
- Existing Business and Parking route/API tests pass.
- Desktop screenshots at the supplied 1265 x 900 reference size are captured.
- Mobile and tablet screenshots are captured after responsive implementation.
- A visual review records intentional deviations caused by real production capability.
- Production current pointer, service, nginx, database, and auth state remain unchanged until explicit cutover approval.

## Missing inputs before claiming full Replit parity

- Public Homepage / Operating Network PNG or source export.
- Mobile/tablet frames.
- Separate full frames for QRIS, API Integration, Reconciliation, Settings, Transfers, Integrations, and Store Setup.
- Explicit approved/alternative labels or Replit version history.
- Exact font family, color tokens, spacing tokens, icon set, and component states.
- Prototype interactions and route annotations.

## Handoff status

`READY_FOR_IMPLEMENTATION=PARTIAL`

The seven supplied desktop frames are detailed enough to start a candidate shared shell and
the two captured product families. They are not enough to claim the entire Replit project or
all responsive/variant designs have been reconstructed.
