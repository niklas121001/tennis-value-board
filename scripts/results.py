"""Trägt Ergebnisse und Schlussquoten für protokollierte Value-Tipps nach -> tips_log.json + bilanz.json

Ergebnis (Reihenfolge):
  1. Rundenlogik (kostenlos): Wer nach dem Tipp-Spiel im selben Turnier erneut im Spielplan steht,
     hat gewonnen. Bei Qualifikationen zählt auch das Hauptfeld.
  2. Absage: Status "abgesagt" aus dem Spielplan -> Tipp ungültig (Einsatz zurück).
  3. OddsPapi /v4/settlements (kostet je 1 Anfrage): nur für Tipps, die 30 h nach Beginn noch offen
     sind (v. a. Endspiele), höchstens ERGEBNIS_ANFRAGEN je Lauf und nur, wenn Kontingent übrig ist.
Schlussquote (CLV): /v4/historical-odds (laut OddsPapi kontingentfrei), letzte Quote vor Spielbeginn.
"""
import os, sys, json, datetime
from common import load, save, config, norm
import fetch_odds as fo

ERGEBNIS_ANFRAGEN = 2
OFFEN_NACH_H = 30


def ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def haupt(turnier):
    t = str(turnier or "").strip()
    return t[:-2].strip() if t.endswith(" Q") else t


def runden_sieger(tip, seen):
    """Gewinner über Folgerunde bestimmen: 'A', 'B' oder None."""
    start = ts(tip.get("start"))
    if not start:
        return None
    t_tip = norm(tip.get("turnier"))
    t_haupt = norm(haupt(tip.get("turnier")))
    ids = {"A": tip.get("p1Id"), "B": tip.get("p2Id")}
    namen = {"A": norm(tip.get("a")), "B": norm(tip.get("b"))}
    gefunden = set()
    for fid, fx in seen.items():
        if fid == tip.get("id"):
            continue
        s = ts(fx.get("start"))
        if not s or s <= start or fx.get("status") == 3:
            continue
        t = norm(fx.get("turnier"))
        gleiches_turnier = (tip.get("tid") and fx.get("tid") == tip.get("tid")) or t == t_tip or t == t_haupt
        if not gleiches_turnier:
            continue
        fx_ids = {fx.get("p1Id"), fx.get("p2Id")} - {None}
        fx_namen = {norm(fx.get("a")), norm(fx.get("b"))}
        for seite in ("A", "B"):
            if (ids[seite] and ids[seite] in fx_ids) or namen[seite] in fx_namen:
                gefunden.add(seite)
    return gefunden.pop() if len(gefunden) == 1 else None


def settlement_sieger(tip, meta):
    """Gewinner über /v4/settlements (Siegermarkt). 'A', 'B', 'V' (ungültig) oder None."""
    res = fo.api("settlements", fixtureId=tip["id"])
    mk = (res.get("markets") or {}).get(str(meta.get("marketId")))
    if not mk:
        return None
    erg = {}
    for oid, o in (mk.get("outcomes") or {}).items():
        for pl in (o.get("players") or {}).values():
            erg[str(oid)] = str(pl.get("result", "")).upper()
            break
    r1, r2 = erg.get(str(meta.get("outcome1"))), erg.get(str(meta.get("outcome2")))
    if r1 == "WIN" or r2 == "LOSE":
        return "A"
    if r2 == "WIN" or r1 == "LOSE":
        return "B"
    if r1 in ("PUSH", "CANCELLED") or r2 in ("PUSH", "CANCELLED"):
        return "V"
    return None


def schlussquoten(fixture_id, start, slugs, meta):
    """{slug: (quote_spieler1, quote_spieler2)} – letzte Quote vor Spielbeginn je Buchmacher."""
    import time
    time.sleep(4)  # Cooldown dieses Endpunkts: 5000 ms
    res = fo.api("historical-odds", fixtureId=fixture_id, bookmakers=",".join(slugs[:3]))
    out = {}
    for slug, bo in (res.get("bookmakers") or {}).items():
        mk = (bo.get("markets") or {}).get(str(meta.get("marketId")))
        if not mk:
            continue
        q = []
        for oid in (meta.get("outcome1"), meta.get("outcome2")):
            o = (mk.get("outcomes") or {}).get(str(oid)) or {}
            best = None
            for eintraege in (o.get("players") or {}).values():
                for e in (eintraege if isinstance(eintraege, list) else [eintraege]):
                    t = ts(e.get("createdAt"))
                    if t and t < start and e.get("price") and (best is None or t > best[0]):
                        best = (t, float(e["price"]))
            q.append(best[1] if best else None)
        if q[0] and q[1]:
            out[slug] = tuple(q)
    return out


