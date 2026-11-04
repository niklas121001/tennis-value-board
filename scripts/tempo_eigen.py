"""Eigenes Platztempo für Challenger aus den gesammelten Match-Statistiken (sap_stats.json) -> docs/data/tempo_eigen.json

Tennis Abstract misst nur ATP-Turniere. Für Challenger wie dort: Asse je Aufschlagpunkt im Vergleich zur Erwartung aus
Aufschläger (wie oft schlägt er sonst Asse) und Returner (wie oft kassiert er sonst welche), jeweils aus allen anderen
Turnieren und zur Mitte gezogen (K_SPIELER). 1,00 = Schnitt unserer Daten. Je Turnier zur 1,00 hin gezogen, solange
wenige Aufschlag-Seiten vorliegen (K_TURNIER), und mehrere Jahre gewichtet wie bei Tennis Abstract (neuere stärker).
Dazu zur Info: gehaltene Aufschlagspiele und Tiebreaks je Satz. Keine API-Abrufe – läuft bei jedem Lauf.
"""
import re, sys, os, json, math, datetime, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import load, save

K_SPIELER = 150      # Aufschlagpunkte, mit denen ein Spieler zum Schnitt gezogen wird
K_TURNIER = 40       # Aufschlag-Seiten (≈ 20 Partien), mit denen ein Turnier zur 1,00 gezogen wird
MIN_SEITEN = 20


def ort(turnier):
    """„Bratislava 2, Slovakia, Qualifying“ -> „bratislava ii“ (Schlüssel wie im Spielplan „Bratislava II Challenger“)."""
    t = re.sub(r",\s*qualifying.*$", "", str(turnier or ""), flags=re.I).split(",")[0].strip().lower()
    return re.sub(r"\s+2$", " ii", re.sub(r"\s+3$", " iii", t))


def main():
    stats = load("sap_stats.json", {}) or {}
    rows = []
    for e in stats.values():
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
            name = re.sub(r"\s+2$", " ii", re.sub(r"\s+challenger.*$", "", str(e.get("turnier") or ""), flags=re.I).strip().lower())
            for z in e.get("satz") or []:
                if isinstance(z[0], int) and isinstance(z[1], int) and max(z) >= 6:
                    k = (name, e.get("belag"), str(e.get("start", ""))[:4])
                    tb[k][0] += sorted(z) == [6, 7]; tb[k][1] += 1
    gesamt_rate = sum(r["ace"] for r in rows) / max(1, sum(r["sv"] for r in rows))
    # Spielerwerte je Turnier ohne dieses Turnier (Leave-one-out): erst Summen gesamt, dann das Turnier abziehen
    sa, ra = collections.defaultdict(lambda: [0, 0]), collections.defaultdict(lambda: [0, 0])
    for r in rows:
        sa[r["s"]][0] += r["ace"]; sa[r["s"]][1] += r["sv"]; ra[r["r"]][0] += r["ace"]; ra[r["r"]][1] += r["sv"]
    gruppen = collections.defaultdict(list)
    for r in rows:
        if str(r["kat"]).lower() == "challenger":
            gruppen[(r["ort"], r["belag"], r["jahr"])].append(r)
    out = {}
    for (o, belag, jahr), rs in gruppen.items():
        ab_s, ab_r = collections.defaultdict(lambda: [0, 0]), collections.defaultdict(lambda: [0, 0])
        for r in rs:
            ab_s[r["s"]][0] += r["ace"]; ab_s[r["s"]][1] += r["sv"]; ab_r[r["r"]][0] += r["ace"]; ab_r[r["r"]][1] += r["sv"]
        def rate(dct, ab, n):
            a, p = dct[n][0] - ab[n][0], dct[n][1] - ab[n][1]
            return (a + K_SPIELER * gesamt_rate) / (p + K_SPIELER)
        obs = sum(r["ace"] for r in rs)
        exp = sum(rate(sa, ab_s, r["s"]) * rate(ra, ab_r, r["r"]) / gesamt_rate * r["sv"] for r in rs)
        gms = sum(r["gms"] for r in rs); brk = sum(r["brk"] for r in rs); t = tb.get((o, belag, jahr), [0, 0])
        x = out.setdefault((o, belag), {"name": o, "belag": belag, "jahre": {}})
        x["jahre"][jahr] = {"seiten": len(rs), "ass_index": round(obs / exp, 3) if exp else None,
                           "hold": round(1 - brk / gms, 3) if gms else None, "tb_satz": round(t[0] / t[1], 3) if t[1] else None}
    jahr_jetzt = datetime.date.today().year
    turniere = []
    for x in out.values():
        js = {j: v for j, v in x["jahre"].items() if v["ass_index"] and int(j) >= jahr_jetzt - 2}
        n = sum(v["seiten"] for v in js.values())
        if n < MIN_SEITEN:
            continue
        g = {j: (int(j) - (jahr_jetzt - 3)) * v["seiten"] for j, v in js.items()}           # neuere Jahre und mehr Daten stärker
        roh = sum(g[j] * v["ass_index"] for j, v in js.items()) / sum(g.values())
        x["speed"] = round(1 + (roh - 1) * n / (n + K_TURNIER), 2)
        x["roh"], x["seiten"], x["ch"], x["quelle"] = round(roh, 3), n, True, "eigen"
        x["alias"] = []
        turniere.append(x)
    turniere.sort(key=lambda x: (x["belag"], -x["speed"]))
    save("tempo_eigen.json", {"stand": datetime.date.today().isoformat(),
                              "quelle": "Eigene Schätzung aus Match-Statistiken (SportsAPIPro): Asse je Aufschlagpunkt vs. Erwartung aus Aufschläger und Returner, 1,00 = Schnitt",
                              "turniere": turniere})
    print(f"Eigenes Platztempo: {len(turniere)} Challenger-Turniere ({len(rows)} Aufschlag-Seiten insgesamt)")
    for x in turniere[:6]:
        print("  ", x["name"], x["belag"], x["speed"], "aus", x["seiten"], "Seiten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
