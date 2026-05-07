"""
fetch_data.py — Hämtar SBL Dam-matchdata från FIBA LiveStats.

Vad scriptet gör:
  1. Går igenom alla SBL Dam-säsonger (2021–2025).
  2. För varje säsong hämtar det schemasidan från Genius Sports
     och plockar ut alla match-ID som finns där.
  3. För varje match laddas en JSON-fil ner från FIBA LiveStats
     med fullständig matchstatistik (per spelare, per kvart, m.m.).
  4. Allt sparas i en SQLite-databasfil ("sbl.db") i samma mapp.

Scriptet är "resumable" — om du avbryter och kör igen så
hoppar det över matcher som redan är hämtade.

Det använder bara standardbibliotek i Python (urllib, sqlite3, re,
json, time, argparse). Inga pip install behövs.

Körs i terminalen:
    python3 fetch_data.py              # hämtar allt
    python3 fetch_data.py --limit 5    # bara 5 matcher per säsong (för test)
    python3 fetch_data.py --season 2025  # bara en säsong
"""

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# -----------------------------------------------------------------------------
# Konfiguration
# -----------------------------------------------------------------------------

# competition_id för SBL Dam per säsong (från Genius Sports).
# Hittade via https://hosted.dcd.shared.geniussports.com/SBF/en/competition/{id}/statistics/team
SEASONS = {
    2017: 17548,
    2018: 20995,
    2019: 24009,
    2020: 27660,
    2021: 30967,
    2022: 34105,
    2023: 36406,
    2024: 39557,
    2025: 42013,
}

# URL-mönster
SCHEDULE_URL = "https://hosted.dcd.shared.geniussports.com/SBF/en/competition/{cid}/schedule"
MATCH_DATA_URL = "https://fibalivestats.dcd.shared.geniussports.com/data/{mid}/data.json"

# Vänta lite mellan anrop så vi inte hamrar deras servrar
DELAY_BETWEEN_MATCHES = 0.4  # sekunder

# Var databasen sparas (samma mapp som scriptet)
DB_PATH = Path(__file__).parent / "sbl.db"

# Header som ser ut att komma från en riktig webbläsare. Genius Sports
# blockerar förfrågningar med okända User-Agents, så vi måste låtsas vara
# Chrome.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}

# -----------------------------------------------------------------------------
# Databas
# -----------------------------------------------------------------------------
#
# Om identifierare:
#   - player_key  = "förnamn|efternamn" (lowercase, trimmat) — vår
#                   interna spelar-ID. Två spelare med exakt samma
#                   namn hamnar i samma rad, vilket är väldigt
#                   sällsynt i SBL Dam. Vi kan förfina senare.
#   - team_name   = lagnamn som det står i data.json (ren text).
#   - match_id    = FIBA LiveStats interna match-ID (heltal).

