"""Schlaghand (R/L) und Bilanz gegen Links-/Rechtshänder -> docs/data/haende.json

Quelle: TML-Database (github.com/Tennismylife/TML-Database, ATP-Ebene inkl. Quali, keine Challenger).
NUR PRIVAT: laut Nutzungsbedingungen keine kommerzielle Nutzung (vor Premium ersetzen/lizenzieren).
Aufruf (manuell, die Schlaghand ändert sich nicht):  python scripts/haende.py /pfad/zu/tml-database
Je Spieler (Name wie in players.json):
  h        Schlaghand "R"/"L"
  vsL/vsR  [Siege, Niederlagen] gegen Links-/Rechtshänder ab BILANZ_AB
  m        Monatswerte {"YYYYMM": [S gg. L, N gg. L, S gg. R, N gg. R]} (zum Zusammenführen mit neueren Quellen)
  srvL/srvR  Aufschlag/Return gegen Links-/Rechtshänder (Summen: svpt, in1, w1, w2, rpt, rw) – vorerst nur gesammelt
"""
import csv, glob, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import NameMatcher, load, save

BILANZ_AB = "20230101"


def zahl(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main(pfad):
    players = load("players.json", {})
    nm = NameMatcher(list(players), load("name_map.json", {}))
    dateien = sorted(glob.glob(os.path.join(pfad, "20[0-9][0-9].csv"))) + [os.path.join(pfad, "ongoing_tourneys.csv")]
    rows = []
    for f in dateien:
        if os.path.exists(f):
            with open(f, encoding="utf-8", errors="ignore") as fh:
                rows += list(csv.DictReader(fh))
    hand = {}
    for r in rows:
        for p in ("winner", "loser"):
            if r.get(p + "_hand") in ("R", "L") and r.get(p + "_name"):
                hand[r[p + "_name"]] = r[p + "_hand"]
    zuord = {n: nm.match(n) for n in hand}
    out = {}
    def rec(name):
        return out.setdefault(name, {"h": None, "vsL": [0, 0], "vsR": [0, 0],
                                     "srvL": dict(svpt=0, in1=0, w1=0, w2=0, rpt=0, rw=0), "srvR": dict(svpt=0, in1=0, w1=0, w2=0, rpt=0, rw=0)})
    for tml, db in zuord.items():
        if db:
            rec(db)["h"] = hand[tml]
    for r in rows:
        if str(r.get("tourney_date", "")) < BILANZ_AB:
            continue
        w, l = zuord.get(r.get("winner_name")), zuord.get(r.get("loser_name"))
        hw, hl = r.get("winner_hand"), r.get("loser_hand")
        if "RET" in str(r.get("score", "")).upper() or "W/O" in str(r.get("score", "")).upper():
            continue
        for me, geg_h, gew, pre, gpre in ((w, hl, True, "w_", "l_"), (l, hw, False, "l_", "w_")):
            if not me or geg_h not in ("R", "L"):
                continue
            x = rec(me)
            x["vs" + geg_h][0 if gew else 1] += 1
            mon = str(r.get("tourney_date", ""))[:6]           # Monatswerte: [S gg. L, N gg. L, S gg. R, N gg. R]
            mm = x.setdefault("m", {}).setdefault(mon, [0, 0, 0, 0])
            mm[(0 if geg_h == "L" else 2) + (0 if gew else 1)] += 1
            sv, i1, w1, w2 = (zahl(r.get(pre + k)) for k in ("svpt", "1stIn", "1stWon", "2ndWon"))
            gsv, gw1, gw2 = (zahl(r.get(gpre + k)) for k in ("svpt", "1stWon", "2ndWon"))
            if None not in (sv, i1, w1, w2) and sv and None not in (gsv, gw1, gw2) and gsv:
                s = x["srv" + geg_h]
                s["svpt"] += sv; s["in1"] += i1; s["w1"] += w1; s["w2"] += w2
                s["rpt"] += gsv; s["rw"] += gsv - gw1 - gw2
    for x in out.values():
        for k in ("srvL", "srvR"):
            x[k] = {a: int(b) for a, b in x[k].items()}
    bis = max((m_ for x in out.values() for m_ in (x.get("m") or {})), default="")
    save("haende.json", {"quelle": "TML-Database (nur privat, keine kommerzielle Nutzung)", "bilanz_ab": BILANZ_AB, "bis": bis, "spieler": out}, indent=0)
    n_l = sum(1 for x in out.values() if x["h"] == "L")
    print(f"Schlaghand: {sum(1 for x in out.values() if x['h'])} Spieler zugeordnet, davon {n_l} Linkshänder")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tml-database")
