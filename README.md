# Tennis Value Board

Website, die automatisch Value-Wetten für ATP- und Challenger-Partien anzeigt, berechnet nach dem Modell aus `Analysetool_Belag.xlsx`.

- **Modell:** 1:1-Nachbau des Excel-Blatts MODELL (`docs/model.js`), geprüft gegen die in der Excel gespeicherten DASHBOARD-Werte (`tests/test_model.js`)
- **Quoten:** OddsPapi (Gratis-Konto), Buchmacher wählbar: Winamax, Tipico, bet365
- **Elo:** täglich von Tennis Abstract (Belags-Elo + yElo)
- **Aufschlag-/Returnwerte, H2H, Blacklist, Parameter:** aus der Excel (`scripts/excel_export.py`)
- **Updates:** automatisch 2× täglich über GitHub Actions, Website über GitHub Pages

## Einrichtung (einmalig, ca. 15 Minuten)

1. **GitHub-Konto** anlegen auf github.com.
2. **Neues Repository** erstellen: oben rechts „+“ → *New repository*, Name z. B. `tennis-value-board`, Sichtbarkeit **Public** (GitHub Pages ist nur für öffentliche Repos kostenlos), *Create repository*.
3. **Dateien hochladen:** im leeren Repo auf *uploading an existing file* klicken und den **Inhalt** des entpackten ZIP-Ordners hineinziehen (inklusive des Ordners `.github`, der unter Windows evtl. ausgeblendet ist – „Ausgeblendete Elemente“ einschalten). *Commit changes*.
4. **OddsPapi-Key:** auf oddspapi.io ein kostenloses Konto anlegen und den API-Key kopieren. Im Repo: *Settings → Secrets and variables → Actions → New repository secret*, Name `ODDSPAPI_KEY`, Wert = Key.
5. **Website einschalten:** *Settings → Pages* → Source „Deploy from a branch“, Branch `main`, Ordner `/docs` → *Save*. Nach 1–2 Minuten steht oben die Adresse (`https://DEINNAME.github.io/tennis-value-board/`).
6. **Erstes Update starten:** Reiter *Actions* → „Daten aktualisieren“ → *Run workflow*. Danach läuft es automatisch täglich um ca. 4 Uhr (Asien-Saison; Uhrzeit in `.github/workflows/update.yml`).

## Kontingent

Pro Update: 1 Anfrage Spielplan + 1 Anfrage je Buchmacher = 6. Bei 1 Update täglich ≈ 186 von 250 Gratis-Anfragen im Monat; der Rest reicht für einige manuelle Läufe. Beim allerersten Lauf kommen einmalig 3 Anfragen dazu (Sportarten, Buchmacher, Märkte). Das Skript verteilt das Restkontingent gleichmäßig auf die verbleibenden Tage und lässt bei Bedarf hintere Buchmacher aus der Liste weg (Reserve: `anfragen_reserve` in `config.json`).

## Bilanz

Jeder Value-Tipp wird beim ersten Erscheinen vor Spielbeginn gespeichert und nicht mehr verändert (`docs/data/tips_log.json`).
Ergebnisse: Wer in der nächsten Runde desselben Turniers im Spielplan steht, hat gewonnen (kostenlos). Was nach 30 h offen ist
(v. a. Endspiele), fragt das Skript bei OddsPapi ab – höchstens 2 Anfragen pro Tag. Schlussquoten für den CLV kommen aus den
historischen Quoten von OddsPapi. Aufgaben (Retirement) werden wie ein normaler Sieg des Weiterkommenden gewertet.

## Challenger-Spieler ohne Tennis-Abstract-Elo

Unbekannte Spieler bekommen ein geschätztes Elo (≈ auf der Website): Startwert aus den Buchmacher-Quoten gegen einen
bekannten Gegner (bis zu 5 Partien gemittelt), danach fortgeschrieben mit jedem Ergebnis. Fehlende Aufschlag-/Returnwerte
werden durch den Durchschnitt der Spieler auf Challenger-Niveau (yElo < 1650) ersetzt (`stats_avg.json`).
Value-Tipps mit geschätzten Spielern zählen erst ab 5 Ergebnissen für die Bilanz. Führt Tennis Abstract den Spieler
später, ersetzt das Elo-Update die Schätzwerte automatisch.

## Pflege

| Was | Wo |
|---|---|
| Buchmacher, Zeitfenster (`tage`: 2 = heute + morgen), Turnierfilter | `config.json` |
| Modell-Parameter | Excel-Blatt PARAMETER → `python scripts/excel_export.py Analysetool_Belag.xlsx` → `docs/data` hochladen |
| Belag eines Turniers | automatisch aus dem Wikipedia-Kalender (Ort + Turnierwoche); Ersatz: `docs/data/turniere.json` (Stichwort → hard/clay/grass) oder direkt auf der Website je Partie |
| Unbekannte Spielernamen | `docs/data/name_map.json`, z. B. `{"Rodriguez Taverna S.": "Santiago Rodriguez Taverna"}` |
| Fehlende Aufschlagwerte | `FEHLENDE_STATS` in `docs/data/params.json`: `nur_elo` (Standard) oder `excel` |

## Ordner

```
config.json                Einstellungen
docs/                      Website (GitHub Pages)
  index.html, model.js
  data/                    alle Daten (werden automatisch aktualisiert)
scripts/
  excel_export.py          Excel → JSON
  update_calendar.py       Turnierkalender mit Belag (Wikipedia, ATP + Challenger)
  update_elo.py            Elo von Tennis Abstract
  fetch_odds.py            Spielplan + Quoten von OddsPapi
  extra_players.py         fehlende (Challenger-)Spieler: Elo aus Quoten + Ergebnissen, Durchschnittswerte
  log_tips.js              Value-Tipps vor Spielbeginn einfrieren
  results.py               Ergebnisse + Schlussquoten nachtragen, Bilanz (ROI, Treffer, CLV)
tests/test_model.js        Abgleich Modell ↔ Excel
.github/workflows/update.yml   Zeitplan
```
