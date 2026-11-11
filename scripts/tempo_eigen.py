"""Eigenes Platztempo für Challenger aus den gesammelten Match-Statistiken (sap_stats.json) -> docs/data/tempo_eigen.json

Tennis Abstract misst nur ATP-Turniere. Für Challenger wie dort: Asse je Aufschlagpunkt im Vergleich zur Erwartung aus
Aufschläger (wie oft schlägt er sonst Asse) und Returner (wie oft kassiert er sonst welche), jeweils aus allen anderen
Turnieren und zur Mitte gezogen (K_SPIELER). 1,00 = Schnitt unserer Daten. Je Turnier zur 1,00 hin gezogen, solange
wenige Aufschlag-Seiten vorliegen (K_TURNIER), und mehrere Jahre gewichtet wie bei Tennis Abstract (neuere stärker).
Seit 04.11.2026 zusätzlich gehaltene Aufschlagspiele vs. Erwartung (je Partie viel mehr Daten als Asse), über die
Steigung Ass-Index ~ Hold-Abweichung auf die Ass-Skala gebracht und zu W_HOLD eingerechnet. ATP-Turniere werden
genauso geschätzt, aber nur zum Vergleich mit Tennis Abstract gespeichert (atp_test). Dazu Tiebreaks je Satz. Keine API-Abrufe – läuft bei jedem Lauf.
"""
import re, sys, os, json, math, datetime, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import load, save, stat_spiele

K_SPIELER = 150      # Aufschlagpunkte, mit denen ein Spieler zum Schnitt gezogen wird
K_TURNIER = 40       # Aufschlag-Seiten (≈ 20 Partien), mit denen ein Turnier zur 1,00 gezogen wird
K_HOLD = 30          # Aufschlagspiele, mit denen ein Spieler beim Halten zum Schnitt gezogen wird
W_HOLD = 0.5         # Anteil der gehaltenen Aufschlagspiele an der Schätzung (Rest: Asse)
MIN_SEITEN = 20


def ort(turnier):
    """„Bratislava 2, Slovakia, Qualifying“ -> „bratislava ii“ (Schlüssel wie im Spielplan „Bratislava II Challenger“)."""
    t = re.sub(r",\s*qualifying.*$", "", str(turnier or ""), flags=re.I).split(",")[0].strip().lower()
    t = re.sub(r"\s+1$", "", t)                      # „Monastir 1“ (Tennis Abstract) = „Monastir“
    return re.sub(r"\s+2$", " ii", re.sub(r"\s+3$", " iii", t))


