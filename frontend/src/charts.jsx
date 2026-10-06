import React from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { cap, fmtNet, fmtSem, themeColor } from "./ui.jsx";

export function seriesLabel(key) {
  return key === "overall_tone" ? "Overall tone" : cap(key);
}

function TrendTip({ active, payload, label, series }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <b>{fmtSem(label)}</b>
      {payload.map((p) => {
        const pt = series[p.dataKey]?.find((x) => x.semester === label);
        return (
          <div key={p.dataKey}>
            <span><i className="sw" style={{ background: p.stroke }} />{seriesLabel(p.dataKey)}</span>
            <span className="num">{fmtNet(p.value)}{pt?.comments ? ` (${pt.comments} students)` : ""}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Net sentiment per semester. Points a group is too small to show are left as gaps. */
export function TrendChart({ semesters, series, keys, height = 320 }) {
  const data = semesters.map((s) => {
    const row = { semester: s };
    keys.forEach((k) => {
      const pt = series[k]?.find((x) => x.semester === s);
      row[k] = pt && pt.available ? pt.net : null;
    });
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--line)" />
        <XAxis dataKey="semester" tickFormatter={fmtSem} tick={{ fill: "var(--muted)", fontSize: 12 }} stroke="var(--line)" />
        <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]} tick={{ fill: "var(--muted)", fontSize: 12 }}
               stroke="var(--line)" tickFormatter={(v) => (v > 0 ? `+${v}` : v)} width={40} />
        <ReferenceLine y={0} stroke="var(--muted)" strokeOpacity={0.6} />
        <Tooltip content={<TrendTip series={series} />} cursor={{ stroke: "var(--muted)", strokeDasharray: "3 3" }} />
        {keys.map((k) => (
          <Line
            key={k} type="monotone" dataKey={k} connectNulls={false} isAnimationActive={false}
            style={{ stroke: themeColor(k) }} strokeWidth={k === "overall_tone" ? 3 : 2}
            dot={{ r: 4, strokeWidth: 2, stroke: "var(--panel)", style: { fill: themeColor(k) } }}
            activeDot={{ r: 6 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Toggle chips that double as the legend. */
export function SeriesChips({ all, active, onToggle }) {
  return (
    <div className="chips" role="group" aria-label="Series shown on the chart">
      {all.map((k) => (
        <button key={k} className="chip" aria-pressed={active.includes(k)} onClick={() => onToggle(k)}>
          <i className="sw" style={{ background: themeColor(k) }} />
          {seriesLabel(k)}
        </button>
      ))}
    </div>
  );
}
