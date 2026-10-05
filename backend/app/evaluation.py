"""Accuracy evaluation for topic/theme assignment and sentiment.

Gold labels come from either
  * data/synthetic/ground_truth.csv  (aligned to stored clauses by text similarity), or
  * a hand-labelled CSV exported with `export-sample` (clause_id, gold_theme, gold_sentiment).
Use the second for real feedback: synthetic accuracy is optimistic because the generator
and the models share vocabulary.
"""
from __future__ import annotations

import csv
import difflib
import json
import math
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .themes import OTHER, THEME_NAMES

THEME_LABELS = THEME_NAMES + [OTHER]
SENT_LABELS = ["positive", "neutral", "negative"]
_SENT_MAP = {"pos": "positive", "neg": "negative", "neu": "neutral", "positive": "positive",
             "negative": "negative", "neutral": "neutral"}


# ----------------------------------------------------------------- metrics
def classification_report(gold: list[str], pred: list[str], labels: list[str]) -> dict:
    """Accuracy, per-class precision/recall/F1, macro and weighted F1, confusion matrix.
    Macro/weighted averages only include classes that appear in the gold labels."""
    if len(gold) != len(pred):
        raise ValueError("gold and pred must have the same length")
    conf = {g: {p: 0 for p in labels} for g in labels}
    for g, p in zip(gold, pred):
        if g in conf and p in conf[g]:
            conf[g][p] += 1
    per = {}
    for lab in labels:
        tp = conf[lab][lab]
        fp = sum(conf[g][lab] for g in labels if g != lab)
        fn = sum(conf[lab][p] for p in labels if p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[lab] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
                    "support": tp + fn}
    present = [lab for lab in labels if per[lab]["support"] > 0]
    n = sum(per[lab]["support"] for lab in labels)
    return {"n": n,
            "accuracy": round(sum(conf[lab][lab] for lab in labels) / n, 3) if n else 0.0,
            "macro_f1": round(sum(per[lab]["f1"] for lab in present) / len(present), 3) if present else 0.0,
            "weighted_f1": round(sum(per[lab]["f1"] * per[lab]["support"] for lab in present) / n, 3) if n else 0.0,
            "per_class": per, "confusion": conf}


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3 or len(x) != len(y):
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 3) if den else None


def purity(topic_ids: list[int], gold: list[str]) -> float:
    by_topic = defaultdict(Counter)
    for t, g in zip(topic_ids, gold):
        by_topic[t][g] += 1
    return round(sum(max(c.values()) for c in by_topic.values()) / len(gold), 3) if gold else 0.0


def npmi_coherence(topics_keywords: list[list[str]], docs: list[str], top_n: int = 8) -> float | None:
    """Mean NPMI over keyword pairs, using clauses as documents. Range -1..1, higher is better."""
    doc_sets = [set(re.findall(r"[a-z]{3,}", d.lower())) for d in docs]
    N = len(doc_sets)
    if not N:
        return None
    df, co = Counter(), Counter()
    vocab = {w for kws in topics_keywords for kw in kws[:top_n] for w in re.findall(r"[a-z]{3,}", kw.lower())}
    for ds in doc_sets:
        present = sorted(ds & vocab)
        df.update(present)
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                co[(present[i], present[j])] += 1
    scores = []
    for kws in topics_keywords:
        words = list(dict.fromkeys(w for kw in kws[:top_n] for w in re.findall(r"[a-z]{3,}", kw.lower())))
        words = [w for w in words if df[w] > 0]
        pair_scores = []
        for i in range(len(words)):
            for j in range(i + 1, len(words)):
                a, b = sorted((words[i], words[j]))
                c = co[(a, b)]
                if c == 0:
                    pair_scores.append(-1.0)
                    continue
                p_ab, p_a, p_b = c / N, df[a] / N, df[b] / N
                pair_scores.append(math.log(p_ab / (p_a * p_b)) / (-math.log(p_ab)) if p_ab < 1 else 1.0)
        if pair_scores:
            scores.append(sum(pair_scores) / len(pair_scores))
    return round(sum(scores) / len(scores), 3) if scores else None


