from fastapi import APIRouter, HTTPException, Depends
from database import orders_col, users_col
from models.schemas import OrderCreate, StatusUpdate, RazorpayVerify
from utils.jwt_handler import require_customer, require_admin
from bson import ObjectId
from datetime import datetime
import random, string, razorpay, os, hmac, hashlib

router = APIRouter()

RAZORPAY_KEY_ID     = os.getenv("RAZORPAY_KEY_ID", "rzp_test_XXXXXXXXXXXXXXXX")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "your_razorpay_secret")

rzp_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

SERVICE_PRICES = {
    "washing_iron":  45,   # Washing + Iron per item
    "ironing":       30,   # Only Iron per item
    "dry_wash_iron": 90,   # Dry Wash + Iron per item
    "bed_sheet":     55,   # Bed Sheet / Bed Spread per piece
}
SUBSCRIPTION_PLANS = {
    "basic":    {"clothes": 10, "price": 349, "label": "Basic — 10 clothes"},
    "standard": {"clothes": 20, "price": 649, "label": "Standard — 20 clothes"},
}

def gen_num():
    return "WW" + "".join(random.choices(string.digits, k=6))

def clean(doc):
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc

def calc_ondemand(items):
    return sum(SERVICE_PRICES.get(i["service"], 10) * i["count"] for i in items)


# ── ADMIN routes ───────────────────────────────────────────────────────────────

@router.get("/admin/stats")
async def admin_stats(user=Depends(require_admin)):
    total     = await orders_col.count_documents({})
    review    = await orders_col.count_documents({"status": "payment_review"})
    pending   = await orders_col.count_documents({"status": "payment_pending"})
    active    = await orders_col.count_documents({"status": {"$in": ["confirmed","picked_up","in_progress","ready","out_for_delivery"]}})
    delivered = await orders_col.count_documents({"status": "delivered"})
    subs      = await orders_col.count_documents({"order_type": "subscription"})
    rev = [r async for r in orders_col.aggregate([
        {"$match": {"payment_status": "paid"}},
        {"$group": {"_id": None, "t": {"$sum": "$amount"}}}
    ])]
    return {"total": total, "pending": pending, "payment_review": review,
            "active": active, "delivered": delivered,
            "subscriptions": subs, "revenue": rev[0]["t"] if rev else 0}

@router.get("/admin/all")
async def admin_all(user=Depends(require_admin)):
    result = []
    async for o in orders_col.find().sort("created_at", -1):
        o = clean(o)
        try:
            cust = await users_col.find_one({"_id": ObjectId(o["customer_id"])})
            o["customer_name"]  = cust.get("name",  "—") if cust else "—"
            o["customer_phone"] = cust.get("phone", "—") if cust else "—"
        except:
            o["customer_name"] = "—"; o["customer_phone"] = "—"
        result.append(o)
    return result

@router.put("/admin/status")
async def admin_status(data: StatusUpdate, user=Depends(require_admin)):
    now = datetime.utcnow()
    res = await orders_col.update_one(
        {"_id": ObjectId(data.order_id)},
        {"$set": {"status": data.status.value, "updated_at": now},
         "$push": {"status_history": {"status": data.status.value,
                   "note": data.note or "", "time": now.isoformat()}}}
    )
    if res.matched_count == 0: raise HTTPException(404, "Order not found")
    return clean(await orders_col.find_one({"_id": ObjectId(data.order_id)}))


# ── RAZORPAY routes ────────────────────────────────────────────────────────────

@router.post("/create-payment")
async def create_razorpay_order(data: OrderCreate, user=Depends(require_customer)):
    """
    Step 1: Calculate amount, create Razorpay order, return rzp_order_id + key.
    The frontend uses this to open Razorpay checkout (which opens GPay / PhonePe).
    Only called for UPI/online payments — cash goes straight to create_order.
    """
    if data.order_type == "subscription":
        plan = SUBSCRIPTION_PLANS.get(data.subscription_plan.value if data.subscription_plan else "basic")
        if not plan: raise HTTPException(400, "Invalid subscription plan")
        amount = plan["price"]
    else:
        if not data.service_items: raise HTTPException(400, "Select at least one service")
        items  = [{"service": si.service.value, "count": si.count} for si in data.service_items]
        amount = calc_ondemand(items)

    # Razorpay amount is in paise (multiply by 100)
    rzp_order = rzp_client.order.create({
        "amount":   amount * 100,
        "currency": "INR",
        "receipt":  gen_num(),
        "notes":    {"customer_id": user["user_id"]}
    })

    return {
        "razorpay_order_id": rzp_order["id"],
        "amount":            amount,
        "currency":          "INR",
        "key_id":            RAZORPAY_KEY_ID,
    }


