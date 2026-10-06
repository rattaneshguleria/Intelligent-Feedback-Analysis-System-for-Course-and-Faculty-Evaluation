import React, { useState } from "react";
import { useApi } from "../api.js";
import { SeriesChips, TrendChart, seriesLabel } from "../charts.jsx";
import {
  Async, Badge, Empty, Kpi, Ledger, Panel, cap, fmtNet, fmtSem, themeColor, useApp,
} from "../ui.jsx";

function headline(trends) {
  const ch = trends.changes.find((c) => c.series === "overall_tone" && c.kind === "latest");
  if (!ch) return { text: "Not enough semesters yet to describe a change.", sub: "" };
  const tone = ch.to_net >= 0.2 ? "mostly positive" : ch.to_net <= -0.2 ? "mostly negative" : "mixed";
  const move = ch.direction === "improved" ? "up" : ch.direction === "declined" ? "down" : "about the same";
  return {
    text: `Student feedback in ${fmtSem(ch.to)} is ${tone}, and ${move} on ${fmtSem(ch.from)}.`,
    sub: `Net sentiment moved from ${fmtNet(ch.from_net)} to ${fmtNet(ch.to_net)} across the institution` +
      (ch.significant ? "; that change is larger than chance would explain." : "; that change is within normal variation."),
  };
}

export default function Overview() {
  const { meta, go } = useApp();
  const latest = meta.semesters[meta.semesters.length - 1];
  const offerings = useApi("/offerings");
  const trends = useApi("/trends/all");
  const faculty = useApi(latest ? `/compare?group_by=faculty&semester=${latest}` : null);
  const [shown, setShown] = useState(["pace", "workload", "clarity"]);
  const toggle = (k) => setShown((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));

  return (
    <div>
      <Async state={trends}>
        {(t) => {
          const h = headline(t);
          return (
            <div className="lede-wrap">
              <h1 className="lede">{h.text}</h1>
              <p>{h.sub}</p>
            </div>
          );
        }}
      </Async>

      <Async state={offerings}>
        {(rows) => {
          const ok = rows.filter((r) => r.reportable);
          const total = ok.reduce((a, r) => a + r.responses, 0);
          const hidden = rows.length - ok.length;
          return (
            <div className="kpis" style={{ marginBottom: 16 }}>
              <Kpi label="Responses analysed" value={total.toLocaleString()} sub="in reportable offerings" />
              <Kpi label="Course offerings" value={rows.length} sub={`${meta.semesters.length} semesters`} />
              <Kpi label="Faculty" value={meta.faculty.length} sub={`${meta.courses.length} courses`} />
              <Kpi label="Hidden for privacy" value={hidden}
                   sub={hidden ? "offerings under the minimum" : "none under the minimum"} />
            </div>
          );
        }}
      </Async>

      <div className="grid2">
        <Panel title={`Themes in ${latest ? fmtSem(latest) : "the latest semester"}`}
               hint="Share positive minus share negative">
          <Async state={trends}>
            {(t) => {
              const rows = Object.entries(t.series)
                .filter(([k]) => k !== "overall_tone")
                .map(([k, pts]) => ({ k, pt: pts.find((p) => p.semester === latest) }))
                .filter((x) => x.pt?.available)
                .map(({ k, pt }) => ({
                  label: k, net: pt.net, n: pt.comments,
                  title: `${cap(k)}: ${fmtNet(pt.net)} from ${pt.comments} students`,
                }))
                .sort((a, b) => b.net - a.net);
              return rows.length ? <Ledger rows={rows} /> : <Empty title="No themes yet">Run the analysis from the Data page.</Empty>;
            }}
          </Async>
        </Panel>

        <Panel title="Faculty snapshot" hint={latest ? `Overall tone, ${fmtSem(latest)}` : ""}>
          <Async state={faculty}>
            {(c) => {
              const rows = c.groups.filter((g) => !g.suppressed)
                .map((g) => ({ label: g.label, net: g.overall_net, n: g.responses, key: g.key,
                               title: `${g.label}: ${fmtNet(g.overall_net)} from ${g.responses} students` }))
                .sort((a, b) => b.net - a.net);
              const hidden = c.groups.filter((g) => g.suppressed).length;
              return (
                <>
                  <Ledger rows={rows} onRowClick={(r) => go("reports", { scope: "faculty", key: r.key })} />
                  {hidden > 0 && <p className="small" style={{ marginTop: 10 }}>{hidden} faculty hidden: fewer than {meta.min_group_size} responses this semester.</p>}
                </>
              );
            }}
          </Async>
        </Panel>
      </div>

      <Panel title="Net sentiment over time" hint="Institution-wide. Pick the themes to show.">
        <Async state={trends}>
          {(t) => (
            <>
              <SeriesChips all={["overall_tone", ...meta.themes.map((x) => x.name)]}
                           active={["overall_tone", ...shown]}
                           onToggle={(k) => k !== "overall_tone" && toggle(k)} />
              <TrendChart semesters={t.semesters} series={t.series} keys={["overall_tone", ...shown]} height={300} />
            </>
          )}
        </Async>
      </Panel>

      <Panel title="Changes worth a look" hint="First semester to latest, where the change is larger than chance">
        <Async state={trends}>
          {(t) => {
            const sig = t.changes.filter((c) => c.kind === "first_to_last" && c.significant && c.series !== "overall_tone");
            if (!sig.length) return <p className="small">No theme has changed by more than chance would explain.</p>;
            return (
              <div className="tablewrap">
                <table>
                  <thead><tr><th>Theme</th><th>Period</th><th className="r">Net before</th><th className="r">Net after</th><th>Verdict</th></tr></thead>
                  <tbody>
                    {sig.map((c) => (
                      <tr key={c.series}>
                        <td style={{ textTransform: "capitalize" }}>
                          <i className="sw" style={{ background: themeColor(c.series) }} />{seriesLabel(c.series)}
                        </td>
                        <td>{fmtSem(c.from)} to {fmtSem(c.to)}</td>
                        <td className="r num">{fmtNet(c.from_net)}</td>
                        <td className="r num">{fmtNet(c.to_net)}</td>
                        <td><Badge direction={c.direction} significant={c.significant} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          }}
        </Async>
      </Panel>
    </div>
  );
}
