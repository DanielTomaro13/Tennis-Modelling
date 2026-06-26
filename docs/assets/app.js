// app.js — shared data loading + page renderers for the static site.
import { projectMatch, blendedWinProb } from "./sim.js";

const fmtPct = (p) => (p * 100).toFixed(0) + "%";
const fmtOdds = (p) => (p > 0 ? (1 / p).toFixed(2) : "—");
// percentage + its fair decimal price, e.g. "62% · 1.61"
const pctOdds = (p) => `${fmtPct(p)} · ${fmtOdds(p)}`;
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  kids.flat().forEach((c) => e.append(c?.nodeType ? c : document.createTextNode(c ?? "")));
  return e;
};
const getJSON = (p) => fetch(p).then((r) => (r.ok ? r.json() : null)).catch(() => null);

function probBar(p) {
  const bar = el("div", { class: "prob-bar" });
  const span = el("span");
  span.style.width = (p * 100).toFixed(1) + "%";
  bar.append(span);
  return bar;
}

async function setFreshness() {
  const meta = await getJSON("data/meta.json");
  const node = document.getElementById("freshness");
  if (meta && node) {
    let txt = `Updated ${meta.generated}`;
    if (meta.backtest) {
      const atp = meta.backtest.find((b) => b.tour === "atp");
      if (atp && atp.n) txt += ` · ATP backtest log-loss ${atp.log_loss}, acc ${(atp.accuracy * 100).toFixed(0)}%`;
    }
    node.textContent = txt;
  }
}

// --------------------------------------------------------------------------- //
// Predictions page
// --------------------------------------------------------------------------- //
async function renderPredictions() {
  const data = await getJSON("data/predictions.json");
  const wrap = document.getElementById("content");
  if (!data || !data.fixtures.length) {
    wrap.append(el("div", { class: "empty" },
      el("p", {}, "No scheduled matches resolved for today yet."),
      el("p", { class: "muted" }, "Fixtures refresh daily from tennis.com. In the meantime, try the "),
      el("a", { href: "predictor.html", class: "btnlink" }, "head-to-head predictor →")));
    return;
  }
  let tour = "all";
  const counts = { all: data.fixtures.length, atp: 0, wta: 0 };
  data.fixtures.forEach((f) => counts[f.tour]++);

  const tabs = el("div", { class: "tabs" });
  ["all", "atp", "wta"].forEach((t) => {
    const b = el("button", { class: t === tour ? "active" : "", "data-t": t },
      `${t.toUpperCase()} (${counts[t]})`);
    b.onclick = () => {
      tour = t;
      [...tabs.children].forEach((c) => c.classList.toggle("active", c.dataset.t === t));
      draw();
    };
    tabs.append(b);
  });
  wrap.append(tabs);
  const grid = el("div", { class: "cards" });
  wrap.append(grid);

  function matchCard(f) {
    const aFav = f.win_prob_1 >= f.win_prob_2;
    const player = (name, prob, odds, fav) => el("div", { class: "player" + (fav ? " fav" : "") },
      el("span", { class: "pname" }, name),
      el("span", { class: "podds muted" }, "fair " + odds),
      el("span", { class: "pprob" }, fmtPct(prob)));
    // top set scores (most likely 2)
    const sets = Object.entries(f.set_score || {}).sort((a, b) => b[1] - a[1]).slice(0, 2)
      .map(([k, v]) => `${k} (${pctOdds(v)})`).join(" · ");
    const chips = el("div", { class: "chips" },
      chip("Total games", f.exp_total_games),
      chip("Tie-break", pctOdds(f.tiebreak_prob)),
      chip("Aces", `${f.exp_aces_1} / ${f.exp_aces_2}`),
      sets ? chip("Likely sets", sets) : "");
    const node = el("div", { class: "match clickable" },
      el("div", { class: "match-top" },
        el("div", { class: "ev" },
          el("span", {}, f.tournament),
          el("span", { class: "muted" }, [f.round, f.date ? fmtDate(f.date) : ""].filter(Boolean).join(" · "))),
        el("span", { class: "pill surf-" + f.surface }, f.surface)),
      el("div", { class: "players" },
        player(f.player1, f.win_prob_1, f.fair_odds_1, aFav),
        el("div", { class: "vsbar" }, probBar(f.win_prob_1)),
        player(f.player2, f.win_prob_2, f.fair_odds_2, !aFav)),
      chips,
      el("div", { class: "more-hint" }, "View all markets →"));
    if (f.markets) node.onclick = () => openDetail(f);
    return node;
  }

  function draw() {
    const rows = data.fixtures.filter((f) => tour === "all" || f.tour === tour);
    if (!rows.length) { grid.replaceChildren(el("p", { class: "muted" }, "No matches for this tour today.")); return; }
    grid.replaceChildren(...rows.map(matchCard));
  }
  draw();
}

function chip(label, value) {
  return el("div", { class: "mchip" }, el("small", {}, label), el("b", {}, String(value)));
}

