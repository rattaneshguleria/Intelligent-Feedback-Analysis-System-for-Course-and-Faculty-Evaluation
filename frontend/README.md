# Dashboard (React + Vite + Recharts)

Pages: Overview, Reports, Trends, Compare, Evaluation, Data (upload CSV + run analysis).

## Run (two terminals)
1. Backend, from `backend/` with `(venv)` active:  `uvicorn app.main:app --reload`
2. Frontend, from `frontend/`:  `npm install` then `npm run dev`  -> open http://localhost:5173

The dev server proxies `/api` to http://127.0.0.1:8000, so no CORS setup is needed.
Before the first view, run the analysis once: `python -m app.cli analyze` (or use the Data page).
Production build: `npm run build` (output in `dist/`; set `VITE_API_URL` if the API is on another host).
