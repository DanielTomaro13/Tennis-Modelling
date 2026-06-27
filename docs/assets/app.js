// app.js — Grand Slam Tennis. NRL-style multi-page site.
import { projectMatch, blendedWinProb, projectDoubles, teamProfile, prWinProb } from "./sim.js";

/* ---------- helpers ---------- */
const fmtPct = (p) => (p * 100).toFixed(0) + "%";
const fmtOdds = (p) => (p && p > 0 ? (1 / p).toFixed(2) : "—");
const pctOdds = (p) => `${fmtPct(p)} · ${fmtOdds(p)}`;
const getJSON = (p) => fetch(p).then((r) => (r.ok ? r.json() : null)).catch(() => null);
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") e[k] = v;
    else e.setAttribute(k, v);
  }
  kids.flat().forEach((c) => e.append(c?.nodeType ? c : document.createTextNode(c ?? "")));
  return e;
}
function fmtDate(d) { return (!d || d.length < 8) ? (d || "") : `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`; }
function miniBar(p) { const b = el("div", { class: "bar" }); const s = el("span"); s.style.width = (p*100).toFixed(1)+"%"; b.append(s); return b; }
const TOUR_LABEL = { atp: "ATP", wta: "WTA" };

const ROUND_ORDER = {
  "Qualifying": 0, "Qualifying Round 1": 0, "Qualifying Round 2": 1, "Qualifying Round 3": 2,
  "Round 1": 3, "Round 2": 4, "Round 3": 5, "Round of 16": 6, "Round 16": 6,
  "Quarterfinal": 7, "Quarterfinals": 7, "Semifinal": 8, "Semifinals": 8, "Final": 9,
};
const roundOrder = (r) => ROUND_ORDER[r] ?? 50;

function filterSelect(label, key, values, state, onChange) {
  const sel = el("select", {}, el("option", { value: "all" }, `${label}: all`),
    ...values.map((v) => el("option", { value: v }, v)));
  sel.value = state[key];
  sel.onchange = () => { state[key] = sel.value; onChange(); };
  return sel;
}
function tourTabs(state, counts, onChange) {
  const tabs = el("div", { class: "tabs" });
  ["all", "atp", "wta"].forEach((t) => {
    const b = el("button", { class: t === state.tour ? "on" : "", "data-t": t }, `${t.toUpperCase()} (${counts[t] ?? 0})`);
    b.onclick = () => { state.tour = t; [...tabs.children].forEach((c) => c.classList.toggle("on", c.dataset.t === t)); onChange(); };
    tabs.append(b);
  });
  return tabs;
}

/* ===========================================================
   MATCHES (index)
   =========================================================== */
