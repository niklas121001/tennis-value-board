"""Ergänzt Spieler, die Tennis Abstract (noch) nicht führt – v. a. Challenger – in docs/data/players.json.

1. Start-Elo aus Marktquoten: Spielt ein unbekannter Spieler gegen einen Spieler mit Elo, wird aus der
   entvigten Durchschnittsquote zurückgerechnet, welches Elo der Markt ihm zutraut. Bis zu MAX_MARKT
   Partien werden gemittelt.
2. Elo aus Ergebnissen: Danach wird das Elo mit jedem Ergebnis fortgeschrieben (Folgerunden-Logik wie in
   results.py), K-Faktor wie bei Tennis Abstract/538: K = 250 / (n + 5) ** 0.4.
3. Durchschnittswerte für fehlende Aufschlag-/Returnwerte (Spieler auf Challenger-Niveau) -> stats_avg.json.

Geschätzte Spieler tragen "geschaetzt": true. update_elo.py ersetzt sie automatisch, sobald Tennis Abstract
den Spieler führt. Kostet keine API-Anfragen.
"""
import sys, math, datetime
from common import load, save, norm, flip, ist_platzhalter
from results import runden_sieger, ts

MAX_MARKT = 5           # Elo aus dem Markt = Mittel der letzten so vielen Quoten-Beobachtungen (laufend aktualisiert)
K_ERGEBNIS = 40         # Ergebnis-Korrektur auf den Marktwert (klein, weil die Quote Form/Ergebnisse schon einpreist)
ERG_DELTA_MAX = 120     # Ergebnis-Korrektur höchstens ± so viele Punkte
BASIS_ELO = 1500        # Mittelpunkt für zwei unbekannte Spieler (Obergrenze; Tennis-Abstract-Skala)
ELO_NIVEAU_MAX = 1650   # Spieler unter diesem yElo bilden den "Challenger-Durchschnitt"
FELDER = ("1in", "1won", "2won")


def belag_key(b):
    b = str(b or "hard").lower()
    return b if b in ("hard", "clay", "grass") else "hard"


def used_elo(p, belag, P):
    """Wie model.js: Belags-Elo, gemischt mit yElo."""
    col = "elo_" + belag_key(belag)
    be = p.get(col) if isinstance(p.get(col), (int, float)) and p.get(col) > 0 else p.get("elo")
    if be is None:
        return None
    if P.get("YELO_EINBEZIEHEN") == "Ja" and isinstance(p.get("elo"), (int, float)):
        w = P.get("W_YELO_BLEND", 0.4)
        return w * p["elo"] + (1 - w) * be
    return be


def clean_name(raw):
    n = " ".join(str(flip(raw)).split())
    return n


def k_faktor(n):
    return 250 / ((n + 5) ** 0.4)


def neu_berechnen(rec):
    """Elo = Mittel der letzten Markt-Beobachtungen + Ergebnis-Korrektur."""
    werte = rec.get("markt_werte") or []
    if werte:
        rec["elo_markt"] = round(sum(werte) / len(werte), 1)
    basis = rec.get("elo_markt", rec.get("elo"))
    if basis is not None:
        setze_elo(rec, basis + rec.get("erg_delta", 0))


def setze_elo(rec, wert):
    wert = round(wert, 1)
    rec.update(elo=wert, elo_hard=wert, elo_clay=wert, elo_grass=wert)


def stats_durchschnitt(players):
    out = {}
    for s in ("hard", "clay", "grass"):
        werte = {f: [] for f in FELDER}
        werte["ret"] = []
        for p in players.values():
            if p.get("geschaetzt") or not isinstance(p.get("elo"), (int, float)) or p["elo"] >= ELO_NIVEAU_MAX:
                continue
            vals = [p.get(f"{s}_{f}") for f in FELDER] + [p.get(f"ret_{s}")]
            if all(isinstance(v, (int, float)) and v > 0 for v in vals):
                for f, v in zip(list(FELDER) + ["ret"], vals):
                    werte[f].append(v)
        if werte["1in"]:
            out[s] = {f: round(sum(v) / len(v), 4) for f, v in werte.items()}
            out[s]["n"] = len(werte["1in"])
    tbs = [p["tb"] for p in players.values() if isinstance(p.get("tb"), (int, float)) and not p.get("geschaetzt")
           and isinstance(p.get("elo"), (int, float)) and p["elo"] < ELO_NIVEAU_MAX]
    tb = round(sum(tbs) / len(tbs), 4) if tbs else 0.5
    for s in out:
        out[s]["tb"] = tb
    return out


