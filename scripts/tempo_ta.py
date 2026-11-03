"""Platztempo aller ATP-Turniere (Hart, Rasen UND Sand) von Tennis Abstract -> docs/data/tempo.json

Quelle: tennisabstract.com/cgi-bin/surface-speed.cgi?year=JJJJ (Ass-Quote bereinigt um Aufschläger/Returner,
1,00 = Tour-Schnitt). Ein einzelnes Jahr schwankt stark (Wetter, Bälle, wenige Partien) – daher Mittel der letzten
JAHRE Jahre, neuere stärker gewichtet (Gewicht 1, 2, 3 …). NUR PRIVAT (Tennis Abstract: nicht-kommerziell).
Läuft im Workflow, wenn tempo.json älter als 30 Tage ist (oder mit --immer).
Aliasnamen aus der bisherigen tempo.json bleiben erhalten.
"""
import re, sys, html, json, datetime, urllib.request
from common import load, save

UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}
JAHRE = 3
BELAG = {"hard": "hard", "clay": "clay", "grass": "grass", "carpet": "hard"}
ALIAS_STD = {"Rio de Janeiro": ["Rio"], "Monte Carlo Masters": ["Monte Carlo", "Monte-Carlo"], "Madrid Masters": ["Madrid"],
             "Rome Masters": ["Rome", "Rom", "Roma"], "Roland Garros": ["French Open", "Roland"], "Munich": ["München", "Muenchen"],
             "Bucharest": ["Bukarest"], "Kitzbuhel": ["Kitzbühel"], "Geneva": ["Genf"]}


def jahr_laden(y):
    url = f"https://www.tennisabstract.com/cgi-bin/surface-speed.cgi?year={y}"
    t = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        td = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(td) >= 5 and re.match(r"\d{2}-\w{3}-\d{4}", td[0]):
            b = BELAG.get(td[2].lower())
            if not b:
                continue                                   # Zeile verrutscht (z. B. Turniername in der Belag-Spalte)
            try:
                out.append((td[1], b, float(td[4])))
            except ValueError:
                pass
    return out


def nur_aktuelles_jahr(alt):
    """Während ATP-Turniere laufen: einmal am Tag nur die Seite des laufenden Jahres laden (1 Abruf, kein Kontingent –
    Tennis Abstract ist frei) und die Werte dieses Jahres in tempo.json aktualisieren; ältere Jahre bleiben."""
    y = datetime.date.today().year
    try:
        zeilen = jahr_laden(y)
    except Exception as e:                         # noqa
        print(f"  {y}: {e}")
        return 0
    if not zeilen:
        return 0
    t = {(r["name"].lower(), r["belag"]): r for r in alt.get("turniere", [])}
    jahre = sorted(set(str(j) for j in alt.get("jahre", [])) | {str(y)})[-JAHRE:]
    g = {j: i + 1 for i, j in enumerate(jahre)}
    neu = 0
    for name, belag, sp in zeilen:
        if "olympic" in name.lower() or "davis" in name.lower():
            continue
        name = re.sub(r"^nd Garros$", "Roland Garros", name)
        x = t.setdefault((name.lower(), belag), {"name": name, "belag": belag, "jahre": {}, "alias": ALIAS_STD.get(name, [])})
        if x["jahre"].get(str(y)) != sp:
            x["jahre"][str(y)] = sp; neu += 1
    for x in t.values():
        x["jahre"] = {j: v for j, v in x["jahre"].items() if j in g}
        if x["jahre"]:
            w = sum(g[j] for j in x["jahre"])
            x["speed"] = round(sum(g[j] * v for j, v in x["jahre"].items()) / w, 2)
    alt["turniere"] = sorted((x for x in t.values() if x["jahre"]), key=lambda x: (x["belag"], -x["speed"]))
    alt["jahre"] = [int(j) for j in jahre]
    alt["tag"] = datetime.date.today().isoformat()
    save("tempo.json", alt)
    print(f"Platztempo {y} aktualisiert (laufende Turniere): {neu} Werte neu/geändert")
    return 0


def main():
    alt = load("tempo.json", {}) or {}
    if "--immer" not in sys.argv and alt.get("stand") and \
            (datetime.date.today() - datetime.date.fromisoformat(alt["stand"])).days < 30:
        laeuft = any(str(m.get("kategorie", "")).upper() == "ATP" for m in (load("matches.json", {}) or {}).get("partien", []))
        if laeuft and alt.get("tag") != datetime.date.today().isoformat():
            return nur_aktuelles_jahr(alt)
        print("Platztempo aktuell (Stand", alt["stand"], ") – nichts zu tun")
        return 0
    jetzt = datetime.date.today().year
    jahre = {}
    for y in range(jetzt - JAHRE, jetzt + 1):
        try:
            z = jahr_laden(y)
        except Exception as e:                     # noqa
            print(f"  {y}: {e}")
            continue
        if z:
            jahre[y] = z
    if not jahre:
        print("Platztempo: keine Daten geladen – tempo.json bleibt")
        return 0
    jahre = dict(sorted(jahre.items())[-JAHRE:])
    alias_alt = {(r["name"].lower(), r["belag"]): r.get("alias") or [] for r in alt.get("turniere", [])}
    t = {}
    for i, (y, zeilen) in enumerate(jahre.items()):
        for name, belag, sp in zeilen:
            if "olympic" in name.lower() or "davis" in name.lower():
                continue
            name = re.sub(r"^nd Garros$", "Roland Garros", name)
            k = (name.lower(), belag)
            x = t.setdefault(k, {"name": name, "belag": belag, "jahre": {}})
            x["jahre"][str(y)] = sp
    for (k, belag), x in t.items():
        g = {y: i + 1 for i, y in enumerate(sorted(str(j) for j in jahre))}
        w = sum(g[y] for y in x["jahre"])
        x["speed"] = round(sum(g[y] * v for y, v in x["jahre"].items()) / w, 2)
        x["alias"] = sorted(set(alias_alt.get((k, belag), []) + ALIAS_STD.get(x["name"], [])))
    out = {"quelle": f"Tennis Abstract – ATP Surface Speed Ratings {min(jahre)}–{max(jahre)}, gewichtetes Mittel (neuere Jahre stärker), "
                     "1,00 = Tour-Schnitt, Asse bereinigt um Aufschläger/Returner – nur privat",
           "url": "https://www.tennisabstract.com/cgi-bin/surface-speed.cgi", "jahre": sorted(jahre), "stand": datetime.date.today().isoformat(),
           "turniere": sorted(t.values(), key=lambda x: (x["belag"], -x["speed"]))}
    save("tempo.json", out)
    from collections import Counter
    print(f"Platztempo: {len(t)} Turniere aus {sorted(jahre)} – {dict(Counter(x['belag'] for x in t.values()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