async function renderMatches() {
  const [data, meta] = await Promise.all([getJSON("data/predictions.json"), getJSON("data/meta.json")]);
  const fr = document.getElementById("freshness");
  if (meta && fr) {
    let t = `Updated ${meta.generated} · rebuilt every 3 hours`;
    const atp = (meta.backtest || []).find((b) => b.tour === "atp");
    if (atp?.n) t += ` · ATP backtest log-loss ${atp.log_loss}, ${(atp.accuracy*100).toFixed(0)}% accuracy`;
    fr.textContent = t;
  }
  const wrap = document.getElementById("content");
  if (!data || !data.fixtures.length) { wrap.append(el("p", { class: "muted" }, "No matches resolved yet — check back after the next rebuild.")); return; }
  const fx = data.fixtures;
  const state = { tour: "all", tournament: "all", round: "all", surface: "all", format: "all" };
  const counts = { all: fx.length, atp: fx.filter(f=>f.tour==="atp").length, wta: fx.filter(f=>f.tour==="wta").length };

  const uniq = (k) => [...new Set(fx.map((f) => f[k]).filter(Boolean))];
  const tournaments = uniq("tournament").sort((a, b) => fx.filter(f=>f.tournament===b).length - fx.filter(f=>f.tournament===a).length);
  const rounds = uniq("round").sort((a, b) => roundOrder(a) - roundOrder(b));
  const surfaces = uniq("surface").sort();
  const formats = uniq("format").sort();

  const filters = el("div", { class: "filters" },
    filterSelect("Tournament", "tournament", tournaments, state, draw),
    filterSelect("Round", "round", rounds, state, draw),
    filterSelect("Surface", "surface", surfaces, state, draw),
    formats.length > 1 ? filterSelect("Format", "format", formats, state, draw) : "",
    el("span", { class: "count", id: "matchcount" }, ""));
  const results = el("div", { id: "results" });
  wrap.append(tourTabs(state, counts, draw), filters, results);

  const passes = (f) => (state.tour==="all"||f.tour===state.tour) && (state.tournament==="all"||f.tournament===state.tournament)
    && (state.round==="all"||f.round===state.round) && (state.surface==="all"||f.surface===state.surface)
    && (state.format==="all"||(f.format||"singles")===state.format);

  function row(f) {
    const aFav = f.win_prob_1 >= f.win_prob_2;
    const nm = (name, p, fav) => el("div", { class: fav ? "fav" : "" }, el("b", {}, name), " ", el("span", { class: "mut" }, fmtPct(p)));
    const aces = f.exp_aces_1 != null ? `${f.exp_aces_1} / ${f.exp_aces_2}` : "—";
    const tr = el("tr", { class: "click" },
      el("td", { class: "pl" }, nm(f.player1, f.win_prob_1, aFav), nm(f.player2, f.win_prob_2, !aFav)),
      el("td", { class: "mut" }, f.round || ""),
      el("td", {}, el("span", { class: "pill surf-" + f.surface }, f.surface)),
      el("td", {}, miniBar(Math.max(f.win_prob_1, f.win_prob_2))),
      el("td", { class: "num" }, `${f.fair_odds_1} / ${f.fair_odds_2}`),
      el("td", { class: "num" }, f.exp_total_games),
      el("td", { class: "num" }, fmtPct(f.tiebreak_prob)),
      el("td", { class: "num mut" }, aces));
    if (f.markets) tr.onclick = () => openDetail(f);
    return tr;
  }

  function draw() {
    const rows = fx.filter(passes);
    document.getElementById("matchcount").textContent = `${rows.length} match${rows.length === 1 ? "" : "es"}`;
    if (!rows.length) { results.replaceChildren(el("p", { class: "muted" }, "No matches for these filters.")); return; }
    const groups = new Map();
    rows.forEach((f) => { if (!groups.has(f.tournament)) groups.set(f.tournament, []); groups.get(f.tournament).push(f); });
    const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
    results.replaceChildren(...ordered.flatMap(([name, items]) => {
      items.sort((a, b) => (roundOrder(a.round) - roundOrder(b.round)) || (Math.max(b.win_prob_1,b.win_prob_2) - Math.max(a.win_prob_1,a.win_prob_2)));
      const tours = [...new Set(items.map((i) => TOUR_LABEL[i.tour]))].join(" + ");
      const head = el("div", { class: "group-head" }, el("h2", {}, name),
        el("span", { class: "muted" }, `${tours} · ${items.length} match${items.length===1?"":"es"}`));
      const table = el("table", {},
        el("thead", {}, el("tr", {},
          el("th", { class: "pl" }, "Match"), el("th", {}, "Round"), el("th", {}, "Surface"),
          el("th", {}, "Win prob"), el("th", {}, "Fair odds"), el("th", {}, "Games"),
          el("th", {}, "TB%"), el("th", {}, "Aces"))),
        el("tbody", {}, ...items.map(row)));
      return [head, el("div", { class: "match" }, el("div", { class: "tablewrap" }, table))];
    }));
  }
  draw();
}

/* ===========================================================
   RANKINGS
   =========================================================== */
