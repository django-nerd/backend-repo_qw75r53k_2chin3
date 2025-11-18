import os
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, create_document, get_documents
from schemas import (
    Salon,
    User,
    Client,
    Service,
    Booking,
    InventoryItem,
    Staff,
    PayrollEntry,
    Subscription,
    Transaction,
    OTP,
    VerificationToken,
    Session,
    AnalyticsSnapshot,
)

# FastAPI app -----------------------------------------------------------------
app = FastAPI(title="Beauty & Wellness Growth OS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utilities -------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _oid_str(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Mongo ObjectId/datetime to string/iso for JSON responses."""
    if not isinstance(doc, dict):
        return doc
    out: Dict[str, Any] = {}
    for k, v in doc.items():
        try:
            from bson import ObjectId  # type: ignore
        except Exception:
            ObjectId = None  # type: ignore
        if ObjectId and isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# Health & schema --------------------------------------------------------------

@app.get("/")
def read_root():
    return {"message": "Backend running", "time": _now().isoformat()}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "Unknown"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:20]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:60]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:60]}"

    return response


# Simple schema exposure for DB viewer
class SchemaInfo(BaseModel):
    name: str
    fields: List[str]


@app.get("/schema", response_model=List[SchemaInfo])
def get_schema_definitions():
    models = [
        Salon,
        User,
        Client,
        Service,
        Booking,
        InventoryItem,
        Staff,
        PayrollEntry,
        Subscription,
        Transaction,
        OTP,
        VerificationToken,
        Session,
        AnalyticsSnapshot,
    ]
    result = []
    for m in models:
        fields = list(m.model_fields.keys())
        result.append(SchemaInfo(name=m.__name__.lower(), fields=fields))
    return result


# Auth & Onboarding ------------------------------------------------------------

class OTPStartRequest(BaseModel):
    phone: str


class OTPStartResponse(BaseModel):
    phone: str
    expires_at: datetime
    # For demo, also return code. In production, send via SMS and do not return.
    code: str


@app.post("/auth/otp/start", response_model=OTPStartResponse)
def start_otp(req: OTPStartRequest):
    code = "".join(random.choices(string.digits, k=6))
    payload = OTP(phone=req.phone, code=code, expires_at=_now() + timedelta(minutes=5), used=False)
    create_document("otp", payload)
    return OTPStartResponse(phone=req.phone, expires_at=payload.expires_at, code=code)


class OTPVerifyRequest(BaseModel):
    phone: str
    code: str


class OTPVerifyResponse(BaseModel):
    token: str
    expires_at: datetime


@app.post("/auth/otp/verify", response_model=OTPVerifyResponse)
def verify_otp(req: OTPVerifyRequest):
    otp_doc = db["otp"].find_one({"phone": req.phone, "code": req.code, "used": False})
    if not otp_doc:
        raise HTTPException(status_code=400, detail="Invalid code")
    if otp_doc.get("expires_at") and otp_doc["expires_at"] < _now():
        raise HTTPException(status_code=400, detail="Code expired")
    db["otp"].update_one({"_id": otp_doc["_id"]}, {"$set": {"used": True}})

    token = "ver_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))
    vt = VerificationToken(phone=req.phone, token=token, expires_at=_now() + timedelta(minutes=15))
    create_document("verificationtoken", vt)
    return OTPVerifyResponse(token=token, expires_at=vt.expires_at)


class OnboardingRequest(BaseModel):
    verification_token: str
    salon_name: str
    city: Optional[str] = None
    address: Optional[str] = None
    owner_name: str
    owner_email: Optional[str] = None


class OnboardingResponse(BaseModel):
    salon_id: str
    user_id: str
    session_token: str
    plan: str


