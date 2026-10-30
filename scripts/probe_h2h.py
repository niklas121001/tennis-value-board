"""Einmal-Test: Tennis-Abstract-Spielerdateien (aktuelle + Karriere)"""
import urllib.request, re
UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}
for url in ["https://www.tennisabstract.com/jsfrags/JanLennardStruff.js",
            "https://www.tennisabstract.com/jsmatches/JanLennardStruffCareer.js"]:
    try:
        t = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
        print(url, len(t)); print(t[:700].replace("\n", " ")); 
        for w in ["Borges", "Challenger", " CH"]:
            i = t.find(w); print(w, "bei", i, t[max(0, i-300):i+150].replace("\n", " ") if i >= 0 else "")
        print("Jahre:", sorted(set(re.findall(r"20[12][0-9][01][0-9][0-3][0-9]", t)))[-3:], sorted(set(re.findall(r"20[12][0-9][01][0-9][0-3][0-9]", t)))[:2])
    except Exception as e:
        print(url, "Fehler", e)
