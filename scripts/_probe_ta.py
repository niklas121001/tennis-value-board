import re, json, time, sys
sys.path.insert(0, ".")
import h2h_ta as H
for name in ["Jannik Sinner", "Mert Alkaya", "Jay Clarke", "Eliakim Coulibaly", "Takuya Kumasaka"]:
    txt = H.laden(name)
    if not txt:
        print("KEINE SEITE", name); continue
    m = re.search(r"var\s+matchmx\s*=\s*\[", txt)
    print("=====", name, len(txt), "matchmx" if m else "kein matchmx")
    for v in re.findall(r"var\s+(\w+)\s*=\s*\[", txt)[:40]: print("  var-array:", v)
    for mm in re.finditer(r"var\s+(matchhead|headers?|cols?\w*|statcols\w*)\s*=\s*(\[[^\]]{0,1500}\])", txt): print("  HEAD", mm.group(1), mm.group(2)[:1500])
    if not m: continue
    i = m.end() - 1; tiefe = 0; ims = False; esc = False
    for j in range(i, len(txt)):
        c = txt[j]
        if ims:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': ims = False
        elif c == '"': ims = True
        elif c == "[": tiefe += 1
        elif c == "]":
            tiefe -= 1
            if tiefe == 0: break
    rows = json.loads(re.sub(r",\s*\]", "]", txt[i:j + 1]))
    gesp = [r for r in rows if len(r) > 15 and r[4] in ("W", "L")]
    print("  Zeilen", len(rows), "gespielt", len(gesp), "Spalten", sorted(set(len(r) for r in rows)))
    neu = sorted(gesp, key=lambda r: str(r[0]), reverse=True)
    for r in neu[:4]: print("  ROW", json.dumps(r, ensure_ascii=False))
    j12 = [r for r in neu if str(r[0]) >= "20251110"]
    def hat(r): return sum(1 for x in r[21:35] if str(x).strip() not in ("", "None")) >= 6 if len(r) > 30 else False
    lv = {}
    for r in j12:
        k = str(r[3]); a = lv.setdefault(k, [0, 0]); a[0] += 1; a[1] += hat(r)
    print("  12 Monate je Stufe [Matches, mit Statistik]:", lv)
    time.sleep(4)
