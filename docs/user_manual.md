# QORVENA · Bitumen Transport ERP
## User Manual (Bilingual · English + తెలుగు)

**Version**: 1.0 · Feb 2026
**Application**: QORVENA / Bitumen Transport ERP
**Scope**: All modules, all workflows, current locked behaviour

> This manual describes the application as it exists today. UI labels are kept in English (exactly as they appear in the app); Telugu explanations sit alongside so your local team can follow.

---

## Table of Contents

1. Getting Started · పరిచయం
2. Dashboard · డాష్‌బోర్డ్
3. Masters · మాస్టర్ డేటా
   - 3.1 Customers · కస్టమర్లు (+ Ship-Sites, GSTIN → State)
   - 3.2 Suppliers · సప్లయర్లు (+ Deactivate / Reactivate)
   - 3.3 Consignor · కన్సైనర్
   - 3.4 Vehicles · వాహనాలు
   - 3.5 Drivers · డ్రైవర్లు
   - 3.6 Products · ప్రొడక్ట్‌లు
   - 3.7 Shortage Policy · షార్టేజ్ పాలసీ
4. Trips · ట్రిప్‌లు
   - 4.1 Creating a Trip · కొత్త ట్రిప్
   - 4.2 Loading · లోడింగ్
   - 4.3 Unloading · అన్‌లోడింగ్
   - 4.4 Freight vs Shortage · ఫ్రైట్ vs షార్టేజ్
   - 4.5 Trip Templates · టెంప్లేట్‌లు
5. Fuel · ఫ్యూయెల్
6. Invoices · ఇన్వాయిస్‌లు
   - 6.1 Creating an Invoice · ఇన్వాయిస్ create చేయడం
   - 6.2 Ship-To handling · Ship-To నిర్వహణ
   - 6.3 Pre-unload vs Completed-unload · అన్‌లోడ్‌కు ముందు vs తర్వాత
   - 6.4 Invoice PDF · ఇన్వాయిస్ PDF (Page X of Y)
7. Payments · పేమెంట్‌లు
8. Reports · రిపోర్ట్‌లు
9. Customer History · కస్టమర్ హిస్టరీ
10. Files · ఫైల్‌లు
11. Team & Roles · టీమ్ మరియు రోల్స్
12. Settings · సెట్టింగ్స్
13. Common Real-World Situations · సాధారణ పరిస్థితులు
14. Form Draft Recovery · ఫారం డ్రాఫ్ట్ రికవరీ
15. Save Retry / Resilience · Save విఫలమైతే
16. Troubleshooting · సమస్యలు పరిష్కారం
17. Do's and Don'ts · ఏం చేయాలి, ఏం చేయకూడదు

---

## 1. Getting Started · పరిచయం

**English**: QORVENA is a Bitumen transport ERP that tracks LRs, Trips, Freight, Shortage, Invoices, Payments, Suppliers, Customers, and Reports. It runs in your browser and stores data in the cloud.

**తెలుగు**: QORVENA అనేది Bitumen transport కోసం ERP. ఇది LR (Lorry Receipt), Trip, Freight, Shortage, Invoice, Payment, Supplier, Customer, Report — అన్నీ track చేస్తుంది. Browser లో run అవుతుంది, data cloud లో save అవుతుంది.

**Login · లాగిన్**:
1. Open the app URL in your browser.
2. Click **Sign in with Google** (Google account తో login చేయండి).
3. First-time users see the setup wizard for Company details.

**Screenshot**: `screenshots/01_login.png` (auto-captured or user-supplied)

---

## 2. Dashboard · డాష్‌బోర్డ్

**Purpose · ఉద్దేశం**: One-glance business overview — key numbers, top customers, top suppliers, recent activity.

**Key Cards / ముఖ్యమైన కార్డులు**:
- **Total Outstanding** — customers ఎంత pending చెల్లించాలి
- **Total Payable** — suppliers కి ఎంత pending pay చేయాలి
- **Recent Trips** — తాజా trip records
- **Top Suppliers by Outstanding** — ఎక్కువ pending ఉన్న suppliers
- **Monthly Freight** — ఈ నెల total freight

**Screenshot**: `screenshots/02_dashboard.png`

---

