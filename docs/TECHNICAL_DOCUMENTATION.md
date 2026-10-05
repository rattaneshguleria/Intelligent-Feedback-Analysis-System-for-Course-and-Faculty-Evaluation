# Technical Documentation
Intelligent Feedback Analysis System for Course and Faculty Evaluation (CSEAIML2026-P38)

## 1. Requirements and where each is met

| Requirement | Implementation |
|---|---|
| Ingest open-ended feedback from evaluation forms | `ingest.py`, `POST /api/ingest`, CLI `ingest` |
| NLP topic modeling into themes (pace, clarity, support, ...) | `topic_models.py`: keyword baseline, LDA baseline, BERTopic (main) |
| Sentiment per theme and per course | `sentiment_models.py` (clause level) aggregated in `reports.py` |
| Summarized report per course/faculty | `reports.build_report`, `report_render.py` |
| Preserve respondent anonymity throughout | `anonymizer.py`, per-offering hashing, `privacy.py`, enforcement inside `reports.py` |
| Compare trends across semesters | `reports.build_trends`, `reports.build_comparison` |
| Evaluation report (topic and sentiment accuracy) | `evaluation.py`, CLI `evaluate`, `docs/evaluation_report.md` |
| Demonstration on anonymized representative data | `scripts/generate_synthetic.py`, `scripts/demo.sh` |
| Dashboard | Not part of the backend; consumes the endpoints in section 8 |

## 2. Architecture

```
 CSV export ──► ingest ──► feedback table ──► segmenter ──► clauses ──┬─► topic model ──► clause_themes
 (student ids,   │ hash id (HMAC, per offering)                      │
  raw comments)  │ scrub comment (regex + optional NER)              └─► sentiment model ─► clause_sentiment
                 │ drop exact date, flag re-id risk
                 ▼                                                         │
        raw id + raw text discarded                                        ▼
                                              reports.py: reports · trends · comparison  (k-threshold enforced here)
                                                                           │
                                       CLI / FastAPI / Markdown export ◄───┘          evaluation.py (gold labels)
```

Everything is stored in SQLite (`schema.sql`). Each model run is stored separately
(`model_runs`, `sentiment_runs`), so methods can be compared and reports can be regenerated
with a different run without re-ingesting anything.

## 3. Data model

| Table | Purpose |
|---|---|
| `semesters`, `faculty`, `courses` | Reference data. `semesters.sort_order` gives chronological order. |
| `offerings` | One course taught by one faculty member in one semester. The unit that reports describe. |
| `feedback` | One response: `respondent_hash`, scrubbed `comment`, optional `rating`, `YYYY-MM` only, `needs_review`. Unique on (offering, hash), so resubmissions are ignored. |
| `clauses` | A comment split into single-opinion clauses. |
| `model_runs`, `topics`, `clause_themes` | Topic runs, discovered topics with their named theme, and one theme per clause per run. |
| `sentiment_runs`, `clause_sentiment` | Sentiment runs and one label (+ score in -1..1) per clause per run. |
| `offering_response_counts` (view) | Responses per offering, used by every privacy check. |

## 4. Anonymity design

Threats considered: (a) someone with the database file; (b) a reader of a report who tries to
work out who wrote a comment; (c) differencing, i.e. comparing two reports to isolate a small group.

| Control | Defends against |
|---|---|
| Raw student id never stored; `HMAC-SHA256(secret salt, offering_id + id)` | (a). The salt is not in the database, and different offerings give unrelated hashes, so one student cannot be linked across courses. |
| Comment scrubbing: faculty names, emails, URLs, phone numbers, roll/registration numbers, titled names, self-introductions, named peers; optional spaCy NER | (a), (b). Recall-oriented, so it may over-redact slightly. |
| Exact submission dates reduced to month | (a), (b) |
| `needs_review` flag for unique-attribute phrases ("only girl", seating, hostel room); flagged comments are never quoted | (b) |
| Minimum group size k (default 5): offerings below k contribute **nothing** to any report, trend or comparison; a theme needs k distinct respondents before it is shown | (b), (c). Excluding small groups from aggregates also blocks subtraction attacks. |
| Quotes exclude clauses containing redaction tags and are de-duplicated | (b) |

