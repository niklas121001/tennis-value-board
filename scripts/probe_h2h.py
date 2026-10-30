"""Einmal-Test: Tennis-Abstract-Spielerdatei mit allen Matches (auch Challenger)?"""
import urllib.request
UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}
for url in ["https://www.tennisabstract.com/jsmatches/JanLennardStruff.js",
            "https://www.tennisabstract.com/cgi-bin/player.cgi?p=JanLennardStruff"]:
    try:
        t = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
        print(url, len(t)); print(t[:1200]); i = t.find("Borges"); print("Borges bei", i, t[max(0, i-400):i+200] if i >= 0 else "")
    except Exception as e:
        print(url, "Fehler", e)
