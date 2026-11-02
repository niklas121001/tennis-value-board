"""Einmal-Test: Winamax-Märkte einer Partie (kostenlos)"""
import sys, json
sys.path.insert(0, "scripts")
import fetch_odds as fo
res = fo.api("historical-odds", fixtureId="id1200266176310134", bookmakers="winamax.de")
for slug, bo in (res.get("bookmakers") or {}).items():
    for mid, x in (bo.get("markets") or {}).items():
        for oid, o in (x.get("outcomes") or {}).items():
            ein = [e for es in (o.get("players") or {}).values() for e in (es if isinstance(es, list) else [es])]
            ein.sort(key=lambda e: str(e.get("createdAt")))
            l = ein[-1] if ein else {}
            print(slug, mid, oid, len(ein), l.get("price"), l.get("active"), str(l.get("createdAt"))[:16], l.get("bookmakerOutcomeId"))
