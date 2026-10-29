"""Eigene, täglich aktualisierte Elo (seit 29.10.2026).

Tennis Abstract aktualisiert seine Elo-Listen nur etwa wöchentlich (meist montags). Dieses Skript nimmt die
Tennis-Abstract-Werte als Basis und rechnet alle Ergebnisse aus unserem Archiv (ATP + Challenger) seit dem
Stand der Basis Spiel für Spiel nach – klassisches Elo-Update:

    neu = alt + K * (Ergebnis - erwartet),   erwartet = 1 / (1 + 10^((Elo Gegner - Elo Spieler) / 400))

- Gesamt-Elo (Feld "elo", yElo) und Belag-Elo (elo_hard/clay/grass, nur auf dem gespielten Belag) getrennt.
- Basis = Feld "ta" (von update_elo.py), sonst gespeicherte Basis, sonst aktuelle Werte (Erststart).
- Neue Tennis-Abstract-Werte -> Basis neu, Stand = letzter Montag (TA enthält Ergebnisse bis zum Sonntag davor).
- Immer aus der Basis neu gerechnet: mehrfaches Ausführen am Tag zählt nichts doppelt.
- Geschätzte Spieler (extra_players.py) werden hier nicht verändert, ihre Elo dient nur als Gegnerstärke.
- Aufgaben/W.O. zählen nicht. Zustand: docs/data/elo_eigen.json.
"""
import sys, json, datetime
from common import load, save, DATA, config

FELDER = ("elo", "elo_hard", "elo_clay", "elo_grass")


def letzter_montag(heute):
    return (heute - datetime.timedelta(days=heute.weekday())).isoformat()


def archiv():
    out = []
    ordner = DATA / "archiv"
    if ordner.exists():
        for f in sorted(ordner.glob("????-??.json"))[-4:]:          # die letzten Monate genügen
            out.extend(json.loads(f.read_text(encoding="utf-8")).values())
    return sorted((x for x in out if x.get("sieger") in ("A", "B") and not x.get("aufgabe") and x.get("start")),
                  key=lambda x: x["start"])


def main():
    players = load("players.json", {})
    P = (load("params.json", {}) or {}).get("params", {})
    K, K_BELAG = P.get("ELO_EIGEN_K", 28), P.get("ELO_EIGEN_K_BELAG", 32)
    state = load("elo_eigen.json", {"spieler": {}})
    st = state.setdefault("spieler", {})
    heute = datetime.datetime.now(datetime.timezone.utc).date()
    montag = letzter_montag(heute)

    # 1) Basis je Tennis-Abstract-Spieler bestimmen
    neu_basis = 0
    for name, rec in players.items():
        if rec.get("geschaetzt") or not isinstance(rec.get("elo"), (int, float)):
            continue
        ta = rec.get("ta")
        alt = st.get(name)
        if ta and (not alt or alt.get("basis") != ta):
            st[name] = {"basis": ta, "stand": montag}
            neu_basis += 1
        elif not alt:
            st[name] = {"basis": {f: rec.get(f) for f in FELDER}, "stand": montag}
            neu_basis += 1
    for name in [n for n in st if n not in players or players[n].get("geschaetzt")]:
        st.pop(name)

    # 2) Ergebnisse seit dem jeweiligen Stand nachrechnen
    cur = {n: dict(v["basis"]) for n, v in st.items()}
    n_sp = {n: 0 for n in st}
    frueh = min((v["stand"] for v in st.values()), default=montag)

    def wert(name, feld):
        r = cur.get(name) or players.get(name) or {}
        v = r.get(feld)
        if not isinstance(v, (int, float)) or v <= 0:
            v = r.get("elo")
        return v if isinstance(v, (int, float)) and v > 0 else None

    angewandt = 0
    for m in archiv():
        tag = str(m["start"])[:10]
        if tag < frueh:
            continue
        a, b = m.get("a"), m.get("b")
        aktiv = [n for n in (a, b) if n in cur and tag >= st[n]["stand"]]
        if not aktiv:
            continue
        s_a = 1.0 if m["sieger"] == "A" else 0.0
        bel = m.get("belag") if m.get("belag") in ("hard", "clay", "grass") else None
        upd = {}
        for feld, k in (("elo", K),) + (((f"elo_{bel}", K_BELAG),) if bel else ()):
            ea, eb = wert(a, feld), wert(b, feld)
            if ea is None or eb is None:
                continue
            erw_a = 1 / (1 + 10 ** ((eb - ea) / 400))
            upd[feld] = (k * (s_a - erw_a), k * ((1 - s_a) - (1 - erw_a)))
        if not upd:
            continue
        for feld, (da, db) in upd.items():
            if a in aktiv and isinstance(cur[a].get(feld) or cur[a].get("elo"), (int, float)):
                cur[a][feld] = (cur[a].get(feld) or cur[a]["elo"]) + da
            if b in aktiv and isinstance(cur[b].get(feld) or cur[b].get("elo"), (int, float)):
                cur[b][feld] = (cur[b].get(feld) or cur[b]["elo"]) + db
        for n in aktiv:
            n_sp[n] += 1
        angewandt += 1

    # 3) Zurückschreiben
    for name, v in cur.items():
        rec = players[name]
        for f in FELDER:
            if isinstance(v.get(f), (int, float)):
                rec[f] = round(v[f], 1)
        b = st[name]["basis"]
        if n_sp[name]:
            rec["elo_eigen"] = {"seit": st[name]["stand"], "spiele": n_sp[name],
                                "delta": round((v.get("elo") or 0) - (b.get("elo") or 0), 1)}
        else:
            rec.pop("elo_eigen", None)
    state["stand"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    save("elo_eigen.json", state, indent=0)
    save("players.json", players)
    bewegt = sorted(((n, players[n]["elo_eigen"]["delta"]) for n in cur if players[n].get("elo_eigen")), key=lambda x: -abs(x[1]))
    print(f"Eigene Elo: {len(cur)} Spieler mit Tennis-Abstract-Basis ({neu_basis} Basis neu), {angewandt} Ergebnisse angewandt, "
          f"{len(bewegt)} Spieler verändert. Größte Änderungen: " + ", ".join(f"{n} {d:+.0f}" for n, d in bewegt[:5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
