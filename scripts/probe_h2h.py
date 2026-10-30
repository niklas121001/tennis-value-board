"""Einmal-Test: Was liefert SportsAPIPro /match/{id}/h2h? Gibt nur die Struktur und ein Beispiel aus."""
import sys, json
sys.path.insert(0, "scripts")
import sportsapipro as s
from common import load
ms = [m for m in load("matches.json", {}).get("partien", []) if m.get("sapId")]
m = next((x for x in ms if x.get("kategorie") == "ATP"), ms[0])
js = s.get(f"/match/{m['sapId']}/h2h")
def struktur(o, tiefe=0):
    if tiefe > 4: return "…"
    if isinstance(o, dict): return {k: struktur(v, tiefe + 1) for k, v in list(o.items())[:25]}
    if isinstance(o, list): return [len(o), struktur(o[0], tiefe + 1) if o else None]
    return type(o).__name__
print(m["a"], "-", m["b"])
print(json.dumps(struktur(js), ensure_ascii=False)[:2500])
print(json.dumps(js, ensure_ascii=False)[:2500])
