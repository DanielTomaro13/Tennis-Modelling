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

const NAV = [
  ["home", "Home", "index.html"], ["matches", "Matches", "matches.html"],
  ["schedule", "Schedule", "schedule.html"], ["rankings", "Rankings", "rankings.html"],
  ["analysis", "Analysis", "analysis.html"], ["compare", "Compare", "compare.html"],
  ["value", "Value", "value.html"], ["pickem", "Pick'em", "pickem.html"],
  ["games", "Games", "games.html"], ["lab", "Model Lab", "lab.html"],
  ["backtest", "Backtest", "backtest.html"],
];
// "The 0 Series" — cross-links to the sister sites. Tennis is the active one here.
const SISTER_SITES = [
  ["AFL 23-0", "https://afl23-0.com"],
  ["NRL 24-0", "https://nrl24-0.com"],
  ["NBA 82-0", "https://nba82-0.com"],
  ["MLB 162-0", "https://mlb162-0.com"],
  ["Football Invincibles", "https://footballinvincibles.com"],
  ["F1 Slam", "https://f1slam.com"],
  ["Tennis Slam", null],
];
function sisterBar() {
  return el("div", { class: "sister-bar", role: "navigation", "aria-label": "Sister sites" },
    el("span", { class: "lead" }, "THE 0 SERIES ·"),
    ...SISTER_SITES.map(([label, href]) => href
      ? el("a", { class: "sister-link", href }, label)
      : el("span", { class: "sister-link", "data-active": "true", "aria-current": "page" }, label)));
}
const FOOT_LINKS = [
  ["How it works", "about.html"], ["Contact", "contact.html"],
  ["Privacy", "privacy.html"], ["Terms", "terms.html"],
];

// Google AdSense. The loader <script> lives in each page's <head>.
// Once the site is approved, paste real ad-unit slot IDs below — until then
// every slot is empty, so nothing renders (no blank boxes, no layout shift).
// Leaving the loader in place also lets you turn on Auto ads with zero code.
const AD_CLIENT = "ca-pub-2087141992057731";
const AD_SLOTS = { top: "", bottom: "" };
function adUnit(slot) {
  if (!slot) return null;
  const box = el("div", { class: "adbox" },
    el("div", { class: "adlbl" }, "Advertisement"),
    el("ins", { class: "adsbygoogle", style: "display:block",
      "data-ad-client": AD_CLIENT, "data-ad-slot": slot,
      "data-ad-format": "auto", "data-full-width-responsive": "true" }));
  return box;
}
function mountAd(box, where) {
  if (!box) return;
  where(box);
  try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch (e) {}
}
function chrome(page) {
  const strip = sisterBar();
  const header = el("header", {}, el("div", { class: "wrap" },
    el("a", { class: "brand", href: "index.html" }, el("img", { class: "ball", src: "assets/ball.svg", alt: "", "aria-hidden": "true" }), el("span", { class: "bt" }, "Grand Slam "), el("span", {}, "Tennis")),
    el("nav", {}, ...NAV.map(([id, label, href]) => el("a", { class: id === page ? "on" : "", href }, label)))));
  const footer = el("footer", {}, el("div", { class: "wrap" },
    el("nav", { class: "foot-links" }, ...FOOT_LINKS.flatMap(([label, href], i) =>
      [i ? el("span", { class: "sep" }, "·") : "", el("a", { href }, label)])),
    el("p", { html: 'Modelled from the <a href="https://github.com/JeffSackmann/tennis_MatchChartingProject">Match Charting Project</a>; fixtures via <a href="https://www.espn.com.au/tennis/schedule">ESPN</a> &amp; tennis.com.' }),
    el("p", {}, "For research and entertainment only — not betting advice."),
    el("p", { class: "series" }, "Part of the 0 Series · ",
      ...SISTER_SITES.filter(([, href]) => href).flatMap(([label, href], i) =>
        [i ? " · " : "", el("a", { href }, label)])),
    el("a", { class: "kofi", href: "https://ko-fi.com/danieltomaro", target: "_blank", rel: "noopener" }, "☕ Support on Ko-fi")));
  document.getElementById("app-header")?.replaceWith(strip, header);
  document.getElementById("app-footer")?.replaceWith(footer);

  const main = document.querySelector("main");
  const content = document.getElementById("content");
  if (content) mountAd(adUnit(AD_SLOTS.top), (b) => content.before(b));
  if (main) mountAd(adUnit(AD_SLOTS.bottom), (b) => main.append(b));
}

