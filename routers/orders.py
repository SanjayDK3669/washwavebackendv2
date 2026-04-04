from fastapi import APIRouter, HTTPException, Depends
from database import orders_col, users_col
from models.schemas import OrderCreate, PaymentConfirm, StatusUpdate
from utils.jwt_handler import require_customer, require_admin
from bson import ObjectId
from datetime import datetime
import random, string, hmac, hashlib, os

router = APIRouter()

RAZORPAY_KEY_ID     = os.getenv("RAZORPAY_KEY_ID",     "rzp_test_YourKeyHere")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "YourSecretHere")

SERVICE_PRICES = {
    "washing":      10,
    "dry_cleaning": 30,
    "ironing":       8,
    "full_laundry": 25,
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

def verify_sig(order_id, payment_id, signature):
    msg      = f"{order_id}|{payment_id}"
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

# ── ADMIN routes FIRST ────────────────────────────────────────────────────────

@router.get("/admin/stats")
async def admin_stats(user=Depends(require_admin)):
    total     = await orders_col.count_documents({})
    paid      = await orders_col.count_documents({"payment_status": "paid"})
    pending   = await orders_col.count_documents({"status": "payment_pending"})
    active    = await orders_col.count_documents({"status": {"$in": ["confirmed","picked_up","in_progress","ready","out_for_delivery"]}})
    delivered = await orders_col.count_documents({"status": "delivered"})
    subs      = await orders_col.count_documents({"order_type": "subscription"})
    rev       = [r async for r in orders_col.aggregate([
        {"$match": {"payment_status": "paid"}},
        {"$group": {"_id": None, "t": {"$sum": "$amount"}}}
    ])]
    return {"total": total, "paid": paid, "pending": pending, "active": active,
            "delivered": delivered, "subscriptions": subs,
            "revenue": rev[0]["t"] if rev else 0}

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
    if res.matched_count == 0:
        raise HTTPException(404, "Order not found")
    return clean(await orders_col.find_one({"_id": ObjectId(data.order_id)}))

# ── CUSTOMER routes ───────────────────────────────────────────────────────────

@router.post("/")
async def create_order(data: OrderCreate, user=Depends(require_customer)):
    for _ in range(5):
        num = gen_num()
        if not await orders_col.find_one({"order_number": num}):
            break

    now = datetime.utcnow()

    if data.order_type == "subscription":
        plan = SUBSCRIPTION_PLANS.get(data.subscription_plan.value if data.subscription_plan else "basic")
        if not plan:
            raise HTTPException(400, "Invalid subscription plan")
        amount        = plan["price"]
        clothes_count = plan["clothes"]
        service_items = []
        services      = []
    else:
        if not data.service_items:
            raise HTTPException(400, "Select at least one service")
        items         = [{"service": si.service.value, "count": si.count} for si in data.service_items]
        amount        = calc_ondemand(items)
        clothes_count = sum(si.count for si in data.service_items)
        service_items = items
        services      = list({si.service.value for si in data.service_items})

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
        "delivery_date":     data.delivery_date,
        "delivery_time":     data.delivery_time,
        "amount":            amount,
        "status":            "payment_pending",
        "payment_status":    "pending",
        "razorpay_order_id":   None,
        "razorpay_payment_id": None,
        "status_history":    [{"status": "payment_pending",
                               "note": "Order placed, awaiting payment",
                               "time": now.isoformat()}],
        "created_at": now,
        "updated_at": now,
    }
    res = await orders_col.insert_one(order)
    return clean(await orders_col.find_one({"_id": res.inserted_id}))

@router.post("/razorpay/create")
async def razorpay_create_order(order_id: str, user=Depends(require_customer)):
    import razorpay
    order = await orders_col.find_one({"_id": ObjectId(order_id), "customer_id": user["user_id"]})
    if not order:
        raise HTTPException(404, "Order not found")
    if order["payment_status"] == "paid":
        raise HTTPException(400, "Already paid")

    client    = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    rzp_order = client.order.create({
        "amount":   order["amount"] * 100,
        "currency": "INR",
        "receipt":  order["order_number"],
        "notes":    {"ww_order_id": str(order["_id"])}
    })

    await orders_col.update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"razorpay_order_id": rzp_order["id"]}}
    )
    return {
        "razorpay_order_id": rzp_order["id"],
        "amount":            order["amount"] * 100,
        "currency":          "INR",
        "key_id":            RAZORPAY_KEY_ID,
        "order_number":      order["order_number"],
        "customer_name":     "",
        "customer_phone":    "",
    }

@router.post("/razorpay/verify")
async def razorpay_verify(data: PaymentConfirm, user=Depends(require_customer)):
    order = await orders_col.find_one({
        "razorpay_order_id": data.razorpay_order_id,
        "customer_id":       user["user_id"]
    })
    if not order:
        raise HTTPException(404, "Order not found")
    if order["payment_status"] == "paid":
        raise HTTPException(400, "Already paid")
    if not verify_sig(data.razorpay_order_id, data.razorpay_payment_id, data.razorpay_signature):
        raise HTTPException(400, "Payment verification failed — invalid signature")

    now = datetime.utcnow()
    await orders_col.update_one(
        {"_id": order["_id"]},
        {"$set": {"payment_status": "paid", "status": "confirmed",
                  "razorpay_payment_id": data.razorpay_payment_id, "updated_at": now},
         "$push": {"status_history": {"status": "confirmed",
                   "note": f"Payment verified. Razorpay ID: {data.razorpay_payment_id}",
                   "time": now.isoformat()}}}
    )
    return clean(await orders_col.find_one({"_id": order["_id"]}))

@router.get("/my-orders")
async def my_orders(user=Depends(require_customer)):
    return [clean(o) async for o in
            orders_col.find({"customer_id": user["user_id"]}).sort("created_at", -1)]

# ── MUST be last — wildcard ───────────────────────────────────────────────────
@router.get("/track/{order_number}")
async def track(order_number: str, user=Depends(require_customer)):
    o = await orders_col.find_one({
        "order_number": order_number.upper(),
        "customer_id":  user["user_id"]
    })
    if not o:
        raise HTTPException(404, "Order not found")
    return clean(o)