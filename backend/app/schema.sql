-- Phase 1 schema. Design rule: no raw student identifier and no raw comment text
-- ever reaches this database. Only a salted, per-offering respondent hash and the
-- scrubbed comment are stored.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS semesters (
    id          INTEGER PRIMARY KEY,
    label       TEXT NOT NULL UNIQUE,          -- e.g. 2025-Spring
    sort_order  INTEGER NOT NULL               -- chronological order for trend charts
);

CREATE TABLE IF NOT EXISTS faculty (
    id          TEXT PRIMARY KEY,              -- e.g. F01
    name        TEXT NOT NULL,
    department  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    code        TEXT PRIMARY KEY,              -- e.g. CSE201
    title       TEXT NOT NULL,
    department  TEXT NOT NULL
);

-- One row = one course taught by one faculty member in one semester.
CREATE TABLE IF NOT EXISTS offerings (
    id          INTEGER PRIMARY KEY,
    course_code TEXT    NOT NULL REFERENCES courses(code),
    faculty_id  TEXT    NOT NULL REFERENCES faculty(id),
    semester_id INTEGER NOT NULL REFERENCES semesters(id),
    enrolled    INTEGER,
    UNIQUE (course_code, faculty_id, semester_id)
);

CREATE TABLE IF NOT EXISTS ingest_batches (
    id             INTEGER PRIMARY KEY,
    filename       TEXT,
    ingested_at    TEXT NOT NULL DEFAULT (datetime('now')),
    rows_total     INTEGER NOT NULL DEFAULT 0,
    rows_loaded    INTEGER NOT NULL DEFAULT 0,
    rows_duplicate INTEGER NOT NULL DEFAULT 0,
    rows_short     INTEGER NOT NULL DEFAULT 0,
    rows_invalid   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS feedback (
    id               INTEGER PRIMARY KEY,
    offering_id      INTEGER NOT NULL REFERENCES offerings(id),
    batch_id         INTEGER REFERENCES ingest_batches(id),
    respondent_hash  TEXT    NOT NULL,         -- HMAC(salt, offering_id | student_id), truncated
    response_ref     TEXT,                     -- optional form response id (not student-linked)
    rating           INTEGER CHECK (rating BETWEEN 1 AND 5),
    submitted_month  TEXT,                     -- YYYY-MM only; exact dates are dropped
    comment          TEXT    NOT NULL,         -- scrubbed text
    redaction_count  INTEGER NOT NULL DEFAULT 0,
    needs_review     INTEGER NOT NULL DEFAULT 0, -- 1 = possible re-identification risk
    UNIQUE (offering_id, respondent_hash)      -- one response per student per offering
);

CREATE INDEX IF NOT EXISTS idx_feedback_offering ON feedback(offering_id);

-- Used by every report: how many responses does each offering have?
CREATE VIEW IF NOT EXISTS offering_response_counts AS
SELECT o.id AS offering_id, o.course_code, o.faculty_id, s.label AS semester,
       s.sort_order, o.enrolled, COUNT(f.id) AS responses
FROM offerings o
JOIN semesters s ON s.id = o.semester_id
LEFT JOIN feedback f ON f.offering_id = o.id
GROUP BY o.id;

-- ---------------------------------------------------------------- Phase 2: topics
-- A comment is split into clauses; each clause gets one theme per model run.
CREATE TABLE IF NOT EXISTS clauses (
    id          INTEGER PRIMARY KEY,
    feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    text        TEXT    NOT NULL,
    UNIQUE (feedback_id, position)
);
CREATE INDEX IF NOT EXISTS idx_clauses_feedback ON clauses(feedback_id);

CREATE TABLE IF NOT EXISTS model_runs (
    id         INTEGER PRIMARY KEY,
    method     TEXT NOT NULL,                  -- keyword | lda | bertopic
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    n_clauses  INTEGER NOT NULL,
    params     TEXT                            -- JSON
);

CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
    topic_idx   INTEGER NOT NULL,
    theme       TEXT NOT NULL,                 -- named theme or 'other'
    theme_score REAL,
    keywords    TEXT,                          -- JSON list
    size        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS clause_themes (
    clause_id INTEGER NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    run_id    INTEGER NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
    topic_idx INTEGER NOT NULL,
    theme     TEXT NOT NULL,
    score     REAL,
    PRIMARY KEY (clause_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_clause_themes_run ON clause_themes(run_id, theme);

-- ---------------------------------------------------------------- Phase 3: sentiment
-- Each clause gets one sentiment label per model run so "clear but too fast"
-- is not flattened into a single overall opinion.
CREATE TABLE IF NOT EXISTS sentiment_runs (
    id         INTEGER PRIMARY KEY,
    method     TEXT NOT NULL,                  -- lexicon | vader | transformer
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    n_clauses  INTEGER NOT NULL,
    params     TEXT                            -- JSON
);

CREATE TABLE IF NOT EXISTS clause_sentiment (
    clause_id INTEGER NOT NULL REFERENCES clauses(id) ON DELETE CASCADE,
    run_id    INTEGER NOT NULL REFERENCES sentiment_runs(id) ON DELETE CASCADE,
    label     TEXT NOT NULL CHECK (label IN ('positive', 'neutral', 'negative')),
    score     REAL,
    PRIMARY KEY (clause_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_clause_sentiment_run ON clause_sentiment(run_id, label);