const playerLink = (tour, name) => el("a", { class: "plink", href: `player.html?tour=${tour}&name=${encodeURIComponent(name)}` }, name);
function record(rec) { return rec ? `${rec[0]}–${rec[1]}` : "—"; }

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
  const presetT = new URLSearchParams(location.search).get("t");
  const state = { tour: "all", tournament: presetT && fx.some((f) => f.tournament === presetT) ? presetT : "all", round: "all", surface: "all", format: "all" };
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
    const isD = f.format === "doubles";
    const nm = (name, p, fav) => {
      const label = isD ? el("b", {}, name) : (() => { const a = playerLink(f.tour, name); a.onclick = (e) => e.stopPropagation(); return el("b", {}, a); })();
      return el("div", { class: fav ? "fav" : "" }, label, " ", el("span", { class: "mut" }, fmtPct(p)));
    };
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
        el("td", { class: "pl" }, playerLink(state.tour, r.name)),
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
    el("tbody", {}, ...rows.map((r) => el("tr", {}, el("td", { class: "pl" }, playerLink(state.tour, r.name)), el("td", { class: "num pos" }, valFn(r))))));

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
const BOOK_LABEL = { sportsbet: "Sportsbet", ladbrokes: "Ladbrokes", pointsbet: "PointsBet", dabble: "Dabble", tab: "TAB" };

function oddsEmpty(wrap, what) {
  wrap.append(el("div", { class: "panel prose" },
    el("h3", {}, what, " ", el("span", { class: "tag" }, "no live prices")),
    el("p", {}, "Prices aren't available right now — bookmaker markets open closer to each match. Check back soon."),
    el("p", { class: "muted" }, "Every match still shows the model's fair price on the Matches page.")));
}

const pairKey = (tour, a, b) => `${tour}|${[a.toLowerCase(), b.toLowerCase()].sort().join("~")}`;

// flatten odds.json -> one row per priced selection (carry players for the model modal)
function oddsRows(data) {
  const rows = [];
  (data.matches || []).forEach((m) => (m.markets || []).forEach((mk) => mk.selections.forEach((s) =>
    rows.push({ tour: m.tour, tournament: m.tournament, surface: m.surface, round: m.round,
      p1: m.player1, p2: m.player2, match: `${m.player1} v ${m.player2}`, market: mk.label, marketKey: mk.key,
      sel: s.label, model: s.model, fair: s.fair, books: s.books, best: s.best, ev: s.ev, edge: s.edge }))));
  return rows;
}

// index predictions fixtures so an odds row can open the full model
async function fixtureIndex() {
  const preds = await getJSON("data/predictions.json");
  const idx = new Map();
  ((preds && preds.fixtures) || []).forEach((f) => idx.set(pairKey(f.tour, f.player1, f.player2), f));
  return idx;
}

