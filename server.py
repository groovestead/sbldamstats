"""
server.py — Lokal webbserver för SBL Dam-statistik.

Vad det här är:
  En liten webbserver som kör på din egen dator och låter dig söka
  spelare och se deras matchstatistik. Servern läser från databasen
  ("sbl.db") som du fyllde med fetch_data.py.

Hur du startar:
  python3 server.py

  Sen öppnar du:  http://localhost:8000/  i din webbläsare.
  Tryck Ctrl+C i terminalen när du vill stänga av.

  Den använder bara Pythons standardbibliotek — inga pip install.
"""

import html as html_lib
import re
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DB_PATH = Path(__file__).parent / "sbl.db"
PORT = 8000


# -----------------------------------------------------------------------------
# Databasen
# -----------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def search_players(conn, query):
    """Hitta spelare som matchar ett sök-ord. Hanterar svenska bokstäver."""
    if not query or len(query.strip()) < 1:
        return []
    q = query.strip().lower()
    rows = conn.execute("""
        SELECT p.player_key, p.first_name, p.family_name, p.photo_url, p.playing_position,
               (SELECT pms.team_name
                FROM player_match_stats pms
                JOIN matches m USING (match_id)
                WHERE pms.player_key = p.player_key
                ORDER BY m.match_id DESC
                LIMIT 1) AS latest_team,
               (SELECT COUNT(*) FROM player_match_stats WHERE player_key = p.player_key) AS games
        FROM players p
    """).fetchall()
    out = []
    for r in rows:
        full = f"{r['first_name'] or ''} {r['family_name'] or ''}".lower()
        if q in full:
            out.append(dict(r))
    # Sortera: först de vars förnamn/efternamn börjar med söket, sen övriga
    def score(p):
        fn = (p["first_name"] or "").lower()
        ln = (p["family_name"] or "").lower()
        if fn.startswith(q) or ln.startswith(q):
            return 0
        return 1
    out.sort(key=lambda p: (score(p), -(p.get("games") or 0), p["family_name"] or ""))
    return out[:50]


def player_detail(conn, player_key):
    """Hämta all data för en specifik spelare."""
    player = conn.execute(
        "SELECT * FROM players WHERE player_key = ?", (player_key,)
    ).fetchone()
    if not player:
        return None

    # Senaste 20 matcherna
    recent = conn.execute("""
        SELECT pms.*,
               m.match_date, m.season_year, m.home_team, m.away_team,
               m.home_score, m.away_score, m.match_id
        FROM player_match_stats pms
        JOIN matches m USING (match_id)
        WHERE pms.player_key = ?
        ORDER BY m.match_id DESC
        LIMIT 20
    """, (player_key,)).fetchall()

    # Säsongsaggregat (snittstatistik per säsong)
    seasons = conn.execute("""
        SELECT m.season_year,
               COUNT(*) AS games,
               AVG(pms.points * 1.0) AS pts,
               AVG(pms.rebounds_total * 1.0) AS reb,
               AVG(pms.assists * 1.0) AS ast,
               AVG(pms.steals * 1.0) AS stl,
               AVG(pms.blocks * 1.0) AS blk,
               AVG(pms.turnovers * 1.0) AS tov,
               AVG(pms.fg_made * 1.0) AS fgm, AVG(pms.fg_att * 1.0) AS fga,
               AVG(pms.three_made * 1.0) AS tpm, AVG(pms.three_att * 1.0) AS tpa,
               AVG(pms.ft_made * 1.0) AS ftm, AVG(pms.ft_att * 1.0) AS fta,
               AVG(pms.plus_minus * 1.0) AS pm
        FROM player_match_stats pms
        JOIN matches m USING (match_id)
        WHERE pms.player_key = ?
        GROUP BY m.season_year
        ORDER BY m.season_year DESC
    """, (player_key,)).fetchall()

    # Senaste 5 matcherna jämfört med innevarande säsongs snitt
    recent_match_ids = [r["match_id"] for r in recent[:5]]
    if recent_match_ids:
        latest_season_year = recent[0]["season_year"]
        placeholders = ",".join("?" for _ in recent_match_ids)
        last5 = conn.execute(f"""
            SELECT COUNT(*) AS games,
                   AVG(points * 1.0) AS pts,
                   AVG(rebounds_total * 1.0) AS reb,
                   AVG(assists * 1.0) AS ast,
                   AVG(steals * 1.0) AS stl,
                   AVG(blocks * 1.0) AS blk,
                   AVG(turnovers * 1.0) AS tov,
                   AVG(plus_minus * 1.0) AS pm
            FROM player_match_stats
            WHERE player_key = ? AND match_id IN ({placeholders})
        """, (player_key, *recent_match_ids)).fetchone()
        season_avg = conn.execute("""
            SELECT COUNT(*) AS games,
                   AVG(pms.points * 1.0) AS pts,
                   AVG(pms.rebounds_total * 1.0) AS reb,
                   AVG(pms.assists * 1.0) AS ast,
                   AVG(pms.steals * 1.0) AS stl,
                   AVG(pms.blocks * 1.0) AS blk,
                   AVG(pms.turnovers * 1.0) AS tov,
                   AVG(pms.plus_minus * 1.0) AS pm
            FROM player_match_stats pms
            JOIN matches m USING (match_id)
            WHERE pms.player_key = ? AND m.season_year = ?
        """, (player_key, latest_season_year)).fetchone()
    else:
        last5 = None
        season_avg = None
        latest_season_year = None

    # Lag spelaren spelat för per säsong
    teams = conn.execute("""
        SELECT m.season_year, pms.team_name, COUNT(*) AS games
        FROM player_match_stats pms
        JOIN matches m USING (match_id)
        WHERE pms.player_key = ?
        GROUP BY m.season_year, pms.team_name
        ORDER BY m.season_year DESC, games DESC
    """, (player_key,)).fetchall()

    return {
        "player": dict(player),
        "recent": [dict(r) for r in recent],
        "seasons": [dict(r) for r in seasons],
        "teams": [dict(r) for r in teams],
        "last5": dict(last5) if last5 else None,
        "season_avg": dict(season_avg) if season_avg else None,
        "latest_season_year": latest_season_year,
    }


