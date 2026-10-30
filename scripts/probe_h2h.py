"""Einmal-Test: Tennis Abstract player-classic (alle Ergebnisse?)"""
import urllib.request, re
UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}
for url in ["https://www.tennisabstract.com/cgi-bin/player-classic.cgi?p=DaniilMedvedev",
            "https://www.tennisabstract.com/jsmatches/DaniilMedvedev.js"]:
    try:
        t = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
        ds = sorted(set(re.findall(r"\b(20[12]\d)(\d\d)(\d\d)\b", t)))
        d2 = sorted(set(re.findall(r"\d{1,2}-\w{3}-(20\d\d)", t)))
        print(url, len(t), "YYYYMMDD:", ds[:1], ds[-2:], len(ds), "dd-Mon-yyyy Jahre:", d2)
        print(t[:300].replace("\n", " "))
        i = t.find("Mannarino"); print("Mannarino", i, t[max(0, i-500):i+100].replace("\n", " ") if i >= 0 else "")
        for s in re.findall(r'src="([^"]+\.js)"', t)[:12]: print("  script", s)
    except Exception as e:
        print(url, "Fehler", e)