async function renderRankings() {
  const boards = await getJSON("data/ratings.json");
  const wrap = document.getElementById("content");
  if (!boards) { wrap.append(el("p", { class: "muted" }, "Ratings unavailable.")); return; }
  const state = { tour: "atp", scope: "overall" };
  const scopeSel = el("select", {}, ...["overall", "Hard", "Clay", "Grass"].map((s) => el("option", { value: s }, s === "overall" ? "All surfaces" : s)));
  scopeSel.onchange = () => { state.scope = scopeSel.value; draw(); };
  const filters = el("div", { class: "filters" }, scopeSel, el("span", { class: "count", id: "rc" }, ""));
  const tabs = tourTabs(state, { all: 0, atp: (boards.atp?.overall||[]).length, wta: (boards.wta?.overall||[]).length }, draw);
  // remove the "all" tab for rankings
  tabs.querySelector('[data-t="all"]').remove();
  if (state.tour === "atp") tabs.querySelector('[data-t="atp"]').classList.add("on");
  const box = el("div", { class: "scrolltable" });
  wrap.append(tabs, filters, box);

  function draw() {
    const rows = (boards[state.tour] && boards[state.tour][state.scope]) || [];
    document.getElementById("rc").textContent = `${rows.length} players`;
    const table = el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "#"), el("th", { class: "pl" }, "Player"), el("th", {}, "Rating"),
        el("th", {}, "Serve W%"), el("th", {}, "Return W%"), el("th", {}, "Ace%"), el("th", {}, "DF%"))),
      el("tbody", {}, ...rows.slice(0, 200).map((r) => el("tr", {},
        el("td", { class: "mut" }, r.rank),
        el("td", { class: "pl" }, el("b", {}, r.name)),
        el("td", { class: "num pos" }, r.pr.toFixed(1)),
        el("td", { class: "num" }, fmtPct(r.spw)),
        el("td", { class: "num" }, fmtPct(r.rpw)),
        el("td", { class: "num mut" }, fmtPct(r.ace_rate)),
        el("td", { class: "num mut" }, fmtPct(r.df_rate))))));
    box.replaceChildren(table);
  }
  draw();
}

/* ===========================================================
   ANALYSIS
   =========================================================== */
async function renderAnalysis() {
  const boards = await getJSON("data/ratings.json");
  const wrap = document.getElementById("content");
  if (!boards) { wrap.append(el("p", { class: "muted" }, "Data unavailable.")); return; }
  const state = { tour: "atp" };
  const tabs = tourTabs(state, { atp: 0, wta: 0 }, draw);
  tabs.querySelector('[data-t="all"]').remove();
  tabs.querySelector('[data-t="atp"]').classList.add("on");
  [...tabs.children].forEach((b) => b.textContent = b.dataset.t.toUpperCase());
  const grid = el("div", {});
  wrap.append(tabs, grid);

  const leaderTable = (rows, valFn, valHead) => el("table", {},
    el("thead", {}, el("tr", {}, el("th", { class: "pl" }, "Player"), el("th", {}, valHead))),
    el("tbody", {}, ...rows.map((r) => el("tr", {}, el("td", { class: "pl" }, el("b", {}, r.name)), el("td", { class: "num pos" }, valFn(r))))));

  function topBy(scope, key, n = 10, desc = true) {
    const rows = [...(boards[state.tour]?.[scope] || [])];
    rows.sort((a, b) => desc ? b[key] - a[key] : a[key] - b[key]);
    return rows.slice(0, n);
  }
  function panel(title, tag, rows, valFn, valHead) {
    return el("div", { class: "subcard" }, el("h4", {}, title), leaderTable(rows, valFn, valHead));
  }

  function draw() {
    grid.replaceChildren(
      el("div", { class: "grid3" },
        panel("Best servers", "", topBy("overall", "spw"), (r) => fmtPct(r.spw), "Serve W%"),
        panel("Best returners", "", topBy("overall", "rpw"), (r) => fmtPct(r.rpw), "Return W%"),
        panel("Biggest aces", "", topBy("overall", "ace_rate"), (r) => fmtPct(r.ace_rate), "Ace%")),
      el("div", { style: "height:16px" }),
      el("div", { class: "grid3" },
        panel("Clay specialists", "", topBy("Clay", "pr"), (r) => r.pr.toFixed(1), "Clay PR"),
        panel("Grass specialists", "", topBy("Grass", "pr"), (r) => r.pr.toFixed(1), "Grass PR"),
        panel("Most double faults", "", topBy("overall", "df_rate"), (r) => fmtPct(r.df_rate), "DF%")));
  }
  draw();
}

