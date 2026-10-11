# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Vite + React + TypeScript single-page app in `src/web`. In development the Vite dev server proxies API calls to the FastAPI backend (port 8000); in production FastAPI serves the static build. The Streamlit dashboard (`src/frontend`, port 8501) stays alongside, untouched, until the React app is proven.

## Users

One person: the owner of the tool, hunting for a rental apartment (currently Bologna, also nearby towns such as Nonantola). Two situations:

- **At the desk:** writes and tunes search configs, launches runs, reads job logs, edits the preferences file, triages a batch of fresh listings in depth.
- **On the phone, out and about:** checks what the last run found, decides quickly which listings deserve a call or a visit.

## Product Purpose

Scrape Immobiliare.it, Casa.it and Idealista.it on schedules, deduplicate, enrich each listing from its detail page, score it with an LLM against a plain-text preferences file, and optionally push the good ones to Notion. The web app is where the owner explores every run's results, asks the AI follow-up questions about a single listing, launches runs, and creates or edits search configs.

Success: a new listing that matches is spotted and judged within seconds of the run finishing, and nothing that failed (scrape, enrichment, scoring, Notion) is hidden.

## Positioning

Three portals collapsed into one deduplicated feed, judged against the owner's own written criteria (must-haves, nice-to-haves, deal breakers) instead of the portals' filters. The AI explains every score in terms of those criteria and can be questioned about any listing.

## Operating Context

- The rental market is competitive: speed between "listing appears" and "owner calls the agency" matters.
- Listings, areas and vocabulary are Italian (affitto, bilocale, locali, arredato, spese condominiali, classe energetica).
- Preferences live in `preferences.txt` (editable from the app) and drive AI scoring.
- A run takes minutes: search pages, then detail enrichment with stealth Firefox (Camoufox) and optional NordVPN SOCKS5 rotation, then AI scoring, then optional Notion push. Progress is visible only through the job log.
- Schedules are cron-like (days + HH:MM, UTC) per search config, run by APScheduler.
- Notion is the downstream record when enabled; the source portal is always the place to act on a listing.

## Capabilities and Constraints

- Backend: FastAPI + SQLModel/SQLite. Existing routes: `/configs` (CRUD, toggle, `POST /{id}/run`), `/jobs` (list, detail with log, per-job stats, overall stats, delete), `/listings` (filter by config, job, score range, text; Notion push), `/preferences` (read/write), `/sites` (sites + variants, areas, effective config with overrides), `/health`.
- Listing record: title, price, sqm, rooms, area, city, ai_score (0-100), ai_verdict, notion_page_id, scraped_at, plus `raw_json` holding thumbnail, description snippet, raw features, detail fields (description, address, photos, costs, energy class, agency), and the AI's structured fields (rent, size, floor, furnished, available_from, reason, notes).
- AI provider: Anthropic when `ANTHROPIC_API_KEY` is set, else OpenRouter. Per-listing chat with the AI needs a new backend endpoint; it does not exist yet.
- Data is often sparse: detail enrichment can return empty fields, and scoring can fail (verdict `Error`, score 0). The interface must show these states truthfully, never as a real score.
- No authentication: the app runs locally for one user.
- No job cancellation exists in the backend yet.
- Name: **MilHouse** (chosen by the owner on 2026-10-04, replacing "rent-fetch", which is taken). The Python package stays `apt_scrape`.

## Brand Commitments

- Product name: MilHouse (the owner's spelling, capital M and H).
- Interface language: Italian.

## Evidence on Hand

- `data/app.db`: 2 search configs (Bologna - Cirenaica, Nonantola), 3 jobs, 55 real listings from Immobiliare.it with titles, prices, sizes, rooms and portal-CDN thumbnails. Every listing currently carries AI verdict `Error` (provider returned 401), and detail fields are empty. Do not present invented scores or details as real.
- `preferences.txt`: the owner's real criteria (bilocale in Bologna, at least 50 m², furnished, heating, price cap around 1,400 EUR including fees).

## Product Principles

1. **Seconds to a verdict.** Every listing should be judgeable at a glance: price, size, rooms, area, score and the reason behind it.
2. **Failure is visible.** A failed scrape, empty enrichment or scoring error is shown as what it is, never as a low score or an empty cell.
3. **The preferences are the yardstick.** Scores and AI answers are read against the owner's own criteria, and those criteria are one step away.
4. **The portal is where you act.** The app judges and organizes; contacting and visiting happen on the source listing, always one tap away.
5. **Desk for depth, phone for speed.** Configuration and deep triage on desktop; fast review of fresh results on the phone.