Tests prove the main claims: no raw student id, email or injected PII string appears anywhere in
a full dump of the database; a suppressed offering returns no data from the offering, faculty,
course, trend or comparison functions.

Residual risk: free text can identify someone through context alone, and regex scrubbing misses
unusual names. The review flag and the minimum group size reduce this but do not remove it.

## 5. NLP pipeline

### 5.1 Segmentation
Comments are split into sentences and then at "but / however / although / though / yet / ;".
This matters because "clear lectures but way too fast" carries two opinions about two themes.
Clauses with fewer than 3 words (tags excluded) are dropped.

### 5.2 Topic modeling
Topic models find unlabelled groups; `themes.py` names them (pace, clarity, support, workload,
assessment, engagement, resources, overall). A topic that matches no theme is labelled `other`
instead of being forced into one.

| Method | How it works | Role |
|---|---|---|
| `keyword` | Weighted theme lexicon with a small stemmer; best-scoring theme wins | Transparent baseline, no dependencies |
| `lda` | Bag-of-words LDA (scikit-learn, 10 topics); topics named by matching their top words to the lexicon | Classical comparison baseline |
| `bertopic` | MiniLM sentence embeddings, UMAP, HDBSCAN, c-TF-IDF; outliers reassigned by embedding distance; each topic named by cosine similarity between its centroid and example sentences per theme (threshold 0.30) | Main method |

Several topics may map to the same theme (for example "too fast" and "too slow" clusters are both pace).

### 5.3 Sentiment
Each clause gets `positive | neutral | negative` and a score in [-1, 1].

| Method | Notes |
|---|---|
| `lexicon` | Rule-based: domain word list, negation window, intensifiers, "too X" rule, hedging and neutral markers, mixed-clause damping |
| `vader` | General-purpose baseline (compound score, +/-0.05 thresholds) |
| `transformer` | `cardiffnlp/twitter-roberta-base-sentiment-latest`; score = P(positive) - P(negative) |

## 6. Reports, trends and comparison

**Net sentiment** is the headline metric: each respondent's clauses are scored +1 / 0 / -1 and
averaged per respondent, then averaged across respondents (range -1 to +1). It is the same for every
sentiment method, so thresholds do not depend on which model produced the labels.

- A theme is a **strength** if net >= +0.25 and a **concern** if net <= -0.25 (`STRENGTH_THRESHOLD`,
  `CONCERN_THRESHOLD`). `other` and `overall` appear in tables but are never listed as strengths or concerns.
- A report contains: response count and rate, average rating, overall net sentiment, a per-theme table
  (comments, net, mean score, positive/neutral/negative share, status), strengths and improvement
  areas with up to two representative quotes each (highest-confidence, de-duplicated, never from flagged
  comments), and a generated summary paragraph. Quotes are extractive, so they cannot misstate a comment.
- Scopes: offering, faculty, course, department; optionally restricted to one semester.
- **Trends** give one series per theme (plus overall tone) across semesters in chronological order. For
  each series the change between the last two available semesters and between the first and last is
  tested with a Welch-style z test on per-respondent values (`significant` when |z| >= 1.96).
  Semesters with fewer than k respondents are reported as unavailable, never as zero.
- **Comparison** lays out faculty or courses side by side per theme, with a baseline row, for department heads.
- Which run is used: the newest run of the preferred method (BERTopic > keyword > LDA; transformer >
  VADER > lexicon), or an explicit run id.

Caveat for users of the trend flags: with about nine series and two comparisons per group, a few
"significant" changes are expected by chance alone. Treat a flag as a prompt to read the comments,
not as proof.

## 7. Evaluation

`python -m app.cli evaluate` aligns gold clause labels to stored clauses and reports accuracy, per-class
precision / recall / F1, macro and weighted F1, confusion matrices, theme purity, topic coherence
(NPMI over clauses) and, for sentiment, the Spearman correlation between each comment's mean sentiment
and the star rating the same student gave (a label-free validity check). Output: `docs/evaluation_report.md`
and `.json`.

Results on the synthetic data (2,252 of 2,320 clauses aligned to ground truth):

