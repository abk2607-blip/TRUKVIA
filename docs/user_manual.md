# QORVENA · Bitumen Transport ERP
## User Manual

**Version**: 1.0 (English) · February 2026
**Application**: QORVENA · Bitumen Transport ERP
**Audience**: Owners, Admins, Accountants, Managers, and new users
**Scope**: All modules and workflows, current locked behaviour

> This manual describes the application as it exists today. UI labels are quoted **exactly** as they appear on screen. Read each section end-to-end before performing the workflow for the first time.

---

## Table of Contents

1. Getting Started
2. Dashboard
3. Masters
    - 3.1 Customers
    - 3.2 Ship-To Sites
    - 3.3 Suppliers (Deactivate / Reactivate)
    - 3.4 Consignor / Consignee
    - 3.5 Vehicles
    - 3.6 Drivers
    - 3.7 Products
    - 3.8 Shortage Policy
4. Trips
    - 4.1 Creating a Trip
    - 4.2 Loading
    - 4.3 Unloading
    - 4.4 Freight vs Shortage
    - 4.5 Trip Templates
5. Fuel Log
6. Invoices
    - 6.1 Creating an Invoice
    - 6.2 Ship-To Handling
    - 6.3 Pre-Unload vs Completed-Unload Invoices
    - 6.4 Invoice PDF (Page X of Y)
7. Payments
8. Reports
9. Customer History
10. Files
11. Team & Roles
12. Settings
13. Common Real-World Situations
14. Form Draft Recovery
15. Save Retry / Resilience
16. Troubleshooting
17. Do's and Don'ts
18. Appendix A — Keyboard Shortcuts
19. Appendix B — Quick Reference: Locked Business Rules
20. Appendix C — Support

---

## 1. Getting Started

**What is this?**
QORVENA is a Bitumen transport ERP. It tracks Lorry Receipts (LRs), Trips, Freight, Shortage, Invoices, Payments, Suppliers, Customers, and business Reports. The application runs entirely in your web browser and stores every record securely in the cloud.

**When should I use it?**
Every business day, for every LR, trip, invoice, and receipt. QORVENA replaces manual registers and spreadsheets.

**Steps to log in**
1. Open the application URL in Google Chrome or Microsoft Edge.
2. On the sign-in card, click **Continue with Google**.
3. Choose your Google account and grant access.
4. First-time users are guided through the company setup wizard.

> IMPORTANT · The **Continue as Demo — Skip Login** button is a QA-only shortcut. It is hidden in production builds. Never share the demo token with customers or drivers.

**Screenshot**: `screenshots/01_login.png`
**Caption**: The sign-in page. Use *Continue with Google* for real accounts; the demo button is disabled in production.

---

## 2. Dashboard

**What is this?**
A one-glance overview of your business — receivables, payables, recent trips, freight for the month, and top customers/suppliers.

**Key cards**
- **Total Outstanding** — total amount customers still owe you.
- **Total Payable** — total amount you still owe suppliers.
- **Recent Trips** — the latest trip records added.
- **Top Suppliers by Outstanding** — suppliers ranked by dues.
- **Monthly Freight** — freight billed / earned this month.

**Steps**
1. From the top navigation, click **Dashboard**.
2. Review the cards.
3. Click any card to drill into the underlying screen.

> TIP · Bookmark the Dashboard URL; it is designed to be the first page you open every morning.

**Screenshot**: `screenshots/02_dashboard.png`
**Caption**: Dashboard headline cards and recent-activity list.

---

## 3. Masters

Masters are the foundational records — Customers, Suppliers, Vehicles, Drivers, Products. Set them up **once and correctly**, and every downstream workflow (Trip, Invoice, Report) becomes fast and consistent.

### 3.1 Customers

**What is this?**
The party you bill for freight.

**When should I use it?**
Before you create the customer's first trip.

**Steps**
1. In the left navigation, click **Customers**.
2. Click **+ Add Customer** (top-right).
3. Fill the fields listed below.
4. Click **Save**.

