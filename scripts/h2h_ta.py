"""Neuere H2H-Duelle (alle Turnierstufen inkl. Challenger) von Tennis Abstract -> docs/data/h2h_ta.json

Für jede kommende Board-Partie mit Quote wird die Spielerseite eines der beiden Spieler geladen
(tennisabstract.com/jsfrags/<Name>.js, Tabelle "Recent Results", ca. die letzten 2–3 Jahre) und die Duelle gegen
den Gegner herausgesucht. Je Spieler höchstens ein Abruf pro Tag, höchstens MAX_ABRUFE je Lauf.
Ältere ATP-Duelle kommen aus h2h_liste.json (TML-Database), die neuesten aus dem eigenen Ergebnis-Archiv.
NUR PRIVAT (Tennis Abstract: nicht-kommerziell).

Zusätzlich "hb": {Name: {"datum", "ab": YYYYMM, "m": {"YYYYMM": [S gg. L, N gg. L, S gg. R, N gg. R]}}} – aktuelle
Bilanz gegen Links-/Rechtshänder (Gegnerhand aus haende.json), wird auf der Website mit den älteren TML-Monaten kombiniert.
Format: {"spieler": {Name: {"datum": "YYYY-MM-DD", "ok": bool}}, "paare": {"Name1|Name2" (alphabetisch):
         {"datum": ..., "duelle": [[YYYYMMDD, Turnier, Belag H/C/G/P, Runde, Sieger 0=Name1/1=Name2, Ergebnis], ...]}}}
"""
import re, sys, time, html, datetime, urllib.request
from common import load, save, NameMatcher

UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}
MAX_ABRUFE = 60
MONATE = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def ta_name(name):
    return re.sub(r"[^A-Za-z]", "", html.unescape(name))


def laden(name):
    url = f"https://www.tennisabstract.com/jsfrags/{ta_name(name)}.js"
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode("utf-8", "replace")
    except Exception as e:                       # noqa – Spieler ohne Seite o. Ä.
        print(f"  {name}: {e}")
        return None


def zeilen(txt):
    """Liefert (Datum YYYYMMDD, Turnier, Belag, Runde, gewonnen?, Gegner, Ergebnis) der fertigen Matches."""
    i = txt.find('id="recent-results"')
    if i < 0:
        return []
    teil = txt[i:txt.find("</table>", i)]
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", teil, re.S):
        td = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(td) < 8:
            continue
        txt_ = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
        dm = re.match(r"(\d{1,2})-(\w{3})-(\d{4})", txt_(td[0]))
        if not dm or dm.group(2) not in MONATE:
            continue
        datum = f"{dm.group(3)}{MONATE[dm.group(2)]:02d}{int(dm.group(1)):02d}"
        spiel = td[6]
        if " d. " not in spiel:
            continue                                  # noch nicht gespielt ("vs")
        links, rechts = spiel.split(" d. ", 1)
        gewonnen = "<b>" in links
        geg = re.search(r"<a [^>]*>(.*?)</a>", rechts if gewonnen else links)
        if not geg:
            continue
        out.append((datum, txt_(td[1]), (txt_(td[2]) or "?")[:1].upper(), txt_(td[3]), gewonnen, html.unescape(geg.group(1)).strip(),
                    txt_(td[7])))
    return out


def main():
    players = load("players.json", {})
    nm = NameMatcher(list(players), load("name_map.json", {}))
    st = load("h2h_ta.json", {"spieler": {}, "paare": {}})
    heute = datetime.date.today().isoformat()
    jetzt = datetime.datetime.now(datetime.timezone.utc).isoformat()
    partien = [m for m in load("matches.json", {}).get("partien", [])
               if m.get("hatQuoten") and str(m.get("start", "")) > jetzt[:19] and m.get("aInDb") and m.get("bInDb")]
    haende = (load("haende.json", {}) or {}).get("spieler", {})
    hand = lambda n: (haende.get(n) or {}).get("h")
    st.setdefault("hb", {})
    seiten, abrufe, neu, n_hb = {}, 0, 0, 0

    def seite(name):
        """Zeilen der Tennis-Abstract-Seite (heute höchstens einmal laden); None, wenn nicht verfügbar."""
        nonlocal abrufe, n_hb
        if name in seiten:
            return seiten[name]
        if abrufe >= MAX_ABRUFE:
            return None
        time.sleep(1.5)
        txt = laden(name)
        abrufe += 1
        ok = bool(txt and 'id="recent-results"' in txt)
        st["spieler"][name] = {"datum": heute, "ok": ok}
        z = [(d, t, b, r, gew, nm.match(geg), erg) for d, t, b, r, gew, geg, erg in zeilen(txt)] if ok else None
        seiten[name] = z
        if z:   # Bilanz gegen Links-/Rechtshänder je Monat (Gegnerhand aus haende.json)
            m_ = {}
            for d, _, _, _, gew, geg, _ in z:
                h = hand(geg)
                if h in ("L", "R"):
                    v = m_.setdefault(d[:6], [0, 0, 0, 0])
                    v[(0 if h == "L" else 2) + (0 if gew else 1)] += 1
            st["hb"][name] = {"datum": heute, "ab": min(d[:6] for d, *_ in z), "m": m_}
            n_hb += 1
        return z

    for m in sorted(partien, key=lambda m: (m.get("kategorie") != "ATP", m.get("start"))):
        x, y = sorted([m["a"], m["b"]])
        key = f"{x}|{y}"
        # Spieler gegen einen Linkshänder: dessen Seite für die aktuelle Bilanz gegen Linkshänder laden
        for me, geg in ((m["a"], m["b"]), (m["b"], m["a"])):
            if hand(geg) == "L" and (st["hb"].get(me) or {}).get("datum") != heute:
                seite(me)
        if (st["paare"].get(key) or {}).get("datum") == heute:
            continue
        kand = sorted([m["a"], m["b"]], key=lambda n: (n not in seiten, not st["spieler"].get(n, {}).get("ok", True)))
        duelle = None
        for me in kand:
            z = seite(me)
            if not z:
                continue
            gegner = m["b"] if me == m["a"] else m["a"]
            duelle = [[d, t, b, r, 0 if (me == x) == gew else 1, erg] for d, t, b, r, gew, geg, erg in z if geg == gegner]
            break
        if duelle is None:
            continue
        st["paare"][key] = {"datum": heute, "duelle": sorted(duelle, key=lambda e: e[0], reverse=True)}
        neu += 1
    # aufräumen: Spieler-Einträge älter als 30 Tage
    grenze = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    st["spieler"] = {k: v for k, v in st["spieler"].items() if v.get("datum", "") >= grenze}
    save("h2h_ta.json", st, indent=0)
    print(f"H2H Tennis Abstract: {neu} Paare aktualisiert, {abrufe} Seiten geladen, {len(st['paare'])} Paare gespeichert; "
          f"Bilanz gegen Links-/Rechtshänder für {n_hb} Spieler aktualisiert ({len(st['hb'])} gespeichert)")


if __name__ == "__main__":
    sys.exit(main())
