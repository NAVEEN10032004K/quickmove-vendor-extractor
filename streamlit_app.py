import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from app import store  # noqa: E402
from app.extractor import extract  # noqa: E402
from app.schema import Amount, Contact, DateItem, VendorRecord  # noqa: E402

MESSAGE_TYPES = ["quote", "confirmation", "delay", "cancellation", "availability", "status", "other"]
CATEGORIES = ["property", "logistics", "utility", "govt_bank", "other"]
CONFIDENCE = ["high", "medium", "low"]
CHIP_COLORS = {"high": "#1a7f37", "medium": "#b7791f", "low": "#c53030"}

st.set_page_config(page_title="QuickMove Vendor Extractor", layout="wide")
store.init_db()


def chip(text: str, color: str) -> str:
    return (f"<span style='background:{color};color:#fff;padding:2px 10px;border-radius:12px;"
            f"margin-right:6px;font-size:0.85rem'>{text}</span>")


def lines(s: str) -> list[str]:
    return [x.strip() for x in s.splitlines() if x.strip()]


st.title("Vendor Message Extractor")

# ---- 1. Input -------------------------------------------------------------
st.header("1. Input")
text = st.text_area("Paste vendor message", height=140)
shot = st.file_uploader("...or drop a screenshot", type=["png", "jpg", "jpeg"])
if st.button("Extract", type="primary"):
    if not text.strip() and not shot:
        st.warning("Paste a message or drop a screenshot first.")
    else:
        with st.spinner("Extracting..."):
            try:
                st.session_state.record = extract(text.strip() or None, shot.getvalue() if shot else None)
                st.session_state.run = st.session_state.get("run", 0) + 1  # resets review widgets
            except Exception as e:
                st.error(f"Extraction failed: {e}")

# ---- 2. Review ------------------------------------------------------------
rec: VendorRecord | None = st.session_state.get("record")
if rec:
    st.header("2. Review")
    k = lambda name: f"{name}_{st.session_state.run}"  # noqa: E731
    st.markdown(chip(f"confidence: {rec.confidence}", CHIP_COLORS[rec.confidence])
                + "".join(chip(f"⚠ {f}", "#d97706") for f in rec.red_flags), unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    message_type = c1.selectbox("Message type", MESSAGE_TYPES, MESSAGE_TYPES.index(rec.message_type), key=k("mt"))
    vendor_category = c2.selectbox("Vendor category", CATEGORIES, CATEGORIES.index(rec.vendor_category), key=k("vc"))
    confidence = c3.selectbox("Confidence", CONFIDENCE, CONFIDENCE.index(rec.confidence), key=k("cf"))

    c1, c2 = st.columns(2)
    vendor_name = c1.text_input("Vendor name", rec.vendor_name or "", key=k("vn"))
    customer_reference = c2.text_input("Customer reference", rec.customer_reference or "", key=k("cr"))

    a = rec.amount or Amount(value=0.0)
    c1, c2, c3 = st.columns([1, 1, 2])
    amount_value = c1.number_input("Amount", value=a.value, min_value=0.0, step=100.0, key=k("av"))
    amount_cur = c2.text_input("Currency", a.currency, key=k("ac"))
    amount_notes = c3.text_input("Amount notes", a.notes or "", key=k("an"))

    st.caption("Dates (add or remove rows)")
    dates_df = st.data_editor(pd.DataFrame([d.model_dump() for d in rec.dates], columns=["what", "when"]),
                              num_rows="dynamic", width="stretch", key=k("dt"))

    c1, c2 = st.columns(2)
    inclusions = c1.text_area("Inclusions (one per line)", "\n".join(rec.inclusions), key=k("in"))
    exclusions = c2.text_area("Exclusions (one per line)", "\n".join(rec.exclusions), key=k("ex"))

    ct = rec.contact or Contact()
    c1, c2, c3 = st.columns(3)
    contact_name = c1.text_input("Contact name", ct.name or "", key=k("cn"))
    contact_phone = c2.text_input("Contact phone", ct.phone or "", key=k("cp"))
    contact_email = c3.text_input("Contact email", ct.email or "", key=k("ce"))

    red_flags = st.text_area("Red flags (one per line)", "\n".join(rec.red_flags), key=k("rf"))
    action_needed = st.text_input("Action needed", rec.action_needed, key=k("ac2"))
    notes = st.text_area("Notes", rec.notes or "", key=k("no"))

    if st.button("Save record"):
        dates = [DateItem(what=str(r["what"] or ""), when=str(r["when"] or ""))
                 for _, r in dates_df.iterrows() if r["what"] or r["when"]]
        contact = Contact(name=contact_name or None, phone=contact_phone or None, email=contact_email or None)
        saved = VendorRecord(
            message_type=message_type, vendor_name=vendor_name or None, vendor_category=vendor_category,
            amount=Amount(value=amount_value, currency=amount_cur or "INR", notes=amount_notes or None)
            if amount_value else None,
            dates=dates, inclusions=lines(inclusions), exclusions=lines(exclusions),
            contact=contact if contact.model_dump(exclude_none=True) else None,
            red_flags=lines(red_flags), customer_reference=customer_reference or None,
            action_needed=action_needed, confidence=confidence, notes=notes or None)
        st.success(f"Saved as record #{store.insert(saved)}")

# ---- 3. Saved records -----------------------------------------------------
st.header("3. Saved records")
c1, c2, c3, c4 = st.columns(4)
filters = {
    "vendor_category": c1.selectbox("Category", [""] + CATEGORIES),
    "message_type": c2.selectbox("Type", [""] + MESSAGE_TYPES),
    "date_from": (d := c3.date_input("Saved from", value=[], key="df")) and d or None,
    "date_to": (d := c4.date_input("Saved to", value=[], key="dtt")) and d or None,
}
filters = {k_: (v.isoformat() if hasattr(v, "isoformat") else v) for k_, v in filters.items()}
rows = store.all_records(filters)
if rows:
    flat = pd.DataFrame(rows)[["id", "created_at", "message_type", "vendor_name", "vendor_category",
                               "customer_reference", "confidence", "action_needed"]]
    sel = st.dataframe(flat, width="stretch", hide_index=True,
                       on_select="rerun", selection_mode="single-row")
    st.download_button("Download CSV", store.export_csv(filters), "records.csv", "text/csv")
    if sel.selection.rows:
        st.subheader(f"Record #{rows[sel.selection.rows[0]]['id']}")
        st.json(rows[sel.selection.rows[0]])
else:
    st.info("No saved records match.")
