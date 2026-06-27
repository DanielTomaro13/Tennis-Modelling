// sim.js — in-browser port of src/sim.py. Powers the live head-to-head predictor.
// Kept deliberately small and 1:1 with the Python engine.

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

export function pointProbs(a, b, league) {
  const lrpw = league.rpw;
  const pa = clamp(a.spw - (b.rpw - lrpw), 0.40, 0.93);
  const pb = clamp(b.spw - (a.rpw - lrpw), 0.40, 0.93);
  return [pa, pb];
}

export function gameHold(p) {
  const q = 1 - p;
  const pdeuce = 20 * p ** 3 * q ** 3;
  const wfd = (p * p) / (p * p + q * q);
  return p ** 4 + 4 * p ** 4 * q + 10 * p ** 4 * q ** 2 + pdeuce * wfd;
}

export function gameExpectedPoints(p) {
  const q = 1 - p;
  const p4 = p ** 4 + q ** 4;
  const p5 = 4 * p * q * (p ** 3 + q ** 3);
  const p6 = 10 * p ** 4 * q ** 2 + 10 * p ** 2 * q ** 4;
  const pdeuce = 20 * p ** 3 * q ** 3;
  const extra = 2.0 / (p * p + q * q);
  return 4 * p4 + 5 * p5 + 6 * p6 + (6 + extra) * pdeuce;
}

export function gameHoldNoAd(p) {
  // No-ad: first to 4 points, single deciding point at 3-3.
  const q = 1 - p;
  return p ** 4 + 4 * p ** 4 * q + 10 * p ** 4 * q ** 2 + 20 * p ** 4 * q ** 3;
}

export function tiebreakWin(pa, pb, first = "A", target = 7) {
  const server = (n) => {
    const g = Math.floor((n + 1) / 2);
    return g % 2 === 0 ? first : (first === "A" ? "B" : "A");
  };
  const wpa = (n) => (server(n) === "A" ? pa : 1 - pb);
  const memo = new Map();
  const f = (a, b) => {
    if (a >= target && a - b >= 2) return 1.0;
    if (b >= target && b - a >= 2) return 0.0;
    if (a >= target - 1 && b >= target - 1 && a === b) {
      const n = a + b;
      const wa1 = wpa(n), wa2 = wpa(n + 1);
      const both = wa1 * wa2;
      const split = wa1 * (1 - wa2) + (1 - wa1) * wa2;
      return split < 1 ? both / (1 - split) : 0.5;
    }
    const key = a * 100 + b;
    if (memo.has(key)) return memo.get(key);
    const wa = wpa(a + b);
    const v = wa * f(a + 1, b) + (1 - wa) * f(a, b + 1);
    memo.set(key, v);
    return v;
  };
  return f(0, 0);
}

export function setDistribution(pa, pb, first = "A", noAd = false) {
  const holdFn = noAd ? gameHoldNoAd : gameHold;
  const holdA = holdFn(pa), holdB = holdFn(pb);
  const tbFirst = first; // 12 games played -> same as set first server
  const tbA = tiebreakWin(pa, pb, tbFirst);
  const serverOf = (ga, gb) => ((ga + gb) % 2 === 0 ? first : (first === "A" ? "B" : "A"));
  const isTerm = (ga, gb) =>
    (ga === 6 && gb <= 4) || (gb === 6 && ga <= 4) || (ga === 7 && gb === 5) || (gb === 7 && ga === 5);
  const terminal = new Map();
  const add = (k, v) => terminal.set(k, (terminal.get(k) || 0) + v);
  let layer = new Map([["0,0", 1.0]]);
  for (let i = 0; i < 13; i++) {
    const nxt = new Map();
    for (const [k, prob] of layer) {
      const [ga, gb] = k.split(",").map(Number);
      if (isTerm(ga, gb)) { add(`${ga},${gb},0`, prob); continue; }
      if (ga === 6 && gb === 6) {
        add("7,6,1", prob * tbA); add("6,7,1", prob * (1 - tbA)); continue;
      }
      const srv = serverOf(ga, gb);
      const aWins = srv === "A" ? holdA : 1 - holdB;
      nxt.set(`${ga + 1},${gb}`, (nxt.get(`${ga + 1},${gb}`) || 0) + prob * aWins);
      nxt.set(`${ga},${gb + 1}`, (nxt.get(`${ga},${gb + 1}`) || 0) + prob * (1 - aWins));
    }
    layer = nxt;
  }
  const out = [];
  for (const [k, pr] of terminal) {
    const [ga, gb, tb] = k.split(",").map(Number);
    out.push([pr, ga, gb, !!tb]);
  }
  return out;
}