function sortHeader(label, key, getter, state, redraw, cls) {
  const arrow = state.sort === key ? (state.dir > 0 ? " ▲" : " ▼") : "";
  const th = el("th", { class: (cls || "") + " so" }, label + arrow);
  th.onclick = () => { if (state.sort === key) state.dir = -state.dir; else { state.sort = key; state.dir = 1; } state._get = getter; redraw(); };
  return th;
}
function applySort(rows, state) {
  if (!state.sort || !state._get) return rows;
  const g = state._get, d = state.dir;
  return [...rows].sort((a, b) => {
    const va = g(a), vb = g(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1; if (vb == null) return -1;
    return (va > vb ? 1 : va < vb ? -1 : 0) * d;
  });
}

/* ===========================================================
   COMPARE — model fair vs every book, across all markets
   =========================================================== */
async function renderCompare() {
  const [data, fxIdx] = await Promise.all([getJSON("data/odds.json"), fixtureIndex()]);
  const wrap = document.getElementById("content");
  if (!data || !data.matches.length) { oddsEmpty(wrap, "Compare odds"); return; }
  const books = data.books;
  const rows = oddsRows(data);
  const markets = [...new Set(rows.map((r) => r.market))];
  const uniq = (k) => [...new Set(rows.map((r) => r[k]).filter(Boolean))].sort();
  const tcounts = { all: data.matches.length, atp: data.matches.filter(m => m.tour === "atp").length, wta: data.matches.filter(m => m.tour === "wta").length };
  const state = { tour: "all", market: markets[0], tournament: "all", round: "all", surface: "all", view: "all", sort: "edge", dir: -1, _get: (r) => r.edge };

  wrap.append(el("p", { class: "muted", style: "margin:-4px 0 10px" },
    `Model fair price vs ${books.map((b) => BOOK_LABEL[b]).join(", ")} across ${markets.length} markets. Green = the book pays over the model's fair price. Tap a row for the full model. Sort by any column. Updated ${data.generated}.`));
  const filters = el("div", { class: "filters" },
    filterSelect("Market", "market", markets, state, draw),
    filterSelect("Tournament", "tournament", uniq("tournament"), state, draw),
    filterSelect("Round", "round", uniq("round"), state, draw),
    filterSelect("Surface", "surface", uniq("surface"), state, draw),
    filterSelect("View", "view", ["all", "value only"], state, draw),
    el("span", { class: "count", id: "cc" }, ""));
  const tabs = tourTabs(state, tcounts, draw);
  const box = el("div", { class: "scrolltable" });
  wrap.append(tabs, filters, box);

  function draw() {
    let sel = rows.filter((r) => r.market === state.market
      && (state.tour === "all" || r.tour === state.tour)
      && (state.tournament === "all" || r.tournament === state.tournament)
      && (state.round === "all" || r.round === state.round)
      && (state.surface === "all" || r.surface === state.surface)
      && (state.view === "all" || r.edge > 0));
    sel = applySort(sel, state);
    document.getElementById("cc").textContent = `${sel.length} selections`;
    const head = el("tr", {}, el("th", { class: "pl" }, "Match"), el("th", { class: "pl" }, "Selection"),
      sortHeader("Model fair", "fair", (r) => r.fair, state, draw));
    books.forEach((b) => head.append(sortHeader(BOOK_LABEL[b], b, (r) => r.books[b], state, draw)));
    head.append(sortHeader("Best", "best", (r) => r.best && r.best.price, state, draw),
      sortHeader("Edge", "edge", (r) => r.edge, state, draw));
    const body = sel.map((r) => {
      const fx = fxIdx.get(pairKey(r.tour, r.p1, r.p2));
      const tr = el("tr", { class: fx && fx.markets ? "click" : "" },
        el("td", { class: "pl mut" }, r.match), el("td", { class: "pl" }, r.sel), el("td", { class: "num" }, r.fair));
      books.forEach((b) => {
        const pr = r.books[b];
        tr.append(el("td", { class: "num" + (pr && pr > r.fair ? " pos" : "") }, pr ? pr.toFixed(2) : "—"));
      });
      tr.append(el("td", { class: "num" }, r.best && r.best.price ? `${r.best.price.toFixed(2)} ${BOOK_LABEL[r.best.book].slice(0, 3)}` : "—"),
        el("td", { class: "num" + (r.edge > 0 ? " pos" : " mut") }, fmtPct(r.edge)));
      if (fx && fx.markets) tr.onclick = () => openDetail(fx);
      return tr;
    });
    box.replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, ...body)));
  }
  draw();
}

/* ===========================================================
   VALUE — positive-edge selections across all markets
   =========================================================== */
async function renderValue() {
  const [data, fxIdx] = await Promise.all([getJSON("data/odds.json"), fixtureIndex()]);
  const wrap = document.getElementById("content");
  if (!data || !data.matches.length) { oddsEmpty(wrap, "Value"); return; }
  const rows = oddsRows(data).filter((r) => r.edge > 0 && r.best && r.best.price);
  const markets = ["all", ...new Set(rows.map((r) => r.market))];
  const tcounts = { all: data.matches.length, atp: data.matches.filter(m => m.tour === "atp").length, wta: data.matches.filter(m => m.tour === "wta").length };
  const state = { tour: "all", market: "all", book: "all", sort: "edge", dir: -1, _get: (r) => r.edge };

  wrap.append(el("p", { class: "muted", style: "margin:-4px 0 10px" },
    `Selections where the best book price beats the model's fair price, any market. Tap a row for the full model. Updated ${data.generated}.`));
  wrap.append(el("div", { class: "disclaim" },
    "Heads-up: the biggest edges are usually heavy underdogs or longshot markets where the model is simply less extreme than the market, not genuine value. The model is well-calibrated overall (see Backtest) but noisier on long prices — treat large EVs as model-vs-market disagreement, not betting tips."));
  const filters = el("div", { class: "filters" },
    filterSelect("Market", "market", markets, state, draw),
    filterSelect("Best book", "book", ["all", ...data.books.map((b) => BOOK_LABEL[b])], state, draw),
    el("span", { class: "count", id: "vc" }, ""));
  const tabs = tourTabs(state, tcounts, draw);
  const box = el("div", { class: "scrolltable" });
  wrap.append(tabs, filters, box);

  function draw() {
    let sel = rows.filter((r) => (state.tour === "all" || r.tour === state.tour)
      && (state.market === "all" || r.market === state.market)
      && (state.book === "all" || BOOK_LABEL[r.best.book] === state.book));
    sel = applySort(sel, state);
    document.getElementById("vc").textContent = `${sel.length} selections`;
    const head = el("tr", {}, el("th", { class: "pl" }, "Selection"), el("th", {}, "Market"), el("th", { class: "pl" }, "Match"),
      sortHeader("Model %", "model", (r) => r.model, state, draw),
      sortHeader("Best price", "price", (r) => r.best.price, state, draw),
      sortHeader("Edge", "edge", (r) => r.edge, state, draw),
      sortHeader("EV", "ev", (r) => r.ev, state, draw));
    const body = sel.map((r) => {
      const fx = fxIdx.get(pairKey(r.tour, r.p1, r.p2));
      const tr = el("tr", { class: fx && fx.markets ? "click" : "" },
        el("td", { class: "pl" }, el("b", {}, r.sel)),
        el("td", { class: "mut" }, r.market),
        el("td", { class: "pl mut" }, r.match),
        el("td", { class: "num" }, fmtPct(r.model)),
        el("td", { class: "num" }, `${r.best.price.toFixed(2)} ${BOOK_LABEL[r.best.book]}`),
        el("td", { class: "num" }, fmtPct(r.edge)),
        el("td", { class: "num pos" }, `+${(r.ev * 100).toFixed(0)}%`));
      if (fx && fx.markets) tr.onclick = () => openDetail(fx);
      return tr;
    });
    box.replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, ...body)));
  }
  draw();
}

