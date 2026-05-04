# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SBL Dam stats — a player statistics search tool for Swedish women's basketball (SBL Dam). Fetches match data from FIBA LiveStats / Genius Sports, stores it in SQLite, and serves it as a static single-page app via GitHub Pages.

No external pip packages are used anywhere — only Python stdlib (urllib, sqlite3, json, re, html, argparse).

## Running locally

```bash
# Fetch all match data (resumable — skips already-fetched matches)
python3 fetch_data.py

# Fetch only one season or limit matches per season (for testing)
python3 fetch_data.py --season 2025
python3 fetch_data.py --limit 5

# Option A: dynamic local server (reads live from sbl.db)
python3 server.py
# → http://localhost:8000

# Option B: export to static JSON, then serve static files
python3 export_static.py
cd docs && python3 -m http.server 8001
# → http://localhost:8001
```

## Architecture

Three Python scripts + one HTML file form the whole system:

- **`fetch_data.py`** — scrapes schedule HTML from Genius Sports, downloads per-match JSON from FIBA LiveStats, parses player stats, and writes everything into `sbl.db` (SQLite). Keyed by `player_key = "firstname|lastname"` (lowercase).

- **`export_static.py`** — reads `sbl.db` and writes `docs/data.json`. Stats rows are serialised as arrays (not objects) for compactness; the field order is defined by `STAT_FIELDS` at the top of this file.

- **`server.py`** — a minimal `http.server`-based web server that queries `sbl.db` directly and renders HTML with f-strings. Used for local development only.

- **`docs/index.html`** — the entire frontend: one self-contained HTML file with all CSS and JS inlined. In production (GitHub Pages) it reads `docs/data.json`.

**Critical coupling:** `STAT_FIELDS` in `export_static.py` and the array-index constants in `docs/index.html` must stay in sync. If you add, remove, or reorder fields in `STAT_FIELDS`, update the corresponding index lookups in `index.html`.

## Automation

GitHub Actions (`.github/workflows/update.yml`) runs daily at 04:00 UTC:
1. Restores `sbl.db` from cache (key: `sbl-db-v1`)
2. Runs `fetch_data.py`
3. Runs `export_static.py`
4. Commits and pushes `docs/data.json` if changed

`sbldamstats/` is a separate git repo (subdirectory) that mirrors the published version on GitHub Pages.

## Data source

- Schedule HTML: `https://hosted.dcd.shared.geniussports.com/SBF/en/competition/{id}/schedule`
- Match JSON: `https://fibalivestats.dcd.shared.geniussports.com/data/{matchId}/data.json`

Season competition IDs are hardcoded in `SEASON` dict at the top of `fetch_data.py`. Data goes back to 2021; earlier seasons were not reported to FIBA LiveStats.

## Known limitations (see IDEER.md for full backlog)

- `player_key` is `firstname|lastname` — two players with identical names would collide.
- Matches are sorted by `match_id` as a proxy for date, not actual parsed date.
- `raw_json` column in `matches` table holds the full FIBA payload and accounts for ~99% of `sbl.db`'s 372 MB. It's never read after initial parse and could be dropped.
- Team names are not normalised — the same club appears under multiple names across seasons.
