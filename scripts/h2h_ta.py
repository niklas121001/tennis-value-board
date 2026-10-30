"""Neuere H2H-Duelle (alle Turnierstufen inkl. Challenger) von Tennis Abstract -> docs/data/h2h_ta.json

Für jede kommende Board-Partie mit Quote wird die Spielerseite eines der beiden Spieler geladen
(tennisabstract.com/cgi-bin/player-classic.cgi?p=<Name>, Array "matchmx" = alle Matches der Karriere, alle Stufen
inkl. Challenger/ITF, mit Gegnerhand) und die Duelle gegen den Gegner herausgesucht. Je Spieler höchstens ein Abruf pro Tag, höchstens MAX_ABRUFE je Lauf.
Ältere ATP-Duelle kommen aus h2h_liste.json (TML-Database), die neuesten aus dem eigenen Ergebnis-Archiv.
NUR PRIVAT (Tennis Abstract: nicht-kommerziell).

Zusätzlich "hb": {Name: {"datum", "ab": YYYYMM, "m": {"YYYYMM": [S gg. L, N gg. L, S gg. R, N gg. R]}}} – aktuelle
Bilanz gegen Links-/Rechtshänder seit 2023 (Gegnerhand von Tennis Abstract, ohne Aufgaben); "haende": eigene Schlaghand.
Format: {"spieler": {Name: {"datum": "YYYY-MM-DD", "ok": bool}}, "paare": {"Name1|Name2" (alphabetisch):
         {"datum": ..., "duelle": [[YYYYMMDD, Turnier, Belag H/C/G/P, Runde, Sieger 0=Name1/1=Name2, Ergebnis], ...]}}}
"""
import re, sys, json, time, html, datetime, urllib.request
from common import load, save, NameMatcher

UA = {"User-Agent": "Mozilla/5.0 (TennisValueApp; private use)"}
MAX_ABRUFE = 60          # Seiten je Lauf (je ca. 0,5 MB)
PAUSE = 4                # Sekunden zwischen zwei Seiten (Tennis Abstract nicht überlasten)
MONATE = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def ta_name(name):
    return re.sub(r"[^A-Za-z]", "", html.unescape(name))


LETZTER_FEHLER = [""]


def laden(name, versuche=2):
    url = f"https://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={ta_name(name)}"
    for v in range(versuche):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
        except Exception as e:                       # noqa – Spieler ohne Seite, Drosselung o. Ä.
            LETZTER_FEHLER[0] = str(e)[:80]
            print(f"  {name}: {e}")
            if v + 1 < versuche:
                time.sleep(20)
    return None


def zeilen(txt):
    """Alle gespielten Matches der Karriere (Array matchmx, alle Stufen inkl. Challenger/ITF):
    (Datum YYYYMMDD = Turnierbeginn, Turnier, Belag, Runde, gewonnen?, Gegner, Ergebnis aus Siegersicht, Gegnerhand)."""
    m = re.search(r"var\s+matchmx\s*=\s*\[", txt or "")
    if not m:
        return []
    # Ende des Arrays über Klammerzählung finden (Strings beachten), dann tolerant als JSON lesen
    i, tiefe, im_str, esc_ = m.end() - 1, 0, False, False
    for j in range(i, len(txt)):
        c = txt[j]
        if im_str:
            if esc_: esc_ = False
            elif c == "\\": esc_ = True
            elif c == '"': im_str = False
        elif c == '"': im_str = True
        elif c == "[": tiefe += 1
        elif c == "]":
            tiefe -= 1
            if tiefe == 0:
                break
    roh = re.sub(r",\s*\]", "]", txt[i:j + 1])
    try:
        rows = json.loads(roh)
    except ValueError as e:
        print("  matchmx nicht lesbar:", str(e)[:120], roh[-120:].replace("\n", " "))
        return []
    out = []
    for r in rows:
        if len(r) < 16 or r[4] not in ("W", "L"):
            continue                                  # "U" = noch nicht gespielt
        out.append((str(r[0]), r[1], (r[2] or "?")[:1].upper(), r[8], r[4] == "W", html.unescape(r[11] or "").strip(), r[9] or "", r[15]))
    return out


def eigene_hand(txt):
    m = re.search(r"var\s+hand\s*=\s*'([RL])'", txt or "")
    return m.group(1) if m else None


def main():
    players = load("players.json", {})
    nm = NameMatcher(list(players), load("name_map.json", {}))
    st = load("h2h_ta.json", {"spieler": {}, "paare": {}})
    if st.get("version") != 2:                    # 30.10.2026: Quelle auf komplette Karriere umgestellt -> alles neu laden
        st = {"version": 2, "spieler": {}, "paare": {}, "hb": {}, "haende": {}}
    heute = datetime.date.today().isoformat()
    jetzt = datetime.datetime.now(datetime.timezone.utc).isoformat()
    partien = [m for m in load("matches.json", {}).get("partien", [])
               if m.get("hatQuoten") and str(m.get("start", "")) > jetzt[:19] and m.get("aInDb") and m.get("bInDb")]
    haende = (load("haende.json", {}) or {}).get("spieler", {})
    hand = lambda n: (haende.get(n) or {}).get("h") or (st.get("haende") or {}).get(n)
    st.setdefault("hb", {})
    seiten, abrufe, neu, n_hb = {}, 0, 0, 0

    def seite(name):
        """Zeilen der Tennis-Abstract-Seite (heute höchstens einmal laden); None, wenn nicht verfügbar."""
        nonlocal abrufe, n_hb
        if name in seiten:
            return seiten[name]
        if abrufe >= MAX_ABRUFE:
            return None
        time.sleep(PAUSE)
        LETZTER_FEHLER[0] = ""
        txt = laden(name)
        abrufe += 1
        roh = zeilen(txt)
        ok = bool(roh)
        st["spieler"][name] = {"datum": heute, "ok": ok}
        if not ok:
            st["spieler"][name]["grund"] = LETZTER_FEHLER[0] or (f"keine Matchliste (Seite {len(txt)} Zeichen)" if txt else "leer")
        if eigene_hand(txt):
            st.setdefault("haende", {})[name] = eigene_hand(txt)
        z = [(d, t, b, r, gew, nm.match(geg), erg, h) for d, t, b, r, gew, geg, erg, h in roh] if ok else None
        seiten[name] = z
        if z:   # Bilanz gegen Links-/Rechtshänder je Monat seit 2023 (Gegnerhand direkt von Tennis Abstract), ohne Aufgaben
            m_ = {}
            for d, _, _, _, gew, geg, erg, h in z:
                if d < "20230101" or h not in ("L", "R") or re.search(r"RET|W/O|DEF|ABD", erg, re.I):
                    continue
                v = m_.setdefault(d[:6], [0, 0, 0, 0])
                v[(0 if h == "L" else 2) + (0 if gew else 1)] += 1
            st["hb"][name] = {"datum": heute, "ab": "202301", "m": m_}
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
            duelle = [[d, t, b, r, 0 if (me == x) == gew else 1, erg] for d, t, b, r, gew, geg, erg, h in z if geg == gegner]
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