def main():
    rows = []
    for e in stat_spiele():
        if e.get("belag") not in ("hard", "clay", "grass"):
            continue
        for srv, ret, st in ((e.get("h"), e.get("a"), e.get("hs")), (e.get("a"), e.get("h"), e.get("as"))):
            if st and st.get("svpt") and st.get("ace") is not None:
                rows.append({"kat": e.get("kat"), "ort": ort(e.get("turnier")), "belag": e["belag"], "jahr": str(e.get("start", ""))[:4],
                             "s": srv, "r": ret, "ace": st["ace"], "sv": st["svpt"],
                             "gms": st.get("sv_gms") or 0, "brk": (st.get("bp_faced") or 0) - (st.get("bp_saved") or 0)})
    tb = collections.defaultdict(lambda: [0, 0])
    # Tiebreaks je Satz aus dem Ergebnis-Archiv (vollständig seit Oktober 2026): „Maia Challenger“ -> „maia“
    from common import DATA
    for f in sorted((DATA / "archiv").glob("????-??.json")):
        for e in json.loads(f.read_text(encoding="utf-8")).values():
            name = ort(re.sub(r"\s+challenger.*$", "", str(e.get("turnier") or ""), flags=re.I))
            for z in e.get("satz") or []:
                if isinstance(z[0], int) and isinstance(z[1], int) and max(z) >= 6:
                    k = (name, e.get("belag"), str(e.get("start", ""))[:4])
                    tb[k][0] += sorted(z) == [6, 7]; tb[k][1] += 1
    L = lambda q: math.log(min(max(q, 1e-4), 1 - 1e-4) / (1 - min(max(q, 1e-4), 1 - 1e-4)))
    gesamt_rate = sum(r["ace"] for r in rows) / max(1, sum(r["sv"] for r in rows))
    g_gms = sum(r["gms"] for r in rows); gesamt_hold = 1 - sum(r["brk"] for r in rows) / max(1, g_gms)
    # Spielerwerte gesamt (Asse/Aufschlagpunkte, gehaltene Spiele/Aufschlagspiele), je Turnier ohne dieses Turnier (Leave-one-out)
    sa, ra = collections.defaultdict(lambda: [0, 0, 0, 0]), collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        for dct, n in ((sa, r["s"]), (ra, r["r"])):
            v = dct[n]; v[0] += r["ace"]; v[1] += r["sv"]; v[2] += r["gms"] - r["brk"]; v[3] += r["gms"]
    gruppen = collections.defaultdict(list)
    for r in rows:
        gruppen[(r["ort"], r["belag"], r["jahr"], str(r["kat"]).lower() == "challenger")].append(r)
    out = {}
    for (o, belag, jahr, ch), rs in gruppen.items():
        ab_s, ab_r = collections.defaultdict(lambda: [0, 0, 0, 0]), collections.defaultdict(lambda: [0, 0, 0, 0])
        for r in rs:
            for dct, n in ((ab_s, r["s"]), (ab_r, r["r"])):
                v = dct[n]; v[0] += r["ace"]; v[1] += r["sv"]; v[2] += r["gms"] - r["brk"]; v[3] += r["gms"]
        def rate(dct, ab, n, i, base, k):
            a, p = dct[n][i] - ab[n][i], dct[n][i + 1] - ab[n][i + 1]
            return (a + k * base) / (p + k)
        obs = sum(r["ace"] for r in rs)
        exp = sum(rate(sa, ab_s, r["s"], 0, gesamt_rate, K_SPIELER) * rate(ra, ab_r, r["r"], 0, gesamt_rate, K_SPIELER) / gesamt_rate * r["sv"] for r in rs)
        # gehaltene Aufschlagspiele vs. Erwartung (Logit: Halten des Aufschlägers + Halten gegen diesen Returner − Schnitt)
        gms = sum(r["gms"] for r in rs); brk = sum(r["brk"] for r in rs)
        e_h = sum(r["gms"] / (1 + math.exp(-(L(rate(sa, ab_s, r["s"], 2, gesamt_hold, K_HOLD)) + L(rate(ra, ab_r, r["r"], 2, gesamt_hold, K_HOLD)) - L(gesamt_hold)))) for r in rs if r["gms"])
        t = tb.get((o, belag, jahr), [0, 0])
        x = out.setdefault((o, belag, ch), {"name": o, "belag": belag, "jahre": {}, "ch": ch})
        x["jahre"][jahr] = {"seiten": len(rs), "ass_index": round(obs / exp, 3) if exp else None,
                           "hold_dev": round(L(1 - brk / gms) - L(e_h / gms), 3) if gms and e_h else None,
                           "hold": round(1 - brk / gms, 3) if gms else None, "tb_satz": round(t[0] / t[1], 3) if t[1] else None}
    # Gehaltene Aufschlagspiele auf die Ass-Skala bringen: Steigung Ass-Index ~ Hold-Abweichung über alle Turniere
    pts = [(v["hold_dev"], v["ass_index"], v["seiten"]) for x in out.values() for v in x["jahre"].values() if v["hold_dev"] is not None and v["ass_index"]]
    W = sum(p[2] for p in pts) or 1; mx = sum(p[0] * p[2] for p in pts) / W; my = sum(p[1] * p[2] for p in pts) / W
    vx = sum(p[2] * (p[0] - mx) ** 2 for p in pts)
    steig = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in pts) / vx if vx else 0
    jahr_jetzt = datetime.date.today().year
    turniere, atp = [], []
    for x in out.values():
        js = {j: v for j, v in x["jahre"].items() if v["ass_index"] and int(j) >= jahr_jetzt - 2}
        n = sum(v["seiten"] for v in js.values())
        if n < MIN_SEITEN:
            continue
        g = {j: (int(j) - (jahr_jetzt - 3)) * v["seiten"] for j, v in js.items()}           # neuere Jahre und mehr Daten stärker
        ass = sum(g[j] * v["ass_index"] for j, v in js.items()) / sum(g.values())
        hd = [(g[j], v["hold_dev"]) for j, v in js.items() if v["hold_dev"] is not None]
        hold_skala = 1 + steig * (sum(a * b for a, b in hd) / sum(a for a, _ in hd) - mx) if hd and steig > 0 else None
        roh = ass if hold_skala is None else (1 - W_HOLD) * ass + W_HOLD * hold_skala         # Asse + gehaltene Aufschlagspiele
        x["speed"] = round(1 + (roh - 1) * n / (n + K_TURNIER), 2)
        x["roh"], x["ass"], x["hold_skala"] = round(roh, 3), round(ass, 3), round(hold_skala, 3) if hold_skala else None
        x["seiten"], x["quelle"], x["alias"] = n, "eigen", []
        (turniere if x["ch"] else atp).append(x)
    atp.sort(key=lambda x: (x["belag"], -x["speed"]))
    turniere.sort(key=lambda x: (x["belag"], -x["speed"]))
    save("tempo_eigen.json", {"stand": datetime.date.today().isoformat(),
                              "quelle": "Eigene Schätzung aus Match-Statistiken (SportsAPIPro + Tennis Abstract): Asse je Aufschlagpunkt vs. Erwartung aus Aufschläger und Returner, 1,00 = Schnitt",
                              "steigung_hold": round(steig, 3), "turniere": turniere,
                              "atp_test": atp})   # ATP nur zum Vergleich mit Tennis Abstract (Test bis Jahresende)
    print(f"Eigenes Platztempo: {len(turniere)} Challenger-Turniere ({len(rows)} Aufschlag-Seiten insgesamt)")
    for x in turniere[:6]:
        print("  ", x["name"], x["belag"], x["speed"], "aus", x["seiten"], "Seiten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
