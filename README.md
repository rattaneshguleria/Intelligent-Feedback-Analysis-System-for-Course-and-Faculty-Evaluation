# Intelligent Feedback Analysis System for Course and Faculty Evaluation

Project ID: CSEAIML2026-P38

## Overview
This project builds a privacy-safe backend for analyzing open-ended student feedback for courses and faculty. The system ingests raw CSV feedback, removes personally identifying information, segments comments into clauses, assigns topic themes, performs clause-level sentiment analysis, and exposes API endpoints for reporting and monitoring.

Primary users:
- Academic quality assurance teams
- Department heads
- Faculty members

## Backend architecture
The backend is organized around three core stages:

1. Ingestion and anonymization
   - Reference data (semesters, faculty, courses, offerings) is loaded from CSV.
   - Raw student IDs are hashed per offering.
   - Comments are scrubbed for names, email/phone IDs, roll numbers, and other risky fields.
   - Short or invalid rows are rejected.

2. Clause-level analysis
   - Each feedback comment is split into clauses.
   - Topic models assign each clause to a theme such as pace, clarity, support, workload, assessment, engagement, or resources.
   - Sentiment models classify each clause as positive, neutral, or negative.

3. Reporting and privacy controls
   - Small offerings are suppressed below a configurable minimum group size.
   - Reporting APIs only expose aggregated results that are reportable.
   - Trended semester-level summaries can be added by using the stored semester and offering metadata.

## Backend modules
- `backend/app/schema.sql` — database schema for reference data, feedback, clauses, topics, and sentiment.
- `backend/app/ingest.py` — anonymized ingestion pipeline and validation rules.
- `backend/app/privacy.py` — minimum-group-size privacy checks.
- `backend/app/segmenter.py` — splitting comments into logical clauses.
- `backend/app/topic_models.py` — keyword, LDA, and BERTopic topic-model implementations.
- `backend/app/topic_pipeline.py` — stores topic model runs and clause theme assignments.
- `backend/app/sentiment_models.py` — clause-level sentiment scoring with lexicon, VADER, and transformer options.
- `backend/app/sentiment_pipeline.py` — stores sentiment runs and clause labels.
- `backend/app/main.py` — FastAPI backend endpoints.
- `backend/app/cli.py` — command-line operations for init, load, ingest, status, segmentation, topics, and sentiment.

## Quick start
Run these commands from `backend/`:

```bash
pip install -r requirements.txt
python scripts/generate_synthetic.py
python -m app.cli init
python -m app.cli load-reference ../data/synthetic
python -m app.cli ingest ../data/synthetic/feedback_raw.csv
python -m app.cli status
python -m app.cli segment
python -m app.cli topics --method keyword
python -m app.cli sentiment --method lexicon
python -m app.cli show-topics --run-id 1
python -m app.cli show-sentiment --run-id 1
python -m unittest discover -s tests -t . -v
uvicorn app.main:app --reload
```

Then open:
- `http://localhost:8000/docs`
- `POST /api/ingest`
- `GET /api/offerings`
- `GET /api/sentiment`
- `POST /api/sentiment`

## Privacy and anonymity design
| Layer | What it does |
|---|---|
| Respondent hash | `HMAC-SHA256(salt, offering_id + student_id)`, computed per offering so one student cannot be linked across courses. The raw ID is never stored. |
| Comment scrubbing | Faculty names, emails, URLs, phones, roll numbers, titled names, self-introductions, and named peers are replaced with tags. Optional spaCy NER adds a second pass. |
| Date coarsening | Only `YYYY-MM` is retained. |
| Review flags | Comments hinting at unique attributes (for example, “only girl,” seating, hostel room) are flagged as `needs_review` for later exclusion. |
| Minimum group size | `privacy.is_reportable()` blocks reports for groups smaller than `MIN_GROUP_SIZE` (default 5). |

## Known limitations
- Regex-based scrubbing can miss unusual names or over-redact some text; spaCy NER reduces but does not eliminate this.
- Free text may still reveal identity through context alone; the review flag and minimum group size are safeguards.
- Synthetic data is template-generated, so accuracy on synthetic feedback may look better than on real-world data.

## Ground truth and testing
`data/synthetic/ground_truth.csv` stores per-clause theme and sentiment labels together with the injected PII values. It is intended for evaluation and testing, and it is not loaded into the application database.

## Expected backend deliverables
The backend is designed to support the following:
- A functional feedback analysis application for course and faculty evaluations.
- Topic-modeling support for classifying open-ended comments into themes.
- Clause-level sentiment analysis.
- Summarized per-course and per-faculty insight reports.
- Privacy-preserving data handling.
- Semester-over-semester trend comparison.
- Technical documentation and demo usage based on anonymized synthetic feedback.