def bilanz(log):
    """Kennzahlen gesamt, je Buchmacher, je Monat, je Belag, ATP/Challenger."""
    def leer():
        return {"tipps": 0, "offen": 0, "gewonnen": 0, "verloren": 0, "ungueltig": 0,
                "einsatz_flat": 0.0, "gewinn_flat": 0.0, "einsatz_kelly": 0.0, "gewinn_kelly": 0.0,
                "clv_summe": 0.0, "clv_n": 0, "quote_summe": 0.0}
    gruppen = {}

    def add(gk, t):
        g = gruppen.setdefault(gk, leer())
        g["tipps"] += 1
        q = t["erstQuote"]
        erg = t.get("ergebnis")
        if t.get("clv") is not None and erg != "V":
            g["clv_summe"] += t["clv"]
            g["clv_n"] += 1
        if erg is None:
            g["offen"] += 1
            return
        if erg == "V":
            g["ungueltig"] += 1
            return
        k = t.get("kelly") or 0
        g["einsatz_flat"] += 1
        g["einsatz_kelly"] += k
        g["quote_summe"] += q
        if erg == "W":
            g["gewonnen"] += 1
            g["gewinn_flat"] += q - 1
            g["gewinn_kelly"] += k * (q - 1)
        else:
            g["verloren"] += 1
            g["gewinn_flat"] -= 1
            g["gewinn_kelly"] -= k

    for t in log.values():
        ch = "Challenger" if "challenger" in norm(f"{t.get('turnier')} {t.get('kategorie') or ''}") else "ATP"
        monat = str(t.get("start", ""))[:7]
        for bm in ("alle", t["buchmacher"]):
            add((bm, "gesamt"), t)
            add((bm, "monat:" + monat), t)
            add((bm, "belag:" + str(t.get("belag"))), t)
            add((bm, "art:" + ch), t)

    out = {}
    for (bm, k), g in gruppen.items():
        n = g["gewonnen"] + g["verloren"]
        g["trefferquote"] = g["gewonnen"] / n if n else None
        g["roi_flat"] = g["gewinn_flat"] / g["einsatz_flat"] if g["einsatz_flat"] else None
        g["roi_kelly"] = g["gewinn_kelly"] / g["einsatz_kelly"] if g["einsatz_kelly"] else None
        g["clv"] = g["clv_summe"] / g["clv_n"] if g["clv_n"] else None
        g["quote_avg"] = g["quote_summe"] / n if n else None
        for x in ("clv_summe", "clv_n", "quote_summe"):
            g.pop(x)
        out.setdefault(bm, {})[k] = g
    return out


def main():
    log = load("tips_log.json", {})
    seen = load("fixtures_seen.json", {})
    meta = load("oddspapi.json", {})
    cfg = config()
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    hat_key = bool(fo.KEY) and meta.get("marketId")
    name2slug = meta.get("buchmacher", {})

    # Budget für Settlements: nur wenn Monatskontingent Luft hat
    monat = jetzt.strftime("%Y-%m")
    verbraucht = meta.get("verbrauch", {}).get(monat, 0)
    frei = cfg["anfragen_limit_monat"] - cfg.get("anfragen_reserve", 0) - verbraucht
    settle_budget = min(ERGEBNIS_ANFRAGEN, max(0, frei)) if hat_key else 0

    neu_erg, neu_clv, settle_calls = 0, 0, 0
    nach_fixture = {}
    for key, t in log.items():
        nach_fixture.setdefault(t["id"], []).append(t)

    for fid, tipps in nach_fixture.items():
        start = ts(tipps[0].get("start"))
        if not start or start > jetzt - datetime.timedelta(hours=2):
            continue  # noch nicht (sicher) begonnen

        # Schlussquoten (kontingentfrei), einmal je Partie für alle Buchmacher dieser Tipps
        if hat_key and any(t.get("schlussQuote") is None and not t.get("clv_versucht") for t in tipps):
            slugs = [name2slug.get(t["buchmacher"], t["buchmacher"]) for t in tipps]
            try:
                sq = schlussquoten(fid, start, sorted(set(slugs)), meta)
            except SystemExit as e:
                print("  Schlussquote nicht abrufbar:", e)
                sq = {}
            for t in tipps:
                t["clv_versucht"] = True
                q = sq.get(name2slug.get(t["buchmacher"], t["buchmacher"]))
                if q:
                    t["schlussQuote"] = q[0] if t["wette"] == "A" else q[1]
                    t["clv"] = t["erstQuote"] / t["schlussQuote"] - 1
                    neu_clv += 1

        # Ergebnis
        if all(t.get("ergebnis") for t in tipps):
            continue
        sieger, quelle = None, None
        st = (seen.get(fid) or {}).get("status")
        if st == 3:
            sieger, quelle = "V", "abgesagt"
        if not sieger:
            sieger, quelle = runden_sieger(tipps[0], seen), "folgerunde"
        if not sieger and start < jetzt - datetime.timedelta(hours=OFFEN_NACH_H) and settle_calls < settle_budget:
            try:
                sieger, quelle = settlement_sieger(tipps[0], meta), "settlement"
                settle_calls += 1
            except SystemExit as e:
                print("  Settlement nicht abrufbar:", e)
                settle_calls += 1
        if sieger:
            for t in tipps:
                t["ergebnis"] = "V" if sieger == "V" else ("W" if sieger == t["wette"] else "L")
                t["sieger"] = sieger
                t["ergebnisQuelle"] = quelle
            neu_erg += 1

    # Kontingent-Zähler für Settlements fortschreiben
    if settle_calls:
        meta.setdefault("verbrauch", {})[monat] = verbraucht + settle_calls
        save("oddspapi.json", meta)

    save("tips_log.json", log, indent=0)
    b = bilanz(log)
    b["_stand"] = jetzt.strftime("%Y-%m-%dT%H:%MZ")
    save("bilanz.json", b)
    g = b.get("alle", {}).get("gesamt", {})
    print(f"Ergebnisse: {neu_erg} Partien neu entschieden, {neu_clv} Schlussquoten, {settle_calls} Settlement-Anfragen. "
          f"Bilanz: {g.get('gewonnen', 0)}-{g.get('verloren', 0)}, offen {g.get('offen', 0)}, "
          f"ROI flat {g['roi_flat']:+.1%}" if g.get("roi_flat") is not None else
          f"Ergebnisse: {neu_erg} neu, {neu_clv} Schlussquoten, {settle_calls} Settlement-Anfragen, noch keine abgeschlossenen Tipps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