/* ===========================================================
   BACKTEST
   =========================================================== */
async function renderBacktest() {
  const meta = await getJSON("data/meta.json");
  const wrap = document.getElementById("content");
  const bt = meta?.backtest || [];
  if (!bt.length) { wrap.append(el("p", { class: "muted" }, "Backtest unavailable.")); return; }
  const kpi = (b) => el("div", { class: "subcard" }, el("h4", {}, `${TOUR_LABEL[b.tour]} — ${b.n} held-out matches`),
    el("div", { class: "kpis" },
      el("div", { class: "kpi pos" }, el("b", {}, b.log_loss), el("i", {}, "Log-loss")),
      el("div", { class: "kpi" }, el("b", {}, b.brier), el("i", {}, "Brier")),
      el("div", { class: "kpi" }, el("b", {}, fmtPct(b.accuracy)), el("i", {}, "Accuracy")),
      el("div", { class: "kpi" }, el("b", {}, fmtPct(b.baseline_accuracy)), el("i", {}, "Rating baseline"))));
  wrap.append(
    el("div", { class: "panel" }, el("h3", {}, "Held-out accuracy ", el("span", { class: "tag" }, "season holdout")),
      el("p", { class: "lead" }, "Profiles are built only from matches before the holdout season, then scored on it — no leakage."),
      el("div", { class: "grid2" }, ...bt.map(kpi))),
    el("div", { class: "panel prose" },
      el("h3", {}, "How the model works"),
      el("p", { html: "Every player gets a recency-weighted, opponent-adjusted <b>serve</b> and <b>return</b> profile per surface. Those feed a hierarchical point&rarr;game&rarr;set&rarr;match engine that prices every market analytically, anchored to a points-rating win probability." }),
      el("p", { html: "Lower <b>log-loss</b> and <b>Brier</b> mean sharper, better-calibrated probabilities. <b>Accuracy</b> is the share of matches where the model's favourite won — close to the rating baseline because both pick the same favourite, so log-loss is the truer measure of quality." })));
}

/* ===========================================================
   MODEL LAB (predictor)
   =========================================================== */
