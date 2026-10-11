# MilHouse (React web app)

The single-page app for the scraper: listings feed, certificate, map, compare,
runs and search configs. It talks to the FastAPI backend in `src/backend`
under `/api`.

## Develop

```bash
npm install
npm run dev
```

The Vite dev server proxies `/api` to `BACKEND_URL` (default
`http://localhost:8000`). Export `BACKEND_URL` in the shell to point it
elsewhere: Vite does not read the repo-root `.env`.

## Build

```bash
npx tsc -b --noEmit && npm run build
```

The build writes `dist/`, which FastAPI serves at `/` (override the location
with `WEB_DIST_DIR`). `npm run lint` runs Oxlint.