/* ===========================================================
   PICK'EM — Dabble's player-prop multiplier game vs the model
   =========================================================== */
async function renderPickem() {
  const [lines, preds] = await Promise.all([getJSON("data/pickem-lines.json"), getJSON("data/predictions.json")]);
  const wrap = document.getElementById("content");
  wrap.append(el("div", { class: "panel prose", style: "margin-top:0" },
    el("h3", {}, "Dabble Pick'em ", el("span", { class: "tag" }, "multiplier game")),
    el("p", { html: "Dabble's <b>Pick'em</b> is a multiplier game: pick player props <b>over or under</b> a set line and stack them for a bigger payout. This lines Dabble's posted lines up against the model's projection so you can see which side the model leans." })));

  if (!lines || !lines.lines || !lines.lines.length) {
    wrap.append(el("div", { class: "panel prose" },
      el("p", {}, "Pick'em lines aren't available right now — they open closer to each match. Check back soon.")));
    return;
  }
  // Match each Pick'em line to the FIXTURE in its event (so "total games" gets that
  // exact match's model total, and aces/DFs get the right player's projection).
  const fxByPair = new Map();
  ((preds && preds.fixtures) || []).forEach((f) => fxByPair.set(pairKey(f.tour, f.player1, f.player2), f));
  const lineFixture = (l) => {
    const parts = (l.event || "").split(/\s+vs?\s+/i);
    return parts.length === 2 ? fxByPair.get(pairKey(l.tour, parts[0].trim(), parts[1].trim())) : null;
  };
  const modelProj = (l, fx) => {
    if (!fx || !fx.markets) return null;
    const m = fx.markets;
    if (l.stat === "games") return m.exp_total_games;          // MATCH total
    const isP1 = pnorm(l.player) === pnorm(fx.player1);
    if (l.stat === "aces") return isP1 ? m.exp_aces_a : m.exp_aces_b;
    if (l.stat === "doublefaults") return isP1 ? m.exp_df_a : m.exp_df_b;
    return null;
  };
  const statName = { games: "Match total games", aces: "Aces", doublefaults: "Double faults" };

  const state = { tour: "all", stat: "all", sort: null, dir: -1, _get: null };
  const stats = [...new Set(lines.lines.map((l) => l.stat))];
  const tabs = tourTabs(state, { all: lines.lines.length, atp: lines.lines.filter(l => l.tour === "atp").length, wta: lines.lines.filter(l => l.tour === "wta").length }, draw);
  const filters = el("div", { class: "filters" },
    filterSelect("Stat", "stat", stats.map((s) => statName[s] || s), state, draw),
    el("span", { class: "count", id: "pkc" }, ""));
  const box = el("div", { class: "scrolltable" });
  wrap.append(tabs, filters, box);

  function draw() {
    let rows = lines.lines.filter((l) => (state.tour === "all" || l.tour === state.tour)
      && (state.stat === "all" || (statName[l.stat] || l.stat) === state.stat))
      .map((l) => { const fx = lineFixture(l); return { l, fx, mp: modelProj(l, fx) }; });
    rows = applySort(rows, state);
    document.getElementById("pkc").textContent = `${rows.length} lines`;
    const head = el("tr", {}, el("th", { class: "pl" }, "Match"), el("th", { class: "pl" }, "Player"), el("th", {}, "Stat"),
      sortHeader("Dabble line", "line", (r) => r.l.line, state, draw),
      sortHeader("Model proj", "mp", (r) => r.mp, state, draw),
      sortHeader("Edge", "edge", (r) => r.mp == null ? null : Math.abs(r.mp - r.l.line), state, draw),
      el("th", {}, "Lean"));
    const body = rows.map(({ l, fx, mp }) => {
      const lean = mp == null ? "—" : (mp > l.line ? "Over" : "Under");
      const tr = el("tr", { class: fx && fx.markets ? "click" : "" },
        el("td", { class: "pl mut" }, fx ? `${fx.player1} v ${fx.player2}` : l.event),
        el("td", { class: "pl" }, el("b", {}, l.player)),
        el("td", { class: "mut" }, statName[l.stat] || l.stat),
        el("td", { class: "num" }, l.line),
        el("td", { class: "num" }, mp == null ? "—" : mp.toFixed(1)),
        el("td", { class: "num mut" }, mp == null ? "—" : (mp - l.line >= 0 ? "+" : "") + (mp - l.line).toFixed(1)),
        el("td", { class: "num " + (lean === "Over" ? "pos" : lean === "Under" ? "neg" : "mut") }, lean));
      if (fx && fx.markets) tr.onclick = () => openDetail(fx);
      return tr;
    });
    box.replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, ...body)));
  }
  draw();
}

