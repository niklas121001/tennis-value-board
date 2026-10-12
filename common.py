"""Gemeinsame Hilfen: Pfade, JSON, Namensabgleich, Belag-Erkennung."""
import json, re, unicodedata, difflib
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
        return self.exact[best[0]] if best else None


# ---------------------------------------------------------------- Belag
STOP = {"atp", "challenger", "men", "mens", "singles", "single", "open", "q", "quali", "qualifying",
        "qualification", "cup", "championships", "championship", "tour", "masters", "the", "de", "di",
        "international", "internationals", "trophy", "tennis", "classic", "finals", "presented", "by"}


def core_tokens(name):
    toks = [t for t in re.split(r"[\s,/()]+", norm(name)) if t and t not in STOP and not t.isdigit() and len(t) > 2]
    return toks


GENERIC = {"san", "santa", "saint", "port", "city", "north", "south", "east", "west", "nuevo", "nueva", "grand", "slam", "great", "royal"}


def detect_surface(turnier, turniere, history):
    """Liefert (belag, quelle). quelle: 'tabelle' | 'historie' | 'standard'."""
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