## 3. Masters · మాస్టర్ డేటా

Masters are the foundational records. Set them up correctly ONCE, then all Trips / Invoices / Reports work automatically.

**తెలుగు**: Masters అంటే — Customers, Suppliers, Vehicles, Drivers, Products మొదలైనవి. వీటిని ఒక్కసారి సరిగ్గా setup చేస్తే, తర్వాత Trip / Invoice / Report ప్రతిదీ automatic గా పనిచేస్తుంది.

### 3.1 Customers · కస్టమర్లు

**Path**: `Suppliers → Customers` (left navigation).

**Fields / ఫీల్డ్స్**:
| Field | Telugu | Required? |
|---|---|---|
| Name | పేరు | ✅ |
| Phone | ఫోన్ | ✅ |
| GSTIN | జి.ఎస్.టి.ఐ.ఎన్ | Optional but recommended |
| State | రాష్ట్రం | ✅ (auto-fills from GSTIN if valid) |
| Pincode | పిన్‌కోడ్ | Optional |
| Opening Balance | ఓపెనింగ్ బ్యాలెన్స్ | 0 by default |

**Duplicate check · నకిలీ చెక్**:
The app blocks creating a customer with the same **name + phone** or **same GSTIN** as an existing customer. If you see the "Duplicate detected" warning, use **View existing** instead of creating a new record.

**Do NOT · చేయకూడదు**:
- Do NOT create a duplicate customer to "fix" a spelling mistake — Edit the existing one instead.
- Do NOT paste a GSTIN with extra "GSTIN " prefix — the app now cleans it on Save, but keep it neat.

**Screenshot**: `screenshots/03_customers_list.png`

#### 3.1.1 Ship-Sites · షిప్-సైట్‌లు

Every customer can have multiple **delivery locations** (Ship-Sites). Example: a customer with sites in Nagarkurnool + Karwar.

**Path**: Customer row → **Ship Sites** action.

**Fields**:
- Site Name · సైట్ పేరు
- Address · చిరునామా
- **GSTIN** · జి.ఎస్.టి.ఐ.ఎన్ — when you enter a valid GSTIN, the **State and State Code auto-fill** from the first 2 digits (e.g. `36AAUFM1425D1ZC` → Telangana / 36).
- State / State Code / PIN — override manually if needed; app warns you if your entry conflicts with the GSTIN-derived state.

**Important · ముఖ్యమైనది**:
- Ship-Site State is INDEPENDENT of Customer State. Customer State ≠ Ship-To State is allowed.
- The app never silently copies Customer State onto a Ship-Site. What you enter, is what invoice shows.

**Screenshot**: `screenshots/04_ship_site_form.png`

### 3.2 Suppliers · సప్లయర్లు

**Path**: `Suppliers → List`.

**Fields**: Similar to Customers — Name, Phone, GSTIN, State, PAN, opening balance.

**Duplicate check**: same name + phone or same GSTIN is blocked.

#### 3.2.1 Deactivate / Reactivate

**Business need · అవసరం**: A supplier who no longer works with you should be hidden from active screens BUT their historical trips + invoices must remain intact.

**How to Deactivate · deactivate ఎలా చేయాలి**:
1. Suppliers → **List** tab (not the dashboard).
2. Find the active supplier row.
3. Click the red **Deactivate** button (right-most column).
4. A modal shows any linked vehicles / trips / payments (dependency counts).
5. Enter a reason (mandatory) and click **Deactivate**.

**How to Reactivate**:
1. Toggle **Show Inactive** at the top-left.
2. Inactive suppliers appear in grey.
3. Click the green **↻ Reactivate**.

**Permissions · అనుమతులు**: Only **Owner** or **Admin** roles can Deactivate/Reactivate. Other roles get a 403 error toast.

**Do NOT**:
- Do NOT delete a supplier record — always Deactivate. Deleting would break historical invoices.

**Screenshot**: `screenshots/05_supplier_deactivate.png`

### 3.3 Consignor · కన్సైనర్

Consignors are the parties who dispatch the product. Similar create/edit flow. Used when the consignor differs from the customer being billed.

### 3.4 Vehicles · వాహనాలు

Track each truck / tanker.

