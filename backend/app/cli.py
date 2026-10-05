"""Command line entry point.  Run from the backend/ folder:

    python -m app.cli init
    python -m app.cli load-reference ../data/synthetic
    python -m app.cli ingest ../data/synthetic/feedback_raw.csv
    python -m app.cli status
    python -m app.cli segment
    python -m app.cli topics --method keyword|lda|bertopic [--n-topics 10]
    python -m app.cli sentiment --method lexicon|vader|transformer
    python -m app.cli show-topics [--run-id N]
    python -m app.cli show-sentiment [--run-id N]
"""
import argparse
import json

from . import db, ingest, privacy, topic_pipeline as tp
from . import sentiment_pipeline as sp


def main():
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create tables")
    p = sub.add_parser("load-reference", help="load semesters/faculty/courses/offerings CSVs")
    p.add_argument("directory")
    p = sub.add_parser("ingest", help="ingest a feedback CSV (anonymized on the way in)")
    p.add_argument("csv_path")
    sub.add_parser("status", help="response counts per offering and whether each is reportable")
    sub.add_parser("segment", help="split comments into clauses")
    p = sub.add_parser("topics", help="run a topic model over all clauses")
    p.add_argument("--method", choices=["keyword", "lda", "bertopic"], default="bertopic")
    p.add_argument("--n-topics", type=int, help="LDA: number of topics. BERTopic: reduce to N topics")
    p = sub.add_parser("sentiment", help="run a clause-level sentiment model over all clauses")
    p.add_argument("--method", choices=["lexicon", "vader", "transformer"], default="lexicon")
    p = sub.add_parser("show-topics", help="print topics and theme distribution of a run")
    p.add_argument("--run-id", type=int)
    p = sub.add_parser("show-sentiment", help="print a sentiment distribution for a run")
    p.add_argument("--run-id", type=int)
    p = sub.add_parser("summary", help="print offering, faculty, and trend summaries")
    p = sub.add_parser("reports", help="print offering and faculty report data")
    args = ap.parse_args()

    conn = db.connect()
    db.init_db(conn)

    if args.cmd == "init":
        print("Database ready.")
    elif args.cmd == "load-reference":
        print(json.dumps(ingest.load_reference_data(conn, args.directory), indent=2))
    elif args.cmd == "ingest":
        rep = ingest.ingest_csv(conn, args.csv_path, filename=args.csv_path)
        print(json.dumps(rep.as_dict(), indent=2))
    elif args.cmd == "status":
        rows = privacy.offering_status(conn)
        for r in rows:
            flag = "ok " if r["reportable"] else "SUPPRESSED"
            print(f"{r['semester']:12} {r['course_code']:7} {r['faculty_id']}  "
                  f"responses={r['responses']:3}  {flag}")
        print(f"\n{sum(not r['reportable'] for r in rows)} of {len(rows)} offerings suppressed (< k responses)")
    elif args.cmd == "segment":
        print(json.dumps(tp.segment_all(conn), indent=2))
    elif args.cmd == "topics":
        params = {}
        if args.n_topics:
            params["n_topics" if args.method == "lda" else "nr_topics"] = args.n_topics
        run_id = tp.run_topic_model(conn, args.method, **params)
        print(f"Run {run_id} ({args.method}) saved. Use: python -m app.cli show-topics --run-id {run_id}")
    elif args.cmd == "sentiment":
        run_id = sp.run_sentiment_model(conn, args.method)
        print(json.dumps({"run_id": run_id, "distribution": sp.sentiment_distribution(conn, run_id)}, indent=2))
    elif args.cmd == "show-topics":
        run_id = args.run_id or tp.latest_run_id(conn)
        if not run_id:
            raise SystemExit("No model runs yet. Run the `topics` command first.")
        meta = conn.execute("SELECT * FROM model_runs WHERE id=?", (run_id,)).fetchone()
        print(f"Run {run_id}: {meta['method']}, {meta['n_clauses']} clauses\n")
        for t in tp.topic_summary(conn, run_id):
            print(f"[{t['theme']:<11}] topic {t['topic_idx']:>3}  n={t['size']:<5} {', '.join(t['keywords'][:6])}")
            for e in t["examples"]:
                print(f"      - {e}")
        print("\nTheme distribution:")
        for d in tp.theme_distribution(conn, run_id):
            print(f"  {d['theme']:<12}{d['clauses']:>6}  {d['share']:.1%}")
    elif args.cmd == "show-sentiment":
        row = args.run_id and {"id": args.run_id} or conn.execute(
            "SELECT id FROM sentiment_runs ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            raise SystemExit("No sentiment runs yet. Run the `sentiment` command first.")
        run_id = row["id"]
        meta = conn.execute("SELECT * FROM sentiment_runs WHERE id=?", (run_id,)).fetchone()
        print(f"Run {run_id}: {meta['method']}, {meta['n_clauses']} clauses\n")
        print(json.dumps(sp.sentiment_distribution(conn, run_id), indent=2))
    elif args.cmd in {"summary", "reports"}:
        from . import reports
        print(json.dumps({
            "offerings": reports.offering_summary(conn),
            "faculty": reports.faculty_summary(conn),
            "trends": reports.trend_summary(conn),
        }, indent=2))


if __name__ == "__main__":
    main()
