"""Einmal-Test (manuell): Liefert OddsPapi Pinnacle/Betfair-Quoten, und geht das kontingentfrei über historical-odds
auch für noch nicht begonnene Partien? Gibt nur Quoten/Slugs aus – keine Kontodaten (Protokoll ist öffentlich)."""
import re, sys, json, time, datetime
sys.path.insert(0, "scripts")
import fetch_odds as fo
from common import load

if not fo.KEY:
    raise SystemExit("kein ODDSPAPI_KEY")
books = json.load(open("/dev/null")) if False else fo.api("bookmakers")
if isinstance(books, dict):
    books = books.get("data") or list(books.values())
scharf = [b for b in books if re.search(r"pinnacle|betfair|sbobet|matchbook|smarkets|betdaq|circa|bookmaker\.eu", str(b.get("slug", "")) + " " + str(b.get("bookmakerName", "")), re.I)]
print("Buchmacher gesamt:", len(books))
print("Scharfe Buchmacher:", [(b.get("slug"), b.get("bookmakerName")) for b in scharf])
meta = load("oddspapi.json", {})
jetzt = datetime.datetime.now(datetime.timezone.utc)
partien = [m for m in load("matches.json", {}).get("partien", []) if m.get("start") and datetime.datetime.fromisoformat(m["start"].replace("Z", "+00:00")) > jetzt]
partien.sort(key=lambda m: (m.get("kategorie") != "ATP", m["start"]))
slugs = ["pinnacle", "winamax.de"]
print("Teste mit:", slugs)
for m in partien[:4]:
    time.sleep(5)
    try:
        res = fo.api("historical-odds", fixtureId=m["id"], bookmakers=",".join(slugs))
    except SystemExit as e:
        print(m["a"], "-", m["b"], "Fehler:", e); continue
    print(f"\n{m['start'][:16]} {m['turnier']}: {m['a']} – {m['b']}")
    for slug, bo in (res.get("bookmakers") or {}).items():
        mk = (bo.get("markets") or {}).get(str(meta.get("marketId")))
        if not mk:
            print("  ", slug, "kein Siegermarkt; Märkte:", list((bo.get("markets") or {}).keys())[:5]); continue
        q = []
        for oid in (meta.get("outcome1"), meta.get("outcome2")):
            o = (mk.get("outcomes") or {}).get(str(oid)) or {}
            ein = [e for es in (o.get("players") or {}).values() for e in (es if isinstance(es, list) else [es])]
            ein.sort(key=lambda e: str(e.get("createdAt")))
            q.append((len(ein), ein[-1].get("price") if ein else None, str(ein[-1].get("createdAt"))[:16] if ein else None))
        print("  ", slug, q)
# Betfair-Börse nur einzeln mit einer outcomeId
for m in partien[:2]:
    time.sleep(5)
    try:
        res = fo.api("historical-odds", fixtureId=m["id"], bookmakers="betfair-ex", outcomeId=str(meta.get("outcome1")))
        bo = (res.get("bookmakers") or {}).get("betfair-ex") or {}
        mk = (bo.get("markets") or {}).get(str(meta.get("marketId"))) or {}
        o = (mk.get("outcomes") or {}).get(str(meta.get("outcome1"))) or {}
        ein = [e for es in (o.get("players") or {}).values() for e in (es if isinstance(es, list) else [es])]
        ein.sort(key=lambda e: str(e.get("createdAt")))
        print("betfair-ex", m["a"], len(ein), ein[-1] if ein else None)
    except SystemExit as e:
        print("betfair-ex Fehler:", e)
print("\nAnfragen mit Kontingent (vermutlich):", fo.calls)
