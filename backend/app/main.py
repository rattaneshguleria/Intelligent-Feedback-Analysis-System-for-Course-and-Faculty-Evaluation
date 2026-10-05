"""FastAPI app.  Run from backend/:  uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config, db, ingest, privacy


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
