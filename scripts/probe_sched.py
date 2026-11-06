"""Einmal-Probe: /schedule/2026-11-05 – Anzahl Events, Paging-Felder, Taranto-Einträge; /match/17427633 testen."""
import json, sys
sys.path.insert(0, ".")
import sportsapipro as s
js = s.get("/schedule/2026-11-05")
top = list(js.keys()) if isinstance(js, dict) else type(js).__name__
ev = list(s.finde(js, lambda x: "homeTeam" in x))
tar = [f"{e.get('id')}:{(e.get('homeTeam') or {}).get('name')}-{(e.get('awayTeam') or {}).get('name')}:{(e.get('status') or {}).get('type')}" for e in ev if "Taranto" in json.dumps(e.get('tournament', {}))]
meta = {k: js[k] for k in js if not isinstance(js[k], (list, dict))} if isinstance(js, dict) else {}
print(f"::notice title=schedule::top={top} n={len(ev)} meta={json.dumps(meta)[:300]} taranto={tar[:12]}")
for pfad in ("/match/17427633", "/event/17427633"):
    d = s.get(pfad)
    print(f"::notice title={pfad}::{json.dumps(d)[:900] if d else 'None'}")
