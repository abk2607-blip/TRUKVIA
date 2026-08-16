# PHASE 2 — QORVENA Mobile App (PARKED)

**Status:** 🅿️ Parked · Do NOT start until Web App reaches v1.0 stable and passes real-world testing.
**Document owner:** User (business owner)
**Last confirmed:** Feb 2026
**Priority order (locked):** 1️⃣ Driver App → 2️⃣ Supplier App → 3️⃣ Office / Admin

---

## 0. Guardrail — Do NOT Start Yet
Do NOT begin Mobile Phase 2 implementation until ALL of the following are done:
- Web App is at v1.0 stable
- All pending items closed: Trips, Suppliers, Drivers, Invoices, Customers, Ship-To, Ledger, Settlement
- Regression Guard passes clean 3 runs in a row on `main`
- Real-world testing sign-off from user

When ready to start, tag the web release as `v1.0-web-stable` first.

---

## 1. Full Mobile Specification (verbatim from user's Feb 2026 spec doc)

### 1.1 Mobile App Login — Role Based Access
Three access types, secure OTP-based login using phone numbers already stored in the web app's Driver and Supplier master data. Same backend authentication and company/tenant isolation as the web app.

- A. Office / Admin Login
- B. Driver Login
- C. Supplier Login

### 1.2 Driver Login — Scope
When a Driver logs in they see ONLY:
- Own profile / basic details
- Own currently active trips (only trips assigned to that Driver)
- Trip details required to complete the trip:
  - Current loading/unloading status
  - Unloading destination / site
  - Vehicle number
  - Customer / Trip reference (where required)

Driver MUST NOT see:
- Other drivers' trips or details
- Supplier master · Customer master
- Supplier ledger · Customer ledger
- Invoices · Company financial info
- Any other administrative modules
- Any other driver's data

### 1.3 Driver — Unload Receipt Upload
For every active Trip, after the vehicle is unloaded:
- Open the active Trip → "Upload Unload Receipt"
- Camera capture OR gallery pick → Submit
- Receipt must be linked to `Trip ID + Driver ID + Vehicle ID + Upload Date/Time` (never store as unlinked generic image)
- Office Dashboard must show: Trip → Unload Receipt → Photo → Driver → Vehicle → Upload Date/Time

Additional (agent recommendation): capture GPS coordinates + device timestamp alongside upload timestamp for fraud-check and proof-of-delivery.

### 1.4 Supplier Login — Scope
When a Supplier logs in they see ONLY:
- Their own vehicles and active trips on those vehicles

They MUST NOT see:
- Other suppliers or their vehicles / trips
- Company-wide trips
- Other supplier ledgers
- Customer master · Driver master
- Office administration · Other financial info

### 1.5 Supplier Trip View — Fields
For each active vehicle/trip the Supplier sees:
Vehicle Number · Driver name (limited) · Trip Date · Customer · From · To / Ship-To · Loading details · Unloading status · Trip reference · Current trip status

### 1.6 Supplier — Unload Receipt Upload
Supplier can also upload the unload receipt (own vehicles only).
Both Driver OR Supplier may upload for the same trip. Prevent unrelated users from uploading against another user's trip.

### 1.7 Login Using Existing Phone Numbers
Very important — reuse existing master data:
- `Driver Master → Mobile Number → Mobile Login → Driver ID`
- `Supplier Master → Mobile Number → Mobile Login → Supplier ID`

Do NOT create a separate Driver/Supplier user database. Use proper OTP auth, don't trust a raw phone number sent by the app.

### 1.8 Supplier Statement Sharing (Office-controlled)
- Office user clicks "Share Statement with Supplier"
- Supplier can then view the statement inside their mobile app
- Supplier sees ONLY their own statement — never another supplier's by ID, URL or API manipulation

### 1.9 Statement Access — 5 Day Time Limit
- Share Statement → 5-day validity window
- After expiry: "This statement access has expired. Please contact the office for a new statement."
- Office can re-share to generate a new 5-day access period

Store per share:
`Statement ID · Supplier ID · Shared By · Shared Date/Time · Expiry Date/Time · Access Status · Version/Ledger snapshot reference`

### 1.10 Statement Must Be a Snapshot (Accounting-safe)
Statement represents the ledger AT THE MOMENT it was shared. If the ledger changes later, the already-shared statement must NOT silently change. Generate `Statement Snapshot → Share for 5 Days`. Supplier sees the exact snapshot Office approved.

