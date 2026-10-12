// Rechnet alle Partien aus matches.json mit dem Modell durch und protokolliert Value-Signale
// in docs/data/tips_log.json (erste + letzte gesehene Quote je Buchmacher -> Basis für CLV).
const fs = require("fs"), path = require("path");
const M = require("../docs/model.js");
const dir = path.join(__dirname, "..", "docs", "data");
const rd = (f, d) => (fs.existsSync(path.join(dir, f)) ? JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")) : d);

const P = rd("params.json");
const D = { params: P.params, csi: P.csi, players: rd("players.json"), h2h: rd("h2h.json"), playerStats: rd("player_stats.json"), blacklist: rd("blacklist.json", []) };
const mj = rd("matches.json", { partien: [] });
if (mj.demo) { console.log("Demo-Daten – nichts protokolliert"); process.exit(0); }
const matches = mj.partien;
const log = rd("tips_log.json", {});
const now = new Date().toISOString().slice(0, 16) + "Z";
let neu = 0;

for (const m of matches) {
  for (const [bm, [qa, qb]] of Object.entries(m.quoten || {})) {
    const r = M.analyse({ turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, qa, qb }, D);
    if (!r.ok || !r.wette) continue;
    const key = `${m.id}|${bm}`;
    const q = r.wette === "A" ? qa : qb;
    const e = log[key] || { id: m.id, start: m.start, turnier: m.turnier, belag: m.belag, a: m.a, b: m.b, buchmacher: bm, wette: r.wette, erstQuote: q, erstP: r.pFinal, erstGesehen: now };
    if (!log[key]) neu++;
    Object.assign(e, { letzteQuote: q, letzteP: r.pFinal, edge: r.wette === "A" ? r.edgeA : r.edgeB, kelly: r.kelly, zuletztGesehen: now });
    log[key] = e;
  }
}
fs.writeFileSync(path.join(dir, "tips_log.json"), JSON.stringify(log, null, 0));
console.log(`Tipp-Protokoll: ${neu} neue Value-Signale, insgesamt ${Object.keys(log).length}`);