@router.post("/verify-payment")
async def verify_and_create_order(data: RazorpayVerify, user=Depends(require_customer)):
    """
    Step 2: Verify Razorpay signature, then persist the order as confirmed + paid.
    """
    # Signature verification
    expected = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        f"{data.razorpay_order_id}|{data.razorpay_payment_id}".encode(),
        hashlib.sha256
    ).hexdigest()

    if expected != data.razorpay_signature:
        raise HTTPException(400, "Payment verification failed — invalid signature")

    # Build order document
    for _ in range(5):
        num = gen_num()
        if not await orders_col.find_one({"order_number": num}): break

    now = datetime.utcnow()
    order_data = data.order_data

    if order_data.order_type == "subscription":
        plan          = SUBSCRIPTION_PLANS.get(order_data.subscription_plan.value if order_data.subscription_plan else "basic")
        amount        = plan["price"]
        clothes_count = plan["clothes"]
        service_items = []
        services      = []
    else:
        items         = [{"service": si.service.value, "count": si.count} for si in order_data.service_items]
        amount        = calc_ondemand(items)
        clothes_count = sum(si.count for si in order_data.service_items)
        service_items = items
        services      = list({si.service.value for si in order_data.service_items})

    # Auto-save address
    if order_data.pickup_address and order_data.pincode:
        cust  = await users_col.find_one({"_id": ObjectId(user["user_id"])})
        saved = cust.get("saved_addresses", []) if cust else []
        exists = any(s["address"] == order_data.pickup_address and s["pincode"] == order_data.pincode for s in saved)
        if not exists:
            await users_col.update_one({"_id": ObjectId(user["user_id"])}, {
                "$push": {"saved_addresses": {"address": order_data.pickup_address, "pincode": order_data.pincode}}
            })

    order = {
        "order_number":         num,
        "customer_id":          user["user_id"],
        "order_type":           order_data.order_type,
        "subscription_plan":    order_data.subscription_plan.value if order_data.subscription_plan else None,
        "service_items":        service_items,
        "services":             services,
        "clothes_count":        clothes_count,
        "notes":                order_data.notes or "",
        "pickup_address":       order_data.pickup_address,
        "pincode":              order_data.pincode,
        "pickup_date":          order_data.pickup_date,
        "pickup_time":          order_data.pickup_time,
        "amount":               amount,
        "payment_method":       order_data.payment_method.value,
        "razorpay_order_id":    data.razorpay_order_id,
        "razorpay_payment_id":  data.razorpay_payment_id,
        "upi_ref":              data.razorpay_payment_id,
        "status":               "confirmed",
        "payment_status":       "paid",
        "status_history": [{
            "status": "confirmed",
            "note":   f"Payment successful via {order_data.payment_method.value.replace('_', ' ')}. Razorpay ID: {data.razorpay_payment_id}",
            "time":   now.isoformat()
        }],
        "created_at": now,
        "updated_at": now,
    }

    res = await orders_col.insert_one(order)
    return clean(await orders_col.find_one({"_id": res.inserted_id}))


# ── CUSTOMER routes ────────────────────────────────────────────────────────────

@router.post("/")
async def create_order(data: OrderCreate, user=Depends(require_customer)):
    """Cash orders only — online payments go through /create-payment + /verify-payment."""
    if data.payment_method.value != "cash":
        raise HTTPException(400, "Use /create-payment for online payments")

    for _ in range(5):
        num = gen_num()
        if not await orders_col.find_one({"order_number": num}): break

    now = datetime.utcnow()

    if data.order_type == "subscription":
        plan          = SUBSCRIPTION_PLANS.get(data.subscription_plan.value if data.subscription_plan else "basic")
        if not plan:  raise HTTPException(400, "Invalid subscription plan")
        amount        = plan["price"]
        clothes_count = plan["clothes"]
        service_items = []
        services      = []
    else:
        if not data.service_items: raise HTTPException(400, "Select at least one service")
        items         = [{"service": si.service.value, "count": si.count} for si in data.service_items]
        amount        = calc_ondemand(items)
        clothes_count = sum(si.count for si in data.service_items)
        service_items = items
        services      = list({si.service.value for si in data.service_items})

    if data.pickup_address and data.pincode:
        cust  = await users_col.find_one({"_id": ObjectId(user["user_id"])})
        saved = cust.get("saved_addresses", []) if cust else []
        exists = any(s["address"] == data.pickup_address and s["pincode"] == data.pincode for s in saved)
        if not exists:
            await users_col.update_one({"_id": ObjectId(user["user_id"])}, {
                "$push": {"saved_addresses": {"address": data.pickup_address, "pincode": data.pincode}}
            })

    order = {
        "order_number":      num,
        "customer_id":       user["user_id"],
        "order_type":        data.order_type,
        "subscription_plan": data.subscription_plan.value if data.subscription_plan else None,
        "service_items":     service_items,
        "services":          services,
        "clothes_count":     clothes_count,
        "notes":             data.notes or "",
        "pickup_address":    data.pickup_address,
        "pincode":           data.pincode,
        "pickup_date":       data.pickup_date,
        "pickup_time":       data.pickup_time,
        "amount":            amount,
        "payment_method":    "cash",
        "upi_ref":           "",
        "status":            "confirmed",
        "payment_status":    "cash_on_pickup",
        "status_history": [{
            "status": "confirmed",
            "note":   "Order confirmed. Payment to be collected on pickup.",
            "time":   now.isoformat()
        }],
        "created_at": now,
        "updated_at": now,
    }
    res = await orders_col.insert_one(order)
    return clean(await orders_col.find_one({"_id": res.inserted_id}))


@router.get("/my-orders")
async def my_orders(user=Depends(require_customer)):
    return [clean(o) async for o in
            orders_col.find({"customer_id": user["user_id"]}).sort("created_at", -1)]

@router.get("/track/{order_number}")
async def track(order_number: str, user=Depends(require_customer)):
    o = await orders_col.find_one({"order_number": order_number.upper(), "customer_id": user["user_id"]})
    if not o: raise HTTPException(404, "Order not found")
    return clean(o)