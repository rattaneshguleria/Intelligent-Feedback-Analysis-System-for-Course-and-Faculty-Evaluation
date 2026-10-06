import React, { useEffect, useMemo, useState } from "react";
import { useApi } from "../api.js";
import { SeriesChips, TrendChart, seriesLabel } from "../charts.jsx";
import { Async, Badge, Panel, Segmented, Select, fmtNet, fmtSem, themeColor, useApp } from "../ui.jsx";

const SCOPES = [
  { value: "all", label: "Institution" },
  { value: "department", label: "Department" },
  { value: "faculty", label: "Faculty" },
  { value: "course", label: "Course" },
];

export default function Trends() {
  const { meta } = useApp();
  const [scope, setScope] = useState("all");
  const [key, setKey] = useState("");
  const [shown, setShown] = useState(["overall_tone", "pace", "workload"]);

  const keyOptions = useMemo(() => {
    if (scope === "faculty") return meta.faculty.map((f) => ({ value: f.id, label: f.name }));
    if (scope === "course") return meta.courses.map((c) => ({ value: c.code, label: `${c.code} ${c.title}` }));
    if (scope === "department") return meta.departments.map((d) => ({ value: d, label: d }));
    return [];
  }, [scope, meta]);

  useEffect(() => {
    if (scope !== "all" && !keyOptions.some((o) => o.value === key)) setKey(keyOptions[0]?.value ?? "");
  }, [scope, keyOptions, key]);

  const path = scope === "all" ? "/trends/all" : key ? `/trends/${scope}/${encodeURIComponent(key)}` : null;
  const trends = useApi(path);
  const toggle = (k) => setShown((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Trends</h1>
          <p>How sentiment changed from semester to semester. A change is flagged only when it is larger than random variation between two groups of students would explain.</p>
        </div>
      </div>

      <div className="controls" style={{ marginBottom: 20 }}>
        <Segmented label="Scope" value={scope} onChange={(v) => { setScope(v); setKey(""); }} options={SCOPES} />
        {scope !== "all" && (
          <Select label={SCOPES.find((s) => s.value === scope).label} value={key} onChange={setKey} options={keyOptions} />
        )}
      </div>

      <Async state={trends}>
        {(t) => {
          const keys = ["overall_tone", ...meta.themes.map((x) => x.name)];
          const hiddenPoints = shown.reduce((n, k) => n + (t.series[k] || []).filter((p) => !p.available).length, 0);
          const changes = t.changes
            .filter((c) => c.kind === "first_to_last")
            .sort((a, b) => Number(b.significant) - Number(a.significant) || Math.abs(b.delta) - Math.abs(a.delta));
          const latest = Object.fromEntries(t.changes.filter((c) => c.kind === "latest").map((c) => [c.series, c]));
          return (
            <div className="stack">
              <Panel title="Net sentiment by semester" hint="Above the line is positive, below is negative">
                <SeriesChips all={keys} active={shown} onToggle={toggle} />
                <TrendChart semesters={t.semesters} series={t.series} keys={shown} />
                {hiddenPoints > 0 && (
                  <p className="small" style={{ marginTop: 8 }}>
                    Gaps in a line mean fewer than {t.min_group_size} students raised that theme that semester.
                  </p>
                )}
              </Panel>

              <Panel title="Change from first to last semester"
                     hint={t.semesters.length > 1 ? `${fmtSem(t.semesters[0])} to ${fmtSem(t.semesters[t.semesters.length - 1])}` : ""}>
                {changes.length === 0 ? (
                  <p className="small">This group needs at least two semesters with enough responses.</p>
                ) : (
                  <div className="tablewrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Theme</th><th className="r">Net before</th><th className="r">Net after</th>
                          <th className="r">Change</th><th className="r">Evidence (z)</th><th>Verdict</th><th>Latest semester</th>
                        </tr>
                      </thead>
                      <tbody>
                        {changes.map((c) => {
                          const l = latest[c.series];
                          return (
                            <tr key={c.series}>
                              <td style={{ textTransform: "capitalize" }}>
                                <i className="sw" style={{ background: themeColor(c.series) }} />{seriesLabel(c.series)}
                              </td>
                              <td className="r num">{fmtNet(c.from_net)}</td>
                              <td className="r num">{fmtNet(c.to_net)}</td>
                              <td className="r num">{fmtNet(c.delta)}</td>
                              <td className="r num">{c.z ?? "–"}</td>
                              <td><Badge direction={c.direction} significant={c.significant} /></td>
                              <td>{l ? <Badge direction={l.direction} significant={l.significant} /> : <span className="small">–</span>}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="small" style={{ marginTop: 12 }}>
                  With about nine series checked per group, one or two flags will appear by chance alone. Treat a single flagged
                  theme as a prompt to read the comments, not as proof.
                </p>
              </Panel>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
