# Product Flow

The flow below separates relationships visible in the PNGs from behavior that must be
verified against current production code.

## Family-level flow

```text
Authenticated workspace
        |
        +--> Product Family: BotConnector Business
        |       |
        |       +--> Dashboard
        |       +--> POS + Orders
        |       +--> Products
        |       +--> Inventory
        |       +--> Transfers
        |       +--> Restaurant
        |       +--> Kitchen / KDS
        |       +--> Reports
        |       +--> Integrations
        |       +--> Store Setup
        |
        +--> Product Family: Parking Payment
                |
                +--> Dashboard
                +--> Transactions
                +--> QRIS / Gateway
                +--> API Integration
                +--> Reconciliation
                +--> Settings
```

The sidebar family switch and labels are directly visible. Exact route names are a VPS
implementation concern and are recorded in `IMPLEMENTATION-HANDOFF.md`.

## Business operating loop

```text
Dashboard attention
   +--> POS + Orders --> active order --> payment/handoff --> Restaurant/KDS ticket
   |
   +--> Inventory --> low/review stock --> Transfers --> confirmation/handoff
   |
   +--> Restaurant/KDS --> table/service state --> Dashboard attention
   |
   +--> Reports / Control Room --> readout and saved operating views
```

### POS order states visible or implied by labels

- New sale: intake state.
- Open orders: orders needing continuation.
- Completed: closed order list.
- Ready: order handoff is ready for the next step.
- Order captured, Payment confirmed, Kitchen acknowledged: a visible stepper in the active order panel.
- Preparing and Paid: examples in the open order list.

These labels describe the UI state model shown in the PNG. The actual transition rules,
payment contract, and mutation endpoints must come from production code.

### Inventory and transfer states

- Healthy: stock is above threshold.
- Low stock: on-hand is below threshold.
- Review: requires a decision or review.
- Open transfer: transfer awaits confirmation.
- Recent stock movement: audit/readout surface.

The dashboard low-stock/action queue, inventory table, and transfer dock should use one
consistent source of truth rather than independently fabricated counts.

### Restaurant and kitchen states

- Table: occupied, available, reserved.
- Shift: started/live, pause shift action.
- Ticket: new, preparing, ready.
- Runner alert: ticket/table waiting for operational handoff.

POS-to-KDS event ownership is not defined by PNG. Keep the existing production contract.

## Parking Payment loop

```text
QRIS / Gateway readiness
        +--> API delivery events
        +--> Payment Dashboard / Transactions
                    +--> Pending
                    +--> Captured
                    +--> Reconciled
                    +--> To reconcile / mismatched handoff
        +--> Reconciliation
        +--> Settings / credential controls
```

### Payment states visible or implied by labels

- Gateway healthy.
- QRIS and gateway active/verified.
- Webhook delivery healthy/delivered/retried.
- Payment pending, captured, reconciled.
- Sandbox environment.
- To reconcile and mismatched summary.

Never derive settlement truth from a visual state or demo count. Reconciliation must use
the authoritative current payment source and preserve idempotency/security behavior.

## Screen relationship matrix

| From | Destination/context | Relationship |
|---|---|---|
| Business Dashboard | POS + Orders | Counter queue and order attention |
| Business Dashboard | Inventory / Transfers | Low stock and transfer action queue |
| Business Dashboard | Restaurant / KDS | Kitchen handoff attention |
| Business Dashboard | Reports | Shift readiness and operating readout |
| POS + Orders | Restaurant / KDS | Order handoff and kitchen acknowledgement |
| POS + Orders | Products / Inventory | Product availability and stock impact |
| Products + Inventory | Transfers | Stock movement and transfer dock |
| Restaurant + KDS | Reports | Service/order activity readout |
| Parking Dashboard | Transactions | KPI to selected payment detail |
| Parking Dashboard | Reconciliation | Pending/to-reconcile handoff |
| QRIS / Gateway | Transactions | Readiness and delivery feed payment records |
| API Integration | Webhook delivery | Technical delivery state |
| Reconciliation | Settings | Operational control/configuration context |

## Navigation rules for implementation

- Preserve family context when moving between sibling screens.
- Keep the selected family and selected workspace item visible.
- If a screen is unavailable for the current tenant/user, use existing auth/entitlement behavior.
- Do not merge Business and Parking Payment data models solely because their shell is shared.
- Deep links and redirects must follow current VPS route contracts, not labels inferred from PNG.
