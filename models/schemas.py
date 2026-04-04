from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

class ServiceType(str, Enum):
    washing      = "washing"
    dry_cleaning = "dry_cleaning"
    ironing      = "ironing"
    full_laundry = "full_laundry"

class OrderStatus(str, Enum):
    payment_pending  = "payment_pending"
    confirmed        = "confirmed"
    picked_up        = "picked_up"
    in_progress      = "in_progress"
    ready            = "ready"
    out_for_delivery = "out_for_delivery"
    delivered        = "delivered"
    cancelled        = "cancelled"

class SubscriptionPlan(str, Enum):
    basic    = "basic"    # 10 clothes Rs 349
    standard = "standard" # 20 clothes Rs 649

# Auth
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

class ServiceItem(BaseModel):
    service: ServiceType
    count: int = Field(ge=1)

class OrderCreate(BaseModel):
    order_type: str = "ondemand"           # "ondemand" | "subscription"
    subscription_plan: Optional[SubscriptionPlan] = None
    service_items: Optional[List[ServiceItem]] = None
    notes: Optional[str] = ""
    pickup_address: str
    pincode: str
    pickup_date: str    # "2024-04-10"
    pickup_time: str    # "10:00 AM"
    delivery_date: str  # "2024-04-12"
    delivery_time: str  # "06:00 PM"

class PaymentConfirm(BaseModel):
    order_id: str
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str

class StatusUpdate(BaseModel):
    order_id: str
    status: OrderStatus
    note: Optional[str] = ""