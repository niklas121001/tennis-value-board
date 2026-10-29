"""Einmal-Test: zählt historical-odds aufs Monatskontingent? Gibt nur Zählerstände aus."""
import sys, time, datetime
sys.path.insert(0, "scripts")
import fetch_odds as fo
from common import load, config
cfg = config()
u0, _ = fo.konto(fo.api("account"), cfg)
jetzt = datetime.datetime.now(datetime.timezone.utc)
ps = [m for m in load("matches.json", {}).get("partien", []) if m.get("start") and datetime.datetime.fromisoformat(m["start"].replace("Z", "+00:00")) > jetzt]
for m in ps[:3]:
    time.sleep(5); fo.api("historical-odds", fixtureId=m["id"], bookmakers="pinnacle")
time.sleep(2)
u1, _ = fo.konto(fo.api("account"), cfg)
print("Zähler vorher", u0, "nachher", u1, "nach 3 historical-odds-Abrufen")
