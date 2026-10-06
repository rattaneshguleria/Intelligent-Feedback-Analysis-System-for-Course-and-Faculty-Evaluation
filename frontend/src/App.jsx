import React, { useEffect, useState } from "react";
import { useApi } from "./api.js";
import { AppCtx, ErrorBox, IconLock, Loading } from "./ui.jsx";
import Overview from "./pages/Overview.jsx";
import Reports from "./pages/Reports.jsx";
import Trends from "./pages/Trends.jsx";
import Compare from "./pages/Compare.jsx";
import Evaluation from "./pages/Evaluation.jsx";
import Data from "./pages/Data.jsx";

const PAGES = [
  ["overview", "Overview", Overview],
  ["reports", "Reports", Reports],
  ["trends", "Trends", Trends],
  ["compare", "Compare", Compare],
  ["evaluation", "Evaluation", Evaluation],
  ["data", "Data", Data],
];

function readHash() {
  const name = window.location.hash.replace("#", "");
  return PAGES.some((p) => p[0] === name) ? name : "overview";
}

export default function App() {
  const [page, setPage] = useState(readHash);
  const [params, setParams] = useState({});
  const [reload, setReload] = useState(0);
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("theme") || "auto"; } catch { return "auto"; }
  });
  const metaState = useApi("/meta", reload);

  useEffect(() => {
    const onHash = () => setPage(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("theme", theme); } catch { /* storage unavailable */ }
  }, [theme]);

  const go = (name, nextParams = {}) => {
    setParams(nextParams);
    window.location.hash = name;
    setPage(name);
    window.scrollTo(0, 0);
  };

  const meta = metaState.data;
  const Page = PAGES.find((p) => p[0] === page)[2];
  const noAnalysis = meta && !meta.selected_runs;

  const nextTheme = { auto: "light", light: "dark", dark: "auto" }[theme];

  return (
    <AppCtx.Provider value={{ meta, go, params, refresh: () => setReload((n) => n + 1) }}>
      <div className="shell">
        <aside className="side">
          <div className="brand">
            Course feedback insights
            <small>Themes and sentiment from student comments</small>
          </div>
          <nav className="nav" aria-label="Main">
            {PAGES.map(([id, label]) => (
              <button key={id} aria-current={page === id ? "page" : undefined} onClick={() => go(id)}>
                {label}
              </button>
            ))}
          </nav>
          <div className="side-foot">
            <div className="privacy">
              <IconLock />
              <span>
                Results appear only when at least {meta?.min_group_size ?? 5} students responded.
                Names and IDs are removed before storage.
              </span>
            </div>
            <button className="linkbtn" onClick={() => setTheme(nextTheme)}>
              Appearance: {theme} (switch to {nextTheme})
            </button>
          </div>
        </aside>
        <main className="main">
          {metaState.loading && !meta && <Loading />}
          {metaState.error && <ErrorBox message={metaState.error} />}
          {meta && noAnalysis && page !== "data" && (
            <div className="note warn" style={{ marginBottom: 16 }}>
              <b>No analysis has been run yet.</b> Open{" "}
              <button className="linkbtn" onClick={() => go("data")}>Data</button> to load feedback and run the analysis.
            </div>
          )}
          {meta && <Page key={page} />}
        </main>
      </div>
    </AppCtx.Provider>
  );
}
