"""
Database Schemas for Beauty & Wellness Growth OS

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
These models are used for validation on create/read endpoints and for the
Flames DB viewer via the /schema endpoint.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime

# Core accounts ---------------------------------------------------------------

class Salon(BaseModel):
    name: str = Field(..., description="Salon/Brand name")
    phone: str = Field(..., description="Primary business phone (E.164 or local)")
    city: Optional[str] = Field(None, description="City name")
    address: Optional[str] = Field(None, description="Street address")
    country: str = Field("IN", description="Country code (ISO2)")
    plan: Literal["trial", "starter", "pro", "enterprise"] = Field(
        "trial", description="Current subscription plan"
    )
    onboarding_done: bool = Field(False, description="Whether onboarding is complete")

class User(BaseModel):
    role: Literal["owner", "manager", "staff"] = Field("owner", description="Role in the salon")
    name: str
    email: Optional[EmailStr] = None
    phone: str
    salon_id: Optional[str] = Field(None, description="Reference to salon _id as string")
    is_active: bool = True

# CRM ------------------------------------------------------------------------

class Client(BaseModel):
    salon_id: str
    name: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    tags: List[str] = []
    notes: Optional[str] = None
    last_visit: Optional[datetime] = None
    source: Optional[str] = Field(None, description="Acquisition source (walk-in, Instagram, etc.)")

class Service(BaseModel):
    salon_id: str
    name: str
    category: Optional[str] = None
    duration_min: int = Field(..., ge=5, le=600)
    price: float = Field(..., ge=0)

# Bookings -------------------------------------------------------------------

class Booking(BaseModel):
    salon_id: str
    client_id: Optional[str] = None
    services: List[str] = Field(default_factory=list, description="List of service names or ids")
    staff_id: Optional[str] = None
    start_time: datetime
    end_time: datetime
    status: Literal["pending", "confirmed", "completed", "cancelled", "no_show"] = "pending"
    notes: Optional[str] = None
    amount: float = 0.0
    payment_status: Literal["unpaid", "paid", "partial", "refunded"] = "unpaid"

# Inventory ------------------------------------------------------------------

class InventoryItem(BaseModel):
    salon_id: str
    sku: Optional[str] = None
    name: str
    brand: Optional[str] = None
    quantity: float = 0
    unit: Literal["pcs", "ml", "g"] = "pcs"
    low_stock_threshold: Optional[float] = 0
    cost_price: Optional[float] = 0
    sale_price: Optional[float] = 0

# Payroll --------------------------------------------------------------------

class Staff(BaseModel):
    salon_id: str
    name: str
    phone: Optional[str] = None
    role: Optional[str] = None
    commission_pct: Optional[float] = Field(0, ge=0, le=100)

class PayrollEntry(BaseModel):
    salon_id: str
    staff_id: str
    month: str = Field(..., description="YYYY-MM")
    base_salary: float = 0
    commissions: float = 0
    bonuses: float = 0
    deductions: float = 0
    payout_status: Literal["pending", "processing", "paid"] = "pending"

# Billing / Subscriptions -----------------------------------------------------

class Subscription(BaseModel):
    salon_id: str
    plan: Literal["trial", "starter", "pro", "enterprise"] = "trial"
    status: Literal["trial", "active", "past_due", "canceled"] = "trial"
    start_date: datetime
    end_date: Optional[datetime] = None
    mrr: float = 0

class Transaction(BaseModel):
    salon_id: str
    amount: float
    currency: Literal["INR"] = "INR"
    purpose: Literal["subscription", "addon", "pos"] = "subscription"
    status: Literal["pending", "succeeded", "failed", "refunded"] = "succeeded"
    timestamp: datetime

# Auth / OTP -----------------------------------------------------------------

class OTP(BaseModel):
    phone: str
    code: str
    expires_at: datetime
    used: bool = False

class VerificationToken(BaseModel):
    phone: str
    token: str
    expires_at: datetime

class Session(BaseModel):
    user_id: str
    salon_id: Optional[str] = None
    token: str
    expires_at: datetime

# Analytics snapshot ----------------------------------------------------------

class AnalyticsSnapshot(BaseModel):
    salon_id: Optional[str] = None
    period: Literal["7d", "30d", "90d", "mtd"] = "30d"
    total_revenue: float = 0
    total_bookings: int = 0
    new_clients: int = 0
    returning_clients: int = 0
