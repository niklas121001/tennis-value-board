"""Gehaltene Aufschlagspiele je Spieler aus den Match-Statistiken (sap_stats.json) -> docs/data/hold_stats.json

Je Spieler und Belag: eigene Aufschlagspiele (gehalten / gespielt) und Aufschlagspiele der Gegner gegen ihn
(von den Gegnern gehalten / gespielt). Für den Tiebreak-Test „nach gehaltenen Aufschlagspielen“ im Modell und zur Anzeige.
Keine API-Abrufe.
"""
import sys, os, collections, datetime
sys.path.insert(0, os.path.dirname(__file__))
from common import load, save, stat_spiele


def main():
    sp = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0, 0]))
    tour = collections.defaultdict(lambda: [0, 0])
    for e in stat_spiele():
        b = e.get("belag")
        if b not in ("hard", "clay", "grass"):
            continue
        ebene = "ch" if str(e.get("kat")).lower() == "challenger" else "atp"
        for me, geg, s in ((e.get("h"), e.get("a"), e.get("hs")), (e.get("a"), e.get("h"), e.get("as"))):
            if not s or not s.get("sv_gms"):
                continue
            g = s["sv_gms"]; h = g - ((s.get("bp_faced") or 0) - (s.get("bp_saved") or 0))
            for key in (b, "alle"):
                v = sp[me][key]; v[0] += h; v[1] += g          # eigener Aufschlag
                w = sp[geg][key]; w[2] += h; w[3] += g         # Gegner schlägt gegen ihn auf
            t = tour[f"{ebene}_{b}"]; t[0] += h; t[1] += g
    out = {"stand": datetime.date.today().isoformat(), "quelle": "Match-Statistiken: SportsAPIPro (seit Okt. 2026) + Tennis Abstract (letzte 12 Monate, Tour + Challenger)",
           "tour": {k: round(v[0] / v[1], 4) for k, v in tour.items() if v[1]},
           "spieler": {n: {k: v for k, v in d.items()} for n, d in sp.items()}}
    save("hold_stats.json", out, indent=0)
    print(f"Hold-Statistik: {len(sp)} Spieler, Tour {out['tour']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
