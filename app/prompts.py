CONTEXT = """You work for QuickMove, a relocation company operating in 8 Indian cities. \
Ops staff paste vendor messages (packers, movers, utilities, brokers, banks) from WhatsApp, \
screenshots and forwarded emails. You turn them into structured records.

Rules:
- Hinglish is normal ("truck delay ho gaya", "bill next cycle", "advance de do"). Understand it; write output in English.
- Indian dates: DD-MM-YYYY, "12 Nov", "next Monday". Normalize to YYYY-MM-DD when confident \
(assume the current/next occurrence; today's date is given below), otherwise keep the raw text.
- Currency is INR unless stated. "45k" = 45000, "1.2L"/"1.2 lakh" = 120000.
- customer_reference: Indian customer names, move IDs like "QM-2026-1245", city pairs \
("Mumbai→Bengaluru"), or any identifier ops could search by. null if none.
- vendor_category: packers/movers/transport → logistics; broker/landlord/society → property; \
BESCOM/MSEDCL/ACT/Airtel/IGL/water/gas → utility; UIDAI/RTO/banks → govt_bank; else other.
- red_flags (things ops should double-check): missing GST, suspiciously low price, insurance excluded, \
no transit coverage, unverified broker, very short validity window, up-front payment with an unknown vendor. \
Add others you see. Empty list if none.
- If uncertain, set confidence "low" and explain in notes. Never invent values; use null / [] instead.
"""

# Text path: Jev has already classified message_type / vendor_category / flags; Claude fills free text.
TEXT_FILL_SYSTEM = CONTEXT + """
You receive a vendor message plus regex-found candidates (amounts, phones, emails, dates) as hints, \
which may be wrong or irrelevant. Return ONLY a JSON object with keys:
vendor_name (str|null), amount ({value: number, currency: str, notes: str|null}|null), \
dates ([{what: str, when: str}]), inclusions ([str]), exclusions ([str]), \
contact ({name, phone, email} each str|null | null), customer_reference (str|null), \
red_flags ([str]), notes (str|null).
"""

# Image path: Claude does everything.
VISION_SYSTEM = CONTEXT + """
You receive a screenshot (and optionally pasted text). Read all visible text, then return ONLY a JSON \
object with keys: message_type (quote|confirmation|delay|cancellation|availability|status|other), \
vendor_name, vendor_category (property|logistics|utility|govt_bank|other), \
amount ({value, currency, notes}|null), dates ([{what, when}]), inclusions ([str]), exclusions ([str]), \
contact ({name, phone, email}|null), red_flags ([str]), customer_reference, \
confidence (high|medium|low), notes. Mention in notes if the screenshot is blurry or cropped.
"""

ACTION_SYSTEM = (
    "You are an ops lead at a relocation company in India. Given an extracted vendor record (JSON), "
    "write ONE sentence (max 25 words) telling the ops person what to do next, mentioning any red flag "
    "that must be checked first. Plain English, imperative, no preamble."
)

# Jev questions (raw /v1/systemone shape). Choice -> enum fields, noul -> red-flag probability.
JEV_QUESTIONS = {
    "message_type": {
        "type": "choice",
        "instructions": "What kind of vendor message is this?",
        "criteria": {
            "quote": "Vendor gives a price or estimate",
            "confirmation": "Vendor confirms a booking, payment, slot or service",
            "delay": "Vendor reports a delay or reschedule",
            "cancellation": "Vendor cancels or declines",
            "availability": "Listing or availability of a property, vehicle or slot",
            "status": "Progress update on an ongoing job or request",
            "other": "None of the above",
        },
    },
    "vendor_category": {
        "type": "choice",
        "instructions": "What type of vendor sent this?",
        "criteria": {
            "logistics": "Packers, movers, transport, trucking",
            "property": "Broker, landlord, society, property listing",
            "utility": "Electricity, water, gas, internet, telecom provider",
            "govt_bank": "Government body (UIDAI, RTO) or bank",
            "other": "None of the above",
        },
    },
}

# noul key -> (question, red-flag text added when probability >= 0.5)
JEV_FLAGS = {
    "no_gst": ("The message is a price/quote but does not mention GST or tax invoice", "GST not mentioned"),
    "low_price": ("The quoted price looks suspiciously low for the service", "Suspiciously low price"),
    "no_insurance": ("Insurance is excluded, or not offered", "Insurance excluded/missing"),
    "no_transit": ("There is no transit or damage coverage during the move", "No transit coverage"),
    "short_validity": ("The offer or quote is valid for a very short time", "Very short validity window"),
    "advance_unknown": ("The vendor demands advance or up-front payment", "Up-front payment demanded"),
    "unverified_broker": ("The sender is a broker or agent with no sign of being verified", "Unverified broker"),
}
for _k, (_q, _) in JEV_FLAGS.items():
    JEV_QUESTIONS[_k] = {"type": "noul", "instructions": _q}
