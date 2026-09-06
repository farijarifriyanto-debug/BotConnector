# Screen Catalog

Field notes below describe what is visibly present. Numbers, names, dates, and statuses
are screenshot demo content, not production requirements.

## BC-BIZ-001 - Business Dashboard

**File:** `replit-assets/Business-Dashboard.png`

- **Product/family:** BotConnector Business, Business Workspace.
- **Purpose:** Give an operating overview: orders, sales, low stock, open handoffs, attention queue, and shift readiness.
- **Layout:** 248 px-class dark sidebar; warm canvas; top header with breadcrumb, search, notification, profile, sync indicator, and New handoff action. Main content has store/branch context row, four KPI cards, a two-column operating pulse and action queue, then shift readiness.
- **Navigation:** Family selector contains Business and Parking Payment. Business workspace links are Dashboard, POS + Orders, Products, Inventory, Transfers, Restaurant, Kitchen / KDS, Reports, Integrations, Store Setup. Dashboard is selected with lime background.
- **Components:** Family switcher, sidebar nav, command search, profile menu, sync status, KPI strip, attention list, semantic status chips, mini bar chart, progress bars, dark action queue, primary CTA.
- **States/status:** Live shift, synced, healthy pace, review today, in motion, needs owner, open handoffs. Selected nav and selected store are visible.
- **Important interactions:** Change family or workspace section; open handoff; inspect attention row; open action queue item; switch store/branch; create a handoff. Exact click destinations are not present in PNG.
- **Relations:** Entry point to POS, inventory, restaurant, reports, and action queue. KPI cards summarize states represented in those screens.
- **Visual style:** Editorial operations console. Light parchment workspace against dark green shell; high contrast dark queue; lime is reserved for selected/healthy/action states.
- **Typography:** Large dark serif `Dashboard`; compact uppercase tracked labels; UI sans for navigation and descriptions; large serif KPI numerals.
- **Colors:** Dark sidebar/panels, warm off-white canvas/cards, lime selected state, green healthy, coral review, amber motion, lavender ownership/attention.
- **Spacing:** Wide breathing room around main sections; 4 KPI cards in one row; 16-24 px card gaps; 16-20 px card radii; thin neutral dividers.
- **Responsive behavior:** Not observed. Preserve information hierarchy by stacking KPI and action queue, moving the queue below the pulse, and making sidebar collapsible.
- **Implementation must preserve:** Business as operating center; real store/tenant context; real KPI sources; action queue semantics; no copied demo numbers; auth and entitlement boundaries.

## BC-BIZ-002 - POS + Orders

**File:** `replit-assets/Business-POS-Orders.png`

- **Product/family:** BotConnector Business, Commerce / POS workspace.
- **Purpose:** Start a sale, find or scan products, monitor open orders, and hand off an active order for payment/kitchen completion.
- **Layout:** Header with counter context, time, Scan item, Filter, and New sale. Main area is two columns: left order intake panel and right active order detail. Left panel has New sale / Open orders / Completed tabs, search, frequently sold product tiles, and order context list. Right panel has customer, order line items, totals, and dark handoff status card.
- **Navigation:** POS + Orders selected. Products, Inventory, Transfers, Restaurant, Kitchen / KDS, Reports, Integrations, Store Setup remain available in sidebar.
- **Components:** Segmented order tabs, product search, product tiles, order list, customer row, item table, subtotal/service/total summary, readiness chip, handoff stepper, Mark as paid button.
- **States/status:** New sale, open orders, completed; order ready; order captured; payment confirmed pending; kitchen acknowledged; preparing and paid order list examples.
- **Important interactions:** Start new sale; search/scan item; filter orders; select product tile; select open order; mark as paid; advance handoff state. Payment mutation must remain behind current production auth/readiness controls.
- **Relations:** Product catalog and inventory feed product availability; order handoff relates to Restaurant/KDS; payment state relates to Business payment flow if that exists in production.
- **Visual style:** Functional counter workspace with a light input/catalog panel and a dark contextual action panel. Lime action is intentionally prominent.
- **Typography:** Serif screen title and order total; sans labels and item rows; uppercase mono-like labels for `Active order`, `Handoff status`, and item metadata.
- **Colors:** Lime active tab/action, green ready/check, amber preparing, lavender paid/secondary state, dark green context panel, warm white surfaces.
- **Spacing:** Left and right panels have generous 20-24 px padding; product grid uses compact equal tiles; line items use horizontal dividers.
- **Responsive behavior:** Not observed. Stack intake before active order; keep totals and payment action sticky or visible; allow product grid to reflow; table rows must not become unreadable.
- **Implementation must preserve:** Real order/payment lifecycle, inventory decrement rules, kitchen handoff contract, CSRF/auth, and no fake Mark as paid action.

## BC-BIZ-003 - Products + Inventory

**File:** `replit-assets/Business-Products-Inventory.png`

