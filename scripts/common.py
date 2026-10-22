"""Gemeinsame Hilfen: Pfade, JSON, Namensabgleich, Belag-Erkennung."""
import json, re, unicodedata, difflib, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"


def load(name, default=None):
    p = DATA / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save(name, obj, indent=1):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")


def config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Namen
def norm(s):
    s = unicodedata.normalize("NFKD", str(s).replace("\xa0", " "))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z ,.\-']", " ", s)
    s = s.replace("-", " ").replace("'", "").replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


PLATZHALTER = re.compile(
    r"\d|\b(tbd|tba|n\.?\s?n|winner|sieger|gewinner|loser|verlierer|qualifier|qualifikant|lucky|bye|freilos|"
    r"match|partie|spiel|round|runde|final|finale|halbfinale|viertelfinale|achtelfinale|semi|quarter|r16|r32|unknown|unbekannt)\b",
    re.I)


def ist_platzhalter(name):
    """True für unbesetzte Paarungen wie '1/8 Final 3 Winner', 'TBD', 'Qualifier', 'Sieger Spiel 12'."""
    n = str(name or "").strip()
    return not n or bool(PLATZHALTER.search(n))


def flip(s):
    """'Sinner, Jannik' -> 'Jannik Sinner'"""
    if "," in s:
        last, first = [x.strip() for x in s.split(",", 1)]
        return f"{first} {last}"
    return s


class NameMatcher:
    """Ordnet Namen aus fremden Quellen den Namen der Spieler-DB zu.

    Reihenfolge: manuelle Zuordnung (name_map.json) -> exakt -> 'Nachname Initiale'
    -> Nachname eindeutig -> unscharf (difflib >= 0.88).
    """

    def __init__(self, db_names, manual=None):
        self.db = list(db_names)
        self.manual = {norm(k): v for k, v in (manual or {}).items()}
        self.exact = {norm(n): n for n in self.db}
        self.by_last = {}
        for n in self.db:
            parts = norm(n).split()
            if parts:
                self.by_last.setdefault(parts[-1], []).append(n)
                # auch doppelte Nachnamen (z. B. 'Carreno Busta') abdecken
                if len(parts) >= 3:
                    self.by_last.setdefault(" ".join(parts[-2:]), []).append(n)

    def match(self, raw):
        if not raw:
            return None
        k = norm(raw)
        if k in self.manual:
            return self.manual[k]
        for cand in (norm(flip(raw)), k):
            if cand in self.exact:
                return self.exact[cand]
        # Formate wie 'Sinner J' oder 'J Sinner' oder 'Sinner, J.'
        f = norm(flip(raw)).split()
        if len(f) >= 2:
            for initial, last in ((f[0], " ".join(f[1:])), (f[-1], " ".join(f[:-1]))):
                if len(initial) == 1:
                    hits = [n for n in self.by_last.get(last, []) if norm(n).startswith(initial)]
                    if len(hits) == 1:
                        return hits[0]
        best = difflib.get_close_matches(norm(flip(raw)), list(self.exact), n=1, cutoff=0.88)
        if best:
            return self.exact[best[0]]
        # Gleicher Nachname + Vorname ist Kurz-/Langform ("Alex" ~ "Alexander", "Nico" ~ "Nicolas"), nur wenn eindeutig
        f = norm(flip(raw)).split()
        if len(f) >= 2:
            for i in range(1, len(f)):
                vor, nach = f[:i], " ".join(f[i:])
                kand = []
                for n in self.by_last.get(nach, []):
                    dv = norm(n).split()[0]
                    if len(vor[0]) >= 3 and len(dv) >= 3 and (dv.startswith(vor[0]) or vor[0].startswith(dv)):
                        kand.append(n)
                if len(set(kand)) == 1:
                    return kand[0]
            # Mehrere Initialen hinten oder vorne ("Ficovich J.P.", "J.P. Ficovich")
            hinten = [t for t in f if len(t) == 1]
            rest = [t for t in f if len(t) > 1]
            if len(hinten) >= 2 and rest and (all(len(t) == 1 for t in f[-len(hinten):]) or all(len(t) == 1 for t in f[:len(hinten)])):
                kand = {n for n in self.by_last.get(" ".join(rest), []) if norm(n).startswith(hinten[0])}
                if len(kand) == 1:
                    return kand.pop()
            # Zusätzlicher zweiter Nachname im Spielplan ("Daniel Merida Aguilar" ~ "Daniel Merida")
            kand = {n for n in self.db if len(norm(n).split()) == len(f) - 1 and norm(n).split() == f[:-1]}
            if len(kand) == 1:
                return kand.pop()
            # Doppelter Nachname nur teilweise geschrieben ("Pedro Martinez" ~ "Pedro Martinez Portero")
            kand = {n for n in self.db if norm(n).split()[:2] == f[:2] and len(norm(n).split()) > len(f) == 2}
            if len(kand) == 1:
                return kand.pop()
        return None


