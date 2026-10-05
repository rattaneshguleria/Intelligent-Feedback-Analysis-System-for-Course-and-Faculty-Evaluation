"""Glue between the database and the topic models."""
from __future__ import annotations

import json
import sqlite3

from .segmenter import segment
from .topic_models import run_method


def segment_all(conn: sqlite3.Connection) -> dict:
    """Split every comment that has no clauses yet. Safe to re-run."""
    rows = conn.execute(
        "SELECT f.id, f.comment FROM feedback f "
        "WHERE NOT EXISTS (SELECT 1 FROM clauses c WHERE c.feedback_id = f.id)").fetchall()
    n_clauses = 0
    for r in rows:
        for pos, text in enumerate(segment(r["comment"])):
            conn.execute("INSERT INTO clauses(feedback_id, position, text) VALUES (?,?,?)",
                         (r["id"], pos, text))
            n_clauses += 1
    conn.commit()
    return {"comments_segmented": len(rows), "clauses_created": n_clauses}


def run_topic_model(conn: sqlite3.Connection, method: str, **params) -> int:
    """Fit a model on all clauses, store topics and per-clause themes. Returns run id."""
    rows = conn.execute("SELECT id, text FROM clauses ORDER BY id").fetchall()
    if not rows:
        raise RuntimeError("No clauses found. Run `python -m app.cli segment` first.")
    result = run_method(method, [r["text"] for r in rows], **params)

    cur = conn.execute("INSERT INTO model_runs(method, n_clauses, params) VALUES (?,?,?)",
                       (method, len(rows), json.dumps(result.params or params)))
    run_id = cur.lastrowid
    for t in result.topics:
        conn.execute(
            "INSERT INTO topics(run_id, topic_idx, theme, theme_score, keywords, size) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, t["topic_idx"], t["theme"], t["theme_score"],
             json.dumps(t["keywords"]), t["size"]))
    conn.executemany(
        "INSERT INTO clause_themes(clause_id, run_id, topic_idx, theme, score) VALUES (?,?,?,?,?)",
        [(r["id"], run_id, a[0], a[1], a[2]) for r, a in zip(rows, result.assignments)])
    conn.commit()
    return run_id


def latest_run_id(conn: sqlite3.Connection, method: str | None = None) -> int | None:
    q = "SELECT id FROM model_runs" + (" WHERE method=?" if method else "") + " ORDER BY id DESC LIMIT 1"
    row = conn.execute(q, (method,) if method else ()).fetchone()
    return row["id"] if row else None


def theme_distribution(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT theme, COUNT(*) n FROM clause_themes WHERE run_id=? GROUP BY theme ORDER BY n DESC",
        (run_id,)).fetchall()
    total = sum(r["n"] for r in rows) or 1
    return [{"theme": r["theme"], "clauses": r["n"], "share": round(r["n"] / total, 3)} for r in rows]


def topic_summary(conn: sqlite3.Connection, run_id: int, examples: int = 2) -> list[dict]:
    out = []
    for t in conn.execute("SELECT * FROM topics WHERE run_id=? ORDER BY size DESC", (run_id,)):
        ex = conn.execute(
            "SELECT c.text FROM clause_themes ct JOIN clauses c ON c.id=ct.clause_id "
            "WHERE ct.run_id=? AND ct.topic_idx=? ORDER BY ct.score DESC, c.id LIMIT ?",
            (run_id, t["topic_idx"], examples)).fetchall()
        out.append({"topic_idx": t["topic_idx"], "theme": t["theme"], "size": t["size"],
                    "keywords": json.loads(t["keywords"] or "[]"),
                    "examples": [e["text"] for e in ex]})
    return out
