// Rechnet alle Partien aus matches.json mit dem Modell durch und protokolliert Value-Signale
// in docs/data/tips_log.json (erste + letzte gesehene Quote je Buchmacher -> Basis für CLV).
const fs = require("fs"), path = require("path");
const M = require("../docs/model.js");
const dir = path.join(__dirname, "..", "docs", "data");
const rd = (f, d) => (fs.existsSync(path.join(dir, f)) ? JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")) : d);

const P = rd("params.json");
const D = { params: P.params, csi: P.csi, tempo: (rd("tempo.json", {}) || {}).turniere || [], players: rd("players.json"), h2h: rd("h2h.json"), playerStats: rd("player_stats.json"), blacklist: rd("blacklist.json", []), statsAvg: rd("stats_avg.json", null), h2hWeb: (rd("h2h_web.json", {}) || {}).paare || {}, h2hApi: (rd("h2h_api.json", {}) || {}).paare || {},
  playerStatsWeb: (rd("player_stats_web.json", {}) || {}).spieler || {}, serveLive: (rd("serve_live.json", {}) || {}).spieler || {} };
const mj = rd("matches.json", { partien: [] });
if (mj.demo) { console.log("Demo-Daten – nichts protokolliert"); process.exit(0); }
const matches = mj.partien;
const log = rd("tips_log.json", {});
// Warnhinweise je Seite: aus dem Spielplan (Aufgabe, Pause, Belagwechsel) + schwacher Favorit (Spieler-Check)
function warnTypen(m, r, seite, qa, qb) {
  const t = (m.warnungen || []).filter((w) => w.seite === seite).map((w) => w.typ);
  const f = r.favCheck, minN = P.params.AUSSENSEITER_MIN_N || 7, max = P.params.FAV_WARN_MAX || 0.6;
  const favSeite = qa < qb ? "A" : qb < qa ? "B" : null;
  if (f && f.pct != null && f.n >= minN && f.pct < max && favSeite === seite) t.push("favschwach");
  // langes Match am Vortag (ab 150 Min. bzw. 33 Games, letztes Spiel höchstens 1 Tag vor dieser Partie)
  const fo = m.form && m.form[seite === "A" ? "a" : "b"];
  if (fo && fo.letztes && m.start && (new Date(m.start) - new Date(fo.letztes)) / 864e5 <= 1.5
      && ((fo.letztesMin && fo.letztesMin >= 150) || (!fo.letztesMin && fo.letztesGames >= 33))) t.push("langesmatch");
  return t;
}
const now = new Date().toISOString().slice(0, 16) + "Z";
const r3 = (x) => (typeof x === "number" && isFinite(x) ? Math.round(x * 1000) / 1000 : null);
let neu = 0;

for (const m of matches) {
  // Nur vor Spielbeginn tippen – ein Tipp nach Anpfiff wäre für die Bilanz wertlos
  if (!m.start || new Date(m.start) <= new Date()) continue;
  // Geschätzte Spieler (Elo aus Marktquoten) erst nach MIN_ERG Ergebnissen in die Bilanz – vorher spiegelt ihr Elo nur den Markt
  const MIN_ERG = 5, unsicher = (n) => D.players[n] && D.players[n].geschaetzt && (D.players[n].n_erg || 0) < MIN_ERG;
  if (unsicher(m.a) || unsicher(m.b)) continue;
  for (const [bm, [qa, qb]] of Object.entries(m.quoten || {})) {
    if ((m.pausiert || []).includes(bm)) continue;   // pausierte Quote: aktuell nicht spielbar
    const r = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
    if (!r.ok || !r.wette) continue;
    const key = `${m.id}|${bm}`;
    const q = r.wette === "A" ? qa : qb;
    // Erste Sichtung wird eingefroren (Tippquote, Edge, Kelly) – spätere Läufe ändern nur "letzte*"
    const e = log[key] || { id: m.id, start: m.start, turnier: m.turnier, belag: m.belag, a: m.a, b: m.b,
      tid: m.tid, p1Id: m.p1Id, p2Id: m.p2Id, kategorie: m.kategorie,
      buchmacher: bm, wette: r.wette, erstQuote: q, erstP: r.pFinal, edge: r.wette === "A" ? r.edgeA : r.edgeB,
      kelly: r.kelly, erstGesehen: now,
      warn: warnTypen(m, r, r.wette, qa, qb) };   // Warnhinweise beim Tipp (für die Auswertung)
    if (!log[key]) neu++;
    e.start = m.start;  // Ansetzung kann sich verschieben
    Object.assign(e, { letzteQuote: q, letzteP: r.pFinal, zuletztGesehen: now });
    log[key] = e;
  }
}
// Korrekturen vor Spielbeginn: Spielerwerte von Hand korrigiert (manuelle_werte.json) oder Quote angepasst
// (manuelle_quoten.json, von der Website gespeichert). Offene Tipps dieser Partien werden mit den korrigierten Daten
// neu gerechnet: kein Value mehr -> "storniert" (zählt nicht in der Bilanz), sonst bleibt der Tipp (bei angepasster
// Quote mit dieser Quote). Wird die Korrektur zurückgenommen, gilt der Tipp wieder wie protokolliert.
{
  const manQ = rd("manuelle_quoten.json", {}), manW = rd("manuelle_werte.json", {}), qv = rd("quoten_verlauf.json", {});
  const z16 = (x) => String(x || "").slice(0, 16);
  const byId = Object.fromEntries(matches.map((m) => [m.id, m]));
  let storno = 0;
  for (const t of Object.values(log)) {
    if (t.ergebnis || !t.start || new Date(t.start) <= new Date()) continue;
    const m = byId[t.id]; if (!m) continue;
    const q = manQ[t.id], qOk = q && q.bm === t.buchmacher && z16(q.zeit) > z16(t.erstGesehen) && z16(q.zeit) < z16(t.start);
    const wOk = [m.a, m.b].some((n) => manW[n] && z16(manW[n]._zeit) > z16(t.erstGesehen) && z16(manW[n]._zeit) < z16(t.start));
    if (!qOk && !wOk) {
      if (t.storniert) { delete t.storniert; delete t.stornoInfo; }
      if (t.erstQuoteOrig) { t.erstQuote = t.erstQuoteOrig; delete t.erstQuoteOrig; }
      continue;
    }
    // Nur Spielerwerte korrigiert: mit den Quoten zum Tipp-Zeitpunkt rechnen (sonst würde eine Marktbewegung storniert)
    let qa, qb;
    if (qOk) [qa, qb] = [q.qa, q.qb];
    else {
      const reihe = ((qv[t.id] || {}).bm || {})[t.buchmacher] || [];
      const vor = reihe.filter((x) => z16(x[0]) <= z16(t.erstGesehen)), e0 = vor[vor.length - 1] || reihe[0];
      [qa, qb] = e0 ? [e0[1], e0[2]] : ((m.quoten || {})[t.buchmacher] || []);
      if (t.wette === "A") qa = t.erstQuote; else qb = t.erstQuote;
    }
    if (!(qa > 1 && qb > 1)) continue;
    const r = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
    if (!r.ok) continue;
    const pS = t.wette === "A" ? r.pFinal : 1 - r.pFinal, qS = t.wette === "A" ? qa : qb;
    if (r.wette !== t.wette) {
      if (!t.storniert) storno++;
      t.storniert = wOk ? "werte" : "quote";
      t.stornoInfo = `Modell ${Math.round(pS * 1000) / 10} % (fair ${(1 / pS).toFixed(2)}) bei Quote ${qS.toFixed(2)} – kein Value`;
    } else {
      delete t.storniert; delete t.stornoInfo;
      if (qOk && Math.abs(qS - t.erstQuote) > 1e-9) { t.erstQuoteOrig = t.erstQuoteOrig || t.erstQuote; t.erstQuote = qS; }
    }
  }
  if (storno) console.log(`Tipps storniert (Daten korrigiert, kein Value mehr): ${storno}`);
}
fs.writeFileSync(path.join(dir, "tips_log.json"), JSON.stringify(log, null, 0));

// Test-Varianten B und C (Hintergrund, Auswertung zum Jahresende): eigene Tipps mit derselben Value-Regel.
// Erste Sichtung wird eingefroren, letzte Quote vor Spielbeginn dient als Schlussquote (CLV).
const vlog = rd("varianten_tips.json", {});
let neuV = 0;
for (const m of matches) {
  if (!m.start || new Date(m.start) <= new Date()) continue;
  const MIN_ERG = 5, unsicher = (n) => D.players[n] && D.players[n].geschaetzt && (D.players[n].n_erg || 0) < MIN_ERG;
  if (unsicher(m.a) || unsicher(m.b)) continue;
  for (const [bm, [qa, qb]] of Object.entries(m.quoten || {})) {
    if ((m.pausiert || []).includes(bm)) continue;
    const r = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
    if (!r.ok || !r.varianten) continue;
    for (const [v, x] of Object.entries(r.varianten)) {
      const key = `${v}|${m.id}|${bm}`;
      if (vlog[key]) {                       // schon getippt: nur letzte Quote nachführen
        const e = vlog[key]; e.letzteQuote = e.wette === "A" ? qa : qb; e.zuletztGesehen = now; e.start = m.start; continue;
      }
      if (!x.wette) continue;
      const q = x.wette === "A" ? qa : qb;
      vlog[key] = { variante: v, id: m.id, start: m.start, turnier: m.turnier, kategorie: m.kategorie, belag: m.belag,
        a: m.a, b: m.b, buchmacher: bm, wette: x.wette, erstQuote: q, letzteQuote: q, erstP: r3(x.p), edge: r3(x.edge),
        kelly: x.kelly, erstGesehen: now, zuletztGesehen: now,
        warn: warnTypen(m, r, x.wette, qa, qb) };
      neuV++;
    }
  }
}
fs.writeFileSync(path.join(dir, "varianten_tips.json"), JSON.stringify(vlog));

// Weitere Signale (Test, Auswertung zum Jahresende) -> signale_log.json, flach 1 U je Signal (Tagesziel: Einsatz für 1 U Gewinn):
//  sturz     – Quote eines Spielers seit erster Sichtung um mind. 10 % (und 0,10) gefallen: Tipp auf diesen Spieler
//  comeback  – Spieler gewinnt auffällig oft nach verlorenem 1. Satz (Archiv, mind. 2 von 3, >= 50 %): Tipp auf Sieg
// Außerdem in tips_log.json: valueWeg (Value-Tipp ist vor Spielbeginn mit der aktuellen Quote kein Value mehr)
{
  const slog = rd("signale_log.json", {}), qv = rd("quoten_verlauf.json", {});
  // Archiv der letzten 12 Monate für die Comeback-Auswertung
  const adir = path.join(dir, "archiv"), arch = [];
  if (fs.existsSync(adir)) for (const f of fs.readdirSync(adir).filter((f) => /^\d{4}-\d{2}\.json$/.test(f)).sort().slice(-12))
    arch.push(...Object.values(JSON.parse(fs.readFileSync(path.join(adir, f), "utf8"))));
  const cbCache = {};
  const comeback = (name) => {
    if (cbCache[name]) return cbCache[name];
    let rueck = 0, cb = 0;
    for (const x of arch) {
      const seite = x.a === name ? "A" : x.b === name ? "B" : null;
      if (!seite || !(x.sieger === "A" || x.sieger === "B") || x.aufgabe) continue;
      const st = (x.satz || []).filter((t) => Array.isArray(t) && t[0] !== t[1]);
      if (st.length < 2) continue;
      if (seite === "A" ? st[0][0] < st[0][1] : st[0][0] > st[0][1]) { rueck++; if (x.sieger === seite) cb++; }
    }
    return (cbCache[name] = { rueck, cb });
  };
  let neuS = 0;
  const neuSignal = (key, obj) => { if (slog[key]) return; slog[key] = Object.assign({ erstGesehen: now, zuletztGesehen: now }, obj); neuS++; };
  for (const m of matches) {
    if (!m.start || new Date(m.start) <= new Date()) continue;
    for (const [bm, [qa, qb]] of Object.entries(m.quoten || {})) {
      if ((m.pausiert || []).includes(bm)) continue;
      const basis = { id: m.id, start: m.start, turnier: m.turnier, kategorie: m.kategorie, belag: m.belag, a: m.a, b: m.b, buchmacher: bm };
      // laufende Signale: letzte Quote mitschreiben (CLV)
      for (const typ of ["sturz", "comeback", "tagesziel"]) {
        const e = slog[`${typ}|${m.id}|${bm}`];
        if (e) { e.letzteQuote = e.wette === "A" ? qa : qb; e.zuletztGesehen = now; e.start = m.start; }
      }
      const reihe = ((qv[m.id] || {}).bm || {})[bm] || [];
      if (reihe.length >= 2) for (const [seite, i] of [["A", 1], ["B", 2]]) {
        const erst = reihe[0][i], jetzt = seite === "A" ? qa : qb;
        if (erst > 1 && jetzt > 1 && 1 - jetzt / erst >= 0.10 && erst - jetzt >= 0.10)
          neuSignal(`sturz|${m.id}|${bm}`, Object.assign({ typ: "sturz", wette: seite, erstQuote: jetzt, letzteQuote: jetzt, anfangsQuote: erst,
            fall: r3(1 - jetzt / erst) }, basis));
      }
      for (const seite of ["A", "B"]) {
        const z = comeback(seite === "A" ? m.a : m.b);
        if (z.rueck >= 3 && z.cb >= 2 && z.cb / z.rueck >= 0.5) {
          const q = seite === "A" ? qa : qb;
          neuSignal(`comeback|${m.id}|${bm}`, Object.assign({ typ: "comeback", wette: seite, erstQuote: q, letzteQuote: q, rueck: z.rueck, cb: z.cb }, basis));
        }
      }
      // Tagesziel (Reiter „Tagesziel“, Standard-Einstellung): Siegchance (Mittel Modell/Markt) >= 70 % und
      // Einsatz für 1 U Gewinn <= 3 U. Getrackt mit dem Einsatz für 1 U Gewinn (= 1 / (Quote − 1)).
      {
        const rr = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
        if (rr.ok && rr.pMarkt != null && rr.pFinal != null) for (const seite of ["A", "B"]) {
          const q = seite === "A" ? qa : qb, pz = seite === "A" ? (rr.pFinal + rr.pMarkt) / 2 : 1 - (rr.pFinal + rr.pMarkt) / 2;
          if (q > 1 && pz >= 0.7 && 1 / (q - 1) <= 3)
            neuSignal(`tagesziel|${m.id}|${bm}`, Object.assign({ typ: "tagesziel", wette: seite, erstQuote: q, letzteQuote: q, pz: r3(pz),
              einsatzU: r3(1 / (q - 1)) }, basis));
        }
      }
      // Value-Tipp weg? (Tipp protokolliert, mit der aktuellen Quote kein Value mehr)
      const t = log[`${m.id}|${bm}`];
      if (t && !t.ergebnis) {
        const r = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
        if (r.ok && r.wette !== t.wette && !t.valueWeg) { t.valueWeg = now; t.valueWegQuote = t.wette === "A" ? qa : qb; }
        else if (r.ok && r.wette === t.wette && t.valueWeg) { delete t.valueWeg; delete t.valueWegQuote; }
      }
    }
  }
  fs.writeFileSync(path.join(dir, "signale_log.json"), JSON.stringify(slog));
  fs.writeFileSync(path.join(dir, "tips_log.json"), JSON.stringify(log, null, 0));
  console.log(`Weitere Signale (Quotensturz/Comeback): ${neuS} neu, insgesamt ${Object.keys(slog).length}`);
}

// Außenseiter-Signale: separat tracken (Tipp auf den Markt-Außenseiter, flacher Einsatz)
const alog = rd("aussenseiter_tips.json", {});
let neuA = 0;
for (const m of matches) {
  if (!m.start || new Date(m.start) <= new Date()) continue;
  for (const [bm, [qa, qb]] of Object.entries(m.quoten || {})) {
    if ((m.pausiert || []).includes(bm)) continue;
    const r = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
    const key = `${m.id}|${bm}`;
    if (alog[key]) { const e = alog[key]; e.letzteQuote = e.wette === "A" ? qa : qb; e.zuletztGesehen = now; e.start = m.start; continue; }
    const x = r.ok && r.aussenseiter;
    if (!x) continue;
    alog[key] = { id: m.id, start: m.start, turnier: m.turnier, kategorie: m.kategorie, belag: m.belag, a: m.a, b: m.b,
      buchmacher: bm, wette: x.seite, erstQuote: x.quote, letzteQuote: x.quote, pModell: r3(x.pModell), pMarkt: r3(x.pMarkt),
      favPct: r3(x.favPct), favN: x.favN, ausPct: r3(x.ausPct), ausN: x.ausN, valueTipp: r.wette === x.seite,
      erstGesehen: now, zuletztGesehen: now };
    neuA++;
  }
}
fs.writeFileSync(path.join(dir, "aussenseiter_tips.json"), JSON.stringify(alog));

// Bilanz-Signale (Test): Siegquote im Quotenbereich spricht für den Spieler, ohne Modell-Value. Separat getrackt.
const blog = rd("bilanz_tips.json", {});
let neuB = 0;
for (const m of matches) {
  if (!m.start || new Date(m.start) <= new Date()) continue;
  for (const [bm, [qa, qb]] of Object.entries(m.quoten || {})) {
    if ((m.pausiert || []).includes(bm)) continue;
    const key = `${m.id}|${bm}`;
    if (blog[key]) { const e = blog[key]; e.letzteQuote = e.wette === "A" ? qa : qb; e.zuletztGesehen = now; e.start = m.start; continue; }
    const r = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
    const x = r.ok && r.bilanzSignal;
    if (!x) continue;
    blog[key] = { id: m.id, start: m.start, turnier: m.turnier, kategorie: m.kategorie, belag: m.belag, a: m.a, b: m.b,
      buchmacher: bm, wette: x.seite, erstQuote: x.quote, letzteQuote: x.quote, band: x.band, siege: x.siege, n: x.n,
      pBand: r3(x.pBand), pEst: r3(x.pEst), pMarkt: r3(x.pMarkt), edge: r3(x.edge), kellyEur: x.kellyEur,
      erstGesehen: now, zuletztGesehen: now };
    neuB++;
  }
}
fs.writeFileSync(path.join(dir, "bilanz_tips.json"), JSON.stringify(blog));
console.log(`Bilanz-Signale (Test): ${neuB} neu, insgesamt ${Object.keys(blog).length}`);
console.log(`Außenseiter-Signale: ${neuA} neu, insgesamt ${Object.keys(alog).length}`);
console.log(`Varianten-Protokoll: ${neuV} neue Tipps (B–F), insgesamt ${Object.keys(vlog).length}`);

// Prognose-Protokoll: für JEDE Partie (nicht nur Tipps) die Einzelteile des Modells vor Spielbeginn einfrieren.
// Grundlage, um später Gewichte (Elo vs. Statistik je Belag, H2H, Kalibrierung, Markt-Anteil) aus echten
// Ergebnissen zu schätzen – ohne Rückschau-Verzerrung. Ergebnisse kommen aus ergebnisse.json.
// Merkmale je Partie für die Jahresend-Suche nach Mustern (was wir noch nicht gezielt tracken):
// Halle/draußen, Runde, Quali, Uhrzeit, Länder (Heimspiel), Form/Belastung, Warnhinweise, Signale. Wird bis Spielbeginn aktualisiert.
const r0 = (m) => { const q = Object.values(m.quoten || {})[0] || []; return M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa: q[0], qb: q[1] }, D); };
function merkmale(m, r, qs) {
  const fo = (f) => f ? { sp: f.spiele7 || 0, s: f.siege7 || 0, saetze: f.saetze7 || 0, games: f.games7 || 0, min: f.min7 || null,
    letztes: f.letztes || null, lMin: f.letztesMin || null, lGames: f.letztesGames || null, quali: !!f.quali } : null;
  const qa = qs && qs.length ? qs[0][0] : null, qb = qs && qs.length ? qs[0][1] : null;
  const std = m.start ? parseInt(new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone: "Europe/Berlin" }).format(new Date(m.start)), 10) : null;
  return {
    gt: m.gt || null, halle: m.gt ? /indoor/i.test(m.gt) : null, tempo: r && r.ok ? (r.tempo ?? null) : null, runde: m.runde || null, quali: !!m.quali, stunde: std,
    landA: m.landA || null, landB: m.landB || null, formA: fo(m.form && m.form.a), formB: fo(m.form && m.form.b),
    warnA: r && r.ok && qa ? warnTypen(m, r, "A", qa, qb) : [], warnB: r && r.ok && qa ? warnTypen(m, r, "B", qa, qb) : [],
    aussenseiter: !!(r && r.aussenseiter), bilanzSignal: r && r.bilanzSignal ? r.bilanzSignal.seite : null,
    favCheck: r && r.favCheck ? { name: r.favCheck.name, pct: r3(r.favCheck.pct), n: r.favCheck.n } : null,
    ausCheck: r && r.ausCheck ? { name: r.ausCheck.name, pct: r3(r.ausCheck.pct), n: r.ausCheck.n } : null,
    h2h: r && r.h2h ? [r.h2h.a, r.h2h.b] : null, nurElo: !!(r && r.nurElo), geschaetzt: !!(r && (r.eloGeschaetztA || r.eloGeschaetztB)) };
}
const prog = rd("prognosen.json", {});
let neuProg = 0;
for (const m of matches) {
  if (!m.start || new Date(m.start) <= new Date()) continue;
  const qs = Object.values(m.quoten || {}).filter((q) => q[0] > 1 && q[1] > 1);
  if (prog[m.id]) {
    // Prognose bleibt eingefroren, die Quoten werden bis Spielbeginn aktualisiert (letzte Quote vor Start).
    // So fehlen keine Quoten mehr, wenn die Partie schon vor dem Quotenstart des Buchmachers erfasst wurde.
    if (qs.length) {
      const e = prog[m.id];
      e.qa = Math.max(...qs.map((q) => q[0])); e.qb = Math.max(...qs.map((q) => q[1]));
      e.qaM = r3(qs.reduce((x, q) => x + q[0], 0) / qs.length); e.qbM = r3(qs.reduce((x, q) => x + q[1], 0) / qs.length);
      e.pMarkt = r3(qs.reduce((s, q) => s + (1 / q[0]) / (1 / q[0] + 1 / q[1]), 0) / qs.length);
      e.quoteStand = now;
      if (!e.qaErst) { e.qaErst = e.qaM; e.qbErst = e.qbM; e.quoteErstZeit = now; }   // Eröffnungsquote (erste gesehene)
      const rNow = r0(m);
      e.merkmale = merkmale(m, rNow, qs);
      if (e.pD == null && rNow.ok && rNow.varianten && rNow.varianten.D) e.pD = r3(rNow.varianten.D.p);   // Variante D (ab 27.10.) nachtragen
      if (e.pE == null && rNow.ok && rNow.varianten && rNow.varianten.E) e.pE = r3(rNow.varianten.E.p);   // Variante E = alte Gewichte
      if (e.pF == null && rNow.ok && rNow.varianten && rNow.varianten.F) e.pF = r3(rNow.varianten.F.p);   // Variante F = Tempo-Gewicht Hart
    }
    continue;
  }
  const qa = qs.length ? Math.max(...qs.map((q) => q[0])) : undefined;   // beste Quote je Seite
  const qb = qs.length ? Math.max(...qs.map((q) => q[1])) : undefined;
  const r = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
  if (!r.ok) continue;
  const pmMittel = qs.length ? qs.reduce((s, q) => s + (1 / q[0]) / (1 / q[0] + 1 / q[1]), 0) / qs.length : null;
  prog[m.id] = { start: m.start, turnier: m.turnier, kategorie: m.kategorie, belag: r.belag, a: m.a, b: m.b,
    pStats: r3(r.pStats), pElo: r3(r.pElo), eloA: r3(r.eloA), eloB: r3(r.eloB), pSrvA: r3(r.pSrvA), pSrvB: r3(r.pSrvB),
    h2hA: r.h2h.a, h2hB: r.h2h.b, pKombi: r3(r.pKombi), pKal: r3(r.pKal), pMarkt: r3(pmMittel), pFinal: r3(r.pFinal),
    qa: qa || null, qb: qb || null,
    qaM: qs.length ? r3(qs.reduce((x, q) => x + q[0], 0) / qs.length) : null,   // Durchschnittsquote (Spieler-Check)
    qbM: qs.length ? r3(qs.reduce((x, q) => x + q[1], 0) / qs.length) : null, nurElo: !!r.nurElo, statsDurchschnitt: !!r.statsDurchschnitt,
    geschaetzt: !!(r.eloGeschaetztA || r.eloGeschaetztB), quali: !!m.quali, modus: r.modus, csi: r.csi, gesehen: now,
    pB: r.varianten ? r3(r.varianten.B.p) : null, pC: r.varianten ? r3(r.varianten.C.p) : null, pD: r.varianten && r.varianten.D ? r3(r.varianten.D.p) : null, pE: r.varianten && r.varianten.E ? r3(r.varianten.E.p) : null, pF: r.varianten && r.varianten.F ? r3(r.varianten.F.p) : null,
    pStatsC: r.varianten ? r3(r.varianten.C.pStats) : null,
    qaErst: qs.length ? r3(qs.reduce((x, q) => x + q[0], 0) / qs.length) : null, qbErst: qs.length ? r3(qs.reduce((x, q) => x + q[1], 0) / qs.length) : null,
    quoteErstZeit: qs.length ? now : null, merkmale: merkmale(m, r, qs) };
  neuProg++;
}
const grenzeProg = new Date(Date.now() - 180 * 864e5).toISOString();
for (const k of Object.keys(prog)) if (String(prog[k].start) < grenzeProg) delete prog[k];
fs.writeFileSync(path.join(dir, "prognosen.json"), JSON.stringify(prog));
console.log(`Prognose-Protokoll: ${neuProg} neue Partien, insgesamt ${Object.keys(prog).length}`);
console.log(`Tipp-Protokoll: ${neu} neue Value-Signale, insgesamt ${Object.keys(log).length}`);