**Fields**

| Field | Required? | Notes |
|---|---|---|
| Name | Yes | Legal / trade name |
| Phone | Yes | Primary contact |
| GSTIN | Recommended | 15-character GSTIN; auto-derives State |
| State | Yes | Auto-filled from GSTIN when valid |
| Pincode | Optional | Head-office pincode |
| Opening Balance | Optional | Defaults to 0 |

**What should I check before Save?**
- The name is spelt correctly.
- Phone is a 10-digit mobile.
- GSTIN, if entered, is exactly 15 characters.
- State matches the GSTIN's first two digits.

**Duplicate customer warning**
QORVENA blocks creation of a customer with the **same name + phone**, or the **same GSTIN**, as an existing record. When the duplicate check fires, you will see a dialog:

- Click **Open Existing** to jump to the existing record.
- Click **Cancel** to go back.
- Click **Continue Creating** only if you have verified that this is genuinely a different party (rare).

> WARNING · Never bypass the duplicate warning to "fix" a spelling. Instead, click **Open Existing** and edit the existing record.

**Common mistakes**
- Pasting the GSTIN with a leading `GSTIN ` prefix. The app now cleans this, but keep entries tidy.
- Editing the wrong record because two similarly-named customers exist. Always confirm the phone or GSTIN.

**Screenshot**: `screenshots/03_customers.png`
**Caption**: Customer list with History, Ship-To, Edit, and Delete actions.

### 3.2 Ship-To Sites

**What is this?**
A **delivery location** attached to a customer. One customer can have many Ship-To Sites — for example a Bengaluru buyer with unloading points in Nagarkurnool, Karwar, and Kurnool.

**When should I use it?**
Whenever a customer receives material at more than one physical address.

**Steps**
1. Open **Customers**.
2. On the customer row, click **Ship-To**.
3. Click **+ Add Ship-Site**.
4. Fill the site name, address, GSTIN (optional), State, State Code, and Pincode.
5. Click **Save**.

**How GSTIN → State auto-derivation works**
- Enter a valid 15-character GSTIN.
- The first two digits identify the State (e.g. `36` → Telangana; `29` → Karnataka).
- State and State Code auto-fill.
- If you override the State manually and it conflicts with the GSTIN prefix, the app shows an amber conflict banner.

> IMPORTANT · Ship-To State is **independent** of Customer State. A Bengaluru-registered customer can legitimately have a Nagarkurnool Ship-To. QORVENA never silently copies Customer State onto a Ship-To Site.

**Common mistakes**
- Entering the Customer's HO address as the Ship-To. Add a separate site for each actual delivery point.
- Deleting a Ship-To that is already referenced by historical trips. Deactivate the customer's site record only if it is genuinely retired; historical invoices continue to reference the correct address.

**Screenshot**: `screenshots/04_customer_form.png`
**Caption**: Add Customer form. Enter GSTIN first — State auto-fills from the first two digits.

### 3.3 Suppliers

**What is this?**
The party who supplies the vehicle / carries the material. Suppliers own vehicles; drivers work under suppliers.

**Fields**
Same shape as Customers — Name, Phone, GSTIN, State, PAN, Opening Balance.

**Duplicate check**
Same name + phone or the same GSTIN is blocked, with the same **Open Existing / Continue Creating** dialog described in section 3.1.

#### Deactivate / Reactivate

**What is this?**
A **soft-delete** for suppliers who no longer work with you. Their historical trips, invoices, and payments **remain intact**; they simply stop appearing in active pickers.

**When should I use it?**
- Supplier retired.
- Supplier's contract ended.
- Duplicate supplier accidentally created and rows already exist against it.

**How to Deactivate**
1. Open **Suppliers**.
2. Click the **List** tab (the top-level card view is separate).
3. Find the active supplier row.
4. Click the red **Deactivate** button at the right of the row.
5. Review the confirmation modal — it shows dependency counts (linked vehicles, trips, payments).
6. Enter a **Reason** (mandatory).
7. Click **Deactivate** to confirm.

