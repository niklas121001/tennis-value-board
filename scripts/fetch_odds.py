"""Holt Spielplan + Siegwetten-Quoten (ATP & Challenger) von OddsPapi -> docs/data/matches.json

Benötigt die Umgebungsvariable ODDSPAPI_KEY.
Anfragen pro Lauf: 1 (Spielplan) + 1 je 3 Buchmacher. Einmalig zusätzlich: sports, bookmakers, markets.
Vor jedem Lauf wird das Kontingent über /v4/account geprüft (kostenlos).
"""
import os, re, sys, json, time, math, datetime, urllib.request, urllib.parse
from common import load, save, config, norm, NameMatcher, detect_surface

BASE = os.environ.get("ODDSPAPI_BASE", "https://api.oddspapi.io/v4")
KEY = os.environ.get("ODDSPAPI_KEY", "")
_last_call = [0.0]
calls = []


def api(path, **params):
    wait = 1.15 - (time.time() - _last_call[0])  # Cooldown 1000 ms je Endpunkt
    if wait > 0:
        time.sleep(wait)
    params["apiKey"] = KEY
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "TennisValueApp"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"OddsPapi {path}: HTTP {e.code} – {msg}")
    finally:
        _last_call[0] = time.time()
    if path != "account":
        calls.append(path)
    return json.loads(body)


def konto(acc, cfg):
    """Verbrauch/Limit aus /account – Feldnamen tolerant lesen."""
    flat = {}
    def walk(x, pre=""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k.lower())
        elif isinstance(x, (int, float)):
            flat[pre] = x
    walk(acc)
    used = next((flat[k] for k in flat if ("count" in k or "used" in k) and "limit" not in k), None)
    limit = next((flat[k] for k in flat if "limit" in k), None) or cfg["anfragen_limit_monat"]
    if used is None:
        # nur Feldnamen mit Zahlenwerten ausgeben – keine Kontodaten (Protokoll ist öffentlich)
        print("  /account: Zahlenfelder", sorted(flat))
    return used, limit


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------- Einmalige Metadaten
def ensure_meta(cfg, meta):
    if not meta.get("sportId"):
        sports = api("sports")
        tennis = [s for s in sports if str(s.get("sportName", "")).lower() == "tennis" or s.get("slug") == "tennis"]
        if not tennis:
            raise SystemExit("Sportart Tennis bei OddsPapi nicht gefunden")
        meta["sportId"] = tennis[0]["sportId"]
        print("Tennis sportId:", meta["sportId"])

    wanted = cfg["buchmacher"]
    if set(meta.get("buchmacher_wunsch", [])) != set(wanted) or not meta.get("buchmacher"):
        books = api("bookmakers")
        if isinstance(books, dict):
            books = books.get("data") or list(books.values())
        key = lambda x: re.sub(r"[^a-z0-9]", "", str(x).lower())  # Ziffern behalten (bet365 != 18bet)
        found, missing = {}, []
        for w in wanted:
            kw = key(w)
            hit = [b for b in books if key(b.get("slug", "")) == kw or key(b.get("bookmakerName", "")) == kw]
            # Länder-Varianten (z. B. 'bwin.de', 'winamax.de'): nur Slugs, die mit dem Namen BEGINNEN, .de bevorzugt
            hit = hit or sorted([b for b in books if key(b.get("slug", "")).startswith(kw)],
                                key=lambda b: (0 if b.get("slug", "").lower().endswith(("de", ".de", "-de")) else 1, len(b.get("slug", ""))))
            if hit:
                found[w] = hit[0]["slug"]
            else:
                missing.append(w)
                print(f"  '{w}' nicht gefunden. Ähnliche Slugs:", [b.get("slug") for b in books if kw[:4] in key(b.get("slug", ""))][:10])
        meta["buchmacher"] = found
        meta["buchmacher_wunsch"] = wanted
        meta["buchmacher_fehlen"] = missing
        print("Buchmacher:", found, "fehlen:", missing)

    if not meta.get("markets_geprueft"):
        markets = api("markets")
        if isinstance(markets, dict):
            markets = markets.get("data") or list(markets.values())
        sid = str(meta["sportId"])
        tennis = [m for m in markets if str(m.get("sportId")) == sid]
        print(f"Märkte gesamt: {len(markets)}, davon Tennis: {len(tennis)}")
        if markets and not tennis:
            print("  Beispiel-Markt (Felder):", json.dumps(markets[0], ensure_ascii=False)[:400])
        for m in [m for m in tennis if "total" not in str(m.get("marketType", "")).lower()][:8]:
            print("  Tennis-Markt:", m.get("marketId"), "|", m.get("marketName"), "|", m.get("marketType"), "|",
                  m.get("period"), "| hc", m.get("handicap"), "| n", m.get("marketLength") or len(m.get("outcomes") or []),
                  "|", [o.get("outcomeName") for o in (m.get("outcomes") or [])])
        def n_out(m):
            return m.get("marketLength") or len(m.get("outcomes") or [])
        def is_winner(m):
            n = f"{m.get('marketName', '')} {m.get('marketType', '')}".lower()
            bad = any(w in n for w in ("handicap", "total", "over", "under", "set ", "game", "exact", "correct", "odd", "even", "tie"))
            good = any(w in n for w in ("winner", "moneyline", "match result", "to win", "12", "head to head", "1x2", "full time result"))
            return good and not bad and n_out(m) == 2 and not m.get("playerProp") and not m.get("handicap")
        cands = [m for m in tennis if is_winner(m)]
        meta["siegermarkt_ids"] = [m["marketId"] for m in cands]
        if cands:
            mk = cands[0]
            outs = mk.get("outcomes") or []
            o1 = next((o for o in outs if str(o.get("outcomeName")).lower() in ("1", "home")), outs[0] if outs else {})
            o2 = next((o for o in outs if o is not o1), outs[-1] if outs else {})
            meta.update(marketId=mk["marketId"], marketName=mk.get("marketName"),
                        outcome1=o1.get("outcomeId"), outcome2=o2.get("outcomeId"))
            print(f"Siegermarkt: {mk['marketId']} {mk.get('marketName')} ({o1.get('outcomeName')}/{o2.get('outcomeName')})")
        else:
            print("Kein Siegermarkt in /markets erkannt – Erkennung erfolgt direkt aus den Quoten.")
        meta["markets_geprueft"] = True
    return meta


