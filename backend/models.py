"""All Pydantic domain models."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


def now_utc():
    return datetime.now(timezone.utc)


def new_id(prefix: str = ""):
    return f"{prefix}{uuid.uuid4().hex[:16]}"


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
    opening_balance: float = 0.0
    advance_balance: float = 0.0     # surplus payments; carried on the customer
    notes: str = ""
    reminder_enabled: bool = True
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())

class Expenses(BaseModel):
    model_config = ConfigDict(extra="allow")
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

class Trip(BaseModel):
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
    status: Literal["pending", "invoiced"] = "pending"
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

class Product(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prd_"))
    name: str
    hsn_sac: str = "996791"
    default_rate: float = 0.0
    unit: str = "MT"
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
    owner_name: str = ""
    owner_phone: str = ""
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


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg_"))
    session_id: str
    role: Literal["user", "assistant", "system"] = "user"
    content: str = ""
    tool_calls: list = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