@app.post("/onboarding/complete", response_model=OnboardingResponse)
def complete_onboarding(req: OnboardingRequest):
    vt = db["verificationtoken"].find_one({"token": req.verification_token})
    if not vt or (vt.get("expires_at") and vt["expires_at"] < _now()):
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    # Create salon
    salon = Salon(name=req.salon_name, phone=vt["phone"], city=req.city, address=req.address, plan="trial", onboarding_done=True)
    salon_id = create_document("salon", salon)

    # Create owner user
    user = User(role="owner", name=req.owner_name, email=req.owner_email, phone=vt["phone"], salon_id=salon_id, is_active=True)
    user_id = create_document("user", user)

    # Create trial subscription (14 days)
    sub = Subscription(salon_id=salon_id, plan="trial", status="trial", start_date=_now(), end_date=_now() + timedelta(days=14), mrr=0)
    create_document("subscription", sub)

    # Create a simple session token
    session_token = "sess_" + "".join(random.choices(string.ascii_letters + string.digits, k=32))
    sess = Session(user_id=user_id, salon_id=salon_id, token=session_token, expires_at=_now() + timedelta(days=7))
    create_document("session", sess)

    return OnboardingResponse(salon_id=salon_id, user_id=user_id, session_token=session_token, plan="trial")


# CRM ------------------------------------------------------------------------

class ClientCreate(BaseModel):
    salon_id: str
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    tags: Optional[List[str]] = []
    notes: Optional[str] = None


@app.post("/crm/clients")
def create_client(body: ClientCreate):
    cid = create_document("client", Client(**body.model_dump()))
    return {"id": cid}


@app.get("/crm/clients")
def list_clients(salon_id: str = Query(...)):
    docs = get_documents("client", {"salon_id": salon_id})
    return [_oid_str(d) for d in docs]


# Services --------------------------------------------------------------------

class ServiceCreate(BaseModel):
    salon_id: str
    name: str
    category: Optional[str] = None
    duration_min: int
    price: float


@app.post("/services")
def create_service(body: ServiceCreate):
    sid = create_document("service", Service(**body.model_dump()))
    return {"id": sid}


@app.get("/services")
def list_services(salon_id: str = Query(...)):
    docs = get_documents("service", {"salon_id": salon_id})
    return [_oid_str(d) for d in docs]


# Bookings --------------------------------------------------------------------

class BookingCreate(BaseModel):
    salon_id: str
    client_id: Optional[str] = None
    services: List[str] = []
    staff_id: Optional[str] = None
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = None


@app.post("/bookings")
def create_booking(body: BookingCreate):
    booking = Booking(**{**body.model_dump(), "status": "confirmed", "payment_status": "unpaid", "amount": 0.0})
    bid = create_document("booking", booking)
    return {"id": bid}


@app.get("/bookings")
def list_bookings(salon_id: str = Query(...), status: Optional[str] = None):
    q: Dict[str, Any] = {"salon_id": salon_id}
    if status:
        q["status"] = status
    docs = get_documents("booking", q)
    return [_oid_str(d) for d in docs]


# Inventory -------------------------------------------------------------------

class InventoryCreate(BaseModel):
    salon_id: str
    name: str
    sku: Optional[str] = None
    brand: Optional[str] = None
    quantity: float = 0
    unit: str = "pcs"
    low_stock_threshold: Optional[float] = 0
    cost_price: Optional[float] = 0
    sale_price: Optional[float] = 0


@app.post("/inventory")
def create_inventory_item(body: InventoryCreate):
    iid = create_document("inventoryitem", InventoryItem(**body.model_dump()))
    return {"id": iid}


@app.get("/inventory")
def list_inventory(salon_id: str = Query(...)):
    docs = get_documents("inventoryitem", {"salon_id": salon_id})
    return [_oid_str(d) for d in docs]


# Staff & Payroll -------------------------------------------------------------

class StaffCreate(BaseModel):
    salon_id: str
    name: str
    phone: Optional[str] = None
    role: Optional[str] = None
    commission_pct: Optional[float] = 0


@app.post("/staff")
def create_staff(body: StaffCreate):
    sid = create_document("staff", Staff(**body.model_dump()))
    return {"id": sid}


@app.get("/staff")
def list_staff(salon_id: str = Query(...)):
    docs = get_documents("staff", {"salon_id": salon_id})
    return [_oid_str(d) for d in docs]


class PayrollCreate(BaseModel):
    salon_id: str
    staff_id: str
    month: str
    base_salary: float = 0
    commissions: float = 0
    bonuses: float = 0
    deductions: float = 0


