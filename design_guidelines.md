# TRUKVIA · Design Guidelines (Iter150E, v1)

Frozen 2026-02-13.  Any change beyond this document requires a fresh
Business-Design Confirmation gate.  Iter150E is a visual/app-shell
standardisation pass — zero financial-logic, zero locked-band, zero
new backend endpoints.

---

## 1 · TRUKVIA master-brand usage

- The owner-supplied trademark-filed PNG is the sole authoritative
  brand identity.  The master is installed at
  `frontend/public/brand/TRUKVIA_master.png` and mirrored to
  `backend/assets/brand/TRUKVIA_master.png` for PDF chrome.
- **DO NOT** redraw, re-trace, recolor, reinterpret, produce a stand-
  in SVG, or invent an alternate lockup.
- Every derivative is a proportional PIL/LANCZOS raster fit of the
  master onto a transparent canvas.  Square derivatives are contain-
  fitted (letterboxed) so the wordmark + TM survive intact.
- TM symbol, proportions, gradients and geometry are preserved verbatim.

### Approved derivatives

| Path                                             | Purpose                       |
|--------------------------------------------------|-------------------------------|
| `favicon.ico`                                    | multi-icon (16 / 32 / 48)    |
| `favicon-16.png`, `-32.png`, `-48.png`           | favicon chain                 |
| `apple-touch-icon-180.png`                       | iOS home-screen               |
| `android-chrome-192.png`, `-512.png`             | PWA / Android chrome          |
| `trukvia-mark-64.png`, `-128.png`                | sidebar brand mark (2x)       |
| `trukvia-wordmark-64.png`, `-128.png`            | secondary wordmark            |
| `trukvia-login-mark.png`                         | login-page brand              |
| `backend/assets/brand/trukvia-pdf-header.png`    | PDF header raster (~830 px)   |

---

## 2 · Brand colour tokens

| Token                | HSL              | Hex       | Notes                        |
|----------------------|------------------|-----------|------------------------------|
| `--brand`            | `28 100% 50%`    | `#FD7800` | Final ember (from logo)     |
| `--brand-foreground` | `0 0% 100%`      | `#FFFFFF` | On-ember text                |
| `--brand-muted`      | `28 100% 94%`    | `#FFE9D6` | Soft ember tint              |
| `--brand-ring`       | `28 100% 50%`    | `#FD7800` | Focus ring                   |
| `--brand-ink`        | `20 80% 22%`     | `#66300F` | Deep ember ink               |
| `--brand-navy`       | `216 98% 20%`    | `#012963` | Logo navy · logo asset only  |

The zinc / near-black foundation (background `zinc-100`, ink
`zinc-950`, borders `zinc-200`, muted `zinc-500`) is preserved
unchanged.  The rose / emerald / amber semantic palette retains its
existing meaning.  Existing shadcn CSS variables are untouched.

---

## 3 · Restrained ember usage

`#FD7800` is a **highlight accent**, not a fill.  Approved uses:

- Active-nav 2 px left-edge indicator on the desktop sidebar.
- Brand mark on the sidebar and login.
- CTA hover-state accent (icon + underline).
- Focus ring / keyboard focus outline.
- HTML `theme-color` and PWA `theme_color`.
- 0.75 pt accent rule beneath TRUKVIA PDF header (non-invoice only).

Never use ember for:

- Table row / column backgrounds.
- Form-field borders in default state.
- Chart series / KPI card backgrounds.
- Semantic statuses (rose / emerald / amber own those meanings).
- Large decorative gradients or full-bleed hero fills.

---

## 4 · Typography

- **Primary body / display:** `Anek Telugu` (300 / 400 / 600 / 700).
- **Heading fallback:** `Chivo` (400 / 700 / 900).
- **Numeric:** `IBM Plex Mono` (400 / 500) — used via `.font-mono`,
  `.mono`, `.num` for tabular financial figures.
- Information-dense accounting workspace style is preserved:
  compact line-height, `letter-spacing: -0.01em` on headings,
  `font-feature-settings: "kern" 1`, tabular-nums on numerics.
- Telugu-first + English annotation is preserved on sidebar nav
  labels and top-level page chrome.

---

## 5 · Iconography

- **Library:** `lucide-react` only.
- Default stroke width `1.75`.  Active-state stroke `2.25`.
- Default sidebar icon size `18`.  Mobile bottom-nav `22`.
- **NO emoji icons** in the shipped UI (`🤖`, `🧠`, `💡` etc.
  are prohibited in production copy).

---

