# Design Inventory

## Inventory summary

| ID | File | Family | Logical screen | Evidence |
|---|---|---|---|---|
| BC-BIZ-001 | `Business-Dashboard.png` | Business | Dashboard | Full desktop frame |
| BC-BIZ-002 | `Business-POS-Orders.png` | Business | POS + Orders | Full desktop frame |
| BC-BIZ-003 | `Business-Products-Inventory.png` | Business | Products + Inventory | Full desktop frame; Inventory tab active |
| BC-BIZ-004 | `Business-Restaurant-Kitchen.png` | Business | Restaurant + Kitchen/KDS | Full desktop frame; Floor plan and live KDS visible |
| BC-BIZ-005 | `Business-Reports-Setup.png` | Business | Reports / Integrations / Store Setup / Quick Mode | Full desktop frame; Reports active |
| BC-PAY-001 | `Parking-Payment-Dashboard-Transactions.png` | Parking Payment | Payment Dashboard / Transactions | Full desktop frame; Dashboard active |
| BC-PAY-002 | `Parking-Payment-QRIS-Reconciliation-Settings.png` | Parking Payment | QRIS / Gateway, API Integration, Reconciliation, Settings | Full desktop frame; QRIS / Gateway active |

## Primary supplied reference

The seven frames above form the primary visual evidence supplied for implementation.
They share a clear desktop operating-workspace direction:

- Dark product-family sidebar.
- Warm light workspace canvas.
- Dense but calm operational content area.
- Serif display headings with sans-serif UI text.
- Lime as primary action and selected state.
- Dark ink panels for queues, context, and high-priority readouts.
- Lavender, coral, amber, blue, and green as semantic accents.

## Alternative directions

No explicit alternative frame, variant label, version label, or rejected direction is
present in the supplied ZIP. The following must therefore remain unverified:

- Whether any frame is an approved variant versus exploration.
- Whether a compact, light-sidebar, or mobile direction exists.
- Whether Business and Parking have different theme variants.
- Whether chart, table, or navigation components have alternate states outside the PNGs.

## Supporting screens

The following are supporting areas visible inside supplied frames, not separately exported
full frames:

- Business Control Room: Reports, Integrations, Store Setup, Quick Mode.
- Parking Payment Controls: QRIS / Gateway, API Integration, Reconciliation, Settings.
- Business Restaurant: Floor plan, Tables, Service notes, and KDS ticket flow.
- Business Inventory: Products and Transfers tabs.
- Parking Payment: Transactions table and reconciliation handoff.

## Not present in archive

These requested families cannot be documented from the supplied PNG evidence:

- Public Homepage / Operating Network.
- Business onboarding, tenant selection, branch selection, and empty states.
- Dedicated transfer detail screen.
- Dedicated QRIS, API Integration, Reconciliation, or Settings screens beyond the visible tab shell.
- Parking payment setup, credential edit, error, webhook delivery, and reconciliation detail states.
- Business mobile or tablet layouts.
- AI, Photo, Slides, Store, Connect, Drive, or Integrations product landing screens.

## Evidence confidence

| Area | Confidence | Reason |
|---|---|---|
| Desktop shell geometry | High | Repeated in all seven frames |
| Product family separation | High | Sidebar family blocks are visible |
| Component visual language | High | Repeated card, chip, table, and header patterns |
| Exact CSS tokens | Medium | Colors and spacing are visually estimated from PNG |
| Interaction behavior | Medium | Some states are visible; click behavior is not exported |
| Responsive behavior | Low | No mobile/tablet evidence |
| Product/API semantics | Low from PNG alone | Must come from current VPS technical source |
