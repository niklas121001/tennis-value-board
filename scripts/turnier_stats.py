"""Satzstatistik je ATP-Turnier (letzte Jahre) -> docs/data/turnier_stats.json

Quelle: TML-Database (github.com/Tennismylife/TML-Database), ATP-Ebene ohne Davis Cup, ab AB_JAHR. NUR PRIVAT.
Aufruf (manuell, ab und zu):  python scripts/turnier_stats.py /pfad/zu/tml-database

Je Turnier: Belag, Halle, Best-of, Jahreswerte [Partien, glatte Siege (2:0 bzw. 3:0), Tiebreak-Sätze, Sätze gesamt],
Anteil glatter Siege, erwarteter Anteil (unabhängige Sätze, Stärke aus Ranglistenpunkten) und daraus der Turnierfaktor:
  faktor_roh = (Anteil / erwartet) / (Tour-Anteil / Tour-erwartet)     – > 1: hier enden mehr Spiele glatt als üblich
  faktor     = 1 + (faktor_roh − 1) · n / (n + SCHRUMPF)               – bei wenigen Partien Richtung 1 gezogen
Ohne Aufgaben/W.O. Der Faktor verändert auf der Website die Satzprognose (Verteilung 2:0 / 2:1), nie die Siegchance.
"""
import csv, glob, json, os, re, sys, math, datetime, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import DATA

AB_JAHR = 2015
SCHRUMPF = 300
EXPONENT = 0.6            # Siegwahrscheinlichkeit aus Ranglistenpunkten: pA^e / (pA^e + pB^e) (an den Daten angepasst)
ALIAS = {                 # zusätzliche Namen, unter denen das Turnier im Spielplan auftaucht
    "Paris Masters": ["Paris", "Bercy"], "Canada Masters": ["Toronto", "Montreal", "Montréal", "Canada"],
    "Indian Wells Masters": ["Indian Wells"], "Miami Masters": ["Miami"], "Madrid Masters": ["Madrid"],
    "Rome Masters": ["Rome", "Rom", "Roma"], "Monte Carlo Masters": ["Monte Carlo", "Monte-Carlo"],
    "Cincinnati Masters": ["Cincinnati"], "Shanghai Masters": ["Shanghai"], "Queen's Club": ["Queens", "London"],
    "s Hertogenbosch": ["Hertogenbosch", "'s-Hertogenbosch"], "Tour Finals": ["Turin", "Finals"],
    "Roland Garros": ["French Open", "Roland"], "Rio de Janeiro": ["Rio"], "Vienna": ["Wien"], "Beijing": ["Peking"],
    "Australian Open": ["Melbourne"], "US Open": ["New York"], "Wimbledon": ["Wimbledon"], "Athens": ["Athen"],
    "Munich": ["München", "Muenchen"], "Hamburg": ["Hamburg"], "Stuttgart": ["Stuttgart"], "Halle": ["Halle"],
}


NAMEN = {}


def saetze(score):
    if re.search(r"RET|W/O|DEF|ABD|unfinished|Walkover", score or "", re.I):
        return None
    s = [x for x in (score or "").split() if re.match(r"^\d+-\d+", x)]
    return s or None


def s_aus_p(p, bo):
    lo, hi = 0.0, 1.0
    for _ in range(40):
        m = (lo + hi) / 2
        v = 3 * m * m - 2 * m ** 3 if bo == 3 else 10 * m ** 3 - 15 * m ** 4 + 6 * m ** 5
        lo, hi = (m, hi) if v < p else (lo, m)
    return (lo + hi) / 2


