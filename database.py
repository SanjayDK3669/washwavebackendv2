from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
load_dotenv()

MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb+srv://dksanjay39_db_user:BWlWv924ORKhYLyt@cluster0.kaqlohf.mongodb.net/?appName=Cluster0"
)
DB_NAME = "washwave"

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# Collections
users_col    = db["users"]     # customers + admin
orders_col   = db["orders"]    # all orders
payments_col = db["payments"]  # payment records

async def create_indexes():
    await users_col.create_index([("phone", 1), ("role", 1)], unique=True)
    await orders_col.create_index("customer_id")
    await orders_col.create_index("order_number", unique=True)
    await orders_col.create_index("status")