// --------------------------------------------------------------------------- //
// Shared full-market renderer (used by the detail modal AND the predictor)
// --------------------------------------------------------------------------- //
function ouRows(dist, label) {
  return Object.entries(dist).map(([line, o]) => [`${label} ${line}`, pctOdds(o.over)]);
}
function probRows(dist, labelFn) {
  return Object.entries(dist).map(([line, p]) => [labelFn(line), pctOdds(p)]);
}
function acesRows(expected, dist) {
  return [["Expected", expected.toFixed(1)], ...probRows(dist, (l) => `Over ${l}`)];
}

function marketGrid(m, n1, n2, winA) {
  const winB = 1 - winA;
  const ss = Object.entries(m.set_score || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, pctOdds(v)]);
  const cards = [
    mktCard("Match winner", [[n1, pctOdds(winA)], [n2, pctOdds(winB)]]),
    mktCard("Sets", [
      ["Straight sets", pctOdds(m.straight_sets)],
      ["Deciding set", pctOdds(m.deciding_set)],
      [`${n1} to win a set`, pctOdds(m.a_wins_set)],
      [`${n2} to win a set`, pctOdds(m.b_wins_set)],
    ]),
    mktCard("1st set winner", [[n1, pctOdds(m.set1_win_a)], [n2, pctOdds(1 - m.set1_win_a)]]),
    mktCard("2nd set winner", [[n1, pctOdds(m.set2_win_a)], [n2, pctOdds(1 - m.set2_win_a)]]),
    mktCard("Correct set score", ss),
    mktCard("Total games", ouRows(m.totals, "Over")),
    mktCard(`Games handicap`, probRows(m.handicap, (l) => `${n1} ${l}`)),
    mktCard(`${n1} total games`, ouRows(m.player_games_a, "Over")),
    mktCard(`${n2} total games`, ouRows(m.player_games_b, "Over")),
    mktCard("Tie-break in match", [["At least one", pctOdds(m.tiebreak_prob)]]),
    mktCard(`Aces — ${n1}`, acesRows(m.exp_aces_a, m.aces_ou_a)),
    mktCard(`Aces — ${n2}`, acesRows(m.exp_aces_b, m.aces_ou_b)),
    mktCard(`Double faults — ${n1}`, acesRows(m.exp_df_a, m.df_ou_a)),
    mktCard(`Double faults — ${n2}`, acesRows(m.exp_df_b, m.df_ou_b)),
    m.most_aces ? mktCard("Most aces", [[n1, pctOdds(m.most_aces.a)], ["Tie", pctOdds(m.most_aces.tie)], [n2, pctOdds(m.most_aces.b)]]) : "",
    m.most_df ? mktCard("Most double faults", [[n1, pctOdds(m.most_df.a)], ["Tie", pctOdds(m.most_df.tie)], [n2, pctOdds(m.most_df.b)]]) : "",
  ].filter(Boolean);
  return el("div", { class: "grid2 markets-grid" }, ...cards);
}

function detailHead(n1, n2, winA, subtitle) {
  const winB = 1 - winA;
  return el("div", { class: "card" },
    el("div", { class: "result-head" },
      el("div", {}, el("div", { class: "big " + (winA >= winB ? "fav" : "") }, fmtPct(winA)), el("div", { class: "muted" }, `${n1} · fair ${fmtOdds(winA)}`)),
      el("div", { class: "muted", style: "text-align:center" }, subtitle),
      el("div", { style: "text-align:right" }, el("div", { class: "big " + (winB > winA ? "fav" : "") }, fmtPct(winB)), el("div", { class: "muted" }, `${n2} · fair ${fmtOdds(winB)}`))),
    el("div", { class: "result-head" }, probBarWide(winA)));
}

function openDetail(f) {
  const sub = [f.surface, `Bo${f.best_of}`, f.round].filter(Boolean).join(" · ");
  const body = el("div", { class: "modal-body" },
    el("div", { class: "modal-evt" }, el("div", {}, f.tournament || ""), el("div", { class: "muted" }, [f.round, f.date ? fmtDate(f.date) : ""].filter(Boolean).join(" · "))),
    detailHead(f.player1, f.player2, f.win_prob_1, sub),
    el("div", { style: "height:16px" }),
    marketGrid(f.markets, f.player1, f.player2, f.win_prob_1));
  const close = el("button", { class: "modal-close", "aria-label": "Close" }, "✕");
  const dialog = el("div", { class: "modal" }, close, body);
  const overlay = el("div", { class: "modal-overlay" }, dialog);
  const dismiss = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") dismiss(); };
  overlay.onclick = (e) => { if (e.target === overlay) dismiss(); };
  close.onclick = dismiss;
  document.addEventListener("keydown", onKey);
  document.body.append(overlay);
}

function fmtDate(d) {
  if (!d || d.length < 8) return d || "";
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
}