# ------------------------------------------------------------- Quoten auslesen
def price(outcome):
    players = (outcome or {}).get("players") or {}
    for p in players.values():
        if p.get("active", True) is not False and p.get("price"):
            return float(p["price"])
    return None


GEFUNDEN = {}   # welche Markt-IDs als Siegermarkt verwendet wurden (fürs Protokoll)
BEISPIEL = []


def extract(bm_odds, meta):
    """Liefert (Quote Spieler 1, Quote Spieler 2) aus dem Siegermarkt eines Buchmachers."""
    markets = bm_odds.get("markets") or {}
    if isinstance(markets, list):
        markets = {str(m.get("marketId")): m for m in markets}
    mid = str(meta.get("marketId")) if meta.get("marketId") is not None else None
    if mid and mid in markets and meta.get("outcome1") is not None:
        outs = markets[mid].get("outcomes") or {}
        qa, qb = price(outs.get(str(meta["outcome1"]))), price(outs.get(str(meta["outcome2"])))
        if qa and qb:
            GEFUNDEN[mid] = GEFUNDEN.get(mid, 0) + 1
            return qa, qb
    # Fallback: Markt mit genau 2 Ausgängen, der nach Siegwette aussieht
    bekannte = {str(x) for x in meta.get("siegermarkt_ids", [])}
    best = None
    for k, mk in markets.items():
        outs = mk.get("outcomes") or {}
        if len(outs) != 2:
            continue
        bid = str(mk.get("bookmakerMarketId", "")).lower()
        if any(w in bid for w in ("total", "handicap", "spread", "over", "under", "set", "game", "point")):
            continue
        boid = {}
        for oid, o in outs.items():
            for pl in (o.get("players") or {}).values():
                boid[oid] = str(pl.get("bookmakerOutcomeId", "")).lower()
                break
        score = (3 if k in bekannte else 0) + (2 if any(w in bid for w in ("moneyline", "winner", "match", "ml", "12")) else 0) \
            + (2 if set(boid.values()) & {"home", "away", "1", "2"} else 0)
        if score >= 2 and (best is None or score > best[0]):
            best = (score, k, outs, boid)
    if best:
        _, k, outs, boid = best
        ids = sorted(outs.keys())
        home = next((i for i, v in boid.items() if v in ("home", "1")), ids[0])
        away = next((i for i in ids if i != home), ids[-1])
        qa, qb = price(outs[home]), price(outs[away])
        if qa and qb:
            GEFUNDEN[k] = GEFUNDEN.get(k, 0) + 1
            return qa, qb
    if len(BEISPIEL) < 2 and markets:
        BEISPIEL.append({k: {"bookmakerMarketId": v.get("bookmakerMarketId"), "outcomes": len(v.get("outcomes") or {})}
                         for k, v in list(markets.items())[:15]})
    return None, None


