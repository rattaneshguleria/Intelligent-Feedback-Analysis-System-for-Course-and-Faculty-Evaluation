# Intelligent Feedback Analysis System (CSEAIML2026-P38)

## Phase 1: schema, synthetic data, anonymized ingestion

### Run it (from `backend/`)
```bash
pip install -r requirements.txt
python scripts/generate_synthetic.py            # writes ../data/synthetic/*
python -m app.cli init
python -m app.cli load-reference ../data/synthetic
python -m app.cli ingest ../data/synthetic/feedback_raw.csv
python -m app.cli status                        # per-offering counts, suppressed groups
python -m unittest discover -s tests -t . -v    # 14 tests
uvicorn app.main:app --reload                   # POST /api/ingest, GET /api/offerings, /docs
```
Set `FEEDBACK_SALT` in production. In development a random salt is created in `data/.salt`.

### Anonymity design
| Layer | What it does |
|---|---|
| Respondent hash | `HMAC-SHA256(salt, offering_id + student_id)`, per offering, so one student cannot be linked across courses. Raw ID is never stored. |
| Comment scrubbing | Faculty names, emails, URLs, phones, reg/roll numbers, titled names, self-introductions and named peers are replaced with tags. Optional spaCy NER adds a second pass. |
| Date coarsening | Only `YYYY-MM` is kept. |
| Review flags | Comments hinting at unique attributes (e.g. "only girl", seating, hostel room) are flagged `needs_review` so later reports can exclude them as quotes. |
| Minimum group size | `privacy.is_reportable()` blocks any group with fewer than `MIN_GROUP_SIZE` (default 5) responses. Every later phase must call it. |

### Known limitations (mention these in the final documentation)
- Regex scrubbing can miss unusual names and may over-redact; spaCy NER reduces but does not remove this.
- Free text can identify someone through context alone; that is what the review flag and the minimum group size are for.
- Synthetic data is template-generated, so accuracy on it will look better than on real feedback.

### Ground truth
`data/synthetic/ground_truth.csv` holds per-clause theme and sentiment labels and the injected PII strings. It is for testing and the Phase 6 evaluation only and is not loaded into the app database.