def main(pfad):
    dateien = [f for f in sorted(glob.glob(os.path.join(pfad, "20[0-9][0-9].csv"))) if int(os.path.basename(f)[:4]) >= AB_JAHR]
    dateien.append(os.path.join(pfad, "ongoing_tourneys.csv"))
    dateien = [dateien[-1]] + sorted(dateien[:-1], reverse=True)    # neueste zuerst: aktuelle Schreibweise
    gesehen, t = set(), {}
    tour = {3: [0, 0, 0.0], 5: [0, 0, 0.0]}
    for f in dateien:
        if not os.path.exists(f):
            continue
        for r in csv.DictReader(open(f, encoding="utf-8", errors="ignore")):
            if r.get("tourney_level") in ("D",) or r.get("best_of") not in ("3", "5"):
                continue
            k = (r.get("tourney_id"), r.get("match_num"))
            if k in gesehen:
                continue
            gesehen.add(k)
            ss = saetze(r.get("score"))
            if not ss:
                continue
            bo = int(r["best_of"])
            glatt = len(ss) == (2 if bo == 3 else 3)
            tb = sum(1 for x in ss if re.match(r"^(7-6|6-7)", x))
            name = (r.get("tourney_name") or "").strip()
            name = NAMEN.setdefault(name.lower(), name)       # gleiche Turniere mit anderer Schreibweise zusammenführen
            jahr = str(r.get("tourney_date", ""))[:4]
            x = t.setdefault(name, {"name": name, "bo": bo, "belag": collections.Counter(), "halle": collections.Counter(),
                                    "level": r.get("tourney_level"), "jahre": {}, "n": 0, "glatt": 0, "erw": 0.0, "tb": 0, "saetze": 0})
            x["belag"][(r.get("surface") or "").lower()] += 1
            x["halle"][r.get("indoor")] += 1
            j = x["jahre"].setdefault(jahr, [0, 0, 0, 0])
            j[0] += 1; j[1] += glatt; j[2] += tb; j[3] += len(ss)
            x["n"] += 1; x["glatt"] += glatt; x["tb"] += tb; x["saetze"] += len(ss)
            try:
                pw, pl = float(r["winner_rank_points"]), float(r["loser_rank_points"])
            except (TypeError, ValueError):
                pw = pl = 0
            if pw > 0 and pl > 0:
                p = pw ** EXPONENT / (pw ** EXPONENT + pl ** EXPONENT)
                s = s_aus_p(max(p, 1 - p), bo)
                e = s * s + (1 - s) ** 2 if bo == 3 else s ** 3 + (1 - s) ** 3
                x["erw"] += e; x.setdefault("n_erw", 0); x["n_erw"] += 1; x.setdefault("glatt_erw", 0); x["glatt_erw"] += glatt
                tour[bo][0] += 1; tour[bo][1] += glatt; tour[bo][2] += e
    basis = {bo: (v[1] / v[0]) / (v[2] / v[0]) for bo, v in tour.items() if v[0]}
    out = {}
    for name, x in t.items():
        if x["n"] < 20:
            continue
        ne = x.get("n_erw", 0)
        roh = ((x["glatt_erw"] / ne) / (x["erw"] / ne)) / basis[x["bo"]] if ne >= 20 else 1.0
        out[name] = {
            "name": name, "bo": x["bo"], "belag": x["belag"].most_common(1)[0][0], "halle": x["halle"].most_common(1)[0][0] == "I",
            "level": x["level"], "alias": ALIAS.get(name, [re.sub(r"\s+Masters$", "", name)] if name.endswith("Masters") else []),
            "n": x["n"], "glatt": round(x["glatt"] / x["n"], 3), "erwartet": round(x["erw"] / ne, 3) if ne else None,
            "tb_satz": round(x["tb"] / x["saetze"], 3), "saetze_schnitt": round(x["saetze"] / x["n"], 2),
            "faktor_roh": round(roh, 3), "faktor": round(1 + (roh - 1) * x["n"] / (x["n"] + SCHRUMPF), 3),
            "jahre": dict(sorted(x["jahre"].items())),
        }
    erg = {"stand": datetime.date.today().isoformat(), "quelle": f"TML-Database ab {AB_JAHR} (ATP-Ebene, ohne Davis Cup) – nur privat",
           "tour": {str(bo): {"n": v[0], "glatt": round(v[1] / v[0], 3), "erwartet": round(v[2] / v[0], 3)} for bo, v in tour.items() if v[0]},
           "schrumpf": SCHRUMPF, "turniere": out}
    (DATA / "turnier_stats.json").write_text(json.dumps(erg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Turnierstatistik: {len(out)} Turniere, Tour Bo3 {erg['tour'].get('3')}, Bo5 {erg['tour'].get('5')}")
    for n in ["Paris Masters", "Basel", "Barcelona", "Rio de Janeiro", "Wimbledon"]:
        if n in out:
            print(" ", n, {k: out[n][k] for k in ("n", "glatt", "erwartet", "faktor_roh", "faktor", "tb_satz")})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../tennismylife/tml-database")