# ---------------------------------------------------------------- Belag
STOP = {"atp", "challenger", "men", "mens", "singles", "single", "open", "q", "quali", "qualifying",
        "qualification", "cup", "championships", "championship", "tour", "masters", "the", "de", "di",
        "international", "internationals", "trophy", "tennis", "classic", "finals", "presented", "by"}


def core_tokens(name):
    toks = [t for t in re.split(r"[\s,/()]+", norm(name)) if t and t not in STOP and not t.isdigit() and len(t) > 2]
    return toks


GENERIC = {"san", "santa", "saint", "port", "city", "north", "south", "east", "west", "nuevo", "nueva", "grand", "slam", "great", "royal"}


def kalender_belag(turnier, datum, kalender):
    """Belag aus dem Wikipedia-Kalender: Ort (oder Turniername ohne 'Challenger') kommt im Turniernamen vor,
    Turnierwoche passt zum Spieldatum (Wochenbeginn -2 bis +9 Tage). Nächstgelegene Woche gewinnt."""
    if not kalender:
        return None
    t = " " + norm(turnier) + " "
    try:
        d = datetime.date.fromisoformat(str(datum)[:10]) if datum else None
    except ValueError:
        d = None
    best = None
    for e in kalender:
        keys = {norm(e.get("ort", ""))}
        nm = norm(re.sub(r"(?i)challenger|open|cup|trophy|\b(i{1,3}|iv|v)\b|\d+", " ", e.get("name", "")))
        if nm:
            keys.add(nm)
        if not any(k and len(k) >= 3 and f" {k} " in t for k in keys):
            continue
        abstand = 0
        if d and e.get("woche"):
            w = datetime.date.fromisoformat(e["woche"])
            diff = (d - w).days
            if diff < -2 or diff > 9:
                continue
            abstand = abs(diff - 3)
        elif d:
            abstand = 99
        ist_ch = "challenger" in t
        if e.get("art") and (e["art"] == "challenger") != ist_ch:
            abstand += 50                     # ATP-Turnier und Challenger am selben Ort: passende Art bevorzugen
        if best is None or abstand < best[0]:
            best = (abstand, e["belag"])
    return best[1] if best else None


def detect_surface(turnier, turniere, history, kalender=None, datum=None):
    """Liefert (belag, quelle). quelle: 'kalender' | 'tabelle' | 'historie' | 'standard'."""
    kb = kalender_belag(turnier, datum, kalender)
    if kb:
        return kb, "kalender"
    t = norm(turnier)
    # 1) gepflegte Turniertabelle (Stichwort -> Belag), längste Stichworte zuerst
    for kw in sorted(turniere, key=len, reverse=True):
        if norm(kw) and re.search(r"\b" + re.escape(norm(kw)) + r"\b", t):
            return turniere[kw], "tabelle"
    # 2) eigene getrackte Spiele (ANALYSE) – Challenger wiederholen sich jährlich am selben Ort
    toks = {x for x in core_tokens(turnier) if len(x) >= 4 and x not in GENERIC}
    if toks:
        for m in reversed(history):
            if m.get("belag") in ("hard", "clay", "grass") and toks & set(core_tokens(m.get("turnier", ""))):
                return m["belag"], "historie"
    return "hard", "standard"


# ---------------------------------------------------------------- Quotenbereiche (Spieler-Check)
# Untergrenze inklusive, Obergrenze exklusiv. Muss mit QUOTEN_BAENDER in docs/model.js übereinstimmen.
QUOTEN_BAENDER = [1.0, 1.3, 1.5, 1.7, 1.9, 2.1, 2.5, 3.0, 4.0]


def quoten_band(q):
    """1.82 -> '1.70-1.90', 5.0 -> '4.00+'. None bei ungültiger Quote."""
    try:
        q = float(q)
    except (TypeError, ValueError):
        return None
    if q <= 1:
        return None
    for i, lo in enumerate(QUOTEN_BAENDER):
        hi = QUOTEN_BAENDER[i + 1] if i + 1 < len(QUOTEN_BAENDER) else None
        if hi is None:
            return f"{lo:.2f}+"
        if lo <= q < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return None


