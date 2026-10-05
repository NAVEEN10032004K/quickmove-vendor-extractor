"""Offline tests (stdlib unittest, no network): python -m unittest discover -s tests -t ."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from app import claude_client, extractor, store
from app.schema import VendorRecord

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def jev(message_type="quote", category="logistics", conf=0.9, **nouls):
    base = {k: 0.0 for k in ("no_gst", "low_price", "no_insurance", "no_transit", "short_validity",
                             "advance_unknown", "unverified_broker")}
    return {**base, **nouls, "message_type": message_type, "message_type_confidence": conf,
            "vendor_category": category, "vendor_category_confidence": conf}


def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (2, 2)).save(b, "PNG")
    return b.getvalue()


class TempDB(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(store, "DB", Path(tempfile.mkdtemp()) / "t.db")
        p.start(), self.addCleanup(p.stop)
        store.init_db()


class SchemaTests(unittest.TestCase):
    def test_empty_record_valid(self):
        r = VendorRecord()
        self.assertEqual((r.message_type, r.confidence, r.dates), ("other", "low", []))

    def test_rejects_bad_enum(self):
        with self.assertRaises(ValidationError):
            VendorRecord(message_type="invoice")
        with self.assertRaises(ValidationError):
            VendorRecord(amount={"value": "Rs five"})


class HintTests(unittest.TestCase):
    def test_no_matches(self):
        self.assertEqual(extractor.regex_hints(""), {"amounts": [], "phones": [], "emails": [], "dates": []})
        self.assertEqual(extractor.regex_hints("ok sir done 🙏")["amounts"], [])

    def test_indian_formats(self):
        h = extractor.regex_hints("₹1,20,000 or 45k, deposit 1.35 lakh, +91 98450-12345, 7 Nov, 07/11/26")
        self.assertEqual(len(h["amounts"]), 3)
        self.assertEqual(len(h["phones"]), 1)
        self.assertEqual(len(h["dates"]), 2)

    def test_landline_and_short_numbers_not_phones(self):
        self.assertEqual(extractor.regex_hints("helpline 1912, ref 12345")["phones"], [])


class ExtractTests(unittest.TestCase):
    def run_text(self, jev_out, fill=None):
        with mock.patch.object(extractor.jev_client, "t", return_value=jev_out), \
             mock.patch.object(extractor.claude_client, "fill_text_fields", return_value=fill or {}):
            return extractor.extract_with_jev("msg")

    def test_flag_threshold(self):
        out = self.run_text(jev(no_insurance=0.84, no_transit=0.85))
        self.assertEqual(out["red_flags"], ["No transit coverage"])

    def test_gst_flag_only_on_quotes(self):
        self.assertIn("GST not mentioned", self.run_text(jev(no_gst=0.99))["red_flags"])
        self.assertNotIn("GST not mentioned", self.run_text(jev("availability", no_gst=0.99))["red_flags"])

    def test_flags_deduped_case_insensitively(self):
        out = self.run_text(jev(no_transit=0.99), {"red_flags": ["no transit coverage", "Odd price"]})
        self.assertEqual(out["red_flags"], ["No transit coverage", "Odd price"])

    def test_confidence_is_the_weaker_of_the_two(self):
        j = jev(conf=0.95)
        j["vendor_category_confidence"] = 0.44
        self.assertEqual(self.run_text(j)["confidence"], "low")
        self.assertEqual(self.run_text(jev(conf=0.6))["confidence"], "medium")

    def test_null_red_flags_from_model_tolerated(self):
        self.assertEqual(self.run_text(jev(), {"red_flags": None})["red_flags"], [])

    def test_null_lists_from_model_become_empty(self):
        r = VendorRecord(**self.run_text(jev(), {"inclusions": None, "dates": None}))
        self.assertEqual((r.inclusions, r.dates), ([], []))

    def test_image_routes_to_vision_not_jev(self):
        vis = {"message_type": "delay", "vendor_category": "logistics", "confidence": "medium"}
        with mock.patch.object(extractor.claude_client, "extract_with_claude_vision", return_value=vis) as v, \
             mock.patch.object(extractor.claude_client, "write_action_sentence", return_value="Call vendor."), \
             mock.patch.object(extractor.jev_client, "t") as j:
            r = extractor.extract(None, png())
        v.assert_called_once()
        j.assert_not_called()
        self.assertEqual((r.message_type, r.action_needed), ("delay", "Call vendor."))

    def test_jev_outage_propagates(self):
        with mock.patch.object(extractor.jev_client, "t", side_effect=RuntimeError("503")):
            with self.assertRaises(RuntimeError):
                extractor.extract("hello", None)


class ClaudeClientTests(unittest.TestCase):
    def test_json_tolerates_fences_and_prose(self):
        self.assertEqual(claude_client._json('Sure!\n```json\n{"a": 1}\n```'), {"a": 1})

    def test_json_missing_gives_clear_error(self):
        with self.assertRaisesRegex(ValueError, "did not return JSON"):
            claude_client._json("I cannot read this image.")

    def test_corrupt_image_rejected_before_api_call(self):
        with mock.patch.object(claude_client, "_ask") as ask:
            with self.assertRaises(Exception):
                claude_client.extract_with_claude_vision(None, b"not an image")
        ask.assert_not_called()


class StoreTests(TempDB):
    def test_empty_db(self):
        self.assertEqual(store.all_records(), [])
        store.export_csv()  # must not crash

    def test_unicode_and_roundtrip(self):
        i = store.insert(VendorRecord(vendor_name="शर्मा Packers", inclusions=["packing ₹"],
                                      amount={"value": 1.5}, contact={"phone": "98450 12345"}))
        r = store.all_records()[0]
        self.assertEqual((r["id"], r["vendor_name"], r["inclusions"]), (i, "शर्मा Packers", ["packing ₹"]))
        self.assertEqual(r["amount"]["currency"], "INR")
        self.assertIn("शर्मा".encode(), store.export_csv())

    def test_filters(self):
        store.insert(VendorRecord(message_type="quote", vendor_category="logistics"))
        store.insert(VendorRecord(message_type="delay", vendor_category="property"))
        self.assertEqual(len(store.all_records({"message_type": "quote"})), 1)
        self.assertEqual(len(store.all_records({"message_type": "quote", "vendor_category": "property"})), 0)
        self.assertEqual(len(store.all_records({"message_type": ""})), 2)  # blank filter = no filter
        self.assertEqual(len(store.all_records({"date_from": "2999-01-01"})), 0)
        self.assertEqual(len(store.all_records({"date_to": "2000-01-01"})), 0)

    def test_sql_injection_in_filter_is_inert(self):
        store.insert(VendorRecord())
        self.assertEqual(store.all_records({"message_type": "x'; DROP TABLE records;--"}), [])
        self.assertEqual(len(store.all_records()), 1)


class UITests(TempDB):
    def app(self):
        return AppTest.from_file(APP, default_timeout=30).run()

    def click(self, at, label):
        return [b for b in at.button if b.label == label][0].click().run()

    def test_extract_with_no_input_warns(self):
        at = self.click(self.app(), "Extract")
        self.assertTrue(at.warning)
        self.assertNotIn("2. Review", [h.value for h in at.header])

    def test_extraction_error_is_shown_not_raised(self):
        at = self.app()
        at.text_area[0].set_value("hello")
        with mock.patch("app.extractor.extract", side_effect=RuntimeError("API down")):
            at = self.click(at, "Extract")
        self.assertFalse(at.exception)
        self.assertIn("API down", at.error[0].value)

    def test_full_flow_extract_edit_save(self):
        rec = VendorRecord(vendor_name="Sharma", amount={"value": 500}, red_flags=["GST not mentioned"],
                           action_needed="Call.", confidence="medium")
        at = self.app()
        at.text_area[0].set_value("hello")
        with mock.patch("app.extractor.extract", return_value=rec):
            at = self.click(at, "Extract")
        self.assertIn("2. Review", [h.value for h in at.header])
        self.assertIn("GST not mentioned", " ".join(m.value for m in at.markdown))
        [t for t in at.text_input if t.label == "Vendor name"][0].set_value("Sharma Edited")
        at = self.click(at, "Save record")
        self.assertFalse(at.exception)
        self.assertIn("Saved as record #1", at.success[0].value)
        self.assertEqual(store.all_records()[0]["vendor_name"], "Sharma Edited")

    def test_saving_blank_record_stores_nulls(self):
        at = self.app()
        at.text_area[0].set_value("x")
        with mock.patch("app.extractor.extract", return_value=VendorRecord()):
            at = self.click(at, "Extract")
        at = self.click(at, "Save record")
        r = store.all_records()[0]
        self.assertFalse(at.exception)
        self.assertEqual((r["vendor_name"], r["amount"], r["contact"]), (None, None, None))

    def test_empty_saved_records_message(self):
        self.assertTrue(any("No saved records" in i.value for i in self.app().info))


if __name__ == "__main__":
    unittest.main()
