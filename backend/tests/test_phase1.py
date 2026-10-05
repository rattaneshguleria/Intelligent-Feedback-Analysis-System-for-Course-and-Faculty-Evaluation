import csv
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from app import db, ingest, privacy
from app.anonymizer import Anonymizer

SYN = Path(__file__).resolve().parents[2] / "data" / "synthetic"
SALT = b"test-salt"


class AnonymizerTests(unittest.TestCase):
    def setUp(self):
        self.a = Anonymizer(faculty_names=["Dr. Anita Sharma"], keep_tokens=["CSE201"], use_ner=False)

    def test_contact_details(self):
        r = self.a.clean("Mail me at rohan.v@gmail.com or call +91 98765 43210, reg 12412345.")
        for leaked in ("rohan.v@gmail.com", "98765", "12412345"):
            self.assertNotIn(leaked, r.text)
        self.assertEqual({"EMAIL", "PHONE", "ID"}, set(r.redactions))

    def test_faculty_names_all_forms(self):
        for s in ("Dr. Anita Sharma teaches well", "Anita ma'am is great", "Prof Sharma is helpful"):
            self.assertIn("[FACULTY]", self.a.clean(s).text, s)
            self.assertNotRegex(self.a.clean(s).text, r"Anita|Sharma")

    def test_self_intro_and_peers(self):
        r = self.a.clean("I am Rohan Verma from K22AB. My friend Simran agrees.")
        self.assertNotRegex(r.text, r"Rohan|Verma|Simran|K22AB")

    def test_unknown_titled_name(self):
        self.assertIn("[PERSON]", self.a.clean("Dr. Gupta was fine").text)

    def test_course_code_kept_but_other_ids_removed(self):
        r = self.a.clean("CSE201 was good, my id is A12345")
        self.assertIn("CSE201", r.text)
        self.assertNotIn("A12345", r.text)

    def test_normal_sentences_untouched(self):
        s = "I am very happy with the pace of this course."
        self.assertEqual(s, self.a.clean(s).text)

    def test_risk_flags(self):
        self.assertIn("unique_attribute", self.a.clean("I was the only girl in class").risk_flags)
        self.assertIn("seating", self.a.clean("I sit in the last row").risk_flags)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SYN / "feedback_raw.csv").exists():
            raise unittest.SkipTest("run scripts/generate_synthetic.py first")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "t.db"
        cls.conn = db.connect(cls.db_path)
        db.init_db(cls.conn)
        ingest.load_reference_data(cls.conn, SYN)
        anon = ingest.build_anonymizer(cls.conn, use_ner=False)
        cls.report = ingest.ingest_csv(cls.conn, SYN / "feedback_raw.csv", "raw.csv", anon, SALT)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_counts(self):
        r = self.report
        self.assertEqual(r.rows_total, 1124)
        self.assertEqual(r.loaded, 1113)
        self.assertEqual(r.duplicates, 4)
        self.assertEqual(r.too_short, 5)       # 3 blank + 2 "ok"
        self.assertEqual(r.invalid, 2)
        self.assertEqual(r.rows_total, r.loaded + r.duplicates + r.too_short + r.invalid)

    def test_no_raw_student_ids_or_injected_pii_in_database(self):
        dump = "\n".join(self.conn.iterdump()).lower()
        with open(SYN / "feedback_raw.csv", newline="", encoding="utf-8") as f:
            ids = {row["student_id"] for row in csv.DictReader(f)}
        self.assertTrue(all(i not in dump for i in ids), "raw student id found in DB")
        self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.\w+", dump), "email found in DB")
        with open(SYN / "ground_truth.csv", newline="", encoding="utf-8") as f:
            leaks = [p for row in csv.DictReader(f) for p in row["pii_strings"].split("|")
                     if p and p.lower() in dump]
        self.assertEqual(leaks, [], f"injected PII survived: {leaks[:5]}")

    def test_faculty_names_scrubbed(self):
        rows = self.conn.execute("SELECT comment FROM feedback").fetchall()
        text = " ".join(r["comment"] for r in rows)
        for n in ("Sharma", "Kulkarni", "Iyer", "Sandhu", "Malhotra", "Bedi"):
            self.assertNotIn(n, text)

    def test_hash_is_per_offering(self):
        self.assertNotEqual(ingest.respondent_hash(SALT, 1, "12400001"), ingest.respondent_hash(SALT, 2, "12400001"))
        self.assertEqual(ingest.respondent_hash(SALT, 1, " 12400001 "), ingest.respondent_hash(SALT, 1, "12400001"))
        self.assertNotEqual(ingest.respondent_hash(b"other", 1, "12400001"), ingest.respondent_hash(SALT, 1, "12400001"))

    def test_small_offering_suppressed(self):
        status = privacy.offering_status(self.conn)
        small = [s for s in status if not s["reportable"]]
        self.assertEqual([(s["course_code"], s["semester"]) for s in small], [("MTH301", "2026-Spring")])
        self.assertEqual(small[0]["responses"], 3)

    def test_reingest_adds_nothing(self):
        anon = ingest.build_anonymizer(self.conn, use_ner=False)
        again = ingest.ingest_csv(self.conn, SYN / "feedback_raw.csv", "raw.csv", anon, SALT)
        self.assertEqual(again.loaded, 0)
        self.assertGreaterEqual(again.duplicates, 1113)

    def test_missing_column_rejected(self):
        with self.assertRaises(ingest.IngestError):
            ingest.ingest_csv(self.conn, io.StringIO("student_id,comment\n1,hello there friend\n"))


if __name__ == "__main__":
    unittest.main()
