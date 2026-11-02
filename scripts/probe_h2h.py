"""Einmal-Test: Tennis Abstract Surface Speed – auch Sand? mehrere Jahre?"""
import urllib.request, re, html
UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}
for y in (2025, 2024, 2023):
    url = f"https://www.tennisabstract.com/cgi-bin/surface-speed.cgi?year={y}"
    try:
        t = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
    except Exception as e:
        print(y, "Fehler", e); continue
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
    out = []
    for r in rows:
        td = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if td: out.append(td)
    print(y, len(t), "Zeilen", len(out))
    for r in out[:3]: print("  ", r)
    print("  Sand:", [r for r in out if any("Clay" in c for c in r)][:40])
