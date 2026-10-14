"""Einmalige Umstellung: docs/data/history.json (eigene getrackte Spiele) -> turnier_belag.json (nur Turnier -> Belag).
Danach wird history.json gelöscht, damit die getrackten Spiele nicht mehr öffentlich im Repo liegen.
Läuft bei jedem Update mit und tut nichts, wenn history.json nicht (mehr) existiert."""
from common import DATA, load, save


def turnier_belag(history):
    """Je Turnier der zuletzt getrackte Belag, sortiert nach Datum (älteste zuerst)."""
    letzte = {}
    for m in history:
        t, b = str(m.get("turnier", "")).strip(), m.get("belag")
        if t and b in ("hard", "clay", "grass"):
            letzte[t] = {"turnier": t, "belag": b, "datum": m.get("datum")}
    return sorted(letzte.values(), key=lambda x: str(x.get("datum") or ""))


def main():
    p = DATA / "history.json"
    if not p.exists():
        return
    neu = turnier_belag(load("history.json", []))
    alt = {x["turnier"]: x for x in load("turnier_belag.json", [])}
    alt.update({x["turnier"]: x for x in neu})
    save("turnier_belag.json", sorted(alt.values(), key=lambda x: str(x.get("datum") or "")))
    p.unlink()
    print(f"history.json ersetzt durch turnier_belag.json ({len(alt)} Turniere)")


if __name__ == "__main__":
    main()