**Fields**: Vehicle number, capacity (MT), current supplier, insurance/permit expiry, RC number.

**Duplicate check**: same vehicle number is blocked.

### 3.5 Drivers · డ్రైవర్లు

**Fields**: Name, phone, licence number/expiry, associated supplier, salary/policy.

### 3.6 Products · ప్రొడక్ట్‌లు

E.g. Bitumen VG 40, VG 30, Emulsion. Each product carries:
- **Rate per MT** — used when calculating shortage deductions.
- **Allowance %** — the acceptable shortage window (Product Master or Customer Custom Allowance can override).

### 3.7 Shortage Policy · షార్టేజ్ పాలసీ

Every trip snapshots the customer's shortage policy at trip-creation time. Common methods:
- **Net Shortage** — deduct only the amount ABOVE the allowance
- **Full Shortage after Limit** — deduct the entire shortage once the allowance is crossed

Policy changes on the Customer master do NOT retroactively change historical trips — they only apply to NEW trips going forward. This is intentional and protects your books.

---

## 4. Trips · ట్రిప్‌లు

### 4.1 Creating a Trip · కొత్త ట్రిప్

**Path**: `Trips → Add` (top-right +).

**Sections**:
1. **Basics** — Date, Vehicle, Driver, Customer, Consignor.
2. **Loading** — From location, Product, Loading Qty (MT), LR number.
3. **Freight** — Freight mode (Per Ton / Fixed / Round Trip), Rate.
4. **Unloading** (fill later) — Unload Date, Unload Qty, To location, **Ship-Site**.
5. **Advances / Diesel from Customer** — money you gave the driver.
6. **Halting** (fill after unload) — arrival date, waiting days.

**Save · సేవ్**:
- Click **Save Trip**. Green toast confirms.
- If your network is slow, the app retries automatically (Idempotency-Key protects against double-submit).

### 4.2 Loading · లోడింగ్

Enter the loading quantity in **MT** (tons). LR number should be unique per company.

### 4.3 Unloading · అన్‌లోడింగ్

**IMPORTANT · ముఖ్యమైనది**:
Unloading fields (Unload Date + Unload Qty) can be filled LATER, after the vehicle actually reaches the destination and unloading is done.

- **Unload Qty (in MT)** — actual quantity that came out of the tanker.
- **Unload Date** — the calendar date of unloading.

If you leave these blank because unloading hasn't happened yet, the invoice will correctly show `—` for Actual Short / Allowance / Net Short. **The app does NOT treat blank unload as zero unload.**

### 4.4 Freight vs Shortage · ఫ్రైట్ vs షార్టేజ్

These are TWO different business states:

| When? | Freight | Shortage |
|---|---|---|
| Loading complete, dispatched | ✅ Calculated | ❌ Not available yet |
| Vehicle unloaded, qty entered | ✅ | ✅ Calculated using existing policy |

**Rule · నియమం**: Freight is available as soon as loading is done. Shortage is only meaningful after actual unloading data is entered. **Do NOT invent an Unload Qty just to see a shortage number** — leave it blank until you actually know.

### 4.5 Trip Templates · ట్రిప్ టెంప్లేట్‌లు

For repetitive routes (same customer, same product, same rate), save a **Template** so next time one click fills the whole form. Path: `Trips → Templates`.

---

## 5. Fuel · ఫ్యూయెల్

Track fuel purchases and issues to vehicles. Optional but useful for costing.

---

## 6. Invoices · ఇన్వాయిస్‌లు

### 6.1 Creating an Invoice · ఇన్వాయిస్ create చేయడం

**Path**: `Invoices → Create`.

**Steps · స్టెప్‌లు**:
1. Select **Customer**.
2. Filter Trips (date range, ship-site).
3. **Tick the trips** to include.
4. Set **Invoice Date** and **Invoice Number** (or auto-generate).
5. Click **Preview**.
6. Click **Save**.

**Invoice numbering**: The app auto-generates the next number per company (e.g. `AKB/26-27/0018`). You can override once, but don't reuse a number.

### 6.2 Ship-To handling · Ship-To నిర్వహణ

The invoice header shows a single **Ship To** block if all selected trips point to the SAME physical delivery site — even when one trip has an explicit `ship_site_id` and another only has a `to_location` string that clearly matches the same site (name / pincode / address).