| Task | Method | Accuracy | Macro F1 | Other |
|---|---|---:|---:|---|
| Themes | keyword | 0.934 | 0.957 | purity 0.958 |
| Themes | LDA (10 topics) | 0.317 | 0.262 | purity 0.412, NPMI coherence -0.308 |
| Sentiment | lexicon | 0.969 | 0.938 | rating Spearman 0.23 (n=1,113) |

LDA performs poorly because the comments are short, so word-count topics mix themes; this is the
reason embedding-based topic modeling is the main method. BERTopic, VADER and the transformer
sentiment model are implemented but their numbers must be produced on the user's machine
(`python -m app.cli analyze --topics bertopic --sentiment transformer`, then `evaluate`).

**These numbers are an upper bound.** The synthetic comments come from templates that share
vocabulary with the keyword and lexicon methods. For a defensible figure, hand-label real clauses:
`export-sample` writes a stratified sample of scrubbed clauses; fill `gold_theme` and
`gold_sentiment`; run `evaluate --labels FILE`.

## 8. API reference (`uvicorn app.main:app --reload`, docs at `/docs`)

| Method and path | Purpose |
|---|---|
| `GET /api/health` | Status and minimum group size |
| `GET /api/meta` | Themes, semesters, faculty, courses, departments, available runs, thresholds |
| `POST /api/ingest` | Upload a feedback CSV (10 MB max) |
| `GET /api/offerings` | Response count and reportable flag per offering |
| `POST /api/analyze?topic_method=&sentiment_method=` | Segment, run both models (blocking) |
| `POST /api/topics?method=` / `GET /api/themes` | Run / read a topic model |
| `POST /api/sentiment?method=` / `GET /api/sentiment` | Run / read a sentiment model (GET never computes) |
| `GET /api/reports/{scope}/{key}?semester=` | Report; `{"suppressed": true}` for small groups |
| `GET /api/reports/{scope}/{key}/markdown` | Same report as Markdown |
| `GET /api/trends/all`, `GET /api/trends/{scope}/{key}` | Semester series and significance flags |
| `GET /api/compare?group_by=&semester=&department=` | Side-by-side comparison |
| `GET /api/evaluation?format=json\|md` | Accuracy against the synthetic ground truth |

`scope` is `offering` (numeric id), `faculty` (e.g. F01), `course` (e.g. CSE201) or `department` (e.g. CSE).
Report endpoints return 404 for unknown keys and optional `theme_run` / `sentiment_run` ids.
There is no authentication; see limitations.

## 9. Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `FEEDBACK_SALT` | generated into `data/.salt` | Secret for respondent hashing. Set it in production. |
| `FEEDBACK_DB` | `data/feedback.db` | SQLite file |
| `MIN_GROUP_SIZE` | 5 | k for every privacy check |
| `MIN_COMMENT_WORDS` | 3 | Shorter comments are skipped at ingest |
| `STRENGTH_THRESHOLD` / `CONCERN_THRESHOLD` | 0.25 / -0.25 | Net-sentiment cut-offs |

## 10. Testing

`python -m unittest discover -s tests -t . -v` runs 55 tests: anonymizer, ingestion and the "no PII in
the database" check, segmentation, theme and sentiment methods against ground truth, report privacy
(suppression, aggregate exclusion, theme minimum, quote cleanliness, flagged comments), chronological
trends, detection of the trends planted in the synthetic data (one faculty member improving on pace, one
declining on workload), comparison, run selection, metric formulas, and the annotation round trip.

## 11. Limitations and future work

- BERTopic, VADER and the transformer model were not executed in the development sandbox (no network);
  the code paths are straightforward but their results are unverified until run.
- The FastAPI layer is a thin wrapper over the tested functions but was not exercised by an HTTP client in tests.
- No authentication or role-based access. A deployment should let faculty see only their own reports and
  department heads only their department.
- Single-label themes per clause; a clause touching two themes is assigned to one.
- Sentiment errors concentrate in hedged or mixed clauses ("some sessions were interesting").
- Scrubbing is heuristic. A production system should add NER (spaCy) and human review of flagged comments.
- Future: confidence intervals instead of z flags, multiple-comparison correction, language support beyond English,
  and an LLM-polished summary paragraph (extractive summaries were chosen because they cannot hallucinate).
