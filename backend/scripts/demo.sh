#!/usr/bin/env bash
# Full end-to-end demo on synthetic data.   Run from backend/:   bash scripts/demo.sh
# Uses its own database (data/demo.db), so it never touches data/feedback.db.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}
export FEEDBACK_DB="$(cd .. && pwd)/data/demo.db"
rm -f "$FEEDBACK_DB"

echo "== 1. synthetic data";            $PY scripts/generate_synthetic.py
echo "== 2. database + reference data"; $PY -m app.cli init && $PY -m app.cli load-reference ../data/synthetic
echo "== 3. anonymized ingestion";      $PY -m app.cli ingest ../data/synthetic/feedback_raw.csv
echo "== 4. themes + sentiment";        $PY -m app.cli analyze --topics keyword --sentiment lexicon > /dev/null
echo "== 4b. baselines for the evaluation comparison"
$PY -m app.cli topics --method lda --n-topics 10
$PY -m app.cli sentiment --method vader > /dev/null || echo "(vaderSentiment not installed, skipping)"
echo "== 5. privacy status";            $PY -m app.cli status | tail -3
echo "== 6. faculty report (F02)";      $PY -m app.cli report faculty F02
echo "== 7. semester trends (F02)";     $PY -m app.cli trends faculty F02
echo "== 8. faculty comparison";        $PY -m app.cli compare --group-by faculty --semester 2026-Spring
echo "== 9. export all reports";        $PY -m app.cli export-reports --out ../docs/sample_reports
echo "== 10. evaluation";               $PY -m app.cli evaluate
