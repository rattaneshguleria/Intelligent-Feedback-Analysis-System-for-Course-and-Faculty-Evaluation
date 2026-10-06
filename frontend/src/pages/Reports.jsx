import React, { useEffect, useMemo, useState } from "react";
import { getText, useApi } from "../api.js";
import {
  Async, Kpi, Ledger, Panel, Segmented, Select, SentimentSplit, Suppressed,
  cap, fmtNet, fmtSem, pct, useApp,
} from "../ui.jsx";

const SCOPES = [
  { value: "faculty", label: "Faculty" },
  { value: "course", label: "Course" },
  { value: "department", label: "Department" },
  { value: "offering", label: "Single offering" },
];

function download(name, text, type = "text/markdown") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function ThemeList({ items, quotes, ledger, empty }) {
  if (!items?.length) return <p className="small">{empty}</p>;
  return (
    <ul className="themelist">
      {items.map((t) => {
        const row = ledger.find((l) => l.label === t);
        const q = quotes?.[t] || {};
        const lines = [...(q.negative || []), ...(q.positive || [])].slice(0, 2);
        return (
          <li key={t}>
            <span className="t">{cap(t)}</span>
            {row && <span className="m num">net {fmtNet(row.net)}, {row.n} students</span>}
            {lines.map((l) => <blockquote key={l}>{l}</blockquote>)}
          </li>
        );
      })}
    </ul>
  );
}

export default function Reports() {
  const { meta, go, params } = useApp();
  const offerings = useApi("/offerings");
  const [scope, setScope] = useState(params.scope || "faculty");
  const [key, setKey] = useState(params.key ?? "");
  const [semester, setSemester] = useState("");

  const keyOptions = useMemo(() => {
    const fac = Object.fromEntries(meta.faculty.map((f) => [f.id, f.name]));
    if (scope === "faculty") return meta.faculty.map((f) => ({ value: f.id, label: f.name }));
    if (scope === "course") return meta.courses.map((c) => ({ value: c.code, label: `${c.code} ${c.title}` }));
    if (scope === "department") return meta.departments.map((d) => ({ value: d, label: d }));
    return (offerings.data || []).map((o) => ({
      value: String(o.offering_id),
      label: `${o.course_code}, ${fac[o.faculty_id] || o.faculty_id}, ${fmtSem(o.semester)}${o.reportable ? "" : " (hidden)"}`,
    }));
  }, [scope, meta, offerings.data]);

  useEffect(() => {
    if (keyOptions.length && !keyOptions.some((o) => String(o.value) === String(key))) {
      setKey(keyOptions[0].value);
    }
  }, [keyOptions, key]);

  const path = key !== "" && keyOptions.length
    ? `/reports/${scope}/${encodeURIComponent(key)}${scope !== "offering" && semester ? `?semester=${encodeURIComponent(semester)}` : ""}`
    : null;
  const report = useApi(path);

  const saveMarkdown = async () => {
    const md = await getText(path.replace(/(\/reports\/[^/]+\/[^/?]+)/, "$1/markdown"));
    download(`report-${scope}-${key}.md`, md);
  };

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <p>A written summary for one faculty member, course, department or offering, with the themes students raised and what they said.</p>
        </div>
      </div>

      <div className="controls" style={{ marginBottom: 20 }}>
        <Segmented label="Report type" value={scope} onChange={(v) => { setScope(v); setKey(""); }} options={SCOPES} />
        <Select label={SCOPES.find((s) => s.value === scope).label} value={key} onChange={setKey} options={keyOptions} />
        {scope !== "offering" && (
          <Select label="Semester" value={semester} onChange={setSemester}
                  options={[{ value: "", label: "All semesters" }, ...meta.semesters.map((s) => ({ value: s, label: fmtSem(s) }))]} />
        )}
      </div>

      <Async state={report}>
        {(r) => {
          if (r.suppressed) return <Suppressed reason={r.reason} min={r.min_group_size} />;
          const ledger = (r.themes || []).map((t) => ({
            label: t.theme, net: t.net, n: t.comments,
            title: `${cap(t.theme)}: ${pct(t.positive)} positive, ${pct(t.neutral)} neutral, ${pct(t.negative)} negative`,
          })).sort((a, b) => b.net - a.net);
          const summary = typeof r.summary === "string" ? r.summary : r.summary?.text;
          return (
            <div className="stack">
              <Panel>
                <div className="panel-head">
                  <h2>{r.title}</h2>
                  <span className="hint noprint">
                    <button className="btn ghost" onClick={saveMarkdown}>Download report</button>{" "}
                    <button className="btn ghost" onClick={() => window.print()}>Print</button>
                  </span>
                </div>
                {summary && <p className="narrative">{summary}</p>}
                <p className="small" style={{ marginTop: 10 }}>
                  Themes found with the {r.runs?.theme_run?.method} model; sentiment scored with the {r.runs?.sentiment_run?.method} model.
                </p>
              </Panel>

              <div className="kpis">
                <Kpi label="Students who responded" value={r.responses} sub={r.enrolled ? `of ${r.enrolled} enrolled` : ""} />
                <Kpi label="Response rate" value={pct(r.response_rate)} />
                <Kpi label="Average rating" value={r.avg_rating != null ? `${r.avg_rating} / 5` : "–"} />
                <Kpi label="Net sentiment" value={fmtNet(r.overall?.net)} sub="positive minus negative" />
              </div>

              <Panel title="How students felt overall" hint={`${r.overall?.clauses} statements from ${r.overall?.comments} comments`}>
                <SentimentSplit positive={r.overall?.positive} neutral={r.overall?.neutral} negative={r.overall?.negative} />
              </Panel>

              <Panel title="Themes" hint="Hover a row for the sentiment split">
                {ledger.length ? <Ledger rows={ledger} /> : <p className="small">No theme has enough responses to show.</p>}
                {r.themes_below_min_group?.length > 0 && (
                  <p className="small" style={{ marginTop: 10 }}>
                    Not shown, fewer than {r.min_group_size} students raised them: {r.themes_below_min_group.map(cap).join(", ")}.
                  </p>
                )}
              </Panel>

              <div className="grid2">
                <Panel title="Strengths">
                  <ThemeList items={r.strengths} quotes={r.quotes} ledger={ledger}
                             empty="No theme is clearly positive enough to call a strength." />
                </Panel>
                <Panel title="Areas to improve">
                  <ThemeList items={r.improvement_areas} quotes={r.quotes} ledger={ledger}
                             empty="No theme is clearly negative enough to flag." />
                </Panel>
              </div>

              {r.offerings?.length > 0 && (
                <Panel title="Offerings included" hint="Select a row to open its report">
                  <div className="tablewrap">
                    <table>
                      <thead><tr><th>Course</th><th>Faculty</th><th>Semester</th><th className="r">Students</th><th className="r">Net</th></tr></thead>
                      <tbody>
                        {r.offerings.map((o) => (
                          <tr key={o.offering_id} className="click"
                              onClick={() => go("reports", { scope: "offering", key: String(o.offering_id) })}>
                            <td>{o.course_code}</td><td>{o.faculty_name}</td><td>{fmtSem(o.semester)}</td>
                            <td className="r num">{o.responses}</td><td className="r num">{fmtNet(o.net)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              )}
            </div>
          );
        }}
      </Async>
    </div>
  );
}