def relevant(fx, cfg):
    t = norm(f"{fx.get('categoryName', '')} {fx.get('tournamentName', '')}")
    f = cfg["turnier_filter"]
    if any(norm(x) in t.split() or norm(x) in t for x in f["ausschliessen"]):
        return False
    if not any(norm(x) in t for x in f["einschliessen"]):
        return False
    p1, p2 = fx.get("participant1Name") or "", fx.get("participant2Name") or ""
    return "/" not in p1 and "/" not in p2  # Doppel aussortieren


def display_name(fx):
    """'Shanghai, China Men Singles' + 'ATP' -> 'ATP Shanghai'; Challenger -> 'Olbia Challenger'"""
    import re
    cat, tn = fx.get("categoryName") or "", fx.get("tournamentName") or ""
    tn = re.sub(r"(?i)\b(men'?s?|singles?)\b", "", tn)
    quali = bool(re.search(r"(?i)qualif|quali", tn))
    tn = re.sub(r"(?i)[,-]?\s*qualif\w*|quali\w*", "", tn)
    tn = tn.split(",")[0].strip(" -")
    if "challenger" in norm(cat) or "challenger" in norm(tn):
        tn = re.sub(r"(?i)\s*(atp\s*)?challenger\s*", " ", tn).strip()
        name = f"{tn} Challenger"
    elif any(s in norm(tn) for s in ("australian open", "french open", "roland garros", "wimbledon", "us open")):
        name = tn
    else:
        name = tn if norm(cat) in norm(tn) else f"{cat} {tn}".strip()
    return name + (" Q" if quali else "")


def main():
    if not KEY:
        raise SystemExit("ODDSPAPI_KEY fehlt (GitHub: Settings → Secrets → Actions)")
    cfg = config()
    meta = load("oddspapi.json", {})
    state = load("meta.json", {})

    acc = api("account")
    used_api, limit = konto(acc, cfg)
    monat = now_utc().strftime("%Y-%m")
    eigen = meta.setdefault("verbrauch", {}).get(monat, 0)   # eigener Zähler je Kalendermonat
    used = max(used_api or 0, eigen)
    # Budget gleichmäßig auf die restlichen Läufe im Monat verteilen
    import calendar
    heute = now_utc()
    tage_rest = calendar.monthrange(heute.year, heute.month)[1] - heute.day + 1
    laeufe_rest = max(1, tage_rest * cfg.get("laeufe_pro_tag", 1))
    budget = (limit - cfg.get("anfragen_reserve", 0) - used) // laeufe_rest
    budget -= 0 if meta.get("markets_geprueft") else 3
    n_books = max(0, budget - 1)  # Anfragen für Quoten (1 geht an den Spielplan)
    print(f"Kontingent: {used}/{limit} verbraucht (API: {used_api}, eigener Zähler: {eigen}), "
          f"Budget dieses Laufs: 1 Spielplan + bis zu {n_books} Quoten-Anfragen")
    if n_books == 0:
        state["quoten_hinweis"] = f"Kontingent fast aufgebraucht ({used}/{limit}) – Update übersprungen"
        save("meta.json", state)
        print(state["quoten_hinweis"])
        return 0
    try:
        return run(cfg, meta, state, n_books)
    finally:
        meta["verbrauch"][monat] = eigen + len(calls)
        meta["verbrauch"] = {k: v for k, v in meta["verbrauch"].items() if k >= monat}
        save("oddspapi.json", meta)