function poissonCdf(k, mean) {
  if (mean <= 0) return 1.0;
  let term = Math.exp(-mean), cdf = term;
  for (let i = 1; i <= k; i++) { term *= mean / i; cdf += term; }
  return Math.min(1, cdf);
}

function mostCompare(lamA, lamB) {
  const kMax = Math.max(30, Math.floor(Math.max(lamA, lamB) * 2) + 25);
  const pmf = (lam) => {
    const out = [lam > 0 ? Math.exp(-lam) : 1.0];
    for (let k = 1; k <= kMax; k++) out.push(lam > 0 ? out[k - 1] * lam / k : 0.0);
    return out;
  };
  const pa = pmf(lamA), pb = pmf(lamB);
  let aGt = 0, tie = 0, cumA = 0;
  for (let y = 0; y <= kMax; y++) { cumA += pa[y]; aGt += pb[y] * (1 - cumA); tie += pa[y] * pb[y]; }
  return { a: aGt, tie, b: Math.max(0, 1 - aGt - tie) };
}

export function projectMatch(a, b, league, bestOf = 3, totalsLines = [20.5, 21.5, 22.5, 23.5]) {
  const [pa, pb] = pointProbs(a, b, league);
  const setsToWin = bestOf === 5 ? 3 : 2;
  const setEven = setDistribution(pa, pb, "A");
  const setOdd = setDistribution(pa, pb, "B");

  let state = new Map([["0,0,0,0,0", 1.0]]);
  const final = new Map();
  const addF = (k, v) => final.set(k, (final.get(k) || 0) + v);
  for (let si = 0; si < 2 * setsToWin - 1; si++) {
    const nxt = new Map();
    const base = si % 2 === 0 ? setEven : setOdd;
    for (const [k, prob] of state) {
      const [sa, sb, ga, gb, anytb] = k.split(",").map(Number);
      if (sa === setsToWin || sb === setsToWin) { addF(k, prob); continue; }
      for (const [spr, sga, sgb, tb] of base) {
        const aWon = sga > sgb;
        const nsa = sa + (aWon ? 1 : 0), nsb = sb + (aWon ? 0 : 1);
        const nk = `${nsa},${nsb},${ga + sga},${gb + sgb},${anytb || tb ? 1 : 0}`;
        nxt.set(nk, (nxt.get(nk) || 0) + prob * spr);
      }
    }
    state = nxt;
  }
  for (const [k, prob] of state) addF(k, prob);

  let winA = 0, anyTb = 0, etg = 0, ega = 0, egb = 0;
  const setScore = {}, gamesDist = {}, marginDist = {}, aGames = {}, bGames = {};
  const bump = (o, k, v) => (o[k] = (o[k] || 0) + v);
  for (const [k, pr] of final) {
    const [sa, sb, ga, gb, anytb] = k.split(",").map(Number);
    if (sa > sb) winA += pr;
    bump(setScore, `${sa}-${sb}`, pr);
    bump(gamesDist, ga + gb, pr);
    bump(marginDist, ga - gb, pr);
    bump(aGames, ga, pr); bump(bGames, gb, pr);
    etg += pr * (ga + gb); ega += pr * ga; egb += pr * gb;
    if (anytb) anyTb += pr;
  }
  const ou = (dist, line) => { let o = 0; for (const v in dist) if (Number(v) > line) o += dist[v]; return { over: o, under: 1 - o }; };
  const totals = {}; totalsLines.forEach((l) => (totals[l] = ou(gamesDist, l)));
  const handicap = {};
  [6.5, 4.5, 2.5, 1.5, -1.5, -2.5, -4.5, -6.5].forEach((thr) => {
    let c = 0; for (const m in marginDist) if (Number(m) > thr) c += marginDist[m];
    const line = -thr;
    handicap[(line > 0 ? "+" : "") + line.toFixed(1)] = c;
  });
  const setWin = (dist) => dist.reduce((s, [p, sga, sgb]) => s + (sga > sgb ? p : 0), 0);
  const set1A = setWin(setEven), set2A = setWin(setOdd);
  let aSet0 = 0, bSet0 = 0, straight = 0;
  for (const k in setScore) {
    if (k.startsWith("0-")) aSet0 += setScore[k];
    if (k.endsWith("-0")) bSet0 += setScore[k];
    const lo = Math.min(+k[0], +k[k.length - 1]), hi = Math.max(+k[0], +k[k.length - 1]);
    if (lo === 0 && hi === setsToWin) straight += setScore[k];
  }
  const pgOU = (dist, mean) => { const c = Math.round(mean), o = {}; [-2, -1, 0, 1, 2].forEach((d) => (o[(c + d + 0.5).toFixed(1)] = ou(dist, c + d + 0.5))); return o; };
  const spA = ega * gameExpectedPoints(pa), spB = egb * gameExpectedPoints(pb);
  const eAcesA = a.ace_rate * spA, eAcesB = b.ace_rate * spB, eDfA = a.df_rate * spA, eDfB = b.df_rate * spB;
  const poiOU = (mean) => { const c = Math.max(0, Math.round(mean)), o = {}; [-2, -1, 0, 1, 2].forEach((d) => { const line = c + d + 0.5; if (line > 0) o[line.toFixed(1)] = 1 - poissonCdf(Math.floor(line), mean); }); return o; };

  return {
    p_a_serve: pa, p_b_serve: pb, hold_a: gameHold(pa), hold_b: gameHold(pb),
    sr_win_a: winA, set1_win_a: set1A, set2_win_a: set2A,
    straight_sets: straight, deciding_set: 1 - straight,
    a_wins_set: 1 - aSet0, b_wins_set: 1 - bSet0,
    set_score: setScore, exp_total_games: etg, exp_games_a: ega, exp_games_b: egb,
    totals, handicap, player_games_a: pgOU(aGames, ega), player_games_b: pgOU(bGames, egb),
    tiebreak_prob: anyTb,
    exp_aces_a: eAcesA, exp_aces_b: eAcesB, exp_df_a: eDfA, exp_df_b: eDfB,
    aces_ou_a: poiOU(eAcesA), aces_ou_b: poiOU(eAcesB), df_ou_a: poiOU(eDfA), df_ou_b: poiOU(eDfB),
    most_aces: mostCompare(eAcesA, eAcesB), most_df: mostCompare(eDfA, eDfB),
    ...(() => {
      const sg = etg / 2;
      const brA = sg * (1 - gameHold(pb)), brB = sg * (1 - gameHold(pa));
      return {
        exp_breaks_a: brA, exp_breaks_b: brB, exp_total_breaks: brA + brB,
        breaks_ou: poiOU(brA + brB), most_breaks: mostCompare(brA, brB),
        break_at_least_a: 1 - Math.exp(-brA), break_at_least_b: 1 - Math.exp(-brB),
        hold_all_a: Math.exp(-brB), hold_all_b: Math.exp(-brA),
      };
    })(),
  };
}

