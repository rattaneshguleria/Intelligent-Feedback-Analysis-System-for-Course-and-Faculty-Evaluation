import React, { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useApi } from "../api.js";
import { Async, Panel, Select, cap } from "../ui.jsx";

const f3 = (n) => (n == null ? "–" : n.toFixed(3));

function MethodChart({ runs }) {
  const data = runs.map((r) => ({ method: r.method, Accuracy: r.accuracy, "Macro F1": r.macro_f1 }));
  return (
    <>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis dataKey="method" tick={{ fill: "var(--muted)", fontSize: 12 }} stroke="var(--line)" />
          <YAxis domain={[0, 1]} tick={{ fill: "var(--muted)", fontSize: 12 }} stroke="var(--line)" width={36} />
          <Tooltip formatter={(v) => v.toFixed(3)} cursor={{ fill: "var(--soft)" }}
                   contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }} />
          <Bar dataKey="Accuracy" fill="var(--c1)" radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false} />
          <Bar dataKey="Macro F1" fill="var(--c2)" radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
      <div className="legend">
        <span><i className="sw" style={{ background: "var(--c1)" }} />Accuracy</span>
        <span><i className="sw" style={{ background: "var(--c2)" }} />Macro F1</span>
      </div>
    </>
  );
}

function RunTable({ runs, extra }) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th>Method</th><th className="r">Clauses</th><th className="r">Accuracy</th>
            <th className="r">Macro F1</th><th className="r">Weighted F1</th>
            {extra.map(([, l]) => <th key={l} className="r">{l}</th>)}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id}>
              <td>{r.method}</td><td className="r num">{r.n}</td>
              <td className="r num">{f3(r.accuracy)}</td><td className="r num">{f3(r.macro_f1)}</td>
              <td className="r num">{f3(r.weighted_f1)}</td>
              {extra.map(([k]) => <td key={k} className="r num">{f3(r[k])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Confusion({ run }) {
  const labels = Object.keys(run.confusion);
  return (
    <div className="tablewrap">
      <table className="cm">
        <thead>
          <tr><th className="lbl">Actual, then predicted</th>{labels.map((l) => <th key={l} style={{ textTransform: "capitalize" }}>{cap(l)}</th>)}</tr>
        </thead>
        <tbody>
          {labels.map((a) => {
            const total = labels.reduce((s, p) => s + (run.confusion[a][p] || 0), 0) || 1;
            return (
              <tr key={a}>
                <td className="lbl" style={{ textTransform: "capitalize" }}>{cap(a)}</td>
                {labels.map((p) => {
                  const v = run.confusion[a][p] || 0;
                  return (
                    <td key={p} className={`num ${a === p ? "diag" : ""}`}
                        style={{ background: `color-mix(in srgb, var(--pos) ${Math.round((v / total) * 70)}%, transparent)` }}
                        title={`${cap(a)} predicted as ${cap(p)}: ${v} of ${total}`}>
                      {v || ""}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PerClass({ run }) {
  return (
    <div className="tablewrap">
      <table>
        <thead><tr><th>Class</th><th className="r">Precision</th><th className="r">Recall</th><th className="r">F1</th><th className="r">Clauses</th></tr></thead>
        <tbody>
          {Object.entries(run.per_class).map(([k, v]) => (
            <tr key={k}>
              <td style={{ textTransform: "capitalize" }}>{cap(k)}</td>
              <td className="r num">{f3(v.precision)}</td><td className="r num">{f3(v.recall)}</td>
              <td className="r num">{f3(v.f1)}</td><td className="r num">{v.support}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Evaluation() {
  const ev = useApi("/evaluation");
  const [pick, setPick] = useState("");

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Evaluation</h1>
          <p>How closely each topic and sentiment method agrees with labelled clauses. This is the evidence for choosing one method over another.</p>
        </div>
      </div>

      <Async state={ev}>
        {(e) => {
          const all = [
            ...e.theme_runs.map((r) => ({ ...r, kind: "Theme" })),
            ...e.sentiment_runs.map((r) => ({ ...r, kind: "Sentiment" })),
          ];
          const options = all.map((r) => ({ value: `${r.kind}-${r.run_id}`, label: `${r.kind}: ${r.method}` }));
          const sel = all.find((r) => `${r.kind}-${r.run_id}` === pick) || all[0];
          return (
            <div className="stack">
              <div className="note warn">
                <b>Read these numbers with care.</b> Scores come from {e.gold_source} ({e.gold_clauses} labelled clauses of {e.total_clauses}).
                Synthetic comments reuse the vocabulary of the keyword and lexicon methods, so those scores are upper bounds.
                Hand-label about 300 real clauses (CLI: <code>export-sample</code>) before quoting accuracy in a report.
              </div>

              <div className="grid2">
                <Panel title="Theme detection" hint="Higher is better, 0 to 1">
                  <MethodChart runs={e.theme_runs} />
                </Panel>
                <Panel title="Sentiment" hint="Higher is better, 0 to 1">
                  <MethodChart runs={e.sentiment_runs} />
                </Panel>
              </div>

              <Panel title="Theme methods in detail">
                <RunTable runs={e.theme_runs} extra={[["purity", "Topic purity"], ["topic_coherence_npmi", "Coherence (NPMI)"]]} />
                <p className="small" style={{ marginTop: 10 }}>Coherence shows a dash for methods that do not produce word-level topics.</p>
              </Panel>

              <Panel title="Sentiment methods in detail">
                <RunTable runs={e.sentiment_runs} extra={[["rating_spearman", "Correlation with star rating"]]} />
              </Panel>

              <Panel title="Where a method goes wrong" hint="Rows are the true label, columns what the method predicted">
                <div className="controls" style={{ marginBottom: 14 }}>
                  <Select label="Method" value={sel ? `${sel.kind}-${sel.run_id}` : ""} onChange={setPick} options={options} />
                </div>
                {sel && (
                  <div className="stack">
                    <Confusion run={sel} />
                    <PerClass run={sel} />
                  </div>
                )}
              </Panel>
            </div>
          );
        }}
      </Async>
    </div>
  );
}
