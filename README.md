# SBL Dam stats

Ett söksverktyg för SBL Dam-statistik. Hämtar matchdata direkt från
FIBA LiveStats (samma datakälla som Profixio bygger på) och presenterar
den i ett enklare gränssnitt.

**Live:** https://groovestead.github.io/sbldamstats/

## Vad det gör

Sök på en spelare och se:

- Hennes senaste 5 matcher i jämförelse med säsongssnittet
- Säsongsaggregat över alla säsonger hon spelat i SBL Dam
- Vilka klubbar hon spelat för, säsong för säsong
- Detaljerad game log med stats per match

Datan täcker säsongerna 2021–2025 och uppdateras automatiskt dagligen.

## Hur det är byggt

Tre delar:

- `fetch_data.py` — hämtar matchdata från FIBA LiveStats och sparar
  i en SQLite-databas (`sbl.db`).
- `export_static.py` — exporterar databasen till en kompakt JSON-fil
  som webbsidan läser.
- `docs/index.html` — själva webbsidan. En enda HTML-fil med all
  CSS och JavaScript inbakat. GitHub Pages serverar den.

GitHub Actions kör `fetch_data.py` + `export_static.py` automatiskt
varje natt och pushar uppdaterad `data.json` till repot.

Allt använder bara Pythons standardbibliotek (urllib, sqlite3, json,
re) — inga externa pip-paket behöver installeras.

## Köra lokalt

För att utveckla eller köra verktyget på din egen dator:

```
# Hämta data en gång (eller efter att nya matcher spelats)
python3 fetch_data.py

# Starta lokal webbserver för utveckling (dynamisk version)
python3 server.py
# → öppna http://localhost:8000

# Eller — exportera till statisk JSON och kolla den versionen
python3 export_static.py
cd docs && python3 -m http.server 8001
# → öppna http://localhost:8001
```

## Datakällor

All data kommer från FIBA LiveStats / Genius Sports, som driver
basketstatistiken för Svenska Basketbollförbundet:

- Schemasida: `https://hosted.dcd.shared.geniussports.com/SBF/en/competition/{id}/schedule`
- Matchdata (JSON): `https://fibalivestats.dcd.shared.geniussports.com/data/{matchId}/data.json`

## Licens

MIT — använd det fritt. Det finns ingen tillhörighet till SBL,
Svenska Basketbollförbundet eller FIBA.
