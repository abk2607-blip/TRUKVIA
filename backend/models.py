"""All Pydantic domain models."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Literal, Any, Dict
from pydantic import BaseModel, Field, ConfigDict, model_validator


def now_utc():
    return datetime.now(timezone.utc)


def new_id(prefix: str = ""):
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def _coerce_none_to_default(cls, data: Any) -> Any:
    """Iter49 — Global defensive coercer.
    Legacy Mongo documents may contain `None` (JSON null) for fields whose
    Pydantic v2 schema declares `str` with a non-None default. Coerce these
    to their empty-string default instead of raising 422. This is the fix for
    "Trip Edit crashes with Pydantic validation error" when re-saving a trip
    whose row was created before a new str field was introduced."""
    if not isinstance(data, dict):
        return data
    for name, field in cls.model_fields.items():
        if name not in data:
            continue
        if data[name] is not None:
            continue
        ann = field.annotation
        # If the annotation includes None (Optional/Union with None), keep None
        try:
            args = getattr(ann, "__args__", None) or ()
            if type(None) in args:
                continue
        except Exception:
            pass
        # Coerce to default when we have one
        if field.default is not None and field.default is not ...:
            data[name] = field.default
        elif field.default_factory is not None:
            try:
                data[name] = field.default_factory()
            except Exception:
                pass
    return data


# ============================================================================
# Iter86 · Phase A — Historical Isolation Layer
# ----------------------------------------------------------------------------
# Every entity that can be imported from a legacy system (Transport Book etc.)
# carries these four columns. Backward-compatible defaults keep every existing
# record behaving exactly as before (`is_historical=False` implicitly).
#
# The `LIVE_ONLY_FILTER` constant MUST be spread into every Mongo query that
# computes a *live* financial aggregate (dashboard KPIs, ledgers, outstanding
# balances, driver salary, invoice-picker for new invoices, etc.). Search /
# view / list endpoints keep returning ALL records so historical data is still
# fully browseable.
# ============================================================================
LIVE_ONLY_FILTER: dict = {"is_historical": {"$ne": True}}



class Company(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: new_id("co_"))
    name: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    gstin: str = ""
    pan: str = ""
    state: str = ""
    pincode: str = ""
    bank_name: str = ""
    account_number: str = ""
    ifsc: str = ""
    branch: str = ""
    hsn_sac: str = "996791"
    invoice_prefix: str = "INV"
    next_invoice_number: int = 1
    # Iter134 · FY-scoped invoice sequence.  Keys are FY strings like "26-27".
    # Legacy `next_invoice_number` is preserved for backward compatibility and
    # self-heals into this map on first use for a given FY.  Numbering is
    # driven by invoice_date, not server clock — see services._next_invoice_number_for_company.
    next_invoice_number_by_fy: Dict[str, int] = Field(default_factory=dict)
    lr_prefix: str = "LR"
    next_lr_number: int = 1
    logo: str = ""  # data URL (base64)
    udyam_registration: str = ""  # MSME / Udyam Registration No. — appears in Invoice T&C
    # Iter134 · Invoice presentation settings (all optional; safe defaults).
    signature_file_id: str = ""              # linked FileRef.id — decorative signature image
    authorised_signatory_name: str = ""      # printed above "Authorised Signatory" label
    authorised_signatory_designation: str = ""
    signature_mode: Literal["none", "image", "dsc"] = "none"  # future-ready; only "image" active
    jurisdiction: str = ""                   # empty → clause hidden on PDF
    system_generated_note: str = ""          # empty → note hidden on PDF; max 200 chars
    is_default: bool = False
    # Iter132a · Credit Note / Debit Note numbering + configuration
    credit_note_prefix: str = "CN"
    next_credit_note_number: int = 1
    debit_note_prefix: str = "DN"       # reserved for Iter132b
    next_debit_note_number: int = 1     # reserved for Iter132b
    require_cdn_approval: bool = False  # draft→issued gate when true

class ShipSite(BaseModel):
    """Iter66 · Phase A — a customer's Ship-To / consignee site location.
    A Customer may have many.  ship_site_id on a Trip picks one."""
    id: str = Field(default_factory=lambda: new_id("ship_"))
    site_name: str
    address: str = ""
    gstin: str = ""
    state: str = ""
    state_code: str = ""
    pincode: str = ""
    contact_person: str = ""
    phone: str = ""
    is_default: bool = False
    is_active: bool = True


class ShortageConfig(BaseModel):
    """Iter89 · Phase 1 — Per-customer shortage configuration.
    limit: percentage-of-loaded (0..100) OR fixed KG, chosen via limit_type.
    method: `net_shortage` (deduct only excess above limit) OR `full_after_limit`
    (deduct FULL actual shortage once the limit is exceeded)."""
    limit: float = 0.0
    limit_type: Literal["pct", "kg"] = "pct"
    method: Literal["net_shortage", "full_after_limit"] = "net_shortage"
    effective_from: str = ""    # ISO date; blank = always
    active: bool = True
    remarks: str = ""


class Customer(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cust_"))
    name: str
    address: str = ""
    phone: str = ""
    email: str = ""
    gstin: str = ""
    pan: str = ""
    state: str = ""
    pincode: str = ""
    customer_code: str = ""          # Iter68 — optional short human-friendly code; searchable
    opening_balance: float = 0.0
    advance_balance: float = 0.0     # surplus payments; carried on the customer
    notes: str = ""
    reminder_enabled: bool = True
    ship_sites: List[ShipSite] = Field(default_factory=list)   # Iter66 · Phase A — multi Ship-To
    # Iter89 · Phase 1 — Customer-specific commercial defaults.
    # Trip snapshots freeze these at CREATE time so master edits never touch history.
    default_freight_method: Literal[
        "per_ton_loading", "per_ton_unloading", "per_ton_higher_of", "fixed"
    ] = "per_ton_loading"
    shortage_config: ShortageConfig = Field(default_factory=ShortageConfig)
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    # Iter86 · Historical Isolation Layer — legacy import flags (defaults keep existing behavior)
    imported_from: str = ""     # e.g. "transport_book"
    imported_ref: str = ""       # original ID in source system
    imported_batch: str = ""     # batch tag for grouped rollback
    is_historical: bool = False  # true = read-only archive; excluded from live aggregations

class Expenses(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _coerce_nones(cls, data):
        return _coerce_none_to_default(cls, data)

    diesel: float = 0.0
    toll: float = 0.0
    batta: float = 0.0
    repair: float = 0.0
    other: float = 0.0
    # Additional expenses / recoveries
    firewood: float = 0.0
    other_desc: str = ""
    other_remarks: str = ""
    diesel_from_customer_qty: float = 0.0
    diesel_from_customer_rate: float = 0.0
    diesel_from_customer_amount: float = 0.0   # recovery (reduces our cost)
    shortage_qty: float = 0.0
    shortage_amount: float = 0.0               # deduction from freight
    cash_advance_received: float = 0.0         # settlement only


class ExpenditureType(BaseModel):
    """Master list of Other Expenditure categories (Driver Food, Parking, Toll, ...)."""
    id: str = Field(default_factory=lambda: new_id("etype_"))
    name: str
    is_default: bool = False   # seeded defaults vs user-added
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


DEFAULT_EXPENDITURE_TYPES = [
    "Driver Food", "Parking", "Toll", "Loading Charges",
    "Unloading Charges", "Weighment", "Labour", "Detention",
    "Cleaning",
    # Iter136 · Non-trip / operational categories (additive; string field).
    "Insurance", "Road Tax", "Permit", "Fitness", "Tyres",
    "Engine Oil", "AdBlue", "Repair", "Spare Parts", "Office / General",
    "Others",
]

class Driver(BaseModel):
    id: str = Field(default_factory=lambda: new_id("drv_"))
    name: str
    phone: str = ""
    license_number: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    # Iter86 · Historical Isolation Layer
    imported_from: str = ""
    imported_ref: str = ""
    imported_batch: str = ""
    is_historical: bool = False

class FieldOverride(BaseModel):
    """Iter99 · Phase 4 — One entry in a Trip's per-field override audit log."""
    id: str = Field(default_factory=lambda: new_id("fov_"))
    field: str                       # e.g. freight_amount, shortage_amount, supplier_shortage_deduction
    label: str = ""                  # human label for the UI badge ("Freight" etc.)
    system_value: float = 0.0
    final_value: float = 0.0
    reason: str = ""
    modified_by: str = ""
    modified_at: str = Field(default_factory=lambda: now_utc().isoformat())
    trip_id: str = ""