def main():
    players = load("players.json")
    P = load("params.json", {}).get("params", {})
    matches = load("matches.json", {}).get("partien", [])
    seen = load("fixtures_seen.json", {})
    state = load("extra_state.json", {"verarbeitet": []})
    verarbeitet = set(state.get("verarbeitet", []))
    neu, markt, erg = 0, 0, 0
    # Aufräumen: versehentlich als Spieler angelegte Platzhalter ("1/8 Final 3 Winner" o. Ä.) entfernen
    weg = [k for k, v in players.items() if v.get("geschaetzt") and ist_platzhalter(k)]
    for k in weg:
        players.pop(k)
    matches = [m for m in matches if not (ist_platzhalter(m.get("a")) or ist_platzhalter(m.get("b")))]
    if weg:
        print(f"  {len(weg)} Platzhalter aus der Spieler-DB entfernt")

    # 1) Start-Elo aus Marktquoten – in drei Stufen, damit auch Challenger-Partien zwischen zwei Unbekannten
    #    einen Wert bekommen:
    #    direkt   : Gegner hat ein echtes Elo (Tennis Abstract) oder ist ein bewährter Schätzwert (>= 3 Ergebnisse)
    #    indirekt : Gegner ist selbst geschätzt (auch aus diesem Lauf) – wiederholt, bis nichts mehr dazukommt
    #    basis    : beide unbekannt – Mittelpunkt = typisches Elo unbekannter Challenger-Spieler, Abstand aus der Quote
    def markt_p(m, seite):
        ps = []
        for q in (m.get("quoten") or {}).values():
            qa, qb = q
            if qa and qb and qa > 1 and qb > 1:
                pa = (1 / qa) / (1 / qa + 1 / qb)
                ps.append(pa if seite == "a" else 1 - pa)
        return min(0.97, max(0.03, sum(ps) / len(ps))) if ps else None

    def key_fuer(m, seite):
        name = m.get(seite)
        if name in players:
            return name
        k = clean_name(m.get(seite + "Roh") or name)
        return k

    def unbekannt(m, seite):
        rec = players.get(key_fuer(m, seite))
        # geschätzte Spieler bekommen mit jeder neuen Partie eine neue Markt-Beobachtung (gleitendes Mittel)
        return rec is None or (rec.get("geschaetzt") and m.get("id") not in rec.get("markt_ids", []))

    def beobachte(m, seite, r_impl, anker):
        nonlocal neu, markt
        key = key_fuer(m, seite)
        rec = players.get(key)
        if not rec:
            rec = {"geschaetzt": True, "n_markt": 0, "n_erg": 0, "quelle": "markt", "anker": anker,
                   "erstellt": datetime.date.today().isoformat()}
            players[key] = rec
            neu += 1
        if m.get("id") in rec.setdefault("markt_ids", []):
            return
        rec["markt_ids"] = (rec["markt_ids"] + [m.get("id")])[-20:]
        rec["markt_werte"] = (rec.get("markt_werte", []) + [round(r_impl, 1)])[-MAX_MARKT:]
        neu_berechnen(rec)
        # beste Ankerqualität merken (direkt > indirekt > basis)
        rang = {"direkt": 0, "indirekt": 1, "basis": 2}
        if rang.get(anker, 3) < rang.get(rec.get("anker"), 3):
            rec["anker"] = anker
        rec["n_markt"] = rec.get("n_markt", 0) + 1
        markt += 1

    def stufe(zulassen, anker, nur_neue=False):
        treffer = 0
        for m in matches:
            if not m.get("quoten"):
                continue
            for seite, anders in (("a", "b"), ("b", "a")):
                if not unbekannt(m, seite):
                    continue
                if nur_neue and key_fuer(m, seite) in players:
                    continue                    # Schätzwerte nicht gegenseitig hochschaukeln
                g = players.get(key_fuer(m, anders))
                if not g or not zulassen(g):
                    continue
                r_g, p = used_elo(g, m.get("belag"), P), markt_p(m, seite)
                if r_g is None or p is None:
                    continue
                beobachte(m, seite, r_g - 400 * math.log10(1 / p - 1), anker)
                treffer += 1
        return treffer

    echt = lambda g: not g.get("geschaetzt") or g.get("n_erg", 0) >= 3
    stufe(echt, "direkt")
    for _ in range(3):                          # Ketten: A kennt B, B kennt C ...
        if not stufe(lambda g: g.get("geschaetzt") and g.get("elo") is not None, "indirekt", nur_neue=True):
            break
    # Basis: beide Spieler unbekannt
    ch_elos = sorted(e for m in matches if "challenger" in norm(f"{m.get('turnier')} {m.get('kategorie') or ''}")
                     for s_ in ("a", "b") for r in [players.get(m.get(s_))] if r and not r.get("geschaetzt")
                     for e in [used_elo(r, m.get("belag"), P)] if e)
    # Unbekannte stehen meist unter den bekannten Challenger-Spielern: Mittel der direkt geschätzten Spieler
    # (Markt gegen bekannten Gegner), sonst unteres Zehntel der bekannten Challenger-Spieler; höchstens BASIS_ELO
    direkt = sorted(r["elo"] for r in players.values() if r.get("geschaetzt") and r.get("anker") == "direkt" and r.get("elo"))
    if len(direkt) >= 8:
        basis = min(direkt[len(direkt) // 2], BASIS_ELO)
    else:
        basis = min(ch_elos[len(ch_elos) // 10], BASIS_ELO) if len(ch_elos) >= 8 else BASIS_ELO
    for m in matches:
        if not m.get("quoten") or players.get(key_fuer(m, "a")) or players.get(key_fuer(m, "b")):
            continue
        p = markt_p(m, "a")
        if p is None:
            continue
        d = 400 * math.log10(p / (1 - p))       # Elo-Abstand, den der Markt sieht
        beobachte(m, "a", basis + d / 2, "basis")
        beobachte(m, "b", basis - d / 2, "basis")
    for _ in range(3):                          # Basis-Schätzungen als Anker für weitere Unbekannte nutzen
        if not stufe(lambda g: g.get("geschaetzt") and g.get("elo") is not None, "indirekt", nur_neue=True):
            break
    print(f"  Basis-Elo für zwei unbekannte Challenger-Spieler: {basis:.0f}")

    # Namen in Spielplan und gesehenen Partien auf die DB-Schlüssel umstellen (sonst erst am nächsten Tag erkannt)
    umbenannt = 0
    for m in matches:
        for seite in ("a", "b"):
            if m.get(seite) in players:
                m[seite + "InDb"] = True
            else:
                k = key_fuer(m, seite)
                if k in players:
                    if m["id"] in seen and seen[m["id"]].get(seite) == m.get(seite):
                        seen[m["id"]][seite] = k
                    m[seite], m[seite + "InDb"] = k, True
                    umbenannt += 1
    unbekannt_rest = sorted({m.get(s_) for m in matches for s_ in ("a", "b") if m.get(s_) not in players})

    # 2) Elo aus Ergebnissen (nur für geschätzte Spieler; Tennis-Abstract-Spieler pflegt Tennis Abstract)
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    for fid, fx in sorted(seen.items(), key=lambda kv: str(kv[1].get("start"))):
        if fid in verarbeitet:
            continue
        a, b = fx.get("a"), fx.get("b")
        ra, rb = players.get(a), players.get(b)
        if not ra or not rb or not (ra.get("geschaetzt") or rb.get("geschaetzt")):
            continue
        st = ts(fx.get("start"))
        if not st or st > jetzt - datetime.timedelta(hours=2):
            continue
        tip = dict(fx, id=fid)
        sieger = runden_sieger(tip, seen)
        if not sieger:
            if st < jetzt - datetime.timedelta(days=4):
                verarbeitet.add(fid)           # nicht mehr klärbar (z. B. Endspiel)
            continue
        ea, eb = used_elo(ra, None, P), used_elo(rb, None, P)
        if ea is None or eb is None:
            verarbeitet.add(fid)
            continue
        pa = 1 / (1 + 10 ** ((eb - ea) / 400))
        sa = 1.0 if sieger == "A" else 0.0
        for rec, s_, p_ in ((ra, sa, pa), (rb, 1 - sa, 1 - pa)):
            if rec.get("geschaetzt"):
                rec.setdefault("elo_markt", rec["elo"] - rec.get("erg_delta", 0))
                d = rec.get("erg_delta", 0) + K_ERGEBNIS * (s_ - p_)
                rec["erg_delta"] = round(max(-ERG_DELTA_MAX, min(ERG_DELTA_MAX, d)), 1)
                neu_berechnen(rec)
                rec["n_erg"] = rec.get("n_erg", 0) + 1
        verarbeitet.add(fid)
        erg += 1

    # 3) Durchschnittswerte für fehlende Aufschlag-/Returnwerte
    avg = stats_durchschnitt(players)

    save("players.json", players)
    save("stats_avg.json", avg)
    mj = load("matches.json", {})
    if mj.get("partien") is not None and not mj.get("demo"):
        mj["partien"] = matches
        save("matches.json", mj)
        save("fixtures_seen.json", seen, indent=0)
        meta = load("meta.json", {})
        meta["unbekannte_namen"] = unbekannt_rest
        save("meta.json", meta)
    state["verarbeitet"] = sorted(verarbeitet & set(seen))
    save("extra_state.json", state, indent=0)
    n_gesch = sum(1 for p in players.values() if p.get("geschaetzt"))
    print(f"Namen im Spielplan zugeordnet: {umbenannt}, weiterhin unbekannt: {len(unbekannt_rest)} {unbekannt_rest[:15]}")
    print(f"Geschätzte Spieler: {neu} neu, {markt} Quoten-Beobachtungen, {erg} Ergebnis-Updates, "
          f"insgesamt {n_gesch} geschätzt. Durchschnitt aus {avg.get('hard', {}).get('n', 0)} Spielern (Hard).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