function pnorm(s) { return (s || "").toLowerCase().normalize("NFKD").replace(/[^a-z]/g, ""); }

/* ===========================================================
   HOME
   =========================================================== */
async function renderHome() {
  const [data, meta, boards] = await Promise.all([getJSON("data/predictions.json"), getJSON("data/meta.json"), getJSON("data/ratings.json")]);
  const fr = document.getElementById("freshness");
  if (meta && fr) fr.textContent = `Model-priced ATP & WTA tennis — singles and doubles. Updated ${meta.generated}, rebuilt every 3 hours.`;
  const wrap = document.getElementById("content");
  const fx = (data && data.fixtures) || [];
  const atpBt = (meta?.backtest || []).find((b) => b.tour === "atp");
  const nPlayers = meta ? (meta.n_players.atp + meta.n_players.wta) : "—";

  // KPI strip
  wrap.append(el("div", { class: "panel" }, el("div", { class: "kpis" },
    el("div", { class: "kpi pos" }, el("b", {}, fx.length), el("i", {}, "Matches priced")),
    el("div", { class: "kpi" }, el("b", {}, nPlayers), el("i", {}, "Players rated")),
    el("div", { class: "kpi" }, el("b", {}, atpBt ? `${(atpBt.accuracy*100).toFixed(0)}%` : "—"), el("i", {}, "ATP backtest acc")),
    el("div", { class: "kpi" }, el("b", {}, atpBt ? atpBt.log_loss : "—"), el("i", {}, "ATP log-loss")))));

  // quick links
  const card = (href, title, desc) => el("a", { class: "navcard", href }, el("h4", {}, title), el("p", { class: "mut" }, desc));
  wrap.append(el("div", { class: "grid3 navcards" },
    card("matches.html", "Matches →", "Every upcoming match, fully priced across the market book."),
    card("rankings.html", "Rankings →", "Serve & return ratings by tour and surface."),
    card("lab.html", "Model Lab →", "Build any singles or doubles match-up live."),
    card("schedule.html", "Schedule →", "Tournaments currently in the model."),
    card("analysis.html", "Analysis →", "Form, leaders and surface specialists."),
    card("games.html", "Games →", "Beat the model and test your tennis IQ.")));

  // featured matches: most lopsided + closest, a handful
  if (fx.length) {
    const singles = fx.filter((f) => f.format !== "doubles");
    const featured = [...singles].sort((a, b) => Math.max(b.win_prob_1,b.win_prob_2) - Math.max(a.win_prob_1,a.win_prob_2)).slice(0, 6);
    wrap.append(el("div", { class: "group-head" }, el("h2", {}, "Standout matches"), el("a", { href: "matches.html" }, "All matches →")));
    const table = el("table", {}, el("thead", {}, el("tr", {},
      el("th", { class: "pl" }, "Match"), el("th", {}, "Event"), el("th", {}, "Surface"), el("th", {}, "Win prob"), el("th", {}, "Fair"))),
      el("tbody", {}, ...featured.map((f) => {
        const aFav = f.win_prob_1 >= f.win_prob_2;
        const tr = el("tr", { class: "click" },
          el("td", { class: "pl" },
            el("div", { class: aFav ? "fav" : "" }, el("b", {}, f.player1), " ", el("span", { class: "mut" }, fmtPct(f.win_prob_1))),
            el("div", { class: !aFav ? "fav" : "" }, el("b", {}, f.player2), " ", el("span", { class: "mut" }, fmtPct(f.win_prob_2)))),
          el("td", { class: "mut" }, f.tournament), el("td", {}, el("span", { class: "pill surf-" + f.surface }, f.surface)),
          el("td", {}, miniBar(Math.max(f.win_prob_1, f.win_prob_2))), el("td", { class: "num" }, `${f.fair_odds_1} / ${f.fair_odds_2}`));
        if (f.markets) tr.onclick = () => openDetail(f);
        return tr;
      })));
    wrap.append(el("div", { class: "match" }, el("div", { class: "tablewrap" }, table)));
  }

  // top of the rankings
  if (boards) {
    const mini = (tour) => el("div", { class: "subcard" }, el("h4", {}, `${TOUR_LABEL[tour]} top 8`),
      el("table", {}, el("tbody", {}, ...(boards[tour]?.overall || []).slice(0, 8).map((r) =>
        el("tr", {}, el("td", { class: "mut" }, r.rank), el("td", { class: "pl" }, playerLink(tour, r.name)), el("td", { class: "num pos" }, r.pr.toFixed(1)))))));
    wrap.append(el("div", { class: "group-head" }, el("h2", {}, "Top of the rankings"), el("a", { href: "rankings.html" }, "Full rankings →")));
    wrap.append(el("div", { class: "grid2" }, mini("atp"), mini("wta")));
  }
}

