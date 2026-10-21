"""Telegram-Nachrichten (nach log_tips.js bzw. am Ende des Laufs mit --system).

  python notify.py           neue Value-Tipps (nach den Regeln in config.json "telegram.regeln", mit ⚠-Hinweisen)
                             + einmal täglich im Frühlauf ein Tagesbericht (gestern, Monat, heute offen)
  python notify.py --system  Systemcheck am Ende des Laufs: meldet Probleme (veraltete Daten, Kontingent knapp,
                             viele unbekannte Namen) – jede Warnung höchstens einmal pro Tag

Benötigt die GitHub-Secrets TELEGRAM_TOKEN (vom @BotFather) und TELEGRAM_CHAT_ID. Ohne sie: übersprungen.
Gemeldet wird jeder Tipp einmal (telegram_gemeldet.json), nur vor Spielbeginn und nur, wenn er in den
letzten 24 Stunden zum ersten Mal gesehen wurde. Einsatz in Units wie auf der Website (0,5er-Schritte, max. 3).
Token und Chat-ID werden nie ins (öffentliche) Protokoll geschrieben.
"""
import os, sys, json, datetime, urllib.request, urllib.parse
from zoneinfo import ZoneInfo
from common import load, save, config

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TZ = ZoneInfo("Europe/Berlin")
TAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
WARN_KURZ = {"aufgabe": "Aufgabe zuletzt", "pause": "lange Pause", "belag": "Belagwechsel", "quote": "Quote steigt", "favschwach": "Favorit schwach"}


def regel_ok(t, r):
    """Tipp-Regeln aus config.json telegram.regeln (alle optional)."""
    if not r:
        return True
    if r.get("min_edge") is not None and (t.get("edge") or 0) * 100 < float(r["min_edge"]):
        return False
    q = t.get("erstQuote") or 0
    if r.get("quote_min") and q < float(r["quote_min"]):
        return False
    if r.get("quote_max") and q > float(r["quote_max"]):
        return False
    ch = "challenger" in f"{t.get('turnier', '')} {t.get('kategorie') or ''}".lower()
    if r.get("turniere") == "atp" and ch or r.get("turniere") == "challenger" and not ch:
        return False
    if r.get("ohne_warnung") and t.get("warn"):
        return False
    return True


def units_zahl(kelly_eur, bank_modell, cfg):
    bank, unit = float(cfg.get("bankroll", 500)), float(cfg.get("unit_eur", 10))
    u = (kelly_eur or 0) * bank / bank_modell / unit
    if u <= 0:
        return 0
    return u if u < 0.25 else min(3, max(0.5, round(u * 2) / 2))


def board_link():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f'\n<a href="https://{owner.lower()}.github.io/{name}/">Zum Board</a>'
    return ""


def ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def de(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def units(kelly_eur, bank_modell, cfg):
    u = units_zahl(kelly_eur, bank_modell, cfg)
    if u <= 0:
        return None
    if u < 0.25:
        return "klein"
    return (str(int(u)) if u == int(u) else de(u, 1)) + " U"


def esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def senden(text):
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        # Fehlertext von Telegram enthält weder Token noch Chat-ID
        print(f"Telegram: HTTP {e.code} – {e.read().decode('utf-8', 'replace')[:200]}")
    except Exception as e:
        print(f"Telegram: {type(e).__name__}")
    return False


def main():
    cfg_all = config()
    cfg = cfg_all.get("telegram", {})
    if not TOKEN or not CHAT:
        print("Telegram: TELEGRAM_TOKEN/TELEGRAM_CHAT_ID fehlen – übersprungen")
        return 0
    if cfg.get("aktiv") is False:
        print("Telegram: in config.json abgeschaltet")
        return 0
    log = load("tips_log.json", {})
    gemeldet = set(load("telegram_gemeldet.json", []))
    bank_modell = float((load("params.json", {}) or {}).get("params", {}).get("BANKROLL") or 500)
    erlaubt = set(cfg_all.get("buchmacher", []))
    jetzt = datetime.datetime.now(datetime.timezone.utc)

    neu = []
    for key, t in log.items():
        start, erst = ts(t.get("start")), ts(t.get("erstGesehen"))
        if key in gemeldet or not start or start <= jetzt or not erst or jetzt - erst > datetime.timedelta(hours=24):
            continue
        if erlaubt and t.get("buchmacher") not in erlaubt:
            continue
        if not regel_ok(t, cfg.get("regeln")):
            gemeldet.add(key)          # außerhalb der Regeln: nicht melden, auch später nicht
            continue
        neu.append((key, t))
    tagesbericht(log, cfg, bank_modell, jetzt)
    if not neu:
        print("Telegram: keine neuen Value-Tipps")
        save("telegram_gemeldet.json", sorted(k for k in gemeldet if k in log), indent=0)
        return 0

    neu.sort(key=lambda x: x[1]["start"])
    zeilen = [f"🎾 <b>{len(neu)} neue{'r' if len(neu) == 1 else ''} Value-Tipp{'' if len(neu) == 1 else 's'}</b>"]
    for key, t in neu:
        seite = t.get("wette")
        spieler, gegner = (t["a"], t["b"]) if seite == "A" else (t["b"], t["a"])
        p = t.get("erstP")
        p_seite = p if seite == "A" else (1 - p if p is not None else None)
        s = ts(t["start"]).astimezone(TZ)
        q = t.get("letzteQuote") or t.get("erstQuote")
        teile = [f"{esc(t.get('buchmacher', '')).capitalize()} {de(q)}"]
        if p_seite:
            teile.append(f"fair {de(1 / p_seite)}")
        if t.get("edge") is not None:
            teile.append(f"Edge {'+' if t['edge'] > 0 else ''}{de(t['edge'] * 100, 1)} %")
        u = units(t.get("kelly"), bank_modell, cfg)
        if u:
            teile.append(u)
        warn = f"\n⚠ {', '.join(WARN_KURZ.get(w, w) for w in t['warn'])}" if t.get("warn") else ""
        zeilen.append(f"\n<b>{esc(spieler)}</b> vs {esc(gegner)}\n{esc(t.get('turnier'))} · {TAGE[s.weekday()]} {s:%d.%m. %H:%M}\n" + " · ".join(teile) + warn)
    zeilen.append(board_link())
    text = "\n".join(zeilen)[:4000]
    if senden(text):
        gemeldet.update(k for k, _ in neu)
        print(f"Telegram: {len(neu)} Tipps gemeldet")
    save("telegram_gemeldet.json", sorted(k for k in gemeldet if k in log), indent=0)
    return 0


def tagesbericht(log, cfg, bank_modell, jetzt):
    """Einmal pro Tag (erster Lauf nach 03 Uhr deutscher Zeit): gestern, laufender Monat, heute offen."""
    status = load("telegram_status.json", {})
    heute = jetzt.astimezone(TZ).date()
    if cfg.get("tagesbericht") is False or status.get("bericht") == heute.isoformat():
        return
    gestern = heute - datetime.timedelta(days=1)

    def bilanz(filter_):
        w = l = 0
        u = 0.0
        for t in log.values():
            s = ts(t.get("start"))
            if not s or not filter_(s.astimezone(TZ).date()) or t.get("ergebnis") not in ("W", "L"):
                continue
            st = units_zahl(t.get("kelly"), bank_modell, cfg)
            if t["ergebnis"] == "W":
                w += 1
                u += st * (t["erstQuote"] - 1)
            else:
                l += 1
                u -= st
        return w, l, u
    gw, gl, gu = bilanz(lambda d: d == gestern)
    mw, ml, mu = bilanz(lambda d: d.year == heute.year and d.month == heute.month)
    offen = sum(1 for t in log.values() if ts(t.get("start")) and ts(t["start"]) > jetzt)
    sg = lambda x: ("+" if x > 0 else "") + de(x, 1)
    text = (f"📊 <b>Tagesbericht {TAGE[heute.weekday()]} {heute:%d.%m.}</b>\n"
            f"Gestern: {gw}–{gl}" + (f" · {sg(gu)} U" if gw + gl else " (keine abgerechneten Tipps)") + "\n"
            f"{MONATE[heute.month - 1]}: {mw}–{ml} · {sg(mu)} U\n"
            f"Offene Tipps (kommende Partien): {offen}" + board_link())
    if senden(text):
        status["bericht"] = heute.isoformat()
        save("telegram_status.json", status)
        print("Telegram: Tagesbericht gesendet")


def systemcheck():
    """Probleme des Laufs melden – je Art höchstens einmal pro Tag."""
    cfg_all = config()
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    heute = jetzt.astimezone(TZ).date().isoformat()
    probleme = {}
    mj = load("matches.json", {}) or {}
    s = ts(mj.get("stand"))
    if not mj.get("demo") and (not s or jetzt - s > datetime.timedelta(hours=20)):
        probleme["quoten"] = "Spielplan/Quoten wurden seit über 20 Stunden nicht aktualisiert (OddsPapi-Schritt prüfen)."
    elif not mj.get("demo") and not mj.get("partien"):
        probleme["leer"] = "Der letzte Lauf hat keine einzige Partie geladen."
    op = load("oddspapi.json", {}) or {}
    monat = jetzt.strftime("%Y-%m")
    verbraucht, limit = (op.get("verbrauch") or {}).get(monat, 0), cfg_all.get("anfragen_limit_monat", 250)
    tage_rest = (datetime.date(jetzt.year + jetzt.month // 12, jetzt.month % 12 + 1, 1) - jetzt.date()).days
    if limit - verbraucht < 25 and tage_rest > 3:
        probleme["kontingent"] = f"OddsPapi-Kontingent fast aufgebraucht: {verbraucht}/{limit} Anfragen, noch {tage_rest} Tage im Monat."
    sp = load("sportsapipro.json", {}) or {}
    l = ts(sp.get("letzterLauf"))
    if os.environ.get("SPORTSAPIPRO_KEY") and (not l or jetzt - l > datetime.timedelta(hours=20)):
        probleme["sportsapipro"] = "SportsAPIPro lief seit über 20 Stunden nicht erfolgreich (Ergebnisse, Belag, H2H fehlen)."
    meta = load("meta.json", {}) or {}
    # unbekannte Spieler nur in Partien zählen, die relevant sind (keine Quali ohne Quote)
    un = {n for x in (mj.get("partien") or []) if not (x.get("quali") and not x.get("quoten"))
          for n, ok in ((x.get("a"), x.get("aInDb", True)), (x.get("b"), x.get("bInDb", True))) if not ok}
    if len(un) > 15:
        probleme["namen"] = f"{len(un)} Spielernamen konnten nicht zugeordnet werden (Modell-Reiter → Unbekannte Namen)."
    if meta.get("quoten_hinweis"):
        probleme["hinweis"] = str(meta["quoten_hinweis"])
    status = load("telegram_status.json", {})
    gemeldet = status.get("system", {})
    neu = {k: v for k, v in probleme.items() if gemeldet.get(k) != heute}
    print(f"Systemcheck: {len(probleme)} Auffälligkeiten" + (": " + " | ".join(probleme.values()) if probleme else ""))
    if not neu or not TOKEN or not CHAT or (cfg_all.get("telegram") or {}).get("systemwarnungen") is False:
        return 0
    if senden("⚙️ <b>Tennis Value Board – bitte prüfen</b>\n\n" + "\n".join("• " + esc(v) for v in neu.values()) + board_link()):
        gemeldet.update({k: heute for k in neu})
        status["system"] = gemeldet
        save("telegram_status.json", status)
    return 0


if __name__ == "__main__":
    sys.exit(systemcheck() if "--system" in sys.argv else main())
