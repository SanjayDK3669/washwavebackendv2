from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

class ServiceType(str, Enum):
    washing      = "washing"
    dry_cleaning = "dry_cleaning"
    ironing      = "ironing"
    full_laundry = "full_laundry"

class OrderStatus(str, Enum):
    payment_pending    = "payment_pending"
    payment_review     = "payment_review"   # admin reviewing txn id
    confirmed          = "confirmed"
    picked_up          = "picked_up"
    in_progress        = "in_progress"
    ready              = "ready"
    out_for_delivery   = "out_for_delivery"
    delivered          = "delivered"
    cancelled          = "cancelled"

class SubscriptionPlan(str, Enum):
    basic    = "basic"
    standard = "standard"

class PaymentMethod(str, Enum):
    phone_pay  = "phone_pay"
    qr_code    = "qr_code"
    upi        = "upi"
    cash       = "cash"

# ── Auth ──────────────────────────────────────────────────────────────────────
class CustomerRegister(BaseModel):
    name: str
    phone: str
    password: str
    address: Optional[str] = ""
    pincode: Optional[str] = ""

class LoginRequest(BaseModel):
    phone: str
    password: str
    role: str = "customer"

class SavedAddress(BaseModel):
    address: str
    pincode: str

# ── Order ─────────────────────────────────────────────────────────────────────
class ServiceItem(BaseModel):
    service: ServiceType
    count: int = Field(ge=1)

class OrderCreate(BaseModel):
    order_type: str = "ondemand"
    subscription_plan: Optional[SubscriptionPlan] = None
    service_items: Optional[List[ServiceItem]] = None
    notes: Optional[str] = ""
    pickup_address: str
    pincode: str
    pickup_date: str   # "2024-04-10"
    pickup_time: str   # "08:00 AM"
    payment_method: PaymentMethod
    upi_ref: Optional[str] = ""   # transaction id (empty for cash)

class PaymentVerify(BaseModel):
    order_id: str
    approved: bool
    note: Optional[str] = ""

# ── Admin ─────────────────────────────────────────────────────────────────────
class StatusUpdate(BaseModel):
    order_id: str
    status: OrderStatus
    note: Optional[str] = ""