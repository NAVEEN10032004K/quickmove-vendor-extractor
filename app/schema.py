from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

MessageType = Literal["quote", "confirmation", "delay", "cancellation", "availability", "status", "other"]
VendorCategory = Literal["property", "logistics", "utility", "govt_bank", "other"]
Confidence = Literal["high", "medium", "low"]


class Amount(BaseModel):
    value: float
    currency: str = "INR"
    notes: Optional[str] = None


class DateItem(BaseModel):
    what: str
    when: str  # YYYY-MM-DD when possible, else raw text


class Contact(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class VendorRecord(BaseModel):
    message_type: MessageType = "other"
    vendor_name: Optional[str] = None
    vendor_category: VendorCategory = "other"
    amount: Optional[Amount] = None
    dates: list[DateItem] = Field(default_factory=list)
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    contact: Optional[Contact] = None
    red_flags: list[str] = Field(default_factory=list)
    customer_reference: Optional[str] = None
    action_needed: str = ""  # filled by Claude after extraction
    confidence: Confidence = "low"
    notes: Optional[str] = None

    @field_validator("dates", "inclusions", "exclusions", "red_flags", mode="before")
    @classmethod
    def _null_list(cls, v):  # LLMs often return null instead of []
        return [] if v is None else v
