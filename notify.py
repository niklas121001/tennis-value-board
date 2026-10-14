"""Telegram-Nachricht bei neuen Value-Tipps (nach log_tips.js).

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


def ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def de(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def units(kelly_eur, bank_modell, cfg):
    bank, unit = float(cfg.get("bankroll", 500)), float(cfg.get("unit_eur", 10))
    u = (kelly_eur or 0) * bank / bank_modell / unit
    if u <= 0:
        return None
    if u < 0.25:
        return "klein"
    u = min(3, max(0.5, round(u * 2) / 2))
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
        neu.append((key, t))
    if not neu:
        print("Telegram: keine neuen Value-Tipps")
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
        zeilen.append(f"\n<b>{esc(spieler)}</b> vs {esc(gegner)}\n{esc(t.get('turnier'))} · {TAGE[s.weekday()]} {s:%d.%m. %H:%M}\n" + " · ".join(teile))
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        zeilen.append(f'\n<a href="https://{owner.lower()}.github.io/{name}/">Zum Board</a>')
    text = "\n".join(zeilen)[:4000]
    if senden(text):
        gemeldet.update(k for k, _ in neu)
        print(f"Telegram: {len(neu)} Tipps gemeldet")
    save("telegram_gemeldet.json", sorted(k for k in gemeldet if k in log), indent=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