async function renderLab() {
  const profiles = await getJSON("data/profiles.json");
  const wrap = document.getElementById("content");
  if (!profiles) { wrap.append(el("p", { class: "muted" }, "Profiles unavailable.")); return; }
  let tour = "atp", format = "singles";
  const tourSel = el("select", {}, ...["atp", "wta"].map((t) => el("option", { value: t }, t.toUpperCase())));
  const formatSel = el("select", {}, el("option", { value: "singles" }, "Singles"), el("option", { value: "doubles" }, "Doubles"));
  const surfSel = el("select", {}, ...["Hard", "Clay", "Grass"].map((s) => el("option", { value: s }, s)));
  const boSel = el("select", {}, el("option", { value: "3" }, "Best of 3"), el("option", { value: "5" }, "Best of 5"));
  const go = el("button", { class: "go" }, "Project match");
  const sels = [el("select", {}), el("select", {}), el("select", {}), el("select", {})];

  function fillPlayers() {
    const names = Object.keys(profiles[tour].players).sort();
    sels.forEach((s, i) => { s.replaceChildren(...names.map((n) => el("option", { value: n }, n))); s.selectedIndex = Math.min(i, names.length - 1); });
  }
  const pickWrap = el("div", {});
  const boLabel = el("label", {}, "Match length", boSel);
  function layout() {
    boLabel.style.display = format === "singles" ? "" : "none";
    if (format === "doubles") {
      pickWrap.replaceChildren(
        el("div", { class: "team-box" }, el("small", {}, "Team 1"), sels[0], sels[1]),
        el("div", { class: "team-box" }, el("small", {}, "Team 2"), sels[2], sels[3]));
    } else {
      pickWrap.replaceChildren(
        el("label", {}, "Player 1", sels[0]), el("label", {}, "Player 2", sels[1]));
    }
  }
  tourSel.onchange = () => { tour = tourSel.value; fillPlayers(); };
  formatSel.onchange = () => { format = formatSel.value; layout(); };
  fillPlayers(); layout();

  const controls = el("div", { class: "controls panel" },
    el("label", {}, "Tour", tourSel), el("label", {}, "Format", formatSel),
    el("label", {}, "Surface", surfSel), boLabel,
    pickWrap, go);
  const out = el("div", { id: "labout" });
  wrap.append(el("div", { class: "lab" }, controls, out));
  const scopeOf = (prof, s) => prof[s] || prof.overall;
  const P = (n) => profiles[tour].players[n];

  go.onclick = () => {
    const league = profiles[tour].league, surface = surfSel.value;
    if (format === "doubles") {
      const ns = sels.map((s) => s.value);
      if (new Set(ns).size < 4) { out.replaceChildren(el("p", { class: "proxy-note" }, "Pick four different players.")); return; }
      const ta = teamProfile(scopeOf(P(ns[0]), surface), scopeOf(P(ns[1]), surface));
      const tb = teamProfile(scopeOf(P(ns[2]), surface), scopeOf(P(ns[3]), surface));
      const m = projectDoubles(ta, tb, league);
      const winA = 0.5 * prWinProb(ta.pr, tb.pr) + 0.5 * m.sr_win_a;
      const t1 = `${ns[0]} / ${ns[1]}`, t2 = `${ns[2]} / ${ns[3]}`;
      out.replaceChildren(
        el("p", { class: "proxy-note" }, "Doubles is modelled from each player's singles serve/return form as a proxy, with no-ad scoring and a 10-point match tie-break deciding set."),
        el("div", { class: "card" }, detailHead(t1, t2, winA, `${surface} · Doubles`)),
        el("div", { style: "height:16px" }), doublesGrid(m, t1, t2, winA));
      return;
    }
    const n1 = sels[0].value, n2 = sels[1].value;
    if (n1 === n2) { out.replaceChildren(el("p", { class: "proxy-note" }, "Pick two different players.")); return; }
    const bestOf = Number(boSel.value);
    const a = { ...scopeOf(P(n1), surface), name: n1 }, b = { ...scopeOf(P(n2), surface), name: n2 };
    const m = projectMatch(a, b, league, bestOf);
    const winA = blendedWinProb(a, b, league, bestOf);
    out.replaceChildren(el("div", { class: "card" }, detailHead(n1, n2, winA, `${surface} · Bo${bestOf}`)),
      el("div", { style: "height:16px" }), marketGrid(m, n1, n2, winA));
  };
  go.click();
}

/* ===========================================================
   COMPARE (placeholder)
   =========================================================== */
function renderCompare() {
  const wrap = document.getElementById("content");
  wrap.append(el("div", { class: "panel prose" },
    el("h3", {}, "Odds comparison ", el("span", { class: "tag" }, "coming soon")),
    el("p", { html: "Next up: pull live bookmaker prices for each market and flag where the model's fair price beats the market — value edges and expected value, the same way the AFL/NRL dashboards do." }),
    el("p", { class: "muted" }, "Until then, every market on the site already shows the model's fair decimal price.")));
}

/* ===========================================================
   Shared: detail modal + market grids
   =========================================================== */
