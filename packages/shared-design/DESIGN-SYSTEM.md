# Shared Design System

Values below are visual estimates from 1265 x 900 PNGs. They are a starting reference,
not a claim about exact Replit source tokens.

## Shell

- **Canvas:** warm editorial light surface, approximately `#F1ECDE`.
- **Sidebar:** fixed dark green surface, approximately 240-248 px wide on desktop.
- **Workspace:** starts after sidebar; top header is approximately 78-92 px high with a thin bottom rule.
- **Content padding:** approximately 24-32 px horizontal and 28-36 px vertical.
- **Max width:** content expands to viewport; cards align to a consistent internal grid.
- **Card radius:** 14-20 px for standard cards; 20-24 px for large feature surfaces.
- **Border:** 1 px low-contrast warm gray; use dividers instead of heavy outlines.
- **Surface hierarchy:** canvas -> white card -> dark context panel; avoid adding extra ornamental layers.

## Sidebar

- Dark vertical shell is persistent across Business and Parking Payment.
- Brand mark sits at the top with a lime square icon and wordmark.
- A `PRODUCT FAMILY` block contains the active family card and sibling family entry.
- A family card has a small icon, family name, descriptor, and chevron.
- Workspace groups use small uppercase tracked labels: `BUSINESS WORKSPACE`, `COMMERCE`, `SERVICE`, `CONTROL`, or `PAYMENT WORKSPACE`, `PAYMENT RAIL`.
- Active nav item uses lime fill for the main workspace item; family-specific secondary selection can use a muted green or purple fill.
- Navigation items are icon + label + optional right-side dot.
- Bottom account block is visible in Parking frame and should be treated as a shared shell component.

## Header

- Breadcrumb or product family eyebrow uses uppercase tracking and muted color.
- Page title uses display serif, dark ink, around 24-32 px.
- One-line description uses sans-serif, muted gray-green, around 12-14 px.
- Right controls: search workspace, keyboard hint, notification, profile, sync status, and one primary/secondary action.
- Primary action is dark ink or lime depending on context; do not use multiple competing primary buttons.
- Sync state is small and quiet but always legible; show time/status when available from real data.

## Typography

| Role | Observed treatment | Starting token |
|---|---|---|
| Display heading | Serif, bold, tight | 24-34 px, line-height 1.0-1.1 |
| Large KPI | Serif, bold | 26-34 px |
| Section heading | Serif, bold | 17-23 px |
| UI body | Sans-serif | 12-14 px, line-height 1.4-1.6 |
| Navigation | Sans-serif, medium | 13-15 px |
| Eyebrow/metadata | Sans or mono-like, uppercase, tracked | 8-10 px, letter-spacing .16-.22em |
| Technical reference | Compact mono-like | 9-11 px |

The exact font family cannot be verified from raster images. Preserve the contrast between
editorial serif headings and utilitarian sans/technical labels.

## Color roles

| Role | Approximate color | Use |
|---|---|---|
| Ink | `#172019` | Text, dark buttons, dark panels |
| Sidebar dark | `#14241E` | Product shell and navigation |
| Dark panel | `#16271F` | Queues, credential cards, KDS, readouts |
| Canvas | `#F1ECDE` | Workspace background |
| Card | `#FFFCF6` | Primary light surfaces |
| Lime | `#D7FF3F` | Primary action, active nav, healthy/ready |
| Green | `#8EBC36` | Healthy/operating accents |
| Purple | `#A99AF2` | Parking Payment family, reports, reconciled |
| Coral | `#F27F70` | Review, new, low stock, urgent |
| Amber | `#E8B75E` | Preparing, pending, in motion, sandbox |
| Blue | `#8CC7D6` | Webhook/external delivery accent |
| Muted text | `#6F7970` | Descriptions and secondary data |
| Divider | `#DDD9CE` | Rules and table separators |

Use colors by semantic role, not by decorative preference. Exact values must be reconciled
with the implementation source once the Replit code or token export is available.

## Buttons and links

- **Primary:** dark ink or lime fill, high-weight sans, 10-14 px radius, compact horizontal padding.
- **Secondary:** white/warm surface with a 1 px neutral border.
- **Dark-panel action:** lime text or lime fill against dark green.
- **Text link:** muted green or lime with a right arrow; reserve arrows for navigation/action.
- **Icon button:** square rounded control with neutral surface; tooltip/accessible label required.
- Hover should lift or change border subtly, not cause layout shift.
- Focus must be visible with a high-contrast outline.

## Cards and panels

- Use white cards for data and forms; dark panels for context, queue, readout, KDS, and credentials.
- Card header has a small uppercase eyebrow and a serif title.
- Large panels use 20-24 px padding; compact cards use 12-18 px.
- Keep one clear purpose per card. Do not turn every navigation item into a marketing card.
- Use a dark panel when the user must act on or interpret selected context.

## Tables and data surfaces

- Table lives inside a rounded white surface with a distinct toolbar.
- Toolbar combines search at left and filters/export at right.
- Header labels are uppercase/tracked and quiet.
- Rows use dividers, 14-18 px vertical padding, and bold only for primary value.
- Status column uses semantic chip, not a full-row color wash.
- Selected row/detail is represented by a dark side panel where present.
- Desktop table may scroll internally; mobile needs an explicit overflow strategy.

## Status chips

- Chip shape: pill, 1 px border or soft fill, 9-11 px uppercase tracked text.
- Healthy/ready/captured: lime-green fill.
- Review/low/new/urgent: coral fill.
- Preparing/pending/in motion/sandbox: amber fill.
- Reconciled/paid/secondary: lavender fill.
- Neutral/available: warm gray or transparent border.
- Always pair color with text; never rely on color alone.

## Selection and active states

- Main selected nav: lime background, dark ink text, optional dark dot.
- Selected family secondary nav: muted family tint (green for Business, purple for Parking Payment).
- Selected segmented tab: colored fill with dark text; inactive tabs remain on neutral surface.
- Selected ticket/payment: stronger border or dark context panel, not just color.
- Active/live state uses a small dot plus text.

## Spacing scale

Use an 8 px base scale, with observed practical values:

```text
4   micro label/icon gap
8   chip and metadata gap
12  compact control padding/gap
16  standard card gap and row inset
20  panel gap and card padding
24  main card padding
32  section/header spacing
48  major workspace separation
```

## Responsive rules

No responsive PNG was supplied. These are implementation rules to preserve hierarchy,
not observations from Replit:

- Collapse sidebar into a drawer with an explicit family switcher.
- Keep page title, primary action, and sync state visible above the fold.
- Stack KPI cards and two-column panels at tablet/mobile widths.
- Convert right-side context panels into below-list sections on narrow screens.
- Keep segmented tabs horizontally scrollable rather than wrapping into unreadable rows.
- Use horizontal table scroll or purposeful row cards; do not hide state/action columns.
- Preserve dark panel/lime action contrast and visible focus states.
- Respect `prefers-reduced-motion`; avoid required animation for status understanding.