class SupplierDieselEntry(BaseModel):
    """Iter91 — One entry in the Supplier Diesel funding log for a Trip.

    Diesel = us funding fuel for the supplier. `amount` is the source of truth
    (auto-computed as `quantity × rate` if not overridden).
    Soft-delete pattern: `deleted=true` excludes from totals & ledger; audit
    (reason/by/when) preserved.
    """
    id: str = Field(default_factory=lambda: new_id("sde_"))
    date: str = ""                  # ISO YYYY-MM-DD; defaults to trip.date on add
    quantity: float = 0.0           # litres
    rate: float = 0.0               # ₹ per litre
    amount: float = 0.0             # ₹; = quantity × rate unless overridden
    mode: str = ""                  # Cash / Bank / UPI / IMPS / NEFT / Other
    reference: str = ""             # transaction / voucher no.
    remarks: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    created_by: str = ""
    modified_at: str = ""
    modified_by: str = ""
    deleted: bool = False
    deleted_reason: str = ""
    deleted_at: str = ""
    deleted_by: str = ""


class SupplierAdvanceEntry(BaseModel):
    """Iter91 — One entry in the Supplier Advance log for a Trip. Same
    audit / soft-delete pattern as SupplierDieselEntry."""
    id: str = Field(default_factory=lambda: new_id("sae_"))
    date: str = ""
    amount: float = 0.0
    mode: str = ""                  # Cash / Bank / UPI / IMPS / NEFT / Other
    reference: str = ""
    remarks: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    created_by: str = ""
    modified_at: str = ""
    modified_by: str = ""
    deleted: bool = False
    deleted_reason: str = ""
    deleted_at: str = ""
    deleted_by: str = ""



