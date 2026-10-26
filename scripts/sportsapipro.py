"""Spieldaten von SportsAPIPro (Tennis V2): Ergebnisse, Belag je Partie, H2H – und Match-Statistiken sammeln.

Free-Tarif: 100 Abfragen pro Tag (Reset 00:00 UTC). Verbrauch pro Lauf:
  1. Spielplan nach Datum (gestern, heute, morgen + bis zu 2 ältere Tage mit offenen Partien): 3–5 Abfragen.
     Eine Abfrage liefert alle Partien des Tages samt Status, Sieger, Satzständen und Belag (groundType).
  2. H2H für jede kommende Partie des Boards mit Quoten – jede Partie nur einmal: ca. 20–60 Abfragen.
  3. Match-Statistiken beendeter Spiele (Aufschlag/Return) mit dem restlichen Kontingent, Spieler mit
     anstehenden Partien zuerst. Werden nur gesammelt (sap_stats.json) – das Modell nutzt sie noch nicht.
Es bleiben immer RESERVE Abfragen frei (z. B. für einen manuellen Test).

Schreibt: sap_events.json (Partien-Cache), sap_map.json (OddsPapi-Partie -> SportsAPIPro-Partie),
h2h_api.json, sap_stats.json, sportsapipro.json (Verbrauch) und ergänzt matches.json um Belag und sapId.
Die Daten stammen sehr wahrscheinlich von Sofascore – nur für den privaten Gebrauch.
"""
import os, re, sys, json, datetime, urllib.request, urllib.error
from common import load, save, NameMatcher

KEY = os.environ.get("SPORTSAPIPRO_KEY", "").strip()
BASE = "https://api.sportsapipro.com/v2/tennis"
# Cloudflare sperrt die Standard-Kennung von Python (Fehler 1010)
UA = "TennisValueBoard/1.0 (+https://github.com)"
TAGESLIMIT = 100
RESERVE = 5
CACHE_TAGE = 7          # beendete/alte Partien so lange im Cache halten
STATS_TAGE = 3          # Statistiken nur für Spiele der letzten Tage nachholen
MITTAG_RESERVE = 30     # so viele Abfragen bleiben nach dem Frühlauf für den Mittagslauf
KATEGORIEN = {"atp", "challenger"}

jetzt = datetime.datetime.now(datetime.timezone.utc)
rest = [None]           # letzter bekannter Stand x-ratelimit-remaining
anfragen = [0]


def frei():
    r = rest[0] if rest[0] is not None else TAGESLIMIT - anfragen[0]
    return r - RESERVE