### 1.11 Office Dashboard — Mobile Audit Trail
Office sees Driver/Supplier mobile activity:
- Receipt uploaded → Trip number · Vehicle · Uploaded by · Upload time · Receipt image
- Statement shared → expiry · viewed / accessed status

### 1.12 Security (Non-Negotiable)
Strict role-based access control enforced on the BACKEND, not just in the mobile UI.
- Driver hitting `GET /api/trips` receives ONLY trips assigned to that Driver
- Supplier receives ONLY active trips on their vehicles
- Any manual API modification → 403 / no access
- Maintain: `company_id` (tenant) + user role + `driver_id` / `supplier_id` filtering on every relevant endpoint

### 1.13 Recommended Development Sequence
- **Phase 1 — Web App (current)**: Trips · Customers · Suppliers · Vehicles · Drivers · Ship-To · Invoice · Ledger · Settlement · Shortage · Halting · Search
- **Phase 2a — API Hardening**: Add `PermissionContext(role, driver_id, supplier_id)` middleware; audit every `/api/*` for tenant + role scoping; add `test_role_permissions.py` regression pytest
- **Phase 2b — Mobile Backend/API Preparation**:
  - `POST /api/auth/otp/send`
  - `POST /api/auth/otp/verify`
  - `GET /api/mobile/driver/trips` (active-only, driver-scoped)
  - `GET /api/mobile/supplier/trips` (active-only, supplier-scoped)
  - `GET /api/mobile/trips/{id}` (permission-checked)
  - `POST /api/trips/{id}/unload-receipt` (multipart + idempotency key + GPS + device ts)
  - `GET /api/trips/{id}/unload-receipts` (list for office view)
  - `POST /api/supplier-statements/share` (creates snapshot + 5-day token)
  - `GET /api/supplier-statements/{token}` (validates expiry + supplier binding)
  - `POST /api/supplier-statements/{token}/revoke` (office-only)
  - `GET /api/mobile/audit-log` (office dashboard feed)
- **Phase 3 — Mobile App Build**: React Native + Expo (single codebase iOS+Android). Priority order: Driver → Supplier → Office.
- **Phase 4 — Testing**:
  - Driver A cannot see Driver B's trips
  - Supplier A cannot see Supplier B's vehicles/trips
  - Supplier cannot access another Supplier's statement
  - Expired statement cannot be accessed after 5 days
  - Receipt uploaded by Driver appears against correct Trip in Office Dashboard
  - Receipt uploaded by Supplier appears against correct Trip in Office Dashboard

### 1.14 Architecture Rule
Same existing backend/DB. Same Trip IDs, Driver IDs, Supplier IDs, Vehicle IDs.
`Office Web App ↔ Same Backend ↔ Driver/Supplier Mobile App` — no duplicate data entry.

---

## 2. Agent Recommendations (over and above user spec)

These are NOT in the original spec — capture now so we don't rediscover them later.

1. **OTP-based login** (Twilio SMS) — server issues short-lived JWT bound to `driver_id`/`supplier_id`/`company_id`. No passwords for drivers.
2. **Same phone number → multiple roles** (owner-driver case): OTP response returns list of `(company, role)` bindings; user picks role at sign-in.
3. **Multi-tenant on same phone**: same handling — pick company + role at login.
4. **"Active trip" definition**: `status ∈ {loaded, in_transit}` OR `date within last 7 days AND status != completed`.
5. **Receipt upload metadata**: image → Object Storage. Alongside: GPS lat/lng, device timestamp, server upload timestamp, client-declared unload time, optional recipient signature.
6. **Statement snapshot storage**: materialized JSON blob (opening balance + trips/payments/adjustments as of shared-at + closing balance + checksum) in new `supplier_statement_snapshots` collection. NOT a live query.
7. **Offline mode for drivers**: unload-receipt upload queues locally, syncs on reconnect. Requires idempotency key on the API.
8. **Revoke-Access before expiry** button for office users.
9. **Trip Completion Signature** (proposal): 3-finger tap OR on-screen signature by site person at unload. Converts driver's phone into an LR-closer device.
10. **DO NOTs**:
    - Do NOT ship WhatsApp share links for statements (forwardable = leak).
    - Do NOT persist mobile session forever — 30-day refresh tokens, force re-OTP on device fingerprint change.
    - Do NOT show suppliers a raw "unpaid amount" (UPI-pressure lever). Show only what's on the approved snapshot.
    - Do NOT rate-let OTP unlimited — 3 per hour per phone number.
    - Do NOT build native-per-platform for MVP. Expo (RN) only.