class Trip(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _coerce_nones(cls, data):
        return _coerce_none_to_default(cls, data)

    id: str = Field(default_factory=lambda: new_id("trip_"))
    company_id: str = ""
    customer_id: str
    date: str  # ISO date
    vehicle_number: str
    vehicle_id: Optional[str] = None
    vehicle_type: Literal["own", "supplier"] = "own"
    # ---- Loading / Unloading (Feb 2026) ----
    loading_date: str = ""       # ISO date; if empty, `date` is used
    unloading_date: str = ""     # ISO date
    loaded_qty: float = 0.0      # MT loaded at origin
    unloaded_qty: float = 0.0    # MT received at destination
    excess_qty: float = 0.0      # auto: max(unloaded - loaded, 0)
    shortage_qty: float = 0.0    # auto: max(loaded - unloaded, 0)
    product_rate_per_mt: float = 0.0   # optional per-MT rate for excess/shortage valuation
    shortage_amount: float = 0.0       # auto: rate * shortage_qty (editable via override)
    excess_amount: float = 0.0         # auto: rate * excess_qty (editable via override)
    shortage_amount_override: bool = False   # true = user manually set shortage_amount
    excess_amount_override: bool = False
    # ---- Halting / Waiting charges (Feb 2026) ----
    total_halting_days: int = 0        # auto: (unloading_date - loading_date) days
    grace_days: int = 4                # user-editable (contractual)
    chargeable_halting_days: int = 0   # auto: max(total_halting_days - grace_days, 0), user-editable
    halting_rate_per_day: float = 0.0  # user-editable
    halting_amount: float = 0.0        # auto: chargeable * rate, user-editable
    halting_amount_override: bool = False
    # ---- Supplier fields ----
    supplier_id: str = ""              # Iter47 Phase 3: FK to Suppliers master (mandatory when vehicle_type=supplier)
    supplier_name: str = ""
    supplier_freight: float = 0.0
    # Supplier freight detailed calculation (mirrors customer billing)
    supplier_freight_mode: Literal["per_ton", "fixed"] = "per_ton"
    supplier_rate_per_ton: float = 0.0
    supplier_fixed_amount: float = 0.0
    supplier_round_trip_kms: float = 0.0
    supplier_rate_per_km_per_ton: float = 0.0
    supplier_loading_point: str = ""
    supplier_unloading_point: str = ""
    supplier_material: str = ""
    supplier_quantity: float = 0.0
    supplier_advance: float = 0.0
    supplier_diesel: float = 0.0                     # Diesel funded by us to supplier — deducted from payable
    # Iter92 — Supplier Halting Charges (independent from Customer Halting).
    # Manual only: NEVER auto-copied from customer halting_amount. Increases
    # supplier_net_payable when > 0. Original/revised values captured by the
    # standard trip audit-log diff (see routers.trips._log_audit).
    supplier_halting_days: float = 0.0
    supplier_halting_rate_per_day: float = 0.0
    supplier_halting_amount: float = 0.0             # user-entered; not auto-computed
    supplier_halting_remarks: str = ""
    # Iter91 — Multi-row diesel / advance transaction logs. When these lists
    # contain any non-deleted rows, `supplier_diesel` / `supplier_advance` are
    # OVERRIDDEN by the sum of their `amount` fields (see services._compute_trip).
    # Legacy trips without entries continue to use the flat fields (lazy
    # migration happens on the first read via routers/trips.get_trip).
    supplier_diesel_entries: List[SupplierDieselEntry] = Field(default_factory=list)
    supplier_advance_entries: List[SupplierAdvanceEntry] = Field(default_factory=list)
    supplier_shortage_deduction: float = 0.0         # Shortage deducted from supplier freight
    supplier_shortage_deduction_override: bool = False  # Iter74 — True when user manually edited; blocks auto-mirror from trip.shortage_amount
    # Iter111 · Supplier Shortage override audit fields. When the user edits
    # the calculated supplier_shortage_deduction:
    #   • supplier_shortage_original_amount holds the last system-computed
    #     value (kept in sync by services._compute_trip whenever override=False).
    #   • Reason, actor, timestamp captured mandatorily in trips.py PUT.
    #   • Restoring the manual value to the system value clears override + reason
    #     WITHOUT dropping an audit crumb (user rule 6 · no audit noise).
    supplier_shortage_original_amount: float = 0.0
    supplier_shortage_override_reason: str = ""
    supplier_shortage_override_by: str = ""
    supplier_shortage_override_at: str = ""
    supplier_other_recoveries: float = 0.0
    supplier_other_income: float = 0.0               # Bonus/other add-ons to supplier
    supplier_net_payable: float = 0.0
    driver_id: Optional[str] = None
    driver_name: str = ""
    driver_mobile: str = ""
    product_id: Optional[str] = None
    load_details: str = "Bitumen VG 40"
    hsn_sac: str = ""
    consignor_id: Optional[str] = None
    consignor_name: str = ""
    consignee_id: Optional[str] = None
    consignee_name: str = ""
    ship_site_id: str = ""                       # Iter66 · Phase A — selected Customer.ship_sites[].id (fallback to to_location if empty)
    customer_reference_number: str = ""          # Iter66 · Phase A — customer's own invoice/ref no. per trip; NEVER inherited
    tons: float
    from_location: str = ""
    to_location: str = ""
    from_pincode: str = ""
    to_pincode: str = ""
    freight_mode: Literal["per_ton", "fixed"]
    rate_per_ton: float = 0.0
    fixed_amount: float = 0.0
    round_trip_kms: float = 0.0
    rate_per_km_per_ton: float = 0.0
    freight_amount: float = 0.0
    expenses: Expenses = Field(default_factory=Expenses)
    total_expense: float = 0.0
    profit: float = 0.0
    net_settlement: float = 0.0
    # ---- Customer-provided (Iter36/39) ----
    customer_diesel_received: float = 0.0    # LEGACY total — kept for backward compat; sum of diesel receipts
    customer_advance_received: float = 0.0   # LEGACY total — kept for backward compat; sum of advance receipts
    customer_receipts: list = Field(default_factory=list)  # Iter39: [{id, date, type:'diesel'|'advance', ...}]
    # ---- Iter40: Other Expenditure (dynamic list) + Remarks ----
    other_expenditures: list = Field(default_factory=list)  # [{id, date, type, amount, remarks}]
    halting_remarks: str = ""
    shortage_remarks: str = ""
    excess_remarks: str = ""
    other_income: float = 0.0
    other_income_remarks: str = ""
    supplier_settlement_remarks: str = ""
    lr_driver_name: str = ""     # LR-side override; falls back to driver_name
    lr_driver_mobile: str = ""   # LR-side override; falls back to driver_mobile
    invoice_id: Optional[str] = None
    status: Literal["pending", "invoiced", "archived_historical"] = "pending"
    notes: str = ""
    # LR / invoice reference fields
    lr_number: str = ""
    lr_time: str = ""
    consignor_name: str = ""
    consignor_address: str = ""
    consignee_site_location: str = ""
    consignee_site_contact: str = ""
    external_invoice_no: str = ""
    customer_invoice_no: str = ""
    customer_purchased_at: str = ""
    invoice_value: float = 0.0
    waybill_no: str = ""
    gross_weight: float = 0.0
    tare_weight: float = 0.0
    seal_numbers: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    # Iter89 · Phase 1 — POLICY SNAPSHOT (frozen at trip create time).
    # These fields are the source-of-truth for THIS trip's freight/shortage math.
    # Future edits to Customer/Product/Supplier masters MUST NOT change these.
    applied_freight_method: str = ""             # per_ton_loading | per_ton_unloading | per_ton_higher_of | fixed
    # Iter99 · Phase 4 — Per-Field Override Audit Trail. Each entry captures
    # the system-computed value vs the final approved value + who/when/why.
    field_overrides: List["FieldOverride"] = Field(default_factory=list)
    # Iter133 · Turn 2A — Canonical Expense bridge XOR flag.
    # False = legacy Trip.expenses / other_expenditures scalars are the cost
    # source for this trip (reports sum them). True = canonical Expense rows
    # linked by trip_id are the cost source (reports read from Expense).
    # NEVER additive — exactly ONE side per trip. Set atomically by
    # services.sync_trip_expenses_to_canonical() at trip write time.
    has_canonical_expenses: bool = False
    # Iter97 · Phase 2 — Trip-level freight override (authorised users only).
    # When > 0, wins over the method-derived calc. Audit captured by PUT /trips.
    freight_amount_override: float = 0.0
    freight_override_reason: str = ""
    freight_override_by: str = ""
    freight_override_at: str = ""
    freight_qty_used: float = 0.0                 # billable qty derived per method (for display)
    applied_product_shortage_pct: float = 0.0    # from product.default_shortage_allowance_pct
    applied_customer_shortage_limit: float = 0.0
    applied_customer_shortage_limit_type: str = ""   # pct | kg
    applied_customer_shortage_method: str = ""       # net_shortage | full_after_limit
    applied_supplier_shortage_limit_kg: float = 0.0
    policy_snapshot_at: str = ""                 # ISO ts when snapshot was taken
    # Iter86 · Historical Isolation Layer
    imported_from: str = ""
    imported_ref: str = ""
    imported_batch: str = ""
    is_historical: bool = False

class Product(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prd_"))
    name: str
    hsn_sac: str = "996791"
    default_rate: float = 0.0
    unit: str = "MT"
    # Iter89 · Phase 1 — default shortage allowance % per product (0-100).
    # Frozen onto trip.applied_product_shortage_pct at CREATE time.
    default_shortage_allowance_pct: float = 0.0
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Party(BaseModel):
    """Consignor / Consignee address book (both types share one shape).
    Used to select loading (consignor) and unloading (consignee) parties on a trip
    when they differ from the billed customer."""
    id: str = Field(default_factory=lambda: new_id("party_"))
    party_type: Literal["consignor", "consignee", "both"] = "both"
    name: str
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    gstin: str = ""
    pan: str = ""
    address: str = ""
    state: str = ""
    pincode: str = ""
    linked_customer_id: Optional[str] = None  # optional linkage to a customer
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Vehicle(BaseModel):
    id: str = Field(default_factory=lambda: new_id("veh_"))
    vehicle_number: str
    vehicle_type: Literal["own", "supplier"] = "own"
    is_active: bool = True                                # Iter63 · Vehicle Active/Inactive status
    owner_name: str = ""
    owner_phone: str = ""
    supplier_id: str = ""              # Iter47 Phase 3: FK to Suppliers master
    supplier_name: str = ""
    supplier_contact_person: str = ""
    supplier_mobile: str = ""
    supplier_state: str = ""
    supplier_gstin: str = ""
    make_model: str = ""
    capacity_tons: float = 0.0
    rc_expiry: str = ""
    fc_expiry: str = ""
    insurance_expiry: str = ""
    permit_expiry: str = ""
    puc_expiry: str = ""
    remarks: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    # Iter86 · Historical Isolation Layer
    imported_from: str = ""
    imported_ref: str = ""
    imported_batch: str = ""
    is_historical: bool = False

class MaintenanceLog(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mnt_"))
    vehicle_id: Optional[str] = None
    vehicle_number: str
    date: str
    type: Literal["Tyre", "Service", "Repair", "Other"] = "Service"
    description: str = ""
    cost: float = 0.0
    odometer: float = 0.0
    next_due_date: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Fuel(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fuel_"))
    date: str  # ISO date
    vehicle_id: Optional[str] = None
    vehicle_number: str
    litres: float
    rate_per_litre: float
    amount: float = 0.0
    odometer: float = 0.0
    station_name: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Payment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pay_"))
    amount: float
    date: str
    mode: str = "Cash"
    note: str = ""

class Invoice(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inv_"))
    company_id: str = ""
    invoice_number: str
    fy_string: str = ""                      # Iter134 · FY snapshot ("26-27") — immutable once issued
    customer_id: str
    invoice_date: str
    trip_ids: List[str]
    subtotal: float
    hsn_sac: str = "996791"  # 996511 or 996791 — chosen at invoice creation
    freight_total: float = 0.0
    halting_total: float = 0.0
    excess_total: float = 0.0
    shortage_total: float = 0.0
    diesel_deduction_total: float = 0.0
    advance_deduction_total: float = 0.0
    gst_type: Literal["cgst_sgst", "igst"] = "cgst_sgst"
    cgst_rate: float = 2.5
    sgst_rate: float = 2.5
    igst_rate: float = 5.0
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    total_tax: float = 0.0
    gross_total: float = 0.0
    round_off: float = 0.0
    total_amount: float = 0.0
    rcm: bool = True  # Reverse charge — tax not collected
    payments: List[Payment] = []
    amount_paid: float = 0.0
    balance_due: float = 0.0
    share_token: Optional[str] = None
    notes: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    # Iter86 · Historical Isolation Layer
    imported_from: str = ""
    imported_ref: str = ""
    imported_batch: str = ""
    is_historical: bool = False

# Simple RBAC: role -> permissions
ROLE_PERMISSIONS = {
    "owner": {"edit_trip", "delete_trip", "edit_invoice", "delete_invoice", "edit_master", "delete_master", "manage_users",
              # Iter132a additive — CN/DN permissions. Existing keys untouched.
              "create_note", "issue_note", "cancel_note", "edit_note_settings"},
    "accountant": {"edit_trip", "edit_invoice", "edit_master",
                   "create_note", "issue_note"},
    "viewer": set(),
}


# ==================== Iter132a · Credit Note / Debit Note ====================

class CDNLine(BaseModel):
    """One line inside a Credit/Debit Note. Same shape as an invoice line
    but semantically an adjustment against the linked invoice."""
    id: str = Field(default_factory=lambda: new_id("cdnl_"))
    description: str
    hsn_sac: str = "996791"
    trip_id: Optional[str] = None   # optional link to a specific trip for drilldown
    quantity: float = 1.0
    rate: float
    taxable_value: float            # quantity * rate, rounded 2dp

class CreditDebitNote(BaseModel):
    """Iter132a · Credit Note (kind='credit'). Debit Note (kind='debit')
    ships in Iter132b — the schema already carries the kind field so no
    migration is needed at that time. Always positive amounts; the kind
    field determines sign in aggregations."""
    id: str = Field(default_factory=lambda: new_id("cdn_"))
    kind: Literal["credit", "debit"] = "credit"
    company_id: str
    note_number: str = ""               # assigned at issue time
    note_date: str                      # ISO date; ≥ invoice_date and ≤ today
    invoice_id: str                     # exactly one linked invoice
    invoice_number_snapshot: str = ""   # cached for reporting/PDF stability
    customer_id: str = ""
    reason_code: Literal[
        "rate_correction", "short_delivery", "quality_claim",
        "post_invoice_discount", "under_charge", "missed_halting",
        "freight_escalation", "sales_return", "other"
    ]
    reason_text: str                    # free text, min 8 chars (validated in router)
    lines: List[CDNLine]

    subtotal: float = 0.0
    gst_type: Literal["cgst_sgst", "igst"] = "cgst_sgst"
    cgst_rate: float = 2.5
    sgst_rate: float = 2.5
    igst_rate: float = 5.0
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    total_tax: float = 0.0
    total_amount: float = 0.0
    round_off: float = 0.0
    rcm: bool = True                    # inherited from invoice
    # Iter132c C2b · GST treatment. Default True → inherit invoice tax as
    # before (statutorily-conservative). When False, taxes are zeroed and the
    # PDF renders a prominent "GST NOT APPLIED" badge. Note that all statutory
    # validators (deadline, over-credit, note-date) still apply regardless.
    apply_gst: bool = True

    status: Literal["draft", "issued", "cancelled"] = "draft"
    cancelled_at: Optional[str] = None
    cancelled_by: Optional[str] = None
    cancelled_reason: Optional[str] = None

    # Approval trail
    created_by: str = ""
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    deadline_override: bool = False     # true when issued past 30-Nov statutory cutoff

    share_token: Optional[str] = None

    # Iter86-parity: historical isolation
    is_historical: bool = False

    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


class CDNLineCreate(BaseModel):
    description: str
    hsn_sac: str = "996791"
    trip_id: Optional[str] = None
    quantity: float = 1.0
    rate: float


class CDNCreateRequest(BaseModel):
    invoice_id: str
    note_date: Optional[str] = None     # defaults to today at server
    reason_code: Literal[
        "rate_correction", "short_delivery", "quality_claim",
        "post_invoice_discount", "under_charge", "missed_halting",
        "freight_escalation", "sales_return", "other"
    ]
    reason_text: str
    lines: List[CDNLineCreate]
    deadline_override_reason: Optional[str] = None  # required when past 30-Nov
    # Iter132c C2b · optional GST treatment override. Default True → inherit
    # tax from invoice. False → zero-tax note; PDF renders "GST NOT APPLIED".
    apply_gst: Optional[bool] = True


class CDNCancelRequest(BaseModel):
    reason: str


# ============================================================================

class TeamMember(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tm_"))
    owner_user_id: str          # the owner's user_id
    email: str
    name: str = ""
    role: Literal["owner", "accountant", "viewer"] = "accountant"
    active: bool = True
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


# ==================== Request DTOs ====================

class InvoiceCreateRequest(BaseModel):
    customer_id: str
    trip_ids: List[str]
    invoice_date: Optional[str] = None
    hsn_sac: str = "996791"  # 996511 or 996791
    gst_type: Literal["cgst_sgst", "igst"] = "cgst_sgst"
    rcm: bool = True
    notes: str = ""
    # Iter134 · Invoice Number UI correction — optional Owner-only override at
    # create time.  If set, must match ^[A-Za-z0-9/_\-]+$ and be unique per
    # tenant. Reason is required (≥ 10 chars) when this differs from the
    # server-suggested number.
    invoice_number: Optional[str] = None
    invoice_number_reason: str = ""


class InvoiceUpdateRequest(BaseModel):
    invoice_date: Optional[str] = None
    gst_type: Optional[Literal["cgst_sgst", "igst"]] = None
    rcm: Optional[bool] = None
    notes: Optional[str] = None
    reason: str = ""


class InvoiceNumberOverrideRequest(BaseModel):
    """Iter134 · Owner-only controlled override of an issued invoice number.
    Uniqueness is enforced server-side via the (user_id, invoice_number)
    unique index. Reason is mandatory (≥ 10 chars) and audit-logged.
    Does NOT touch fy_string — that remains the immutable numbering FY."""
    new_number: str
    reason: str


class PaymentAdd(BaseModel):
    amount: float
    date: Optional[str] = None
    mode: str = "Cash"
    note: str = ""


class FileRef(BaseModel):
    id: str = Field(default_factory=lambda: new_id("file_"))
    storage_path: str
    original_filename: str
    content_type: str
    size: int
    category: str = "general"           # logo | vehicle_doc | fuel_bill | lr_proof | trip_attachment | general
    linked_type: str = ""               # vehicle | trip | fuel | invoice | ""
    linked_id: str = ""
    is_deleted: bool = False
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


class AuditLog(BaseModel):
    id: str = Field(default_factory=lambda: new_id("audit_"))
    timestamp: str = Field(default_factory=lambda: now_utc().isoformat())
    module: str                  # trip | invoice | customer | vehicle | driver | product | company | payment
    action: str                  # create | update | delete
    entity_id: str = ""
    entity_ref: str = ""         # user-friendly name (invoice_number, vehicle_number, etc.)
    reason: str = ""
    changes: dict = Field(default_factory=dict)   # {field: {old, new}}
    user_email: str = ""
    user_name: str = ""


# ==================== Trip Template ====================

class TripTemplate(BaseModel):
    """Company-shared reusable trip template.

    Stores the recurring parts of a trip so an operator can populate a Trip Sheet
    with a single click and only edit variable fields (vehicle, driver, date, tons).
    """
    id: str = Field(default_factory=lambda: new_id("tpl_"))
    name: str                                          # e.g. "IOCL Vizag → Medak — Bitumen VG 30"
    customer_id: str = ""
    from_location: str = ""
    to_location: str = ""
    load_details: str = ""                             # material / product free text
    product_type: str = ""                             # VG-30 / VG-40 / CRMB / PMB / Emulsion …
    round_trip_kms: float = 0.0
    freight_mode: Literal["per_ton", "fixed"] = "per_ton"
    rate_per_ton: float = 0.0
    rate_per_km_per_ton: float = 0.0
    fixed_amount: float = 0.0
    hsn_sac: str = "996791"
    gst_type: Literal["cgst_sgst", "igst", "rcm"] = "cgst_sgst"
    halting_rate_per_day: float = 0.0
    remarks: str = ""                                  # default notes / remarks
    is_active: bool = True
    created_by: str = ""                               # user_id of creator (audit)
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


class ChatSession(BaseModel):
    """A single conversation thread with the AI business assistant (per company)."""
    id: str = Field(default_factory=lambda: new_id("chat_"))
    title: str = "New chat"
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


# ============================================================================
# Iter45 — Supplier Master + Supplier Payments (dedicated Suppliers module)
# ============================================================================

class SupplierProductShortageLimit(BaseModel):
    """Iter90 — Per-product shortage KG threshold for a supplier.

    Example: Bitumen → 100 KG, Emulsion → 100 KG, CRMB → 150 KG.
    Rule (unchanged from Iter89): if trip shortage ≤ limit → 0 deduction;
    if trip shortage > limit → FULL actual shortage is deductible.
    """
    product_id: str
    product_name: str = ""      # denormalised for display; product_id is source of truth
    limit_kg: float = 0.0



class Supplier(BaseModel):
    """Supplier / hired-vehicle owner master. Company-scoped."""
    id: str = Field(default_factory=lambda: new_id("sup_"))
    name: str
    contact_person: str = ""
    mobile: str = ""
    alt_mobile: str = ""
    address: str = ""
    state: str = ""
    city: str = ""
    gst_in: str = ""
    pan: str = ""
    msme_number: str = ""
    bank_name: str = ""
    account_number: str = ""
    ifsc: str = ""
    branch: str = ""
    payment_terms: str = ""              # free text (e.g. "Net 15 days", "Advance 40%")
    opening_balance: float = 0.0         # positive amount
    opening_balance_type: Literal["payable", "advance"] = "payable"
    remarks: str = ""
    is_active: bool = True
    # Iter89 · Phase 1 — Supplier-specific fixed-KG shortage threshold.
    # Rule: shortage ≤ limit → 0 deduction. shortage > limit → FULL actual shortage.
    # (Deliberately different from Customer shortage config.)
    # Iter90 — Product-wise limits. `product_shortage_limits` is the source of
    # truth; `shortage_limit_kg` is retained as a legacy default fallback for
    # any product NOT listed in `product_shortage_limits`. Existing trips keep
    # their frozen `applied_supplier_shortage_limit_kg` snapshot (no impact).
    shortage_limit_kg: float = 0.0
    product_shortage_limits: List[SupplierProductShortageLimit] = Field(default_factory=list)
    # Audit
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    # Iter86 · Historical Isolation Layer
    imported_from: str = ""
    imported_ref: str = ""
    imported_batch: str = ""
    is_historical: bool = False


class SupplierPayment(BaseModel):
    """A payment (or receipt) transaction against a supplier's ledger.
    All supplier trip transactions (freight, advance, diesel, cust.diesel adj,
    shortage/excess, other recovery/income) are DERIVED from trips at ledger
    read-time — never duplicated here. This document tracks only the actual
    money movements between us and the supplier."""
    id: str = Field(default_factory=lambda: new_id("sp_"))
    supplier_id: str
    date: str                              # ISO YYYY-MM-DD
    amount: float                          # always positive; direction inferred from `type`
    type: Literal["payment_out", "receipt_in"] = "payment_out"  # our-cash-out vs our-cash-in
    mode: Literal["Cash", "Bank", "UPI", "IMPS", "NEFT", "RTGS", "Cheque", "Other"] = "Bank"
    account_id: str = ""                   # optional link to a bank account master
    ref_no: str = ""
    against: Literal["advance", "trip", "outstanding", "other"] = "outstanding"
    trip_id: str = ""                      # optional link
    lr_number: str = ""                    # optional link
    remarks: str = ""
    # Audit
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    is_deleted: bool = False
    deleted_by: str = ""
    deleted_at: str = ""
    deletion_reason: str = ""
    # Iter86 · Historical Isolation Layer
    imported_from: str = ""
    imported_ref: str = ""
    imported_batch: str = ""
    is_historical: bool = False


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg_"))
    session_id: str
    role: Literal["user", "assistant", "system"] = "user"
    content: str = ""
    tool_calls: list = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


# ============================================================================
# Iter133 · Expense / Vehicle Cost Management — Turn 1 Foundation
# ----------------------------------------------------------------------------
# Party architecture (FROZEN — see /app/memory/PRD.md Iter133 section):
#   * Supplier  — hired-vehicle owner (existing, untouched)
#   * Vendor    — spare-parts / workshop parts vendor (new)
#   * Mechanic  — labour / service provider (new)
# Roles (FROZEN):
#   * RepairEvent          — operational envelope; NEVER stores monetary total
#   * VendorBill / MechWO  — payable + bill/service evidence + document anchor
#   * Expense              — canonical authoritative cost transaction
#   * *Payment             — cash movement only; NEVER creates an Expense
# Master principle: ENTER ONCE → CALCULATE ONCE → REFLECT EVERYWHERE.
# ============================================================================

class Vendor(BaseModel):
    """Iter133 · Spare-parts / workshop vendor master (Turn 1). Company-scoped.
    Distinct identity from Supplier (hired-vehicle owner) and Mechanic (labour)."""
    id: str = Field(default_factory=lambda: new_id("ven_"))
    name: str
    contact_person: str = ""
    mobile: str = ""
    alt_mobile: str = ""
    address: str = ""
    state: str = ""
    city: str = ""
    gst_in: str = ""
    pan: str = ""
    msme_number: str = ""
    bank_name: str = ""
    account_number: str = ""
    ifsc: str = ""
    branch: str = ""
    payment_terms: str = ""
    opening_balance: float = 0.0
    opening_balance_type: Literal["payable", "advance"] = "payable"
    remarks: str = ""
    is_active: bool = True
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    deactivated_by: str = ""
    deactivated_at: str = ""
    deactivation_reason: str = ""
    imported_from: str = ""
    imported_ref: str = ""
    imported_batch: str = ""
    is_historical: bool = False


class Mechanic(BaseModel):
    """Iter133 · Labour / service mechanic master (Turn 1). Company-scoped.
    Distinct from Vendor (parts) and Supplier (hired vehicle)."""
    id: str = Field(default_factory=lambda: new_id("mec_"))
    name: str
    contact_person: str = ""
    mobile: str = ""
    alt_mobile: str = ""
    address: str = ""
    state: str = ""
    city: str = ""
    gst_in: str = ""
    pan: str = ""
    skill: str = ""
    payment_terms: str = ""
    opening_balance: float = 0.0
    opening_balance_type: Literal["payable", "advance"] = "payable"
    remarks: str = ""
    is_active: bool = True
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    deactivated_by: str = ""
    deactivated_at: str = ""
    deactivation_reason: str = ""
    is_historical: bool = False


class RepairEvent(BaseModel):
    """Iter133 · Repair operational envelope (Turn 1).

    CRITICAL: this model has NO monetary total field. Vehicle Repair Cost is
    always DERIVED from the linked Expense rows. `extra='forbid'` guarantees
    a client cannot smuggle a `total_cost` into the payload.
    """
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: new_id("rev_"))
    event_date: str
    vehicle_id: str = ""
    vehicle_number: str = ""
    trip_id: str = ""
    odometer: float = 0.0
    workshop_name: str = ""
    description: str = ""
    status: Literal["open", "closed"] = "open"
    remarks: str = ""
    file_ids: List[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    is_deleted: bool = False
    deleted_by: str = ""
    deleted_at: str = ""
    deletion_reason: str = ""


class VendorBill(BaseModel):
    """Iter133 · Spare-parts vendor payable + bill document (Turn 1).

    Turn-1 hard constraint (frozen): 1 VendorBill → at most 1 vehicle_id.
    Multi-vehicle allocation is P1 · DEFERRED.
    """
    id: str = Field(default_factory=lambda: new_id("vbl_"))
    vendor_id: str
    vendor_name: str = ""
    bill_number: str = ""
    bill_date: str
    bill_amount: float
    vehicle_id: str = ""
    vehicle_number: str = ""
    trip_id: str = ""
    repair_event_id: str = ""
    narration: str = ""
    remarks: str = ""
    file_ids: List[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    is_deleted: bool = False
    deleted_by: str = ""
    deleted_at: str = ""
    deletion_reason: str = ""


class MechanicWorkOrder(BaseModel):
    """Iter133 · Mechanic labour payable + service evidence (Turn 1)."""
    id: str = Field(default_factory=lambda: new_id("mwo_"))
    mechanic_id: str
    mechanic_name: str = ""
    work_date: str
    amount: float
    hours_worked: float = 0.0
    vehicle_id: str = ""
    vehicle_number: str = ""
    trip_id: str = ""
    repair_event_id: str = ""
    narration: str = ""
    remarks: str = ""
    file_ids: List[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    is_deleted: bool = False
    deleted_by: str = ""
    deleted_at: str = ""
    deletion_reason: str = ""


class Expense(BaseModel):
    """Iter133 · Canonical authoritative cost transaction (Turn 1).

    ONE real-world cost = ONE Expense row. Trip Cost, Vehicle Cost, and
    Expense Register are PROJECTIONS of this row. Never sum this alongside
    its twin VendorBill/MechanicWorkOrder in a report — the future report
    source map (see PRD Iter133) is exclusive:
      Vehicle/Trip/Expense-Register  ← reads Expense ONLY.
      Vendor/Mechanic Ledger         ← reads Bill/WO + Payment ONLY.
    """
    id: str = Field(default_factory=lambda: new_id("exp_"))
    date: str
    category: str
    subcategory: str = ""
    amount: float
    narration: str = ""
    remarks: str = ""
    vehicle_id: str = ""
    vehicle_number: str = ""
    trip_id: str = ""
    repair_event_id: str = ""
    party_type: Literal["vendor", "mechanic", "supplier", "driver", "cash", "none"] = "cash"
    party_id: str = ""
    party_name: str = ""
    vendor_bill_id: str = ""
    mechanic_work_order_id: str = ""
    supplier_owned_vehicle: bool = False
    supplier_settlement_mode: Literal[
        "supplier_settlement_adjustment", "company_borne", "n/a"
    ] = "n/a"
    settlement_mode: Literal["cash_now", "payable"] = "payable"
    reversal_of: str = ""
    is_reversed: bool = False
    # Iter133 · Turn 2A — Source-line identity for idempotent materialisation
    # from legacy Trip.expenses / other_expenditures. `source_key` is a
    # namespaced deterministic string; ONE canonical Expense per source_key.
    #   trip:{trip_id}:legacy:{field}   for Trip.expenses.*
    #   trip:{trip_id}:oe:{row_id}      for Trip.other_expenditures[]
    # Never uses amount/date/vendor heuristics. `source_type='manual'` means
    # user-typed via the Expense API (no auto-materialisation).
    source_type: Literal["manual", "trip_legacy", "trip_other_expenditure"] = "manual"
    source_key: str = ""
    source_trip_id: str = ""    # denormalised for fast cleanup queries
    file_ids: List[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    is_deleted: bool = False
    deleted_by: str = ""
    deleted_at: str = ""
    deletion_reason: str = ""
    is_historical: bool = False


class VendorPayment(BaseModel):
    """Iter133 · Minimal cash-movement record against a Vendor (Turn 1).

    Mirrors SupplierPayment shape. NEVER creates or modifies an Expense
    (payment ≠ cost). Turn 1 ships schema + basic CRUD only — no ledger UI,
    no paid/outstanding report, no reconciliation.
    """
    id: str = Field(default_factory=lambda: new_id("vpay_"))
    vendor_id: str
    date: str
    amount: float
    type: Literal["payment_out", "receipt_in"] = "payment_out"
    mode: Literal["Cash", "Bank", "UPI", "IMPS", "NEFT", "RTGS", "Cheque", "Other"] = "Bank"
    account_id: str = ""
    ref_no: str = ""
    against: Literal["bill", "advance", "outstanding", "other"] = "outstanding"
    vendor_bill_id: str = ""
    remarks: str = ""
    file_ids: List[str] = Field(default_factory=list)
    # Iter133 · Turn 2C — correction / reversal support (append-only audit).
    corrected_at: str = ""
    corrected_by: str = ""
    correction_count: int = 0
    latest_correction_id: str = ""
    is_reversed: bool = False
    reversed_by: str = ""
    reversed_at: str = ""
    reversal_reason: str = ""
    reversal_of: str = ""            # id of the payment being reversed
    reconciled_at: str = ""
    reconciled_ref: str = ""
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    is_deleted: bool = False
    deleted_by: str = ""
    deleted_at: str = ""
    deletion_reason: str = ""


class MechanicPayment(BaseModel):
    """Iter133 · Minimal cash-movement record against a Mechanic (Turn 1)."""
    id: str = Field(default_factory=lambda: new_id("mpay_"))
    mechanic_id: str
    date: str
    amount: float
    type: Literal["payment_out", "receipt_in"] = "payment_out"
    mode: Literal["Cash", "Bank", "UPI", "IMPS", "NEFT", "RTGS", "Cheque", "Other"] = "Bank"
    account_id: str = ""
    ref_no: str = ""
    against: Literal["work_order", "advance", "outstanding", "other"] = "outstanding"
    mechanic_work_order_id: str = ""
    remarks: str = ""
    file_ids: List[str] = Field(default_factory=list)
    # Iter133 · Turn 2C — correction / reversal support.
    corrected_at: str = ""
    corrected_by: str = ""
    correction_count: int = 0
    latest_correction_id: str = ""
    is_reversed: bool = False
    reversed_by: str = ""
    reversed_at: str = ""
    reversal_reason: str = ""
    reversal_of: str = ""
    reconciled_at: str = ""
    reconciled_ref: str = ""
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    is_deleted: bool = False
    deleted_by: str = ""
    deleted_at: str = ""
    deletion_reason: str = ""


class PaymentCorrection(BaseModel):
    """Iter133 · Turn 2C · Immutable audit row for a Vendor/Mechanic Payment
    correction. Append-only. Never edited or deleted."""
    id: str = Field(default_factory=lambda: new_id("pcr_"))
    payment_type: Literal["vendor", "mechanic"]
    payment_id: str
    correction_index: int
    kind: Literal["attribute", "amount_reversal_new"] = "attribute"
    correction_reason: str
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    diff: dict = Field(default_factory=dict)
    linked_reversal_id: str = ""     # for amount_reversal_new: id of reversed original
    linked_new_id: str = ""          # for amount_reversal_new: id of freshly created row
    force_reconciled_override: bool = False
    corrected_by: str = ""
    corrected_at: str = Field(default_factory=lambda: now_utc().isoformat())