# -----------------------------------------------------------------------------
# HTML — vi bygger sidor med f-strings, inga template-bibliotek behövs
# -----------------------------------------------------------------------------

STYLE = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
    background: #0f1115;
    color: #e8e8e8;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    line-height: 1.5;
}
a { color: #6cb6ff; text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 20px 24px 60px; }
header.site {
    border-bottom: 1px solid #2a2f3a;
    padding: 14px 24px;
    background: #161a22;
    position: sticky;
    top: 0;
    z-index: 10;
}
header.site .row { max-width: 1100px; margin: 0 auto; display: flex; align-items: center; gap: 16px; }
header.site h1 { font-size: 18px; margin: 0; font-weight: 600; }
header.site h1 a { color: inherit; }
header.site form { flex: 1; }
header.site input[type=text] {
    width: 100%;
    padding: 10px 14px;
    border-radius: 8px;
    background: #0f1115;
    border: 1px solid #2a2f3a;
    color: inherit;
    font-size: 16px;
}
header.site input[type=text]:focus { outline: none; border-color: #6cb6ff; }

.section { margin-top: 28px; }
.section h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.06em; color: #9aa3b2; margin: 0 0 10px; font-weight: 600; }

.card { background: #161a22; border: 1px solid #2a2f3a; border-radius: 10px; padding: 16px; }

table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { color: #9aa3b2; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #2a2f3a; }
tr.match td { border-bottom: 1px solid #1f2530; }
tr.match:hover td { background: #1a1f2a; }

.player-grid { display: grid; grid-template-columns: 100px 1fr; gap: 18px; align-items: center; }
.player-grid img { width: 100px; height: 100px; border-radius: 12px; object-fit: cover; background: #2a2f3a; }
.player-name { font-size: 28px; font-weight: 700; line-height: 1.1; }
.player-meta { color: #9aa3b2; margin-top: 4px; font-size: 14px; }

.compare {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 8px;
    margin-top: 8px;
}
.compare .stat {
    background: #0f1115;
    border: 1px solid #2a2f3a;
    border-radius: 8px;
    padding: 10px;
    text-align: center;
}
.compare .stat .label { font-size: 11px; color: #9aa3b2; text-transform: uppercase; letter-spacing: 0.06em; }
.compare .stat .val { font-size: 22px; font-weight: 700; margin-top: 4px; }
.compare .stat .delta { font-size: 12px; margin-top: 2px; }
.compare .stat .delta.up { color: #6fd28e; }
.compare .stat .delta.down { color: #ff8b8b; }
.compare .stat .delta.zero { color: #9aa3b2; }

.results { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; margin-top: 12px; }
.result {
    display: flex; gap: 12px; align-items: center;
    background: #161a22; border: 1px solid #2a2f3a; border-radius: 10px;
    padding: 12px; text-decoration: none; color: inherit;
    transition: border-color 0.1s ease;
}
.result:hover { border-color: #6cb6ff; text-decoration: none; }
.result img { width: 48px; height: 48px; border-radius: 8px; object-fit: cover; background: #2a2f3a; }
.result .name { font-weight: 600; }
.result .meta { font-size: 13px; color: #9aa3b2; }

.muted { color: #9aa3b2; }
.empty { padding: 40px 20px; text-align: center; color: #9aa3b2; }
"""


def page(title, body, search_query=""):
    safe_title = html_lib.escape(title)
    safe_search = html_lib.escape(search_query)
    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} — SBL Dam stats</title>
  <style>{STYLE}</style>
</head>
<body>
  <header class="site">
    <div class="row">
      <h1><a href="/">SBL Dam stats</a></h1>
      <form action="/" method="get" autocomplete="off">
        <input type="text" name="q" value="{safe_search}" placeholder="Sök spelare (förnamn eller efternamn)" autofocus>
      </form>
    </div>
  </header>
  <main class="wrap">
    {body}
  </main>
</body>
</html>"""


def fmt(value, dec=1):
    """Formatera ett tal till en eller flera decimaler. Tom om None."""
    if value is None:
        return "–"
    try:
        return f"{float(value):.{dec}f}"
    except (TypeError, ValueError):
        return "–"


def fmt_int(value):
    if value is None:
        return "–"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "–"


def render_search(query, results):
    if not query.strip():
        body = """
        <div class="empty">
          <p>Sök efter en spelare i rutan ovan.<br>Du kan skriva för- eller efternamn.</p>
        </div>"""
        return page("Sök", body)

    if not results:
        body = f'<div class="empty"><p>Inga spelare hittade för "{html_lib.escape(query)}".</p></div>'
        return page(f"Sök: {query}", body, search_query=query)

    cards = []
    for p in results:
        photo = p.get("photo_url") or ""
        photo_html = f'<img src="{html_lib.escape(photo)}" alt="">' if photo else '<div style="width:48px;height:48px;border-radius:8px;background:#2a2f3a"></div>'
        name = html_lib.escape(f"{p['first_name'] or ''} {p['family_name'] or ''}".strip())
        meta_parts = []
        if p.get("playing_position"):
            meta_parts.append(p["playing_position"])
        if p.get("latest_team"):
            meta_parts.append(p["latest_team"])
        if p.get("games"):
            meta_parts.append(f"{p['games']} matcher")
        meta = html_lib.escape(" · ".join(meta_parts)) if meta_parts else ""
        url = "/player/" + urllib.parse.quote(p["player_key"], safe="")
        cards.append(f"""
            <a class="result" href="{url}">
              {photo_html}
              <div>
                <div class="name">{name}</div>
                <div class="meta">{meta}</div>
              </div>
            </a>""")

    body = f"""
    <div class="section">
      <h2>{len(results)} resultat</h2>
      <div class="results">{"".join(cards)}</div>
    </div>"""
    return page(f"Sök: {query}", body, search_query=query)


def delta_html(recent_val, season_val):
    """Visa skillnaden mellan senaste 5 och säsongssnittet."""
    if recent_val is None or season_val is None:
        return ""
    diff = recent_val - season_val
    if abs(diff) < 0.05:
        return '<div class="delta zero">±0.0</div>'
    cls = "up" if diff > 0 else "down"
    sign = "+" if diff > 0 else ""
    return f'<div class="delta {cls}">{sign}{diff:.1f} vs säsong</div>'


def render_player(data):
    p = data["player"]
    recent = data["recent"]
    seasons = data["seasons"]
    teams = data["teams"]
    last5 = data["last5"]
    season_avg = data["season_avg"]
    latest_season = data["latest_season_year"]

    # Header
    name = html_lib.escape(f"{p['first_name'] or ''} {p['family_name'] or ''}".strip())
    photo = p.get("photo_url") or ""
    photo_html = f'<img src="{html_lib.escape(photo)}" alt="">' if photo else '<div style="width:100px;height:100px;border-radius:12px;background:#2a2f3a"></div>'
    meta_parts = []
    if p.get("playing_position"):
        meta_parts.append(p["playing_position"])
    if p.get("shirt_number"):
        meta_parts.append(f"#{p['shirt_number']}")
    if teams:
        meta_parts.append(teams[0]["team_name"])
    meta = html_lib.escape(" · ".join(meta_parts))

    header_html = f"""
    <div class="card">
      <div class="player-grid">
        {photo_html}
        <div>
          <div class="player-name">{name}</div>
          <div class="player-meta">{meta}</div>
        </div>
      </div>
    </div>"""

    # Senaste 5 vs säsongssnitt
    compare_html = ""
    if last5 and season_avg and last5.get("games") and season_avg.get("games"):
        stats = [
            ("PTS", "pts"),
            ("REB", "reb"),
            ("AST", "ast"),
            ("STL", "stl"),
            ("BLK", "blk"),
            ("TOV", "tov"),
            ("+/-", "pm"),
        ]
        cells = []
        for label, key in stats:
            r = last5.get(key)
            s = season_avg.get(key)
            cells.append(f"""
              <div class="stat">
                <div class="label">{label}</div>
                <div class="val">{fmt(r)}</div>
                {delta_html(r, s)}
              </div>""")
        compare_html = f"""
        <div class="section">
          <h2>Senaste {int(last5['games'])} matcher · säsong {latest_season}</h2>
          <div class="card">
            <div class="muted" style="margin-bottom:6px">Snitt över hennes senaste matcher i jämförelse med hela säsongens snitt</div>
            <div class="compare">{"".join(cells)}</div>
          </div>
        </div>"""

    # Säsongssnitt-tabell
    season_rows = []
    for s in seasons:
        season_rows.append(f"""
          <tr>
            <td>{s['season_year']}</td>
            <td>{s['games']}</td>
            <td>{fmt(s['pts'])}</td>
            <td>{fmt(s['reb'])}</td>
            <td>{fmt(s['ast'])}</td>
            <td>{fmt(s['stl'])}</td>
            <td>{fmt(s['blk'])}</td>
            <td>{fmt(s['tov'])}</td>
            <td>{fmt(s['fgm'])}/{fmt(s['fga'])}</td>
            <td>{fmt(s['tpm'])}/{fmt(s['tpa'])}</td>
            <td>{fmt(s['ftm'])}/{fmt(s['fta'])}</td>
            <td>{fmt(s['pm'])}</td>
          </tr>""")
    seasons_html = ""
    if season_rows:
        seasons_html = f"""
        <div class="section">
          <h2>Säsongssnitt</h2>
          <div class="card" style="overflow-x:auto">
            <table>
              <thead><tr>
                <th>Säsong</th><th>Matcher</th>
                <th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TOV</th>
                <th>FG</th><th>3P</th><th>FT</th><th>+/-</th>
              </tr></thead>
              <tbody>{"".join(season_rows)}</tbody>
            </table>
          </div>
        </div>"""

    # Lag genom åren
    teams_html = ""
    if teams:
        team_rows = []
        for t in teams:
            team_rows.append(f"<tr><td>{t['season_year']}</td><td>{html_lib.escape(t['team_name'] or '')}</td><td>{t['games']} matcher</td></tr>")
        teams_html = f"""
        <div class="section">
          <h2>Lag</h2>
          <div class="card" style="overflow-x:auto">
            <table>
              <thead><tr><th>Säsong</th><th>Lag</th><th>Antal matcher</th></tr></thead>
              <tbody>{"".join(team_rows)}</tbody>
            </table>
          </div>
        </div>"""

    # Senaste matcher (game log)
    log_rows = []
    for r in recent:
        # Beskriv matchen "Luleå 95–57 Södertälje" och visa motståndare
        home = r.get("home_team") or ""
        away = r.get("away_team") or ""
        team = r.get("team_name") or ""
        own_is_home = team and team == home
        opp = away if own_is_home else home
        score = f"{r.get('home_score','')}–{r.get('away_score','')}" if r.get("home_score") is not None else ""
        result_str = f"{score} mot {opp}"
        log_rows.append(f"""
          <tr class="match">
            <td>{html_lib.escape(r.get('match_date') or '')}</td>
            <td class="muted">{html_lib.escape(result_str)}</td>
            <td>{html_lib.escape(r.get('minutes') or '')}</td>
            <td>{fmt_int(r.get('points'))}</td>
            <td>{fmt_int(r.get('rebounds_total'))}</td>
            <td>{fmt_int(r.get('assists'))}</td>
            <td>{fmt_int(r.get('steals'))}</td>
            <td>{fmt_int(r.get('blocks'))}</td>
            <td>{fmt_int(r.get('turnovers'))}</td>
            <td>{fmt_int(r.get('fg_made'))}/{fmt_int(r.get('fg_att'))}</td>
            <td>{fmt_int(r.get('three_made'))}/{fmt_int(r.get('three_att'))}</td>
            <td>{fmt_int(r.get('ft_made'))}/{fmt_int(r.get('ft_att'))}</td>
            <td>{fmt_int(r.get('plus_minus'))}</td>
          </tr>""")
    log_html = ""
    if log_rows:
        log_html = f"""
        <div class="section">
          <h2>Senaste matcherna</h2>
          <div class="card" style="overflow-x:auto">
            <table>
              <thead><tr>
                <th>Datum</th><th>Match</th><th>Min</th>
                <th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TOV</th>
                <th>FG</th><th>3P</th><th>FT</th><th>+/-</th>
              </tr></thead>
              <tbody>{"".join(log_rows)}</tbody>
            </table>
          </div>
        </div>"""

    body = header_html + compare_html + seasons_html + teams_html + log_html
    return page(name, body)


# -----------------------------------------------------------------------------
# HTTP-hanterare
# -----------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            url = urllib.parse.urlparse(self.path)
            path = url.path
            params = urllib.parse.parse_qs(url.query)

            conn = get_db()
            try:
                if path in ("/", ""):
                    q = params.get("q", [""])[0]
                    results = search_players(conn, q)
                    self._send_html(render_search(q, results))
                elif path.startswith("/player/"):
                    key = urllib.parse.unquote(path[len("/player/"):])
                    data = player_detail(conn, key)
                    if not data:
                        self._send_html(page("Hittade inte", '<div class="empty"><p>Spelaren finns inte i databasen.</p><p><a href="/">← Tillbaka</a></p></div>'), status=404)
                    else:
                        self._send_html(render_player(data))
                elif path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                else:
                    self._send_html(page("Hittade inte", '<div class="empty"><p>Sidan finns inte.</p><p><a href="/">← Tillbaka</a></p></div>'), status=404)
            finally:
                conn.close()
        except BrokenPipeError:
            # Klienten stängde anslutningen — inget att göra
            pass
        except Exception as e:
            try:
                self._send_html(page("Fel", f'<div class="empty"><p>Ett fel uppstod: {html_lib.escape(str(e))}</p></div>'), status=500)
            except Exception:
                pass

    def _send_html(self, html_str, status=200):
        data = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        # Tystare loggning — visa bara fel
        if "200" in (args[1] if len(args) > 1 else ""):
            return
        super().log_message(format, *args)


# -----------------------------------------------------------------------------
# Starta servern
# -----------------------------------------------------------------------------

def main():
    if not DB_PATH.exists():
        print(f"Hittar inte databasen ({DB_PATH}).")
        print("Kör först:  python3 fetch_data.py")
        return

    print(f"SBL Dam-statistik körs på http://localhost:{PORT}")
    print("Öppna länken i din webbläsare. Tryck Ctrl+C för att stänga.")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServern stoppad.")


if __name__ == "__main__":
    main()