// Combine two players into one team serve/return profile (simple average).
export function teamProfile(p1, p2) {
  const avg = (k) => (p1[k] + p2[k]) / 2;
  return {
    spw: avg("spw"), rpw: avg("rpw"),
    ace_rate: avg("ace_rate"), df_rate: avg("df_rate"), pr: avg("pr"),
  };
}

// Doubles projection: no-ad games, sets to 6 (7-pt TB), deciding set = 10-pt
// match tiebreak. Modelled from the four players' singles form as a proxy.
export function projectDoubles(teamA, teamB, league) {
  const [pa, pb] = pointProbs(teamA, teamB, league);
  const setEven = setDistribution(pa, pb, "A", true);
  const setOdd = setDistribution(pa, pb, "B", true);
  const setWinFrom = (dist) => dist.reduce((s, [p, ga, gb]) => s + (ga > gb ? p : 0), 0);
  const tbFrom = (dist) => dist.reduce((s, [p, , , tb]) => s + (tb ? p : 0), 0);
  const gamesFrom = (dist) => dist.reduce((s, [p, ga, gb]) => s + p * (ga + gb), 0);

  const s1A = setWinFrom(setEven), s2A = setWinFrom(setOdd);
  const superA = tiebreakWin(pa, pb, "A", 10);

  const p20 = s1A * s2A;                                   // A wins sets 1 & 2
  const p02 = (1 - s1A) * (1 - s2A);                       // B wins both
  const split = s1A * (1 - s2A) + (1 - s1A) * s2A;         // 1-1 -> super TB
  const p21 = split * superA, p12 = split * (1 - superA);
  const winA = p20 + p21;

  const setScore = { "2-0": p20, "2-1": p21, "1-2": p12, "0-2": p02 };
  const straight = p20 + p02;
  const expGames = gamesFrom(setEven) + gamesFrom(setOdd) * (1 - p20 - p02) /* set2 always played */;
  return {
    sr_win_a: winA,
    set_score: setScore,
    straight_sets: straight,
    deciding_set: split,                                   // goes to match tie-break
    a_wins_set: 1 - p02, b_wins_set: 1 - p20,
    set1_win_a: s1A, set2_win_a: s2A,
    super_tb_a: superA,
    exp_total_games: gamesFrom(setEven) + gamesFrom(setOdd),
    tiebreak_prob: 1 - (1 - tbFrom(setEven)) * (1 - tbFrom(setOdd)),
    hold_a: gameHoldNoAd(pa), hold_b: gameHoldNoAd(pb),
  };
}

