# QORVENA · Bitumen Transport ERP
## User Manual

**Version**: 1.0 (English)
**Released**: February 2026
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

**Screenshot**: `screenshots/02_dashboard_crop.png`
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

QORVENA checks for duplicates the moment you click **Save**. What happens next depends on which field matched.

| Match on | What QORVENA does | Buttons you will see |
|---|---|---|
| **GSTIN** | Blocks the save. A GSTIN belongs to only one customer, so a second record cannot be created. | **Cancel** · **Open Existing** |
| **PAN** (only when neither record has a GSTIN) | Blocks the save. | **Cancel** · **Open Existing** |
| **Name** (spelling/spaces ignored) | Shows a warning and pauses the save. You can proceed if you are sure this is a genuinely different party. | **Cancel** · **Continue Creating** · **Open Existing** |
| **Phone number** | Never blocks. The app quietly highlights other customers with the same phone number so you can verify. | (no pop-up) |

- **Cancel** — dismiss the dialog and go back to the form.
- **Open Existing** — jump to the existing record. You can then edit it instead of creating a new one.
- **Continue Creating** — appears **only** for a Name match. Click it when the two records are genuinely different companies (for example, a namesake or a separate branch).

If a GSTIN or PAN match is a mistake and the two records are truly different, ask an Owner or Admin — they have a separate override with a written reason. Regular users cannot bypass GSTIN or PAN matches.

> IMPORTANT · Never bypass a duplicate warning to "fix" a spelling. Click **Open Existing** and edit the existing record.

**Screenshot**: `screenshots/25_customer_duplicate_gstin.png`
**Caption**: Duplicate detected — GSTIN match. Only **Cancel** and **Open Existing** are available; GSTIN and PAN matches cannot be overridden by regular users.

**Screenshot**: `screenshots/25b_customer_duplicate_name.png`
**Caption**: Possible duplicate — Name match. **Continue Creating** appears **only** for name matches; click it if the two records are genuinely different companies.

**Common mistakes**
- Pasting the GSTIN with a leading `GSTIN ` prefix. The app now cleans this, but keep entries tidy.
- Editing the wrong record because two similarly-named customers exist. Always confirm the phone or GSTIN.

**Screenshot**: `screenshots/03_customers_crop.png`
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
Same shape as Customers — Name, Phone / Mobile, GSTIN, State, PAN, Opening Balance.

**Duplicate supplier warning**

Supplier duplicates are stricter than customer duplicates. In addition to GSTIN and PAN, **the supplier name is also blocked** — the app will not let you create a second supplier with the same name.

| Match on | What QORVENA does | Buttons you will see |
|---|---|---|
| **GSTIN** | Blocks the save | **Cancel** · **Open Existing** |
| **PAN** (only when neither record has a GSTIN) | Blocks the save | **Cancel** · **Open Existing** |
| **Name** (spelling/spaces ignored) | Blocks the save | **Cancel** · **Open Existing** |
| **Mobile number** | Never blocks. The app quietly highlights other suppliers with the same mobile so you can verify. | (no pop-up) |

There is **no Continue Creating** button on the supplier dialog. If a block is genuinely wrong, an Owner or Admin can override it with a written reason.

**Screenshot**: `screenshots/05c_supplier_duplicate_modal.png`
**Caption**: Supplier duplicate dialog — regardless of the matched field, only **Cancel** and **Open Existing** are offered.

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
Only **Owner** and **Admin** roles can Deactivate / Reactivate. Manager, Accountant, and Viewer roles see an **Access denied** message if they try.

**Screenshot**: `screenshots/05d_supplier_deactivate_modal.png`
**Caption**: Deactivate confirmation dialog. QORVENA lists linked vehicles and historical-trip counts before the action, and a **Reason** is mandatory. The action is a soft-delete only.

**Screenshot**: `screenshots/05_suppliers_crop.png`
**Caption**: Suppliers dashboard with Total Outstanding, Payments, and top-suppliers list.

**Screenshot**: `screenshots/05b_supplier_list_crop.png`
**Caption**: Suppliers **List** tab — the Deactivate button appears at the right of each row. Toggle **Show Inactive** to reveal soft-deleted suppliers and reactivate them.

**Screenshot**: `screenshots/06_parties_consignor_crop.png`
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

**Duplicate vehicle handling**

Vehicles are matched purely on the **vehicle number** (upper-case, spaces removed). QORVENA never creates two records for the same vehicle — if you enter one that already exists, the app quietly points you at the existing record.

| Match on | What QORVENA does | Buttons you will see |
|---|---|---|
| **Vehicle Number** | Opens the dialog and offers to take you to the existing vehicle. No new record is created. | **Cancel** · **Open Existing** |

The bulk-import path is stricter still: duplicate vehicle numbers inside the same file, or vehicle numbers that already exist in your account, are rejected with a clear error line — never merged silently.

