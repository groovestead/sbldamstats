"""
migrate_pbp.py — Engångsmigration: extraherar PBP ur raw_json, lagrar i
                 match_pbp-tabellen och rensar sedan raw_json.

Körs en gång:
    python3 migrate_pbp.py

Vacuumar databasen efteråt för att fysiskt frigöra diskutrymmet.
Scriptet är idempotent — om det körs igen hoppas redan migrerade
matcher över.
"""

import json
import sqlite3
from pathlib import Path

from fetch_data import extract_pbp

DB_PATH = Path(__file__).parent / "sbl.db"

SCHEMA_PBP = """
CREATE TABLE IF NOT EXISTS match_pbp (
    match_id INTEGER PRIMARY KEY,
    pbp_json TEXT
);
"""


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Hittar inte databasen: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA_PBP)

    already = set(
        r[0] for r in conn.execute("SELECT match_id FROM match_pbp")
    )

    rows = conn.execute(
        "SELECT match_id FROM matches WHERE raw_json IS NOT NULL"
    ).fetchall()

    to_migrate = [r[0] for r in rows if r[0] not in already]
    print(f"{len(rows)} matcher med raw_json, {len(to_migrate)} att migrera.")

    migrated = 0
    skipped = 0
    for (mid,) in conn.execute(
        "SELECT match_id FROM matches WHERE raw_json IS NOT NULL"
    ):
        if mid in already:
            continue
        raw = conn.execute(
            "SELECT raw_json FROM matches WHERE match_id = ?", (mid,)
        ).fetchone()[0]
        try:
            data = json.loads(raw)
        except Exception:
            skipped += 1
            continue
        pbp = extract_pbp(data)
        if pbp:
            conn.execute(
                "INSERT OR REPLACE INTO match_pbp (match_id, pbp_json) VALUES (?, ?)",
                (mid, json.dumps(pbp, separators=(",", ":"), ensure_ascii=False)),
            )
            migrated += 1
        else:
            skipped += 1

    conn.commit()
    print(f"  Extraherat PBP: {migrated} matcher, {skipped} utan PBP-data.")

    print("Rensar raw_json…")
    conn.execute("UPDATE matches SET raw_json = NULL")
    conn.commit()

    print("Kör VACUUM (kan ta en stund)…")
    conn.execute("VACUUM")
    conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"Klart! Databasen är nu {size_mb:.1f} MB.")


if __name__ == "__main__":
    main()