SCHEMA = """
CREATE TABLE IF NOT EXISTS seasons (
    competition_id INTEGER PRIMARY KEY,
    year INTEGER,
    league_name TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    team_name TEXT PRIMARY KEY,
    short_name TEXT,
    code TEXT,
    logo_url TEXT
);

CREATE TABLE IF NOT EXISTS players (
    player_key TEXT PRIMARY KEY,
    first_name TEXT,
    family_name TEXT,
    photo_url TEXT,
    playing_position TEXT,
    shirt_number TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    match_id INTEGER PRIMARY KEY,
    competition_id INTEGER,
    season_year INTEGER,
    match_date TEXT,        -- "Sep 27, 2025, 4:00 PM"
    parsed_date TEXT,       -- "2025-09-27" (ISO-format, för korrekt sortering)
    venue TEXT,
    status TEXT,            -- COMPLETE / LIVE / SCHEDULED / CANCELLED
    home_team TEXT,
    away_team TEXT,
    home_score INTEGER,
    away_score INTEGER,
    attendance INTEGER,
    raw_json TEXT,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id INTEGER,
    player_key TEXT,
    team_name TEXT,
    is_starter INTEGER,
    minutes TEXT,
    fg_made INTEGER, fg_att INTEGER, fg_pct REAL,
    three_made INTEGER, three_att INTEGER, three_pct REAL,
    two_made INTEGER, two_att INTEGER, two_pct REAL,
    ft_made INTEGER, ft_att INTEGER, ft_pct REAL,
    rebounds_def INTEGER, rebounds_off INTEGER, rebounds_total INTEGER,
    assists INTEGER, turnovers INTEGER, steals INTEGER,
    blocks INTEGER, blocks_received INTEGER,
    fouls_personal INTEGER, fouls_drawn INTEGER,
    points INTEGER,
    points_second_chance INTEGER, points_fast_break INTEGER, points_in_paint INTEGER,
    plus_minus INTEGER,
    PRIMARY KEY (match_id, player_key)
);

CREATE TABLE IF NOT EXISTS match_pbp (
    match_id INTEGER PRIMARY KEY,
    pbp_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_pms_player ON player_match_stats (player_key);
CREATE INDEX IF NOT EXISTS idx_pms_team ON player_match_stats (team_name);
CREATE INDEX IF NOT EXISTS idx_matches_season ON matches (season_year);
"""


def parse_match_date(date_str):
    """Tolka FIBA:s datumformat till ISO-datum (ÅÅÅÅ-MM-DD).

    Indata ser ut som "Sep 27, 2025, 4:00 PM".
    Returnerar "2025-09-27", eller None om strängen inte kan tolkas.
    """
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%b %d, %Y, %I:%M %p")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def open_db():
    """Öppna (och initiera) databasen."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)

    # Lägg till parsed_date om databasen är äldre och saknar kolumnen.
    # (ALTER TABLE ADD COLUMN misslyckas om kolumnen redan finns, därav try/except.)
    try:
        conn.execute("ALTER TABLE matches ADD COLUMN parsed_date TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # kolumnen finns redan

    # Fyll i parsed_date för befintliga rader som saknar värdet.
    rows = conn.execute(
        "SELECT match_id, match_date FROM matches WHERE parsed_date IS NULL AND match_date IS NOT NULL"
    ).fetchall()
    if rows:
        print(f"Migrerar datum för {len(rows)} befintliga matcher…")
        for match_id, match_date in rows:
            parsed = parse_match_date(match_date)
            if parsed:
                conn.execute(
                    "UPDATE matches SET parsed_date = ? WHERE match_id = ?",
                    (parsed, match_id),
                )
        conn.commit()
        print("  Klart.")

    return conn


# -----------------------------------------------------------------------------
# HTTP-hjälpare
# -----------------------------------------------------------------------------

def http_get(url):
    """Hämta en URL och returnera innehållet som text."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


# -----------------------------------------------------------------------------
# Parser för schemasidan
# -----------------------------------------------------------------------------

# Varje matchblock börjar med <div class="match-wrap STATUS_X" id="extfix_NNN">.
# Vi avgränsar blocket genom nästa matchblock-start (eller dokumentslutet).

MATCH_WRAP_RE = re.compile(
    r'<div\s+class\s*=\s*"match-wrap\s+STATUS_(?P<status>\w+)"\s+id\s*=\s*"extfix_(?P<mid>\d+)"',
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r'<div class="match-time">.*?<span>(?P<date>[^<]+)</span>',
    re.DOTALL,
)
VENUE_RE = re.compile(
    r'class="venuename"[^>]*>(?P<venue>[^<]+)</a>',
)


