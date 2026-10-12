"""Aktualisiert Elo-Werte in docs/data/players.json aus Tennis Abstract.

- yElo (Saison-Elo)            -> Feld "elo"        (= SPIELER_DB Spalte B)
- hElo / cElo / gElo (Belag)   -> elo_hard/clay/grass (= SPIELER_DB P/Q/R)

Spieler, die noch nicht in der DB stehen, werden mit Elo (ohne Aufschlagwerte) ergänzt
und mit "neu": true markiert. Aufschlag-/Returnwerte bleiben unverändert.
"""
import sys, time, datetime, urllib.request
from html.parser import HTMLParser
from common import load, save, NameMatcher, norm

URL_ELO = "https://tennisabstract.com/reports/atp_elo_ratings.html"
URL_YELO = "https://tennisabstract.com/reports/atp_season_yelo_ratings.html"
UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}


class Tables(HTMLParser):
    """Sammelt alle Tabellen als Listen von Zeilen (Textzellen)."""

    def __init__(self):
        super().__init__()
        self.tables, self.row, self.cell, self.in_cell = [], None, "", False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.in_cell, self.cell = True, ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.row.append(self.cell.replace("\xa0", " ").strip())
            self.in_cell = False
        elif tag == "tr" and self.row is not None and self.tables:
            if self.row:
                self.tables[-1].append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.in_cell:
            self.cell += data


def fetch(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            print(f"  Versuch {attempt + 1} fehlgeschlagen: {e}")
            time.sleep(5)
    raise SystemExit(f"Konnte {url} nicht laden")


def parse(html, needed):
    """Findet die Tabelle, deren Kopfzeile alle Spalten in `needed` enthält -> Liste von Dicts."""
    p = Tables()
    p.feed(html)
    for t in p.tables:
        for i, row in enumerate(t[:3]):
            if all(n in row for n in needed):
                head = row
                out = []
                for r in t[i + 1:]:
                    cells = [c for c in r]
                    if len(cells) < len(head):
                        continue
                    out.append(dict(zip(head, cells)))
                return out
    return []


def f(x):
    try:
        return round(float(str(x).replace(",", ".")), 1)
    except ValueError:
        return None


def main():
    players = load("players.json")
    manual = load("name_map.json", {})
    m = NameMatcher(players.keys(), manual)

    elo = parse(fetch(URL_ELO), ["Player", "hElo", "cElo", "gElo"])
    yelo = parse(fetch(URL_YELO), ["Player", "yElo"])
    if len(elo) < 100 or len(yelo) < 50:
        raise SystemExit(f"Zu wenige Zeilen gelesen (Elo {len(elo)}, yElo {len(yelo)}) – Seitenaufbau geändert?")

    upd, neu = 0, 0
    seen = {}
    for r in elo:
        name = r["Player"].strip()
        key = m.match(name) or name
        rec = players.setdefault(key, {"elo": None, "neu": True})
        if rec.get("neu"):
            neu += 1 if key not in seen else 0
        for col, fld in (("hElo", "elo_hard"), ("cElo", "elo_clay"), ("gElo", "elo_grass")):
            v = f(r.get(col))
            if v:
                rec[fld] = v
        # Fallback für Spieler ohne yElo: allgemeines Elo
        if rec.get("elo") is None and f(r.get("Elo")):
            rec["elo"] = f(r.get("Elo"))
        seen[key] = True
        upd += 1
    for r in yelo:
        name = r["Player"].strip()
        key = m.match(name)
        if key and f(r.get("yElo")):
            players[key]["elo"] = f(r.get("yElo"))

    save("players.json", players)
    meta = load("meta.json", {})
    meta["elo_update"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    save("meta.json", meta)
    print(f"Elo aktualisiert: {upd} Spieler (davon {neu} neu ohne Aufschlagwerte), yElo-Zeilen: {len(yelo)}")


if __name__ == "__main__":
    sys.exit(main())