**Screenshot**: `screenshots/07b_vehicle_duplicate_modal.png`
**Caption**: Vehicle duplicate dialog. The backend never creates a second row; it returns the existing one, and the UI offers **Open Existing** so you can edit it.

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

**Screenshot**: `screenshots/11_trip_form_crop.png`
**Caption**: Trip creation form — sections collapse for a focused workflow.

**Screenshot**: `screenshots/10_trips_crop.png`
**Caption**: Trip list with filters, totals bar, and inline actions per row.

**Screenshot**: `screenshots/14_trip_import_crop.png`
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

**Screenshot**: `screenshots/13_trip_templates_crop.png`
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

**Screenshot**: `screenshots/18_fuel_crop.png`

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
5. Set the **Invoice Date**. The **Invoice Number** is auto-assigned by the server from the company's prefix + FY + running sequence (see below).
6. Click **Preview** to review the calculated totals and PDF layout.
7. Click **Save** to finalise.

**What should I check before Save?**
- The trip list matches what you actually intend to bill.
- The Ship-To block is correct (see 6.2).
- Tax split (IGST vs CGST/SGST) matches the invoice jurisdiction.
- The invoice date sits inside the correct financial year (Apr–Mar).

**Invoice numbering**

QORVENA generates each invoice number automatically. There is **no** per-invoice override on the create screen — the sequence is guaranteed by the server.

Format: `{Invoice Prefix}/{FY}/{Sequence}` — e.g. `AKB/26-27/0018`.

- **Invoice Prefix** and **Next Invoice Number** are set once per company in **Settings**.
- The prefix may already include the FY (`VBK/26-27/`), in which case QORVENA appends only the running sequence — no doubled slashes, no doubled FY.
- Sequences are per company and increment on every successful save.
- The API rejects duplicate invoice numbers.

> IMPORTANT · Only change **Invoice Prefix** or **Next Invoice Number** in **Settings** when you have a real, deliberate reason (new FY, new company, legacy migration). Retro-changing after invoices have gone out breaks your audit trail.

**Screenshot**: `screenshots/15_invoices_crop.png`
**Caption**: Invoice list with status filters and quick actions.

**Screenshot**: `screenshots/16_invoice_create_crop.png`
**Caption**: Invoice creation — pick a customer, tick trips, preview totals, save.

**Screenshot**: `screenshots/18b_overdue_crop.png`
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

**Screenshot**: `screenshots/17_invoice_view_crop.png`

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

**Screenshot**: `screenshots/19_reports_crop.png`

---

## 9. Customer History

**What is this?**
A deep-drill single-customer view showing all trips, invoices, payments, and running balance on one page. Also displays age buckets (0-30, 30-60, 60-90, 90+ days) for outstanding invoices.

**Steps**
1. Click **Customers → History**.
2. Search or select the customer.
3. Scroll for trip / invoice / payment tables and the age-bucket card.

**Screenshot**: `screenshots/23_customer_history_crop.png`

---

## 10. Files

**What is this?**
Attach documents (LR scans, delivery challans, driver documents) to trips, suppliers, or drivers. Files are stored securely in cloud object storage.

**Steps**
1. Click **Files** in the left navigation.
2. Choose the **Category** and drag-and-drop the file (max 10 MB per file).
3. Files appear in **Your Files** with Preview and Delete actions.

**Screenshot**: `screenshots/22_files_crop.png`

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

**Screenshot**: `screenshots/20_team_crop.png`

---

## 12. Settings

**Path**: **Settings** in the left navigation.

**Sections**
- **Company** — legal name, address, PAN, GSTIN, bank details. These appear on the invoice PDF header and footer.
- **Numbering** — Invoice Prefix and Next Invoice Number per company. QORVENA auto-composes the running number as `{Prefix}/{FY}/{Sequence}`.
- **Products** — as per section 3.7.
- **Shortage policy** — as per section 3.8.
- **Notifications** — email digest opt-ins.

> TIP · Only the **Owner / Admin** can change the invoice numbering settings. Do this only when starting a new financial year or migrating from a legacy series — never mid-year.

**Screenshot**: `screenshots/21_settings_crop.png`

---

## 13. Common Real-World Situations

| Situation | What to do |
|---|---|
| Driver confirms unloaded quantity by phone | Open the trip → Unloading section → enter Unload Qty and Unload Date → Save. Regenerate the invoice PDF. |
| Customer says the GSTIN on the invoice was wrong | Edit the customer's GSTIN → app auto-updates State → regenerate the invoice. Do **not** edit the invoice number (it is server-assigned; there is no override). |
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

**What is this?**
QORVENA is built to survive flaky mobile networks and dropped Wi-Fi. Even if the internet flickers while you click **Save**, the app never saves the same record twice.

