# arbiter — web

The Arbiter demo frontend: paste a comment → a **ruling** with per-category
severities, highlighted offending spans, and gray-area context flags.

Stack: **React + Vite + TypeScript + Ant Design**. Ported from the `variant-b`
"Verdict / Document" mockup (dark judicial console, IBM Plex fonts).

## Run

```bash
npm install
npm run dev          # http://localhost:5173
```

The app calls `POST /api/moderate`. In dev, Vite proxies `/api` → the FastAPI
backend (default `http://127.0.0.1:8000`; override with `VITE_API_TARGET`).

Start the backend separately, e.g.:

```bash
# from the repo root
uvicorn arbiter.api.main:app --reload
```

**Offline / no backend?** The engine falls back to a deterministic mock
(curated sample verdicts + a heuristic generator), so the UI is fully
demoable with zero setup. The masthead dot shows `live` vs `mock`.

## Scripts

- `npm run dev` — dev server with API proxy
- `npm run build` — typecheck + production build to `dist/`
- `npm run preview` — serve the production build
- `npm run lint` — typecheck only (`tsc --noEmit`)

## Layout

```
src/
  main.tsx              # entry + antd dark ConfigProvider
  App.tsx               # the VariantB page (masthead, submission, ruling slot)
  store.ts              # shared store (useSyncExternalStore)
  components/
    Ruling.tsx          # ruling: statement, evidence, findings, gray-area notes
    Evidence.tsx        # comment with highlighted spans (antd Tooltip on hover)
  lib/
    engine.ts           # categories, samples, mock + heuristic, moderate(), segments
    types.ts            # Verdict / Category / ContextFlags / ...
  styles/
    tokens.css          # design tokens (OKLCH surfaces, severity + action scales)
    variant-b.css       # the verdict/document layout
```
