/*
 * Tennis-Prognose-Modell – 1:1-Nachbau des Excel-Blatts MODELL (Analysetool_Belag.xlsx).
 * Läuft im Browser (window.TennisModel) und in Node (module.exports).
 *
 * Eingabe pro Partie: { turnier, belag, a, b, qa, qb, spieleA?, spieleB?, modus? }
 * Stammdaten: { params, csi, players, h2h, h2hWeb, h2hApi, playerStats, playerStatsWeb, serveLive, blacklist }
 */
(function (root) {
  "use strict";

  const isNum = (x) => typeof x === "number" && isFinite(x);
  const clip = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
  const logit = (p) => Math.log(p / (1 - p));
  const sigm = (z) => 1 / (1 + Math.exp(-z));

  function surfKey(belag) {
    const b = String(belag || "hard").toLowerCase();
    return b === "clay" || b === "grass" || b === "hard" ? b : "other";
  }

  // ---------- Hilfsfunktionen aus dem MODELL-Blatt ----------

  // T3/U3: Wahrscheinlichkeit, ein Aufschlagspiel zu gewinnen
  function pGame(p) {
    const q = 1 - p;
    return p ** 4 + 4 * p ** 4 * q + 10 * p ** 4 * q ** 2 + 20 * p ** 3 * q ** 3 * (p ** 2 / (p ** 2 + q ** 2));
  }

  // V3: Satzgewinn mit Tiebreak-Mischung
  function pSet(gA, gB, tbA, tbB, wTB) {
    const g = (gA + 1 - gB) / 2;
    const h = 1 - g;
    const tbModel = g ** 2 / (g ** 2 + h ** 2);
    const tb = wTB * (tbA / (tbA + tbB)) + (1 - wTB) * tbModel;
    return (
      g ** 6 + 6 * g ** 6 * h + 21 * g ** 6 * h ** 2 + 56 * g ** 6 * h ** 3 + 126 * g ** 6 * h ** 4 +
      252 * g ** 5 * h ** 5 * (g ** 2 + 2 * g * h * tb)
    );
  }

  // X3: Matchgewinn aus Satzgewinn
  function pMatch(s, mode) {
    const t = 1 - s;
    return mode === 5 ? s ** 3 + 3 * s ** 3 * t + 6 * s ** 3 * t ** 2 : s ** 2 + 2 * s ** 2 * t;
  }

  // AN3: Bo3 / Bo5
  function detectMode(turnier, override, P) {
    if (override === 3 || override === 5) return override;
    const t = String(turnier || "");
    if (!t) return P.MODUS_SAETZE;
    const tl = t.toLowerCase();
    if (tl.includes("quali") || t.trim().endsWith(" Q")) return 3;
    if (["australian open", "french open", "roland", "wimbledon", "us open"].some((s) => tl.includes(s))) return 5;
    return P.MODUS_SAETZE;
  }

  // Platztempo Hart/Rasen (ATP-Turniere, Tennis Abstract Surface Speed: 1,00 = Tour-Schnitt). Nur ATP, Challenger ohne Wert.
  // Challenger: eigene Schätzung aus Match-Statistiken (tempo_eigen.json, Zeilen mit ch: true)
  function lookupTempo(turnier, belag, tabelle) {
    const t = String(turnier || "").toLowerCase(), sk = surfKey(belag), ch = /challenger/.test(t);
    if (!tabelle || !sk) return null;
    for (const row of tabelle) {
      if (row.belag !== sk || !!row.ch !== ch) continue;
      for (const n of [row.name, ...(row.alias || [])]) if (n && t.includes(String(n).toLowerCase())) return row.speed;
    }
    return null;
  }
  // Tempo-Stufe je Belag (gleiche Grenzen wie scripts/h2h_ta.py)
  function tempoStufe(belag, sp) {
    const [lo, hi] = { hard: [0.95, 1.15], clay: [0.65, 0.85], grass: [1.05, 1.25] }[belag] || [0.95, 1.15];
    return sp < lo ? "langsam" : sp >= hi ? "schnell" : "mittel";
  }
  // DASHBOARD AJ: Court Speed Index (nur Sand)
  function lookupCSI(turnier, belag, csiTable) {
    if (surfKey(belag) !== "clay") return null;
    const t = String(turnier || "").toLowerCase();
    for (const row of csiTable) if (row.name && t.includes(row.name.toLowerCase())) return row.csi;
    for (const row of csiTable) if (row.alias && t.includes(row.alias.toLowerCase())) return row.csi;
    return null;
  }

  function weights(sk, csi, P) {
    if (sk === "clay") {
      if (!csi) return [P.W_STATS_CLAY, P.W_ELO_CLAY];
      return [
        P.W_STATS_CLAY_SLOW + (P.W_STATS_CLAY_FAST - P.W_STATS_CLAY_SLOW) * csi / 10,
        P.W_ELO_CLAY_SLOW + (P.W_ELO_CLAY_FAST - P.W_ELO_CLAY_SLOW) * csi / 10,
      ];
    }
    if (sk === "grass") return [P.W_STATS_GRASS, P.W_ELO_GRASS];
    if (sk === "hard") return [P.W_STATS_HARD, P.W_ELO_HARD];
    return [P.W_STATS, P.W_ELO];
  }

  function h2hEinzeln(a, b, h2h) {
    if (!h2h) return [0, 0];
    if (h2h[a + "|" + b]) return h2h[a + "|" + b];
    if (h2h[b + "|" + a]) { const r = h2h[b + "|" + a]; return [r[1], r[0]]; }
    return [0, 0];
  }
  // Excel-Bilanz (h2h.json) + von der Website nach dem Excel-Stichtag erfasste Spiele (h2h_web.json).
  // Liegt eine abgerufene Gesamtbilanz vor (h2h_api.json, SportsAPIPro), gilt sie – außer Excel+Web kennt mehr Duelle
  // (z. B. ein neues Duell nach dem Abruf). Rückgabe: [Siege A, Siege B, Quelle]
  function h2hLookup(a, b, h2h, web, api) {
    const x = h2hEinzeln(a, b, h2h), y = h2hEinzeln(a, b, web);
    const eigen = [x[0] + y[0], x[1] + y[1]];
    const hatApi = api && (api[a + "|" + b] || api[b + "|" + a]);
    if (hatApi) {
      const z = h2hEinzeln(a, b, api);
      if (z[0] + z[1] >= eigen[0] + eigen[1]) return [z[0], z[1], "spieldaten"];
    }
    return [eigen[0], eigen[1], "excel"];
  }

  // ---- Spieler-Check: Excel-Bilanz (player_stats.json) + seit dem Excel-Stand fortgeschrieben (player_stats_web.json)
  const QUOTEN_BAENDER = [1.0, 1.3, 1.5, 1.7, 1.9, 2.1, 2.5, 3.0, 4.0];   // wie scripts/common.py
  function quotenBand(q) {
    if (!isNum(q) || q <= 1) return null;
    for (let i = 0; i < QUOTEN_BAENDER.length; i++) {
      const lo = QUOTEN_BAENDER[i], hi = QUOTEN_BAENDER[i + 1];
      if (hi === undefined) return lo.toFixed(2) + "+";
      if (q >= lo && q < hi) return lo.toFixed(2) + "-" + hi.toFixed(2);
    }
    return null;
  }
  function spielerRolle(name, rolle, D) {
    const x = (D.playerStats || {})[name], w = (D.playerStatsWeb || {})[name];
    const nX = x ? x[rolle + "_n"] || 0 : 0, pX = x ? x[rolle + "_pct"] : null;
    const sX = nX && isNum(pX) ? pX * nX : 0;
    const [sW, lW] = (w && w[rolle]) || [0, 0];
    const n = nX + sW + lW;
    return { pct: n ? (sX + sW) / n : null, n, nWeb: sW + lW };
  }
  function spielerBand(name, q, D) {
    const band = quotenBand(q);
    if (!band) return null;
    const x = (((D.playerStats || {})[name] || {}).baender || {})[band] || [0, 0];
    const w = (((D.playerStatsWeb || {})[name] || {}).baender || {})[band] || [0, 0];
    const s = x[0] + w[0], n = s + x[1] + w[1];
    return { name, band, quote: q, siege: s, n, pct: n ? s / n : null };
  }

  // Tourschnitt Aufschlag-/Returnpunkte je Belag über alle Spieler mit Werten (einmal je Datensatz berechnet)
  function tourSchnitt(D, s) {
    D._tour = D._tour || {};
    if (D._tour[s]) return D._tour[s];
    let n = 0, srv = 0, ret = 0;
    for (const p of Object.values(D.players || {})) {
      const a = p[s + "_1in"], b = p[s + "_1won"], c = p[s + "_2won"], r = p["ret_" + s];
      if ([a, b, c, r].every(isNum) && a > 0) { srv += a * b + (1 - a) * c; ret += r; n++; }
    }
    return (D._tour[s] = n ? { srv: srv / n, ret: ret / n, n } : { srv: 0.62, ret: 0.38, n: 0 });
  }
  // Value-Regel wie im Hauptmodell (Quote über fair, höchstens MAX_QUOTE_VALUE, nur Modell-Favorit) + Kelly
  function bewerte(p, match, haveOdds, D, P) {
    const fairA = 1 / p, fairB = 1 / (1 - p);
    const r = { p, fairA, fairB, wette: null, edge: null, kelly: null };
    if (!haveOdds) return r;
    const vA = match.qa > fairA && match.qa <= P.MAX_QUOTE_VALUE && fairA < fairB;
    const vB = match.qb > fairB && match.qb <= P.MAX_QUOTE_VALUE && fairB < fairA;
    const fav = fairA < fairB ? match.a : match.b;
    if ((vA || vB) && !(D.blacklist || []).includes(fav)) {
      r.wette = vA ? "A" : "B";
      const q = vA ? match.qa : match.qb, f = vA ? fairA : fairB;
      r.edge = q / f - 1;
      r.kelly = Math.round(P.BANKROLL * P.KELLY_FRACTION * Math.max(0, (1 / f - 1 / q) / (1 - 1 / q)) * 100) / 100;
    }
    return r;
  }

  // Satzergebnis-Prognose (BY3..CM3): q so bestimmen, dass P(Match) = P(A) final
  // Turnier-Satzstatistik (turnier_stats.json, ATP-Ebene) zum Turniernamen im Spielplan finden
  function lookupTurnierStats(turnier, stats) {
    const t = String(turnier || "").toLowerCase();
    if (!stats || /challenger/.test(t)) return null;
    let best = null, bl = 0;
    for (const x of Object.values(stats)) for (const n of [x.name, ...(x.alias || [])]) {
      const nn = String(n || "").toLowerCase();
      if (nn.length > bl && nn.length >= 4 && t.includes(nn)) { best = x; bl = nn.length; }
    }
    return best;
  }
  // k > 1: mehr glatte Siege als bei unabhängigen Sätzen (Sätze hängen zusammen – Form, Momentum). Siegchance bleibt gleich,
  // nur die Verteilung 2:0 ↔ 2:1 (bzw. 3:0 ↔ 3:1/3:2) verschiebt sich.
  function setScores(pFinal, mode, k) {
    k = isNum(k) && k > 0 ? k : 1;
    const by = clip(pFinal, 0.05, 0.95);
    const F = (q) => (mode === 5 ? 6 * q ** 5 - 15 * q ** 4 + 10 * q ** 3 : 3 * q ** 2 - 2 * q ** 3);
    const dF = (q) => Math.max(0.05, mode === 5 ? 30 * q ** 2 * (1 - q) ** 2 : 6 * q * (1 - q));
    const q0 = clip(0.5 + (by - 0.5) / (mode === 5 ? 1.875 : 1.5), 0.05, 0.95);
    const q1 = clip(q0 - (F(q0) - by) / dF(q0), 0.05, 0.95);
    const q = clip(q1 - (F(q1) - by) / dF(q1), 0.05, 0.95);
    const r = 1 - q;
    let sc;
    if (mode === 5) {
      sc = { "3-0": q ** 3, "3-1": 3 * q ** 3 * r, "3-2": 6 * q ** 3 * r ** 2, "0-3": r ** 3, "1-3": 3 * r ** 3 * q, "2-3": 6 * r ** 3 * q ** 2 };
      if (k !== 1) {
        const pa = sc["3-0"] + sc["3-1"] + sc["3-2"], pb = 1 - pa;
        const a0 = Math.min(pa * 0.98, sc["3-0"] * k), b0 = Math.min(pb * 0.98, sc["0-3"] * k);
        const ra = sc["3-1"] + sc["3-2"], rb = sc["1-3"] + sc["2-3"];
        sc = { "3-0": a0, "3-1": (pa - a0) * sc["3-1"] / ra, "3-2": (pa - a0) * sc["3-2"] / ra,
               "0-3": b0, "1-3": (pb - b0) * sc["1-3"] / rb, "2-3": (pb - b0) * sc["2-3"] / rb };
      }
    } else {
      sc = { "2-0": q ** 2, "2-1": 2 * q ** 2 * r, "0-2": r ** 2, "1-2": 2 * r ** 2 * q };
      if (k !== 1) {
        const pa = sc["2-0"] + sc["2-1"], pb = 1 - pa;
        const a0 = Math.min(pa * 0.98, sc["2-0"] * k), b0 = Math.min(pb * 0.98, sc["0-2"] * k);
        sc = { "2-0": a0, "2-1": pa - a0, "0-2": b0, "1-2": pb - b0 };
      }
    }
    let top = null;
    for (const k in sc) if (top === null || sc[k] > sc[top]) top = k;
    const glattA = mode === 5 ? sc["3-0"] : sc["2-0"];
    const glattB = mode === 5 ? sc["0-3"] : sc["0-2"];
    const voll = mode === 5 ? sc["3-2"] + sc["2-3"] : sc["2-1"] + sc["1-2"];
    return { q, scores: sc, top, pTop: sc[top], fairTop: 1 / sc[top], glattA, glattB, vollDistanz: voll };
  }

  // ---------- Hauptfunktion ----------
  function analyse(match, D) {
    const P = D.params;
    const sk = surfKey(match.belag);
    // Fortgeschriebene Aufschlag-/Returnwerte (serve_live.json) über den Excel-Stand legen
    const live = (n) => {
      const p = D.players[n], l = D.serveLive && D.serveLive[n];
      return p && l ? Object.assign({}, p, l) : p;
    };
    const pa = live(match.a);
    const pb = live(match.b);
    const out = { a: match.a, b: match.b, belag: sk, warnungen: [] };
    if (!pa) out.warnungen.push(match.a + " nicht in Spieler-DB");
    if (!pb) out.warnungen.push(match.b + " nicht in Spieler-DB");
    if (!pa || !pb) return out;

    // Elo (G3/K3 mit BQ..BT)
    const eloCol = sk === "clay" ? "elo_clay" : sk === "grass" ? "elo_grass" : "elo_hard";
    const belagElo = (p) => (isNum(p[eloCol]) && p[eloCol] > 0 ? p[eloCol] : p.elo);
    // yElo (Saison-Elo) startet im Januar neu und ist anfangs unsicher: Gewicht ab 1.1. über YELO_ANLAUF_TAGE (45) Tage
    // linear von 0 auf W_YELO_BLEND hochfahren (seit 04.11.2026, wirkt ab Januar 2027)
    const tagImJahr = (() => { const d = match.start ? new Date(match.start) : new Date(); return (d - new Date(Date.UTC(d.getUTCFullYear(), 0, 1))) / 864e5; })();
    const wYelo = P.W_YELO_BLEND * Math.min(1, Math.max(0, tagImJahr / (P.YELO_ANLAUF_TAGE ?? 45)));
    const mix = (p) => (P.YELO_EINBEZIEHEN === "Ja" && isNum(p.elo) ? wYelo * p.elo + (1 - wYelo) * belagElo(p) : belagElo(p));
    const eloA = mix(pa), eloB = mix(pb);

    // Aufschlagwerte nach Belag (H..N); "other" nutzt Hard-Spalten wie die Excel
    const s = sk === "clay" ? "clay" : sk === "grass" ? "grass" : "hard";
    const retKey = "ret_" + s;
    const felder = [s + "_1in", s + "_1won", s + "_2won", retKey];
    const fehlt = (p) => felder.some((k) => !isNum(p[k]));
    out.statsFehlenA = fehlt(pa); out.statsFehlenB = fehlt(pb);
    out.aufschlagQuelle = { a: pa["quelle_" + s] || (out.statsFehlenA ? null : "excel"), b: pb["quelle_" + s] || (out.statsFehlenB ? null : "excel"),
      nA: pa["n_" + s] || 0, nB: pb["n_" + s] || 0 };
    // App-Erweiterung: fehlende Werte mit dem Durchschnitt auf Challenger-Niveau (stats_avg.json) auffüllen
    const avg = D.statsAvg && D.statsAvg[s];
    const mitAvg = !!avg && P.FEHLENDE_STATS !== "excel" && P.STATS_DURCHSCHNITT !== false;
    const fuell = (p) => {
      if (!mitAvg) return p;
      const q = Object.assign({}, p);
      for (const k of felder) if (!isNum(q[k])) q[k] = avg[k.replace(s + "_", "").replace(retKey, "ret")];
      return q;
    };
    if (out.statsFehlenA) out.warnungen.push(match.a + ": Aufschlag-/Returnwerte (" + s + ") fehlen" + (mitAvg ? " – Durchschnitt verwendet" : ""));
    if (out.statsFehlenB) out.warnungen.push(match.b + ": Aufschlag-/Returnwerte (" + s + ") fehlen" + (mitAvg ? " – Durchschnitt verwendet" : ""));
    out.statsDurchschnitt = mitAvg && (out.statsFehlenA || out.statsFehlenB);
    out.eloGeschaetztA = !!pa.geschaetzt; out.eloGeschaetztB = !!pb.geschaetzt;
    for (const [p, n] of [[pa, match.a], [pb, match.b]])
      if (p.geschaetzt) out.warnungen.push(n + ": Elo geschätzt aus Marktquoten (" + (p.n_markt || 0) + " Quoten, " + (p.n_erg || 0) + " Ergebnisse" +
        ({ direkt: ", Bezug: Gegner mit echtem Elo", indirekt: ", Bezug: anderer geschätzter Spieler", basis: ", Bezug: Challenger-Mittelwert – grob" }[p.anker] || "") + ")");
    const sa = fuell(pa), sb = fuell(pb);
    // Excel: leere Zelle -> VLOOKUP liefert 0 (kein Fehler), daher 0 statt 0,348
    const retA = isNum(sa[retKey]) ? sa[retKey] : 0; // BJ3
    const retB = isNum(sb[retKey]) ? sb[retKey] : 0; // BI3
    const srv = (p, retOpp) => (p[s + "_1in"] * p[s + "_1won"] + (1 - p[s + "_1in"]) * p[s + "_2won"] + (1 - retOpp)) / 2;
    const adj = sk === "clay" ? P.SURF_CLAY : sk === "grass" ? P.SURF_GRASS : P.SURF_HARD;
    const pSrvA = clip(srv(sa, retB) + adj, P.P_SRV_MIN, P.P_SRV_MAX);
    const pSrvB = clip(srv(sb, retA) + adj, P.P_SRV_MIN, P.P_SRV_MAX);

    const mode = detectMode(match.turnier, match.modus, P);
    const tbA = isNum(pa.tb) ? pa.tb : (mitAvg && avg.tb) || 0.52, tbB = isNum(pb.tb) ? pb.tb : (mitAvg && avg.tb) || 0.52;
    const gA = pGame(pSrvA), gB = pGame(pSrvB);
    let setA = pSet(gA, gB, tbA, tbB, P.W_TB);
    if (!isFinite(setA)) setA = 0.5; // IFERROR(...;0,5)
    const pStats = pMatch(setA, mode);
    const pElo = 1 / (1 + 10 ** ((eloB - eloA) / 400));

    // H2H (AB..AF)
    const [hA, hB, hQuelle] = h2hLookup(match.a, match.b, D.h2h, D.h2hWeb, D.h2hApi);
    const hN = hA + hB;
    const h2hPct = hN >= P.H2H_MIN_MATCHES ? hA / hN : 0.5;
    const h2hW = hN < P.H2H_MIN_MATCHES ? 0 : Math.min(P.H2H_MAX_WEIGHT, (hN / 10) * P.H2H_MAX_WEIGHT);

    // Belag-Erfahrung (BO3) – optional, Spiele der letzten 12 Monate
    const ref = P.SURF_EXP_REF;
    const spA = isNum(match.spieleA) ? match.spieleA : null, spB = isNum(match.spieleB) ? match.spieleB : null;
    const erf = spA === null && spB === null ? 0 :
      (Math.min(spA === null ? ref : spA, ref) / ref - Math.min(spB === null ? ref : spB, ref) / ref) * P.W_SURF_EXP;

    // Kombination (AG3)
    // Sand-Tempo: bevorzugt Tennis Abstract (Ass-Quote, Mehrjahresmittel), auf die CSI-Skala 0–10 umgerechnet;
    // sonst der CSI aus der Excel
    let csi = lookupCSI(match.turnier, match.belag, D.csi || []);
    if (sk === "clay" && P.CSI_AUS_TEMPO !== false) {
      const spC = lookupTempo(match.turnier, match.belag, D.tempo);
      const lo = P.CSI_TEMPO_LANGSAM ?? 0.5, hi = P.CSI_TEMPO_SCHNELL ?? 1.0;
      if (isNum(spC)) csi = Math.round(clip((spC - lo) / (hi - lo), 0, 1) * 100) / 10;
    }
    let [wS, wE] = weights(sk, csi, P);
    // App-Erweiterung: fehlen Aufschlagwerte, Statistik-Teil abschalten (Excel rechnet mit 0)
    out.nurElo = P.FEHLENDE_STATS !== "excel" && !mitAvg && (out.statsFehlenA || out.statsFehlenB);
    if (out.nurElo) wS = 0;
    const pKombi = clip((wS * pStats + wE * pElo + h2hW * h2hPct) / (wS + wE + h2hW) + erf, 0.05, 0.95);

    // Kalibrierung + Markt-Blend (BU..BW)
    const pKal = sigm(P.K_KALIBRIERUNG * logit(clip(pKombi, 0.02, 0.98)));
    const haveOdds = isNum(match.qa) && isNum(match.qb) && match.qa > 1 && match.qb > 1;
    const pMarkt = haveOdds ? (1 / match.qa) / (1 / match.qa + 1 / match.qb) : null;
    const pFinal = pMarkt === null ? pKal : sigm(P.W_MODELL_BLEND * logit(pKal) + (1 - P.W_MODELL_BLEND) * logit(pMarkt));

    const fairA = 1 / pFinal, fairB = 1 / (1 - pFinal);
    const edgeA = haveOdds ? match.qa / fairA - 1 : null;
    const edgeB = haveOdds ? match.qb / fairB - 1 : null;
    const valueA = haveOdds && match.qa > fairA && match.qa <= P.MAX_QUOTE_VALUE;
    const valueB = haveOdds && match.qb > fairB && match.qb <= P.MAX_QUOTE_VALUE;

    // Empfehlung (DASHBOARD X): nur auf den Modell-Favoriten
    const modellFav = fairA < fairB ? match.a : fairB < fairA ? match.b : null;
    let empfehlung = "Kein Value", wette = null;
    if ((D.blacklist || []).includes(modellFav)) {
      empfehlung = "⛔ BLACKLIST – nicht anspielen";
    } else if (valueA && valueB) {
      if (fairA < fairB) wette = "A"; else if (fairB < fairA) wette = "B"; else empfehlung = "⚠️ Beide Value!";
    } else if (valueA && fairA < fairB) wette = "A";
    else if (valueB && fairB < fairA) wette = "B";
    if (wette) empfehlung = "👉 Auf " + (wette === "A" ? match.a : match.b) + " setzen";
    // Seit 29.10.2026: keine Value-Tipps, wenn ein Spieler nur eine geschätzte Elo hat (Modell dort nachweislich schwach)
    const eloGeschaetzt = (out.eloGeschaetztA || out.eloGeschaetztB) && P.TIPP_BEI_GESCHAETZT !== true;
    if (wette && eloGeschaetzt) {
      empfehlung = "Kein Tipp – Elo geschätzt (" + [out.eloGeschaetztA && match.a, out.eloGeschaetztB && match.b].filter(Boolean).join(", ") + ")";
      wette = null;
    }

    // Kelly (AG..AI) – nur wenn Value auf Modell-Favorit (unabhängig von Blacklist, wie in der Excel)
    let kelly = null, buchQ = null;
    if ((valueA && fairA < fairB) || (valueB && fairB < fairA)) {
      buchQ = valueA && fairA < fairB ? match.qa : match.qb;
      const fair = Math.min(fairA, fairB);
      kelly = Math.round(P.BANKROLL * P.KELLY_FRACTION * Math.max(0, (1 / fair - 1 / buchQ) / (1 - 1 / buchQ)) * 100) / 100;
    }

    // Spieler-Check (AC..AF): Buch-Favorit / -Außenseiter
    let favCheck = null, ausCheck = null;
    if (haveOdds && D.playerStats) {
      const fav = match.qa < match.qb ? match.a : match.b;
      const aus = match.qa < match.qb ? match.b : match.a;
      favCheck = Object.assign({ name: fav }, spielerRolle(fav, "fav", D));
      ausCheck = Object.assign({ name: aus }, spielerRolle(aus, "aus", D));
    }
    // Außenseiter-Signal: Markt-Favorit gewinnt als Favorit selten (< 65 %), Außenseiter als Außenseiter oft (> 40 %),
    // und das Modell sieht den Außenseiter stärker als der Markt. Wird separat getrackt (aussenseiter_tips.json).
    let aussenseiter = null;
    if (favCheck && ausCheck && match.qa !== match.qb) {
      const minN = P.AUSSENSEITER_MIN_N || 7, favMax = P.AUSSENSEITER_FAV_MAX || 0.65, ausMin = P.AUSSENSEITER_AUS_MIN || 0.4;
      const ausSeite = match.qa > match.qb ? "A" : "B";
      const pModellAus = ausSeite === "A" ? pFinal : 1 - pFinal, pMarktAus = ausSeite === "A" ? pMarkt : 1 - pMarkt;
      if (favCheck.n >= minN && favCheck.pct != null && favCheck.pct < favMax &&
          ausCheck.n >= minN && ausCheck.pct != null && ausCheck.pct > ausMin && pModellAus > pMarktAus) {
        aussenseiter = { seite: ausSeite, name: ausCheck.name, gegen: favCheck.name, quote: ausSeite === "A" ? match.qa : match.qb,
          favPct: favCheck.pct, favN: favCheck.n, ausPct: ausCheck.pct, ausN: ausCheck.n,
          pModell: pModellAus, pMarkt: pMarktAus, fair: 1 / pModellAus };
      }
    }
    // Quotenbereich: wie oft hat der Spieler bei einer Quote in diesem Bereich gewonnen?
    const baender = haveOdds ? { a: spielerBand(match.a, match.qa, D), b: spielerBand(match.b, match.qb, D) } : null;
    // Bilanz-Signal (Test): Siegquote des Spielers im Quotenbereich, zum Markt hin gezogen (je kleiner n, desto stärker).
    // Nur für Seiten ohne Value-Tipp; kleiner Einsatz (Kelly-Anteil BILANZ_KELLY, max. 1 U). Separat getrackt (bilanz_tips.json).
    let bilanzSignal = null;
    if (baender && pMarkt !== null) {
      const minN = P.BILANZ_MIN_N || 8, K = P.BILANZ_K || 15, minEdge = P.BILANZ_MIN_EDGE || 0.03, maxQ = P.BILANZ_MAX_QUOTE || 4;
      for (const seite of ["A", "B"]) {
        const bd = seite === "A" ? baender.a : baender.b, q = seite === "A" ? match.qa : match.qb;
        if (!bd || bd.n < minN || seite === wette || !(q > 1) || q > maxQ) continue;
        const pm = seite === "A" ? pMarkt : 1 - pMarkt;
        const pEst = (bd.siege + K * pm) / (bd.n + K), edge = pEst * q - 1;
        if (edge < minEdge || (bilanzSignal && bilanzSignal.edge >= edge)) continue;
        const f = Math.max(0, edge / (q - 1)) * (P.BILANZ_KELLY || 0.25);
        bilanzSignal = { seite, name: seite === "A" ? match.a : match.b, gegen: seite === "A" ? match.b : match.a, quote: q,
          band: bd.band, siege: bd.siege, n: bd.n, pBand: bd.pct, pEst, pMarkt: pm, edge, fair: 1 / pEst,
          kellyEur: Math.round(P.BANKROLL * f * 100) / 100 };
      }
    }

    // ---- Test-Varianten (laufen im Hintergrund mit, Auswertung zum Jahresende) ----
    // B: Elo gedämpft (Faktor 0,8), Statistik-Teil nur mit echten Spielerwerten, keine Zusatz-Kalibrierung
    // C: wie B, aber Statistik-Teil gegnerbereinigt (Aufschlag A und Return B jeweils relativ zum Tourschnitt)
    const VARIANTE_BLEND = P.W_MODELL_BLEND, ELO_DAEMPFUNG = 0.8;   // gleicher Modellanteil wie das Hauptmodell
    const pEloD = sigm(ELO_DAEMPFUNG * logit(clip(pElo, 1e-4, 1 - 1e-4)));
    const echteStats = !out.statsFehlenA && !out.statsFehlenB;
    const kombi = (pS, mitStats) => {
      const ws = mitStats ? wS : 0;
      return clip((ws * pS + wE * pEloD + h2hW * h2hPct) / (ws + wE + h2hW) + erf, 0.03, 0.97);
    };
    const mitMarkt = (p) => (pMarkt === null ? p : sigm(VARIANTE_BLEND * logit(p) + (1 - VARIANTE_BLEND) * logit(pMarkt)));
    let pStatsC = null;
    if (echteStats) {
      const t = tourSchnitt(D, s);
      const sv = (p) => p[s + "_1in"] * p[s + "_1won"] + (1 - p[s + "_1in"]) * p[s + "_2won"];
      const qA = clip(t.srv + (sv(pa) - t.srv) - (pb[retKey] - t.ret), P.P_SRV_MIN, P.P_SRV_MAX);
      const qB = clip(t.srv + (sv(pb) - t.srv) - (pa[retKey] - t.ret), P.P_SRV_MIN, P.P_SRV_MAX);
      let sC = pSet(pGame(qA), pGame(qB), tbA, tbB, P.W_TB);
      if (!isFinite(sC)) sC = 0.5;
      pStatsC = pMatch(sC, mode);
    }
    // D (seit 27.10.2026): wie A, aber Statistik-Gewicht je Belag neu – Hard weniger (Statistik-Teil traf dort ~50 %),
    // Sand mehr (dort stärkster Teil). Rasen unverändert. Kalibrierung und Markt-Blend wie A.
    let pD = null;
    {
      const wsH = isNum(P.D_W_STATS_HARD) ? P.D_W_STATS_HARD : 0.15, wsC = isNum(P.D_W_STATS_CLAY) ? P.D_W_STATS_CLAY : 0.40;
      let [wsD, weD] = sk === "hard" ? [wsH, 1 - wsH] : sk === "clay" ? [wsC, 1 - wsC] : [wS, wE];
      if (out.nurElo) wsD = 0;
      const pKombiD = clip((wsD * pStats + weD * pElo + h2hW * h2hPct) / (wsD + weD + h2hW) + erf, 0.05, 0.95);
      const pKalD = sigm(P.K_KALIBRIERUNG * logit(clip(pKombiD, 0.02, 0.98)));
      pD = pMarkt === null ? pKalD : sigm(P.W_MODELL_BLEND * logit(pKalD) + (1 - P.W_MODELL_BLEND) * logit(pMarkt));
    }
    // E (seit 27.10.2026): bisheriges Modell A mit den alten Excel-Gewichten – damit der Vergleich bis Jahresende weiterläuft
    let pE = null;
    if (isNum(P.E_W_STATS_HARD)) {
      const PE = { W_STATS_CLAY: P.E_W_STATS_CLAY, W_ELO_CLAY: P.E_W_ELO_CLAY, W_STATS_CLAY_SLOW: P.E_W_STATS_CLAY_SLOW, W_ELO_CLAY_SLOW: P.E_W_ELO_CLAY_SLOW,
        W_STATS_CLAY_FAST: P.E_W_STATS_CLAY_FAST, W_ELO_CLAY_FAST: P.E_W_ELO_CLAY_FAST, W_STATS_GRASS: P.W_STATS_GRASS, W_ELO_GRASS: P.W_ELO_GRASS,
        W_STATS_HARD: P.E_W_STATS_HARD, W_ELO_HARD: P.E_W_ELO_HARD, W_STATS: P.W_STATS, W_ELO: P.W_ELO };
      let [wsE, weE] = weights(sk, csi, PE);
      if (out.nurElo) wsE = 0;
      const pKombiE = clip((wsE * pStats + weE * pElo + h2hW * h2hPct) / (wsE + weE + h2hW) + erf, 0.05, 0.95);
      const pKalE = sigm(P.K_KALIBRIERUNG * logit(clip(pKombiE, 0.02, 0.98)));
      pE = pMarkt === null ? pKalE : sigm(P.W_MODELL_BLEND * logit(pKalE) + (1 - P.W_MODELL_BLEND) * logit(pMarkt));
    }
    // F (seit 27.10.2026): wie A, aber auf Hart Statistik-Gewicht nach Platztempo: langsam (≤ 0,8) 25 % … sehr schnell (≥ 1,4) 10 %.
    // Ohne Tempo-Wert (Challenger, unbekannt) wie A.
    const tempoF = lookupTempo(match.turnier, match.belag, D.tempo);
    let pF = null;
    {
      let [wsF, weF] = [wS, wE];
      if (sk === "hard" && isNum(tempoF)) {
        const lo = P.F_TEMPO_LANGSAM ?? 0.8, hi = P.F_TEMPO_SCHNELL ?? 1.4, a = P.F_W_STATS_LANGSAM ?? 0.25, b = P.F_W_STATS_SCHNELL ?? 0.10;
        const t = clip((tempoF - lo) / (hi - lo), 0, 1);
        wsF = out.nurElo ? 0 : a + (b - a) * t; weF = 1 - (a + (b - a) * t);
      }
      const pKombiF = clip((wsF * pStats + weF * pElo + h2hW * h2hPct) / (wsF + weF + h2hW) + erf, 0.05, 0.95);
      const pKalF = sigm(P.K_KALIBRIERUNG * logit(clip(pKombiF, 0.02, 0.98)));
      pF = pMarkt === null ? pKalF : sigm(P.W_MODELL_BLEND * logit(pKalF) + (1 - P.W_MODELL_BLEND) * logit(pMarkt));
    }
    // G (seit 29.10.2026): Mischung aus C und F – Elo gedämpft, Statistik gegnerbereinigt (nur echte Werte), keine
    // Zusatz-Kalibrierung, dazu auf Hart das Statistik-Gewicht nach Platztempo wie F. Ohne Tempo-Wert = C.
    let pG = null;
    {
      let [wsG, weG] = [wS, wE];
      if (sk === "hard" && isNum(tempoF)) {
        const lo = P.F_TEMPO_LANGSAM ?? 0.8, hi = P.F_TEMPO_SCHNELL ?? 1.4, a = P.F_W_STATS_LANGSAM ?? 0.25, b = P.F_W_STATS_SCHNELL ?? 0.10;
        const t = clip((tempoF - lo) / (hi - lo), 0, 1);
        wsG = a + (b - a) * t; weG = 1 - wsG;
      }
      if (!echteStats || pStatsC === null) wsG = 0;
      pG = mitMarkt(clip((wsG * (pStatsC ?? 0.5) + weG * pEloD + h2hW * h2hPct) / (wsG + weG + h2hW) + erf, 0.03, 0.97));
    }
    // ---- Variante H (Test seit 02.11.2026): Gesamtschätzung aus Markt + Modell + allen Spieler-Statistiken ----
    // Basis = faire Pinnacle-Quote (sonst Buchmacher, entvigt). Jede Statistik wird zum Markt hin gezogen
    // (s + K·p) / (n + K) und als Logit-Abweichung vom Markt gezählt; die Statistik-Abweichungen werden gemittelt
    // (sie überschneiden sich stark), das Modell geht mit Gewicht H_W_MODELL ein.
    // J (Test seit 02.11.2026): dieselbe Rechnung ohne Markteinfluss – Basis = reines Modell (wie I), Statistiken zum Modell hin gezogen.
    const pinFair = Array.isArray(match.pinnacle) && match.pinnacle[0] > 1 && match.pinnacle[1] > 1 ? (1 / match.pinnacle[0]) / (1 / match.pinnacle[0] + 1 / match.pinnacle[1]) : null;
    const gesamtRechnen = (pBasis, basisName) => {
      if (pBasis === null) return null;
      const pin = basisName === "Pinnacle" ? pBasis : null;
      const K = P.H_K ?? 20, L = (x) => logit(clip(x, 0.02, 0.98)), teile = [];
      const stat = (name, label, s_, n, pRef, seite, zeig) => {      // pRef = Markt-Siegchance dieses Spielers; zeig = echte Bilanz bei relativen Werten
        if (!(n > 0)) return;
        const pEst = (s_ + K * pRef) / (n + K), d = L(pEst) - L(pRef);
        teile.push({ name, label, s: s_, n, pRef, pEst, d: seite === "A" ? d : -d, ...(zeig ? { zeig } : {}) });
      };
      const pA = pBasis, favA = match.qa <= match.qb, qA = match.qa, qB = match.qb;
      for (const [seite, nm, pS, qS, qG, istFav] of [["A", match.a, pA, qA, qB, favA], ["B", match.b, 1 - pA, qB, qA, !favA]]) {
        const r_ = spielerRolle(nm, istFav ? "fav" : "aus", D);
        if (r_.n && isNum(r_.pct)) stat(nm, istFav ? "Siegquote als Favorit" : "Siegquote als Außenseiter", r_.pct * r_.n, r_.n, pS, seite);
        const bd = spielerBand(nm, qS, D); if (bd && bd.n) stat(nm, "bei eigener Quote " + bd.band, bd.siege, bd.n, pS, seite);
        const gb = quotenBand(qG);
        if (gb) { let s_ = 0, n = 0;
          for (const src of [(D.playerStats || {})[nm], (D.playerStatsWeb || {})[nm]]) { const x = ((src && src.gbaender) || {})[istFav ? "fav" : "aus"] || {}; const v = x[gb]; if (v) { s_ += v[0]; n += v[0] + v[1]; } }
          if (n) stat(nm, "bei Gegnerquote " + gb, s_, n, pS, seite); }
        const gegner = seite === "A" ? match.b : match.a, hb = (D.hbTA || {})[nm];
        if (hb && D.haende && ((D.haende[gegner] || {}).h === "L" || (D.handTA || {})[gegner] === "L")) {
          let wl = 0, ll = 0, wr = 0, lr = 0; for (const v of Object.values(hb.m || {})) { wl += v[0]; ll += v[1]; wr += v[2]; lr += v[3]; }
          const nL = wl + ll, nR = wr + lr;
          if (nL >= 5 && nR >= 10) {               // Abweichung gegen Linkshänder relativ zur eigenen Bilanz gegen Rechtshänder
            const rel = clip(pS + (wl / nL - wr / nR), 0.03, 0.97);
            stat(nm, `gegen Linkshänder (rel. zu Rechtsh. ${Math.round(100 * wr / nR)} %)`, rel * nL, nL, pS, seite, `${wl}–${ll}`);
          }
        }
        // 1U auf Sieg: eigene Bilanz im Archiv gegenüber der Markterwartung (Summe der fairen Siegchancen)
        const ar = (D.arcStats || {})[nm];
        if (ar && ar.n >= 3) stat(nm, `Archiv vs. Markt (erwartet ${ar.ps.toFixed(1)} Siege)`, clip(pS + (ar.w - ar.ps) / ar.n, 0.03, 0.97) * ar.n, ar.n, pS, seite, `${ar.w}–${ar.n - ar.w}`);
        // Platztempo: Bilanz in der Tempo-Stufe dieses Turniers relativ zur Bilanz auf dem Belag (seit 2023, Tennis Abstract)
        const tp = (D.tempoTA || {})[nm];
        if (tp && isNum(tempoF) && tp[sk]) {
          const st_ = tempoStufe(sk, tempoF), b_ = tp[sk][st_];
          let W = 0, N = 0; for (const v of Object.values(tp[sk])) { W += v[0]; N += v[0] + v[1]; }
          const n_ = b_ ? b_[0] + b_[1] : 0;
          if (n_ >= 5 && N >= 15) stat(nm, `Platztempo ${st_} (Belag gesamt ${Math.round(100 * W / N)} %)`, clip(pS + (b_[0] / n_ - W / N), 0.03, 0.97) * n_, n_, pS, seite, `${b_[0]}–${b_[1]}`);
        }
        const tstH = lookupTurnierStats(match.turnier, D.turnierStats);
        if (tp && tstH && typeof tstH.halle === "boolean") {
          const x = tp[tstH.halle ? "halle" : "draussen"], y = tp[tstH.halle ? "draussen" : "halle"];
          const n_ = x ? x[0] + x[1] : 0, N = n_ + (y ? y[0] + y[1] : 0);
          if (n_ >= 5 && N >= 15) stat(nm, `${tstH.halle ? "Halle" : "draußen"} (gesamt ${Math.round(100 * (x[0] + (y ? y[0] : 0)) / N)} %)`, clip(pS + (x[0] / n_ - (x[0] + (y ? y[0] : 0)) / N), 0.03, 0.97) * n_, n_, pS, seite, `${x[0]}–${x[1]}`);
        }
      }
      const dStats = teile.length ? teile.reduce((a, t) => a + t.d, 0) / teile.length : 0;
      const dModell = L(pKal) - L(pBasis), wM = P.H_W_MODELL ?? 0.3, wS = P.H_W_STATS ?? 1;
      // Form/Belastung (eigener Term, nicht gemittelt): Spielzeit der letzten 7 Tage im Vergleich (je Stunde mehr
      // über 1,5 h hinaus H_BELAST Logit-Punkte Abzug, höchstens 4 h) und Zusatzabzug für ein langes Match (≥ 150 Min.) in den letzten 30 h.
      let dForm = 0; const form = [];
      if (match.form && match.form.a && match.form.b) {
        const minuten = (f) => !f.spiele7 ? 0 : (isNum(f.min7) && f.minN === f.spiele7 ? f.min7 : (f.games7 || 0) * 4.3);
        const lang = (f) => { if (!f || !f.letztes || !match.start) return false;
          const h_ = (new Date(match.start) - new Date(f.letztes)) / 36e5; if (!(h_ > 0 && h_ < 30)) return false;
          return (f.letztesMin && f.letztesMin >= 150) || (!f.letztesMin && f.letztesGames >= 33); };
        const mA = minuten(match.form.a), mB = minuten(match.form.b), wB = P.H_BELAST ?? 0.04, wL = P.H_LANG ?? 0.1;
        // erste 1,5 h Unterschied zählen nicht (Spielpraxis gleicht leichte Mehrbelastung aus)
        const dh0 = (mA - mB) / 60, dh = Math.sign(dh0) * clip(Math.abs(dh0) - (P.H_BELAST_FREI ?? 1.5), 0, 4);
        if (dh !== 0) { dForm -= wB * dh; form.push({ label: `Spielzeit 7 Tage ${Math.round(mA)} vs. ${Math.round(mB)} Min.`, d: -wB * dh }); }
        if (lang(match.form.a)) { dForm -= wL; form.push({ label: `${match.a}: langes Match in den letzten 30 h`, d: -wL }); }
        if (lang(match.form.b)) { dForm += wL; form.push({ label: `${match.b}: langes Match in den letzten 30 h`, d: wL }); }
      }
      // Heimvorteil: Spieler spielt im eigenen Land, Gegner nicht (Land aus der Spieldaten-API)
      const ortL = match.ort && match.ort.land, lA = match.landA, lB = match.landB, wH = P.H_HEIM ?? 0.1;
      if (ortL && lA && lB && lA !== lB) {
        if (lA === ortL) { dForm += wH; form.push({ label: `Heimspiel ${match.a} (${ortL})`, d: wH }); }
        if (lB === ortL) { dForm -= wH; form.push({ label: `Heimspiel ${match.b} (${ortL})`, d: -wH }); }
      }
      // Reise: voriges Spiel (innerhalb H_REISE_TAGE = 5 Tagen) mindestens 5 Zeitzonen entfernt
      if (match.ort && isNum(match.ort.tz) && match.start) {
        const wR = P.H_REISE ?? 0.08;
        for (const [k, nm, sg] of [["a", match.a, -1], ["b", match.b, 1]]) {
          const v = match.form && match.form[k] && match.form[k].vorOrt; if (!v || !isNum(v.tz)) continue;
          const tage = (new Date(match.start) - new Date(v.start)) / 864e5, dz = Math.abs(v.tz - match.ort.tz), z = Math.min(dz, 24 - dz);
          if (tage >= 0 && tage <= (P.H_REISE_TAGE ?? 5) && z >= 5) { dForm += sg * wR; form.push({ label: `${nm}: Reise ${Math.round(z)} Zeitzonen (${v.land} → ${match.ort.land}) vor ${Math.round(tage)} T.`, d: sg * wR }); }
        }
      }
      // Elo-Trend: Elo-Veränderung der letzten ~30 Tage im Vergleich (je 50 Punkte Unterschied H_TREND, höchstens 150)
      const trA = ((D.players || {})[match.a] || {}).elo_trend, trB = ((D.players || {})[match.b] || {}).elo_trend;
      if (trA && trB && isNum(trA.d) && isNum(trB.d)) {
        const dd = clip((trA.d - trB.d) / 50, -3, 3) * (P.H_TREND ?? 0.04);
        if (Math.abs(trA.d - trB.d) >= 25) { dForm += dd; form.push({ label: `Elo-Trend ${trA.d >= 0 ? "+" : ""}${trA.d} vs. ${trB.d >= 0 ? "+" : ""}${trB.d} (${trA.tage} T.)`, d: dd }); }
      }
      const p = sigm(L(pBasis) + wM * dModell + wS * dStats + dForm);
      return { p, pBasis, basis: basisName, dModell, wM, dStats, wS, dForm, form, teile };
    };
    const gesamt = gesamtRechnen(pinFair ?? pMarkt, pinFair != null ? "Pinnacle" : "Buchmacher");
    const gesamtModell = gesamtRechnen(pKal, "Modell");

    const varianten = {
      D: bewerte(pD, match, haveOdds, D, P),
      F: bewerte(pF, match, haveOdds, D, P),
      ...(pE !== null ? { E: bewerte(pE, match, haveOdds, D, P) } : {}),
      B: bewerte(mitMarkt(kombi(pStats, echteStats)), match, haveOdds, D, P),
      C: bewerte(mitMarkt(kombi(pStatsC, echteStats)), match, haveOdds, D, P),
      G: bewerte(pG, match, haveOdds, D, P),
      ...(gesamt ? { H: bewerte(gesamt.p, match, haveOdds, D, P) } : {}),
      I: bewerte(pKal, match, haveOdds, D, P),                       // I (Test seit 02.11.2026): nur Modell, ohne Markt-Mischung
      J: bewerte(gesamtModell.p, match, haveOdds, D, P),             // J: nur Modell + Statistiken + Umstände, ohne Markt
    };
    varianten.C.pStats = pStatsC;
    // ---- Varianten K–Q (Test seit 02.11.2026), Buchstabe M ist für „Markt“ vergeben ----
    const nur = (v, ok) => (ok ? v : Object.assign({}, v, { wette: null, edge: null, kelly: null }));
    const vA = bewerte(pFinal, match, haveOdds, D, P);
    // K Konsens: Tipp nur, wenn mindestens 3 von A, D, F, H dieselbe Seite tippen; p = Mittel der vier
    {
      const vs = [vA, varianten.D, varianten.F, varianten.H].filter(Boolean);
      const pK = vs.reduce((a, v) => a + v.p, 0) / vs.length, k = bewerte(pK, match, haveOdds, D, P);
      const nA = vs.filter((v) => v.wette === "A").length, nB = vs.filter((v) => v.wette === "B").length;
      const seite = nA >= (P.K_MIN ?? 3) ? "A" : nB >= (P.K_MIN ?? 3) ? "B" : null;
      if (seite && haveOdds) { const q = seite === "A" ? match.qa : match.qb, f = seite === "A" ? 1 / pK : 1 / (1 - pK);
        Object.assign(k, { wette: seite, edge: q / f - 1, kelly: Math.round(P.BANKROLL * P.KELLY_FRACTION * Math.max(0, (1 / f - 1 / q) / (1 - 1 / q)) * 100) / 100, stimmen: Math.max(nA, nB) });
      } else Object.assign(k, { wette: null, edge: null, kelly: null });
      varianten.K = k;
    }
    // L Mindest-Edge: wie A, aber erst ab L_MIN_EDGE (+5 %)
    varianten.L = nur(vA, vA.edge != null && vA.edge >= (P.L_MIN_EDGE ?? 0.05));
    // N Weniger Modell: wie A, aber nur N_BLEND (25 %) Modell, Rest Markt
    varianten.N = bewerte(pMarkt === null ? pKal : sigm((P.N_BLEND ?? 0.25) * logit(pKal) + (1 - (P.N_BLEND ?? 0.25)) * logit(pMarkt)), match, haveOdds, D, P);
    // O Excel-Muster: wie A, aber nur ATP (kein Challenger), Favorit, Quote 1,30–2,20
    {
      const ch = /challenger/i.test(String(match.turnier || "") + " " + String(match.kategorie || ""));
      const q = vA.wette === "A" ? match.qa : vA.wette === "B" ? match.qb : null;
      varianten.O = nur(vA, !ch && q != null && q >= (P.O_QUOTE_MIN ?? 1.3) && q <= (P.O_QUOTE_MAX ?? 2.2));
    }
    // P Pinnacle-Abweichung: p = faire Pinnacle-Quote, Tipp wenn der Buchmacher mind. PIN_MIN_EDGE mehr zahlt (ohne Modell)
    // (wie das 📌-Signal auf beiden Seiten, also auch Außenseiter, bis Quote PIN_MAX_QUOTE)
    if (pinFair != null) {
      const v = { p: pinFair, fairA: 1 / pinFair, fairB: 1 / (1 - pinFair), wette: null, edge: null, kelly: null };
      if (haveOdds) {
        const eA = match.qa * pinFair - 1, eB = match.qb * (1 - pinFair) - 1, mE = P.PIN_MIN_EDGE ?? 0.02, mQ = P.PIN_MAX_QUOTE ?? 5;
        const okA = eA >= mE && match.qa <= mQ, okB = eB >= mE && match.qb <= mQ;
        const seite = okA && (!okB || eA >= eB) ? "A" : okB ? "B" : null;
        if (seite) { const q = seite === "A" ? match.qa : match.qb, pp = seite === "A" ? pinFair : 1 - pinFair;
          Object.assign(v, { wette: seite, edge: seite === "A" ? eA : eB, kelly: Math.round(P.BANKROLL * P.KELLY_FRACTION * Math.max(0, (pp - 1 / q) / (1 - 1 / q)) * 100) / 100 }); }
      }
      varianten.P = v;
    }
    // Q Quotenbewegung: wie A, aber nur wenn sich Pinnacle seit dem ersten Sehen um mind. Q_MIN_BEWEGUNG zu unserer Seite bewegt hat
    if (pinFair != null && Array.isArray(match.pinErst) && match.pinErst[0] > 1 && match.pinErst[1] > 1) {
      const p0 = (1 / match.pinErst[0]) / (1 / match.pinErst[0] + 1 / match.pinErst[1]), dp = pinFair - p0, mind = P.Q_MIN_BEWEGUNG ?? 0.01;
      varianten.Q = nur(vA, (vA.wette === "A" && dp >= mind) || (vA.wette === "B" && -dp >= mind));
      varianten.Q.bewegung = dp;
    }
    const ohneModell = new Set(["P"]);   // P nutzt keine Elo -> Regel „geschätzte Elo“ greift dort nicht
    if (eloGeschaetzt) for (const [k_, v] of Object.entries(varianten)) if (!ohneModell.has(k_)) { v.wette = null; v.edge = null; v.kelly = null; }   // gleiche Regel für alle Modell-Varianten

    // Satzverteilung: Sätze sind nicht unabhängig (mehr glatte Siege als im Markov-Modell) – globaler Faktor je Ebene,
    // dazu der Turnierfaktor aus turnier_stats.json (nur ATP-Ebene). Siegchance unverändert.
    const istCh = /challenger/i.test(String(match.turnier || "") + " " + String(match.kategorie || ""));
    const satzBasis = mode === 5 ? (P.SATZ_GLATT_BO5 ?? 1) : istCh ? (P.SATZ_GLATT_CH ?? 1) : (P.SATZ_GLATT_ATP ?? 1);
    const tst = lookupTurnierStats(match.turnier, D.turnierStats);
    const satzK = { basis: satzBasis, turnier: tst ? tst.name : null, faktor: tst ? tst.faktor : 1, k: satzBasis * (tst ? tst.faktor : 1) };

    // Satz- und Tiebreak-Märkte (2:0, 3 Sätze, 1. Satz, Tiebreak im 1. Satz / im Match)
    const maerkte = (() => {
      const hA = pGame(pSrvA), hB = pGame(pSrvB), mm = {};
      const zuTB = (a, b, aSrv) => { const k = a + "|" + b + "|" + aSrv; if (k in mm) return mm[k];
        let r; if (a === 6 && b === 6) r = 1; else if (a === 7 || b === 7 || (a >= 6 && a - b >= 2) || (b >= 6 && b - a >= 2)) r = 0;
        else r = aSrv ? hA * zuTB(a + 1, b, false) + (1 - hA) * zuTB(a, b + 1, false) : (1 - hB) * zuTB(a + 1, b, true) + hB * zuTB(a, b + 1, true);
        return (mm[k] = r); };
      const tRoh = (zuTB(0, 0, true) + zuTB(0, 0, false)) / 2;
      // Test (seit 04.11.2026): Tiebreak-Chance aus den gehaltenen Aufschlagspielen der Spieler (hold_stats.json) statt aus den
      // Aufschlagpunkten – eigener Aufschlag gehalten und Halten der Gegner gegen ihn, je zum Tour-Schnitt gezogen (H_HOLD_K Spiele)
      const tbAusHold = (() => {
        const hs = D.holdStats; if (!hs || !hs.spieler) return null;
        const xa = (hs.spieler[match.a] || {})[sk] || (hs.spieler[match.a] || {}).alle, xb = (hs.spieler[match.b] || {})[sk] || (hs.spieler[match.b] || {}).alle;
        if (!xa || !xb || xa[1] < 10 || xb[1] < 10) return null;
        const avg = (hs.tour || {})[(istCh ? "ch_" : "atp_") + sk] || (hs.tour || {})["ch_" + sk] || 0.8, K = P.H_HOLD_K ?? 40, Lg = (q) => logit(clip(q, 0.02, 0.98));
        const sh = (h, n) => (h + K * avg) / (n + K);
        const gA = sigm(Lg(sh(xa[0], xa[1])) + Lg(sh(xb[2], xb[3])) - Lg(avg)), gB = sigm(Lg(sh(xb[0], xb[1])) + Lg(sh(xa[2], xa[3])) - Lg(avg));
        const m2 = {}, z2 = (a, b, aSrv) => { const k = a + "|" + b + "|" + aSrv; if (k in m2) return m2[k];
          let r; if (a === 6 && b === 6) r = 1; else if (a === 7 || b === 7 || (a >= 6 && a - b >= 2) || (b >= 6 && b - a >= 2)) r = 0;
          else r = aSrv ? gA * z2(a + 1, b, false) + (1 - gA) * z2(a, b + 1, false) : (1 - gB) * z2(a + 1, b, true) + gB * z2(a, b + 1, true);
          return (m2[k] = r); };
        return { roh: (z2(0, 0, true) + z2(0, 0, false)) / 2, holdA: gA, holdB: gB };
      })();
      const tbF = (istCh ? (P.TB_FAKTOR_CH ?? 1) : (P.TB_FAKTOR_ATP ?? 1)) * (tst && isNum(tst.tb_faktor) ? tst.tb_faktor : 1);
      const t = clip(tRoh * tbF, 0.01, 0.8);
      const ss = setScores(pFinal, mode, satzK.k), sc = ss.scores;
      const nSaetze = mode === 5 ? { 3: sc["3-0"] + sc["0-3"], 4: sc["3-1"] + sc["1-3"], 5: sc["3-2"] + sc["2-3"] }
                                 : { 2: sc["2-0"] + sc["0-2"], 3: sc["2-1"] + sc["1-2"] };
      let tbMatch = 0; for (const [n, pn] of Object.entries(nSaetze)) tbMatch += pn * (1 - (1 - t) ** +n);
      // Test (seit 04.11.2026, nur ATP mit Platztempo): Tiebreak-Faktor aus dem Platztempo statt aus der Turnier-Tiebreak-Quote.
      // Steigung aus den ATP-Turnieren (Tiebreak-Anteil je Satz ~ Tempo): Hart +63 % je 1,0 Tempo um 1,10, Sand +107 % um 0,69, Rasen +97 % um 1,13
      let tbTest = null;
      if (isNum(tempoF)) {
        const [mitte, steig] = { hard: [1.10, 0.63], clay: [0.69, 1.07], grass: [1.13, 0.97] }[sk] || [1.10, 0.63];
        const fT = clip(1 + steig * (tempoF - mitte), 0.8, 1.3), tT = clip(tRoh * (istCh ? (P.TB_FAKTOR_CH ?? 1) : (P.TB_FAKTOR_ATP ?? 1)) * fT, 0.01, 0.8);
        let mT = 0; for (const [n, pn] of Object.entries(nSaetze)) mT += pn * (1 - (1 - tT) ** +n);
        tbTest = { tb1: tT, tbMatch: mT, faktor: fT };
      }
      let tbHold = null;
      if (tbAusHold) {
        const tH = clip(tbAusHold.roh * tbF, 0.01, 0.8);
        let mH = 0; for (const [n, pn] of Object.entries(nSaetze)) mH += pn * (1 - (1 - tH) ** +n);
        tbHold = { tb1: tH, tbMatch: mH, holdA: tbAusHold.holdA, holdB: tbAusHold.holdB };
      }
      return { glattA: mode === 5 ? sc["3-0"] : sc["2-0"], glattB: mode === 5 ? sc["0-3"] : sc["0-2"],
        volleDistanz: mode === 5 ? null : sc["2-1"] + sc["1-2"], satz1A: ss.q, tb1: t, tbMatch, tbRoh: tRoh, tbFaktor: tbF, tbTest, tbHold,
        // Best-of-5 (Grand Slams): über/unter 3,5 bzw. 4,5 Sätze und genaue Ergebnisse 3:1 / 3:2
        ...(mode === 5 ? { ueber35: 1 - sc["3-0"] - sc["0-3"], ueber45: sc["3-2"] + sc["2-3"], dreiEinsA: sc["3-1"], dreiEinsB: sc["1-3"],
          dreiZweiA: sc["3-2"], dreiZweiB: sc["2-3"] } : {}) };
    })();

    return Object.assign(out, {
      maerkte, gesamt, gesamtModell,
      varianten,
      ok: true, modus: mode, csi, tempo: lookupTempo(match.turnier, match.belag, D.tempo),
      eloA, eloB, yEloA: pa.elo, yEloB: pb.elo,
      pSrvA, pSrvB, pStats, pElo,
      h2h: { a: hA, b: hB, n: hN, quelle: hQuelle, pct: hN > 0 ? h2hPct : null, gewicht: h2hW },
      tbA, tbB, pKombi, pKal, pMarkt, pFinal,
      fairA, fairB, fairModellA: 1 / pKal, fairModellB: 1 / (1 - pKal),
      fairMarktA: pMarkt ? 1 / pMarkt : null, fairMarktB: pMarkt ? 1 / (1 - pMarkt) : null,
      edgeA, edgeB, valueA, valueB, empfehlung, wette, kelly, buchQ,
      favCheck, ausCheck, baender, aussenseiter, bilanzSignal,
      saetze: setScores(pFinal, mode, satzK.k),
      saetzeUnabh: setScores(pFinal, mode, 1), satzK,
    });
  }


  // ---- Empfehlungen (Seite „Empfehlungen“, seit 03.11.2026, getrennt von Bilanz und Value-Tipps) ----
  // Je ATP-Partie eine Hauptwette und eine Alternative aus Sieg und Satz-/Tiebreak-Märkten – Value ist nicht nötig.
  // Siegchance = Gesamtschätzung H (sonst Modell A), Satzverteilung daraus mit Glatt-Korrektur, Tiebreak aus dem Modell.
  // Kandidaten: Quote EMP_MIN_QUOTE–EMP_MAX_QUOTE und Edge mind. EMP_MIN_EDGE (nicht deutlich schlechter als fair).
  // Haupt = höchste Trefferchance. Alternative = bester Erwartungswert (p · Quote) unter den Märkten mit spürbar
  // höherer Quote (mind. EMP_ALT_ABSTAND über der Hauptwette), ohne das Gegenteil der Hauptwette; sonst zweithöchste Chance.
  const EMP_GEGEN = { ueber35: "unter35", unter35: "ueber35", ueber45: "unter45", unter45: "ueber45", siegA: "siegB", siegB: "siegA", glattA: "mind1B", mind1B: "glattA", glattB: "mind1A", mind1A: "glattB", dreiSaetze: "zweiSaetze",
    zweiSaetze: "dreiSaetze", satz1A: "satz1B", satz1B: "satz1A", tb1Ja: "tb1Nein", tb1Nein: "tb1Ja", tbJa: "tbNein", tbNein: "tbJa" };
  function empfehlungen(r, match, mq, P) {
    if (!r || !r.ok || !(match.qa > 1 && match.qb > 1)) return null;
    mq = mq || {};
    const pW = r.gesamt && isNum(r.gesamt.p) ? r.gesamt.p : r.pFinal, mode = r.modus || 3;
    const ss = setScores(pW, mode, (r.satzK && r.satzK.k) || 1), sc = ss.scores, mk = r.maerkte || {};
    const pM = { siegA: pW, siegB: 1 - pW, satz1A: ss.q, satz1B: 1 - ss.q, tb1Ja: mk.tb1, tb1Nein: 1 - mk.tb1, tbJa: mk.tbMatch, tbNein: 1 - mk.tbMatch };
    if (mode === 3) Object.assign(pM, { glattA: sc["2-0"], glattB: sc["0-2"], mind1A: 1 - sc["0-2"], mind1B: 1 - sc["2-0"], zweiEinsA: sc["2-1"], zweiEinsB: sc["1-2"],
      dreiSaetze: sc["2-1"] + sc["1-2"], zweiSaetze: sc["2-0"] + sc["0-2"] });
    else Object.assign(pM, { glattA: sc["3-0"], glattB: sc["0-3"], mind1A: 1 - sc["0-3"], mind1B: 1 - sc["3-0"], dreiEinsA: sc["3-1"], dreiEinsB: sc["1-3"],
      dreiZweiA: sc["3-2"], dreiZweiB: sc["2-3"], ueber35: 1 - sc["3-0"] - sc["0-3"], unter35: sc["3-0"] + sc["0-3"], ueber45: sc["3-2"] + sc["2-3"], unter45: 1 - sc["3-2"] - sc["2-3"] });
    const qOf = { siegA: match.qa, siegB: match.qb };
    const minQ = P.EMP_MIN_QUOTE ?? 1.2, maxQ = P.EMP_MAX_QUOTE ?? 5, minE = P.EMP_MIN_EDGE ?? -0.05;
    const kand = [];
    for (const [k, p] of Object.entries(pM)) {
      const q = qOf[k] || mq[k];
      if (!(q > 1) || !(p > 0 && p < 1) || q < minQ || q > maxQ) continue;
      const edge = q * p - 1; if (edge < minE) continue;
      kand.push({ k, p, q, edge });
    }
    if (!kand.length) return { pW, haupt: null, alt: null, kand };
    const haupt = kand.slice().sort((a, b) => b.p - a.p || b.edge - a.edge)[0];
    const rest = kand.filter((x) => x.k !== haupt.k && x.k !== EMP_GEGEN[haupt.k]);
    const hoeher = rest.filter((x) => x.q >= haupt.q + (P.EMP_ALT_ABSTAND ?? 0.3) && x.q <= (P.EMP_ALT_MAX_QUOTE ?? 3));
    const alt = hoeher.length ? hoeher.sort((a, b) => b.p * b.q - a.p * a.q || b.p - a.p)[0] : (rest.sort((a, b) => b.p - a.p)[0] || null);
    return { pW, haupt, alt, kand };
  }

  // ---- Live-Rechner (wie Excel-Blatt LIVE-WETTEN): Siegchance A ab aktuellem Spielstand.
  // st = {sA, sB (Sätze), gA, gB (Spiele im Satz), pA, pB (Punkte 0..4 = 0/15/30/40/AD bzw. Tiebreak-Punkte), tb (bool),
  //       srv ("A"/"B", Aufschläger im laufenden Spiel), saetze ([[A,B], …] abgeschlossene Sätze)}
  // o = {pSrvA, pSrvB, modus (3/5), pPre (Pre-Match-Prognose final), momentum (Gewicht, z. B. 0,3), pMin, pMax}
  function live(st, o) {
    const need = ((o.modus || 3) + 1) / 2, pmin = o.pMin ?? 0.4, pmax = o.pMax ?? 0.85;
    const D2 = (p) => p * p / (p * p + (1 - p) * (1 - p));
    const rechne = (pA, pB) => {
      const gm = {}, game = (p, a, b) => {           // Aufschläger gewinnt das Spiel ab Punktstand a:b
        const k = p + "|" + a + "|" + b; if (k in gm) return gm[k];
        let r;
        if (a >= 4 && a - b >= 2) r = 1; else if (b >= 4 && b - a >= 2) r = 0;
        else if (a >= 3 && b >= 3) r = a === b ? D2(p) : a > b ? p + (1 - p) * D2(p) : p * D2(p);
        else r = p * game(p, a + 1, b) + (1 - p) * game(p, a, b + 1);
        return (gm[k] = r);
      };
      const pt = (pA + (1 - pB)) / 2, tm = {}, tb = (a, b) => {   // Tiebreak (neutraler Punktgewinn wie Excel)
        const k = a + "|" + b; if (k in tm) return tm[k];
        let r;
        if (a >= 7 && a - b >= 2) r = 1; else if (b >= 7 && b - a >= 2) r = 0;
        else if (a >= 6 && b >= 6) r = a === b ? D2(pt) : a > b ? pt + (1 - pt) * D2(pt) : pt * D2(pt);
        else r = pt * tb(a + 1, b) + (1 - pt) * tb(a, b + 1);
        return (tm[k] = r);
      };
      const hA = game(pA, 0, 0), hB = game(pB, 0, 0), sm = {}, set = (a, b, aSrv) => {
        const k = a + "|" + b + "|" + aSrv; if (k in sm) return sm[k];
        let r;
        if (a === 7 || (a >= 6 && a - b >= 2)) r = 1; else if (b === 7 || (b >= 6 && b - a >= 2)) r = 0;
        else if (a === 6 && b === 6) r = tb(0, 0);
        else r = aSrv ? hA * set(a + 1, b, false) + (1 - hA) * set(a, b + 1, false)
                      : (1 - hB) * set(a + 1, b, true) + hB * set(a, b + 1, true);
        return (sm[k] = r);
      };
      const ps = (set(0, 0, true) + set(0, 0, false)) / 2, mm = {}, match = (a, b) => {
        const k = a + "|" + b; if (k in mm) return mm[k];
        const r = a >= need ? 1 : b >= need ? 0 : ps * match(a + 1, b) + (1 - ps) * match(a, b + 1);
        return (mm[k] = r);
      };
      const aSrv = st.srv !== "B";
      let gameA = null, pSet;
      if (st.tb || (st.gA === 6 && st.gB === 6)) pSet = tb(st.pA || 0, st.pB || 0);
      else {
        gameA = aSrv ? game(pA, st.pA || 0, st.pB || 0) : 1 - game(pB, st.pB || 0, st.pA || 0);
        pSet = gameA * set((st.gA || 0) + 1, st.gB || 0, !aSrv) + (1 - gameA) * set(st.gA || 0, (st.gB || 0) + 1, !aSrv);
      }
      const p = pSet * match((st.sA || 0) + 1, st.sB || 0) + (1 - pSet) * match(st.sA || 0, (st.sB || 0) + 1);
      return { p, pSet, gameA, p00: match(0, 0), hA, hB };
    };
    // Momentum: Spielgewinn-Anteil bisher minus erwarteter Anteil verschiebt p_srv (ab 4 gespielten Spielen)
    const basis = rechne(o.pSrvA, o.pSrvB);
    let gw = st.gA || 0, gl = st.gB || 0;
    for (const [x, y] of st.saetze || []) { gw += +x || 0; gl += +y || 0; }
    const g = (basis.hA + (1 - basis.hB)) / 2, delta = gw + gl >= 4 ? gw / (gw + gl) - g : 0, w = o.momentum || 0;
    const pA2 = clip(o.pSrvA + w * delta, pmin, pmax), pB2 = clip(o.pSrvB - w * delta, pmin, pmax);
    const lv = w && delta ? rechne(pA2, pB2) : basis;
    // Kalibrierung: Logit-Verschiebung, damit 0:0 genau die Pre-Match-Prognose ergibt
    const off = isNum(o.pPre) && o.pPre > 0 && o.pPre < 1 ? logit(o.pPre) - logit(clip(basis.p00, 1e-4, 1 - 1e-4)) : 0;
    const pure = clip(lv.p, 0, 1);
    const kal = pure <= 0 || pure >= 1 ? pure : sigm(logit(clip(pure, 1e-6, 1 - 1e-6)) + off);
    return { p: kal, pPur: pure, pSet: lv.pSet, pGame: lv.gameA, offset: off, delta, pSrvA: pA2, pSrvB: pB2, gespielt: gw + gl };
  }

  const api = { analyse, live, weights, empfehlungen, lookupTurnierStats, pGame, pSet, pMatch, detectMode, lookupCSI, lookupTempo, setScores, quotenBand };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TennisModel = api;
})(typeof self !== "undefined" ? self : this);