## 6 · App-shell grammar

The desktop sidebar is exactly **5 sections**, in this order:

1. **Masters** — Customers, Consignor/Consignee, Suppliers,
   Vendors, Mechanics, Drivers, Shortage Policy, Vehicles,
   Products.
2. **Operations** — Dashboard, Trips, Trip Templates, Fuel,
   Expenses, Quick Expense, Customer History.
3. **Financials** — Invoices, Overdue, Credit / Debit Notes,
   **Day Book**, **Account Ledger**, **Day Closing**.
4. **Reports** — Reports, Audit Log.
5. **System** — Files, Team, Settings.

Section headings render as a 10 px uppercase eyebrow in `zinc-500`.
The active nav item paints a 2 px ember left-edge indicator plus
`zinc-950` fill (no ember fill).  All 24 existing route paths and
all 24 existing `data-testid` values are preserved verbatim.  Only
the 3 new Financial Control links are added:

| Label            | testid                 | Path                |
|------------------|------------------------|---------------------|
| Day Book         | `nav-fin-day-book`     | `/fin/day-book`     |
| Account Ledger   | `nav-fin-accounts`     | `/fin/accounts`     |
| Day Closing      | `nav-fin-day-closing`  | `/fin/day-closing`  |

`/fin/accounts` is a route-level redirect to
`/fin/accounts/BANK_DEFAULT` (replace-navigation so the bare
path does not remain in browser history).  The existing
`/fin/accounts/:code` route is unchanged.  The mobile bottom-nav is
untouched.

---

## 7 · Buttons / cards / tables

- Zinc foundation preserved: `bg-white` cards, `border-zinc-200`,
  hover `bg-zinc-50`, primary CTA `bg-zinc-950 text-white`.
- Table numeric conventions: right-align, `IBM Plex Mono`, thousand-
  separator formatting.  No layout changes anywhere in this release.
- Semantic status colours (unchanged):
  - **rose**  · blocked / error / breaking
  - **emerald** · confirmed / positive / paid
  - **amber** · warning / non-blocking guidance / draft

---

## 8 · Copy voice

- Uppercase eyebrow convention (`text-[11px] uppercase tracking-widest
  font-bold text-zinc-500`).
- Imperative CTA verbs.
- Sidebar / mobile chrome copy: **TRUKVIA / అకౌంటింగ్ · Accounting Suite**.
- HTML title (browser tab / OS taskbar): **TRUKVIA · Bitumen
  Transport ERP**.
- Meta description: *TRUKVIA — bitumen transport ERP with canonical
  financial control.*
- Amber for non-blocking informational guidance.
- Rose for blocked / error states.
- Emerald for confirmed / positive states.
- No financial / business terminology is renamed in Iter150E.

---

## 9 · PDF chrome (non-invoice only)

- Applied via the additive helper `backend/pdf_brand.py`.
- Header: TRUKVIA raster lockup + document title + 0.75 pt ember
  accent rule.
- Footer: `TRUKVIA · <report name> · Page X of Y`.
- Presentation only — never mutates values, ordering, sorting,
  GSTINs, totals, or business logic.
- Applies to the 8 authorised non-invoice producers only.  Invoice
  PDF is **explicitly excluded** under Path P1 (protects
  `backend/services.py` and `backend/routers/invoices.py`).  Invoice
  branding is deferred to a future separately-authorised iteration.

---

## 10 · Explicit exclusions (all deferred)

- Dark mode.
- Motion library.
- i18n framework.
- Reconciliation Center (Iter150F).
- Dashboard redesign.
- Reports page restructuring.
- Marketing / landing site.
- Financial logic changes.
- New backend endpoints.
- Locked-band amendments.
- Invoice PDF branding.

---

## 11 · Test-id discipline

- Every existing `data-testid` is frozen (24 nav testids preserved).
- New testids introduced by Iter150E:
  `nav-fin-day-book`, `nav-fin-accounts`, `nav-fin-day-closing`,
  `login-brand-mark`, `sidebar-brand-mark`,
  `sidebar-section-masters`, `sidebar-section-operations`,
  `sidebar-section-financials`, `sidebar-section-reports`,
  `sidebar-section-system`.
- Kebab-case only.  No numeric-suffix duplication.  No renaming
  of existing testids under any circumstance.

---

## 12 · Change-control rule

Any deviation from the tokens, exclusions, sidebar shape, PDF chrome
scope, or approved copy in this document requires a fresh Business-
Design Confirmation gate signed by the owner.  No silent drift.
