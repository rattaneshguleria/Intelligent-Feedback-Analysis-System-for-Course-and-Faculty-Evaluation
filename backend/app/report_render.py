"""Turn report dictionaries into readable Markdown (for export and for the API)."""
from __future__ import annotations

ARROW = {"improved": "improved", "declined": "declined", "stable": "no significant change"}


def _pct(x):
    return f"{x:.0%}"


def render_report(r: dict) -> str:
    runs = r["runs"]
    if r.get("suppressed"):
        return (f"# Report: {r['scope']} {r['key']}\n\n> {r['reason']}\n\n"
                f"_Minimum group size: {r['min_group_size']}._\n")
    lines = [f"# {r['title']}", "", r["summary"], ""]
    o = r["overall"]
    lines += ["## At a glance", "",
              f"- Responses: **{r['responses']}**" + (f" ({_pct(r['response_rate'])} response rate)" if r.get("response_rate") else ""),
              f"- Net sentiment: **{o['net']:+.2f}** (positive {_pct(o['positive'])}, neutral {_pct(o['neutral'])}, negative {_pct(o['negative'])})"]
    if r.get("avg_rating") is not None:
        lines.append(f"- Average rating: **{r['avg_rating']:.2f} / 5**")
    if r["offerings_suppressed"]:
        lines.append(f"- {r['offerings_suppressed']} offering(s) left out because they have too few responses to report safely")
    lines += ["", "## Themes", "",
              "| Theme | Comments | Net | Positive | Neutral | Negative | Status |",
              "|---|---:|---:|---:|---:|---:|---|"]
    for t in r["themes"]:
        lines.append(f"| {t['theme']} | {t['comments']} | {t['net']:+.2f} | {_pct(t['positive'])} | "
                     f"{_pct(t['neutral'])} | {_pct(t['negative'])} | {t['status']} |")
    if r["themes_below_min_group"]:
        lines += ["", f"_Not shown (fewer than {r['min_group_size']} respondents): "
                      + ", ".join(r["themes_below_min_group"]) + "._"]

    def block(title, names, kind):
        out = ["", f"## {title}", ""]
        if not names:
            return out + ["None identified."]
        for n in names:
            out.append(f"**{n}**")
            for q in r["quotes"].get(n, {}).get(kind, []):
                out.append(f"> {q}")
            out.append("")
        return out
    lines += block("Strengths", r["strengths"], "positive")
    lines += block("Improvement areas", r["improvement_areas"], "negative")
    if r["offerings"]:
        lines += ["## Offerings included", "", "| Course | Faculty | Semester | Responses | Net |", "|---|---|---|---:|---:|"]
        for x in r["offerings"]:
            lines.append(f"| {x['course_code']} | {x['faculty_name']} | {x['semester']} | {x['responses']} | {x['net']:+.2f} |")
        lines.append("")
    lines += ["---", f"_Topics: {runs['theme_run']['method']} (run {runs['theme_run']['id']}); "
                     f"sentiment: {runs['sentiment_run']['method']} (run {runs['sentiment_run']['id']}). "
                     f"Net sentiment = share positive minus share negative, averaged per respondent. "
                     f"Groups under {r['min_group_size']} respondents are never shown._"]
    return "\n".join(lines) + "\n"


def render_trends(t: dict) -> str:
    title = "all courses" if t["scope"] == "all" else f"{t['scope']} {t['key']}"
    lines = [f"# Semester trends: {title}", "",
             "| Series | " + " | ".join(t["semesters"]) + " |",
             "|---|" + "---:|" * len(t["semesters"])]
    for name, pts in t["series"].items():
        cells = [f"{p['net']:+.2f} (n={p['comments']})" if p["available"] else "n/a" for p in pts]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Changes", ""]
    sig = [c for c in t["changes"]]
    if not sig:
        lines.append("Not enough reportable semesters to compare.")
    for c in sig:
        lines.append(f"- **{c['series']}** ({c['from']} to {c['to']}): {c['from_net']:+.2f} to {c['to_net']:+.2f}, "
                     f"{ARROW[c['direction']]}" + (f" (z={c['z']})" if c["z"] is not None else ""))
    lines += ["", f"_Change is called significant when |z| >= 1.96 on per-respondent values. "
                  f"Semesters with fewer than {t['min_group_size']} respondents are shown as n/a._"]
    return "\n".join(lines) + "\n"


def render_comparison(c: dict) -> str:
    where = " / ".join(x for x in (c.get("department"), c.get("semester")) if x) or "all departments and semesters"
    themes = [t for t in c["themes"]]
    lines = [f"# Comparison by {c['group_by']}: {where}", "",
             "| " + c["group_by"].capitalize() + " | Responses | Overall | " + " | ".join(themes) + " |",
             "|---|---:|---:|" + "---:|" * len(themes)]
    for g in c["groups"]:
        if g["suppressed"]:
            lines.append(f"| {g['label']} | n/a | suppressed (too few responses) |" + " |" * len(themes))
            continue
        cells = [f"{g['themes'][t]['net']:+.2f}" if t in g["themes"] else "n/a" for t in themes]
        lines.append(f"| {g['label']} | {g['responses']} | {g['overall_net']:+.2f} | " + " | ".join(cells) + " |")
    b = c.get("baseline")
    if b:
        cells = [f"{b['themes'][t]['net']:+.2f}" if t in b["themes"] else "n/a" for t in themes]
        lines.append(f"| **Baseline (all above)** | {b['responses']} | {b['overall_net']:+.2f} | " + " | ".join(cells) + " |")
    lines += ["", f"_Values are net sentiment (-1 to +1). n/a = fewer than {c['min_group_size']} respondents for that cell._"]
    return "\n".join(lines) + "\n"