- **Product/family:** BotConnector Business, Commerce / Inventory workspace.
- **Purpose:** Switch between inventory, products, and transfers; review stock health; search catalog; inspect movement and handoff needs.
- **Layout:** Header with Add product action and sync scope. Segmented tabs Inventory, Products, Transfers. Three KPI cards for tracked products, stock to review, and open transfers. Full-width searchable table with Filters and Export. Lower two-column area starts a movement log and transfer dock.
- **Navigation:** Inventory is selected in the sidebar and in the workspace tabs. Products and Transfers are sibling destinations.
- **Components:** Workspace tabs, sync indicator, KPI cards, search input, filters, export action, data table, stock chips, movement log, transfer dock.
- **States/status:** Healthy, low stock, review; open transfers awaiting confirmation; synced across stores. The screenshot shows product rows with on-hand, threshold, location, and state.
- **Important interactions:** Switch tabs; search by name or SKU; filter; export; select a product; inspect movement; open or confirm transfer. Exact behavior and API fields must be mapped to current production.
- **Relations:** Dashboard low-stock attention and transfer queue; POS consumes product availability; Restaurant recipes/KDS may consume inventory if supported by actual Business code.
- **Visual style:** Data-dense but editorial: a large calm table framed by rounded white surface, dark transfer dock, and small semantic chips.
- **Typography:** Serif title; compact sans table labels and values; tiny uppercase table metadata; bold values for on-hand and state.
- **Colors:** Lime active Inventory tab and healthy; coral low stock; amber review; lavender open transfer accent; warm canvas/card contrast.
- **Spacing:** Three KPI cards in one row; table header separated by 1 px divider; rows use approximately 16-20 px vertical rhythm; 16-20 px radius.
- **Responsive behavior:** Not observed. Table should scroll horizontally or switch to row cards; KPI cards stack; tabs remain horizontally scrollable.
- **Implementation must preserve:** Actual SKU/product schema, location and threshold semantics, export contract, transfer authorization, and tenant isolation.

## BC-BIZ-004 - Restaurant + Kitchen/KDS

**File:** `replit-assets/Business-Restaurant-Kitchen.png`

- **Product/family:** BotConnector Business, Restaurant / Service workspace.
- **Purpose:** Keep floor service and kitchen working from the same order moment; see table occupancy and live kitchen tickets.
- **Layout:** Header with Pause shift. Service row shows lunch service, start time, staff avatars, and people on floor. Left light panel has Floor plan / Tables / Service notes tabs and a 4-column table grid. Right dark panel is Kitchen / KDS with Live ticket flow and vertical ticket cards. A selected ticket section continues below the visible fold.
- **Navigation:** Restaurant is selected; Kitchen / KDS is a sibling navigation entry and also appears as the right-side surface.
- **Components:** Service status row, staff avatar group, segmented tabs, table grid, occupied/available/reserved table tiles, KDS ticket list, ticket status chips, selected ticket panel, Pause shift action.
- **States/status:** Occupied, available, reserved; KDS New, Preparing, Ready; Live; lunch service started; table alert waiting for runner.
- **Important interactions:** Pause/resume shift; switch floor plan/tables/service notes; select table; select KDS ticket; update ticket state; assign runner; open selected ticket detail. Mutation rules must come from actual Business backend.
- **Relations:** POS order handoff creates/updates KDS ticket; table status informs POS; dashboard kitchen handoff attention and reports reflect service state.
- **Visual style:** Split operational surface: light spatial map plus dark high-attention ticket rail. Lime and coral show urgency without making the whole screen noisy.
- **Typography:** Serif screen title; sans table/customer/ticket text; uppercase small labels for KDS and ticket metadata.
- **Colors:** Dark KDS panel; light floor plan; lime live/ready; coral new/urgent; amber preparing; lavender reserved; muted dotted borders for available tables.
- **Spacing:** 4-column table grid with equal tiles; 14-18 px gaps; ticket rail uses stacked cards with 16 px gaps; panel corners around 18-20 px.
- **Responsive behavior:** Not observed. On mobile, floor plan and KDS must become sequential tabs or a vertical two-panel flow; preserve current selected ticket visibly.
- **Implementation must preserve:** Actual order-to-kitchen event flow, service shift state, ticket status transitions, and staff permissions.

## BC-BIZ-005 - Reports / Integrations / Store Setup / Quick Mode

**File:** `replit-assets/Business-Reports-Setup.png`

- **Product/family:** BotConnector Business, Business Control Room.
- **Purpose:** Review performance and reach operating controls without leaving the Business family.
- **Layout:** Header titled Control room with Create report action. Left control card contains Reports, Integrations, Store Setup, and Quick Mode. Main area has report period selector, sales-by-day chart, dark readout card, and report library with saved views.
- **Navigation:** Reports is selected in both sidebar and control card. Integrations, Store Setup, and Quick Mode are visible sibling controls.
- **Components:** Control-room subnav, report period dropdown, chart panel, readout panel, report library cards, Create report CTA, Open full report link.
- **States/status:** Current period, selected Reports control, readout observations, saved operating views. The chart data is demo content.
- **Important interactions:** Switch control-room area; change period; create report; open full report; open saved view. Do not infer report generation API from the PNG.
- **Relations:** Dashboard summarizes operation; inventory and order events feed reports; Integrations and Store Setup are adjacent setup/control contexts.
- **Visual style:** Calm analytical page with light chart surface and dark insight/readout surface. Left control card makes this a control room, not a generic card catalog.
- **Typography:** Serif `Control room` and report headings; sans descriptions; uppercase report labels; chart labels small and quiet.
- **Colors:** Lavender chart bars and selected report chip; dark readout; lime links; warm neutral surfaces.
- **Spacing:** Left control card is narrow; report content is wide; 20-24 px panel gaps; saved views use compact horizontal cards.
- **Responsive behavior:** Not observed. Stack control card above report; chart can scroll or reduce density; readout moves below chart.
- **Implementation must preserve:** Real report periods/data, export/report permissions, integration setup boundaries, and store configuration ownership.