def spieler_bilanz_add(ziel, name, quote, gegen_quote, gewonnen):
    """Zählt ein Spiel in {name: {fav:[S,N], aus:[S,N], baender:{band:[S,N]}}}. Favorit = niedrigere Quote."""
    if not name or not quote or not gegen_quote:
        return
    rec = ziel.setdefault(name, {"fav": [0, 0], "aus": [0, 0], "baender": {}})
    rolle = "fav" if quote < gegen_quote else "aus" if quote > gegen_quote else None
    i = 0 if gewonnen else 1
    if rolle:
        rec[rolle][i] += 1
    b = quoten_band(quote)
    if b:
        rec["baender"].setdefault(b, [0, 0])[i] += 1


# ---------------------------------------------------------------- Doppelte Spieler (Mittelnamen)
STAT_FELDER = ("hard_1in", "clay_1in", "grass_1in")


def doppelte_zusammenfuehren(players, manual):
    """Führt Einträge zusammen, die sich nur durch Mittelnamen unterscheiden, z. B. 'Thiago Agustin Tirante'
    (Tennis Abstract, nur Elo) und 'Thiago Tirante' (Excel, mit Aufschlagwerten).
    Behalten wird der Eintrag mit Aufschlagwerten; er bekommt die Elo-Werte des anderen. Der andere Name
    wird in name_map.json auf den behaltenen abgebildet. Liefert die Liste der Zusammenführungen."""
    def hat_stats(rec):
        return any(isinstance(rec.get(f), (int, float)) for f in STAT_FELDER)

    toks = {n: norm(n).split() for n in players}
    nach_rand = {}
    for n, t in toks.items():
        if len(t) >= 2:
            nach_rand.setdefault((t[0], t[-1]), []).append(n)
    paare = []
    for gruppe in nach_rand.values():
        if len(gruppe) != 2:
            continue                      # nur eindeutige Fälle
        a, b = sorted(gruppe, key=lambda n: len(toks[n]))
        if len(toks[a]) == len(toks[b]) or not set(toks[a]) <= set(toks[b]):
            continue
        ra, rb = players[a], players[b]
        if ra.get("geschaetzt") or rb.get("geschaetzt"):
            continue
        if hat_stats(ra) and not hat_stats(rb):
            behalten, weg = a, b
        elif hat_stats(rb) and not hat_stats(ra):
            behalten, weg = b, a
        else:
            continue
        ziel, quelle = players[behalten], players[weg]
        for f in ("elo", "elo_hard", "elo_clay", "elo_grass"):
            if isinstance(quelle.get(f), (int, float)):
                ziel[f] = quelle[f]
        ziel.pop("neu", None)
        players.pop(weg)
        manual[weg] = behalten
        paare.append((weg, behalten))
    return paare


# ---------------------------------------------------------------- Plausibilitätsprüfung Aufschlagwerte (Excel-Basis)
PLAUSIBEL = {"1in": (0.50, 0.78), "1won": (0.55, 0.88), "2won": (0.35, 0.62), "ret": (0.22, 0.52)}


def unplausible_entfernen(players):
    """Setzt offensichtlich falsche Excel-Aufschlag-/Returnwerte auf leer (Original bleibt unter 'unplausibel').
    Regeln je Wert: außerhalb der Spanne in PLAUSIBEL; zusätzlich 1st Won <= 2nd Won -> beide leer.
    Leere Werte füllt das Modell mit dem Challenger-Durchschnitt bzw. serve_stats.py mit echten Spieldaten."""
    n = 0
    for name, r in players.items():
        alt = r.get("unplausibel", {})
        for s in ("hard", "clay", "grass"):
            keys = {"1in": f"{s}_1in", "1won": f"{s}_1won", "2won": f"{s}_2won", "ret": f"ret_{s}"}
            weg = set()
            manuell = r.get("manuell") or {}
            for f, k in keys.items():
                v = r.get(k)
                if k in manuell:
                    continue                       # von Hand eingetragen: nicht anfassen
                if isinstance(v, (int, float)) and not (PLAUSIBEL[f][0] <= v <= PLAUSIBEL[f][1]):
                    weg.add(f)
            w1, w2 = r.get(keys["1won"]), r.get(keys["2won"])
            if isinstance(w1, (int, float)) and isinstance(w2, (int, float)) and w1 <= w2 and not ({"1won", "2won"} & weg) \
                    and keys["1won"] not in manuell and keys["2won"] not in manuell:
                weg |= {"1won", "2won"}
            for f in weg:
                alt[keys[f]] = r[keys[f]]
                r[keys[f]] = None
                n += 1
        if alt:
            r["unplausibel"] = alt
    return n
