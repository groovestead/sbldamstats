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
    # Umeå-laget under sina olika namn genom åren
    "a3 basket":                     "Umeå Basket",
    "a3 basket umeå":                "Umeå Basket",
    "udominate":                     "Umeå Basket",
    "udominate (umeå)":              "Umeå Basket",
    "udominate basket":              "Umeå Basket",
    "umeå basket":                   "Umeå Basket",            # självmapping

    "aik basket":                    "AIK",
    "alviks bbk":                    "Alvik Basket",
    "alvik basket":                  "Alvik Basket",           # självmapping
    "ik eos":                        "IK Eos",
    "ik eos lund":                   "IK Eos",
    "idrottsklubben eos":            "IK Eos",
    "mark basket":                   "Mark Basket",
    "mark borås":                    "Mark Basket",
    "malbas bbk":                    "Malbas",
    "norrköping dophins":            "Norrköping Dolphins",    # stavfel i källdata
    "norrköpings basketförening":    "Norrköping Dolphins",
    "sbbk dam":                      "Södertälje BBK",
    "södertälje basketbollklubb":    "Södertälje BBK",
    "telge basket":                  "Södertälje BBK",
    "sallén basket":                 "Uppsala Basket",
    "salléns basket":                "Uppsala Basket",
    "uppsala basket dam":            "Uppsala Basket",
    "föreningen uppsala basket dam": "Uppsala Basket",
    "visby ladies":                  "Visby Ladies",           # hanterar VISBY LADIES via lower()
    "wetterbygden sparks":           "Wetterbygdens Sparks",
    "sjuhärads basketbollförening":  "Sjuhärads Basket",
    "östersunds basket":             "Östersund Basket",
    "högsbo":                        "Högsbo",
    "högsbo (göteborg)":             "Högsbo",
    "högsbo basket":                 "Högsbo",
    "luleå basket":                  "Luleå Basket",           # självmapping
    "rig luleå":                     "RIG Luleå",
    "borås basket":                  "Borås Basket",
    "brahe basket":                  "Brahe Basket",
    "helsingborg bbk":               "Helsingborg BBK",
}

# SM-finalhistorik 1958–2025. Källa: Finalhistoria210426_1.xlsx.
# Namnen är normaliserade till kanoniska klubbnamn för att matcha statistikdatan.
# aborted=True innebär att säsongen avbröts innan finale spelades klart (2020: COVID).
_FINALS_HISTORY = [
    # year, champion, finalist, aborted
    (2025, "Luleå Basket",        "Högsbo",                    False),
    (2024, "Södertälje BBK",      "Luleå Basket",              False),
    (2023, "Luleå Basket",        "Södertälje BBK",            False),
    (2022, "Norrköping Dolphins", "Luleå Basket",              False),
    (2021, "Luleå Basket",        "Alvik Basket",              False),
    (2020, "Luleå Basket",        "Alvik Basket",              True),  # avbruten (COVID)
    (2019, "Umeå Basket",         "Högsbo",                    False),
    (2018, "Luleå Basket",        "Umeå Basket",               False),
    (2017, "Luleå Basket",        "Umeå Basket",               False),
    (2016, "Luleå Basket",        "Umeå Basket",               False),
    (2015, "Luleå Basket",        "Umeå Basket",               False),
    (2014, "Luleå Basket",        "Norrköping Dolphins",       False),
    (2013, "Norrköping Dolphins", "Solna BK",                  False),
    (2012, "Södertälje BBK",      "Luleå Basket",              False),
    (2011, "Södertälje BBK",      "Luleå Basket",              False),
    (2010, "08 Stockholm",        "Solna BK",                  False),
    (2009, "Solna BK",            "Södertälje BBK",            False),
    (2008, "Solna BK",            "Södertälje BBK",            False),
    (2007, "08 Stockholm",        "Luleå Basket",              False),
    (2006, "Solna BK",            "Luleå Basket",              False),
    (2005, "Visby Ladies",        "Luleå Basket",              False),
    (2004, "Solna BK",            "Brahe (Huskvarna)",         False),
    (2003, "08 Stockholm",        "Solna BK",                  False),
    (2002, "Solna BK",            "Norrköping Dolphins",       False),
    (2001, "08 Alvik Stockholm",  "IK Eos",                    False),
    (2000, "Norrköping Dolphins", "Nerike (Örebro)",           False),
    (1999, "Nerike (Örebro)",     "Södertälje BBK",            False),
    (1998, "Nerike (Örebro)",     "Alvik Basket",              False),
    (1997, "Södertälje BBK",      "Visby Ladies",              False),
    (1996, "Nerike (Örebro)",     "Visby Ladies",              False),
    (1995, "Bro (Örebro)",        "Stockholm Capitals",        False),
    (1994, "Arvika",              "Stockholm Capitals",        False),
    (1993, "Arvika",              "Uppsala Basket",            False),
    (1992, "Arvika",              "Solna BK",                  False),
    (1991, "Arvika",              "Södertälje BBK",            False),
    (1990, "Arvika",              "KFUM Söder (Stockholm)",    False),
    (1989, "Arvika",              "Visby Ladies",              False),
    (1988, "Solna BK",            "Arvika",                    False),
    (1987, "Solna BK",            "Visby Ladies",              False),
    (1986, "Solna BK",            "Visby Ladies",              False),
    (1985, "Södertälje BBK",      "Uppsala Basket",            False),
    (1984, "Södertälje BBK",      "Solna BK",                  False),
    (1983, "Södertälje BBK",      "Solna BK",                  False),
    (1982, "Södertälje BBK",      "Uppsala Basket",            False),
    (1981, "Södertälje BBK",      "Uppsala Basket",            False),
    (1980, "Södertälje BBK",      "Uppsala Basket",            False),
    (1979, "Södertälje BBK",      "KFUM Söder (Stockholm)",    False),
    (1978, "Södertälje BBK",      "Uppsala Basket",            False),
    (1977, "Södertälje BBK",      "Högsbo",                    False),
    (1976, "Högsbo",              "Alvik Basket",              False),
    (1975, "Högsbo",              "KFUM-KFUM Västerås",        False),
    (1974, "KFUM-KFUM Västerås", "BK Rush (Stockholm)",       False),
    (1973, "KFUM Söder (Stockholm)", "KFUM-KFUM Västerås",    False),
    (1972, "KFUM-KFUM Västerås", "KFUM Söder (Stockholm)",    False),
    (1971, "Ruter/Mörby (Stockholm)", "BK Rush (Stockholm)",  False),
    (1970, "BK Rush (Stockholm)", "Ruter/Mörby (Stockholm)",  False),
    (1969, "Ruter/Mörby (Stockholm)", "Katrineholms SK",      False),
    (1968, "BK Ruter (Stockholm)", "BK Rush (Stockholm)",     False),
    (1967, "BK Ruter (Stockholm)", "Blackeberg (Stockholm)",  False),
    (1966, "Sunne",               "Blackeberg (Stockholm)",   False),
    (1965, "Blackeberg (Stockholm)", "BK Rush (Stockholm)",   False),
    (1964, "Blackeberg (Stockholm)", "BK Ruter (Stockholm)",  False),
    (1963, "Blackeberg (Stockholm)", "Göteborgs Kvinnliga IK", False),
    (1962, "Blackeberg (Stockholm)", "Göteborgs Kvinnliga IK", False),
    (1961, "Blackeberg (Stockholm)", "BK Rilton (Stockholm)", False),
    (1960, "BK Rilton (Stockholm)", "Blackeberg (Stockholm)", False),
    (1959, "Blackeberg (Stockholm)", "BK Rilton (Stockholm)", False),
    (1958, "BK Rilton (Stockholm)", "KFUM Söder (Stockholm)", False),
]