@app.post("/payroll")
def create_payroll(body: PayrollCreate):
    pid = create_document("payrollentry", PayrollEntry(**body.model_dump()))
    return {"id": pid}


@app.get("/payroll")
def list_payroll(salon_id: str = Query(...), month: Optional[str] = None):
    q: Dict[str, Any] = {"salon_id": salon_id}
    if month:
        q["month"] = month
    docs = get_documents("payrollentry", q)
    return [_oid_str(d) for d in docs]


# Billing / Transactions ------------------------------------------------------

class TransactionCreate(BaseModel):
    salon_id: str
    amount: float
    purpose: str = "subscription"
    status: str = "succeeded"


@app.post("/billing/transactions")
def create_transaction(body: TransactionCreate):
    tx = Transaction(salon_id=body.salon_id, amount=body.amount, purpose=body.purpose, status=body.status, timestamp=_now())
    tid = create_document("transaction", tx)
    return {"id": tid}


@app.get("/billing/transactions")
def list_transactions(salon_id: str = Query(...)):
    docs = get_documents("transaction", {"salon_id": salon_id})
    return [_oid_str(d) for d in docs]


# Analytics -------------------------------------------------------------------

@app.get("/analytics/summary")
def analytics_summary(salon_id: Optional[str] = None, period: str = Query("30d", pattern="^(7d|30d|90d|mtd)$")):
    now = _now()
    if period == "mtd":
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    else:
        days = int(period.replace("d", ""))
        start = now - timedelta(days=days)

    match = {"timestamp": {"$gte": start}}
    if salon_id:
        match["salon_id"] = salon_id

    # Revenue from transactions
    revenue = 0.0
    for t in db["transaction"].find(match):
        if t.get("status") == "succeeded":
            revenue += float(t.get("amount", 0))

    # Bookings
    b_match = {"created_at": {"$gte": start}}
    if salon_id:
        b_match["salon_id"] = salon_id
    total_bookings = db["booking"].count_documents(b_match)

    # Clients
    c_match = {"created_at": {"$gte": start}}
    if salon_id:
        c_match["salon_id"] = salon_id
    new_clients = db["client"].count_documents(c_match)

    # Returning clients approx: clients with >1 booking in window
    returning_clients = 0
    pipeline = [
        {"$match": {"start_time": {"$gte": start}, **({"salon_id": salon_id} if salon_id else {})}},
        {"$group": {"_id": "$client_id", "cnt": {"$sum": 1}}},
        {"$match": {"cnt": {"$gt": 1}}},
        {"$count": "rc"},
    ]
    try:
        agg = list(db["booking"].aggregate(pipeline))
        if agg:
            returning_clients = agg[0].get("rc", 0)
    except Exception:
        returning_clients = 0

    return {
        "period": period,
        "total_revenue": revenue,
        "total_bookings": int(total_bookings),
        "new_clients": int(new_clients),
        "returning_clients": int(returning_clients),
    }


# Admin dashboard --------------------------------------------------------------

@app.get("/admin/metrics")
def admin_metrics():
    total_salons = db["salon"].count_documents({})
    active_paid = db["subscription"].count_documents({"status": {"$in": ["active", "past_due"]}})
    on_trial = db["subscription"].count_documents({"status": "trial"})

    # MRR from active subscriptions
    mrr = 0.0
    for s in db["subscription"].find({"status": {"$in": ["active", "past_due"]}}):
        mrr += float(s.get("mrr", 0))

    # Last 30d revenue
    last30 = _now() - timedelta(days=30)
    revenue_30d = 0.0
    for t in db["transaction"].find({"timestamp": {"$gte": last30}, "status": "succeeded"}):
        revenue_30d += float(t.get("amount", 0))

    # Daily actives proxy = salons with any booking in last 24h
    last1d = _now() - timedelta(days=1)
    salon_ids = db["booking"].distinct("salon_id", {"created_at": {"$gte": last1d}})
    daily_active_salons = len(salon_ids)

    return {
        "total_salons": int(total_salons),
        "active_paid_salons": int(active_paid),
        "trial_salons": int(on_trial),
        "mrr": mrr,
        "arr": mrr * 12,
        "revenue_30d": revenue_30d,
        "daily_active_salons": daily_active_salons,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