def parse_schedule(html):
    """Plocka ut alla matcher ur schemasidans HTML.

    Returnerar en lista med dicts: {match_id, status, date, venue}.
    """
    matches = []
    starts = list(MATCH_WRAP_RE.finditer(html))
    for i, m in enumerate(starts):
        block_start = m.start()
        block_end = starts[i + 1].start() if i + 1 < len(starts) else len(html)
        block = html[block_start:block_end]

        date_m = DATE_RE.search(block)
        venue_m = VENUE_RE.search(block)

        matches.append({
            "match_id": int(m.group("mid")),
            "status": m.group("status"),
            "date": date_m.group("date").strip() if date_m else None,
            "venue": venue_m.group("venue").strip() if venue_m else None,
        })
    return matches


# -----------------------------------------------------------------------------
# Hjälpare
# -----------------------------------------------------------------------------

def _int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def _float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def make_player_key(player):
    """Bygg en stabil nyckel från spelarens namn."""
    fn = (player.get("firstName") or "").strip().lower()
    ln = (player.get("familyName") or "").strip().lower()
    if not fn and not ln:
        return None
    return f"{fn}|{ln}"


# -----------------------------------------------------------------------------
# PBP-extraktion (används vid sparning och migration)
# -----------------------------------------------------------------------------

_PBP_INCLUDE = {
    "2pt", "3pt", "freethrow", "rebound", "steal", "turnover",
    "block", "foul", "substitution", "timeout",
}


def extract_pbp(data):
    """Extrahera play-by-play ur ett FIBA-matchobjekt.

    Returnerar None om matchen saknar PBP-data, annars en dict
    {"t1": str, "t2": str, "ev": [[period, gt, tno, at, sub, ok, s1, s2, fn, ln], ...]}.
    """
    raw_events = data.get("pbp") or []
    if not raw_events:
        return None
    tm_raw = data.get("tm") or {}
    if isinstance(tm_raw, dict):
        tm_vals = list(tm_raw.values())
    else:
        tm_vals = list(tm_raw)
    t1 = tm_vals[0].get("name", "") if len(tm_vals) > 0 else ""
    t2 = tm_vals[1].get("name", "") if len(tm_vals) > 1 else ""
    events = []
    for ev in reversed(raw_events):  # rådata är omvänd kronologisk ordning
        at = ev.get("actionType", "")
        if at not in _PBP_INCLUDE:
            continue
        if ev.get("subType") == "offensivedeadball":
            continue
        events.append([
            ev.get("period", 0),
            ev.get("gt", ""),
            ev.get("tno", 0),
            at,
            ev.get("subType", ""),
            ev.get("success", 0),
            ev.get("s1", 0),
            ev.get("s2", 0),
            ev.get("firstName") or ev.get("internationalFirstName") or "",
            ev.get("familyName") or ev.get("internationalFamilyName") or "",
        ])
    if not events:
        return None
    return {"t1": t1, "t2": t2, "ev": events}


# -----------------------------------------------------------------------------
# Spara en match i databasen
# -----------------------------------------------------------------------------

