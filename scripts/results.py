"""Trägt Ergebnisse und Schlussquoten für protokollierte Value-Tipps nach -> tips_log.json + bilanz.json

Ergebnis (Reihenfolge):
  0. SportsAPIPro (sap_events.json / sap_map.json aus sportsapipro.py): Sieger bzw. Absage/Walkover direkt.
  1. Rundenlogik (kostenlos): Wer nach dem Tipp-Spiel im selben Turnier erneut im Spielplan steht,
     hat gewonnen. Bei Qualifikationen zählt auch das Hauptfeld.
  2. Absage: Status "abgesagt" aus dem Spielplan -> Tipp ungültig (Einsatz zurück).
  3. OddsPapi /v4/settlements (kostet je 1 Anfrage): nur für Tipps, die 30 h nach Beginn noch offen
     sind (v. a. Endspiele), höchstens ERGEBNIS_ANFRAGEN je Lauf und nur, wenn Kontingent übrig ist.
Schlussquote (CLV): /v4/historical-odds (laut OddsPapi kontingentfrei), letzte Quote vor Spielbeginn.
"""
import os, sys, json, datetime
from common import load, save, config, norm, spieler_bilanz_add, DATA, NameMatcher, name_einheitlich
import fetch_odds as fo
from sportsapipro import ergebnis as sap_ergebnis, aufgabe as sap_aufgabe

ERGEBNIS_ANFRAGEN = 2
H2H_STAND_STANDARD = "2026-10-13"   # letztes ANALYSE-Datum des zuletzt exportierten Excel-Stands
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


def api_sieger(fid, smap, sap):
    """Sieger aus den SportsAPIPro-Spieldaten: 'A', 'B', 'V' oder None."""
    z = smap.get(fid)
    r = sap_ergebnis(sap.get(str(z["sap"]))) if z else None
    if r in ("H", "A"):
        heim_ist_a = not z.get("tausch")
        return "A" if (r == "H") == heim_ist_a else "B"
    return r


def api_aufgabe(fid, smap, sap):
    """True, wenn die Partie laut Spieldaten durch Aufgabe endete."""
    z = smap.get(fid)
    return bool(z) and sap_aufgabe(sap.get(str(z["sap"])))


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
    time.sleep(max(0, 5.5 - (time.time() - fo._last_call[0])))  # Cooldown dieses Endpunkts: 5000 ms
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
        if t.get("storniert"):                  # Daten korrigiert, danach kein Value mehr -> zählt nicht
            continue
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


def quote_aus_verlauf(verlauf, fid, start):
    """Letzte Quote vor Spielbeginn aus quoten_verlauf.json, Durchschnitt über die Buchmacher -> (qa, qb) oder (None, None)."""
    v = (verlauf or {}).get(fid) or {}
    qs = []
    for reihe in (v.get("bm") or {}).values():
        vor = [r for r in reihe if len(r) >= 3 and r[1] and r[2] and (not start or str(r[0]) < str(start)[:16] + "Z")]
        if vor:
            qs.append(vor[-1][1:3])
    if not qs:
        return None, None
    return round(sum(q[0] for q in qs) / len(qs), 3), round(sum(q[1] for q in qs) / len(qs), 3)