def run(cfg, meta, state, n_books):

    meta = ensure_meta(cfg, meta)
    save("oddspapi.json", meta)

    # 1) Spielplan der nächsten Tage (max. 10 Tage laut API)
    # Zeitfenster: ab jetzt bis Ende des Folgetages (deutsche Zeit), bei tage=2 also heute + morgen
    from zoneinfo import ZoneInfo
    berlin = ZoneInfo("Europe/Berlin")
    start = now_utc()
    heute = start.astimezone(berlin).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (heute + datetime.timedelta(days=min(9, cfg.get("tage", 2)))).astimezone(datetime.timezone.utc)
    fixtures = api("fixtures", sportId=meta["sportId"], **{"from": iso(start), "to": iso(end)})
    if isinstance(fixtures, dict):
        fixtures = fixtures.get("data") or fixtures.get("fixtures") or []
    fixtures = [fx for fx in fixtures if relevant(fx, cfg) and iso(start)[:16] <= str(fx.get("startTime", ""))[:16] < iso(end)[:16]]
    tids = sorted({fx["tournamentId"] for fx in fixtures})
    print(f"{len(fixtures)} relevante Partien in {len(tids)} Turnieren")

    # 2) Quoten. Gratis-Tarif: 1 Buchmacher und max. 5 Turniere je Anfrage.
    #    Turniere in 5er-Gruppen: ATP zuerst, dann Challenger nach Anzahl Partien.
    #    Budget: Gruppe für Gruppe, je Gruppe Buchmacher in der Reihenfolge aus config.json.
    slugs = [meta["buchmacher"][b] for b in cfg["buchmacher"] if b in meta["buchmacher"]]
    anz, ist_ch = {}, {}
    for fx in fixtures:
        t = fx["tournamentId"]
        anz[t] = anz.get(t, 0) + 1
        ist_ch[t] = "challenger" in norm(f"{fx.get('categoryName', '')} {fx.get('tournamentName', '')}")
    tids = sorted(tids, key=lambda t: (ist_ch[t], -anz[t]))
    gruppen = [tids[i:i + cfg.get("turniere_pro_anfrage", 5)] for i in range(0, len(tids), cfg.get("turniere_pro_anfrage", 5))]
    auftraege = [(g, s) for g in gruppen for s in slugs][:n_books]
    if len(auftraege) < len(gruppen) * len(slugs):
        print(f"Budget reicht für {len(auftraege)} von {len(gruppen) * len(slugs)} Quoten-Anfragen "
              f"({len(gruppen)} Turniergruppen × {len(slugs)} Buchmacher) – hintere Challenger/Buchmacher fehlen heute")
    odds = {}
    for gruppe, slug in auftraege:
        res = api("odds-by-tournaments", tournamentIds=",".join(map(str, gruppe)), bookmaker=slug)
        if isinstance(res, dict):
            res = res.get("data") or list(res.values())
        for fx in res:
            for slug, bo in (fx.get("bookmakerOdds") or {}).items():
                if bo.get("bookmakerIsActive") is False or bo.get("suspended"):
                    continue
                qa, qb = extract(bo, meta)
                if qa and qb:
                    odds.setdefault(fx["fixtureId"], {})[slug] = [qa, qb]

    # 3) Zusammenbauen
    players = load("players.json")
    matcher = NameMatcher(players.keys(), load("name_map.json", {}))
    turniere = load("turniere.json", {}).get("turniere", {})
    history = load("history.json", [])
    slug2name = {v: k for k, v in meta["buchmacher"].items()}
    out, unbekannt = [], set()
    for fx in sorted(fixtures, key=lambda x: x.get("startTime", "")):
        o = odds.get(fx["fixtureId"], {})  # auch Partien ohne Quoten: Modell rechnet trotzdem
        ra, rb = fx.get("participant1Name"), fx.get("participant2Name")
        a, b = matcher.match(ra), matcher.match(rb)
        for raw, hit in ((ra, a), (rb, b)):
            if not hit:
                unbekannt.add(raw)
        tn = display_name(fx)
        belag, quelle = detect_surface(tn, turniere, history)
        out.append({
            "id": fx["fixtureId"], "start": fx.get("startTime"), "turnier": tn,
            "kategorie": fx.get("categoryName"), "belag": belag, "belagQuelle": quelle,
            "a": a or ra, "b": b or rb, "aRoh": ra, "bRoh": rb,
            "aInDb": bool(a), "bInDb": bool(b), "hatQuoten": bool(o),
            "quoten": {slug2name.get(s, s): q for s, q in o.items()},
        })

    save("matches.json", {"stand": iso(now_utc()), "partien": out})
    acc = api("account")
    v, l = konto(acc, cfg)
    monat = now_utc().strftime("%Y-%m")
    v = max(v or 0, meta.get("verbrauch", {}).get(monat, 0) + len(calls))
    state.update(quoten_update=iso(now_utc()), quoten_hinweis=None,
                 kontingent={"verbraucht": v, "limit": l},
                 unbekannte_namen=sorted(unbekannt), buchmacher_fehlen=meta.get("buchmacher_fehlen", []))
    save("meta.json", state)
    print("Verwendete Siegermärkte (Markt-ID: Anzahl):", GEFUNDEN or "keine")
    if not GEFUNDEN and BEISPIEL:
        print("Beispiel-Märkte eines Buchmachers:", json.dumps(BEISPIEL, ensure_ascii=False)[:1500])
    print(f"{len(out)} Partien gespeichert ({sum(1 for x in out if x['hatQuoten'])} mit Quoten), {len(unbekannt)} unbekannte Namen, Anfragen: {calls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
