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
MAX_ABRUFE = 120         # Seiten je Lauf (je ca. 0,5 MB; ~8 Min. bei 4 s Pause). Jeder Spieler bleibt bei 1 Seite pro Tag – die Obergrenze sorgt nur dafür, dass alle Board-Spieler schon im Frühlauf dran sind (bis 11.11.2026: 60)
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


def roh_zeilen(txt):
    """Array matchmx der Spielerseite als Liste (48 Spalten je Match); [] wenn nicht lesbar."""
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
        return json.loads(roh)
    except ValueError as e:
        print("  matchmx nicht lesbar:", str(e)[:120], roh[-120:].replace("\n", " "))
        return []


def zeilen(txt):
    """Alle gespielten Matches der Karriere (Array matchmx, alle Stufen inkl. Challenger/ITF):
    (Datum YYYYMMDD = Turnierbeginn, Turnier, Belag, Runde, gewonnen?, Gegner, Ergebnis aus Siegersicht, Gegnerhand)."""
    out = []
    for r in roh_zeilen(txt):
        if len(r) < 16 or r[4] not in ("W", "L"):
            continue                                  # "U" = noch nicht gespielt
        out.append((str(r[0]), r[1], (r[2] or "?")[:1].upper(), r[8], r[4] == "W", html.unescape(r[11] or "").strip(), r[9] or "", r[15]))
    return out


def spiele(txt, name, ab):
    """Einzelne Matches mit Statistik (Tour + Challenger, ohne ITF/Davis Cup), Turnierbeginn ab `ab`, für das eigene
    Platztempo und die gehaltenen Aufschlagspiele: Schlüssel „Datum|Runde|Name1|Name2“ (Namen alphabetisch) ->
    [Datum, Stufe, Turnier, Belag, Runde, Name1, Name2, Werte1, Werte2]; Werte = [Asse, Doppelfehler, Aufschlagpunkte,
    1. im Feld, Punkte 1., Punkte 2., Aufschlagspiele, Breakbälle abgewehrt, Breakbälle gegen]."""
    z = lambda v: int(v) if str(v).strip().isdigit() else None
    out = {}
    for r in roh_zeilen(txt):
        if len(r) < 39 or r[4] not in ("W", "L") or str(r[0]) < ab or str(r[3]) not in ("G", "M", "A", "F", "C"):
            continue
        b = {"H": "hard", "C": "clay", "G": "grass"}.get((r[2] or "?")[:1].upper())
        geg = html.unescape(r[11] or "").strip()
        ich, er = [z(r[k]) for k in range(21, 30)], [z(r[k]) for k in range(30, 39)]
        if not b or not geg or None in ich or None in er or ich[2] < 20 or er[2] < 20:
            continue
        x, y = sorted([name, geg])
        out[f"{r[0]}|{r[8]}|{x}|{y}"] = [str(r[0]), str(r[3]), r[1], b, r[8], x, y] + ([ich, er] if x == name else [er, ich])
    return out


TA_STUFEN = {"G", "M", "A", "F", "C", "D"}     # Grand Slam, Masters, ATP, Finals, Challenger, Davis Cup – ohne ITF (15/25)


def aufschlag(txt, ab):
    """Aufschlag-/Returnwerte je Belag aus den Match-Statistiken der Spielerseite (Spalten 21–38), Turnierbeginn ab `ab`
    (YYYYMMDD), nur Tour- und Challenger-Ebene. Ergebnis je Belag: [Matches, 1. Aufschlag im Feld, Punkte hinter dem 1.,
    Punkte hinter dem 2., Returnpunkte gewonnen, Aufschlagspiele gehalten, Aufschlagpunkte]."""
    z = lambda v: int(v) if str(v).strip().lstrip("-").isdigit() else None
    sm = {}
    for r in roh_zeilen(txt):
        if len(r) < 39 or r[4] not in ("W", "L") or str(r[0]) < ab or str(r[3]) not in TA_STUFEN:
            continue
        b = {"H": "hard", "C": "clay", "G": "grass"}.get((r[2] or "?")[:1].upper())
        sv, in1, w1, w2, sg, bs, bf = (z(r[k]) for k in (23, 24, 25, 26, 27, 28, 29))
        osv, ow1, ow2 = z(r[32]), z(r[34]), z(r[35])
        if not b or None in (sv, in1, w1, w2, osv, ow1, ow2) or sv < 20 or osv < 20 or in1 <= 0 or sv - in1 <= 0:
            continue
        a = sm.setdefault(b, [0] * 10)
        for i_, v in enumerate((1, sv, in1, w1, w2, osv, ow1 + ow2, sg or 0, (bf or 0) - (bs or 0) if sg else 0)):
            a[i_] += v
    out = {}
    for b, (n, sv, in1, w1, w2, osv, ow, sg, brk, _) in sm.items():
        out[b] = [n, round(in1 / sv, 4), round(w1 / in1, 4), round(w2 / (sv - in1), 4), round(1 - ow / osv, 4),
                  round(1 - brk / sg, 4) if sg else None, sv]
    return out


