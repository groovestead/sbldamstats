# SBL Dam stats — backlog

En lista över saker att göra senare. Inget av det här är brådskande
— allt som funkar idag fortsätter funka som det är.

Bocka av med `[x]` när något är klart. Lägg till nya rader när du
kommer på saker.

---

## Förbättringar — bra att ha innan publik release

- [x ] **Städa upp lagnamn.** Just nu finns 40 unika "lag" eftersom
  klubbar bytt namn över åren och det finns även stavfel i källdatan
  (t.ex. "Norrköping Dolphins" vs "Norrköpings Basketförening" vs
  "Norrköping Dophins"). Bör mappas till en kanonisk lista på 13–14 lag.
- [x ] **Sortera matcher på riktigt datum.** Just nu sorteras "senaste
  matcher" på match_id som proxy för datum. Funkar i 99 % av fallen
  men borde parsa det riktiga datumet ("Sep 27, 2025, 4:00 PM").
- [x ] **Hantera spelare med samma namn.** Idag används förnamn+efternamn
  som unik nyckel. Två spelare med exakt samma namn skulle hamna i
  samma rad. Sannolikt mycket sällsynt i SBL Dam, men borde lösas
  genom att hämta personId från Genius Sports-spelarsidan.
- [x ] **Förfina mobillayout.** Sidorna funkar på mobil men kan göras
  prydligare. Speciellt jämförelserutan ("senaste 5 vs säsong") som
  blir lite trång.

## Funktioner som vore bra för livekommentar

- [ ] **"Dagens matcher"-vy.** En sida som visar matcher som spelas
  idag/ikväll med snabblänkar till alla deltagande spelare.
- [ ] **Lagvy med trupp.** Klicka på ett lag och se alla spelare i
  truppen sorterade efter t.ex. poäng/match.
- [x] **Snabbsök med tangentbordsgenväg.** Tryck "/" för att hoppa fokus direkt till sökrutan. Snabbare under livesändning.
- [ ] **"Säsongstoppar i ligan".** Vem leder ligan i poäng, returer,
  assists, etc. — färdiga listor du kan referera till live.
- [ ] **Spelarjämförelse.** Klicka på två spelare och få deras
  statistik sida vid sida.
- [ ] **Karriärbäst-markeringar.** På spelarens game log: markera
  med en symbol om hon slog ett karriärbäst i någon kategori den
  matchen.

## Publicering

- [ ] **Göra sidan live på Netlify.** Repot kan vara privat. Vi har
  steg-för-steg-instruktioner sparade i chatten.
- [ ] **Eget domännamn.** Om du senare vill ha t.ex.
  `sbldamstats.se` istället för `*.netlify.app`. Kostar ~10–15 USD/år
  för domänen, själva hostingen är fortsatt gratis.
- [ ] **Lägga till "Senast uppdaterad"-stämpel synligt.** Idag
  diskret längst ner — borde kanske vara mer framträdande.

## Långsiktigt — utöka räckvidd

- [ ] **Lägga till SBL Herr.** Samma datakälla, samma struktur —
  bara att lägga till några competitionId i `fetch_data.py`.
- [ ] **Lägga till Basketettan Dam.** Samma — och spelar-ID:n är
  stabila över ligor, så vi skulle kunna följa spelare som rört
  sig mellan ligorna.
- [ ] **Lägga till Svenska Cupen.** Också samma datakälla.
- [ ] **Hitta data för säsonger före 2021.** Sannolikt inte möjligt
  via FIBA LiveStats men kan finnas hos Profixio eller arkiverat
  hos basket.se. Värt en undersökning.
- [ ] **Per-match-sida.** Klickbar matchruta som visar fullständigt
  box score, både lag.
- [ ] **Play-by-play.** Datan finns redan i de råa JSON-filerna —
  bara att rendera den.

## Tekniska förbättringar

- [x] **Slimma databasen.** `raw_json`-kolumnen tar 99 % av filstorleken
  (372 MB) men används aldrig efter den första parsningen. Kunde
  droppas för att göra databasen ~5 MB istället.
- [ ] **Lägga in en pre-byggd databas i repot.** Då slipper GitHub
  Actions hämta hela historiken vid första körningen om cachen
  rensats.
- [ ] **Bättre felmeddelanden.** Idag skriver scriptet bara
  "fel: <X>" — kunde ge bättre vägledning.

## Egna idéer (Johannes)

> Lägg till saker här när du kommer på dem!

- [ ] För kommentering: Ha en sida för pågående matcher som visar trender och intressant statistik i den pågående matchen. 
- [ ] Finns det data i play-by-play som inte syns i ordinarie box score? Exempelvis: Tekniska fouls, offensiva fouls, eller dragna offensiva fouls. 
- [ ] På spelar- och lagsidar: Visa nyheter från tidningar och sociala medier kopplat till spelaren/laget

---

*Senast uppdaterad: 2026-05-04*