**How to Reactivate**
1. On the Suppliers **List** tab, toggle **Show Inactive** at the top-left.
2. Inactive suppliers appear in muted grey.
3. Click the green **↻ Reactivate** button on the correct row.

> IMPORTANT · Deactivate is a **soft-delete**. Historical LRs, trips and invoices continue to display the supplier correctly. Never delete a supplier record from the database — you would break historical books.

**Permissions**
Only **Owner** and **Admin** roles can Deactivate / Reactivate. Manager, Accountant, and Viewer roles see a `403` toast if they try.

**Screenshot**: `screenshots/05_suppliers.png`
**Caption**: Suppliers dashboard with Total Outstanding, Payments, and top-suppliers list.

**Screenshot**: `screenshots/05b_supplier_list.png`
**Caption**: Suppliers **List** tab — the Deactivate button appears at the right of each row. Toggle **Show Inactive** to reveal soft-deleted suppliers and reactivate them.

**Screenshot**: `screenshots/06_parties_consignor.png`
**Caption**: Consignor / Consignee address book. Add a party once, reuse it across LRs.

### 3.4 Consignor / Consignee

**What is this?**
The party who **dispatches** (Consignor) or **receives** (Consignee) the product. Used on the LR and invoice when they differ from the billed Customer.

**Steps**
1. Click **Consignor / Consignee** in the left navigation.
2. Add the party with name, address, and GSTIN.

### 3.5 Vehicles

