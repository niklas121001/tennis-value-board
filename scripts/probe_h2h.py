"""Einmal-Test: Struktur der Match-Arrays in player-classic"""
import urllib.request, re
UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}
t = urllib.request.urlopen(urllib.request.Request("https://www.tennisabstract.com/cgi-bin/player-classic.cgi?p=DaniilMedvedev", headers=UA), timeout=60).read().decode("utf-8", "replace")
for m in re.finditer(r"var\s+(\w+)\s*=\s*\[\[", t):
    print("Array", m.group(1), "bei", m.start())
i = t.find('"2026102'); print(t[max(0, i-50):i+700].replace("\n", " "))
i = t.find("Mannarino\""); 
for m in re.finditer(r'\["(\d{8})"[^\]]*Mannarino[^\]]*\]', t): print("H2H:", m.group(0)[:400])
