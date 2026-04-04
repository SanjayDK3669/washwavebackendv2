from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from enum import Enum

class ServiceType(str, Enum):
    washing      = "washing"
    dry_cleaning = "dry_cleaning"
    ironing      = "ironing"
    full_laundry = "full_laundry"

class OrderStatus(str, Enum):
    payment_pending = "payment_pending"
    confirmed       = "confirmed"
    picked_up       = "picked_up"
    in_progress     = "in_progress"
    ready           = "ready"
    delivered       = "delivered"
    cancelled       = "cancelled"

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

# Order — per-service cloth counts
class ServiceItem(BaseModel):
    service: ServiceType
    count: int = Field(ge=1)

class OrderCreate(BaseModel):
    service_items: List[ServiceItem]
    notes: Optional[str] = ""
    pickup_address: str
    pincode: str

class PaymentConfirm(BaseModel):
    order_id: str
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str

# Admin
class StatusUpdate(BaseModel):
    order_id: str
    status: OrderStatus
    note: Optional[str] = ""