**What you will see**
- One green **Saved** confirmation, not two.
- If the network drops mid-save, the app quietly retries in the background.
- Your typed data is not lost.

**If the Save confirmation doesn't appear**
1. Wait about 30 seconds — the app is retrying quietly.
2. If nothing appears, hard-refresh with **Ctrl + Shift + R**.
3. Open the list view (Trips, Invoices, etc.) and check whether the record is already there **before** you re-enter it.

> TIP · The green **Saved** toast is your proof. If you see it, the record is on the server — even if the page looks like it is still loading.

---

## 16. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Customer "Already Exists" dialog with **Continue Creating** button | Name-only match (warning) | Verify the details. Click **Continue Creating** if this is a genuine namesake or a different branch. |
| Customer or Supplier "Already Exists" **without** a **Continue Creating** button | The GSTIN, PAN, or Supplier name already exists | Click **Open Existing** and edit that record. If the block is genuinely wrong, ask your Owner or Admin to override it with a reason. |
| Vehicle "Already Exists" dialog | Vehicle number is already registered in your account | Click **Open Existing**. The app never creates two records for the same vehicle. |
| **REFRESHING…** pill visible for more than 15 seconds | The app is re-checking its connection to the server, often after the laptop woke up from sleep | Wait 15–30 seconds. If it stays, press **Ctrl + Shift + R** to reload. |
| Invoice PDF still shows the old State | The Ship-To Site was corrected but the invoice PDF hasn't been regenerated | Edit the Ship-To Site → **Save** → open the invoice and regenerate the PDF. |
| Shortage column shows **—** unexpectedly | The trip's **Unload Qty** has not been entered yet | Open the trip, fill Unload Qty and Unload Date, then Save. Shortage will appear automatically. |
| Shortage column shows the full Load MT | Your browser is showing an old copy of the invoice PDF | Press **Ctrl + Shift + R** to force a fresh copy. The latest invoice will correctly show **—** for pre-unload trips. |
| Amber **App update available** nudge | A newer build of QORVENA has been released | Click the nudge. Your in-flight draft is preserved. |
| **Access denied** message when clicking **Deactivate** on a supplier | Your role does not have permission | Ask an Owner or Admin to perform the action. |
| Nothing happens after you click **Save** | The internet dropped and the app is retrying quietly | Wait 30 seconds. Check the list view to see whether the record was saved before re-entering. |

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
- Do **NOT** create duplicate customers — click **Open Existing** on the warning dialog. For genuine namesakes, use **Continue Creating** (only shown for name matches).
- Do **NOT** hard-refresh during a Save — wait for the confirmation toast.
- Do **NOT** manually edit the invoice number — it is server-assigned; change the Prefix / Next Number in **Settings** only when starting a new FY.
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

1. **Duplicate Masters** —
    - **Customer** · GSTIN and PAN matches are blocked; **Name** matches show a warning that a regular user can bypass with *Continue Creating* (Owner/Admin can also override GSTIN/PAN via the admin flow with a written reason). Phone matches are advisory only.
    - **Supplier** · GSTIN, PAN, **and Name** all block creation; mobile is advisory only. No *Continue Creating* button on the supplier dialog.
    - **Vehicle** · Match on vehicle number is idempotent — the backend returns the existing row, never inserts a second. Modal offers Cancel / Open Existing.
2. **Ship-To Independence** — Ship-To State is independent of Customer State; GSTIN can derive State / State Code; Customer State is never silently copied to a Ship-To.
3. **Trip Loading and Unloading** — Loading and Unloading are **separate stages**. Freight is available at dispatch; shortage requires unloading data.
4. **Missing Unload Data** — Blank unload fields mean "Not Available Yet" — NOT "zero unloaded". Pre-unload invoices must NOT show fabricated shortages.
5. **Invoice Ship-To** — Preview and PDF are guaranteed identical. GSTIN is cleaned on display. Unload Date renders correctly on the PDF row.
6. **Invoice Number** — Server-assigned as `{Prefix}/{FY}/{Sequence}` per company. No per-invoice user override. Prefix and Next Number are set once in **Settings**; both are Owner/Admin-only.
7. **Invoice Pagination** — Every PDF shows Page X of Y on every page; the signature block appears on the last page only.
8. **Supplier Deactivate** — Soft-delete only. All historical LRs, trips, and invoices remain intact. Show Inactive toggle reveals them; Reactivate is one click. Owner / Admin only.
9. **Draft Recovery** — Only meaningful, non-empty forms are offered for restore. Blank forms are ignored.

---

## Appendix C · Support

For questions about the application:

1. Read the relevant section of this manual.
2. Contact your Owner or Admin.
3. For production support, email **bitumentra@gmail.com**.

---

End of manual · Version 1.0 · Released February 2026

QORVENA · Bitumen Transport ERP
