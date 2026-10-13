"""Einmaliger Test der SportsAPIPro-Tennis-Schnittstelle (Free-Tarif: 100 Abfragen/Tag).

Prüft mit max. ~10 Abfragen:
  1. Spielplan nach Datum – sind ATP und Challenger dabei?
  2. Match-Statistiken eines beendeten Spiels – gibt es Aufschlag-/Returnwerte?
  3. H2H – gibt es (inzwischen) einen Endpunkt?
  4. Letzte Spiele eines Spielers
Schreibt nur Strukturinfos ins Log, nie den Key. Ändert keine Dateien im Repo.
"""
import os, sys, json, datetime, urllib.request, urllib.error

KEY = os.environ.get("SPORTSAPIPRO_KEY", "").strip()
if not KEY:
    print("SPORTSAPIPRO_KEY fehlt – bitte als GitHub-Secret anlegen.")
    sys.exit(1)

BASES = ["https://api.sportsapipro.com/v2/tennis", "https://v2.tennis.sportsapipro.com"]
MAX_ANFRAGEN = 12
anfragen = 0
base_ok = None


def get(pfad):
    """GET mit x-api-key. Probiert beim ersten Mal beide Hosts. Liefert (status, json|None)."""
    global anfragen, base_ok
    for base in ([base_ok] if base_ok else BASES):
        if anfragen >= MAX_ANFRAGEN:
            print("  (Testbudget erreicht)")
            return None, None
        anfragen += 1
        url = base + pfad
        req = urllib.request.Request(url, headers={"x-api-key": KEY, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                limits = {k: v for k, v in r.headers.items() if "limit" in k.lower() or "remaining" in k.lower()}
                if limits:
                    print(f"  Kontingent-Header: {limits}")
                base_ok = base
                return r.status, json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:200]
            print(f"  {pfad} @ {base.split('//')[1].split('/')[0]} -> HTTP {e.code}: {text}")
            if e.code in (401, 403, 429):
                return e.code, None
        except Exception as e:
            print(f"  {pfad} -> Fehler: {type(e).__name__}: {e}")
    return None, None


def finde_events(obj):
    """Sucht rekursiv die erste Liste von Partien (Dicts mit homeTeam/awayTeam o. ä.)."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and any(k in obj[0] for k in ("homeTeam", "home", "homePlayer", "player1")):
            return obj
        for x in obj:
            r = finde_events(x)
            if r:
                return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = finde_events(v)
            if r:
                return r
    return []


def name(t):
    if isinstance(t, dict):
        return t.get("name") or t.get("shortName") or t.get("slug") or "?"
    return str(t)


def turnier(e):
    t = e.get("tournament") or {}
    cat = (t.get("category") or {}).get("name", "") if isinstance(t, dict) else ""
    return f"{cat} | {name(t)}" if cat else name(t)


def status(e):
    s = e.get("status")
    return (s.get("type") or s.get("description")) if isinstance(s, dict) else str(s)


print("=== 1) Spielplan nach Datum ===")
heute = datetime.date.today()
gestern = heute - datetime.timedelta(days=1)
events = []
for pfad in (f"/schedule/{gestern.isoformat()}", f"/api/schedule/{gestern.isoformat()}", "/today"):
    st, js = get(pfad)
    if st in (401, 403):
        print("Key wird nicht akzeptiert – Abbruch.")
        sys.exit(1)
    if js is not None:
        events = finde_events(js)
        print(f"  {pfad}: HTTP {st}, Top-Level-Felder: {list(js)[:10] if isinstance(js, dict) else type(js).__name__}, Partien: {len(events)}")
        if events:
            print(f"  Felder einer Partie: {sorted(events[0])[:40]}")
            break

if not events:
    print("Keine Partien gefunden – Rohantwort (Ausschnitt):")
    print(json.dumps(js, ensure_ascii=False)[:800] if js is not None else "  keine")
    sys.exit(0)

einzel = [e for e in events if "doubles" not in turnier(e).lower() and "/" not in name(e.get("homeTeam", e.get("home", "")))]
kat = {}
for e in einzel:
    t = turnier(e).lower()
    k = "challenger" if "challenger" in t else "itf" if "itf" in t else "wta" if "wta" in t or "women" in t else "atp" if "atp" in t else "sonstige"
    kat[k] = kat.get(k, 0) + 1
print(f"  Einzel: {len(einzel)} – nach Kategorie: {kat}")
for e in [x for x in einzel if "challenger" in turnier(x).lower()][:3] + [x for x in einzel if "atp" in turnier(x).lower() and "challenger" not in turnier(x).lower()][:2]:
    print(f"   · {turnier(e)}: {name(e.get('homeTeam', e.get('home')))} – {name(e.get('awayTeam', e.get('away')))} [{status(e)}]")

# Beendetes Challenger-Spiel bevorzugen
fertig = [e for e in einzel if str(status(e)).lower() in ("finished", "ended", "ft", "closed")]
probe = next((e for e in fertig if "challenger" in turnier(e).lower()), fertig[0] if fertig else einzel[0])
eid = probe.get("id")
print(f"\n=== 2) Match-Statistiken (Partie {eid}: {name(probe.get('homeTeam', probe.get('home')))} – {name(probe.get('awayTeam', probe.get('away')))}, {turnier(probe)}) ===")
for pfad in (f"/match/{eid}/statistics", f"/api/match/{eid}/statistics", f"/event/{eid}/statistics"):
    st, js = get(pfad)
    if js is not None:
        namen = []

        def sammle(o):
            if isinstance(o, dict):
                if "name" in o and ("home" in o or "homeValue" in o):
                    namen.append(f"{o['name']}: {o.get('home')} / {o.get('away')}")
                for v in o.values():
                    sammle(v)
            elif isinstance(o, list):
                for v in o:
                    sammle(v)
        sammle(js)
        print(f"  {pfad}: HTTP {st}, {len(namen)} Kennzahlen")
        for n in namen[:30]:
            print(f"   · {n}")
        if not namen:
            print("  Rohantwort (Ausschnitt): " + json.dumps(js, ensure_ascii=False)[:600])
        break

print("\n=== 3) H2H ===")
for pfad in (f"/match/{eid}/h2h", f"/event/{eid}/h2h"):
    st, js = get(pfad)
    if js is not None:
        print(f"  {pfad}: HTTP {st} – Ausschnitt: {json.dumps(js, ensure_ascii=False)[:400]}")
        break
else:
    print("  kein H2H-Endpunkt erreichbar")

print("\n=== 4) Letzte Spiele eines Spielers ===")
pid = (probe.get("homeTeam") or probe.get("home") or {}).get("id") if isinstance(probe.get("homeTeam") or probe.get("home"), dict) else None
if pid:
    st, js = get(f"/teams/{pid}/events/last/0")
    ev = finde_events(js) if js is not None else []
    print(f"  Spieler {pid}: HTTP {st}, {len(ev)} Partien"
          + (f", älteste: {ev[0].get('startTimestamp')} neueste: {ev[-1].get('startTimestamp')}" if ev else ""))
else:
    print("  keine Spieler-ID in den Partiedaten")

print(f"\nVerbrauchte Abfragen: {anfragen}")
