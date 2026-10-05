"""Command line entry point.  Run from the backend/ folder.

Data:      init | load-reference DIR | ingest CSV | status
Analysis:  segment | topics --method M | sentiment --method M | analyze
Inspect:   show-topics | show-sentiment
Reports:   report SCOPE KEY [--semester S] [--format md|json]
           trends [SCOPE [KEY]] | compare --group-by faculty|course
           export-reports --out DIR
Quality:   export-sample --out CSV | evaluate [--labels CSV] [--out FILE]
"""
import argparse
import json
from pathlib import Path

from . import config, db, evaluation, ingest, pipeline, privacy, report_render, reports
from . import sentiment_pipeline as sp
from . import topic_pipeline as tp


def _runs(p):
    p.add_argument("--theme-run", type=int, help="topic run id (default: preferred method's newest run)")
    p.add_argument("--sentiment-run", type=int, help="sentiment run id (default: preferred method's newest run)")


def build_parser():
    ap = argparse.ArgumentParser(prog="app.cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create tables")
    p = sub.add_parser("load-reference", help="load semesters/faculty/courses/offerings CSVs")
    p.add_argument("directory")
    p = sub.add_parser("ingest", help="ingest a feedback CSV (anonymized on the way in)")
    p.add_argument("csv_path")
    sub.add_parser("status", help="response counts per offering and whether each is reportable")
    sub.add_parser("segment", help="split comments into clauses")
    p = sub.add_parser("topics", help="run a topic model over all clauses")
    p.add_argument("--method", choices=["keyword", "lda", "bertopic"], default="keyword")
    p.add_argument("--n-topics", type=int, help="LDA: number of topics. BERTopic: reduce to N topics")
    p = sub.add_parser("sentiment", help="run a clause-level sentiment model")
    p.add_argument("--method", choices=["lexicon", "vader", "transformer"], default="lexicon")
    p = sub.add_parser("analyze", help="segment + topic model + sentiment model in one step")
    p.add_argument("--topics", choices=["keyword", "lda", "bertopic"], default="keyword")
    p.add_argument("--sentiment", choices=["lexicon", "vader", "transformer"], default="lexicon")
    p = sub.add_parser("show-topics", help="print topics and theme distribution of a run")
    p.add_argument("--run-id", type=int)
    p = sub.add_parser("show-sentiment", help="print the sentiment distribution of a run")
    p.add_argument("--run-id", type=int)

    p = sub.add_parser("report", help="insight report for an offering, faculty member, course or department")
    p.add_argument("scope", choices=reports.SCOPES)
    p.add_argument("key", help="offering id | faculty id (F01) | course code (CSE201) | department (CSE)")
    p.add_argument("--semester")
    p.add_argument("--format", choices=["md", "json"], default="md")
    _runs(p)
    p = sub.add_parser("trends", help="semester-over-semester trends")
    p.add_argument("scope", nargs="?", choices=reports.TREND_SCOPES, default="all")
    p.add_argument("key", nargs="?")
    p.add_argument("--format", choices=["md", "json"], default="md")
    _runs(p)
    p = sub.add_parser("compare", help="compare faculty or courses side by side")
    p.add_argument("--group-by", choices=["faculty", "course"], default="faculty")
    p.add_argument("--semester")
    p.add_argument("--department")
    p.add_argument("--format", choices=["md", "json"], default="md")
    _runs(p)
    p = sub.add_parser("export-reports", help="write every reportable report as Markdown files")
    p.add_argument("--out", default=str(config.ROOT / "data" / "reports"))
    _runs(p)

    p = sub.add_parser("export-sample", help="export clauses for hand labelling")
    p.add_argument("--out", default=str(config.ROOT / "data" / "annotation_sample.csv"))
    p.add_argument("--n", type=int, default=300)
    _runs(p)
    p = sub.add_parser("evaluate", help="evaluate topic and sentiment runs against gold labels")
    p.add_argument("--labels", help="hand-labelled CSV (default: synthetic ground truth)")
    p.add_argument("--out", default=str(config.ROOT / "docs" / "evaluation_report.md"))
    p.add_argument("--all-runs", action="store_true", help="evaluate every stored run, not just the newest per method")
    return ap


def _slug(s):
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(s))