_CANON_VALUES = set(_TEAM_CANON.values())
_unknown_teams: set = set()  # fylls i av canonical_team(); rapporteras i main()

def canonical_team(name):
    """Returnera det kanoniska klubbnamnet, eller originalnamnet om inget finns i mappingen."""
    if not name:
        return name
    stripped = name.strip()
    result = _TEAM_CANON.get(stripped.lower(), stripped)
    # Varna om ett lagnamn varken finns i mappingen eller är ett känt kanoniskt namn.
    if stripped.lower() not in _TEAM_CANON and stripped not in _CANON_VALUES:
        _unknown_teams.add(stripped)
    return result


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

    # PBP per match — sparas i docs/pbp/{match_id}.json, laddas on-demand av frontend
    # Samtidigt parsas offensiva fouls, tekniska fouls och osportsliga fouls per spelare/match.
    pbp_dir = OUT_DIR / "pbp"
    pbp_dir.mkdir(parents=True, exist_ok=True)
    pbp_count = 0
    _EXTRA_FOUL_SUBTYPES = {"offensive", "technical", "unsportsmanlike"}
    pbp_fouls = {}  # "player_key:match_id" -> [off, tech, unsport]

    for pbp_row in conn.execute("SELECT match_id, pbp_json FROM match_pbp"):
        mid, pbp_raw = pbp_row[0], pbp_row[1]
        if not pbp_raw:
            continue
        with open(pbp_dir / f"{mid}.json", "w", encoding="utf-8") as f:
            f.write(pbp_raw)
        pbp_count += 1

        try:
            pbp_data = json.loads(pbp_raw)
        except Exception:
            continue
        for ev in pbp_data.get("ev", []):
            if len(ev) < 10 or ev[3] != "foul" or ev[4] not in _EXTRA_FOUL_SUBTYPES:
                continue
            fn = (ev[8] or "").strip()
            ln = (ev[9] or "").strip()
            if not fn and not ln:
                continue
            pkey = f"{fn}|{ln}".lower()
            k = f"{pkey}:{mid}"
            if k not in pbp_fouls:
                pbp_fouls[k] = [0, 0, 0]
            if ev[4] == "offensive":
                pbp_fouls[k][0] += 1
            elif ev[4] == "technical":
                pbp_fouls[k][1] += 1
            else:
                pbp_fouls[k][2] += 1

    print(f"  PBP: {pbp_count} matchfiler i docs/pbp/")
    print(f"  PBP fouls: {len(pbp_fouls)} spelare/match-rader (OFF/TF/UNSPORT)")

    finals = [
        {"year": yr, "champion": ch, "finalist": fn, "aborted": ab}
        for yr, ch, fn, ab in _FINALS_HISTORY
    ]

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
        "pbp_fouls": pbp_fouls,
        "finals": finals,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # separators=(",", ":") ger oss minsta möjliga JSON utan onödiga blanksteg
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = OUT_FILE.stat().st_size / 1024
    print(f"Skrev {OUT_FILE.relative_to(ROOT)}")
    print(f"  {len(players)} spelare, {len(matches)} matcher, {len(stats)} statistikrader")
    print(f"  Filstorlek: {size_kb:.1f} KB")

    if _unknown_teams:
        print(f"\nOkända lagnamn (lägg till i _TEAM_CANON om de är felstavningar):")
        for t in sorted(_unknown_teams):
            print(f"  {t!r}")

    conn.close()


if __name__ == "__main__":
    main()
