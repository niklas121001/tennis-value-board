"""Turnierkalender mit Belag aus Wikipedia -> docs/data/kalender.json

Quellen (Lizenz CC BY-SA, Nutzung mit Quellenangabe erlaubt):
  https://en.wikipedia.org/wiki/<Jahr>_ATP_Challenger_Tour
  https://en.wikipedia.org/wiki/<Jahr>_ATP_Tour
Je Turnier: Name, Ort, Belag (hard/clay/grass, Halle = hard), Wochenbeginn.
Die Belag-Erkennung (common.detect_surface) nutzt den Kalender vorrangig: Ort im Turniernamen + passende Woche.
"""
import sys, re, json, time, datetime, urllib.request, urllib.parse
from html.parser import HTMLParser
from common import load, save

UA = {"User-Agent": "TennisValueApp/1.0 (privates Hobbyprojekt; Kalenderabgleich 1x taeglich)"}
MONATE = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
BELAG_RE = re.compile(r"^\s*(hard|clay|grass|carpet)\b\s*(\(i\))?\s*[–—-]", re.I)
WOCHE_RE = re.compile(r"^\s*(" + "|".join(MONATE) + r")\s+(\d{1,2})\b", re.I)


class Zellen(HTMLParser):
    """Liefert Tabellenzeilen als Listen von Zellentexten; <br> und Blockenden werden zu Zeilenumbrüchen."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.depth = [], None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = ""
        elif tag in ("br", "p", "div", "li") and self.cell is not None:
            self.cell += "\n"
        elif tag in ("style", "sup"):
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in ("style", "sup"):
            self.depth = max(0, self.depth - 1)
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(self.cell.replace("\xa0", " ").strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None and not self.depth:
            self.cell += data


def lade(seite):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "parse", "page": seite, "prop": "text", "format": "json", "formatversion": 2, "redirects": 1})
    for versuch in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))["parse"]["text"]
        except Exception as e:  # noqa
            print(f"  {seite}: Versuch {versuch + 1} fehlgeschlagen ({e})")
            time.sleep(5)
    return ""


def parse(html, jahr):
    p = Zellen()
    p.feed(html)
    out, woche = [], None
    for row in p.rows:
        for zelle in row:
            m = WOCHE_RE.match(zelle)
            if m and len(zelle) < 40:
                woche = datetime.date(jahr, MONATE.index(m.group(1).lower()) + 1, int(m.group(2)))
            zeilen = [z.strip() for z in zelle.split("\n") if z.strip()]
            for i, z in enumerate(zeilen):
                b = BELAG_RE.match(z)
                if not b or i == 0:
                    continue
                belag = b.group(1).lower()
                belag = "hard" if belag == "carpet" else belag
                kopf = zeilen[:i]
                name = kopf[0]
                ort = kopf[1].split(",")[0].strip() if len(kopf) > 1 else ""
                if not ort and "," in name:          # Name und Ort in einer Zeile
                    ort = name.split(",")[0].strip()
                out.append({"name": name, "ort": ort, "belag": belag, "halle": bool(b.group(2)),
                            "woche": woche.isoformat() if woche else None})
                break
    return out


def main():
    jahr = datetime.date.today().year
    eintraege = []
    for seite, art in ((f"{jahr}_ATP_Challenger_Tour", "challenger"), (f"{jahr}_ATP_Tour", "atp")):
        html = lade(seite)
        e = parse(html, jahr) if html else []
        for x in e:
            x["art"] = art
        print(f"Kalender {seite}: {len(e)} Turniere erkannt")
        eintraege += e
    # Im Dezember schon das Folgejahr dazunehmen
    if datetime.date.today().month == 12:
        html = lade(f"{jahr + 1}_ATP_Challenger_Tour")
        eintraege += [dict(x, art="challenger") for x in parse(html, jahr + 1)] if html else []
    if len(eintraege) < 20:
        alt = load("kalender.json", [])
        print(f"Zu wenige Einträge erkannt ({len(eintraege)}) – alter Kalender ({len(alt)}) bleibt bestehen")
        return 0
    save("kalender.json", eintraege, indent=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
