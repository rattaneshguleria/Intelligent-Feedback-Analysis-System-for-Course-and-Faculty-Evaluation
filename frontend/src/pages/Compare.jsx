import React, { useState } from "react";
import { useApi } from "../api.js";
import { Async, Panel, Segmented, Select, fmtNet, fmtSem, netTint, cap, useApp } from "../ui.jsx";

export default function Compare() {
  const { meta, go } = useApp();
  const [groupBy, setGroupBy] = useState("faculty");
  const [semester, setSemester] = useState(meta.semesters[meta.semesters.length - 1] || "");
  const [department, setDepartment] = useState("");

  const q = new URLSearchParams({ group_by: groupBy });
  if (semester) q.set("semester", semester);
  if (department) q.set("department", department);
  const cmp = useApi(`/compare?${q}`);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Compare</h1>
          <p>Net sentiment for each faculty member or course, theme by theme. Blue cells are more positive than negative, orange the reverse. Cells are left blank when too few students raised the theme.</p>
        </div>
      </div>

      <div className="controls" style={{ marginBottom: 20 }}>
        <Segmented label="Compare by" value={groupBy} onChange={setGroupBy}
                   options={[{ value: "faculty", label: "Faculty" }, { value: "course", label: "Course" }]} />
        <Select label="Semester" value={semester} onChange={setSemester}
                options={[{ value: "", label: "All semesters" }, ...meta.semesters.map((s) => ({ value: s, label: fmtSem(s) }))]} />
        <Select label="Department" value={department} onChange={setDepartment}
                options={[{ value: "", label: "All departments" }, ...meta.departments.map((d) => ({ value: d, label: d }))]} />
      </div>

      <Async state={cmp}>
        {(c) => {
          const groups = [...c.groups].sort((a, b) => (b.overall_net ?? -9) - (a.overall_net ?? -9));
          const themes = c.themes;
          const scopeName = groupBy === "faculty" ? "faculty" : "course";
          return (
            <Panel title={`All ${scopeName}`} hint="Sorted by overall tone. Select a row to open its report.">
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>
                      <th>{groupBy === "faculty" ? "Faculty" : "Course"}</th>
                      <th className="r">Students</th>
                      <th className="cell">Overall tone</th>
                      {themes.map((t) => <th key={t} className="cell" style={{ textTransform: "capitalize" }}>{cap(t)}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((g) =>
                      g.suppressed ? (
                        <tr key={g.key} className="muted">
                          <td>{g.label}</td>
                          <td colSpan={themes.length + 2}>Hidden: fewer than {c.min_group_size} responses</td>
                        </tr>
                      ) : (
                        <tr key={g.key} className="click"
                            onClick={() => go("reports", { scope: groupBy, key: g.key })}>
                          <td>{g.label}<div className="small">{g.department}</div></td>
                          <td className="r num">{g.responses}</td>
                          <td className="cell num" style={{ background: netTint(g.overall_net) }}>{fmtNet(g.overall_net)}</td>
                          {themes.map((t) => {
                            const v = g.themes?.[t];
                            return v ? (
                              <td key={t} className="cell num" style={{ background: netTint(v.net) }}
                                  title={`${cap(t)}: ${fmtNet(v.net)} from ${v.comments} students`}>
                                {fmtNet(v.net)}<small>{v.comments}</small>
                              </td>
                            ) : (
                              <td key={t} className="cell-hidden" title="Too few students raised this theme">–</td>
                            );
                          })}
                        </tr>
                      )
                    )}
                    {c.baseline && (
                      <tr style={{ fontWeight: 600 }}>
                        <td>All {scopeName} combined</td>
                        <td className="r num">{c.baseline.responses}</td>
                        <td className="cell num" style={{ background: netTint(c.baseline.overall_net) }}>{fmtNet(c.baseline.overall_net)}</td>
                        {themes.map((t) => {
                          const v = c.baseline.themes?.[t];
                          return v ? (
                            <td key={t} className="cell num" style={{ background: netTint(v.net) }}>
                              {fmtNet(v.net)}<small>{v.comments}</small>
                            </td>
                          ) : <td key={t} className="cell-hidden">–</td>;
                        })}
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="small" style={{ marginTop: 10 }}>Small figure under each score is the number of students who raised that theme.</p>
            </Panel>
          );
        }}
      </Async>
    </div>
  );
}
