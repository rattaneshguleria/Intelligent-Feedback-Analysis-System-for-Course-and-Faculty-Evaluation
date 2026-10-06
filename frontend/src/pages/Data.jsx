import React, { useRef, useState } from "react";
import { useApi, postJson, uploadCsv } from "../api.js";
import { Async, ErrorBox, Kpi, Panel, Select, fmtSem, useApp } from "../ui.jsx";

const TOPIC_METHODS = [
  { value: "keyword", label: "Keyword (fast, transparent baseline)" },
  { value: "lda", label: "LDA (classic baseline)" },
  { value: "bertopic", label: "BERTopic (main method, slow)" },
];
const SENTIMENT_METHODS = [
  { value: "lexicon", label: "Lexicon (fast)" },
  { value: "vader", label: "VADER (needs vaderSentiment)" },
  { value: "transformer", label: "Transformer (slow)" },
];

function UploadPanel({ onDone }) {
  const inputRef = useRef(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const send = async (file) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await uploadCsv(file));
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="1. Load feedback" hint="CSV upload. Student IDs are hashed and comments scrubbed before anything is stored.">
      <div
        className={`dropzone ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files[0]); }}
      >
        <p style={{ marginBottom: 12 }}>
          {busy ? "Uploading and anonymising…" : "Drop a feedback .csv here, or choose a file."}
        </p>
        <input ref={inputRef} type="file" accept=".csv" hidden onChange={(e) => { send(e.target.files[0]); e.target.value = ""; }} />
        <button className="btn ghost" disabled={busy} onClick={() => inputRef.current?.click()}>Choose CSV</button>
      </div>
      {error && <div style={{ marginTop: 12 }}><ErrorBox message={error} /></div>}
      {result && (
        <div style={{ marginTop: 16 }}>
          <div className="kpis">
            <Kpi label="Loaded" value={result.loaded} sub={`of ${result.rows_total} rows`} />
            <Kpi label="Duplicates skipped" value={result.duplicates} />
            <Kpi label="Too short" value={result.too_short} />
            <Kpi label="Invalid" value={result.invalid} />
          </div>
          {result.flagged_for_review > 0 && (
            <p className="small" style={{ marginTop: 10 }}>
              {result.flagged_for_review} comments were flagged for review and are kept out of quoted examples.
            </p>
          )}
          {Object.keys(result.redactions || {}).length > 0 && (
            <p className="small" style={{ marginTop: 10 }}>
              Personal details removed:{" "}
              {Object.entries(result.redactions).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(", ")}.
            </p>
          )}
          {result.errors?.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary className="small">{result.errors.length} row problems (no comment text shown)</summary>
              <pre className="json">{result.errors.join("\n")}</pre>
            </details>
          )}
        </div>
      )}
    </Panel>
  );
}

function AnalysisPanel({ meta, onDone }) {
  const [topic, setTopic] = useState("keyword");
  const [sentiment, setSentiment] = useState("lexicon");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const slow = topic === "bertopic" || sentiment === "transformer";

  const run = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const q = new URLSearchParams({ topic_method: topic, sentiment_method: sentiment });
      setResult(await postJson(`/analyze?${q}`));
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const sel = meta.selected_runs;
  return (
    <Panel title="2. Run the analysis" hint="Splits comments into clauses, assigns themes, scores sentiment.">
      <div className="controls">
        <Select label="Theme method" value={topic} onChange={setTopic} options={TOPIC_METHODS} />
        <Select label="Sentiment method" value={sentiment} onChange={setSentiment} options={SENTIMENT_METHODS} />
        <button className="btn" disabled={busy} onClick={run}>{busy ? "Running…" : "Run analysis"}</button>
      </div>
      {slow && (
        <p className="small" style={{ marginTop: 10 }}>
          BERTopic and the transformer can take minutes and may time out in the browser. For those, run{" "}
          <code>python -m app.cli analyze --topics bertopic --sentiment transformer</code> in the backend folder, then refresh.
        </p>
      )}
      {error && <div style={{ marginTop: 12 }}><ErrorBox message={error} /></div>}
      {result && (
        <p className="small" style={{ marginTop: 12 }}>
          Done: {result.segmentation?.clauses_created ?? "?"} clauses analysed with the {result.topic_run.method} theme model and {result.sentiment_run.method} sentiment.
          Reports use the preferred method on file (BERTopic, then keyword, then LDA; transformer, then VADER, then lexicon).
        </p>
      )}
      <p className="small" style={{ marginTop: 12 }}>
        {sel
          ? <>Reports currently use {sel.theme_run?.method} themes (run #{sel.theme_run?.id}) and {sel.sentiment_run?.method} sentiment (run #{sel.sentiment_run?.id}).</>
          : "No analysis has been run yet."}
      </p>
      {(meta.topic_runs.length > 0 || meta.sentiment_runs.length > 0) && (
        <p className="small" style={{ marginTop: 6 }}>
          Stored runs, themes: {meta.topic_runs.map((r) => `#${r.id} ${r.method}`).join(", ") || "none"}; sentiment:{" "}
          {meta.sentiment_runs.map((r) => `#${r.id} ${r.method}`).join(", ") || "none"}.
        </p>
      )}
    </Panel>
  );
}

function OfferingsPanel({ reloadKey, faculty }) {
  const names = Object.fromEntries(faculty.map((f) => [f.id, f.name]));
  const state = useApi("/offerings", reloadKey);
  return (
    <Panel title="3. Responses per course offering" hint="Offerings under the minimum are never shown in reports.">
      <Async state={state}>
        {(rows) => (
          <div className="tablewrap">
            <table>
              <thead>
                <tr><th>Semester</th><th>Course</th><th>Faculty</th><th className="r">Enrolled</th><th className="r">Responses</th><th>Status</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.offering_id}>
                    <td>{fmtSem(r.semester)}</td>
                    <td>{r.course_code}</td>
                    <td>{names[r.faculty_id] || r.faculty_id}</td>
                    <td className="r num">{r.enrolled ?? "–"}</td>
                    <td className="r num">{r.responses}</td>
                    <td>{r.reportable ? "Shown" : <span className="badge flat">Hidden: too few responses</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </Panel>
  );
}

export default function Data() {
  const { meta, refresh } = useApp();
  const [reloadKey, setReloadKey] = useState(0);
  const done = () => { setReloadKey((n) => n + 1); refresh(); };

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Data</h1>
          <p>Load student feedback, run the analysis, and check which course offerings have enough responses to be reported.</p>
        </div>
      </div>
      <UploadPanel onDone={done} />
      <AnalysisPanel meta={meta} onDone={done} />
      <OfferingsPanel reloadKey={reloadKey} faculty={meta.faculty} />
    </div>
  );
}