function mktCard(title, rows) {
  return el("div", { class: "mkt" }, el("h3", {}, title),
    ...rows.map(([k, v]) => el("div", { class: "row" }, el("span", { class: "mut" }, k), el("b", {}, v))));
}
function probBarWide(p) { const b = el("div", { class: "prob-bar" }); const s = el("span"); s.style.width = (p*100).toFixed(1)+"%"; b.append(s); return b; }
function detailHead(n1, n2, winA, subtitle) {
  const winB = 1 - winA;
  return el("div", {},
    el("div", { class: "result-head" },
      el("div", {}, el("div", { class: "big " + (winA>=winB?"fav":"") }, fmtPct(winA)), el("div", { class: "mut" }, `${n1} · fair ${fmtOdds(winA)}`)),
      el("div", { class: "mut", style: "text-align:center" }, subtitle),
      el("div", { style: "text-align:right" }, el("div", { class: "big " + (winB>winA?"fav":"") }, fmtPct(winB)), el("div", { class: "mut" }, `${n2} · fair ${fmtOdds(winB)}`))),
    el("div", { class: "result-head" }, probBarWide(winA)));
}
const ouRows = (dist, label) => Object.entries(dist).map(([line, o]) => [`${label} ${line}`, pctOdds(o.over)]);
const probRows = (dist, fn) => Object.entries(dist).map(([line, p]) => [fn(line), pctOdds(p)]);
const acesRows = (exp, dist) => [["Expected", exp.toFixed(1)], ...probRows(dist, (l) => `Over ${l}`)];

function marketGrid(m, n1, n2, winA) {
  const winB = 1 - winA;
  const ss = Object.entries(m.set_score || {}).sort((a, b) => b[1]-a[1]).map(([k, v]) => [k, pctOdds(v)]);
  const cards = [
    mktCard("Match winner", [[n1, pctOdds(winA)], [n2, pctOdds(winB)]]),
    mktCard("Sets", [["Straight sets", pctOdds(m.straight_sets)], ["Deciding set", pctOdds(m.deciding_set)],
      [`${n1} to win a set`, pctOdds(m.a_wins_set)], [`${n2} to win a set`, pctOdds(m.b_wins_set)]]),
    mktCard("1st set winner", [[n1, pctOdds(m.set1_win_a)], [n2, pctOdds(1 - m.set1_win_a)]]),
    mktCard("2nd set winner", [[n1, pctOdds(m.set2_win_a)], [n2, pctOdds(1 - m.set2_win_a)]]),
    mktCard("Correct set score", ss),
    mktCard("Total games", ouRows(m.totals, "Over")),
    mktCard("Games handicap", probRows(m.handicap, (l) => `${n1} ${l}`)),
    mktCard(`${n1} total games`, ouRows(m.player_games_a, "Over")),
    mktCard(`${n2} total games`, ouRows(m.player_games_b, "Over")),
    mktCard("Tie-break in match", [["At least one", pctOdds(m.tiebreak_prob)]]),
    m.exp_breaks_a !== undefined ? mktCard("Breaks of serve", [[`Expected ${n1}`, m.exp_breaks_a.toFixed(1)], [`Expected ${n2}`, m.exp_breaks_b.toFixed(1)], ["Total expected", m.exp_total_breaks.toFixed(1)]]) : "",
    m.breaks_ou ? mktCard("Total breaks", probRows(m.breaks_ou, (l) => `Over ${l}`)) : "",
    m.most_breaks ? mktCard("Most breaks", [[n1, pctOdds(m.most_breaks.a)], ["Tie", pctOdds(m.most_breaks.tie)], [n2, pctOdds(m.most_breaks.b)]]) : "",
    m.break_at_least_a !== undefined ? mktCard("To break serve (1+)", [[n1, pctOdds(m.break_at_least_a)], [n2, pctOdds(m.break_at_least_b)]]) : "",
    m.hold_all_a !== undefined ? mktCard("To hold throughout", [[n1, pctOdds(m.hold_all_a)], [n2, pctOdds(m.hold_all_b)]]) : "",
    mktCard(`Aces — ${n1}`, acesRows(m.exp_aces_a, m.aces_ou_a)),
    mktCard(`Aces — ${n2}`, acesRows(m.exp_aces_b, m.aces_ou_b)),
    mktCard(`Double faults — ${n1}`, acesRows(m.exp_df_a, m.df_ou_a)),
    mktCard(`Double faults — ${n2}`, acesRows(m.exp_df_b, m.df_ou_b)),
    m.most_aces ? mktCard("Most aces", [[n1, pctOdds(m.most_aces.a)], ["Tie", pctOdds(m.most_aces.tie)], [n2, pctOdds(m.most_aces.b)]]) : "",
    m.most_df ? mktCard("Most double faults", [[n1, pctOdds(m.most_df.a)], ["Tie", pctOdds(m.most_df.tie)], [n2, pctOdds(m.most_df.b)]]) : "",
  ].filter(Boolean);
  return el("div", { class: "markets-grid" }, ...cards);
}

