from fastapi import APIRouter, HTTPException, Depends
from database import users_col
from models.schemas import CustomerRegister, LoginRequest
from utils.jwt_handler import create_token, get_current_user
from bson import ObjectId
from datetime import datetime
import bcrypt, os

router = APIRouter()

ADMIN_PHONE    = os.getenv("ADMIN_PHONE", "9999999999")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin@washwave2025")

def hp(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def vp(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def clean(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("password", None)
    return doc

# ── Customer register ─────────────────────────────────
@router.post("/register")
async def register(data: CustomerRegister):
    if await users_col.find_one({"phone": data.phone.strip(), "role": "customer"}):
        raise HTTPException(400, "Phone number already registered")
    doc = {
        "role": "customer",
        "name": data.name.strip(),
        "phone": data.phone.strip(),
        "password": hp(data.password),
        "address": data.address or "",
        "pincode": data.pincode or "",
        "created_at": datetime.utcnow(),
    }
    res = await users_col.insert_one(doc)
    user = await users_col.find_one({"_id": res.inserted_id})
    return {"token": create_token(str(res.inserted_id), "customer"), "user": clean(user)}

# ── Login (customer + admin) ──────────────────────────
@router.post("/login")
async def login(data: LoginRequest):
    role = data.role.strip().lower()

    if role == "admin":
        if data.phone.strip() != ADMIN_PHONE:
            raise HTTPException(401, "Invalid admin credentials")
        if data.password != ADMIN_PASSWORD:
            raise HTTPException(401, "Invalid admin credentials")
        admin_doc = {"id": "admin-001", "name": "Admin", "role": "admin", "phone": ADMIN_PHONE}
        return {"token": create_token("admin-001", "admin"), "user": admin_doc}

    user = await users_col.find_one({"phone": data.phone.strip(), "role": "customer"})
    if not user:
        raise HTTPException(401, "Phone number not found")
    if not vp(data.password, user["password"]):
        raise HTTPException(401, "Incorrect password")
    return {"token": create_token(str(user["_id"]), "customer"), "user": clean(user)}

# ── Me ────────────────────────────────────────────────
@router.get("/me")
async def me(current=Depends(get_current_user)):
    if current["role"] == "admin":
        return {"id": "admin-001", "name": "Admin", "role": "admin"}
    user = await users_col.find_one({"_id": ObjectId(current["user_id"])})
    if not user:
        raise HTTPException(404, "User not found")
    return clean(user)
