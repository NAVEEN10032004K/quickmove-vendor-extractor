import io
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from app.schema import VendorRecord

DB = Path(os.getenv("RECORDS_DB") or Path(__file__).resolve().parent.parent / "records.db")
JSON_COLS = ["amount", "dates", "inclusions", "exclusions", "contact", "red_flags"]

SCHEMA = """CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    message_type TEXT, vendor_name TEXT, vendor_category TEXT,
    amount TEXT, dates TEXT, inclusions TEXT, exclusions TEXT, contact TEXT, red_flags TEXT,
    customer_reference TEXT, action_needed TEXT, confidence TEXT, notes TEXT)"""


@contextmanager
def _conn():  # sqlite3's own `with` commits but never closes
    c = sqlite3.connect(DB)
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db():
    with _conn() as c:
        c.execute(SCHEMA)


def insert(record: VendorRecord) -> int:
    row = record.model_dump()
    for k in JSON_COLS:
        row[k] = json.dumps(row[k], ensure_ascii=False)
    cols = ", ".join(row)
    with _conn() as c:
        return c.execute(f"INSERT INTO records ({cols}) VALUES ({', '.join('?' * len(row))})",
                         list(row.values())).lastrowid


def all_records(filters: dict | None = None) -> list[dict]:
    """filters: vendor_category, message_type (exact), date_from / date_to (YYYY-MM-DD, on created_at)."""
    f = {k: v for k, v in (filters or {}).items() if v}
    where, args = [], []
    for k in ("vendor_category", "message_type"):
        if k in f:
            where.append(f"{k} = ?"), args.append(f[k])
    if "date_from" in f:
        where.append("date(created_at) >= ?"), args.append(str(f["date_from"]))
    if "date_to" in f:
        where.append("date(created_at) <= ?"), args.append(str(f["date_to"]))
    sql = "SELECT * FROM records" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC"
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(sql, args)]
    for r in rows:
        for k in JSON_COLS:
            r[k] = json.loads(r[k]) if r[k] else None
    return rows


def export_csv(filters: dict | None = None) -> bytes:
    df = pd.DataFrame(all_records(filters))
    for k in JSON_COLS:  # keep lists readable in a sheet
        if k in df:
            df[k] = df[k].map(lambda v: json.dumps(v, ensure_ascii=False) if v is not None else "")
    return df.to_csv(index=False).encode("utf-8")


if __name__ == "__main__":
    import tempfile

    DB = Path(tempfile.mkdtemp()) / "t.db"
    init_db()
    i = insert(VendorRecord(vendor_name="X", message_type="quote", red_flags=["GST not mentioned"]))
    got = all_records({"message_type": "quote"})
    assert got[0]["id"] == i and got[0]["red_flags"] == ["GST not mentioned"]
    assert not all_records({"vendor_category": "property"})
    assert b"GST not mentioned" in export_csv()
    print("ok")
