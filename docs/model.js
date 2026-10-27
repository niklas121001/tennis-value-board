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
  function lookupTempo(turnier, belag, tabelle) {
    const t = String(turnier || "").toLowerCase(), sk = surfKey(belag);
    if (!tabelle || /challenger/.test(t) || (sk !== "hard" && sk !== "grass")) return null;
    for (const row of tabelle) {
      if (row.belag !== sk) continue;
      for (const n of [row.name, ...(row.alias || [])]) if (n && t.includes(String(n).toLowerCase())) return row.speed;
    }
    return null;
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
  function setScores(pFinal, mode) {
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
    } else {
      sc = { "2-0": q ** 2, "2-1": 2 * q ** 2 * r, "0-2": r ** 2, "1-2": 2 * r ** 2 * q };
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
    const mix = (p) => (P.YELO_EINBEZIEHEN === "Ja" && isNum(p.elo) ? P.W_YELO_BLEND * p.elo + (1 - P.W_YELO_BLEND) * belagElo(p) : belagElo(p));
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
    const csi = lookupCSI(match.turnier, match.belag, D.csi || []);
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
    const varianten = {
      D: bewerte(pD, match, haveOdds, D, P),
      ...(pE !== null ? { E: bewerte(pE, match, haveOdds, D, P) } : {}),
      B: bewerte(mitMarkt(kombi(pStats, echteStats)), match, haveOdds, D, P),
      C: bewerte(mitMarkt(kombi(pStatsC, echteStats)), match, haveOdds, D, P),
    };
    varianten.C.pStats = pStatsC;

    return Object.assign(out, {
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
      saetze: setScores(pFinal, mode),
    });
  }

  const api = { analyse, pGame, pSet, pMatch, detectMode, lookupCSI, setScores, quotenBand };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TennisModel = api;
})(typeof self !== "undefined" ? self : this);
