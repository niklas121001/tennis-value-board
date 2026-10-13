// Vergleicht den JS-Nachbau mit den in der Excel gespeicherten DASHBOARD-Werten.
const fs = require("fs"), path = require("path");
const M = require("../docs/model.js");
const d = (f) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "docs", "data", f), "utf8"));
// Parameter eingefroren auf Excel-Stand (docs/data/params.json darf live geändert werden, z. B. W_MODELL_BLEND)
const P = JSON.parse(fs.readFileSync(path.join(__dirname, "params_excel.json"), "utf8"));
// Spieler-DB eingefroren auf Excel-Stand (docs/data/players.json wird täglich mit neuen Elo-Werten überschrieben)
const players = JSON.parse(fs.readFileSync(path.join(__dirname, "players_excel.json"), "utf8"));
const D = { params: P.params, csi: P.csi, players, h2h: d("h2h.json"), playerStats: d("player_stats.json"), blacklist: d("blacklist.json") };
const rows = JSON.parse(fs.readFileSync(path.join(__dirname, "excel_dashboard.json"), "utf8"));
let worst = 0, fails = 0;
for (const r of rows) {
  const res = M.analyse({ turnier: r.turnier, belag: r.belag, a: r.a, b: r.b, qa: r.qa, qb: r.qb,
    spieleA: typeof r.spieleA === "number" ? r.spieleA : undefined, spieleB: typeof r.spieleB === "number" ? r.spieleB : undefined,
    modus: r.modus }, D);
  if (!res.ok) { console.log("NICHT BERECHNET", r.a, r.b, res.warnungen); fails++; continue; }
  const checks = [["eloA", res.eloA, r.eloA], ["pSrvA", res.pSrvA, r.pSrvA], ["pStats", res.pStats, r.pStats], ["pElo", res.pElo, r.pElo], ["pFinal", res.pFinal, r.pFinal], ["fairA", res.fairA, r.fairA], ["kelly", res.kelly || 0, r.kelly || 0]];
  for (const [k, a, e] of checks) {
    const diff = Math.abs(a - e);
    worst = Math.max(worst, k === "kelly" || k === "eloA" ? 0 : diff);
    if (diff > (k === "kelly" ? 0.011 : 1e-6)) { console.log("ABWEICHUNG", r.a, "vs", r.b, k, a, e); fails++; }
  }
  const empfE = String(r.empf), empfJ = res.empfehlung;
  if (empfE !== empfJ) { console.log("EMPFEHLUNG", r.a, r.b, JSON.stringify(empfE), JSON.stringify(empfJ)); fails++; }
  if (r.top && r.top !== res.saetze.top) { console.log("SATZ", r.a, r.b, r.top, res.saetze.top); fails++; }
}
console.log(`${rows.length} Partien geprüft, ${fails} Abweichungen, größte Wahrscheinlichkeitsdifferenz ${worst.toExponential(2)}`);
process.exit(fails ? 1 : 0);
