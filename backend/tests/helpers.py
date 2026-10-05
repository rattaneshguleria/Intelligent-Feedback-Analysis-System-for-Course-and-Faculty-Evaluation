"""Shared test fixture: a fully analysed database built from the synthetic data."""
import tempfile
from pathlib import Path

from app import db, ingest, pipeline

SYN = Path(__file__).resolve().parents[2] / "data" / "synthetic"
SALT = b"test-salt"


def build_db(topic_method="keyword", sentiment_method="lexicon"):
    tmp = tempfile.TemporaryDirectory()
    conn = db.connect(Path(tmp.name) / "t.db")
    db.init_db(conn)
    ingest.load_reference_data(conn, SYN)
    anon = ingest.build_anonymizer(conn, use_ner=False)
    ingest.ingest_csv(conn, SYN / "feedback_raw.csv", "raw.csv", anon, SALT)
    pipeline.analyze(conn, topic_method, sentiment_method)
    return tmp, conn
