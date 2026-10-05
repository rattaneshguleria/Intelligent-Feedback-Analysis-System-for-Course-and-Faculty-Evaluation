import json
import sqlite3

from .sentiment_models import run_sentiment


def run_sentiment_model(conn: sqlite3.Connection, method: str, **params) -> int:
    rows = conn.execute("SELECT id, text FROM clauses ORDER BY id").fetchall()
    if not rows:
        raise RuntimeError("No clauses found. Run `python -m app.cli segment` first.")
    results = run_sentiment(method, [r["text"] for r in rows], **params)
    cur = conn.execute("INSERT INTO sentiment_runs(method, n_clauses, params) VALUES (?,?,?)",
                       (method, len(rows), json.dumps(params)))
    run_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO clause_sentiment(clause_id, run_id, label, score) VALUES (?,?,?,?)",
        [(r["id"], run_id, lab, sc) for r, (lab, sc) in zip(rows, results)])
    conn.commit()
    return run_id


def sentiment_distribution(conn: sqlite3.Connection, run_id: int) -> dict:
    rows = conn.execute("SELECT label, COUNT(*) n FROM clause_sentiment WHERE run_id=? GROUP BY label",
                        (run_id,)).fetchall()
    total = sum(r["n"] for r in rows) or 1
    return {r["label"]: round(r["n"] / total, 3) for r in rows}