// --------------------------------------------------------------------------- //
// Ratings page
// --------------------------------------------------------------------------- //
async function renderRatings() {
  const boards = await getJSON("data/ratings.json");
  const wrap = document.getElementById("content");
  if (!boards) { wrap.append(el("p", { class: "muted" }, "Ratings unavailable.")); return; }
  let tour = "atp", scope = "overall";
  const controls = el("div", { class: "controls" });
  const tourSel = el("select", {}, ...["atp", "wta"].map((t) => el("option", { value: t }, t.toUpperCase())));
  const scopeSel = el("select", {}, ...["overall", "Hard", "Clay", "Grass"].map((s) => el("option", { value: s }, s)));
  tourSel.onchange = () => { tour = tourSel.value; draw(); };
  scopeSel.onchange = () => { scope = scopeSel.value; draw(); };
  controls.append(tourSel, scopeSel);
  wrap.append(controls);
  const card = el("div", { class: "table-wrap" });
  wrap.append(card);

  function draw() {
    const rows = (boards[tour] && boards[tour][scope]) || [];
    const table = el("table");
    table.append(el("tr", {},
      el("th", { class: "num" }, "#"), el("th", {}, "Player"),
      el("th", { class: "num" }, "Rating"), el("th", { class: "num" }, "Serve W%"),
      el("th", { class: "num" }, "Return W%"), el("th", { class: "num" }, "Ace%"),
      el("th", { class: "num" }, "DF%"),
    ));
    rows.slice(0, 100).forEach((r) => table.append(el("tr", {},
      el("td", { class: "num muted" }, String(r.rank)),
      el("td", {}, r.name),
      el("td", { class: "num fav" }, r.pr.toFixed(1)),
      el("td", { class: "num" }, fmtPct(r.spw)),
      el("td", { class: "num" }, fmtPct(r.rpw)),
      el("td", { class: "num muted" }, fmtPct(r.ace_rate)),
      el("td", { class: "num muted" }, fmtPct(r.df_rate)),
    )));
    card.replaceChildren(table);
  }
  draw();
}

// --------------------------------------------------------------------------- //
// Predictor page (live, in-browser)
// --------------------------------------------------------------------------- //
async function renderPredictor() {
  const profiles = await getJSON("data/profiles.json");
  const wrap = document.getElementById("content");
  if (!profiles) { wrap.append(el("p", { class: "muted" }, "Profiles unavailable.")); return; }

  let tour = "atp";
  const tourSel = el("select", {}, ...["atp", "wta"].map((t) => el("option", { value: t }, t.toUpperCase())));
  const p1Sel = el("select", {}), p2Sel = el("select", {});
  const surfSel = el("select", {}, ...["Hard", "Clay", "Grass"].map((s) => el("option", { value: s }, s)));
  const boSel = el("select", {}, el("option", { value: "3" }, "Best of 3"), el("option", { value: "5" }, "Best of 5"));
  const go = el("button", { class: "primary" }, "Project match");

  function fillPlayers() {
    const names = Object.keys(profiles[tour].players).sort();
    [p1Sel, p2Sel].forEach((sel, i) => {
      sel.replaceChildren(...names.map((n) => el("option", { value: n }, n)));
      sel.selectedIndex = Math.min(i, names.length - 1);
    });
    if (names.length > 1) p2Sel.selectedIndex = 1;
  }
  tourSel.onchange = () => { tour = tourSel.value; fillPlayers(); };
  fillPlayers();

  const controls = el("div", { class: "controls" }, tourSel, p1Sel, surfSel, p2Sel, boSel, go);
  wrap.append(controls);
  const out = el("div", { id: "predout" });
  wrap.append(out);

  function scopeOf(prof, surface) { return prof[surface] || prof.overall; }

  go.onclick = () => {
    const league = profiles[tour].league;
    const n1 = p1Sel.value, n2 = p2Sel.value;
    if (n1 === n2) { out.replaceChildren(el("p", { class: "muted" }, "Pick two different players.")); return; }
    const surface = surfSel.value, bestOf = Number(boSel.value);
    const a = { ...scopeOf(profiles[tour].players[n1], surface), name: n1 };
    const b = { ...scopeOf(profiles[tour].players[n2], surface), name: n2 };
    const m = projectMatch(a, b, league, bestOf);
    const winA = blendedWinProb(a, b, league, bestOf);
    const head = detailHead(n1, n2, winA, `${surface} · Bo${bestOf}`);
    out.replaceChildren(head, el("div", { style: "height:18px" }), marketGrid(m, n1, n2, winA));
  };
  go.click();
}

function probBarWide(p) {
  const bar = el("div", { class: "prob-bar", style: "width:100%;height:12px" });
  const span = el("span"); span.style.width = (p * 100).toFixed(1) + "%"; bar.append(span);
  return bar;
}
function mktCard(title, rows) {
  return el("div", { class: "card mkt" }, el("h3", {}, title),
    ...rows.map(([k, v]) => el("div", { class: "row" }, el("span", { class: "muted" }, k), el("b", {}, v))));
}

// --------------------------------------------------------------------------- //
const page = document.body.dataset.page;
setFreshness();
if (page === "predictions") renderPredictions();
else if (page === "ratings") renderRatings();
else if (page === "predictor") renderPredictor();