def eigene_hand(txt):
    m = re.search(r"var\s+hand\s*=\s*'([RL])'", txt or "")
    return m.group(1) if m else None


# Platztempo (tempo.json, Tennis Abstract) und Halle (turnier_stats.json) je Turniername – für die Spieler-Bilanzen
_TEMPO, _HALLE = None, None


def _norm(t):
    return re.sub(r"[^a-z]", "", str(t).lower())   # Challenger ("… CH") bleiben eigene Namen -> kein Tempo-Wert


def tempo_von(turnier, belag, jahr):
    global _TEMPO
    if _TEMPO is None:
        _TEMPO = {}
        for r in (load("tempo.json", {}) or {}).get("turniere", []):
            for n in [r["name"]] + (r.get("alias") or []):
                _TEMPO[(_norm(n), r["belag"])] = r
    r = _TEMPO.get((_norm(turnier), belag))
    if not r:
        return None
    return (r.get("jahre") or {}).get(str(jahr), r.get("speed"))


def tempo_stufe(belag, sp):
    lo, hi = {"hard": (0.95, 1.15), "clay": (0.65, 0.85), "grass": (1.05, 1.25)}.get(belag, (0.95, 1.15))
    return "langsam" if sp < lo else "schnell" if sp >= hi else "mittel"


def halle_von(turnier):
    global _HALLE
    if _HALLE is None:
        _HALLE = {}
        for x in ((load("turnier_stats.json", {}) or {}).get("turniere") or {}).values():
            for n in [x["name"]] + (x.get("alias") or []):
                _HALLE[_norm(n)] = bool(x.get("halle"))
    return _HALLE.get(_norm(turnier))


