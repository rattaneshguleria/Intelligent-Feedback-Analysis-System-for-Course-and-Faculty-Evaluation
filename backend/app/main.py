"""FastAPI app.  Run from backend/:  uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config, db, ingest, privacy, reports, sentiment_pipeline as sp


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    yield


app = FastAPI(title="Feedback Analysis System", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@app.get("/api/health")
def health():
    return {"status": "ok", "min_group_size": config.MIN_GROUP_SIZE}


@app.post("/api/ingest")
async def ingest_feedback(file: UploadFile = File(...)):
    """Upload a feedback CSV. Identifiers are hashed and comments scrubbed before storage."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (10 MB max)")
    conn = db.connect()
    try:
        report = ingest.ingest_bytes(conn, data, file.filename)
    except ingest.IngestError as e:
        raise HTTPException(422, str(e))
    finally:
        conn.close()
    return report.as_dict()


@app.get("/api/offerings")
def list_offerings():
    """Response count per course offering and whether it meets the anonymity floor."""
    conn = db.connect()
    try:
        return privacy.offering_status(conn)
    finally:
        conn.close()


@app.get("/api/summary")
def get_summary():
    """High-level backend summary for offerings, faculty, and trend data."""
    conn = db.connect()
    try:
        return {
            "offerings": reports.offering_summary(conn),
            "faculty": reports.faculty_summary(conn),
            "trends": reports.trend_summary(conn),
        }
    finally:
        conn.close()


@app.get("/api/reports/offerings")
def get_offering_reports():
    conn = db.connect()
    try:
        return reports.offering_summary(conn)
    finally:
        conn.close()


@app.get("/api/reports/faculty")
def get_faculty_reports():
    conn = db.connect()
    try:
        return reports.faculty_summary(conn)
    finally:
        conn.close()


@app.get("/api/reports/trends")
def get_trends():
    conn = db.connect()
    try:
        return reports.trend_summary(conn)
    finally:
        conn.close()


@app.get("/api/sentiment")
def get_latest_sentiment(method: str = Query(default="lexicon"), run_id: int | None = None):
    """Run the selected sentiment method or return the latest saved sentiment summary."""
    conn = db.connect()
    try:
        if run_id is not None:
            row = conn.execute("SELECT id FROM sentiment_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Sentiment run not found")
            return {"run_id": row["id"], "distribution": sp.sentiment_distribution(conn, row["id"]) }

        row = conn.execute("SELECT id FROM sentiment_runs ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            rows = conn.execute("SELECT id, text FROM clauses ORDER BY id").fetchall()
            if not rows:
                return {"run_id": None, "distribution": {}}
            run_id = sp.run_sentiment_model(conn, method)
            return {"run_id": run_id, "distribution": sp.sentiment_distribution(conn, run_id)}
        return {"run_id": row["id"], "distribution": sp.sentiment_distribution(conn, row["id"]) }
    finally:
        conn.close()


@app.post("/api/sentiment")
def create_sentiment(method: str = Query(default="lexicon")):
    """Compute a clause-level sentiment run and save it to the database."""
    conn = db.connect()
    try:
        run_id = sp.run_sentiment_model(conn, method)
        return {"run_id": run_id, "distribution": sp.sentiment_distribution(conn, run_id)}
    finally:
        conn.close()