**What is this?**
Each truck / tanker in your (or your suppliers') fleet.

**Fields**: Vehicle number, capacity (MT), owning Supplier, Insurance expiry, Permit expiry, RC number.

**Duplicate check**: Same vehicle number is blocked (with the same Open Existing / Continue Creating dialog).

**What should I check before Save?**
- Vehicle number is in the correct RTO format (e.g. `AP16TA1234`).
- Insurance / permit expiry dates are current.

### 3.6 Drivers

**What is this?**
The person driving the vehicle.

**Fields**: Name, phone, licence number, licence expiry, associated Supplier, salary / policy.

**Common mistakes**
- Forgetting to enter licence expiry — the compliance report will flag such drivers as at-risk.

### 3.7 Products

**What is this?**
The material you carry — e.g. Bitumen VG 40, VG 30, Emulsion.

**Fields**
- **Rate per MT** — used when calculating shortage deductions.
- **Allowance %** — the acceptable shortage window.

### 3.8 Shortage Policy

**What is this?**
The formula that converts a physical short (Load MT − Unload MT) into an invoice deduction.

**Common methods**
- **Net Shortage** — deduct only the amount **above** the allowance.
- **Full Shortage after Limit** — deduct the entire shortage once the allowance is crossed.

> IMPORTANT · Changing a policy on the Customer master applies **only to new trips**. Historical trips continue to use the policy that was in force when the trip was created. This protects your closed books.

---

## 4. Trips

### 4.1 Creating a Trip

**What is this?**
The core operational record — a single vehicle movement from a Loading point to an Unloading point.

**Steps**
1. Click **Trips** in the left navigation.
2. Click **+ Add** (top-right).
3. Fill the sections listed below.
4. Click **Save Trip**.

**Sections**

| Section | When to fill |
|---|---|
| Basics — Date, Vehicle, Driver, Customer, Consignor | At dispatch |
| Loading — From location, Product, Loading Qty (MT), LR number | At dispatch |
| Freight — Mode (Per Ton / Fixed / Round Trip), Rate | At dispatch |
| Unloading — Unload Date, Unload Qty, To location, Ship-Site | **After** unloading is confirmed |
| Advances / Diesel from Customer | Whenever you give money to the driver |
| Halting — Arrival date, Waiting days | After unload |

> TIP · You do **not** have to wait for unloading data to save the trip. Save with Loading complete and empty Unloading fields; return later to fill Unload Qty and Unload Date.

**Screenshot**: `screenshots/11_trip_form.png`
**Caption**: Trip creation form — sections collapse for a focused workflow.

**Screenshot**: `screenshots/10_trips.png`
**Caption**: Trip list with filters, totals bar, and inline actions per row.

**Screenshot**: `screenshots/12_trip_view.png`
**Caption**: Trip detail view — Loading, Unloading, Freight, and audit fields on a single page.

**Screenshot**: `screenshots/14_trip_import.png`
**Caption**: Bulk import — download the Excel template, fill your rows, and upload.

### 4.2 Loading

Enter the loading quantity in **MT** (metric tons). Assign a unique LR number per company. The app blocks duplicate LR numbers within the same company.

### 4.3 Unloading

**IMPORTANT rules**

- **Unload Qty (in MT)** — the actual quantity that came out of the tanker at destination.
- **Unload Date** — the calendar date on which unloading was completed.
- Leave these blank if unloading has not happened yet.

> WARNING · Missing unload data means **"Not Available Yet"** — it does **NOT** mean "zero unloaded". Never enter `Unload Qty = 0` to force-close a trip. `0` is treated as a real zero-unload (a total loss) which is almost never correct.

### 4.4 Freight vs Shortage

Freight and Shortage are two **independent** business states:

| Trip state | Freight available? | Shortage available? |
|---|---|---|
| Loaded, dispatched, unloading pending | Yes — calculated at dispatch | No — shown as `—` |
| Unloaded, Unload Qty and Unload Date entered | Yes | Yes — calculated using the snapshotted shortage policy |

**Rule**
- Freight is finalised at dispatch.
- Shortage becomes meaningful **only** after actual unloading data is entered.
- Pre-unload invoices must **never** fabricate a shortage number — QORVENA correctly displays `—` for Actual Short / Allowance / Net Short until unload data arrives.

### 4.5 Trip Templates

**What is this?**
A saved set of default values (Customer, Product, From-To, Rate) for repetitive routes. One click fills the whole trip form.

**Steps**
1. Click **Trips → Templates**.
2. Click **+ New Template**.
3. Fill and save.
4. Next time, on the trip form, choose the template from the **Apply Template** dropdown.

**Screenshot**: `screenshots/13_trip_templates.png`
**Caption**: Trip Templates — save repetitive routes for one-click reuse.

---

## 5. Fuel Log

**What is this?**
A record of diesel fill-ups per vehicle, used for costing and reconciliation.

**Steps**
1. Click **Fuel** in the left navigation.
2. Either drag-and-drop a fuel-bill photo (auto-tags vehicle + date from the filename pattern `AP16TA1234_2026-02-05_hp.jpg`) or click **+ New Fill** to enter manually.
3. Fill vehicle, date, litres, rate, amount, odometer, station.
4. Click **Save**.

**Screenshot**: `screenshots/18_fuel.png`

---

## 6. Invoices

### 6.1 Creating an Invoice

**What is this?**
Consolidating one or more trips into a GST-compliant tax invoice for a customer.

**Steps**
1. Click **Invoices → + Create** (or use the shortcut from the customer's screen).
2. Select the **Customer**.
3. Apply filters — date range, Ship-Site — to narrow the trip list.
4. **Tick** the trips to include in this invoice.
5. Set the **Invoice Date** and **Invoice Number** (auto-generated by default).
6. Click **Preview** to review the calculated totals and PDF layout.
7. Click **Save** to finalise.

**What should I check before Save?**
- The trip list matches what you actually intend to bill.
- The Ship-To block is correct (see 6.2).
- Tax split (IGST vs CGST/SGST) matches the invoice jurisdiction.
- Invoice number is unique — the app blocks duplicates.

**Invoice numbering**
Auto-format per company (example: `AKB/26-27/0018`). You can override once, but never reuse an existing number.

**Screenshot**: `screenshots/15_invoices.png`
**Caption**: Invoice list with status filters and quick actions.

**Screenshot**: `screenshots/16_invoice_create.png`
**Caption**: Invoice creation — pick a customer, tick trips, preview totals, save.

**Screenshot**: `screenshots/18b_overdue.png`
**Caption**: Overdue Invoices screen — filter by age bucket and send reminders.

### 6.2 Ship-To Handling

The invoice header shows a **single Ship-To block** when all selected trips point to the **same physical delivery site** — even if one trip carries an explicit `ship_site_id` and another only has a `to_location` string that clearly matches the same site (by name, pincode, or address).

If the selected trips genuinely go to different Ship-Sites, the invoice shows:

> "Mixed destinations — see trip rows below"

and each trip row prints its own Ship-To detail.

> IMPORTANT · Ship-To on the invoice is derived from the trip, not the Customer master. Customer State ≠ Ship-To State is legal and common.

### 6.3 Pre-Unload vs Completed-Unload Invoices

You can raise an invoice as soon as the vehicle is dispatched. Waiting for unloading is **not** required.

**Pre-Unload Invoice**

| Column | Value |
|---|---|
| Load MT | actual value |
| Unload MT | — |
| Unload Date | — |
| Actual Short | — |
| Allowance | — |
| Net Short | — |
| Freight | actual freight (fully calculated) |

The invoice total is `Freight + Tax`; no shortage is deducted.

**Completed-Unload Invoice**

| Column | Value |
|---|---|
| Load MT | actual value |
| Unload MT | actual value |
| Unload Date | actual date |
| Actual Short | calculated |
| Allowance | policy-based |
| Net Short | calculated |
| Freight | actual freight |

Once you enter Unload Qty and Unload Date on the trip, the shortage engine runs automatically. Regenerate the invoice PDF to reflect the actual short / allowance / net.

> WARNING · Do **NOT** enter `Unload Qty = 0` just to force the invoice to show a shortage. `0` MT will be treated as a genuine zero-unload — a total loss.

### 6.4 Invoice PDF (Page X of Y)

Every invoice PDF prints **Page X of Y** in the bottom-right of every page:

- Single-page invoice → `Page 1 of 1`
- Two-page invoice → `Page 1 of 2` and `Page 2 of 2`
- Long invoices flow across as many pages as needed.

The signature block appears only on the **last** page.

**GSTIN cleanup**
The Ship-To GSTIN is normalised on display. Even if a legacy record stored the GSTIN with a `GSTIN ` prefix or trailing tabs, the PDF renders only the 15-character GSTIN.

**Screenshot**: `screenshots/17_invoice_view.png`

---

## 7. Payments

**What is this?**
Recording money received from customers and money paid to suppliers.

**Steps**
1. Click **Payments** (from the Suppliers or Customers screen) → **+ Add**.
2. Select the party (customer or supplier).
3. Fill amount, mode (Cash / Bank / UPI / Cheque), reference, date, receipt-or-voucher number.
4. Click **Save**.

The party's running balance updates immediately.

---

## 8. Reports

**Path**: **Reports** in the left navigation.

**Pre-built reports**

| Report | What it shows |
|---|---|
| LR Register | Every LR with load, unload, freight, and shortage |
| Customer Statement | Invoice-wise ledger with running balance |
| Supplier Settlement | Trip-wise settlement with driver / supplier splits |
| GSTR-1 Ready | Invoice-wise GST summary for filing |
| Cash Flow | Receipts vs payments by date |
| P&L | Freight income vs costs |

Each report supports date filters and Export to Excel / PDF.

**Screenshot**: `screenshots/19_reports.png`

---

## 9. Customer History

**What is this?**
A deep-drill single-customer view showing all trips, invoices, payments, and running balance on one page. Also displays age buckets (0-30, 30-60, 60-90, 90+ days) for outstanding invoices.

**Steps**
1. Click **Customers → History**.
2. Search or select the customer.
3. Scroll for trip / invoice / payment tables and the age-bucket card.

**Screenshot**: `screenshots/23_customer_history.png`

---

## 10. Files

**What is this?**
Attach documents (LR scans, delivery challans, driver documents) to trips, suppliers, or drivers. Files are stored securely in cloud object storage.

**Steps**
1. Click **Files** in the left navigation.
2. Choose the **Category** and drag-and-drop the file (max 10 MB per file).
3. Files appear in **Your Files** with Preview and Delete actions.

**Screenshot**: `screenshots/22_files.png`

---

## 11. Team & Roles

**Path**: **Team** in the left navigation.

**Roles**

| Role | Access |
|---|---|
| Owner | Full access, Team management, Supplier Deactivate |
| Admin | Most write access, Supplier Deactivate |
| Manager | Create / edit trips, invoices, payments; **no** Deactivate |
| Accountant | Invoice & payment access; masters are read-only |
| Viewer | Read-only |

**Steps to invite a team member**
1. Click **Team → + Invite Member**.
2. Enter the invitee's email and choose a Role.
3. Click **Send Invite**.
4. The invitee signs in with their own Google account.

**Screenshot**: `screenshots/20_team.png`

---

## 12. Settings

**Path**: **Settings** in the left navigation.

**Sections**
- **Company** — legal name, address, PAN, GSTIN, bank details. These appear on the invoice PDF header and footer.
- **Numbering** — invoice number format per company / financial year.
- **Products** — as per section 3.7.
- **Shortage policy** — as per section 3.8.
- **Notifications** — email digest opt-ins.

> TIP · Only the **Owner** can change the invoice numbering pattern once the year has issued invoices — the app blocks it otherwise to preserve the audit trail.

**Screenshot**: `screenshots/21_settings.png`

---

## 13. Common Real-World Situations

| Situation | What to do |
|---|---|
| Driver confirms unloaded quantity by phone | Open the trip → Unloading section → enter Unload Qty and Unload Date → Save. Regenerate the invoice PDF. |
| Customer says the GSTIN on the invoice was wrong | Edit the customer's GSTIN → app auto-updates State → regenerate the invoice. Do **not** edit the invoice number. |
| Supplier retired; don't want them appearing in dropdowns | Suppliers → **List** tab → **Deactivate**. Historical trips remain intact. |
| Ship-To State was wrong on an old invoice | Edit the Ship-Site → correct GSTIN → State auto-updates. Only **future** invoices reflect the change unless you re-open and re-save the older invoice. |
| Vehicle broke down mid-trip; no unloading yet | Save the trip with Load MT and blank Unloading. Invoice can be raised for freight; shortage stays `—`. |
| Duplicate customer created accidentally | Automatic merge is not supported. Deactivate the wrong one; ask an Admin to move trips manually if needed. |

---

## 14. Form Draft Recovery

**What is this?**
If the browser closes or the tab crashes while you were filling a Trip, Customer, or Invoice form, the app **auto-saves a local draft** with your entries so far.

**How to recover**
1. Reopen the same form (e.g. Trips → + Add).
2. If the app detected a meaningful in-progress draft, a subtle **Restore draft?** banner appears at the top of the form.
3. Click **Restore** to bring back your entries.

> IMPORTANT · Only **meaningful** drafts (with real data typed into fields) are offered for recovery. Blank untouched forms will not create ghost drafts, so you won't be pestered by empty prompts.

**Where drafts live**
Locally in your browser only. Drafts do **not** sync across devices. Save the form to persist to the cloud as soon as you can.

---

## 15. Save Retry / Resilience

Every Save call carries a unique **Idempotency-Key** header.

- If your network flickers and the browser retries the Save, the server recognises the duplicate and does **not** create two records.
- You will see **one** green confirmation toast, not two.
- Business data stays consistent even under bad networks.

If a Save toast never appears, wait ~30 seconds — the app is retrying under the hood. If the toast still doesn't appear, hard-refresh (Ctrl + Shift + R) and confirm from the list view whether the record was actually saved before re-entering.

---

## 16. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Duplicate detected" dialog | Same name + phone or same GSTIN already exists | Click **Open Existing** and edit that record |
| **REFRESHING…** pill visible for more than 15 seconds | Backend health probe temporarily failing (often after browser sleep/wake) | Wait 15–30 s; if it persists, Ctrl + Shift + R |
| Invoice PDF still shows the old State | Ship-Site record wasn't re-saved after correction | Edit Ship-Site → Save → regenerate the invoice |
| Shortage column shows `—` unexpectedly | Trip's Unload Qty is blank | Enter the actual Unload Qty; shortage will auto-appear |
| Actual Short equals the full Load MT | Old cached invoice PDF | Hard-reload (Ctrl + Shift + R); the latest engine will show `—` for pre-unload trips |
| Amber **App update available** nudge | A newer application build has shipped | Click it — your in-flight drafts are preserved |
| `403` when clicking **Deactivate** on a supplier | You are not Owner or Admin | Ask the Owner to perform the action |

---

## 17. Do's and Don'ts

### DO

- Set up all Masters (Customers, Vehicles, Drivers, Products) **first**, before creating trips.
- Use Ship-To Sites for every distinct delivery location.
- Enter GSTINs cleanly — the app auto-derives State.
- Leave Unload Qty and Unload Date **blank** until the vehicle is actually unloaded.
- Regenerate invoice PDFs after any data correction.
- Use Trip Templates for repetitive routes to save time.

### DO NOT

- Do **NOT** delete old suppliers or customers — always Deactivate.
- Do **NOT** enter `Unload Qty = 0` when unloading is still pending.
- Do **NOT** create duplicate customers — click **Open Existing** on the warning dialog.
- Do **NOT** hard-refresh during a Save — wait for the confirmation toast.
- Do **NOT** reuse invoice numbers — the app blocks this, but do not try to work around it.
- Do **NOT** modify Ship-To State on historical customers expecting old invoices to change — old invoices remain historical unless you re-open and re-save them.
- Do **NOT** share your Google login. Invite team members with their own email addresses.

---

## Appendix A · Keyboard Shortcuts

- **Ctrl + K** — global search
- **Ctrl + Shift + R** — force reload (use only if the UI is stuck)
- **Esc** — close any modal

---

## Appendix B · Quick Reference: Locked Business Rules

The following rules are LOCKED in the current release. They protect data integrity across trips, invoices, and books.

1. **Duplicate Masters** — Customer / Supplier / Vehicle duplicates are blocked by name+phone or GSTIN; the dialog offers Open Existing / Cancel / Continue Creating.
2. **Ship-To Independence** — Ship-To State is independent of Customer State; GSTIN can derive State / State Code; Customer State is never silently copied to a Ship-To.
3. **Trip Loading and Unloading** — Loading and Unloading are **separate stages**. Freight is available at dispatch; shortage requires unloading data.
4. **Missing Unload Data** — Blank unload fields mean "Not Available Yet" — NOT "zero unloaded". Pre-unload invoices must NOT show fabricated shortages.
5. **Invoice Ship-To** — Preview and PDF are guaranteed identical. GSTIN is cleaned on display. Unload Date renders correctly on the PDF row.
6. **Invoice Pagination** — Every PDF shows Page X of Y on every page; the signature block appears on the last page only.
7. **Supplier Deactivate** — Soft-delete only. All historical LRs, trips, and invoices remain intact. Show Inactive toggle reveals them; Reactivate is one click. Owner / Admin only.
8. **Draft Recovery** — Only meaningful, non-empty forms are offered for restore. Blank forms are ignored.

---

## Appendix C · Support

For questions about the application:

1. Read the relevant section of this manual.
2. Contact your Owner or Admin.
3. For production support, email **bitumentra@gmail.com**.

---

End of manual · Version 1.0 · February 2026

QORVENA · Bitumen Transport ERP