def archiv_schreiben(erg_alle, seen, prog, smap, sap, log):
    """Ergebnis-Archiv aller entschiedenen Partien -> docs/data/archiv/JJJJ-MM.json (+ index.json).
    Einträge werden nur ergänzt bzw. um den Satzstand vervollständigt, nie gelöscht."""
    ordner = DATA / "archiv"
    ordner.mkdir(exist_ok=True)
    tipps = {}
    for t in log.values():
        if t.get("storniert"):
            continue
        x = tipps.setdefault(t["id"], {"seite": t.get("wette"), "bm": []})
        x["bm"].append(t.get("buchmacher"))
    nm = NameMatcher(load("players.json", {}).keys(), load("name_map.json", {}))
    verlauf = load("quoten_verlauf.json", {})
    monate, neu = {}, 0
    # bestehende Monate laden und Namen vereinheitlichen ("Friend, Jay" -> "Jay Dylan Hara Friend")
    for pf in sorted(ordner.glob("????-??.json")):
        monate[pf.stem] = json.loads(pf.read_text(encoding="utf-8"))
        for fid, x in monate[pf.stem].items():
            if x.get("tipp") and fid not in tipps:      # Tipp inzwischen storniert
                x["tipp"], x["bm"] = None, None
            for s in ("a", "b"):
                x[s] = name_einheitlich(x.get(s), nm)
            if not x.get("qa") or not x.get("qb"):      # Quote nachtragen, falls sie erst nach der Prognose kam
                pr = prog.get(fid) or {}
                qa, qb = pr.get("qaM") or pr.get("qa"), pr.get("qbM") or pr.get("qb")
                if not (qa and qb):
                    qa, qb = quote_aus_verlauf(verlauf, fid, x.get("start"))
                if qa and qb:
                    x["qa"], x["qb"] = qa, qb
    for fid, e in erg_alle.items():
        start = str(e.get("start") or "")
        if len(start) < 7 or e.get("sieger") not in ("A", "B", "V"):
            continue
        m = start[:7]
        if m not in monate:
            pf = ordner / f"{m}.json"
            monate[m] = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else {}
        alt = monate[m].get(fid)
        pr, fx = prog.get(fid) or {}, seen.get(fid) or {}
        z = smap.get(fid)
        ev = sap.get(str(z["sap"])) if z else None
        satz = None
        if ev and ev.get("satz"):
            satz = [[y, x] if z.get("tausch") else [x, y] for x, y in ev["satz"]]
        if alt and (alt.get("satz") or not satz) and bool(alt.get("aufgabe")) == bool(e.get("aufgabe")):
            continue
        tp = tipps.get(fid)
        qa, qb = pr.get("qaM") or pr.get("qa"), pr.get("qbM") or pr.get("qb")
        if not (qa and qb):
            qa, qb = quote_aus_verlauf(verlauf, fid, start)
        monate[m][fid] = {
            "start": start, "turnier": pr.get("turnier") or fx.get("turnier"), "kat": pr.get("kategorie"),
            "belag": pr.get("belag") or (ev or {}).get("belag"), "a": name_einheitlich(pr.get("a") or e.get("a"), nm), "b": name_einheitlich(pr.get("b") or e.get("b"), nm),
            "qa": qa, "qb": qb, "p": pr.get("pFinal"),
            "sieger": e["sieger"], "aufgabe": bool(e.get("aufgabe")) or None, "satz": satz, "runde": (ev or {}).get("runde"),
            "tipp": tp["seite"] if tp else None, "bm": sorted(set(tp["bm"])) if tp else None,
        }
        neu += 0 if alt else 1
    for m, inhalt in monate.items():
        (ordner / f"{m}.json").write_text(json.dumps(inhalt, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    index = {}
    for pf in sorted(ordner.glob("????-??.json")):
        index[pf.stem] = len(json.loads(pf.read_text(encoding="utf-8")))
    (ordner / "index.json").write_text(json.dumps(index), encoding="utf-8")
    print(f"Ergebnis-Archiv: {neu} neue Partien, {sum(index.values())} insgesamt in {len(index)} Monaten")


def main():
    log = load("tips_log.json", {})
    seen = load("fixtures_seen.json", {})
    meta = load("oddspapi.json", {})
    smap, sap = load("sap_map.json", {}), load("sap_events.json", {})
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

        # Aufgabe: Partie nicht zu Ende gespielt -> Tipp zählt nicht (ungültig), auch nachträglich
        if api_aufgabe(fid, smap, sap):
            for t in tipps:
                if t.get("ergebnis") != "V" or not t.get("aufgabe"):
                    t["ergebnis"], t["ergebnisQuelle"], t["aufgabe"] = "V", "aufgabe", True
                    t.setdefault("sieger", api_sieger(fid, smap, sap))
                    neu_erg += 1
            continue

        # Ergebnis
        if all(t.get("ergebnis") for t in tipps):
            continue
        sieger, quelle = None, None
        st = (seen.get(fid) or {}).get("status")
        if st == 3:
            sieger, quelle = "V", "abgesagt"
        if not sieger:
            sieger, quelle = api_sieger(fid, smap, sap), "spieldaten"
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

    # Ergebnisse ALLER gesehenen Partien (für "Meine Wetten" auf der Website) – nur Folgerunde/Absage, keine Anfragen.
    # Enthält keine persönlichen Daten: Partie-ID, Spieler, Sieger.
    erg_alle = load("ergebnisse.json", {})
    for fid, fx in seen.items():
        if fid in erg_alle:
            continue
        st = ts(fx.get("start"))
        if not st or st > jetzt - datetime.timedelta(hours=2):
            continue
        sieger = "V" if fx.get("status") == 3 else (api_sieger(fid, smap, sap) or runden_sieger(dict(fx, id=fid), seen))
        if sieger:
            erg_alle[fid] = {"sieger": sieger, "a": fx.get("a"), "b": fx.get("b"), "start": fx.get("start")}
    for fid, e in erg_alle.items():              # Aufgabe markieren (zählt nicht als richtig/falsch)
        if e.get("sieger") in ("A", "B") and api_aufgabe(fid, smap, sap):
            e["aufgabe"] = True
    for t in log.values():                      # Settlements aus der Bilanz mitnehmen
        if t.get("sieger") and t["id"] not in erg_alle:
            erg_alle[t["id"]] = {"sieger": t["sieger"], "a": t.get("a"), "b": t.get("b"), "start": t.get("start")}
    grenze = (jetzt - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    erg_alle = {k: v for k, v in erg_alle.items() if str(v.get("start", "")) >= grenze}
    save("ergebnisse.json", erg_alle, indent=0)

    # Test-Varianten (B/C) abrechnen – gleiche Regeln wie die Bilanz (Absage/Walkover/Aufgabe = ungültig)
    vlog = load("varianten_tips.json", {})
    neu_v = 0
    for t in vlog.values():
        if t.get("ergebnis"):
            continue
        e = erg_alle.get(t["id"])
        if not e or e.get("sieger") not in ("A", "B", "V"):
            continue
        t["ergebnis"] = "V" if e["sieger"] == "V" or e.get("aufgabe") else ("W" if e["sieger"] == t["wette"] else "L")
        if t.get("letzteQuote") and t.get("erstQuote"):
            t["clv"] = round(t["erstQuote"] / t["letzteQuote"] - 1, 4)
        neu_v += 1
    if vlog:
        save("varianten_tips.json", vlog, indent=0)
        print(f"Varianten: {neu_v} Tipps abgerechnet, insgesamt {len(vlog)}")

    # Außenseiter- und Bilanz-Signale abrechnen (gleiche Regeln)
    for datei in ("aussenseiter_tips.json", "bilanz_tips.json", "signale_log.json"):
        alog = load(datei, {})
        for t in alog.values():
            if t.get("ergebnis"):
                continue
            e = erg_alle.get(t["id"])
            if not e or e.get("sieger") not in ("A", "B", "V"):
                continue
            t["ergebnis"] = "V" if e["sieger"] == "V" or e.get("aufgabe") else ("W" if e["sieger"] == t["wette"] else "L")
            if t.get("letzteQuote") and t.get("erstQuote"):
                t["clv"] = round(t["erstQuote"] / t["letzteQuote"] - 1, 4)
        if alog:
            save(datei, alog, indent=0)

    # H2H automatisch erweitern: jedes entschiedene Spiel NACH dem Excel-Stichtag (letztes Datum in ANALYSE)
    # einmal zählen. Ältere Spiele stecken bereits in h2h.json aus der Excel.
    hw = load("h2h_web.json", {"stand": H2H_STAND_STANDARD, "spiele": {}})
    neu_h2h = 0
    for fid, e in erg_alle.items():
        if fid in hw["spiele"] or e.get("sieger") not in ("A", "B") or not e.get("a") or not e.get("b"):
            continue
        if str(e.get("start", ""))[:10] <= str(hw.get("stand", "")):
            continue
        sieger, verlierer = (e["a"], e["b"]) if e["sieger"] == "A" else (e["b"], e["a"])
        hw["spiele"][fid] = {"sieger": sieger, "verlierer": verlierer, "start": e.get("start")}
        neu_h2h += 1
    paare = {}
    for sp in hw["spiele"].values():
        x, y = sorted([sp["sieger"], sp["verlierer"]])
        rec = paare.setdefault(f"{x}|{y}", [0, 0])
        rec[0 if sp["sieger"] == x else 1] += 1
    hw["paare"] = paare
    save("h2h_web.json", hw)
    if neu_h2h:
        print(f"H2H: {neu_h2h} neue Spiele erfasst (seit Excel-Stand {hw.get('stand')}), {len(paare)} Paarungen ergänzt")

    # Spieler-Check fortschreiben (Favorit/Außenseiter, Quotenbereiche): jedes entschiedene Spiel mit Quote NACH dem
    # Excel-Stichtag einmal zählen. Quote = Durchschnitt der Buchmacher vor Spielbeginn (prognosen.json).
    prog = load("prognosen.json", {})
    verlauf_sc = load("quoten_verlauf.json", {})
    sw = {"stand": hw.get("stand"), "spiele": load("player_stats_web.json", {}).get("spiele", {})}
    sw["spiele"] = {k: v for k, v in sw["spiele"].items() if str(v.get("start", ""))[:10] > str(sw["stand"] or "")
                    and not (erg_alle.get(k) or {}).get("aufgabe")}
    for fid, e in erg_alle.items():
        pr = prog.get(fid)
        if fid in sw["spiele"] or not pr or e.get("sieger") not in ("A", "B") or e.get("aufgabe"):
            continue
        if str(e.get("start", ""))[:10] <= str(sw.get("stand") or ""):
            continue
        qa, qb = pr.get("qaM") or pr.get("qa"), pr.get("qbM") or pr.get("qb")
        if not qa or not qb:
            qa, qb = quote_aus_verlauf(verlauf_sc, fid, e.get("start"))
        if not qa or not qb:
            continue
        # gleiche Partie -> gleiche Reihenfolge A/B; Namen aus der Prognose (Spieler-DB-Namen)
        sw["spiele"][fid] = {"a": pr.get("a") or e["a"], "b": pr.get("b") or e["b"], "qa": qa, "qb": qb, "sieger": e["sieger"], "start": e.get("start")}
    nm = NameMatcher(load("players.json", {}).keys(), load("name_map.json", {}))
    for sp in sw["spiele"].values():
        sp["a"], sp["b"] = name_einheitlich(sp["a"], nm), name_einheitlich(sp["b"], nm)
    spieler = {}
    for sp in sw["spiele"].values():
        spieler_bilanz_add(spieler, sp["a"], sp["qa"], sp["qb"], sp["sieger"] == "A")
        spieler_bilanz_add(spieler, sp["b"], sp["qb"], sp["qa"], sp["sieger"] == "B")
    sw["spieler"] = spieler
    save("player_stats_web.json", sw, indent=0)
    print(f"Spieler-Check: {len(sw['spiele'])} Spiele seit Excel-Stand {sw.get('stand')}, {len(spieler)} Spieler fortgeschrieben")

    # Pinnacle-Schlussquote je Partie (kostenlos über historical-odds, 5 s je Abruf): scharfe Referenz für CLV und
    # die Jahresauswertung aller Varianten/Signale. Nur Partien, die seit mind. 1 Std. laufen, max. 3 Tage zurück.
    if hat_key:
        import time as _t
        t0, n_pin, scharf = _t.time(), 0, cfg.get("scharf_buchmacher", "pinnacle")
        offen_pin = sorted((fid for fid, pr in prog.items() if pr.get("pinSchluss") is None and not pr.get("pinVersucht")
                            and ts(pr.get("start")) and jetzt - datetime.timedelta(days=3) < ts(pr.get("start")) < jetzt - datetime.timedelta(hours=1)),
                           key=lambda f: (prog[f].get("kategorie") != "ATP", prog[f].get("start")))
        pin_fehler = []
        for fid in offen_pin:
            if n_pin >= 150 or _t.time() - t0 > 600 or len(pin_fehler) >= 6:
                break
            try:
                sq = schlussquoten(fid, ts(prog[fid]["start"]), [scharf], meta)
            except SystemExit as e:
                pin_fehler.append(str(e)[:160])
                print("  Pinnacle-Schlussquote nicht abrufbar:", e)
                _t.sleep(8 if "429" in str(e) else 1)
                if "404" in str(e):
                    prog[fid]["pinVersucht"] = True
                continue
            n_pin += 1
            prog[fid]["pinVersucht"] = True
            if sq.get(scharf):
                prog[fid]["pinSchluss"] = list(sq[scharf])
        st_ = load("meta.json", {})
        st_["pin_schluss"] = {"stand": jetzt.strftime("%Y-%m-%dT%H:%MZ"), "abgerufen": n_pin, "offen": len(offen_pin),
                              "fehler": len(pin_fehler), "fehler_beispiele": sorted(set(pin_fehler))[:3]}
        save("meta.json", st_)
        if n_pin or pin_fehler:
            (DATA / "prognosen.json").write_text(json.dumps(prog, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"Pinnacle-Schlussquoten: {sum(1 for f in offen_pin[:n_pin] if prog[f].get('pinSchluss'))} von {n_pin} Partien")
        # Signale: CLV gegen die Pinnacle-Schlussquote
        for datei in ("signale_log.json",):
            sl = load(datei, {})
            for x in sl.values():
                pr = prog.get(x.get("id")) or {}
                if pr.get("pinSchluss") and x.get("pinSchluss") is None:
                    x["pinSchluss"] = pr["pinSchluss"][0] if x.get("wette") == "A" else pr["pinSchluss"][1]
            save(datei, sl, indent=0)

    try:
        archiv_schreiben(erg_alle, seen, prog, smap, sap, log)
    except Exception as ex:                      # Archiv darf das Update nie blockieren
        print("Ergebnis-Archiv übersprungen:", ex)

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
