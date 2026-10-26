// Rechnet alle Partien aus matches.json mit dem Modell durch und protokolliert Value-Signale
// in docs/data/tips_log.json (erste + letzte gesehene Quote je Buchmacher -> Basis für CLV).
const fs = require("fs"), path = require("path");
const M = require("../docs/model.js");
const dir = path.join(__dirname, "..", "docs", "data");
const rd = (f, d) => (fs.existsSync(path.join(dir, f)) ? JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")) : d);

const P = rd("params.json");
const D = { params: P.params, csi: P.csi, players: rd("players.json"), h2h: rd("h2h.json"), playerStats: rd("player_stats.json"), blacklist: rd("blacklist.json", []), statsAvg: rd("stats_avg.json", null), h2hWeb: (rd("h2h_web.json", {}) || {}).paare || {}, h2hApi: (rd("h2h_api.json", {}) || {}).paare || {},
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
console.log(`Varianten-Protokoll: ${neuV} neue Tipps (B/C), insgesamt ${Object.keys(vlog).length}`);

// Prognose-Protokoll: für JEDE Partie (nicht nur Tipps) die Einzelteile des Modells vor Spielbeginn einfrieren.
// Grundlage, um später Gewichte (Elo vs. Statistik je Belag, H2H, Kalibrierung, Markt-Anteil) aus echten
// Ergebnissen zu schätzen – ohne Rückschau-Verzerrung. Ergebnisse kommen aus ergebnisse.json.
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
    pB: r.varianten ? r3(r.varianten.B.p) : null, pC: r.varianten ? r3(r.varianten.C.p) : null,
    pStatsC: r.varianten ? r3(r.varianten.C.pStats) : null };
  neuProg++;
}
const grenzeProg = new Date(Date.now() - 180 * 864e5).toISOString();
for (const k of Object.keys(prog)) if (String(prog[k].start) < grenzeProg) delete prog[k];
fs.writeFileSync(path.join(dir, "prognosen.json"), JSON.stringify(prog));
console.log(`Prognose-Protokoll: ${neuProg} neue Partien, insgesamt ${Object.keys(prog).length}`);
console.log(`Tipp-Protokoll: ${neu} neue Value-Signale, insgesamt ${Object.keys(log).length}`);
