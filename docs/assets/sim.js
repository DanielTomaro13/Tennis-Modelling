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

export function tiebreakWin(pa, pb, first = "A") {
  const server = (n) => {
    const g = Math.floor((n + 1) / 2);
    return g % 2 === 0 ? first : (first === "A" ? "B" : "A");
  };
  const wpa = (n) => (server(n) === "A" ? pa : 1 - pb);
  const memo = new Map();
  const f = (a, b) => {
    if (a >= 7 && a - b >= 2) return 1.0;
    if (b >= 7 && b - a >= 2) return 0.0;
    if (a >= 6 && b >= 6 && a === b) {
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

export function setDistribution(pa, pb, first = "A") {
  const holdA = gameHold(pa), holdB = gameHold(pb);
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

export function projectMatch(a, b, league, bestOf = 3, totalsLines = [20.5, 21.5, 22.5, 23.5]) {
  const [pa, pb] = pointProbs(a, b, league);
  const setsToWin = bestOf === 5 ? 3 : 2;
  const setEven = setDistribution(pa, pb, "A");
  const setOdd = setDistribution(pa, pb, "B");

  let state = new Map([["0,0,0,0", 1.0]]);
  const final = new Map();
  const addF = (k, v) => final.set(k, (final.get(k) || 0) + v);
  for (let si = 0; si < 2 * setsToWin - 1; si++) {
    const nxt = new Map();
    const base = si % 2 === 0 ? setEven : setOdd;
    for (const [k, prob] of state) {
      const [sa, sb, tg, anytb] = k.split(",").map(Number);
      if (sa === setsToWin || sb === setsToWin) { addF(k, prob); continue; }
      for (const [spr, ga, gb, tb] of base) {
        const aWon = ga > gb;
        const nsa = sa + (aWon ? 1 : 0), nsb = sb + (aWon ? 0 : 1);
        const nk = `${nsa},${nsb},${tg + ga + gb},${anytb || tb ? 1 : 0}`;
        nxt.set(nk, (nxt.get(nk) || 0) + prob * spr);
      }
    }
    state = nxt;
  }
  for (const [k, prob] of state) addF(k, prob);

  let winA = 0, anyTb = 0, etg = 0;
  const setScore = {}, gamesDist = {};
  for (const [k, pr] of final) {
    const [sa, sb, tg, anytb] = k.split(",").map(Number);
    if (sa > sb) winA += pr;
    const ss = `${sa}-${sb}`;
    setScore[ss] = (setScore[ss] || 0) + pr;
    gamesDist[tg] = (gamesDist[tg] || 0) + pr;
    etg += pr * tg;
    if (anytb) anyTb += pr;
  }
  const totals = {};
  for (const line of totalsLines) {
    let over = 0;
    for (const g in gamesDist) if (Number(g) > line) over += gamesDist[g];
    totals[line] = { over, under: 1 - over };
  }
  const spA = (etg / 2) * gameExpectedPoints(pa);
  const spB = (etg / 2) * gameExpectedPoints(pb);
  return {
    p_a_serve: pa, p_b_serve: pb,
    hold_a: gameHold(pa), hold_b: gameHold(pb),
    sr_win_a: winA, set_score: setScore,
    exp_total_games: etg, totals, tiebreak_prob: anyTb,
    exp_aces_a: a.ace_rate * spA, exp_aces_b: b.ace_rate * spB,
    exp_df_a: a.df_rate * spA, exp_df_b: b.df_rate * spB,
  };
}

export function prWinProb(prA, prB, scale = 130.0) {
  return 1.0 / (1.0 + Math.exp(-(prA - prB) / scale));
}

// Blend the Markov win prob with the points-rating anchor (mirrors evaluate.py).
export function blendedWinProb(a, b, league, bestOf, eloBlend = 0.55) {
  const m = projectMatch(a, b, league, bestOf);
  const anchor = prWinProb(a.pr, b.pr);
  return eloBlend * anchor + (1 - eloBlend) * m.sr_win_a;
}
