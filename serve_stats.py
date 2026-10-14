"""Aufschlag-/Returnwerte fortschreiben (Schritt 2) -> docs/data/serve_live.json

Quelle: Match-Statistiken aus sap_stats.json (SportsAPIPro), nur Spiele NACH dem Excel-Stand (h2h_web.json "stand").
Je Spieler und Belag:
  - Spieler mit Excel-Werten: Excel-Wert wird mit den neuen Spielen fortlaufend weitergerechnet.
    Der Excel-Wert zählt dabei wie EXCEL_GEWICHT_PUNKTE Aufschlagpunkte (bzw. Returnpunkte), jedes neue
    Spiel kommt mit seinen echten Punkten dazu. Beispiel: 1. Aufschlag gewonnen Excel 70 %, Gewicht 1.500
    Punkte (~20 Spiele); ein neues Spiel mit 45/71 = 63 % verschiebt den Wert auf rund 69,7 %.
  - Spieler ohne Excel-Werte: nur die neuen Spiele, sobald MIN_SPIELE_OHNE_EXCEL auf dem Belag vorliegen
    (vorher greift wie bisher der Challenger-Durchschnitt).
players.json bleibt unverändert (Excel-Stand); das Modell legt serve_live.json darüber.
Einstellungen in config.json unter "aufschlag_fortschreibung".
"""
import sys
from common import load, save, config, NameMatcher

FELDER = ("1in", "1won", "2won", "ret")


def main():
    cfg = config().get("aufschlag_fortschreibung", {})
    gewicht = float(cfg.get("excel_gewicht_punkte", 1500))
    min_spiele = int(cfg.get("min_spiele_ohne_excel", 3))

    stats = load("sap_stats.json", {})
    players = load("players.json", {})
    stand = str((load("h2h_web.json", {}) or {}).get("stand") or "")
    if not stats or not players:
        print("Aufschlagwerte: keine Daten")
        return 0
    nm = NameMatcher(players.keys(), load("name_map.json", {}))

    summen = {}          # (name, belag) -> Zähler
    nicht = set()
    for e in stats.values():
        if str(e.get("start", ""))[:10] <= stand or e.get("belag") not in ("hard", "clay", "grass"):
            continue
        for seite, gegner in (("h", "a"), ("a", "h")):
            st, sg = e.get(seite + "s"), e.get(gegner + "s")
            if not st or not sg:
                continue
            name = nm.match(e.get(seite))
            if not name:
                nicht.add(e.get(seite))
                continue
            svpt, f_in = st.get("svpt"), st.get("first_in")
            f_won, s_won = st.get("first_won"), st.get("second_won")
            # Returnpunkte = Aufschlagpunkte des Gegners, die man gewonnen hat
            g_svpt, g_in, g_fw, g_sw = sg.get("svpt"), sg.get("first_in"), sg.get("first_won"), sg.get("second_won")
            if None in (svpt, f_in, f_won, s_won) or not svpt or svpt < 20:
                continue
            z = summen.setdefault((name, e["belag"]), {"n": 0, "svpt": 0, "in": 0, "fw": 0, "sw": 0, "s2": 0, "rw": 0, "rp": 0})
            z["n"] += 1
            z["svpt"] += svpt
            z["in"] += f_in
            z["fw"] += f_won
            z["sw"] += s_won
            z["s2"] += svpt - f_in
            if None not in (g_svpt, g_fw, g_sw) and g_svpt:
                z["rp"] += g_svpt
                z["rw"] += g_svpt - g_fw - g_sw

    live = {}
    n_fort, n_neu = 0, 0
    for (name, b), z in summen.items():
        p = players.get(name, {})
        excel = {f: p.get(f"{b}_{f}" if f != "ret" else f"ret_{b}") for f in FELDER}
        hat_excel = all(isinstance(v, (int, float)) for v in excel.values())
        if hat_excel:
            x1 = excel["1in"]
            werte = {
                "1in": (excel["1in"] * gewicht + z["in"]) / (gewicht + z["svpt"]),
                "1won": (excel["1won"] * gewicht * x1 + z["fw"]) / (gewicht * x1 + z["in"]),
                "2won": (excel["2won"] * gewicht * (1 - x1) + z["sw"]) / (gewicht * (1 - x1) + z["s2"]),
                "ret": (excel["ret"] * gewicht + z["rw"]) / (gewicht + z["rp"]) if z["rp"] else excel["ret"],
            }
            quelle = "excel+spieldaten"
            n_fort += 1
        else:
            if z["n"] < min_spiele or not z["in"] or not z["s2"] or not z["rp"]:
                continue
            werte = {"1in": z["in"] / z["svpt"], "1won": z["fw"] / z["in"], "2won": z["sw"] / z["s2"], "ret": z["rw"] / z["rp"]}
            quelle = "spieldaten"
            n_neu += 1
        rec = live.setdefault(name, {})
        for f, v in werte.items():
            rec[f"{b}_{f}" if f != "ret" else f"ret_{b}"] = round(v, 4)
        rec[f"n_{b}"] = z["n"]
        rec[f"quelle_{b}"] = quelle

    save("serve_live.json", {"stand": stand, "excel_gewicht_punkte": gewicht, "spieler": live})
    print(f"Aufschlagwerte: {n_fort} Spieler/Beläge fortgeschrieben (Excel + Spieldaten), {n_neu} neu nur aus Spieldaten "
          f"(ab {min_spiele} Spielen), {len(nicht)} Namen ohne Zuordnung")
    for n in sorted(x for x in nicht if x)[:10]:
        print("  ohne Zuordnung:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
