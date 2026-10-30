"""Einmal-Test: h2h_ta.py mit wenigen Abrufen"""
import sys, json, os
sys.path.insert(0, "scripts"); os.chdir("scripts")
import h2h_ta
h2h_ta.MAX_ABRUFE = 6
h2h_ta.main()
from common import load
d = load("h2h_ta.json", {})
print(json.dumps(d.get("spieler"), ensure_ascii=False))
for k, v in list(d.get("paare", {}).items())[:6]:
    print(k, json.dumps(v, ensure_ascii=False)[:600])
