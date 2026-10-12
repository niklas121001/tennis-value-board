# Tennis Value Board

Website, die automatisch Value-Wetten für ATP- und Challenger-Partien anzeigt, berechnet nach dem Modell aus `Analysetool_Belag.xlsx`.

- **Modell:** 1:1-Nachbau des Excel-Blatts MODELL (`docs/model.js`), geprüft gegen die in der Excel gespeicherten DASHBOARD-Werte (`tests/test_model.js`)
- **Quoten:** OddsPapi (Gratis-Konto), Buchmacher wählbar: bet365, Tipico, Bwin, Interwetten, Winamax
- **Elo:** täglich von Tennis Abstract (Belags-Elo + yElo)
- **Aufschlag-/Returnwerte, H2H, Blacklist, Parameter:** aus der Excel (`scripts/excel_export.py`)
- **Updates:** automatisch 2× täglich über GitHub Actions, Website über GitHub Pages

## Einrichtung (einmalig, ca. 15 Minuten)

1. **GitHub-Konto** anlegen auf github.com.
2. **Neues Repository** erstellen: oben rechts „+“ → *New repository*, Name z. B. `tennis-value-board`, Sichtbarkeit **Public** (GitHub Pages ist nur für öffentliche Repos kostenlos), *Create repository*.
3. **Dateien hochladen:** im leeren Repo auf *uploading an existing file* klicken und den **Inhalt** des entpackten ZIP-Ordners hineinziehen (inklusive des Ordners `.github`, der unter Windows evtl. ausgeblendet ist – „Ausgeblendete Elemente“ einschalten). *Commit changes*.
4. **OddsPapi-Key:** auf oddspapi.io ein kostenloses Konto anlegen und den API-Key kopieren. Im Repo: *Settings → Secrets and variables → Actions → New repository secret*, Name `ODDSPAPI_KEY`, Wert = Key.
5. **Website einschalten:** *Settings → Pages* → Source „Deploy from a branch“, Branch `main`, Ordner `/docs` → *Save*. Nach 1–2 Minuten steht oben die Adresse (`https://DEINNAME.github.io/tennis-value-board/`).
6. **Erstes Update starten:** Reiter *Actions* → „Daten aktualisieren“ → *Run workflow*. Danach läuft es automatisch um 9:15 und 17:15 Uhr.

## Kontingent

Pro Update: 1 Anfrage Spielplan + 2 Anfragen Quoten (max. 3 Buchmacher je Anfrage) = 3. Bei 2 Updates täglich ≈ 180 von 250 Gratis-Anfragen im Monat. Beim allerersten Lauf kommen einmalig 3 Anfragen dazu (Sportarten, Buchmacher, Märkte). Wird es knapp, überspringt das Skript Updates automatisch (Reserve: `anfragen_reserve` in `config.json`).

## Pflege

| Was | Wo |
|---|---|
| Buchmacher, Zeitfenster (`tage`: 2 = heute + morgen), Turnierfilter | `config.json` |
| Modell-Parameter | Excel-Blatt PARAMETER → `python scripts/excel_export.py Analysetool_Belag.xlsx` → `docs/data` hochladen |
| Belag eines Turniers | `docs/data/turniere.json` (Stichwort → hard/clay/grass) oder direkt auf der Website je Partie |
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
  update_elo.py            Elo von Tennis Abstract
  fetch_odds.py            Spielplan + Quoten von OddsPapi
  log_tips.js              Value-Tipps protokollieren (CLV)
tests/test_model.js        Abgleich Modell ↔ Excel
.github/workflows/update.yml   Zeitplan
```