def export_reports(conn, out_dir, theme_run=None, sentiment_run=None):
    out = Path(out_dir)
    ctx = reports.Context(conn, theme_run, sentiment_run)
    written, skipped = [], []

    def write(rel, text):
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(rel)

    for o in ctx.offerings:
        if not o["reportable"]:
            skipped.append(f"{o['course_code']} {o['semester']}")
            continue
        r = reports.build_report(conn, "offering", o["offering_id"], ctx=ctx)
        write(f"offerings/{_slug(o['course_code'])}_{_slug(o['semester'])}.md", report_render.render_report(r))
    for scope, keys in (("faculty", sorted({o["faculty_id"] for o in ctx.offerings})),
                        ("course", sorted({o["course_code"] for o in ctx.offerings}))):
        for key in keys:
            r = reports.build_report(conn, scope, key, ctx=ctx)
            t = reports.build_trends(conn, scope, key, ctx=ctx)
            write(f"{scope}/{_slug(key)}.md", report_render.render_report(r) + "\n" + report_render.render_trends(t))
    write("trends_all.md", report_render.render_trends(reports.build_trends(conn, "all", ctx=ctx)))
    write("comparison_faculty.md", report_render.render_comparison(reports.build_comparison(conn, "faculty", ctx=ctx)))
    write("comparison_course.md", report_render.render_comparison(reports.build_comparison(conn, "course", ctx=ctx)))
    index = ["# Report index", "", f"{len(written)} files. Min group size: {ctx.k}.", ""]
    index += [f"- [{w}]({w})" for w in written]
    if skipped:
        index += ["", "Suppressed (too few responses): " + ", ".join(skipped)]
    (out / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return {"files": len(written) + 1, "suppressed_offerings": skipped, "folder": str(out)}


def main(argv=None):
    args = build_parser().parse_args(argv)
    conn = db.connect()
    db.init_db(conn)
    runs = {"theme_run": getattr(args, "theme_run", None), "sentiment_run": getattr(args, "sentiment_run", None)}

    try:
        if args.cmd == "init":
            print("Database ready.")
        elif args.cmd == "load-reference":
            print(json.dumps(ingest.load_reference_data(conn, args.directory), indent=2))
        elif args.cmd == "ingest":
            print(json.dumps(ingest.ingest_csv(conn, args.csv_path, filename=args.csv_path).as_dict(), indent=2))
        elif args.cmd == "status":
            rows = privacy.offering_status(conn)
            for r in rows:
                flag = "ok " if r["reportable"] else "SUPPRESSED"
                print(f"{r['semester']:12} {r['course_code']:7} {r['faculty_id']}  responses={r['responses']:3}  {flag}")
            print(f"\n{sum(not r['reportable'] for r in rows)} of {len(rows)} offerings suppressed (< k responses)")
        elif args.cmd == "segment":
            print(json.dumps(tp.segment_all(conn), indent=2))
        elif args.cmd == "topics":
            params = {}
            if args.n_topics:
                params["n_topics" if args.method == "lda" else "nr_topics"] = args.n_topics
            run_id = tp.run_topic_model(conn, args.method, **params)
            print(f"Run {run_id} ({args.method}) saved. See it with: python -m app.cli show-topics --run-id {run_id}")
        elif args.cmd == "sentiment":
            run_id = sp.run_sentiment_model(conn, args.method)
            print(json.dumps({"run_id": run_id, "distribution": sp.sentiment_distribution(conn, run_id)}, indent=2))
        elif args.cmd == "analyze":
            print(json.dumps(pipeline.analyze(conn, args.topics, args.sentiment), indent=2))
        elif args.cmd == "show-topics":
            run_id = args.run_id or tp.latest_run_id(conn)
            if not run_id:
                raise SystemExit("No topic runs yet. Run the `topics` command first.")
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
            row = {"id": args.run_id} if args.run_id else conn.execute(
                "SELECT id FROM sentiment_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                raise SystemExit("No sentiment runs yet. Run the `sentiment` command first.")
            meta = conn.execute("SELECT * FROM sentiment_runs WHERE id=?", (row["id"],)).fetchone()
            print(f"Run {row['id']}: {meta['method']}, {meta['n_clauses']} clauses\n")
            print(json.dumps(sp.sentiment_distribution(conn, row["id"]), indent=2))
        elif args.cmd == "report":
            key = int(args.key) if args.scope == "offering" else args.key
            r = reports.build_report(conn, args.scope, key, args.semester, **runs)
            print(json.dumps(r, indent=2) if args.format == "json" else report_render.render_report(r))
        elif args.cmd == "trends":
            t = reports.build_trends(conn, args.scope, args.key, **runs)
            print(json.dumps(t, indent=2) if args.format == "json" else report_render.render_trends(t))
        elif args.cmd == "compare":
            c = reports.build_comparison(conn, args.group_by, args.semester, args.department, **runs)
            print(json.dumps(c, indent=2) if args.format == "json" else report_render.render_comparison(c))
        elif args.cmd == "export-reports":
            print(json.dumps(export_reports(conn, args.out, **runs), indent=2))
        elif args.cmd == "export-sample":
            n = evaluation.export_annotation_sample(conn, args.out, args.n, **runs)
            print(f"Wrote {n} clauses to {args.out}. Fill gold_theme and gold_sentiment, then run:\n"
                  f"  python -m app.cli evaluate --labels {args.out}")
        elif args.cmd == "evaluate":
            if args.labels:
                gold, source = evaluation.gold_from_labels(args.labels), f"hand labels ({args.labels})"
            else:
                gt = config.ROOT / "data" / "synthetic" / "ground_truth.csv"
                if not gt.exists():
                    raise SystemExit("No ground truth found. Pass --labels or generate the synthetic data.")
                gold, source = evaluation.gold_from_synthetic(conn, gt), "synthetic ground truth"
            ev = evaluation.evaluate_all(conn, gold, source, all_runs=args.all_runs)
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(evaluation.render_markdown(ev), encoding="utf-8")
            (out.with_suffix(".json")).write_text(json.dumps(ev, indent=2), encoding="utf-8")
            for r in ev["theme_runs"]:
                print(f"themes    {r['method']:<9} accuracy={r['accuracy']:.3f} macro_f1={r['macro_f1']:.3f}")
            for r in ev["sentiment_runs"]:
                print(f"sentiment {r['method']:<9} accuracy={r['accuracy']:.3f} macro_f1={r['macro_f1']:.3f}")
            print(f"Report written to {out}")
    except (reports.ReportError, RuntimeError, ValueError) as e:
        raise SystemExit(f"Error: {e}")


if __name__ == "__main__":
    main()
