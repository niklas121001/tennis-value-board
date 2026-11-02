"""Einmal-Test: Namen der Märkte (1 Anfrage /markets)"""
import sys, json
sys.path.insert(0, "scripts")
import fetch_odds as fo
from common import load
meta = load("oddspapi.json", {})
res = fo.api("markets", sportId=meta.get("sportId"))
if isinstance(res, dict): res = res.get("data") or list(res.values())
ids = {"121","12231","12239","12241","12245","12247","12249","12251","12433","12877","123","125","129","1213","1217","1221","1225","1229","1233","1237","1241","1245","1253","12155","12159","12171","12183","12263","12366","12378","12435","12917","12983","121077","121143"}
for m in res:
    mid = str(m.get("marketId"))
    if mid in ids:
        print(mid, m.get("marketName"), "|", m.get("marketType"), m.get("handicap"), m.get("period") or m.get("periodName"), [ (o.get("outcomeId"), o.get("outcomeName")) for o in (m.get("outcomes") or [])][:4])
print("Calls:", fo.calls)
