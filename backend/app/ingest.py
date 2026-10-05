"""Load reference data and ingest feedback CSVs through the anonymization layer.

Expected feedback CSV columns
  required: student_id, course_code, faculty_id, semester, comment
  optional: rating (1-5), submitted_on (YYYY-MM-DD), response_ref

The raw student_id is hashed and discarded. The raw comment is scrubbed and only
the scrubbed version is written. Neither is logged.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .anonymizer import Anonymizer

REQUIRED_COLS = {"student_id", "course_code", "faculty_id", "semester", "comment"}


class IngestError(Exception):
    pass


@dataclass
class IngestReport:
    batch_id: int = 0
    rows_total: int = 0
    loaded: int = 0
    duplicates: int = 0
    too_short: int = 0
    invalid: int = 0
    flagged_for_review: int = 0
    redactions: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)   # row number + reason, never content

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["redactions"] = dict(self.redactions)
        return d


def respondent_hash(salt: bytes, offering_id: int, student_id: str) -> str:
    """Per-offering hash: the same student gets unrelated hashes in different
    offerings, so responses cannot be linked across courses."""
    msg = f"{offering_id}|{student_id.strip().lower()}".encode()
    return hmac.new(salt, msg, hashlib.sha256).hexdigest()[:32]


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_reference_data(conn: sqlite3.Connection, directory) -> dict:
    """Load semesters.csv, faculty.csv, courses.csv, offerings.csv (idempotent)."""
    d = Path(directory)
    for r in _read_csv(d / "semesters.csv"):
        conn.execute("INSERT OR IGNORE INTO semesters(label, sort_order) VALUES (?,?)",
                     (r["label"], int(r["sort_order"])))
    for r in _read_csv(d / "faculty.csv"):
        conn.execute("INSERT OR REPLACE INTO faculty(id, name, department) VALUES (?,?,?)",
                     (r["faculty_id"], r["name"], r["department"]))
    for r in _read_csv(d / "courses.csv"):
        conn.execute("INSERT OR REPLACE INTO courses(code, title, department) VALUES (?,?,?)",
                     (r["course_code"], r["title"], r["department"]))
    for r in _read_csv(d / "offerings.csv"):
        sem = conn.execute("SELECT id FROM semesters WHERE label=?", (r["semester"],)).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO offerings(course_code, faculty_id, semester_id, enrolled) "
            "VALUES (?,?,?,?)",
            (r["course_code"], r["faculty_id"], sem["id"], int(r["enrolled"] or 0)),
        )
    conn.commit()
    return {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            for t in ("semesters", "faculty", "courses", "offerings")}


def build_anonymizer(conn: sqlite3.Connection, use_ner: bool = True) -> Anonymizer:
    names = [r["name"] for r in conn.execute("SELECT name FROM faculty")]
    codes = [r["code"] for r in conn.execute("SELECT code FROM courses")]
    return Anonymizer(faculty_names=names, keep_tokens=codes, use_ner=use_ner)


def ingest_csv(conn: sqlite3.Connection, source, filename: str = "upload.csv",
               anonymizer: Anonymizer | None = None, salt: bytes | None = None,
               ) -> IngestReport:
    """`source` is a path or a text file-like object."""
    anonymizer = anonymizer or build_anonymizer(conn)
    salt = salt or config.get_salt()

    opened = None
    if isinstance(source, (str, Path)):
        opened = open(source, newline="", encoding="utf-8-sig")
        stream = opened
    else:
        stream = source
    try:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise IngestError("CSV is empty")
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        missing = REQUIRED_COLS - set(reader.fieldnames)
        if missing:
            raise IngestError(f"Missing required column(s): {', '.join(sorted(missing))}")

        offerings = {
            (r["course_code"].upper(), r["faculty_id"], r["label"]): r["id"]
            for r in conn.execute(
                "SELECT o.id, o.course_code, o.faculty_id, s.label FROM offerings o "
                "JOIN semesters s ON s.id=o.semester_id")
        }

        rep = IngestReport()
        cur = conn.execute("INSERT INTO ingest_batches(filename) VALUES (?)", (filename,))
        rep.batch_id = cur.lastrowid

        for line_no, row in enumerate(reader, start=2):   # line 1 is the header
            rep.rows_total += 1
            sid = (row.get("student_id") or "").strip()
            key = ((row.get("course_code") or "").strip().upper(),
                   (row.get("faculty_id") or "").strip(),
                   (row.get("semester") or "").strip())
            if not sid:
                rep.invalid += 1; rep.errors.append(f"row {line_no}: missing student_id"); continue
            if key not in offerings:
                rep.invalid += 1; rep.errors.append(f"row {line_no}: unknown course/faculty/semester"); continue

            rating = None
            raw_rating = (row.get("rating") or "").strip()
            if raw_rating:
                if raw_rating.isdigit() and 1 <= int(raw_rating) <= 5:
                    rating = int(raw_rating)
                else:
                    rep.invalid += 1; rep.errors.append(f"row {line_no}: rating must be 1-5"); continue

            result = anonymizer.clean(row.get("comment") or "")
            visible_words = len(re.sub(r"\[[A-Z]+\]", "", result.text).split())
            if visible_words < config.MIN_COMMENT_WORDS:
                rep.too_short += 1; continue

            month = None
            m = re.match(r"(\d{4}-\d{2})", (row.get("submitted_on") or "").strip())
            if m:
                month = m.group(1)

            oid = offerings[key]
            c = conn.execute(
                "INSERT OR IGNORE INTO feedback(offering_id, batch_id, respondent_hash, "
                "response_ref, rating, submitted_month, comment, redaction_count, needs_review) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (oid, rep.batch_id, respondent_hash(salt, oid, sid),
                 (row.get("response_ref") or "").strip() or None, rating, month,
                 result.text, result.redaction_count, int(result.needs_review)),
            )
            if c.rowcount == 0:
                rep.duplicates += 1
                continue
            rep.loaded += 1
            rep.flagged_for_review += int(result.needs_review)
            rep.redactions.update(result.redactions)

        conn.execute(
            "UPDATE ingest_batches SET rows_total=?, rows_loaded=?, rows_duplicate=?, "
            "rows_short=?, rows_invalid=? WHERE id=?",
            (rep.rows_total, rep.loaded, rep.duplicates, rep.too_short, rep.invalid, rep.batch_id),
        )
        conn.commit()
        rep.errors = rep.errors[:50]
        return rep
    finally:
        if opened:
            opened.close()


def ingest_bytes(conn, data: bytes, filename: str, **kw) -> IngestReport:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise IngestError("File must be UTF-8 encoded CSV") from e
    return ingest_csv(conn, io.StringIO(text, newline=""), filename, **kw)