/* ===========================================================
   SCHEDULE
   =========================================================== */
async function renderSchedule() {
  const data = await getJSON("data/predictions.json");
  const wrap = document.getElementById("content");
  const fx = (data && data.fixtures) || [];
  if (!fx.length) { wrap.append(el("p", { class: "muted" }, "No tournaments in the model right now.")); return; }
  const byT = new Map();
  fx.forEach((f) => {
    if (!byT.has(f.tournament)) byT.set(f.tournament, { surface: f.surface, tours: new Set(), dmin: f.date, dmax: f.date, n: 0, dbl: 0 });
    const t = byT.get(f.tournament);
    t.tours.add(TOUR_LABEL[f.tour]); t.n++; if (f.format === "doubles") t.dbl++;
    if (f.date && (!t.dmin || f.date < t.dmin)) t.dmin = f.date;
    if (f.date && (!t.dmax || f.date > t.dmax)) t.dmax = f.date;
  });
  const rows = [...byT.entries()].sort((a, b) => b[1].n - a[1].n);
  const table = el("table", {}, el("thead", {}, el("tr", {},
    el("th", { class: "pl" }, "Tournament"), el("th", {}, "Tour"), el("th", {}, "Surface"),
    el("th", {}, "Dates"), el("th", {}, "Matches"), el("th", {}, ""))),
    el("tbody", {}, ...rows.map(([name, t]) => el("tr", { class: "click", onclick: () => location.href = `matches.html?t=${encodeURIComponent(name)}` },
      el("td", { class: "pl" }, el("b", {}, name)),
      el("td", { class: "mut" }, [...t.tours].join(" + ")),
      el("td", {}, el("span", { class: "pill surf-" + t.surface }, t.surface)),
      el("td", { class: "mut" }, t.dmin === t.dmax ? fmtDate(t.dmin) : `${fmtDate(t.dmin)} → ${fmtDate(t.dmax)}`),
      el("td", { class: "num" }, t.n + (t.dbl ? ` (${t.dbl} dbl)` : "")),
      el("td", {}, el("span", { class: "mut" }, "View →"))))));
  wrap.append(el("div", { class: "match" }, el("div", { class: "tablewrap" }, table)));
}

/* ===========================================================
   PLAYER
   =========================================================== */
