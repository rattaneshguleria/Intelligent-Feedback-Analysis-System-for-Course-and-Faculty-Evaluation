import React, { createContext, useContext } from "react";

export const AppCtx = createContext({ meta: null, go: () => {} });
export const useApp = () => useContext(AppCtx);

/* Fixed colour per theme (never re-assigned when filters change). */
const THEME_SLOT = {
  pace: "--c1", clarity: "--c2", support: "--c3", workload: "--c4",
  assessment: "--c5", engagement: "--c6", resources: "--c7", overall: "--c8",
};
export const themeColor = (name) =>
  name === "overall_tone" ? "var(--ink)" : `var(${THEME_SLOT[name] || "--neu"})`;

export const cap = (s) => (s || "").replace(/_/g, " ");
export const fmtNet = (n) => (n == null ? "–" : `${n > 0 ? "+" : ""}${n.toFixed(2)}`);
export const pct = (n) => (n == null ? "–" : `${Math.round(n * 100)}%`);
export const fmtSem = (s) => {
  const [y, t] = (s || "").split("-");
  return t ? `${t} ${y}` : s;
};

/* ---------- small building blocks ---------- */
export function Select({ label, value, onChange, options }) {
  return (
    <label className="field">
      {label}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

export function Segmented({ value, onChange, options, label }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Kpi({ label, value, sub }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="value num">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Panel({ title, hint, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      {(title || hint) && (
        <div className="panel-head">
          {title && <h2>{title}</h2>}
          {hint && <span className="hint">{hint}</span>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Loading() {
  return <div className="skeleton" aria-busy="true" aria-label="Loading" />;
}

export function ErrorBox({ message }) {
  return (
    <div className="note err" role="alert">
      <b>Could not load this view.</b> {message}
    </div>
  );
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

/** Wraps an API state: loading, error, then children(data). */
export function Async({ state, children }) {
  if (state.loading) return <Loading />;
  if (state.error) return <ErrorBox message={state.error} />;
  if (!state.data) return null;
  return children(state.data);
}

export function Suppressed({ reason, min }) {
  return (
    <div className="note warn">
      <b>Hidden to protect anonymity.</b>{" "}
      {reason || `Fewer than ${min} students responded, so no results are shown.`}
    </div>
  );
}

export function Badge({ direction, significant }) {
  if (direction === "improved") return <span className="badge up">▲ Improved</span>;
  if (direction === "declined") return <span className="badge down">▼ Declined</span>;
  return <span className="badge flat">{significant ? "Changed" : "No clear change"}</span>;
}

/* ---------- ledger: one row per theme, bars diverge from zero ---------- */
export function Ledger({ rows, onRowClick }) {
  return (
    <div className="ledger" role="table" aria-label="Net sentiment by theme">
      <div className="ledger-scale">
        <span />
        <span className="axis"><span>← more negative</span><span>more positive →</span></span>
        <span className="ledger-val">Net</span>
        <span className="ledger-n">Students</span>
      </div>
      {rows.map((r) => (
        <div
          key={r.label}
          className={`ledger-row ${onRowClick ? "click" : ""}`}
          role="row"
          title={r.title}
          onClick={onRowClick ? () => onRowClick(r) : undefined}
        >
          <span className="ledger-label">{cap(r.label)}</span>
          <span className="track" aria-hidden="true">
            <span
              className={`bar ${r.net >= 0 ? "pos" : "neg"}`}
              style={{ width: `${Math.min(Math.abs(r.net), 1) * 50}%` }}
            />
          </span>
          <span className="ledger-val num">{fmtNet(r.net)}</span>
          <span className="ledger-n num">{r.n ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

export function SentimentSplit({ positive, neutral, negative }) {
  const parts = [
    ["Positive", positive, "var(--pos)"],
    ["Neutral", neutral, "var(--neu)"],
    ["Negative", negative, "var(--neg)"],
  ];
  return (
    <div>
      <div className="stackbar" role="img" aria-label={parts.map(([n, v]) => `${n} ${pct(v)}`).join(", ")}>
        {parts.map(([n, v, c]) => (
          <span key={n} style={{ flex: Math.max(v || 0, 0.004), background: c }} title={`${n}: ${pct(v)}`} />
        ))}
      </div>
      <div className="legend">
        {parts.map(([n, v, c]) => (
          <span key={n}><i className="sw" style={{ background: c }} />{n} <b className="num">{pct(v)}</b></span>
        ))}
      </div>
    </div>
  );
}

/* Blue for positive, orange for negative, strength scales with |net|. */
export function netTint(net) {
  if (net == null) return "transparent";
  const strength = Math.round(Math.min(Math.abs(net), 1) * 55);
  return `color-mix(in srgb, var(${net >= 0 ? "--pos" : "--neg"}) ${strength}%, transparent)`;
}

export const IconLock = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </svg>
);
