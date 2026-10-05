"""Backend report builders for offering summaries, faculty rollups and trends."""
from __future__ import annotations

import sqlite3
from collections import defaultdict


def latest_theme_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM model_runs ORDER BY id DESC LIMIT 1").fetchone()
    return int(row["id"]) if row else None


def latest_sentiment_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM sentiment_runs ORDER BY id DESC LIMIT 1").fetchone()
    return int(row["id"]) if row else None


def _theme_distribution(conn: sqlite3.Connection, run_id: int, offering_id: int | None = None) -> list[dict]:
    if offering_id is None:
        rows = conn.execute(
            "SELECT theme, COUNT(*) AS clauses FROM clause_themes WHERE run_id=? GROUP BY theme ORDER BY clauses DESC",
            (run_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ct.theme, COUNT(*) AS clauses "
            "FROM clause_themes ct "
            "JOIN clauses c ON c.id = ct.clause_id "
            "JOIN feedback f ON f.id = c.feedback_id "
            "WHERE ct.run_id=? AND f.offering_id=? GROUP BY ct.theme ORDER BY clauses DESC",
            (run_id, offering_id),
        ).fetchall()
    total = sum(r["clauses"] for r in rows) or 1
    return [{"theme": r["theme"], "clauses": r["clauses"], "share": round(r["clauses"] / total, 3)} for r in rows]


def _sentiment_distribution(conn: sqlite3.Connection, run_id: int, offering_id: int | None = None) -> dict:
    if offering_id is None:
        rows = conn.execute(
            "SELECT label, COUNT(*) AS clauses FROM clause_sentiment WHERE run_id=? GROUP BY label",
            (run_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT cs.label, COUNT(*) AS clauses "
            "FROM clause_sentiment cs "
            "JOIN clauses c ON c.id = cs.clause_id "
            "JOIN feedback f ON f.id = c.feedback_id "
            "WHERE cs.run_id=? AND f.offering_id=? GROUP BY cs.label",
            (run_id, offering_id),
        ).fetchall()
    total = sum(r["clauses"] for r in rows) or 1
    return {r["label"]: round(r["clauses"] / total, 3) for r in rows}


def _strengths_and_improvements(theme_rows: list[dict], sentiment_rows: dict) -> tuple[list[str], list[str]]:
    if not theme_rows:
        return [], []
    theme_pos = {}
    theme_neg = {}
    for row in theme_rows:
        theme = row["theme"]
        theme_pos[theme] = sentiment_rows.get(theme, {}).get("positive", 0.0)
        theme_neg[theme] = sentiment_rows.get(theme, {}).get("negative", 0.0)

    strengths = [
        t for t, _ in sorted(
            theme_pos.items(),
            key=lambda kv: (kv[1] - theme_neg.get(kv[0], 0.0), kv[1]),
            reverse=True,
        )[:3]
    ]
    improvements = [
        t for t, _ in sorted(
            theme_neg.items(),
            key=lambda kv: (kv[1] - theme_pos.get(kv[0], 0.0), kv[1]),
            reverse=True,
        )[:3]
    ]
    return strengths, improvements


def offering_report(conn: sqlite3.Connection, offering_id: int, theme_run_id: int | None = None, sentiment_run_id: int | None = None) -> dict:
    theme_run_id = theme_run_id or latest_theme_run_id(conn)
    sentiment_run_id = sentiment_run_id or latest_sentiment_run_id(conn)
    row = conn.execute(
        "SELECT o.id AS offering_id, o.course_code, o.faculty_id, s.label AS semester, f.name AS faculty_name, "
        "COUNT(DISTINCT fb.id) AS responses "
        "FROM offerings o "
        "JOIN semesters s ON s.id = o.semester_id "
        "JOIN faculty f ON f.id = o.faculty_id "
        "LEFT JOIN feedback fb ON fb.offering_id = o.id "
        "WHERE o.id = ? GROUP BY o.id",
        (offering_id,),
    ).fetchone()
    if row is None:
        return {}

    theme_rows = _theme_distribution(conn, theme_run_id, offering_id) if theme_run_id else []
    sentiment_rows = _sentiment_distribution(conn, sentiment_run_id, offering_id) if sentiment_run_id else {}

    per_theme = defaultdict(dict)
    for r in conn.execute(
        "SELECT ct.theme, cs.label, COUNT(*) AS n "
        "FROM clause_themes ct "
        "JOIN clauses c ON c.id = ct.clause_id "
        "JOIN feedback f ON f.id = c.feedback_id "
        "LEFT JOIN clause_sentiment cs ON cs.clause_id = ct.clause_id AND cs.run_id = ? "
        "WHERE ct.run_id = ? AND f.offering_id = ? GROUP BY ct.theme, cs.label",
        (sentiment_run_id, theme_run_id, offering_id),
    ).fetchall():
        per_theme[r["theme"]][r["label"] if r["label"] else "neutral"] = r["n"]

    for theme in per_theme:
        total = sum(per_theme[theme].values()) or 1
        per_theme[theme] = {k: round(v / total, 3) for k, v in per_theme[theme].items()}

    strengths, improvements = _strengths_and_improvements(theme_rows, per_theme)
    return {
        "offering_id": row["offering_id"],
        "course_code": row["course_code"],
        "faculty_id": row["faculty_id"],
        "faculty_name": row["faculty_name"],
        "semester": row["semester"],
        "responses": int(row["responses"] or 0),
        "reportable": bool((row["responses"] or 0) >= 5),
        "theme_distribution": theme_rows,
        "sentiment_distribution": sentiment_rows,
        "strengths": strengths,
        "improvement_areas": improvements,
    }


def offering_summary(conn: sqlite3.Connection, theme_run_id: int | None = None, sentiment_run_id: int | None = None) -> list[dict]:
    theme_run_id = theme_run_id or latest_theme_run_id(conn)
    sentiment_run_id = sentiment_run_id or latest_sentiment_run_id(conn)
    if theme_run_id is None:
        return []

    rows = conn.execute(
        "SELECT o.id AS offering_id, o.course_code, o.faculty_id, s.label AS semester, "
        "f.name AS faculty_name, COUNT(DISTINCT fb.id) AS responses "
        "FROM offerings o "
        "JOIN semesters s ON s.id = o.semester_id "
        "JOIN faculty f ON f.id = o.faculty_id "
        "LEFT JOIN feedback fb ON fb.offering_id = o.id "
        "GROUP BY o.id ORDER BY s.sort_order, o.course_code"
    ).fetchall()
    out = []
    for row in rows:
        out.append(offering_report(conn, int(row["offering_id"]), theme_run_id, sentiment_run_id))
    return [r for r in out if r]


def faculty_summary(conn: sqlite3.Connection, theme_run_id: int | None = None, sentiment_run_id: int | None = None) -> list[dict]:
    theme_run_id = theme_run_id or latest_theme_run_id(conn)
    sentiment_run_id = sentiment_run_id or latest_sentiment_run_id(conn)
    rows = conn.execute(
        "SELECT f.id AS faculty_id, f.name, f.department, COUNT(DISTINCT o.id) AS offerings, "
        "COUNT(DISTINCT fb.id) AS responses "
        "FROM faculty f "
        "LEFT JOIN offerings o ON o.faculty_id = f.id "
        "LEFT JOIN feedback fb ON fb.offering_id = o.id "
        "GROUP BY f.id ORDER BY f.name"
    ).fetchall()
    summary = []
    for row in rows:
        theme_rows = conn.execute(
            "SELECT ct.theme, COUNT(*) AS clauses "
            "FROM clause_themes ct "
            "JOIN clauses c ON c.id = ct.clause_id "
            "JOIN feedback fb ON fb.id = c.feedback_id "
            "JOIN offerings o ON o.id = fb.offering_id "
            "WHERE ct.run_id = ? AND o.faculty_id = ? GROUP BY ct.theme ORDER BY clauses DESC",
            (theme_run_id, row["faculty_id"]),
        ).fetchall() if theme_run_id else []
        sentiment_rows = conn.execute(
            "SELECT cs.label, COUNT(*) AS clauses "
            "FROM clause_sentiment cs "
            "JOIN clauses c ON c.id = cs.clause_id "
            "JOIN feedback fb ON fb.id = c.feedback_id "
            "JOIN offerings o ON o.id = fb.offering_id "
            "WHERE cs.run_id = ? AND o.faculty_id = ? GROUP BY cs.label",
            (sentiment_run_id, row["faculty_id"]),
        ).fetchall() if sentiment_run_id else []

        total_themes = sum(r["clauses"] for r in theme_rows) or 1
        total_sent = sum(r["clauses"] for r in sentiment_rows) or 1
        summary.append({
            "faculty_id": row["faculty_id"],
            "name": row["name"],
            "department": row["department"],
            "offerings": int(row["offerings"] or 0),
            "responses": int(row["responses"] or 0),
            "reportable": bool((row["responses"] or 0) >= 5),
            "theme_distribution": [{"theme": r["theme"], "clauses": r["clauses"], "share": round(r["clauses"] / total_themes, 3)} for r in theme_rows],
            "sentiment_distribution": {r["label"]: round(r["clauses"] / total_sent, 3) for r in sentiment_rows},
        })
    return summary


def trend_summary(conn: sqlite3.Connection, theme_run_id: int | None = None, sentiment_run_id: int | None = None) -> list[dict]:
    theme_run_id = theme_run_id or latest_theme_run_id(conn)
    sentiment_run_id = sentiment_run_id or latest_sentiment_run_id(conn)
    if theme_run_id is None:
        return []

    rows = conn.execute(
        "SELECT s.label AS semester, ct.theme, COUNT(*) AS clauses, AVG(CASE WHEN cs.score IS NOT NULL THEN cs.score ELSE 0 END) AS avg_score "
        "FROM clause_themes ct "
        "JOIN clauses c ON c.id = ct.clause_id "
        "JOIN feedback fb ON fb.id = c.feedback_id "
        "JOIN offerings o ON o.id = fb.offering_id "
        "JOIN semesters s ON s.id = o.semester_id "
        "LEFT JOIN clause_sentiment cs ON cs.clause_id = ct.clause_id AND cs.run_id = ? "
        "WHERE ct.run_id = ? GROUP BY s.label, ct.theme ORDER BY s.sort_order, ct.theme",
        (sentiment_run_id, theme_run_id),
    ).fetchall()
    by_semester = defaultdict(list)
    for r in rows:
        by_semester[r["semester"]].append({
            "theme": r["theme"],
            "clauses": r["clauses"],
            "avg_sentiment_score": round(float(r["avg_score"] or 0.0), 3),
        })
    return [{"semester": sem, "themes": data} for sem, data in sorted(by_semester.items(), key=lambda kv: kv[0])]
