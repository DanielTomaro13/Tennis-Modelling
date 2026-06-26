// app.js — shared data loading + page renderers for the static site.
import { projectMatch, blendedWinProb } from "./sim.js";

const fmtPct = (p) => (p * 100).toFixed(0) + "%";
const fmtOdds = (p) => (p > 0 ? (1 / p).toFixed(2) : "—");
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
    wrap.append(el("p", { class: "muted" }, "No upcoming fixtures resolved. Check back after the next daily run."));
    return;
  }
  let tour = "all";
  const tabs = el("div", { class: "tabs" });
  ["all", "atp", "wta"].forEach((t) => {
    const b = el("button", { class: t === tour ? "active" : "" }, t.toUpperCase());
    b.onclick = () => { tour = t; [...tabs.children].forEach((c) => c.classList.toggle("active", c.textContent === t.toUpperCase())); draw(); };
    tabs.append(b);
  });
  wrap.append(tabs);
  const card = el("div", { class: "card" });
  wrap.append(card);

  function draw() {
    const rows = data.fixtures.filter((f) => tour === "all" || f.tour === tour);
    const table = el("table");
    table.append(el("tr", {},
      el("th", {}, "Date"), el("th", {}, "Event"), el("th", {}, "Surface"),
      el("th", {}, "Match"), el("th", { class: "num" }, "Win %"),
      el("th", { class: "num" }, "Fair odds"), el("th", { class: "num" }, "Games"),
      el("th", { class: "num" }, "TB %"), el("th", { class: "num" }, "Aces"),
    ));
    rows.forEach((f) => {
      const aFav = f.win_prob_1 >= f.win_prob_2;
      const p1 = el("div", { class: aFav ? "fav" : "" }, `${f.player1} ${fmtPct(f.win_prob_1)}`);
      const p2 = el("div", { class: !aFav ? "fav" : "" }, `${f.player2} ${fmtPct(f.win_prob_2)}`);
      table.append(el("tr", {},
        el("td", { class: "muted" }, fmtDate(f.date)),
        el("td", {}, el("div", {}, f.tournament), el("div", { class: "muted", html: f.round || "" })),
        el("td", {}, el("span", { class: "pill surf-" + f.surface }, f.surface)),
        el("td", {}, p1, p2),
        el("td", { class: "num" }, probBar(Math.max(f.win_prob_1, f.win_prob_2))),
        el("td", { class: "num" }, `${f.fair_odds_1} / ${f.fair_odds_2}`),
        el("td", { class: "num" }, String(f.exp_total_games)),
        el("td", { class: "num" }, fmtPct(f.tiebreak_prob)),
        el("td", { class: "num muted" }, `${f.exp_aces_1} / ${f.exp_aces_2}`),
      ));
    });
    card.replaceChildren(table);
  }
  draw();
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
  const card = el("div", { class: "card" });
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
    const winB = 1 - winA;

    const head = el("div", { class: "card" },
      el("div", { class: "result-head" },
        el("div", {}, el("div", { class: "big " + (winA >= winB ? "fav" : "") }, fmtPct(winA)), el("div", { class: "muted" }, `${n1} · fair ${fmtOdds(winA)}`)),
        el("div", { class: "muted" }, `${surface} · Bo${bestOf}`),
        el("div", { style: "text-align:right" }, el("div", { class: "big " + (winB > winA ? "fav" : "") }, fmtPct(winB)), el("div", { class: "muted" }, `${n2} · fair ${fmtOdds(winB)}`)),
      ),
      el("div", { class: "result-head" }, probBarWide(winA)),
    );

    const setScores = Object.entries(m.set_score).sort((x, y) => y[1] - x[1]);
    const markets = el("div", { class: "grid2" },
      mktCard("Match shape", [
        ["Expected total games", m.exp_total_games.toFixed(1)],
        ["At least one tie-break", fmtPct(m.tiebreak_prob)],
        [`${n1} hold %`, fmtPct(m.hold_a)],
        [`${n2} hold %`, fmtPct(m.hold_b)],
      ]),
      mktCard("Set betting", setScores.map(([k, v]) => [k, fmtPct(v)])),
      mktCard("Total games", Object.entries(m.totals).map(([line, o]) => [`Over ${line}`, fmtPct(o.over)])),
      mktCard("Serve markets (expected)", [
        [`${n1} aces`, m.exp_aces_a.toFixed(1)],
        [`${n2} aces`, m.exp_aces_b.toFixed(1)],
        [`${n1} double faults`, m.exp_df_a.toFixed(1)],
        [`${n2} double faults`, m.exp_df_b.toFixed(1)],
      ]),
    );
    out.replaceChildren(head, el("div", { style: "height:18px" }), markets);
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
