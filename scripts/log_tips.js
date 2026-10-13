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
const now = new Date().toISOString().slice(0, 16) + "Z";
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
      kelly: r.kelly, erstGesehen: now };
    if (!log[key]) neu++;
    e.start = m.start;  // Ansetzung kann sich verschieben
    Object.assign(e, { letzteQuote: q, letzteP: r.pFinal, zuletztGesehen: now });
    log[key] = e;
  }
}
fs.writeFileSync(path.join(dir, "tips_log.json"), JSON.stringify(log, null, 0));

// Prognose-Protokoll: für JEDE Partie (nicht nur Tipps) die Einzelteile des Modells vor Spielbeginn einfrieren.
// Grundlage, um später Gewichte (Elo vs. Statistik je Belag, H2H, Kalibrierung, Markt-Anteil) aus echten
// Ergebnissen zu schätzen – ohne Rückschau-Verzerrung. Ergebnisse kommen aus ergebnisse.json.
const prog = rd("prognosen.json", {});
let neuProg = 0;
const r3 = (x) => (typeof x === "number" && isFinite(x) ? Math.round(x * 1000) / 1000 : null);
for (const m of matches) {
  if (!m.start || new Date(m.start) <= new Date() || prog[m.id]) continue;
  const qs = Object.values(m.quoten || {}).filter((q) => q[0] > 1 && q[1] > 1);
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
    geschaetzt: !!(r.eloGeschaetztA || r.eloGeschaetztB), modus: r.modus, csi: r.csi, gesehen: now };
  neuProg++;
}
const grenzeProg = new Date(Date.now() - 180 * 864e5).toISOString();
for (const k of Object.keys(prog)) if (String(prog[k].start) < grenzeProg) delete prog[k];
fs.writeFileSync(path.join(dir, "prognosen.json"), JSON.stringify(prog));
console.log(`Prognose-Protokoll: ${neuProg} neue Partien, insgesamt ${Object.keys(prog).length}`);
console.log(`Tipp-Protokoll: ${neu} neue Value-Signale, insgesamt ${Object.keys(log).length}`);
