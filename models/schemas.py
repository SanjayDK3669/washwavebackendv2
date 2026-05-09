from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

class ServiceType(str, Enum):
    washing_iron  = "washing_iron"   # Washing + Iron  — ₹45
    ironing       = "ironing"        # Only Iron       — ₹30
    dry_wash_iron = "dry_wash_iron"  # Dry Wash + Iron — ₹90
    bed_sheet     = "bed_sheet"      # Bed Sheet/Spread — ₹55

class OrderStatus(str, Enum):
    payment_pending    = "payment_pending"
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
    phone_pay = "phone_pay"
    gpay      = "gpay"
    upi       = "upi"
    cash      = "cash"

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
    upi_ref: Optional[str] = ""   # unused for online; kept for cash fallback

class RazorpayVerify(BaseModel):
    razorpay_order_id:  str
    razorpay_payment_id: str
    razorpay_signature:  str
    order_data: OrderCreate   # full order details to persist after verification

# ── Admin ─────────────────────────────────────────────────────────────────────
class StatusUpdate(BaseModel):
    order_id: str
    status: OrderStatus
    note: Optional[str] = ""