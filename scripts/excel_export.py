"""Exportiert die Stammdaten aus Analysetool_Belag.xlsx nach data/*.json.

Aufruf:  python scripts/excel_export.py Pfad/zu/Analysetool_Belag.xlsx [--merge] [--tests]
Excel-Updates laufen über den Chat (die Excel soll nicht ins öffentliche Repo): --merge behält Elo + geschätzte Spieler.
Kann jederzeit erneut laufen, wenn die Excel weiter gepflegt wird.
"""
import json, sys, datetime, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import openpyxl

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ".").replace("\xa0", ""))
    except ValueError:
        return None


def clean(s):
    return str(s).replace("\xa0", " ").strip() if s is not None else ""


def main(path, merge=False, tests=False):
    wb = openpyxl.load_workbook(path, data_only=True)
    DATA.mkdir(exist_ok=True)

    # ---- PARAMETER (Name -> Wert, Spalte A/B) ----
    ws = wb["PARAMETER"]
    params = {}
    for r in ws.iter_rows(min_row=1, max_row=120, max_col=2, values_only=True):
        k, v = r
        if isinstance(k, str) and k.isupper() and k.replace("_", "").isalnum():
            if isinstance(v, (datetime.date, datetime.datetime)):
                v = v.strftime("%Y-%m-%d")
            params[k] = v
    # App-Parameter (nicht in der Excel): Umgang mit fehlenden Aufschlagwerten
    #   "nur_elo" = Statistik-Teil entfällt, wenn einem Spieler Werte fehlen
    #   "excel"   = wie die Excel (leere Zellen zählen als 0)
    params.setdefault("FEHLENDE_STATS", "nur_elo")
    # CSI-Tabelle
    csi = []
    for r in ws.iter_rows(min_row=50, max_row=67, max_col=5, values_only=True):
        if r[0]:
            csi.append({"name": clean(r[0]), "csi": num(r[1]), "alias": clean(r[4])})

    # ---- SPIELER_DB ----
    ws = wb["SPIELER_DB"]
    cols = ["elo", "hard_1in", "hard_1won", "hard_2won", "clay_1in", "clay_1won", "clay_2won",
            "grass_1in", "grass_1won", "grass_2won", "ret_hard", "ret_clay", "ret_grass",
            "tb", "elo_hard", "elo_clay", "elo_grass"]
    players = {}
    for r in ws.iter_rows(min_row=4, max_col=18, values_only=True):
        name = clean(r[0])
        if not name:
            continue
        players[name] = {c: num(v) for c, v in zip(cols, r[1:18])}

    # ---- SPIELER-STATS (Favorit/Außenseiter-Bilanz) ----
    ws = wb["SPIELER-STATS"]
    pstats = {}
    for r in ws.iter_rows(min_row=11, max_col=11, values_only=True):
        name = clean(r[1])
        if not name:
            continue
        fav_n = (r[4] or 0) + (r[5] or 0)
        aus_n = (r[8] or 0) + (r[9] or 0)
        pstats[name] = {"fav_pct": num(r[6]), "fav_n": fav_n, "aus_pct": num(r[10]), "aus_n": aus_n}

    # ---- H2H: Gesamtbilanz (manuell + getrackt) ----
    ws = wb["H2H"]
    h2h = {}
    for r in ws.iter_rows(min_row=4, max_col=14, values_only=True):
        a, b = clean(r[0]), clean(r[1])
        if not a or not b:
            continue
        wa, wb_ = int(num(r[12]) or 0), int(num(r[13]) or 0)
        # Excel nimmt bei Dubletten den ersten Treffer (MATCH) -> erster gewinnt
        if f"{a}|{b}" not in h2h and f"{b}|{a}" not in h2h:
            h2h[f"{a}|{b}"] = [wa, wb_]

    # ---- ANALYSE: getrackte Spiele (für H2H-Fallback und spätere Auswertung) ----
    ws = wb["ANALYSE"]
    stichtag = datetime.datetime.strptime(params.get("H2H_STICHTAG", "2026-04-04"), "%Y-%m-%d")
    history = []
    for r in ws.iter_rows(min_row=5, max_col=16, values_only=True):
        if not r[2]:
            continue
        d = r[3]
        history.append({
            "turnier": clean(r[1]), "belag": clean(r[2]).lower(),
            "datum": d.strftime("%Y-%m-%d") if isinstance(d, datetime.datetime) else None,
            "a": clean(r[4]), "b": clean(r[5]), "qa": num(r[6]), "qb": num(r[7]),
            "pa": num(r[8]), "sieger": clean(r[15]),
        })
    # Paare, die nicht in der H2H-Tabelle stehen: aus ANALYSE ab Stichtag zählen
    tracked = {}
    for m in history:
        if not m["datum"] or m["sieger"] not in ("A", "B"):
            continue
        if datetime.datetime.strptime(m["datum"], "%Y-%m-%d") < stichtag:
            continue
        w, l = (m["a"], m["b"]) if m["sieger"] == "A" else (m["b"], m["a"])
        tracked[(w, l)] = tracked.get((w, l), 0) + 1
    for (w, l), n in tracked.items():
        a, b = sorted([w, l])
        key = f"{a}|{b}"
        if key in h2h or f"{b}|{a}" in h2h:
            continue
        h2h[key] = [tracked.get((a, b), 0), tracked.get((b, a), 0)]

    # Quotenbereiche je Spieler aus ANALYSE (nur Summen je Spieler und Bereich werden veröffentlicht, keine Einzelspiele)
    from common import spieler_bilanz_add
    bilanz = {}
    for m in history:
        if m["sieger"] not in ("A", "B"):
            continue
        spieler_bilanz_add(bilanz, m["a"], m["qa"], m["qb"], m["sieger"] == "A")
        spieler_bilanz_add(bilanz, m["b"], m["qb"], m["qa"], m["sieger"] == "B")
    for name, rec in bilanz.items():
        ziel = pstats.setdefault(name, {"fav_pct": None, "fav_n": 0, "aus_pct": None, "aus_n": 0})
        ziel["baender"] = rec["baender"]
        if rec.get("gbaender"):
            ziel["gbaender"] = rec["gbaender"]

    # ---- BLACKLIST ----
    ws = wb["BLACKLIST"]
    blacklist = [clean(r[0]) for r in ws.iter_rows(min_row=4, max_col=1, values_only=True) if clean(r[0])]

    # Test-Vorlagen (eingefrorener Excel-Stand) neu schreiben: Spieler-DB + gespeicherte DASHBOARD-Werte
    if tests:
        TESTS = ROOT / "tests"
        (TESTS / "players_excel.json").write_text(json.dumps(players, ensure_ascii=False, indent=1), encoding="utf-8")
        (TESTS / "params_excel.json").write_text(json.dumps({"params": params, "csi": csi}, ensure_ascii=False, indent=1), encoding="utf-8")
        ws = wb["DASHBOARD"]
        rows = []
        for r in ws.iter_rows(min_row=5, max_row=36, max_col=52, values_only=True):
            if not r[4] or not isinstance(r[6], (int, float)) or not isinstance(r[16], (int, float)):
                continue
            rows.append(dict(turnier=r[1], belag=r[2], a=r[4], b=r[5], qa=r[6], qb=r[7], eloA=r[8], eloB=r[9],
                             pSrvA=r[10], pSrvB=r[11], pStats=r[12], pElo=r[13], pFinal=r[16], fairA=r[17], fairB=r[18],
                             edgeA=r[19], empf=r[23], kelly=r[34], csi=r[35], spieleA=r[26], spieleB=r[27], modus=r[42], top=r[44]))
        (TESTS / "excel_dashboard.json").write_text(json.dumps(rows, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        print(f"Test-Vorlagen: {len(rows)} DASHBOARD-Partien")

    # Zusammenführen statt überschreiben: Elo-Werte (täglich von Tennis Abstract) und geschätzte Spieler bleiben,
    # aus der Excel kommen Aufschlag-/Return-/Tiebreak-Werte.
    if merge and (DATA / "players.json").exists():
        alt = json.loads((DATA / "players.json").read_text(encoding="utf-8"))
        elo_felder = ("elo", "elo_hard", "elo_clay", "elo_grass")
        neu_gesamt = dict(alt)
        for name, rec in players.items():
            if name in alt:
                ziel = dict(alt[name])
                for k, v in rec.items():
                    if k in elo_felder and ziel.get(k) is not None:
                        continue                      # aktuelles Elo behalten
                    if v is not None:
                        ziel[k] = v
                ziel.pop("neu", None)
                neu_gesamt[name] = ziel
            else:
                neu_gesamt[name] = rec
        print(f"Zusammengeführt: {len(players)} Spieler aus der Excel, {len(neu_gesamt)} insgesamt "
              f"(Elo-Werte und geschätzte Spieler beibehalten)")
        players = neu_gesamt

    # H2H-Stichtag: alles bis zum letzten ANALYSE-Datum steckt jetzt in h2h.json; Website-Spiele bis dahin verwerfen
    daten = [m["datum"] for m in history if m.get("datum")]
    stand = max(daten) if daten else None
    hw_pfad = DATA / "h2h_web.json"
    hw = json.loads(hw_pfad.read_text(encoding="utf-8")) if hw_pfad.exists() else {"spiele": {}}
    if stand:
        hw["stand"] = stand
        hw["spiele"] = {k: v for k, v in hw.get("spiele", {}).items() if str(v.get("start", ""))[:10] > stand}
        paare = {}
        for sp in hw["spiele"].values():
            x, y = sorted([sp["sieger"], sp["verlierer"]])
            rec = paare.setdefault(f"{x}|{y}", [0, 0])
            rec[0 if sp["sieger"] == x else 1] += 1
        hw["paare"] = paare
        hw_pfad.write_text(json.dumps(hw, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"H2H-Stichtag: {stand} ({len(hw['spiele'])} Website-Spiele danach bleiben)")

    out = {
        "params.json": {"params": params, "csi": csi},
        "players.json": players,
        "player_stats.json": pstats,
        "h2h.json": h2h,
        "blacklist.json": blacklist,
        # Nur Turnier -> Belag veröffentlichen (keine getrackten Spiele, Quoten oder Ergebnisse)
        "turnier_belag.json": __import__("migrate_history").turnier_belag(history),
    }
    for fn, obj in out.items():
        (DATA / fn).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "history.json").unlink(missing_ok=True)
    print(f"Spieler: {len(players)}, H2H-Paare: {len(h2h)}, Blacklist: {len(blacklist)}, getrackte Spiele (nur intern genutzt): {len(history)}, Parameter: {len(params)}")


if __name__ == "__main__":
    # python excel_export.py Datei.xlsx [--merge] [--tests]
    #   --merge  bestehende players.json ergänzen (Elo + geschätzte Spieler behalten) statt ersetzen
    #   --tests  Test-Vorlagen in tests/ aus derselben Excel neu erzeugen
    args = sys.argv[1:]
    main(args[0], merge="--merge" in args, tests="--tests" in args)