def save_match(conn, match_id, competition_id, season_year, schedule_info, data):
    cur = conn.cursor()

    home = data.get("tm", {}).get("1", {}) or {}
    away = data.get("tm", {}).get("2", {}) or {}

    # Lag — spara/uppdatera grundinfo
    for team in (home, away):
        name = team.get("name") or team.get("nameInternational")
        if not name:
            continue
        cur.execute(
            """INSERT OR REPLACE INTO teams (team_name, short_name, code, logo_url)
               VALUES (?, ?, ?, ?)""",
            (
                name,
                team.get("shortName"),
                team.get("code"),
                team.get("logo"),
            ),
        )

    # Match-rad (raw_json sparas ej längre — PBP hanteras separat)
    match_date = schedule_info.get("date")
    cur.execute(
        """INSERT OR REPLACE INTO matches (
              match_id, competition_id, season_year, match_date, parsed_date, venue,
              status, home_team, away_team, home_score, away_score,
              attendance, raw_json, fetched_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, datetime('now'))""",
        (
            match_id,
            competition_id,
            season_year,
            match_date,
            parse_match_date(match_date),
            schedule_info.get("venue"),
            schedule_info.get("status"),
            home.get("name"),
            away.get("name"),
            _int(home.get("score") or home.get("full_score")),
            _int(away.get("score") or away.get("full_score")),
            _int(data.get("attendance")),
        ),
    )

    # Play-by-play
    pbp = extract_pbp(data)
    if pbp:
        cur.execute(
            "INSERT OR REPLACE INTO match_pbp (match_id, pbp_json) VALUES (?, ?)",
            (match_id, json.dumps(pbp, separators=(",", ":"), ensure_ascii=False)),
        )

    # Spelare och deras matchstatistik
    for team in (home, away):
        team_name = team.get("name")
        players = team.get("pl") or {}
        for slot, p in players.items():
            key = make_player_key(p)
            if not key:
                continue

            # Spelarinfo (skriv över med senaste — namn/foto kan ändras)
            cur.execute(
                """INSERT OR REPLACE INTO players (
                       player_key, first_name, family_name, photo_url,
                       playing_position, shirt_number
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    p.get("firstName"),
                    p.get("familyName"),
                    p.get("photoT") or p.get("photoS"),
                    p.get("playingPosition"),
                    p.get("shirtNumber"),
                ),
            )

            # Per-match-statistik
            cur.execute(
                """INSERT OR REPLACE INTO player_match_stats (
                       match_id, player_key, team_name, is_starter, minutes,
                       fg_made, fg_att, fg_pct,
                       three_made, three_att, three_pct,
                       two_made, two_att, two_pct,
                       ft_made, ft_att, ft_pct,
                       rebounds_def, rebounds_off, rebounds_total,
                       assists, turnovers, steals,
                       blocks, blocks_received,
                       fouls_personal, fouls_drawn,
                       points,
                       points_second_chance, points_fast_break, points_in_paint,
                       plus_minus
                   ) VALUES (?, ?, ?, ?, ?,
                             ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                             ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    match_id,
                    key,
                    team_name,
                    1 if str(p.get("starter") or "").strip() in ("1", "true", "True") else 0,
                    p.get("sMinutes"),
                    _int(p.get("sFieldGoalsMade")), _int(p.get("sFieldGoalsAttempted")), _float(p.get("sFieldGoalsPercentage")),
                    _int(p.get("sThreePointersMade")), _int(p.get("sThreePointersAttempted")), _float(p.get("sThreePointersPercentage")),
                    _int(p.get("sTwoPointersMade")), _int(p.get("sTwoPointersAttempted")), _float(p.get("sTwoPointersPercentage")),
                    _int(p.get("sFreeThrowsMade")), _int(p.get("sFreeThrowsAttempted")), _float(p.get("sFreeThrowsPercentage")),
                    _int(p.get("sReboundsDefensive")), _int(p.get("sReboundsOffensive")), _int(p.get("sReboundsTotal")),
                    _int(p.get("sAssists")), _int(p.get("sTurnovers")), _int(p.get("sSteals")),
                    _int(p.get("sBlocks")), _int(p.get("sBlocksReceived")),
                    _int(p.get("sFoulsPersonal")), _int(p.get("sFoulsOn")),
                    _int(p.get("sPoints")),
                    _int(p.get("sPointsSecondChance")), _int(p.get("sPointsFastBreak")), _int(p.get("sPointsInThePaint")),
                    _int(p.get("sPlusMinusPoints")),
                ),
            )

    conn.commit()


# -----------------------------------------------------------------------------
# Huvudslinga
# -----------------------------------------------------------------------------