function doublesGrid(m, t1, t2, winA) {
  const winB = 1 - winA;
  const ss = Object.entries(m.set_score).sort((a, b) => b[1]-a[1]).map(([k, v]) => [k, pctOdds(v)]);
  return el("div", { class: "markets-grid" },
    mktCard("Match winner", [[t1, pctOdds(winA)], [t2, pctOdds(winB)]]),
    mktCard("Set betting", ss),
    mktCard("Sets", [["Straight sets", pctOdds(m.straight_sets)], ["Match tie-break (deciding set)", pctOdds(m.deciding_set)],
      [`${t1} to win a set`, pctOdds(m.a_wins_set)], [`${t2} to win a set`, pctOdds(m.b_wins_set)]]),
    mktCard("1st set winner", [[t1, pctOdds(m.set1_win_a)], [t2, pctOdds(1 - m.set1_win_a)]]),
    mktCard("2nd set winner", [[t1, pctOdds(m.set2_win_a)], [t2, pctOdds(1 - m.set2_win_a)]]),
    mktCard("Match shape", [["Expected total games", m.exp_total_games.toFixed(1)], ["Tie-break in a set", pctOdds(m.tiebreak_prob)],
      [`${t1} hold %`, fmtPct(m.hold_a)], [`${t2} hold %`, fmtPct(m.hold_b)]]));
}

function openDetail(f) {
  const isD = f.format === "doubles";
  const sub = [f.surface, isD ? "Doubles" : `Bo${f.best_of}`, f.round].filter(Boolean).join(" · ");
  const grid = isD ? doublesGrid(f.markets, f.player1, f.player2, f.win_prob_1) : marketGrid(f.markets, f.player1, f.player2, f.win_prob_1);
  const body = el("div", {},
    el("div", { class: "modal-evt" }, el("div", {}, f.tournament || ""), el("div", { class: "mut" }, [f.round, f.date ? fmtDate(f.date) : ""].filter(Boolean).join(" · "))),
    el("div", { class: "card" }, detailHead(f.player1, f.player2, f.win_prob_1, sub)),
    el("div", { style: "height:16px" }), grid);
  const close = el("button", { class: "modal-close" }, "✕");
  const overlay = el("div", { class: "modal-overlay" }, el("div", { class: "modal" }, close, body));
  const dismiss = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") dismiss(); };
  overlay.onclick = (e) => { if (e.target === overlay) dismiss(); };
  close.onclick = dismiss;
  document.addEventListener("keydown", onKey);
  document.body.append(overlay);
}

/* ---------- router ---------- */
const page = document.body.dataset.page;
({ matches: renderMatches, rankings: renderRankings, analysis: renderAnalysis,
   backtest: renderBacktest, lab: renderLab, compare: renderCompare }[page] || (() => {}))();
