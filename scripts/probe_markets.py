"""Einmal-Probe: Tennis-Märkte von OddsPapi (Satz-Handicap, Anzahl Sätze, genaues Ergebnis) als Annotation ausgeben."""
import json, sys
sys.path.insert(0, ".")
import fetch_odds as fo
ms = fo.api("markets")
if isinstance(ms, dict):
    ms = ms.get("data") or list(ms.values())
t = [m for m in ms if str(m.get("sportId")) == "12"]
zeilen = []
for m in t:
    n = f"{m.get('marketName','')} {m.get('marketType','')}".lower()
    if any(w in n for w in ("set", "handicap", "total", "exact", "correct", "tie")):
        zeilen.append(f"{m.get('marketId')}|{m.get('marketName')}|{m.get('marketType')}|p={m.get('period')}|hc={m.get('handicap')}|" +
                      ",".join(f"{o.get('outcomeId')}:{o.get('outcomeName')}" for o in (m.get('outcomes') or [])))
print(f"Tennis-Märkte {len(t)}, gefiltert {len(zeilen)}")
for i in range(0, len(zeilen), 12):
    print("::notice title=Maerkte " + str(i) + "::" + " || ".join(zeilen[i:i+12]))