If the selected trips go to genuinely different Ship-Sites, the invoice shows:
> "Mixed destinations — see trip rows below"

And each trip row prints its own Ship-To detail. This is intentional and protects invoice accuracy.

### 6.3 Pre-unload vs Completed-unload · అన్‌లోడ్‌కు ముందు vs తర్వాత

You CAN raise an invoice as soon as the vehicle is dispatched — you don't have to wait for unloading.

**Pre-unload invoice · అన్‌లోడ్ కాకముందు invoice**:
- Load MT ✅ actual value
- Unload MT · Unload Date · Actual Short · Allowance · Net Short — all `—`
- Freight — correctly calculated
- Invoice total = Freight + Tax (no shortage deducted)

**After unloading is entered**, the shortage engine runs automatically and the invoice can be regenerated to reflect the actual short/allowance/net.

**Do NOT · చేయకూడదు**:
- Do NOT enter `Unload Qty = 0` to force-close a trip. Leave it blank until the real number is known. `0` MT will be treated as a real zero-unloaded value — a total loss — which is almost never what you want.

### 6.4 Invoice PDF · ఇన్వాయిస్ PDF (Page X of Y)

Every invoice PDF shows **Page X of Y** in the bottom-right corner of every page:
- 1-page invoice → `Page 1 of 1`
- 2-page invoice → `Page 1 of 2` / `Page 2 of 2`
- Long invoices flow across as many pages as needed.

Signature block appears only on the LAST page.

**GSTIN**: The Ship-To GSTIN is cleaned automatically — even if it was originally stored with prefix "GSTIN " or extra tabs, the PDF now displays only the 15-char GSTIN.

**Screenshot**: `screenshots/10_invoice_pdf.png`

---

## 7. Payments · పేమెంట్‌లు

Record customer receipts and supplier payments.

**Path**: `Payments → Add`.

**Fields**: Party (customer/supplier), amount, mode (cash/bank/UPI/cheque), reference, date, receipt/voucher number.

The app updates the party's balance immediately.

---

## 8. Reports · రిపోర్ట్‌లు

**Path**: `Reports` — a menu of pre-built reports:
- **LR Register** — every LR with load/unload/freight/shortage
- **Customer Statement** — invoice-wise ledger with running balance
- **Supplier Settlement** — trip-wise settlement with driver/supplier splits
- **GSTR-1 Ready** — invoice-wise GST summary
- **Cash Flow** — receipts vs payments by date
- **P&L** — freight income vs costs

Each report has date filters and Export to Excel / PDF.

---

## 9. Customer History · కస్టమర్ హిస్టరీ

Deep-drill single customer view: all trips, invoices, payments, running balance on one page. Also shows outstanding age buckets (0-30, 30-60, 60-90, 90+ days).

---

## 10. Files · ఫైల్‌లు

Attach documents (LR scans, delivery challans, driver docs) to trips / suppliers / drivers. Files are stored securely in cloud object storage.

---

## 11. Team & Roles · టీమ్ మరియు రోల్స్

**Path**: `Team`.

**Roles · పాత్రలు**:
- **Owner** · యజమాని — full access + Team management + Supplier Deactivate
- **Admin** · అడ్మిన్ — most write access + Supplier Deactivate
- **Manager** · మేనేజర్ — create/edit trips/invoices/payments; no Deactivate
- **Accountant** · అకౌంటెంట్ — invoice & payment access; read-only masters
- **Viewer** · వ్యూయర్ — read-only

Owner invites team members by email. Members log in via Google.

---

## 12. Settings · సెట్టింగ్స్

**Path**: `Settings`.

- **Company** — legal name, address, PAN, GSTIN, bank details (used on Invoice PDF header + bottom)
- **Numbering** — invoice number format
- **Products** — see 3.6
- **Shortage policy** — see 3.7
- **Notifications** — email digests

---

## 13. Common Real-World Situations · సాధారణ పరిస్థితులు

