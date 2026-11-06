"""Einmal-Probe: Paging des Spielplans und Aufbau von /match/{id}."""
import json, sys
sys.path.insert(0, ".")
import sportsapipro as s
for q in ("?page=2", "?offset=50", "?limit=200", "?page=1&limit=100"):
    js = s.get("/schedule/2026-11-05" + q)
    if isinstance(js, dict):
        ev = list(s.finde(js, lambda x: "homeTeam" in x))
        tar = sum(1 for e in ev if "Taranto" in json.dumps(e.get("tournament", {})))
        meta = {k: js[k] for k in js if not isinstance(js[k], (list, dict))}
        print(f"::notice title=schedule{q}::n={len(ev)} taranto={tar} meta={json.dumps(meta)[:200]} erst={(ev[0].get('tournament') or {}).get('name') if ev else None}")
    else:
        print(f"::notice title=schedule{q}::None")
d = s.get("/match/17427633")
e = ((d or {}).get("data") or {}).get("event") or {}
k = s.kompakt(e) if e else None
print(f"::notice title=match keys::{list(e.keys())[:40]}")
print(f"::notice title=match kompakt::{json.dumps(k)[:600]}")
