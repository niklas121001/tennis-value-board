"""Turnier-Satzstatistik mit dem eigenen Ergebnis-Archiv fortschreiben (Ersatz für die TML-Database, die seit Januar 2026
nicht mehr aktualisiert wird) -> docs/data/turnier_stats.json

Basis = TML-Zahlen bis 2025 (beim ersten Lauf als „basis“ in turnier_stats_archiv.json eingefroren), dazu jede
ATP-Partie aus docs/data/archiv (ohne Challenger, ohne Aufgaben/W.O.). Erwarteter Anteil glatter Siege aus der
Marktquote statt aus Ranglistenpunkten. Läuft täglich im Workflow, rechnet nur neue Partien hinzu.
"""
import json, re, sys, os, datetime
sys.path.insert(0, os.path.dirname(__file__))
from common import load, save, DATA

SCHRUMPF = 300


def s_aus_p(p, bo):
    lo, hi = 0.0, 1.0
    for _ in range(40):
        m = (lo + hi) / 2
        v = 3 * m * m - 2 * m ** 3 if bo == 3 else 10 * m ** 3 - 15 * m ** 4 + 6 * m ** 5
        lo, hi = (m, hi) if v < p else (lo, m)
    return (lo + hi) / 2


def zuordnen(turnier, stats):
    t = str(turnier or "").lower()
    if "challenger" in t:
        return None
    best, bl = None, 0
    for k, x in stats.items():
        for n in [x["name"]] + (x.get("alias") or []):
            nn = str(n or "").lower()
            if len(nn) > bl and len(nn) >= 4 and nn in t:
                best, bl = k, len(nn)
    return best


def main():
    ts = load("turnier_stats.json", {}) or {}
    stats = ts.get("turniere") or {}
    st = load("turnier_stats_archiv.json", {}) or {}
    if "basis" not in st:                        # TML-Stand einfrieren (Summen statt Quoten)
        st["basis"] = {k: {"n": x["n"], "glatt": x["glatt"] * x["n"], "erw": (x.get("erwartet") or 0) * x["n"], "n_erw": x["n"] if x.get("erwartet") else 0,
                           "tb": x["tb_satz"] * x["saetze_schnitt"] * x["n"], "saetze": x["saetze_schnitt"] * x["n"], "fs": x["erster_satz"] * x["n"],
                           "jahre": x.get("jahre", {})} for k, x in stats.items()}
        st["basis_tour"] = {"tour": ts.get("tour"), "tb_satz": ts.get("tb_satz")}
        st["dazu"], st["ids"] = {}, []
    ids = set(st["ids"])
    arc = {}
    for f in sorted((DATA / "archiv").glob("????-??.json")):
        arc.update(json.loads(f.read_text(encoding="utf-8")))
    neu = 0
    for fid, a in arc.items():
        if fid in ids or a.get("sieger") not in ("A", "B") or a.get("aufgabe"):
            continue
        k = zuordnen(a.get("turnier"), stats)
        if not k:
            continue
        ss = [z for z in (a.get("satz") or []) if z and len(z) == 2 and z[0] != z[1]]
        bo = stats[k].get("bo", 3)
        if len(ss) < (2 if bo == 3 else 3):
            continue
        sa, sb = sum(1 for z in ss if z[0] > z[1]), sum(1 for z in ss if z[1] > z[0])
        glatt = (sa == 0 or sb == 0)
        tb = sum(1 for z in ss if sorted(z) == [6, 7])
        erster_sieger_gewinnt = (ss[0][0] > ss[0][1]) == (a["sieger"] == "A")
        d = st["dazu"].setdefault(k, {"n": 0, "glatt": 0, "erw": 0.0, "n_erw": 0, "tb": 0, "saetze": 0, "fs": 0, "jahre": {}})
        d["n"] += 1; d["glatt"] += glatt; d["tb"] += tb; d["saetze"] += len(ss); d["fs"] += erster_sieger_gewinnt
        if (a.get("qa") or 0) > 1 and (a.get("qb") or 0) > 1:
            p = (1 / a["qa"]) / (1 / a["qa"] + 1 / a["qb"]); s = s_aus_p(max(p, 1 - p), bo)
            d["erw"] += s * s + (1 - s) ** 2 if bo == 3 else s ** 3 + (1 - s) ** 3; d["n_erw"] += 1
        j = d["jahre"].setdefault(str(a.get("start", ""))[:4], [0, 0, 0, 0]); j[0] += 1; j[1] += glatt; j[2] += tb; j[3] += len(ss)
        ids.add(fid); neu += 1
    st["ids"] = sorted(ids)
    tour = st["basis_tour"]["tour"] or {}
    basis = {bo: (v["glatt"] / v["erwartet"]) for bo, v in tour.items() if v.get("erwartet")}
    tour_tb = st["basis_tour"]["tb_satz"] or 0.186
    for k, d in st["dazu"].items():
        b, x = st["basis"].get(k), stats.get(k)
        if not b or not x:
            continue
        n = b["n"] + d["n"]; glatt = b["glatt"] + d["glatt"]; ne = b["n_erw"] + d["n_erw"]; erw = b["erw"] + d["erw"]
        saetze = b["saetze"] + d["saetze"]; tb = b["tb"] + d["tb"]; fs = b["fs"] + d["fs"]
        jahre = dict(b["jahre"]); [jahre.__setitem__(j, [u + w for u, w in zip(jahre.get(j, [0, 0, 0, 0]), v)]) for j, v in d["jahre"].items()]
        roh = ((glatt / n) / (erw / ne)) / basis.get(str(x.get("bo", 3)), 1) if ne >= 20 and erw else x.get("faktor_roh", 1)
        x.update({"n": n, "glatt": round(glatt / n, 3), "erwartet": round(erw / ne, 3) if ne else x.get("erwartet"),
                  "tb_satz": round(tb / saetze, 3), "saetze_schnitt": round(saetze / n, 2),
                  "tb_faktor": round(1 + ((tb / saetze) / tour_tb - 1) * saetze / (saetze + 600), 3),
                  "erster_satz": round(fs / n, 3), "faktor_roh": round(roh, 3), "faktor": round(1 + (roh - 1) * n / (n + SCHRUMPF), 3),
                  "jahre": dict(sorted(jahre.items())), "archiv_n": d["n"]})
    ts["quelle"] = "TML-Database bis 2025 (ATP-Ebene, ohne Davis Cup) + eigenes Ergebnis-Archiv ab Okt. 2026 – nur privat"
    ts["stand_archiv"] = datetime.date.today().isoformat()
    save("turnier_stats.json", ts)
    save("turnier_stats_archiv.json", st, indent=0)
    print(f"Turnierstatistik aus Archiv: {neu} neue Partien, {sum(d['n'] for d in st['dazu'].values())} insgesamt in {len(st['dazu'])} Turnieren")
    return 0


if __name__ == "__main__":
    sys.exit(main())
