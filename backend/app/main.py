"""FastAPI app.  Run from backend/:  uvicorn app.main:app --reload   then open /docs"""
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from . import config, db, evaluation, ingest, pipeline, privacy, report_render, reports
from . import sentiment_pipeline as sp
from . import topic_pipeline as tp
from .themes import THEMES


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    yield


app = FastAPI(title="Feedback Analysis System", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@contextmanager
def session():
    """One SQLite connection per request, opened and closed in the same thread."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except reports.ReportError as e:
        raise HTTPException(404, str(e))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ basics
@app.get("/api/health")
def health():
    return {"status": "ok", "min_group_size": config.MIN_GROUP_SIZE}


@app.get("/api/meta")
def meta():
    """Everything a dashboard needs to build its filters."""
    with session() as conn:
        try:
            selected = reports.resolve_runs(conn)
        except reports.ReportError:
            selected = None
        return {
            "min_group_size": config.MIN_GROUP_SIZE,
            "thresholds": {"strength": config.STRENGTH_THRESHOLD, "concern": config.CONCERN_THRESHOLD},
            "themes": [{"name": n, "description": s["description"]} for n, s in THEMES.items()],
            "semesters": [r["label"] for r in conn.execute("SELECT label FROM semesters ORDER BY sort_order")],
            "faculty": [dict(r) for r in conn.execute("SELECT id, name, department FROM faculty ORDER BY name")],
            "courses": [dict(r) for r in conn.execute("SELECT code, title, department FROM courses ORDER BY code")],
            "departments": [r["department"] for r in conn.execute("SELECT DISTINCT department FROM courses ORDER BY 1")],
            "topic_runs": [dict(r) for r in conn.execute("SELECT id, method, created_at FROM model_runs ORDER BY id")],
            "sentiment_runs": [dict(r) for r in conn.execute("SELECT id, method, created_at FROM sentiment_runs ORDER BY id")],
            "selected_runs": selected,
        }


@app.post("/api/ingest")
async def ingest_feedback(file: UploadFile = File(...)):
    """Upload a feedback CSV. Identifiers are hashed and comments scrubbed before storage."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (10 MB max)")
    with session() as conn:
        try:
            return ingest.ingest_bytes(conn, data, file.filename).as_dict()
        except ingest.IngestError as e:
            raise HTTPException(422, str(e))


@app.get("/api/offerings")
def list_offerings():
    """Response count per course offering and whether it meets the anonymity floor."""
    with session() as conn:
        return privacy.offering_status(conn)


# ------------------------------------------------------------------ analysis
@app.post("/api/analyze")
def analyze(topic_method: str = Query("keyword", pattern="^(keyword|lda|bertopic)$"),
            sentiment_method: str = Query("lexicon", pattern="^(lexicon|vader|transformer)$")):
    """Segment comments, run a topic model and a sentiment model. Blocking: BERTopic and the
    transformer can take minutes, so prefer the CLI for those."""
    with session() as conn:
        return _wrap(pipeline.analyze, conn, topic_method, sentiment_method)


@app.get("/api/themes")
def latest_themes(run_id: int | None = None):
    with session() as conn:
        rid = run_id or tp.latest_run_id(conn)
        if rid is None:
            return {"run_id": None, "themes": []}
        return {"run_id": rid, "themes": tp.theme_distribution(conn, rid)}


@app.post("/api/topics")
def create_topics(method: str = Query("keyword", pattern="^(keyword|lda|bertopic)$")):
    with session() as conn:
        tp.segment_all(conn)
        rid = _wrap(tp.run_topic_model, conn, method)
        return {"run_id": rid, "themes": tp.theme_distribution(conn, rid)}


@app.get("/api/sentiment")
def latest_sentiment(run_id: int | None = None):
    """Distribution of the newest (or given) sentiment run. Does not compute anything."""
    with session() as conn:
        row = ({"id": run_id} if run_id else
               conn.execute("SELECT id FROM sentiment_runs ORDER BY id DESC LIMIT 1").fetchone())
        if row is None:
            return {"run_id": None, "distribution": {}}
        if not conn.execute("SELECT 1 FROM sentiment_runs WHERE id=?", (row["id"],)).fetchone():
            raise HTTPException(404, "Sentiment run not found")
        return {"run_id": row["id"], "distribution": sp.sentiment_distribution(conn, row["id"])}


@app.post("/api/sentiment")
def create_sentiment(method: str = Query("lexicon", pattern="^(lexicon|vader|transformer)$")):
    with session() as conn:
        tp.segment_all(conn)
        rid = _wrap(sp.run_sentiment_model, conn, method)
        return {"run_id": rid, "distribution": sp.sentiment_distribution(conn, rid)}


# ------------------------------------------------------------------ reports
@app.get("/api/reports/{scope}/{key}")
def get_report(scope: str, key: str, semester: str | None = None,
               theme_run: int | None = None, sentiment_run: int | None = None):
    """scope = offering | faculty | course | department. Groups under the minimum size return
    {"suppressed": true} with no data."""
    with session() as conn:
        k = int(key) if scope == "offering" and key.isdigit() else key
        return _wrap(reports.build_report, conn, scope, k, semester, theme_run, sentiment_run)


@app.get("/api/reports/{scope}/{key}/markdown", response_class=PlainTextResponse)
def get_report_markdown(scope: str, key: str, semester: str | None = None):
    with session() as conn:
        k = int(key) if scope == "offering" and key.isdigit() else key
        return report_render.render_report(_wrap(reports.build_report, conn, scope, k, semester))


@app.get("/api/trends/all")
def get_trends_all(theme_run: int | None = None, sentiment_run: int | None = None):
    with session() as conn:
        return _wrap(reports.build_trends, conn, "all", None, theme_run, sentiment_run)


@app.get("/api/trends/{scope}/{key}")
def get_trends(scope: str, key: str, theme_run: int | None = None, sentiment_run: int | None = None):
    """Semester-over-semester series with significance flags. scope = faculty | course | department."""
    with session() as conn:
        return _wrap(reports.build_trends, conn, scope, key, theme_run, sentiment_run)


@app.get("/api/compare")
def compare(group_by: str = Query("faculty", pattern="^(faculty|course)$"),
            semester: str | None = None, department: str | None = None):
    with session() as conn:
        return _wrap(reports.build_comparison, conn, group_by, semester, department)


# ------------------------------------------------------------------ evaluation
@app.get("/api/evaluation")
def get_evaluation(format: str = Query("json", pattern="^(json|md)$")):
    """Accuracy of the newest run of each method against the synthetic ground truth."""
    gt = config.ROOT / "data" / "synthetic" / "ground_truth.csv"
    if not gt.exists():
        raise HTTPException(404, "No ground truth file. Use the CLI with --labels for hand-labelled data.")
    with session() as conn:
        gold = evaluation.gold_from_synthetic(conn, gt)
        ev = _wrap(evaluation.evaluate_all, conn, gold, "synthetic ground truth")
    if format == "md":
        return PlainTextResponse(evaluation.render_markdown(ev))
    return ev
