"""Privacy-safe reports, trends and comparisons built from stored clause themes + sentiment.

Metric used everywhere: NET SENTIMENT = mean polarity (+1 positive, 0 neutral, -1 negative),
averaged per respondent first so a verbose student does not outweigh everyone else.
It is method-independent, so thresholds stay valid for lexicon, VADER or transformer runs.

Privacy rules enforced in this module (not left to callers):
  * offerings with fewer than k responses never contribute data to any report, trend or
    comparison, so a small class cannot be recovered by subtraction either;
  * a theme needs at least k distinct respondents before its numbers are shown;
  * quotes skip comments flagged for re-identification risk and any clause containing a
    redaction tag, and are de-duplicated.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import defaultdict

from . import config
from .themes import OTHER, THEME_NAMES

SCOPES = ("offering", "faculty", "course", "department")
TREND_SCOPES = ("all", "faculty", "course", "department")
THEME_RUN_PREF = ("bertopic", "keyword", "lda")
SENT_RUN_PREF = ("transformer", "vader", "lexicon")
LIST_EXCLUDE = {OTHER, "overall"}          # shown in tables, never called a "strength"
OVERALL = "overall_tone"                   # series name for all clauses of a comment
POLARITY = {"positive": 1, "neutral": 0, "negative": -1}


class ReportError(ValueError):
    pass


# ----------------------------------------------------------------- small statistics
def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _var(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def compare_means(a: list[float], b: list[float]) -> dict:
    """Welch-style z test on per-respondent values. 'significant' means |z| >= 1.96."""
    delta = _mean(b) - _mean(a)
    se = math.sqrt(_var(a) / max(len(a), 1) + _var(b) / max(len(b), 1))
    z = delta / se if se > 0 else (math.inf if delta else 0.0)
    significant = abs(z) >= 1.96
    direction = ("improved" if delta > 0 else "declined") if significant else "stable"
    return {"delta": round(delta, 3), "z": round(z, 2) if math.isfinite(z) else None,
            "significant": significant, "direction": direction}


# ----------------------------------------------------------------- run selection
def _pick_run(conn, table, prefs, explicit):
    if explicit is not None:
        row = conn.execute(f"SELECT id, method FROM {table} WHERE id=?", (explicit,)).fetchone()
        if not row:
            raise ReportError(f"Run {explicit} not found in {table}")
        return {"id": row["id"], "method": row["method"]}
    for m in prefs:
        row = conn.execute(f"SELECT id, method FROM {table} WHERE method=? ORDER BY id DESC LIMIT 1",
                           (m,)).fetchone()
        if row:
            return {"id": row["id"], "method": row["method"]}
    return None


def resolve_runs(conn, theme_run=None, sentiment_run=None) -> dict:
    """Newest run of the preferred method (bertopic > keyword > lda; transformer > vader >
    lexicon), unless a run id is given explicitly."""
    t = _pick_run(conn, "model_runs", THEME_RUN_PREF, theme_run)
    s = _pick_run(conn, "sentiment_runs", SENT_RUN_PREF, sentiment_run)
    if not t or not s:
        raise ReportError("No topic or sentiment run found. Run `python -m app.cli analyze` first.")
    return {"theme_run": t, "sentiment_run": s}


# ----------------------------------------------------------------- data context
class Context:
    """Loads everything once so trends/comparisons do not re-query per semester."""

    def __init__(self, conn, theme_run=None, sentiment_run=None, k=None):
        self.k = k if k is not None else config.MIN_GROUP_SIZE
        self.runs = resolve_runs(conn, theme_run, sentiment_run)
        self.offerings = [dict(r, reportable=r["responses"] >= self.k) for r in conn.execute(
            "SELECT v.offering_id, v.course_code, co.title AS course_title, co.department, "
            "v.faculty_id, fa.name AS faculty_name, v.semester, v.sort_order, v.enrolled, v.responses "
            "FROM offering_response_counts v JOIN courses co ON co.code = v.course_code "
            "JOIN faculty fa ON fa.id = v.faculty_id ORDER BY v.sort_order, v.course_code")]
        self.semesters = sorted({(o["sort_order"], o["semester"]) for o in self.offerings})
        self.rows_by_offering: dict[int, list[dict]] = defaultdict(list)
        for r in conn.execute(
                "SELECT o.id AS offering_id, f.id AS feedback_id, f.rating, f.needs_review, "
                "c.id AS clause_id, c.text, ct.theme, cs.label, cs.score "
                "FROM clauses c JOIN feedback f ON f.id = c.feedback_id "
                "JOIN offerings o ON o.id = f.offering_id "
                "JOIN clause_themes ct ON ct.clause_id = c.id AND ct.run_id = ? "
                "JOIN clause_sentiment cs ON cs.clause_id = c.id AND cs.run_id = ? "
                "ORDER BY c.id",
                (self.runs["theme_run"]["id"], self.runs["sentiment_run"]["id"])):
            self.rows_by_offering[r["offering_id"]].append(dict(r))

    def rows(self, offering_ids):
        out = []
        for oid in offering_ids:
            out.extend(self.rows_by_offering.get(oid, []))
        return out


def _matches(o, scope, key):
    if scope == "all":
        return True
    if scope == "offering":
        return str(o["offering_id"]) == str(key)
    if scope == "faculty":
        return o["faculty_id"] == key
    if scope == "course":
        return o["course_code"].upper() == str(key).upper()
    if scope == "department":
        return o["department"].lower() == str(key).lower()
    raise ReportError(f"Unknown scope '{scope}'")


# ----------------------------------------------------------------- summarising rows
def _series_values(rows):
    """series name -> one polarity value per respondent (mean over that respondent's clauses)."""
    by_comment = defaultdict(list)
    for r in rows:
        by_comment[r["feedback_id"]].append(r)
    out = defaultdict(list)
    for rs in by_comment.values():
        out[OVERALL].append(_mean([POLARITY[r["label"]] for r in rs]))
        per = defaultdict(list)
        for r in rs:
            per[r["theme"]].append(POLARITY[r["label"]])
        for theme, vals in per.items():
            out[theme].append(_mean(vals))
    return out, len(by_comment)


def _shares(rows):
    n = len(rows) or 1
    c = {"positive": 0, "neutral": 0, "negative": 0}
    for r in rows:
        c[r["label"]] += 1
    return {k: round(v / n, 3) for k, v in c.items()}


def _pick_quotes(rows, theme, label, limit=2):
    seen, cands = set(), []
    for r in rows:
        if r["theme"] != theme or r["label"] != label or r["needs_review"]:
            continue
        text = r["text"]
        if "[" in text or len(text.split()) < 4:
            continue
        key = re.sub(r"[^a-z0-9]", "", text.lower())
        if key in seen:
            continue
        seen.add(key)
        cands.append(r)
    cands.sort(key=lambda r: (-abs(r["score"]), r["clause_id"]))
    return [c["text"] for c in cands[:limit]]


def _status(net):
    if net >= config.STRENGTH_THRESHOLD:
        return "strength"
    if net <= config.CONCERN_THRESHOLD:
        return "concern"
    return "mixed"


def summarize(rows, k, with_quotes=True) -> dict:
    vals, n_comments = _series_values(rows)
    ratings = {r["feedback_id"]: r["rating"] for r in rows if r["rating"] is not None}
    overall = {"comments": n_comments, "clauses": len(rows),
               "net": round(_mean(vals[OVERALL]), 3),
               "mean_score": round(_mean([r["score"] for r in rows]), 3), **_shares(rows)}
    by_theme = defaultdict(list)
    for r in rows:
        by_theme[r["theme"]].append(r)
    themes, below = [], []
    for theme, trs in by_theme.items():
        if theme == OTHER:
            continue
        cn = len({r["feedback_id"] for r in trs})
        if cn < k:
            below.append(theme)
            continue
        net = round(_mean(vals[theme]), 3)
        themes.append({"theme": theme, "comments": cn, "clauses": len(trs),
                       "mention_rate": round(cn / n_comments, 3), "net": net,
                       "mean_score": round(_mean([r["score"] for r in trs]), 3),
                       **_shares(trs), "status": _status(net)})
    themes.sort(key=lambda t: -t["net"])
    strengths = [t for t in themes if t["status"] == "strength" and t["theme"] not in LIST_EXCLUDE]
    concerns = sorted([t for t in themes if t["status"] == "concern" and t["theme"] not in LIST_EXCLUDE],
                      key=lambda t: t["net"])
    quotes = {}
    if with_quotes:
        for t in strengths:
            quotes[t["theme"]] = {"positive": _pick_quotes(rows, t["theme"], "positive")}
        for t in concerns:
            quotes[t["theme"]] = {"negative": _pick_quotes(rows, t["theme"], "negative")}
    return {"overall": overall, "avg_rating": round(_mean(list(ratings.values())), 2) if ratings else None,
            "themes": themes, "themes_below_min_group": sorted(below),
            "strengths": [t["theme"] for t in strengths],
            "improvement_areas": [t["theme"] for t in concerns], "quotes": quotes}


def _tone(net):
    return "positive" if net >= 0.2 else "negative" if net <= -0.2 else "mixed"


def narrative(title, responses, rate, s) -> str:
    o = s["overall"]
    parts = [f"{title}: {responses} students responded" +
             (f" ({rate:.0%} of those enrolled)." if rate else ".")]
    parts.append(f"Overall tone is {_tone(o['net'])} (net sentiment {o['net']:+.2f}; "
                 f"{o['positive']:.0%} of comments' clauses positive, {o['negative']:.0%} negative).")
    by = {t["theme"]: t for t in s["themes"]}
    if s["strengths"]:
        parts.append("Strengths: " + ", ".join(
            f"{t} ({by[t]['net']:+.2f}, {by[t]['comments']} comments)" for t in s["strengths"]) + ".")
    else:
        parts.append("No theme stands out as a clear strength.")
    if s["improvement_areas"]:
        parts.append("Improvement areas: " + ", ".join(
            f"{t} ({by[t]['net']:+.2f}, {by[t]['comments']} comments)" for t in s["improvement_areas"]) + ".")
    else:
        parts.append("No theme shows a clear concern.")
    busiest = sorted((t for t in s["themes"] if t["theme"] not in LIST_EXCLUDE),
                     key=lambda t: -t["comments"])[:3]
    if busiest:
        parts.append("Most discussed: " + ", ".join(t["theme"] for t in busiest) + ".")
    return " ".join(parts)


# ----------------------------------------------------------------- public: reports
def build_report(conn, scope, key, semester=None, theme_run=None, sentiment_run=None,
                 k=None, ctx: Context | None = None) -> dict:
    if scope not in SCOPES:
        raise ReportError(f"scope must be one of {', '.join(SCOPES)}")
    ctx = ctx or Context(conn, theme_run, sentiment_run, k)
    sel = [o for o in ctx.offerings
           if _matches(o, scope, key) and (semester is None or o["semester"] == semester)]
    if not sel:
        raise ReportError("No offerings match that scope/key/semester")
    ok = [o for o in sel if o["reportable"]]
    base = {"scope": scope, "key": key, "semester": semester, "runs": ctx.runs,
            "min_group_size": ctx.k, "offerings_suppressed": len(sel) - len(ok)}
    if not ok:
        return {**base, "suppressed": True,
                "reason": f"Fewer than {ctx.k} responses, so no results are shown to protect anonymity."}

    rows = ctx.rows([o["offering_id"] for o in ok])
    s = summarize(rows, ctx.k)
    responses = sum(o["responses"] for o in ok)
    enrolled = sum(o["enrolled"] or 0 for o in ok)
    rate = responses / enrolled if enrolled else None
    first = ok[0]
    title = {"offering": f"{first['course_code']} {first['course_title']} ({first['faculty_name']}, {first['semester']})",
             "faculty": f"{first['faculty_name']}" + (f", {semester}" if semester else ", all semesters"),
             "course": f"{first['course_code']} {first['course_title']}" + (f", {semester}" if semester else ", all semesters"),
             "department": f"{first['department']} department" + (f", {semester}" if semester else ", all semesters")}[scope]
    breakdown = []
    if scope != "offering":
        for o in ok:
            ov = summarize(ctx.rows([o["offering_id"]]), ctx.k, with_quotes=False)["overall"]
            breakdown.append({"offering_id": o["offering_id"], "course_code": o["course_code"],
                              "faculty_name": o["faculty_name"], "semester": o["semester"],
                              "responses": o["responses"], "net": ov["net"]})
    return {**base, "suppressed": False, "title": title, "responses": responses,
            "enrolled": enrolled or None, "response_rate": round(rate, 3) if rate else None,
            "offerings": breakdown, **s, "summary": narrative(title, responses, rate, s)}


# ----------------------------------------------------------------- public: trends
def build_trends(conn, scope="all", key=None, theme_run=None, sentiment_run=None,
                 k=None, ctx: Context | None = None) -> dict:
    if scope not in TREND_SCOPES:
        raise ReportError(f"scope must be one of {', '.join(TREND_SCOPES)}")
    ctx = ctx or Context(conn, theme_run, sentiment_run, k)
    scoped = [o for o in ctx.offerings if _matches(o, scope, key)]
    if not scoped:
        raise ReportError("No offerings match that scope/key")

    labels = [lab for _, lab in ctx.semesters]
    per_sem: dict[str, tuple] = {}
    for _, lab in ctx.semesters:
        ok = [o for o in scoped if o["semester"] == lab and o["reportable"]]
        if not ok:
            per_sem[lab] = (None, None, "no_reportable_offerings")
            continue
        rows = ctx.rows([o["offering_id"] for o in ok])
        vals, _ = _series_values(rows)
        per_sem[lab] = (rows, vals, None)

    theme_order = [t for t in THEME_NAMES]
    series_names = [OVERALL] + [t for t in theme_order
                                if any(v and t in v[1] for v in per_sem.values() if v[0] is not None)]
    series, raw = {}, {}
    for name in series_names:
        pts, raw[name] = [], {}
        for lab in labels:
            rows, vals, why = per_sem[lab]
            if rows is None:
                pts.append({"semester": lab, "available": False, "reason": why})
                continue
            v = vals.get(name, [])
            if len(v) < ctx.k:
                pts.append({"semester": lab, "available": False, "reason": "below_min_group"})
                continue
            sel = rows if name == OVERALL else [r for r in rows if r["theme"] == name]
            raw[name][lab] = v
            pts.append({"semester": lab, "available": True, "comments": len(v),
                        "net": round(_mean(v), 3),
                        "mean_score": round(_mean([r["score"] for r in sel]), 3)})
        series[name] = pts

    changes = []
    for name, pts in series.items():
        avail = [p for p in pts if p["available"]]
        if len(avail) < 2:
            continue
        pairs = [("latest", avail[-2], avail[-1])]
        if len(avail) > 2:
            pairs.append(("first_to_last", avail[0], avail[-1]))
        for kind, a, b in pairs:
            cmp = compare_means(raw[name][a["semester"]], raw[name][b["semester"]])
            changes.append({"series": name, "kind": kind, "from": a["semester"], "to": b["semester"],
                            "from_net": a["net"], "to_net": b["net"], **cmp})
    return {"scope": scope, "key": key, "semesters": labels, "series": series, "changes": changes,
            "runs": ctx.runs, "min_group_size": ctx.k}


# ----------------------------------------------------------------- public: comparison
def build_comparison(conn, group_by="faculty", semester=None, department=None,
                     theme_run=None, sentiment_run=None, k=None, ctx: Context | None = None) -> dict:
    if group_by not in ("faculty", "course"):
        raise ReportError("group_by must be 'faculty' or 'course'")
    ctx = ctx or Context(conn, theme_run, sentiment_run, k)
    pool = [o for o in ctx.offerings
            if (semester is None or o["semester"] == semester)
            and (department is None or o["department"].lower() == department.lower())]
    if not pool:
        raise ReportError("No offerings match those filters")

    def cell(offerings):
        ok = [o for o in offerings if o["reportable"]]
        if not ok:
            return None
        s = summarize(ctx.rows([o["offering_id"] for o in ok]), ctx.k, with_quotes=False)
        return {"responses": sum(o["responses"] for o in ok), "offerings": len(ok),
                "overall_net": s["overall"]["net"],
                "themes": {t["theme"]: {"net": t["net"], "comments": t["comments"]} for t in s["themes"]}}

    groups = defaultdict(list)
    for o in pool:
        groups[o["faculty_id"] if group_by == "faculty" else o["course_code"]].append(o)
    out = []
    for gk, offs in groups.items():
        label = offs[0]["faculty_name"] if group_by == "faculty" else f"{offs[0]['course_code']} {offs[0]['course_title']}"
        c = cell(offs)
        out.append({"key": gk, "label": label, "department": offs[0]["department"],
                    "suppressed": c is None, **(c or {})})
    out.sort(key=lambda g: (g["suppressed"], -g.get("overall_net", 0)))
    return {"group_by": group_by, "semester": semester, "department": department,
            "themes": [t for t in THEME_NAMES if t != "overall"] + ["overall"],
            "groups": out, "baseline": cell(pool), "runs": ctx.runs, "min_group_size": ctx.k}
