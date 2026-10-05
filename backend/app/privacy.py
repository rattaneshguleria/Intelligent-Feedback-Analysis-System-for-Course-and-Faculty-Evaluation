"""Minimum-group-size rule shared by every report and API response.

A course with only 3 responses can leak who said what even if names are removed.
All later phases must call is_reportable() before showing anything for a group.
"""
import sqlite3

from . import config


def is_reportable(count: int, k: int | None = None) -> bool:
    return count >= (k if k is not None else config.MIN_GROUP_SIZE)


def offering_status(conn: sqlite3.Connection, k: int | None = None) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM offering_response_counts ORDER BY sort_order, course_code"
    ).fetchall()
    return [
        {**dict(r), "reportable": is_reportable(r["responses"], k)} for r in rows
    ]
