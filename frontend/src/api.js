import { useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options) {
  let res;
  try {
    res = await fetch(`${BASE}/api${path}`, options);
  } catch {
    throw new Error("Cannot reach the API. From backend/, run: uvicorn app.main:app --reload");
  }
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* body was not JSON */
    }
    if (detail && typeof detail !== "string") detail = JSON.stringify(detail);
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res;
}

export const getJson = async (path) => (await request(path)).json();
export const getText = async (path) => (await request(path)).text();
export const postJson = async (path) => (await request(path, { method: "POST" })).json();
export const uploadCsv = async (file) => {
  const body = new FormData();
  body.append("file", file);
  return (await request("/ingest", { method: "POST", body })).json();
};

/** Fetch JSON for a path. Pass null to skip the request. */
export function useApi(path, reloadKey = 0) {
  const [state, setState] = useState({ data: null, error: null, loading: Boolean(path) });
  useEffect(() => {
    if (!path) {
      setState({ data: null, error: null, loading: false });
      return undefined;
    }
    let stale = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    getJson(path)
      .then((data) => !stale && setState({ data, error: null, loading: false }))
      .catch((e) => !stale && setState({ data: null, error: e.message, loading: false }));
    return () => {
      stale = true;
    };
  }, [path, reloadKey]);
  return state;
}
