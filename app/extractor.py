import re

from app import claude_client, jev_client
from app.prompts import JEV_FLAGS, JEV_QUESTIONS
from app.schema import VendorRecord

FLAG_THRESHOLD = 0.85  # Jev noul probability needed to raise a flag (0.5 was too noisy in testing)

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_HINTS = {
    "amounts": r"(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?(?:\s?(?:k|L|lakh)\b)?|\b\d+(?:\.\d+)?\s?(?:k|L|lakh)\b",
    "phones": r"(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}",
    "emails": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "dates": rf"\b\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{2,4}}\b|\b\d{{1,2}}\s{_MONTH}\b",
}


def regex_hints(message: str) -> dict:
    return {k: re.findall(p, message, re.I) for k, p in _HINTS.items()}


def _confidence(c: float) -> str:
    return "high" if c >= 0.8 else "medium" if c >= 0.5 else "low"


def extract_with_jev(message: str) -> dict:
    """Jev: enums, confidence and red flags. Claude: free-text fields (Jev can't return strings)."""
    jev = jev_client.t(message, JEV_QUESTIONS)
    fields = claude_client.fill_text_fields(message, regex_hints(message))
    quote_only = {"no_gst", "low_price"}  # Jev fires these on listings/notices too
    flags = [txt for k, (_, txt) in JEV_FLAGS.items()
             if jev[k] >= FLAG_THRESHOLD and (k not in quote_only or jev["message_type"] == "quote")]
    merged = {f.lower(): f for f in reversed(flags + (fields.get("red_flags") or []))}  # case-insensitive dedupe
    fields["red_flags"] = list(reversed(merged.values()))
    return {
        **fields,
        "message_type": jev["message_type"],
        "vendor_category": jev["vendor_category"],
        "confidence": _confidence(min(jev["message_type_confidence"], jev["vendor_category_confidence"])),
    }


def extract(message: str | None, image_bytes: bytes | None) -> VendorRecord:
    if image_bytes:
        record = VendorRecord(**claude_client.extract_with_claude_vision(message, image_bytes))
    else:
        record = VendorRecord(**extract_with_jev(message or ""))
    record.action_needed = claude_client.write_action_sentence(record.model_dump_json())
    return record


if __name__ == "__main__":
    h = regex_hints("Quote Rs. 18,000 + 1.2L deposit, call 98450 12345, a@b.in, move 12 Nov or 05-11-2026")
    assert len(h["amounts"]) == 2 and h["phones"] and h["emails"] == ["a@b.in"] and len(h["dates"]) == 2, h
    print("ok", h)