async function renderPlayer() {
  const params = new URLSearchParams(location.search);
  const tour = params.get("tour") || "atp";
  const name = params.get("name") || "";
  const wrap = document.getElementById("content");
  const data = await getJSON(`data/players-${tour}.json`);
  const p = data && data[name];
  if (!p) { wrap.append(el("div", { class: "hero" }, el("h1", {}, name || "Player")), el("p", { class: "muted" }, "No profile found for this player.")); return; }
  document.title = `${name} · Grand Slam Tennis`;

  wrap.append(el("div", { class: "hero" },
    el("h1", {}, name),
    el("p", { class: "muted" }, `${TOUR_LABEL[tour]}${p.rank ? ` · PR rank #${p.rank}` : ""} · career charted record ${record(p.record.overall)}`)));

  // surface stat table
  const SC = [["overall", "All surfaces"], ["Hard", "Hard"], ["Clay", "Clay"], ["Grass", "Grass"]];
  const stat = el("table", {}, el("thead", {}, el("tr", {},
    el("th", { class: "pl" }, "Surface"), el("th", {}, "Rating"), el("th", {}, "Serve W%"), el("th", {}, "Return W%"),
    el("th", {}, "Ace%"), el("th", {}, "DF%"), el("th", {}, "Record"))),
    el("tbody", {}, ...SC.filter(([k]) => p.profile[k]).map(([k, label]) => {
      const s = p.profile[k];
      return el("tr", {},
        el("td", { class: "pl" }, k === "overall" ? el("b", {}, label) : el("span", { class: "pill surf-" + k }, label)),
        el("td", { class: "num pos" }, s.pr.toFixed(1)),
        el("td", { class: "num" }, fmtPct(s.spw)), el("td", { class: "num" }, fmtPct(s.rpw)),
        el("td", { class: "num mut" }, fmtPct(s.ace_rate)), el("td", { class: "num mut" }, fmtPct(s.df_rate)),
        el("td", { class: "num mut" }, record(p.record[k] || [0, 0])));
    })));
  wrap.append(el("div", { class: "group-head" }, el("h2", {}, "Form by surface")),
    el("div", { class: "match" }, el("div", { class: "tablewrap" }, stat)));

  // recent results
  if (p.recent.length) {
    const rt = el("table", {}, el("thead", {}, el("tr", {},
      el("th", { class: "pl" }, "Date"), el("th", {}, "Result"), el("th", { class: "pl" }, "Opponent"),
      el("th", {}, "Surface"), el("th", { class: "pl" }, "Event"), el("th", {}, "Round"))),
      el("tbody", {}, ...p.recent.map((m) => el("tr", {},
        el("td", { class: "mut" }, fmtDate(String(m.date))),
        el("td", { class: m.result === "W" ? "pos" : "mut" }, el("b", {}, m.result)),
        el("td", { class: "pl" }, playerLink(tour, m.opp)),
        el("td", {}, el("span", { class: "pill surf-" + m.surface }, m.surface)),
        el("td", { class: "pl mut" }, m.tournament || ""), el("td", { class: "mut" }, m.round || "")))));
    wrap.append(el("div", { class: "group-head" }, el("h2", {}, "Recent results"), el("span", { class: "muted" }, `${p.recent.length} matches`)),
      el("div", { class: "match" }, el("div", { class: "tablewrap" }, rt)));
  }
}

/* ===========================================================
   GAMES
   =========================================================== */
async function renderGames() {
  const wrap = document.getElementById("content");
  const tabs = el("div", { class: "tabs" });
  const pane = el("div", { style: "margin-top:16px" });
  const games = [["hl", "Higher or Lower"], ["btm", "Beat the Model"]];
  let active = "hl";
  games.forEach(([id, label]) => {
    const b = el("button", { class: id === active ? "on" : "", "data-g": id }, label);
    b.onclick = () => { active = id; [...tabs.children].forEach((c) => c.classList.toggle("on", c.dataset.g === id)); load(); };
    tabs.append(b);
  });
  wrap.append(tabs, pane);
  function load() { pane.replaceChildren(); (active === "hl" ? gameHigherLower : gameBeatModel)(pane); }
  load();
}

async function gameHigherLower(pane) {
  const boards = await getJSON("data/ratings.json");
  if (!boards) { pane.append(el("p", { class: "muted" }, "Data unavailable.")); return; }
  const pool = [...(boards.atp?.overall || []), ...(boards.wta?.overall || [])].filter((r) => r.serve_pts > 400);
  const STATS = [["pr", "Points Rating", (v) => v.toFixed(1)], ["spw", "serve points won", fmtPct], ["rpw", "return points won", fmtPct], ["ace_rate", "ace rate", fmtPct]];
  let score = 0, streak = 0, best = 0;
  const pick = () => { let a = pool[(Math.random()*pool.length)|0], b = pool[(Math.random()*pool.length)|0]; let g=0; while (b === a && g++ < 9) b = pool[(Math.random()*pool.length)|0]; return [a, b, STATS[(Math.random()*STATS.length)|0]]; };
  let [A, B, S] = pick();
  const scoreLine = el("div", { class: "kpis", style: "margin-bottom:14px" });
  const board = el("div", { class: "card", style: "padding:18px" });
  const render = () => {
    scoreLine.replaceChildren(
      el("div", { class: "kpi pos" }, el("b", {}, score), el("i", {}, "Score")),
      el("div", { class: "kpi" }, el("b", {}, streak), el("i", {}, "Streak")),
      el("div", { class: "kpi" }, el("b", {}, best), el("i", {}, "Best")));
    const [key, label] = S;
    const btn = (pl) => { const b = el("button", { class: "go", style: "margin:6px 0" }, pl.name); b.onclick = () => guess(pl); return b; };
    board.replaceChildren(
      el("p", { class: "lead", style: "text-align:center;font-size:16px" }, `Who has the higher ${label}?`),
      el("div", { class: "grid2" }, btn(A), btn(B)));
  };
  const guess = (choice) => {
    const [key] = S; const other = choice === A ? B : A;
    const correct = choice[key] >= other[key];
    if (correct) { score++; streak++; best = Math.max(best, streak); } else { streak = 0; }
    board.replaceChildren(el("div", { class: "panel", style: "text-align:center;margin:0" },
      el("h3", { style: "justify-content:center" }, correct ? "✓ Correct" : "✗ Nope"),
      el("p", {}, `${A.name}: ${S[2](A[S[0]])} · ${B.name}: ${S[2](B[S[0]])}`),
      el("button", { class: "go", style: "max-width:220px;margin:8px auto 0", onclick: () => { [A, B, S] = pick(); render(); } }, "Next →")));
    scoreLine.replaceChildren(
      el("div", { class: "kpi pos" }, el("b", {}, score), el("i", {}, "Score")),
      el("div", { class: "kpi" }, el("b", {}, streak), el("i", {}, "Streak")),
      el("div", { class: "kpi" }, el("b", {}, best), el("i", {}, "Best")));
  };
  pane.append(el("div", { class: "panel" }, el("h3", {}, "Higher or Lower ", el("span", { class: "tag" }, "serve & return")),
    el("p", { class: "lead" }, "Pick the player who rates higher on a random stat. Build your streak."),
    scoreLine, board));
  render();
}

async function gameBeatModel(pane) {
  const data = await getJSON("data/predictions.json");
  const singles = ((data && data.fixtures) || []).filter((f) => f.format !== "doubles");
  if (!singles.length) { pane.append(el("p", { class: "muted" }, "No matches to play right now.")); return; }
  const slate = singles.slice().sort(() => 0.5 - Math.random()).slice(0, 8);
  let agree = 0, done = 0;
  const tally = el("div", { class: "kpis", style: "margin-bottom:14px" });
  const updateTally = () => tally.replaceChildren(
    el("div", { class: "kpi pos" }, el("b", {}, `${agree}/${done}`), el("i", {}, "Agreed with model")),
    el("div", { class: "kpi" }, el("b", {}, `${slate.length - done}`), el("i", {}, "Remaining")));
  const list = el("div", {});
  slate.forEach((f, i) => {
    const item = el("div", { class: "subcard", style: "margin:10px 0" });
    const head = el("div", { class: "mut", style: "font-size:12px;margin-bottom:8px" }, `${f.tournament} · ${f.round} · ${f.surface}`);
    const btn = (name, which) => { const b = el("button", { class: "go", style: "margin:4px 0" }, name); b.onclick = () => reveal(which, b); return b; };
    const choices = el("div", { class: "grid2" }, btn(f.player1, 1), btn(f.player2, 2));
    item.append(head, choices);
    list.append(item);
    function reveal(which, b) {
      const modelFav = f.win_prob_1 >= f.win_prob_2 ? 1 : 2;
      const matched = which === modelFav;
      if (matched) agree++; done++;
      const fp = modelFav === 1 ? f.player1 : f.player2;
      const fprob = Math.max(f.win_prob_1, f.win_prob_2);
      item.replaceChildren(head, el("div", { class: matched ? "pos" : "mut", style: "font-weight:600" },
        `${matched ? "✓ You agree" : "✗ You differ"} — model: ${fp} ${fmtPct(fprob)} (${fmtOdds(fprob)})`),
        el("div", { class: "mut", style: "font-size:12.5px;margin-top:4px" }, `You picked ${which === 1 ? f.player1 : f.player2}`));
      updateTally();
    }
  });
  pane.append(el("div", { class: "panel" }, el("h3", {}, "Beat the Model ", el("span", { class: "tag" }, "pick'em")),
    el("p", { class: "lead" }, "Pick the winner of each match, then see who the model favours. How often do you agree?"),
    tally, list));
  updateTally();
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
chrome(page);
({ home: renderHome, matches: renderMatches, schedule: renderSchedule, rankings: renderRankings,
   analysis: renderAnalysis, games: renderGames, backtest: renderBacktest, lab: renderLab,
   compare: renderCompare, value: renderValue, pickem: renderPickem, player: renderPlayer }[page] || (() => {}))();
