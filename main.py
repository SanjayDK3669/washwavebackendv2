from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers import auth, orders
from database import create_indexes
import uvicorn, os

app = FastAPI(title="WashWave API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await create_indexes()

app.include_router(auth.router,   prefix="/api/auth",   tags=["Auth"])
app.include_router(orders.router, prefix="/api/orders", tags=["Orders"])

# Serve images folder (QR code etc.)
images_dir = os.path.join(os.path.dirname(__file__), "images")
os.makedirs(images_dir, exist_ok=True)
app.mount("/images", StaticFiles(directory=images_dir), name="images")

@app.get("/")
def root():
    return {"message": "WashWave API v2 running"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)