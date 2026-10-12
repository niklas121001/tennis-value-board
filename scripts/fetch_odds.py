"""Holt Spielplan + Siegwetten-Quoten (ATP & Challenger) von OddsPapi -> docs/data/matches.json

Benötigt die Umgebungsvariable ODDSPAPI_KEY.
Anfragen pro Lauf: 1 (Spielplan) + 1 je 3 Buchmacher. Einmalig zusätzlich: sports, bookmakers, markets.
Vor jedem Lauf wird das Kontingent über /v4/account geprüft (kostenlos).
"""
import os, sys, json, time, math, datetime, urllib.request, urllib.parse
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
        found, missing = {}, []
        for w in wanted:
            nw = norm(w).replace(" ", "")
            hit = [b for b in books if norm(b.get("slug", "")).replace(" ", "") == nw]
            hit = hit or [b for b in books if norm(b.get("bookmakerName", "")).replace(" ", "") == nw]
            # Länder-Varianten (z. B. 'bwin.de', 'winamax-de'): deutsche Variante bevorzugen
            hit = hit or sorted([b for b in books if nw in norm(b.get("slug", "")).replace(" ", "")],
                                key=lambda b: (0 if "de" in b.get("slug", "") else 1, len(b.get("slug", ""))))
            if hit:
                found[w] = hit[0]["slug"]
            else:
                missing.append(w)
        meta["buchmacher"] = found
        meta["buchmacher_wunsch"] = wanted
        meta["buchmacher_fehlen"] = missing
        print("Buchmacher:", found, "fehlen:", missing)

    if not meta.get("marketId"):
        markets = api("markets")
        sid = meta["sportId"]
        cands = [m for m in markets if m.get("sportId") == sid and m.get("marketLength") == 2
                 and not m.get("playerProp") and str(m.get("period", "")).lower() in ("fulltime", "ft", "match", "full time", "")
                 and not m.get("handicap")]
        def score(m):
            n = (str(m.get("marketName", "")) + " " + str(m.get("marketType", ""))).lower()
            return (("winner" in n) or ("moneyline" in n) or ("12" == str(m.get("marketType", ""))) or ("match" in n)) * 10 - len(n)
        cands.sort(key=score, reverse=True)
        if not cands:
            raise SystemExit("Kein Tennis-Siegermarkt gefunden")
        mk = cands[0]
        outs = mk.get("outcomes", [])
        o1 = next((o for o in outs if str(o.get("outcomeName")) in ("1", "Home", "home")), outs[0])
        o2 = next((o for o in outs if o is not o1), outs[-1])
        meta.update(marketId=mk["marketId"], marketName=mk.get("marketName"),
                    outcome1=o1["outcomeId"], outcome2=o2["outcomeId"])
        print(f"Siegermarkt: {mk['marketId']} {mk.get('marketName')} ({o1.get('outcomeName')}/{o2.get('outcomeName')})")
    return meta


# ------------------------------------------------------------- Quoten auslesen
def price(outcome):
    players = (outcome or {}).get("players") or {}
    for p in players.values():
        if p.get("active", True) is not False and p.get("price"):
            return float(p["price"])
    return None


def extract(bm_odds, meta):
    markets = bm_odds.get("markets") or {}
    mk = markets.get(str(meta["marketId"]))
    if mk:
        outs = mk.get("outcomes") or {}
        return price(outs.get(str(meta["outcome1"]))), price(outs.get(str(meta["outcome2"])))
    # Fallback: Markt mit 2 Ausgängen und 'moneyline'/'winner' in der Buchmacher-ID
    for mid, mk in markets.items():
        outs = mk.get("outcomes") or {}
        bid = str(mk.get("bookmakerMarketId", "")).lower()
        if len(outs) == 2 and any(w in bid for w in ("moneyline", "winner", "match")):
            o = sorted(outs.keys())
            return price(outs[o[0]]), price(outs[o[1]])
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
    used, limit = acc.get("request_count"), acc.get("request_limit") or cfg["anfragen_limit_monat"]
    n_books = max(1, len(cfg["buchmacher"]))
    need = 1 + math.ceil(n_books / 3) + (0 if meta.get("marketId") else 3)
    print(f"Kontingent: {used}/{limit} verbraucht, dieser Lauf braucht ca. {need}")
    if used is not None and used + need > limit - cfg.get("anfragen_reserve", 0):
        state["quoten_hinweis"] = f"Kontingent fast aufgebraucht ({used}/{limit}) – Update übersprungen"
        save("meta.json", state)
        print(state["quoten_hinweis"])
        return 0

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

    # 2) Quoten: bis zu 3 Buchmacher je Anfrage
    slugs = list(meta["buchmacher"].values())
    odds = {}
    for i in range(0, len(slugs), 3):
        if not tids:
            break
        chunk = slugs[i:i + 3]
        res = api("odds-by-tournaments", tournamentIds=",".join(map(str, tids)), bookmakers=",".join(chunk))
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
    state.update(quoten_update=iso(now_utc()), quoten_hinweis=None,
                 kontingent={"verbraucht": acc.get("request_count"), "limit": acc.get("request_limit")},
                 unbekannte_namen=sorted(unbekannt), buchmacher_fehlen=meta.get("buchmacher_fehlen", []))
    save("meta.json", state)
    print(f"{len(out)} Partien gespeichert ({sum(1 for x in out if x['hatQuoten'])} mit Quoten), {len(unbekannt)} unbekannte Namen, Anfragen: {calls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