| Situation · పరిస్థితి | What to do · ఏం చేయాలి |
|---|---|
| Driver called; unloaded qty confirmed | Open trip → Unloading section → enter Unload Qty + Unload Date → Save. Then regenerate invoice PDF. |
| Customer says GSTIN was wrong on invoice | Edit the customer's GSTIN → app auto-updates State → regenerate the invoice. Do NOT edit invoice number. |
| Supplier retired; don't want in dropdowns | Suppliers → List → Deactivate. Old trips remain. |
| Ship-Site State was wrong | Edit Ship-Site → GSTIN auto-suggests correct State. Only future invoices reflect the change; already-issued invoices stay historical unless you re-open + Save them. |
| Vehicle broke down mid-trip; no unloading yet | Save the trip with Load MT and blank Unload. Invoice can still be raised for freight; shortage stays `—`. |
| Duplicate customer created accidentally | Merge is not automatic. Deactivate the wrong one, move trips manually if needed. Ask an Admin. |

---

## 14. Form Draft Recovery · ఫారం డ్రాఫ్ట్ రికవరీ

If your browser closes or the tab crashes while filling a Trip / Customer / Invoice form, the app **auto-saves a local draft**.

Next time you open that form, you'll see a subtle "Restore draft?" banner. Click it to restore your entries.

**Important**: drafts live in the browser only — they don't sync across devices. Save the form as soon as you're done to persist to cloud.

---

## 15. Save Retry / Resilience · Save విఫలమైతే

Every Save call carries a unique **Idempotency-Key**. If your network flickers and the app retries automatically:
- The server recognises the duplicate and does NOT create two records.
- You'll see one green toast, not two.
- Business data stays consistent.

If a Save toast never appears, wait a moment — the app is retrying. If it still doesn't succeed after ~30s, refresh the page (Ctrl+Shift+R) and check whether the record was actually saved before re-entering.

---

## 16. Troubleshooting · సమస్యలు పరిష్కారం

| Symptom · లక్షణం | Likely cause · కారణం | Fix · పరిష్కారం |
|---|---|---|
| "Duplicate detected" | Same name+phone or same GSTIN exists | Search & open the existing record |
| "REFRESHING..." pill visible | Backend health probe temporarily failing (often after browser sleep/wake) | Wait ~15 s; if persistent, Ctrl+Shift+R |
| Invoice PDF shows old State | Ship-Site wasn't saved with the new State | Edit Ship-Site → Save → regenerate invoice |
| Shortage shows `—` unexpectedly | Trip's Unload Qty is blank/0 | Enter actual Unload Qty; shortage will auto-appear |
| Actual Short = full Load MT | Old cached invoice PDF | Hard-reload (Ctrl+Shift+R); latest engine will show `—` for pre-unload |
| Amber "App update available" nudge | A newer build has shipped | Click it — your drafts are preserved |
| 403 on Supplier Deactivate | You're not Owner/Admin | Ask Owner to do it |

---

## 17. Do's and Don'ts · ఏం చేయాలి, ఏం చేయకూడదు

### ✅ DO
- Set up all Masters (Customers, Vehicles, Drivers, Products) FIRST.
- Use Ship-Sites for multi-location customers.
- Enter GSTIN cleanly — the app will auto-fill State.
- Leave Unload fields blank until the vehicle is actually unloaded.
- Regenerate invoice PDFs after data corrections.
- Use Trip Templates for repetitive routes.

### ❌ DO NOT
- Do NOT delete old suppliers/customers — always Deactivate.
- Do NOT enter `Unload Qty = 0` when unloading is pending.
- Do NOT create duplicate customers — search & edit the existing record.
- Do NOT hard-refresh during a Save — wait for the confirmation toast.
- Do NOT reuse invoice numbers — the app blocks this, but avoid trying.
- Do NOT modify Ship-Site State on historical customers expecting old invoices to change — they won't unless re-saved.
- Do NOT share your Google login — invite team members with their own emails.

---

## Appendix A · Keyboard Shortcuts

- **Ctrl + K** — global search
- **Ctrl + Shift + R** — force reload (use only if UI is stuck)
- **Esc** — close any modal

## Appendix B · Support

For questions about the application:
- Check this manual first.
- Contact your Owner / Admin.
- For production support, email **bitumentra@gmail.com**.

---

*End of manual · Version 1.0 · Feb 2026*
*QORVENA · Bitumen Transport ERP*
