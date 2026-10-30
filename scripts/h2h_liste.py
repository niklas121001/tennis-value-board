"""Alle H2H-Duelle mit Ergebnis -> docs/data/h2h_liste.json (für die Liste im Partie-Detail)

Quelle: TML-Database (github.com/Tennismylife/TML-Database): ATP-Ebene (Grand Slams, Masters, 500, 250, Finals,
Davis Cup), KEINE Challenger. Neuere Duelle (alle Stufen) ergänzt die Website live aus dem eigenen Ergebnis-Archiv.
NUR PRIVAT: laut Nutzungsbedingungen keine kommerzielle Nutzung (vor Premium ersetzen/lizenzieren).
Aufruf (manuell, ab und zu):  python scripts/h2h_liste.py /pfad/zu/tml-database

Format: {"stand": "YYYY-MM-DD", "bis": letztes Turnierdatum, "paare": {"Name1|Name2" (alphabetisch): [
           [Turnier-Startdatum YYYYMMDD, Turnier, Belag H/C/G/P, Runde, Sieger 0=Name1/1=Name2, Ergebnis], ... neueste zuerst]}}
Nur Paare, bei denen beide Spieler in players.json stehen.
"""
import csv, glob, json, os, sys, datetime
sys.path.insert(0, os.path.dirname(__file__))
from common import NameMatcher, load, DATA

AB = "1990"


def main(pfad):
    players = load("players.json", {})
    nm = NameMatcher(list(players), load("name_map.json", {}))
    dateien = sorted(f for f in glob.glob(os.path.join(pfad, "[12][0-9][0-9][0-9].csv")) if os.path.basename(f)[:4] >= AB)
    dateien.append(os.path.join(pfad, "ongoing_tourneys.csv"))
    cache, paare, gesehen, bis = {}, {}, set(), ""

    def db(n):
        if n not in cache:
            cache[n] = nm.match(n) if n else None
        return cache[n]

    for f in dateien:
        if not os.path.exists(f):
            continue
        with open(f, encoding="utf-8", errors="ignore") as fh:
            for r in csv.DictReader(fh):
                w, l = db(r.get("winner_name")), db(r.get("loser_name"))
                if not w or not l or w == l:
                    continue
                key_ = (r.get("tourney_id"), r.get("match_num"), w, l)
                if key_ in gesehen:                       # ongoing_tourneys.csv überschneidet sich mit dem Jahr
                    continue
                gesehen.add(key_)
                x, y = sorted([w, l])
                d = str(r.get("tourney_date", ""))
                bis = max(bis, d)
                name = (r.get("tourney_name") or "").strip()
                paare.setdefault(f"{x}|{y}", []).append(
                    [d, name, (r.get("surface") or "?")[:1].upper(), r.get("round") or "", 0 if w == x else 1, (r.get("score") or "").strip()])
    for v in paare.values():
        v.sort(key=lambda e: e[0], reverse=True)
    out = {"stand": datetime.date.today().isoformat(), "bis": bis,
           "quelle": "TML-Database (ATP-Ebene, ohne Challenger) – nur privat", "paare": paare}
    (DATA / "h2h_liste.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(len(v) for v in paare.values())
    print(f"H2H-Liste: {len(paare)} Paare, {n} Duelle, TML bis {bis}, Datei {round((DATA / 'h2h_liste.json').stat().st_size / 1024)} KB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../tennismylife/tml-database")