def main():
    players = load("players.json", {})
    nm = NameMatcher(list(players), load("name_map.json", {}))
    st = load("h2h_ta.json", {"spieler": {}, "paare": {}})
    if st.get("version") != 2:                    # 30.10.2026: Quelle auf komplette Karriere umgestellt -> alles neu laden
        st = {"version": 2, "spieler": {}, "paare": {}, "hb": {}, "haende": {}}
    heute = datetime.date.today().isoformat()
    ab12 = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y%m%d")
    tas = load("ta_stats.json", {}) or {}
    tas.setdefault("spieler", {})
    tam = load("ta_matches.json", {}) or {}        # einzelne Matches mit Statistik (für tempo_eigen.py und hold_stats.py)
    tam.setdefault("spiele", {})
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
        # keine Matchliste: andere Schreibweisen versuchen (Namen aus name_map.json, z. B. „Tomas Martin Etcheverry“,
        # und nur erster Buchstabe groß, z. B. „Mccabe“)
        if not roh:
            alt = [k for k, v in (load("name_map.json", {}) or {}).items() if v == name]
            alt.append(" ".join(t[:1].upper() + t[1:].lower() for t in name.split()))
            for a in dict.fromkeys(alt):
                if ta_name(a) == ta_name(name) or abrufe >= MAX_ABRUFE:
                    continue
                time.sleep(PAUSE)
                t2 = laden(a); abrufe += 1
                if zeilen(t2):
                    txt, roh = t2, zeilen(t2)
                    print(f"  {name}: Tennis Abstract unter „{a}“")
                    break
        ok = bool(roh)
        st["spieler"][name] = {"datum": heute, "ok": ok}
        if not ok:
            st["spieler"][name]["grund"] = LETZTER_FEHLER[0] or (f"keine Matchliste (Seite {len(txt)} Zeichen)" if txt else "leer")
        if eigene_hand(txt):
            st.setdefault("haende", {})[name] = eigene_hand(txt)
        if ok:      # Aufschlag-/Returnwerte der letzten 12 Monate (Test-Variante R) -> ta_stats.json
            w = aufschlag(txt, ab12)
            if w:
                tas["spieler"][name] = dict(w, datum=heute)
            tam["spiele"].update(spiele(txt, name, ab12))
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
            # 1. Satz seit 2023: nach gewonnenem bzw. verlorenem 1. Satz – Match gewonnen/verloren (Ergebnis aus Siegersicht)
            fs = {"g": [0, 0], "v": [0, 0]}
            for d, _, _, _, gew, geg, erg, h in z:
                m1 = re.match(r"^(\d+)-(\d+)", erg or "")
                if d < "20230101" or not m1 or re.search(r"RET|W/O|DEF|ABD", erg, re.I) or m1.group(1) == m1.group(2):
                    continue
                satz1_sieger_gewann = int(m1.group(1)) > int(m1.group(2))
                erster = satz1_sieger_gewann if gew else not satz1_sieger_gewann
                fs["g" if erster else "v"][0 if gew else 1] += 1
            st.setdefault("fs", {})[name] = fs
            # Platztempo und Halle seit 2023: Bilanz je Belag in den Tempo-Stufen langsam/mittel/schnell und Halle/draußen
            tp = {}
            for d, turnier, bel, _, gew, geg, erg, h in z:
                if d < "20230101" or re.search(r"RET|W/O|DEF|ABD", erg or "", re.I):
                    continue
                b_ = {"H": "hard", "C": "clay", "G": "grass"}.get(bel)
                if not b_:
                    continue
                sp = tempo_von(turnier, b_, d[:4])
                if sp is not None:
                    v = tp.setdefault(b_, {}).setdefault(tempo_stufe(b_, sp), [0, 0]); v[0 if gew else 1] += 1
                ha = halle_von(turnier)
                if ha is not None:
                    v = tp.setdefault("halle" if ha else "draussen", [0, 0]); v[0 if gew else 1] += 1
            st.setdefault("tempo", {})[name] = tp
        return z

    def veraltet(me):
        """Seite neu laden: nicht heute geladen oder (neue) Auswertungen 1. Satz / Platztempo fehlen noch."""
        if me in seiten or (st["spieler"].get(me) or {}).get("datum") == heute and not (st["spieler"].get(me) or {}).get("ok", True):
            return False                              # heute schon geladen bzw. heute schon ohne Erfolg versucht
        return (st["hb"].get(me) or {}).get("datum") != heute or me not in st.get("fs", {}) or me not in st.get("tempo", {}) \
            or not tas.get("stand") or not tam.get("stand")                  # erster Lauf mit Aufschlagwerten: alle Seiten einmal neu auswerten

    for m in sorted(partien, key=lambda m: (m.get("kategorie") != "ATP", m.get("start"))):
        x, y = sorted([m["a"], m["b"]])
        key = f"{x}|{y}"
        # Spieler gegen einen Linkshänder: dessen Seite für die aktuelle Bilanz gegen Linkshänder laden
        for me, geg in ((m["a"], m["b"]), (m["b"], m["a"])):
            if hand(geg) == "L" and veraltet(me):
                seite(me)
        for me in (m["a"], m["b"]):                    # beide Spieler: 1. Satz-Statistik und Bilanz aktuell halten
            if veraltet(me) and abrufe < MAX_ABRUFE:
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
    g60 = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    tas["spieler"] = {k: v for k, v in tas["spieler"].items() if v.get("datum", "") >= g60}
    tas["stand"] = heute
    tas["quelle"] = "Tennis Abstract, Match-Statistiken der letzten 12 Monate (Tour + Challenger, ohne ITF); nur privat"
    tas["format"] = "je Belag: [Matches, 1. Aufschlag im Feld, Punkte 1. Aufschlag, Punkte 2. Aufschlag, Returnpunkte, Aufschlagspiele gehalten, Aufschlagpunkte]"
    save("ta_stats.json", tas, indent=0)
    ab400 = (datetime.date.today() - datetime.timedelta(days=400)).strftime("%Y%m%d")
    tam["spiele"] = {k: v for k, v in tam["spiele"].items() if v[0] >= ab400}
    tam["stand"] = heute
    tam["quelle"] = "Tennis Abstract, Match-Statistiken (Tour + Challenger); nur privat"
    save("ta_matches.json", tam, indent=0)
    print(f"Match-Statistiken Tennis Abstract: {len(tam['spiele'])} Spiele gespeichert")
    print(f"Aufschlagwerte Tennis Abstract: {len(tas['spieler'])} Spieler gespeichert")
    print(f"H2H Tennis Abstract: {neu} Paare aktualisiert, {abrufe} Seiten geladen, {len(st['paare'])} Paare gespeichert; "
          f"Bilanz gegen Links-/Rechtshänder für {n_hb} Spieler aktualisiert ({len(st['hb'])} gespeichert)")


if __name__ == "__main__":
    sys.exit(main())
