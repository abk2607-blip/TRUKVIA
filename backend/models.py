"""All Pydantic domain models."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Literal, Any
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
    lr_prefix: str = "LR"
    next_lr_number: int = 1
    logo: str = ""  # data URL (base64)
    udyam_registration: str = ""  # MSME / Udyam Registration No. — appears in Invoice T&C
    is_default: bool = False

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
    "Cleaning", "Others",
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
    supplier_shortage_deduction: float = 0.0         # Shortage deducted from supplier freight
    supplier_shortage_deduction_override: bool = False  # Iter74 — True when user manually edited; blocks auto-mirror from trip.shortage_amount
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
    "owner": {"edit_trip", "delete_trip", "edit_invoice", "delete_invoice", "edit_master", "delete_master", "manage_users"},
    "accountant": {"edit_trip", "edit_invoice", "edit_master"},
    "viewer": set(),
}

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


class InvoiceUpdateRequest(BaseModel):
    invoice_date: Optional[str] = None
    gst_type: Optional[Literal["cgst_sgst", "igst"]] = None
    rcm: Optional[bool] = None
    notes: Optional[str] = None
    reason: str = ""


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
    shortage_limit_kg: float = 0.0
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