## BC-PAY-001 - Payment Dashboard / Transactions

**File:** `replit-assets/Parking-Payment-Dashboard-Transactions.png`

- **Product/family:** Parking Payment, Payment Workspace.
- **Purpose:** Monitor captured value, transaction state, pending records, and reconciliation workload.
- **Layout:** Parking Payment family sidebar; header with Export; parking payment context row and Gateway healthy chip; four KPI cards; left transactions table with tabs All transactions, Pending, Captured; right selected payment context card; reconciliation handoff strip below.
- **Navigation:** Payment family contains Dashboard, Transactions, QRIS / Gateway, API Integration, Reconciliation, Settings. Dashboard is selected.
- **Components:** Family selector, payment workspace sidebar, gateway health chip, KPI cards, transaction tabs, filter/search icons, transaction table, selected-payment card, payment status chips, reconciliation handoff.
- **States/status:** Gateway healthy; captured, pending, reconciled; selected payment; to reconcile; settled/pending/mismatched summary examples.
- **Important interactions:** Export; switch Dashboard/Transactions; filter/search; select transaction; open transaction detail; open reconciliation. Payment mutation and settlement remain controlled by actual payment backend.
- **Relations:** QRIS / Gateway and API delivery feed transactions; Reconciliation consumes transaction states; Settings controls payment infrastructure.
- **Visual style:** Same shell as Business but a purple family accent identifies Parking Payment. Dark selected-payment panel keeps payment context visible.
- **Typography:** Serif Payment Dashboard and amount; sans transaction table; uppercase payment-rail labels; monospace-like references and timestamps.
- **Colors:** Purple family accent; lime captured/healthy; amber pending; lavender reconciled; coral/error potential; dark context panel.
- **Spacing:** KPI strip mirrors Business; table has dense rows and internal horizontal/vertical scroll affordances; selected card aligns to table height.
- **Responsive behavior:** Not observed. Use transaction cards or horizontal table scroll; selected payment should move below list; KPI cards stack.
- **Implementation must preserve:** Real payment state, gateway response mapping, idempotency, reconciliation authority, and read-only versus mutation boundaries.

## BC-PAY-002 - QRIS / Gateway / API / Reconciliation / Settings

**File:** `replit-assets/Parking-Payment-QRIS-Reconciliation-Settings.png`

- **Product/family:** Parking Payment, Payment Controls.
- **Purpose:** Show payment rail readiness, credentials, delivery events, and adjacent control destinations.
- **Layout:** Header titled Payment controls. Horizontal tab bar with QRIS / Gateway, API Integration, Reconciliation, Settings. Main light readiness panel has three progress rows and three status tiles. Right dark credential status panel. Lower full-width webhook delivery events panel.
- **Navigation:** QRIS / Gateway is the active tab. The other three labels are visible navigation targets, not independently captured screens.
- **Components:** Segmented control, readiness progress bars, readiness status labels, credential card, credential masking/copy affordances, manage credentials link, webhook events table/list, delivery chips.
- **States/status:** QRIS active, gateway verified, webhook healthy, credentials present, sandbox, delivered, retried once. These are demo visual states only.
- **Important interactions:** Switch tabs; manage/copy credentials; inspect delivery event; open reconciliation/settings/API controls. Secret values must never be put in client markup beyond the existing production masking rules.
- **Relations:** Payment Dashboard consumes readiness and delivery results; Reconciliation reads transaction delivery/capture state; Settings and API tabs own setup operations.
- **Visual style:** Readiness page uses progress rails and a dark credential panel; purple is Parking Payment identity, lime is healthy/active, amber marks environment or retry.
- **Typography:** Serif Payment controls and readiness heading; uppercase labels; compact sans event rows; tiny technical identifiers.
- **Colors:** Purple active tab, green/lime readiness, blue webhook accent, amber sandbox/retry, dark credential surface.
- **Spacing:** Tab bar is compact and horizontal; readiness rows separated by dividers; three status tiles in a row; event rows are full width.
- **Responsive behavior:** Not observed. Make tabs horizontally scrollable; stack readiness and credential panels; keep credential actions reachable; events become cards.
- **Implementation must preserve:** Credential security, gateway contract, webhook delivery truth, sandbox/live distinction, reconciliation semantics, and role restrictions.

## Cross-screen shell observations

All seven frames use the same high-level shell. Detailed tokens and component rules are in
`DESIGN-SYSTEM.md`; screen relationships are in `PRODUCT-FLOW.md`.
