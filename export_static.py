"""
export_static.py — Plocka ut allt ur sbl.db och spara en kompakt JSON
                   som den statiska webbsidan (docs/) kan läsa.

Körs så här (efter fetch_data.py):
    python3 export_static.py

Resultat: docs/data.json
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "sbl.db"
OUT_DIR = ROOT / "docs"
OUT_FILE = OUT_DIR / "data.json"

# Mappar rånamn från databasen (case-insensitivt) till kanoniskt klubbnamn.
# Databasen lämnas orörd — normaliseringen sker bara här vid export.
# Lägg till nya rader om källdatan introducerar fler varianter.
_TEAM_CANON = {
    "a3 basket":                     "A3 Basket Umeå",
    "aik basket":                    "AIK",
    "alviks bbk":                    "Alvik Basket",
    "ik eos":                        "IK Eos",
    "ik eos lund":                   "IK Eos",
    "idrottsklubben eos":            "IK Eos",
    "mark basket":                   "Mark Basket",
    "mark borås":                    "Mark Basket",
    "malbas bbk":                    "Malbas",
    "norrköping dophins":            "Norrköping Dolphins",   # stavfel i källdata
    "norrköpings basketförening":    "Norrköping Dolphins",
    "sbbk dam":                      "Södertälje BBK",
    "södertälje basketbollklubb":    "Södertälje BBK",
    "uppsala basket dam":            "Uppsala Basket",
    "föreningen uppsala basket dam": "Uppsala Basket",
    "visby ladies":                  "Visby Ladies",          # hanterar VISBY LADIES via lower()
    "wetterbygden sparks":           "Wetterbygdens Sparks",
    "sjuhärads basketbollförening":  "Sjuhärads Basket",
    "östersunds basket":             "Östersund Basket",
}


def canonical_team(name):
    """Returnera det kanoniska klubbnamnet, eller originalnamnet om inget finns i mappingen."""
    if not name:
        return name
    # Om inget kanoniskt namn finns: returnera ändå name.strip() så att
    # blanksteg i slutet av strängen (från källdata) alltid städas bort.
    return _TEAM_CANON.get(name.strip().lower(), name.strip())


# Fältordningen i den kompakta "stats"-arrayen. Frontenden använder
# samma ordning för att läsa siffrorna. Om du ändrar något här måste
# motsvarande ändring göras i index.html.
STAT_FIELDS = [
    "match_id",
    "player_key",
    "team_name",
    "is_starter",
    "minutes",
    "fg_made", "fg_att",
    "three_made", "three_att",
    "ft_made", "ft_att",
    "rebounds_def", "rebounds_off",
    "assists",
    "turnovers",
    "steals",
    "blocks",
    "fouls_personal",
    "points",
    "plus_minus",
]


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Hittar inte databasen: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Spelare
    players = []
    for r in conn.execute("""
        SELECT player_key, first_name, family_name, photo_url,
               playing_position, shirt_number
        FROM players
    """):
        players.append({
            "key": r["player_key"],
            "first": r["first_name"] or "",
            "last": r["family_name"] or "",
            "photo": r["photo_url"] or "",
            "pos": r["playing_position"] or "",
            "shirt": r["shirt_number"] or "",
        })

    # Matcher
    matches = []
    for r in conn.execute("""
        SELECT match_id, season_year, match_date, parsed_date, home_team, away_team,
               home_score, away_score, status
        FROM matches
        ORDER BY match_id
    """):
        matches.append({
            "id": r["match_id"],
            "year": r["season_year"],
            "date": r["match_date"] or "",
            "date_parsed": r["parsed_date"] or "",  # ISO-format "2025-09-27", används för sortering
            "home": canonical_team(r["home_team"]),
            "away": canonical_team(r["away_team"]),
            "hs": r["home_score"],
            "as": r["away_score"],
            "status": r["status"] or "",
        })

    # Statistik per spelare/match — som array-av-arrayer för kompakthet
    team_idx = STAT_FIELDS.index("team_name")
    stats = []
    for r in conn.execute(f"""
        SELECT {", ".join(STAT_FIELDS)}
        FROM player_match_stats
    """):
        row = [r[f] for f in STAT_FIELDS]
        row[team_idx] = canonical_team(row[team_idx])
        stats.append(row)

    data = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "season_count": conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0],
            "match_count": len(matches),
            "player_count": len(players),
            "stat_count": len(stats),
        },
        "stat_fields": STAT_FIELDS,
        "players": players,
        "matches": matches,
        "stats": stats,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # separators=(",", ":") ger oss minsta möjliga JSON utan onödiga blanksteg
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = OUT_FILE.stat().st_size / 1024
    print(f"Skrev {OUT_FILE.relative_to(ROOT)}")
    print(f"  {len(players)} spelare, {len(matches)} matcher, {len(stats)} statistikrader")
    print(f"  Filstorlek: {size_kb:.1f} KB")

    # PBP per match — sparas i docs/pbp/{match_id}.json, laddas on-demand av frontend
    pbp_dir = OUT_DIR / "pbp"
    pbp_dir.mkdir(parents=True, exist_ok=True)
    pbp_count = 0
    for pbp_row in conn.execute("SELECT match_id, pbp_json FROM match_pbp"):
        mid, pbp_raw = pbp_row[0], pbp_row[1]
        if not pbp_raw:
            continue
        with open(pbp_dir / f"{mid}.json", "w", encoding="utf-8") as f:
            f.write(pbp_raw)
        pbp_count += 1

    print(f"  PBP: {pbp_count} matchfiler i docs/pbp/")

    conn.close()


if __name__ == "__main__":
    main()