# ----------------------------------------------------------------- gold labels
def _norm(s: str) -> str:
    s = re.sub(r"\[[A-Z]+\]", " ", s.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def gold_from_synthetic(conn: sqlite3.Connection, gt_csv) -> dict[int, dict]:
    """Align ground-truth clauses to stored clauses -> {clause_id: {theme, sentiment}}."""
    by_ref = defaultdict(list)
    for r in conn.execute("SELECT c.id cid, c.text, f.response_ref ref FROM clauses c "
                          "JOIN feedback f ON f.id = c.feedback_id ORDER BY f.id, c.position"):
        by_ref[r["ref"]].append((r["cid"], _norm(r["text"])))
    gold: dict[int, dict] = {}
    with open(gt_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            clauses = by_ref.get(row["response_ref"])
            if not clauses:
                continue
            pieces = [(p["theme"], p["sentiment"], _norm(p["text"])) for p in json.loads(row["clauses_json"])]
            ratio = lambda a, b: difflib.SequenceMatcher(None, a, b).ratio()
            pairs = []
            if len(clauses) == len(pieces):
                pairs = [(i, i) for i in range(len(pieces)) if ratio(clauses[i][1], pieces[i][2]) >= 0.6]
            else:
                cand = sorted(((ratio(c[1], p[2]), ci, pi) for ci, c in enumerate(clauses)
                               for pi, p in enumerate(pieces)), reverse=True)
                used_c, used_p = set(), set()
                for sc, ci, pi in cand:
                    if sc >= 0.75 and ci not in used_c and pi not in used_p:
                        pairs.append((ci, pi)); used_c.add(ci); used_p.add(pi)
            for ci, pi in pairs:
                theme, sent, _ = pieces[pi]
                gold[clauses[ci][0]] = {"theme": OTHER if theme == "none" else theme,
                                        "sentiment": _SENT_MAP[sent]}
    return gold


def gold_from_labels(path) -> dict[int, dict]:
    gold = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cid = int(row["clause_id"])
            entry = {}
            th = (row.get("gold_theme") or "").strip().lower()
            se = (row.get("gold_sentiment") or "").strip().lower()
            if th:
                entry["theme"] = OTHER if th == "none" else th
            if se:
                entry["sentiment"] = _SENT_MAP.get(se, se)
            if entry:
                gold[cid] = entry
    return gold


# ----------------------------------------------------------------- run evaluation
def evaluate_theme_run(conn, run_id: int, gold: dict[int, dict]) -> dict:
    run = conn.execute("SELECT * FROM model_runs WHERE id=?", (run_id,)).fetchone()
    rows = [r for r in conn.execute(
        "SELECT clause_id, topic_idx, theme FROM clause_themes WHERE run_id=?", (run_id,))
        if r["clause_id"] in gold and "theme" in gold[r["clause_id"]]]
    g = [gold[r["clause_id"]]["theme"] for r in rows]
    p = [r["theme"] for r in rows]
    rep = classification_report(g, p, THEME_LABELS)
    rep.update({"run_id": run_id, "method": run["method"], "purity": purity([r["topic_idx"] for r in rows], g)})
    coh = None
    if run["method"] in ("lda", "bertopic"):
        kws = [json.loads(t["keywords"] or "[]") for t in
               conn.execute("SELECT keywords FROM topics WHERE run_id=?", (run_id,))]
        coh = npmi_coherence(kws, [r["text"] for r in conn.execute("SELECT text FROM clauses")])
    rep["topic_coherence_npmi"] = coh
    rep["n_topics"] = conn.execute("SELECT COUNT(*) c FROM topics WHERE run_id=?", (run_id,)).fetchone()["c"]
    return rep


def evaluate_sentiment_run(conn, run_id: int, gold: dict[int, dict]) -> dict:
    run = conn.execute("SELECT * FROM sentiment_runs WHERE id=?", (run_id,)).fetchone()
    rows = [r for r in conn.execute(
        "SELECT clause_id, label FROM clause_sentiment WHERE run_id=?", (run_id,))
        if r["clause_id"] in gold and "sentiment" in gold[r["clause_id"]]]
    g = [gold[r["clause_id"]]["sentiment"] for r in rows]
    rep = classification_report(g, [r["label"] for r in rows], SENT_LABELS)
    # validity check that needs no labels: does comment-level sentiment track the star rating?
    per_comment = defaultdict(list)
    ratings = {}
    for r in conn.execute(
            "SELECT f.id fid, f.rating, cs.score FROM clause_sentiment cs "
            "JOIN clauses c ON c.id = cs.clause_id JOIN feedback f ON f.id = c.feedback_id "
            "WHERE cs.run_id=? AND f.rating IS NOT NULL", (run_id,)):
        per_comment[r["fid"]].append(r["score"])
        ratings[r["fid"]] = r["rating"]
    fids = list(per_comment)
    rep.update({"run_id": run_id, "method": run["method"],
                "rating_spearman": spearman([sum(per_comment[f]) / len(per_comment[f]) for f in fids],
                                            [ratings[f] for f in fids]),
                "rating_n": len(fids)})
    return rep


def evaluate_all(conn, gold: dict[int, dict], gold_source: str, all_runs: bool = False) -> dict:
    def pick(table):
        if all_runs:
            return [r["id"] for r in conn.execute(f"SELECT id FROM {table} ORDER BY id")]
        return [conn.execute(f"SELECT MAX(id) i FROM {table} WHERE method=?", (m["method"],)).fetchone()["i"]
                for m in conn.execute(f"SELECT DISTINCT method FROM {table}")]
    total_clauses = conn.execute("SELECT COUNT(*) c FROM clauses").fetchone()["c"]
    return {"gold_source": gold_source, "gold_clauses": len(gold), "total_clauses": total_clauses,
            "theme_runs": [evaluate_theme_run(conn, i, gold) for i in pick("model_runs")],
            "sentiment_runs": [evaluate_sentiment_run(conn, i, gold) for i in pick("sentiment_runs")]}


# ----------------------------------------------------------------- annotation sample
def export_annotation_sample(conn, out_csv, n: int = 300, seed: int = 42,
                             theme_run: int | None = None, sentiment_run: int | None = None) -> int:
    """Write a stratified sample of scrubbed clauses for hand labelling. Fill gold_theme with
    one of the theme names (or 'other') and gold_sentiment with positive/neutral/negative."""
    from .reports import resolve_runs
    runs = resolve_runs(conn, theme_run, sentiment_run)
    rows = conn.execute(
        "SELECT c.id clause_id, c.text, ct.theme predicted_theme, cs.label predicted_sentiment "
        "FROM clauses c JOIN clause_themes ct ON ct.clause_id=c.id AND ct.run_id=? "
        "JOIN clause_sentiment cs ON cs.clause_id=c.id AND cs.run_id=? ORDER BY c.id",
        (runs["theme_run"]["id"], runs["sentiment_run"]["id"])).fetchall()
    rng = random.Random(seed)
    buckets = defaultdict(list)
    seen = set()
    for r in rows:
        key = _norm(r["text"])
        if key in seen:
            continue
        seen.add(key)
        buckets[r["predicted_theme"]].append(r)
    for b in buckets.values():
        rng.shuffle(b)
    chosen = []
    while len(chosen) < n and any(buckets.values()):
        for theme in sorted(buckets):
            if buckets[theme] and len(chosen) < n:
                chosen.append(buckets[theme].pop())
    rng.shuffle(chosen)
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["clause_id", "text", "predicted_theme", "predicted_sentiment", "gold_theme", "gold_sentiment"])
        for r in chosen:
            w.writerow([r["clause_id"], r["text"], r["predicted_theme"], r["predicted_sentiment"], "", ""])
    return len(chosen)


# ----------------------------------------------------------------- markdown report
def _matrix(rep, labels):
    short = lambda s: s[:6]
    head = "| gold \\ predicted | " + " | ".join(short(l) for l in labels) + " |"
    lines = [head, "|---|" + "---:|" * len(labels)]
    for g in labels:
        if rep["per_class"][g]["support"]:
            lines.append(f"| {g} | " + " | ".join(str(rep["confusion"][g][p]) for p in labels) + " |")
    return "\n".join(lines)


def _per_class(rep, labels):
    lines = ["| Class | Precision | Recall | F1 | Support |", "|---|---:|---:|---:|---:|"]
    for lab in labels:
        c = rep["per_class"][lab]
        if c["support"]:
            lines.append(f"| {lab} | {c['precision']:.3f} | {c['recall']:.3f} | {c['f1']:.3f} | {c['support']} |")
    return "\n".join(lines)


def render_markdown(ev: dict) -> str:
    L = ["# Evaluation report", "",
         f"Gold labels: **{ev['gold_source']}**, covering {ev['gold_clauses']} of {ev['total_clauses']} stored clauses.", ""]
    if "synthetic" in ev["gold_source"]:
        L += ["> **Read this first.** The synthetic data is generated from templates that share vocabulary with "
              "the keyword and lexicon methods, so these numbers are an upper bound, not an estimate of "
              "performance on real student comments. Re-run with `--labels` on a hand-labelled sample of real "
              "feedback (`export-sample`) before quoting accuracy.", ""]
    L += ["## 1. Theme classification (topic modeling)", "",
          "| Method | Run | Clauses | Accuracy | Macro F1 | Weighted F1 | Purity | Topics | Coherence (NPMI) |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in ev["theme_runs"]:
        coh = "n/a" if r["topic_coherence_npmi"] is None else f"{r['topic_coherence_npmi']:.3f}"
        L.append(f"| {r['method']} | {r['run_id']} | {r['n']} | {r['accuracy']:.3f} | {r['macro_f1']:.3f} | "
                 f"{r['weighted_f1']:.3f} | {r['purity']:.3f} | {r['n_topics']} | {coh} |")
    L += ["", "_Purity: share of clauses that fall in the majority gold theme of their topic. Coherence: mean NPMI "
              "of each topic's top keywords over all clauses (only meaningful for learned topics: LDA, BERTopic)._", ""]
    if ev["theme_runs"]:
        best = max(ev["theme_runs"], key=lambda r: r["macro_f1"])
        L += [f"### Best theme method: {best['method']} (run {best['run_id']})", "",
              _per_class(best, THEME_LABELS), "", "Confusion matrix:", "", _matrix(best, THEME_LABELS), ""]
    L += ["## 2. Sentiment analysis", "",
          "| Method | Run | Clauses | Accuracy | Macro F1 | Weighted F1 | Rating correlation (Spearman) |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for r in ev["sentiment_runs"]:
        rho = "n/a" if r["rating_spearman"] is None else f"{r['rating_spearman']:.3f} (n={r['rating_n']})"
        L.append(f"| {r['method']} | {r['run_id']} | {r['n']} | {r['accuracy']:.3f} | {r['macro_f1']:.3f} | "
                 f"{r['weighted_f1']:.3f} | {rho} |")
    L += ["", "_Rating correlation compares each comment's mean sentiment score with the 1-5 star rating "
              "the same student gave. It needs no hand labels, so it is a useful check on real data._", ""]
    if ev["sentiment_runs"]:
        best = max(ev["sentiment_runs"], key=lambda r: r["macro_f1"])
        L += [f"### Best sentiment method: {best['method']} (run {best['run_id']})", "",
              _per_class(best, SENT_LABELS), "", "Confusion matrix:", "", _matrix(best, SENT_LABELS), ""]
    L += ["## 3. Limitations", "",
          "- Clause alignment between ground truth and stored clauses is by text similarity; clauses that "
          "could not be matched are excluded rather than guessed.",
          "- Mixed or hedged clauses (\"some sessions were interesting\") are the main source of sentiment errors.",
          "- Themes are single-label per clause; a clause that touches two themes is scored on one.", ""]
    return "\n".join(L)