---

## 3. Cost Estimate — Preliminary (NOT a fixed final cost)

### 3.1 Estimated Emergent Credits: **400–800 credits (~₹6,500–₹13,000 / ~$80–$160)**

Treat this as an estimate. Real cost depends on iteration count, testing volume, and how much scope is added mid-build.

### 3.2 Breakdown — What IS included in the 400–800 credits
| Bucket | Credits |
|---|---|
| Initial setup + Expo/RN scaffold + OTP auth + role-based middleware | 50–100 |
| Core feature build (3 roles, receipt upload w/ camera+GPS, statement snapshot + 5-day expiry, audit log) | 250–500 |
| Testing & debugging (mobile testing agent + role isolation pytest suite) | 50–100 |
| Iterations & UI polish | 50–100 |

### 3.3 What is NOT included in the 400–800 credits
- ❌ **Twilio SMS/OTP send costs** — separate from Emergent credits (paid per SMS to Twilio, ~₹0.30–₹0.60 per SMS in India; budget ~₹1,000–₹3,000/month for typical 10-driver / 20-supplier tenant)
- ❌ **Google Play Store one-time developer fee** — ₹2,000 (one-time, per developer account)
- ❌ **Apple App Store developer fee** — ~₹9,000/year (only if publishing to iOS)
- ❌ **App Store Optimization / icon design / screenshots** — optional, external
- ❌ **Additional integrations** if scope grows (e.g., WhatsApp business API, push notifications provider)
- ❌ **Ongoing Emergent deployment cost** — see 3.4
- ❌ **Any real-world beta rollout support hours** (device debugging, driver hand-holding)

### 3.4 Emergent deployment cost (production)
- The mobile app CAN reuse the existing web backend deployment → **₹0 extra backend deploy cost**
- If a separate mobile backend is chosen → **~50 credits/month** per deployment
- Emergent-managed Object Storage usage is included in the platform plan (already provisioned)

### 3.5 Mobile Agent / Subscription
- Mobile App development in Emergent requires the **Mobile Agent**, which requires a **paid subscription**
- Switch via: Agent selector (top of chat) → select **Mobile**
- Check current subscription: **Profile → Manage Plan**
- Check credit balance: **Profile → Credits** (Monthly + Top-up + Bonus)

### 3.6 Cost-optimization playbook (for when we start)
1. Build role-by-role: **Driver → Supplier → Office**. Push to GitHub between roles.
2. Use **Rollback** instead of debugging in circles.
3. Fork context when approaching context limits (fresh handoff summary → cheaper iterations).
4. Batch related features into one session (e.g., all receipt-upload work together).
5. Keep the shared backend — do NOT duplicate business logic in the mobile client.

### 3.7 Total realistic budget for a small-to-medium fleet (10–20 drivers, 20–40 suppliers)
| Item | One-time | Recurring (monthly) |
|---|---|---|
| Emergent Mobile build credits | ₹6,500–₹13,000 | — |
| Play Store developer fee | ₹2,000 | — |
| Apple developer (optional) | — | ₹750 (₹9,000/yr amortized) |
| Twilio SMS OTP | — | ₹1,000–₹3,000 |
| Emergent hosting (reuse web backend) | — | ₹0 extra |
| **Total** | **~₹8,500–₹15,000** | **~₹1,000–₹3,750/month** |

---

## 4. Pre-flight Checklist (do these BEFORE calling Mobile Agent to start)

- [ ] Web App at v1.0-web-stable (git tag)
- [ ] Regression Guard clean 3× on main
- [ ] Real-world web testing sign-off from user
- [ ] Twilio account created + verified sender number
- [ ] Google Play Console account paid (₹2,000 one-time)
- [ ] Confirm Mobile Agent subscription active
- [ ] Confirm credit balance ≥ 800
- [ ] Freeze the Phase-2 spec (this file) — no scope additions mid-build
- [ ] Backup snapshot of current DB and codebase

---

## 5. When Ready to Start

Open a new chat with the Mobile Agent and paste this reference:

> "Start Phase 2 Mobile App per `/app/memory/PHASE_2_MOBILE.md`. Priority order: Driver first, then Supplier, then Office. Reuse existing FastAPI backend at same URLs. Do not duplicate DB or business logic. Confirm subscription + credit balance before starting."