def get(pfad):
    if frei() <= 0:
        return None
    anfragen[0] += 1
    req = urllib.request.Request(BASE + pfad, headers={"x-api-key": KEY, "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            rem = r.headers.get("x-ratelimit-remaining")
            if rem is not None and rem.strip().lstrip("-").isdigit():
                rest[0] = int(rem)
            return json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:160]
        print(f"  {pfad}: HTTP {e.code} {text}")
        if e.code == 429:
            rest[0] = 0
        if e.code in (401, 403) and "1010" not in text:
            raise SystemExit("SportsAPIPro: Key wird nicht akzeptiert")
    except Exception as e:
        print(f"  {pfad}: {type(e).__name__}: {e}")
    return None


def finde(obj, test):
    """Erste Liste von Dicts (rekursiv), deren erstes Element test() erfüllt."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and test(obj[0]):
            return obj
        for x in obj:
            r = finde(x, test)
            if r:
                return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = finde(v, test)
            if r:
                return r
    return []


def belag_von(gt):
    g = str(gt or "").lower()
    if "clay" in g:
        return "clay"
    if "grass" in g:
        return "grass"
    if any(x in g for x in ("hard", "synthetic", "carpet", "indoor", "acrylic")):
        return "hard"
    return None


def iso(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def zeit(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def kompakt(e):
    """Partie aus der API -> kleines Dict. None für Doppel/fremde Kategorien."""
    t = e.get("tournament") or {}
    kat = str((t.get("category") or {}).get("name", "")).strip()
    tn = str(t.get("name", ""))
    h, a = e.get("homeTeam") or {}, e.get("awayTeam") or {}
    hn, an = str(h.get("name", "")), str(a.get("name", ""))
    if kat.lower() not in KATEGORIEN or "/" in hn or "/" in an or re.search(r"doubles|mixed", tn, re.I):
        return None
    st = e.get("status") or {}
    satz = []
    hs, as_ = e.get("homeScore") or {}, e.get("awayScore") or {}
    for i in range(1, 6):
        k = f"period{i}"
        if k in hs and k in as_:
            satz.append([hs[k], as_[k]])
    # Spieldauer: Sofascore liefert je Satz die Dauer in Sekunden unter time.period1..5 (nicht immer vorhanden)
    tm = e.get("time") or {}
    sek = [tm.get(f"period{i}") for i in range(1, 6) if isinstance(tm.get(f"period{i}"), (int, float))]
    dauer = round(sum(sek) / 60) if sek and len(sek) >= len(satz) and sum(sek) > 600 else None
    return {"id": e.get("id"), "start": iso(e["startTimestamp"]) if e.get("startTimestamp") else None, "min": dauer,
            "kat": kat, "turnier": tn, "belag": belag_von(e.get("groundType")), "gt": e.get("groundType"),
            "h": hn, "a": an, "hId": h.get("id"), "aId": a.get("id"),
            "hL": (h.get("country") or {}).get("alpha2"), "aL": (a.get("country") or {}).get("alpha2"),
            "st": str(st.get("type", "")).lower(), "desc": str(st.get("description", "")),
            "w": e.get("winnerCode"), "runde": (e.get("roundInfo") or {}).get("name"), "satz": satz}


def aufgabe(ev):
    """True, wenn die Partie durch Aufgabe (Retirement/Disqualifikation) endete – nicht zu Ende gespielt."""
    return bool(ev) and ev.get("st") == "finished" and bool(re.search(r"retir|ret\.|aufgabe|default|abandon", ev.get("desc", ""), re.I))


def ergebnis(ev):
    """'H', 'A', 'V' (ungültig: Absage/Walkover) oder None (noch offen)."""
    if not ev:
        return None
    d = ev.get("desc", "").lower()
    if ev.get("st") in ("canceled", "cancelled") or "walkover" in d or "w/o" in d:
        return "V"
    if ev.get("st") == "finished" and ev.get("w") in (1, 2):
        return "H" if ev["w"] == 1 else "A"
    return None


# ---------------------------------------------------------------- Statistiken
def zahl(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def stat_teile(item, seite):
    """(Wert, Gesamt) eines Statistik-Eintrags, z. B. 'First serve points: 45/71 (63%)' -> (45, 71)."""
    v, t = zahl(item.get(seite + "Value")), zahl(item.get(seite + "Total"))
    if v is not None:
        return v, t
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)", str(item.get(seite, "")))
    if m:
        return float(m.group(1)), float(m.group(2))
    return zahl(item.get(seite)), None


FELDER = {  # API-Name -> (Kurzname Wert, Kurzname Gesamt)
    "aces": ("ace", None), "double faults": ("df", None),
    "first serve": ("first_in", "svpt"), "first serve points": ("first_won", "first_in2"),
    "second serve points": ("second_won", "second_pts"), "service games played": ("sv_gms", None),
    "break points saved": ("bp_saved", "bp_faced"),
    "first serve return points": ("ret1_won", "ret1_pts"), "second serve return points": ("ret2_won", "ret2_pts"),
    "return games played": ("ret_gms", None),
}


def statistik(js):
    """Gesamt-Statistik (Periode ALL) -> ({Kurzname: Wert} Heim, {…} Gast)."""
    perioden = finde(js, lambda x: "groups" in x or "period" in x)
    ziel = next((p for p in perioden if str(p.get("period", "")).upper() == "ALL"), perioden[0] if perioden else None)
    if not ziel:
        return None
    h, a = {}, {}
    def sammle(o):
        if isinstance(o, dict):
            n = str(o.get("name", "")).strip().lower()
            if n in FELDER and ("home" in o or "homeValue" in o):
                kv, kt = FELDER[n]
                for seite, ziel_d in (("home", h), ("away", a)):
                    if kv in ziel_d:
                        continue          # erster Treffer (Gesamt) zählt
                    v, t = stat_teile(o, seite)
                    if v is not None:
                        ziel_d[kv] = v
                    if kt and t is not None:
                        ziel_d[kt] = t
            for x in o.values():
                sammle(x)
        elif isinstance(o, list):
            for x in o:
                sammle(x)
    sammle(ziel)
    return (h, a) if h and a else None


# ---------------------------------------------------------------- Ablauf
def main():
    if not KEY:
        print("SPORTSAPIPRO_KEY fehlt – übersprungen")
        return 0
    meta = load("sportsapipro.json", {})
    heute_utc = jetzt.strftime("%Y-%m-%d")
    if meta.get("tag") == heute_utc and meta.get("rest") is not None:
        rest[0] = meta["rest"]     # Stand aus einem früheren Lauf heute (bis zur ersten Antwort)

    cache = load("sap_events.json", {})
    smap = load("sap_map.json", {})
    seen = load("fixtures_seen.json", {})
    mj = load("matches.json", {"partien": []})

    # 1) Spielplan: gestern, heute, morgen + ältere Tage mit noch offenen Partien
    tage = [(jetzt + datetime.timedelta(days=d)).strftime("%Y-%m-%d") for d in (-1, 0, 1)]
    offen = sorted({str(ev.get("start", ""))[:10] for ev in cache.values()
                    if ergebnis(ev) is None and ev.get("start") and ev["start"][:10] < tage[0]
                    and ev["start"][:10] >= (jetzt - datetime.timedelta(days=5)).strftime("%Y-%m-%d")}, reverse=True)
    n_ev = 0
    for tag in tage + offen[:2]:
        js = get(f"/schedule/{tag}")
        if js is None:
            continue
        for e in finde(js, lambda x: "homeTeam" in x):
            k = kompakt(e)
            if k and k["id"] is not None:
                cache[str(k["id"])] = k
                n_ev += 1
    grenze = (jetzt - datetime.timedelta(days=CACHE_TAGE)).strftime("%Y-%m-%d")
    cache = {k: v for k, v in cache.items() if str(v.get("start", "")) >= grenze}

    # 2) OddsPapi-Partien den API-Partien zuordnen (Namen + Startzeit ±20 h)
    evs = list(cache.values())
    def zuordnen(a, b, start, aroh=None, broh=None):
        s = zeit(start)
        if not s or not a or not b:
            return None
        kand = [e for e in evs if e.get("start") and abs((zeit(e["start"]) - s).total_seconds()) < 20 * 3600]
        if not kand:
            return None
        nm = NameMatcher({x for e in kand for x in (e["h"], e["a"])})
        ma = nm.match(a) or (aroh and nm.match(aroh))
        mb = nm.match(b) or (broh and nm.match(broh))
        if not ma or not mb or ma == mb:
            return None
        treffer = [e for e in kand if {e["h"], e["a"]} == {ma, mb}]
        if not treffer:
            return None
        e = min(treffer, key=lambda e: abs((zeit(e["start"]) - s).total_seconds()))
        return {"sap": e["id"], "tausch": e["h"] != ma}

    roh = {m["id"]: (m.get("aRoh"), m.get("bRoh")) for m in mj.get("partien", [])}
    neu_map = 0
    for fid, fx in seen.items():
        if fid in smap:
            continue
        z = zuordnen(fx.get("a"), fx.get("b"), fx.get("start"), *roh.get(fid, (None, None)))
        if z:
            smap[fid] = z
            neu_map += 1
    for m in mj.get("partien", []):
        if m["id"] not in smap:
            z = zuordnen(m.get("a"), m.get("b"), m.get("start"), m.get("aRoh"), m.get("bRoh"))
            if z:
                smap[m["id"]] = z
                neu_map += 1
    smap = {k: v for k, v in smap.items() if k in seen or any(m["id"] == k for m in mj.get("partien", []))}

    # Belag je Partie + sapId in matches.json
    n_belag = 0
    board_namen = set()
    laender = load("laender.json", {})        # DB-Name -> Ländercode (ISO alpha2), für Flaggen auf der Website
    for m in mj.get("partien", []):
        z = smap.get(m["id"])
        ev = cache.get(str(z["sap"])) if z else None
        if not ev:
            continue
        m["sapId"] = ev["id"]
        la, lb = (ev.get("aL"), ev.get("hL")) if z.get("tausch") else (ev.get("hL"), ev.get("aL"))
        for seite, land in (("a", la), ("b", lb)):
            if land and len(str(land)) == 2:
                m["land" + seite.upper()] = str(land).upper()
                laender[m[seite]] = str(land).upper()
        if "qualif" in str(ev.get("turnier", "")).lower() or "qualif" in str(ev.get("runde") or "").lower():
            m["quali"] = True                # OddsPapi kennzeichnet Quali-Partien nicht – SportsAPIPro schon
        else:
            m.pop("quali", None)
        if ev.get("runde"):
            m["runde"] = ev["runde"]
        board_namen.update([ev["h"], ev["a"]])
        if ev.get("belag") and not mj.get("demo"):
            if m.get("belag") != ev["belag"]:
                print(f"  Belag {m.get('turnier')}: {m.get('belag')} ({m.get('belagQuelle')}) -> {ev['belag']} ({ev.get('gt')})")
            m["belag"], m["belagQuelle"] = ev["belag"], "spieldaten"
            n_belag += 1
    # Form/Belastung je Board-Spieler aus dem Partien-Cache (ATP + Challenger der letzten 7 Tage)
    def form(pid, vor, ev_jetzt):
        basis = re.sub(r",?\s*qualifying.*$", "", ev_jetzt.get("turnier", ""), flags=re.I).strip().lower()
        spiele = [e for e in evs if pid in (e.get("hId"), e.get("aId")) and e.get("id") != ev_jetzt["id"]
                  and e.get("start") and zeit(e["start"]) < vor and (vor - zeit(e["start"])).days < 7
                  and ergebnis(e) in ("H", "A")]
        if not spiele:
            return {"spiele7": 0}
        letzte = max(spiele, key=lambda e: e["start"])
        quali = any("qualif" in e.get("turnier", "").lower() and e["turnier"].lower().startswith(basis) for e in spiele) \
            and "qualif" not in ev_jetzt.get("turnier", "").lower()
        siege = sum(1 for e in spiele if (ergebnis(e) == "H") == (e.get("hId") == pid))
        mins = [e.get("min") for e in spiele if isinstance(e.get("min"), (int, float))]
        return {"spiele7": len(spiele), "saetze7": sum(len(e.get("satz") or []) for e in spiele),
                "games7": sum(int(x) + int(y) for e in spiele for x, y in (e.get("satz") or []) if isinstance(x, (int, float)) and isinstance(y, (int, float))),
                "min7": sum(mins) if mins else None, "minN": len(mins),
                "letztesMin": letzte.get("min"), "letztesGames": sum(int(x) + int(y) for x, y in (letzte.get("satz") or []) if isinstance(x, (int, float)) and isinstance(y, (int, float))),
                "dreisatz7": sum(1 for e in spiele if len(e.get("satz") or []) >= 3), "siege7": siege,
                "letztes": letzte["start"], "quali": quali}
    # Spielerverlauf (dauerhaft): letztes Spiel, Aufgabe im letzten Spiel, letztes Spiel je Belag
    hist = load("letzte_spiele.json", {"seit": heute_utc, "spieler": {}})
    for e in sorted(evs, key=lambda e: e.get("start") or ""):
        if ergebnis(e) not in ("H", "A") or not e.get("start"):
            continue
        for seite, pid_, name in (("H", e.get("hId"), e.get("h")), ("A", e.get("aId"), e.get("a"))):
            if pid_ is None:
                continue
            r = hist["spieler"].setdefault(str(pid_), {"name": name, "belag": {}})
            if e["start"] >= r.get("letztes", ""):
                r["letztes"] = e["start"]
                r["name"] = name
                # Aufgabe: Partie durch Aufgabe beendet und dieser Spieler hat verloren
                r["aufgabe"] = e["start"][:10] if aufgabe(e) and ergebnis(e) != seite else None
            if e.get("belag") and e["start"] > r["belag"].get(e["belag"], ""):
                r["belag"][e["belag"]] = e["start"]
    save("letzte_spiele.json", hist, indent=0)
    beobachtet_seit = zeit(hist["seit"] + "T00:00:00Z")
    BELAG_DE = {"hard": "Hard", "clay": "Sand", "grass": "Rasen"}

    def warnungen(pid_, start, belag):
        r = hist["spieler"].get(str(pid_))
        if not r or not r.get("letztes"):
            return []
        w = []
        letztes = zeit(r["letztes"])
        if letztes and letztes < start:
            tage = (start - letztes).days
            if r.get("aufgabe"):
                w.append({"typ": "aufgabe", "text": f"Aufgabe im letzten Spiel ({r['aufgabe'][8:10]}.{r['aufgabe'][5:7]}.)"})
            if tage > 30:
                w.append({"typ": "pause", "text": f"Pause: letztes Spiel vor {tage} Tagen"})
        if belag and (start - beobachtet_seit).days > 30:
            auf_b = zeit(r["belag"].get(belag, "")) if r["belag"].get(belag) else None
            andere = [zeit(t) for b, t in r["belag"].items() if b != belag]
            kuerzlich_anders = any(t and 0 <= (start - t).days <= 14 for t in andere)
            if kuerzlich_anders and (not auf_b or (start - auf_b).days > 30):
                w.append({"typ": "belag", "text": f"Belagwechsel: erstes {BELAG_DE.get(belag, belag)}-Spiel seit über 30 Tagen"})
        return w

    n_form = 0
    for m in mj.get("partien", []):
        z = smap.get(m["id"])
        ev = cache.get(str(z["sap"])) if z else None
        s_ = zeit(m.get("start"))
        if not ev or not s_:
            continue
        fh, fa = form(ev.get("hId"), s_, ev), form(ev.get("aId"), s_, ev)
        m["form"] = {"a": fa, "b": fh} if z["tausch"] else {"a": fh, "b": fa}
        wh, wa = warnungen(ev.get("hId"), s_, m.get("belag")), warnungen(ev.get("aId"), s_, m.get("belag"))
        ws = [dict(x, seite="A") for x in (wa if z["tausch"] else wh)] + [dict(x, seite="B") for x in (wh if z["tausch"] else wa)]
        if ws:
            m["warnungen"] = ws
        else:
            m.pop("warnungen", None)
        n_form += 1

    if not mj.get("demo"):
        save("matches.json", mj, indent=0)
        if laender:
            save("laender.json", laender, indent=0)

    # 3) H2H für kommende Board-Partien mit Quoten – je Partie einmal
    h2h = load("h2h_api.json", {"paare": {}, "abrufe": {}})
    kommend = sorted((m for m in mj.get("partien", []) if m.get("sapId") and m.get("quoten")
                      and zeit(m.get("start")) and zeit(m["start"]) > jetzt
                      and str(m["sapId"]) not in h2h["abrufe"]), key=lambda m: m["start"])
    n_h2h = 0
    for m in kommend:
        js = get(f"/match/{m['sapId']}/h2h")
        if js is None:
            if frei() <= 0:
                break
            continue
        duel = (js.get("data") or {}).get("teamDuel") if isinstance(js, dict) else None
        hw, aw = int((duel or {}).get("homeWins") or 0), int((duel or {}).get("awayWins") or 0)
        wa, wb = (aw, hw) if smap[m["id"]]["tausch"] else (hw, aw)
        h2h["paare"].pop(f"{m['b']}|{m['a']}", None)
        h2h["paare"][f"{m['a']}|{m['b']}"] = [wa, wb]
        h2h["abrufe"][str(m["sapId"])] = {"paar": f"{m['a']}|{m['b']}", "datum": heute_utc}
        n_h2h += 1
    g60 = (jetzt - datetime.timedelta(days=60)).strftime("%Y-%m-%d")
    h2h["abrufe"] = {k: v for k, v in h2h["abrufe"].items() if v.get("datum", "") >= g60}
    h2h["quelle"] = "SportsAPIPro (Gesamtbilanz aller Duelle, alle Turnierstufen)"
    save("h2h_api.json", h2h)

    # 4) Match-Statistiken beendeter Spiele sammeln (für die spätere Fortschreibung der Aufschlag-/Returnwerte)
    stats = load("sap_stats.json", {})
    sgrenze = (jetzt - datetime.timedelta(days=STATS_TAGE)).strftime("%Y-%m-%d")
    fertig = [e for e in cache.values() if ergebnis(e) in ("H", "A") and str(e["id"]) not in stats
              and str(e.get("start", "")) >= sgrenze and len(e.get("satz", [])) >= 2]
    def prio(e):
        p = 0
        if e["h"] in board_namen or e["a"] in board_namen:
            p += 4           # Spieler mit anstehender Partie zuerst
        if "qualif" not in e["turnier"].lower():
            p += 2
        if e["kat"].lower() == "atp":
            p += 1
        return (-p, e["start"])
    n_stats, fehler = 0, 0
    # Frühlauf: Kontingent für den Mittagslauf übrig lassen (Spielplan + H2H neuer Partien)
    fuer_spaeter = MITTAG_RESERVE if jetzt.hour < 8 else 0
    for e in sorted(fertig, key=prio):
        if frei() - fuer_spaeter <= 0:
            break
        js = get(f"/match/{e['id']}/statistics")
        if js is None:
            fehler += 1
            if fehler >= 3:
                print("  Statistiken: 3 Fehler in Folge – Abbruch für diesen Lauf")
                break
            continue
        fehler = 0
        st = statistik(js)
        stats[str(e["id"])] = {"start": e["start"], "kat": e["kat"], "turnier": e["turnier"], "belag": e["belag"],
                               "h": e["h"], "a": e["a"], "hId": e["hId"], "aId": e["aId"], "w": e["w"],
                               "hs": st[0] if st else None, "as": st[1] if st else None}
        n_stats += 1
    g400 = (jetzt - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    stats = {k: v for k, v in stats.items() if str(v.get("start", "")) >= g400}
    save("sap_stats.json", stats, indent=0)

    save("sap_events.json", cache, indent=0)
    save("sap_map.json", smap, indent=0)
    meta.update({"tag": heute_utc, "rest": rest[0], "letzterLauf": jetzt.strftime("%Y-%m-%dT%H:%MZ")})
    meta.setdefault("verbrauch", {})
    meta["verbrauch"][heute_utc] = meta["verbrauch"].get(heute_utc, 0) + anfragen[0]
    meta["verbrauch"] = dict(sorted(meta["verbrauch"].items())[-30:])
    save("sportsapipro.json", meta)

    ohne = [m for m in mj.get("partien", []) if not m.get("sapId")]
    print(f"SportsAPIPro: {anfragen[0]} Abfragen, Rest heute {rest[0]}. Partien im Cache: {len(cache)} ({n_ev} geladen). "
          f"Zugeordnet: {len(mj.get('partien', [])) - len(ohne)}/{len(mj.get('partien', []))} Board-Partien "
          f"({neu_map} neu). Belag gesetzt: {n_belag}. H2H abgerufen: {n_h2h} (offen {len(kommend) - n_h2h}). "
          f"Statistiken: {n_stats} neu, {len(stats)} gesamt.")
    for m in ohne[:8]:
        print(f"  nicht zugeordnet: {m.get('turnier')}: {m.get('a')} – {m.get('b')} ({m.get('start')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