export function prWinProb(prA, prB, scale = 130.0) {
  return 1.0 / (1.0 + Math.exp(-(prA - prB) / scale));
}

// Results-based surface Elo win prob (mirrors ratings.elo_win_prob).
export function eloWinProb(elo, a, b, surface, surfW = 0.5) {
  if (!elo) return null;
  const init = 1500;
  const sa = (elo.surface && elo.surface[surface]) || {};
  const ra = surfW * (sa[a] ?? init) + (1 - surfW) * ((elo.overall || {})[a] ?? init);
  const rb = surfW * (sa[b] ?? init) + (1 - surfW) * ((elo.overall || {})[b] ?? init);
  return 1 / (1 + 10 ** ((rb - ra) / 400));
}
const _logit = (p) => { p = Math.min(Math.max(p, 1e-9), 1 - 1e-9); return Math.log(p / (1 - p)); };
export function combineProb(simP, eloP, w) {
  return eloP == null ? simP : 1 / (1 + Math.exp(-((1 - w) * _logit(simP) + w * _logit(eloP))));
}
// Re-project the match with the per-point edge shifted so the winner prob = target.
export function anchorTo(a, b, league, bestOf, target, totalsLines) {
  const base = projectMatch(a, b, league, bestOf, totalsLines);
  if (target == null || Math.abs(base.sr_win_a - target) < 0.004) return base;
  let lo = -0.18, hi = 0.18, last = base;
  for (let i = 0; i < 16; i++) {
    const d = (lo + hi) / 2;
    const aa = { ...a, spw: a.spw + d, rpw: a.rpw + d }, bb = { ...b, spw: b.spw - d, rpw: b.rpw - d };
    last = projectMatch(aa, bb, league, bestOf, totalsLines);
    if (last.sr_win_a < target) lo = d; else hi = d;
  }
  return last;
}
