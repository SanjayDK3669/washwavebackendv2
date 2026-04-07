from fastapi import APIRouter, HTTPException, Depends
from database import orders_col, users_col
from models.schemas import OrderCreate, PaymentVerify, StatusUpdate
from utils.jwt_handler import require_customer, require_admin
from bson import ObjectId
from datetime import datetime
import random, string

router = APIRouter()

SERVICE_PRICES = {"washing": 10, "dry_cleaning": 30, "ironing": 8, "full_laundry": 25}
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

# ── ADMIN routes FIRST (before wildcard) ──────────────────────────────────────

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

@router.put("/admin/verify-payment")
async def admin_verify_payment(data: PaymentVerify, user=Depends(require_admin)):
    """Admin approves or rejects the UPI transaction ID submitted by customer."""
    now = datetime.utcnow()
    if data.approved:
        new_status     = "confirmed"
        payment_status = "paid"
        note = data.note or "Payment verified by admin"
    else:
        new_status     = "payment_pending"
        payment_status = "pending"
        note = data.note or "Transaction ID rejected — please re-submit correct ID"

    await orders_col.update_one(
        {"_id": ObjectId(data.order_id)},
        {"$set": {"status": new_status, "payment_status": payment_status, "updated_at": now},
         "$push": {"status_history": {"status": new_status, "note": note, "time": now.isoformat()}}}
    )
    return clean(await orders_col.find_one({"_id": ObjectId(data.order_id)}))

# ── CUSTOMER routes ────────────────────────────────────────────────────────────

@router.post("/")
async def create_order(data: OrderCreate, user=Depends(require_customer)):
    for _ in range(5):
        num = gen_num()
        if not await orders_col.find_one({"order_number": num}): break

    now = datetime.utcnow()
    is_cash = data.payment_method.value == "cash"

    if data.order_type == "subscription":
        plan = SUBSCRIPTION_PLANS.get(data.subscription_plan.value if data.subscription_plan else "basic")
        if not plan: raise HTTPException(400, "Invalid subscription plan")
        amount = plan["price"]; clothes_count = plan["clothes"]
        service_items = []; services = []
    else:
        if not data.service_items: raise HTTPException(400, "Select at least one service")
        items         = [{"service": si.service.value, "count": si.count} for si in data.service_items]
        amount        = calc_ondemand(items)
        clothes_count = sum(si.count for si in data.service_items)
        service_items = items
        services      = list({si.service.value for si in data.service_items})

    # Cash orders go straight to confirmed; UPI/card orders need admin review
    if is_cash:
        init_status     = "confirmed"
        payment_status  = "cash_on_pickup"
        init_note       = "Order confirmed. Payment to be collected on pickup."
    else:
        init_status     = "payment_review"
        payment_status  = "pending"
        init_note       = f"Payment submitted via {data.payment_method.value.replace('_',' ')}. Transaction ref: {data.upi_ref or 'N/A'}. Awaiting admin verification."

    # Auto-save address for customer
    if data.pickup_address and data.pincode:
        cust = await users_col.find_one({"_id": ObjectId(user["user_id"])})
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
        "payment_method":    data.payment_method.value,
        "upi_ref":           data.upi_ref or "",
        "status":            init_status,
        "payment_status":    payment_status,
        "status_history":    [{"status": init_status, "note": init_note, "time": now.isoformat()}],
        "created_at":        now,
        "updated_at":        now,
    }
    res = await orders_col.insert_one(order)
    return clean(await orders_col.find_one({"_id": res.inserted_id}))

@router.get("/my-orders")
async def my_orders(user=Depends(require_customer)):
    return [clean(o) async for o in
            orders_col.find({"customer_id": user["user_id"]}).sort("created_at", -1)]

# wildcard LAST
@router.get("/track/{order_number}")
async def track(order_number: str, user=Depends(require_customer)):
    o = await orders_col.find_one({"order_number": order_number.upper(), "customer_id": user["user_id"]})
    if not o: raise HTTPException(404, "Order not found")
    return clean(o)