def run(seasons_to_fetch, limit_per_season=None):
    conn = open_db()

    for year, cid in seasons_to_fetch:
        conn.execute(
            "INSERT OR REPLACE INTO seasons (competition_id, year, league_name) VALUES (?, ?, ?)",
            (cid, year, "Damer - SBL Dam"),
        )
    conn.commit()

    already_have = set(row[0] for row in conn.execute("SELECT match_id FROM matches"))
    print(f"Har sedan tidigare {len(already_have)} matcher i databasen.")

    total_new = 0
    total_failed = 0

    for year, cid in seasons_to_fetch:
        print(f"\n=== Säsong {year} (competition_id {cid}) ===")
        try:
            html = http_get(SCHEDULE_URL.format(cid=cid))
        except Exception as e:
            print(f"  Kunde inte hämta schema för {year}: {e}")
            continue

        schedule = parse_schedule(html)
        completed = [m for m in schedule if m["status"] == "COMPLETE"]
        print(f"  Schema: {len(schedule)} matcher totalt, {len(completed)} färdigspelade.")

        # Om parsern inte hittade några matcher: spara HTML:en så vi kan
        # se vad servern faktiskt svarade med. Då blir det enkelt att
        # diagnostisera vad som är fel.
        if len(schedule) == 0:
            debug_path = Path(__file__).parent / f"debug_schedule_{year}.html"
            debug_path.write_text(html, encoding="utf-8")
            print(f"  ⚠ Hittade inga matcher i schemat. Sparade rådata till {debug_path.name} (storlek: {len(html)} tecken)")

        to_fetch = [m for m in completed if m["match_id"] not in already_have]
        if limit_per_season:
            to_fetch = to_fetch[:limit_per_season]
        print(f"  Att hämta nu: {len(to_fetch)} matcher")

        for i, info in enumerate(to_fetch, 1):
            mid = info["match_id"]
            try:
                raw = http_get(MATCH_DATA_URL.format(mid=mid))
                data = json.loads(raw)
                save_match(conn, mid, cid, year, info, data)
                total_new += 1
                print(f"  [{i}/{len(to_fetch)}] match {mid} — {info.get('date','?')} ✓")
            except urllib.error.HTTPError as e:
                print(f"  [{i}/{len(to_fetch)}] match {mid} — HTTP-fel {e.code}")
                total_failed += 1
            except Exception as e:
                print(f"  [{i}/{len(to_fetch)}] match {mid} — fel: {e}")
                total_failed += 1

            time.sleep(DELAY_BETWEEN_MATCHES)

    # Visa lite kortfattad statistik om vad som finns i databasen nu
    print("\n--- Databasen efter körning ---")
    for label, query in [
        ("Säsonger",       "SELECT COUNT(*) FROM seasons"),
        ("Lag",            "SELECT COUNT(*) FROM teams"),
        ("Spelare",        "SELECT COUNT(*) FROM players"),
        ("Matcher",        "SELECT COUNT(*) FROM matches"),
        ("Spelar/match-rader", "SELECT COUNT(*) FROM player_match_stats"),
    ]:
        n = conn.execute(query).fetchone()[0]
        print(f"  {label:22s} {n}")

    conn.close()

    print()
    print(f"Klart! Nya matcher hämtade: {total_new}, misslyckade: {total_failed}")
    print(f"Databasen ligger i: {DB_PATH}")


def parse_args():
    p = argparse.ArgumentParser(description="Hämta SBL Dam-matchdata från FIBA LiveStats.")
    p.add_argument(
        "--season",
        type=int,
        help="Hämta bara en säsong (t.ex. --season 2025). Om utelämnad: alla.",
    )
    p.add_argument(
        "--limit",
        type=int,
        help="Hämta max N matcher per säsong (för test). Om utelämnad: alla.",
    )
    return p.parse_args()


def main():
    args = parse_args()

    seasons = list(SEASONS.items())
    if args.season:
        if args.season not in SEASONS:
            print(f"Okänd säsong {args.season}. Tillgängliga: {sorted(SEASONS)}")
            sys.exit(1)
        seasons = [(args.season, SEASONS[args.season])]

    run(seasons, limit_per_season=args.limit)


if __name__ == "__main__":
    main()
