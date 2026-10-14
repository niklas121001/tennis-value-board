"""Quotenverlauf je Partie und Buchmacher -> docs/data/quoten_verlauf.json

Läuft nach fetch_odds.py. Speichert bei jedem Lauf die aktuelle Quote, wenn sie sich geändert hat:
  {fixtureId: {"start": ..., "bm": {winamax: [["2026-10-14T02:07Z", 1.85, 2.05], ...]}}}
Die Website zeigt damit einen Pfeil (Quote seit erster Sichtung gefallen/gestiegen) und den Verlauf im Detail.
Partien, deren Start mehr als 3 Tage zurückliegt, werden entfernt.
"""
import sys, datetime
from common import load, save


def main():
    mj = load("matches.json", {"partien": []})
    if mj.get("demo"):
        print("Quotenverlauf: Demo-Daten – übersprungen")
        return 0
    verlauf = load("quoten_verlauf.json", {})
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    ts = jetzt.strftime("%Y-%m-%dT%H:%MZ")
    neu = 0
    for m in mj.get("partien", []):
        if not m.get("quoten"):
            continue
        v = verlauf.setdefault(m["id"], {"start": m.get("start"), "bm": {}})
        v["start"] = m.get("start")
        for bm, (qa, qb) in m["quoten"].items():
            if bm in (m.get("pausiert") or []) or not qa or not qb:
                continue
            reihe = v["bm"].setdefault(bm, [])
            if not reihe or (reihe[-1][1], reihe[-1][2]) != (qa, qb):
                reihe.append([ts, qa, qb])
                neu += 1
            del reihe[:-20]                      # höchstens 20 Stände je Buchmacher
    grenze = (jetzt - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    verlauf = {k: v for k, v in verlauf.items() if str(v.get("start") or "9999") >= grenze}
    save("quoten_verlauf.json", verlauf, indent=0)
    print(f"Quotenverlauf: {neu} neue Quotenstände, {len(verlauf)} Partien")
    return 0


if __name__ == "__main__":
    sys.exit(main())
