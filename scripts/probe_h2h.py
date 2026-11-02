"""Einmal-Test: Welche Märkte liefert historical-odds (Winamax/Pinnacle) für Tennis? (kostenlos)"""
import sys, json, time, datetime
sys.path.insert(0, "scripts")
import fetch_odds as fo
from common import load
ms = [m for m in load("matches.json", {}).get("partien", []) if m.get("hatQuoten")]
ms.sort(key=lambda m: (m.get("kategorie") != "ATP", m["start"]))
for m in ms[:2]:
    time.sleep(5)
    res = fo.api("historical-odds", fixtureId=m["id"], bookmakers="winamax.de,pinnacle")
    print(m["a"], "-", m["b"], m["turnier"])
    for slug, bo in (res.get("bookmakers") or {}).items():
        mk = bo.get("markets") or {}
        print(" ", slug, len(mk), "Märkte")
        for mid, x in mk.items():
            outs = x.get("outcomes") or {}
            bmids = set()
            for oid, o in outs.items():
                for pl in (o.get("players") or {}).values():
                    e = pl[-1] if isinstance(pl, list) and pl else pl
                    if isinstance(e, dict): bmids.add(str(e.get("bookmakerOutcomeId") or e.get("bookmakerMarketId") or "")[:30])
            print("   ", mid, "Ausgänge", list(outs)[:8], sorted(bmids)[:6])
print("Calls:", fo.calls)
