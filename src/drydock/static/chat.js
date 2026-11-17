// One window. The sidebar picks a project, the thread shows what the crew did,
// the composer starts the next job. Everything in the thread arrived as an
// event from the server, so nothing here can claim progress that was not made.

const S = { projects: [], commands: [], runs: [], project: null, key: null, menu: -1,
  engines: [], models: [], engine: "claude", model: "opus" };
window.S = S;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const MK = { done: "✓", reverted: "✗", blocked: "✗", working: "▸", waiting: "·" };

/* ---------- thread ---------- */

function say(who, html, cls = "") {
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.innerHTML = (who ? `<div class="from">${esc(who)}</div>` : "") + html;
  $("thread-inner").appendChild(el);
  $("thread").scrollTop = $("thread").scrollHeight;
  return el;
}

function youSaid(text) {
  say("", `<div class="bubble">${esc(text)}</div>`, "you");
}

/* ---------- live run ---------- */

const live = { items: new Map(), baseline: null, tests: null, cost: 0, el: {} };

function renderPlan() {
  if (!live.el.plan) return;
  const items = [...live.items.values()];
  live.el.plan.querySelector(".steps").innerHTML = items.map(i => `
      <div class="step ${i.status}">
        <span class="mk">${i.status === "working"
          ? '<span class="spin"></span>' : (MK[i.status] || "·")}</span>
        <span class="n mono">${i.id}</span>
        <div><div class="ttl">${esc(i.title)}</div>
        ${i.note ? `<div class="why">${esc(i.note)}</div>` : ""}
        ${i.gates ? `<div class="gates">${i.gates}</div>` : ""}</div>
      </div>`).join("");

  // The item being worked on is the one thing anyone is looking for, so it
  // is also kept in view when the plan is longer than the panel.
  const live_el = live.el.plan.querySelector(".step.working");
  if (live_el && !live.pinned) live_el.scrollIntoView({ block: "nearest" });
}

function renderStats() {
  const b = live.baseline;
  if (!b || !live.el.stats) return;
  const now = live.tests === null ? b.tests : live.tests;
  const landed = [...live.items.values()].filter(i => i.status === "done").length;
  const started = b.tests || b.failed || b.builds;
  live.el.stats.innerHTML = `
    ${started ? `
      <div class="stat ${now < b.tests ? "bad" : "ok"}"><b>${now}</b><span>tests running</span></div>
      <div class="stat"><b>${b.tests}</b><span>before any change</span></div>`
    : `<div class="stat"><b>${now}</b><span>tests exist now</span></div>`}
    <div class="stat"><b>${landed}</b><span>items landed</span></div>
    <div class="stat"><b>$${live.cost.toFixed(2)}</b><span>${
      S.engine === "claude" ? "on your plan, not billed" : "billed"}</span></div>`;
  $("spend").textContent = `$${live.cost.toFixed(2)}`;
}

// Each landed item offers its own diff, read back out of git on demand. It
// is not kept with the run: the commit is the record, and a second copy is a
// copy that can disagree with it.
function showDiffLink(e) {
  const msg = say("crew", `<div class="body">
    <p><b>Item ${e.id} landed.</b> ${esc(e.note)}</p>
    <details class="diff"><summary>See what changed</summary>
      <div class="patch">reading the commit…</div></details></div>`, "dim");
  const box = msg.querySelector("details");
  box.addEventListener("toggle", async () => {
    if (!box.open || box.dataset.loaded) return;
    box.dataset.loaded = "1";
    const r = await (await fetch(`/api/diff/${S.key}/${e.id}`)).json();
    const out = msg.querySelector(".patch");
    if (!r.ok) { out.textContent = r.reason; return; }
    out.innerHTML = paint(r.patch) +
      (r.clipped ? `<div class="why">The rest of the diff is not shown. An item
        this large cannot be read as one change.</div>` : "");
    box.querySelector("summary").textContent =
      `What changed in item ${e.id} · ${r.commit}`;
  }, { once: false });
}

// Colouring a diff is four lines of CSS and makes the difference between a
// wall of text and something a person will actually read.
function paint(patch) {
  return patch.split("\n").map(line => {
    const cls = line.startsWith("+++") || line.startsWith("---") ? "meta"
      : line.startsWith("+") ? "add"
      : line.startsWith("-") ? "del"
      : line.startsWith("@@") ? "hunk"
      : line.startsWith("diff ") || line.startsWith("index ") ? "meta" : "";
    return `<div class="dl ${cls}">${esc(line) || "&nbsp;"}</div>`;
  }).join("");
}

function toolLine(agent, detail) {
  if (!live.el.tools) return;
  live.el.tools.querySelector("details").style.display = "";
  const box = live.el.tools.querySelector(".lines");
  const row = document.createElement("div");
  row.className = "toolline";
  row.textContent = `${agent}  ${detail}`;
  box.appendChild(row);
  const n = box.children.length;
  live.el.tools.querySelector("summary").textContent =
    `${n} step${n === 1 ? "" : "s"} taken`;
}

const on = {
  "run.started": (e) => {
    S.skillsOn = e.skills || [];
    Office.reset();
    const NEEDS = {
      Verifier: "baseline", Analyst: "analyst",
      Architect: "planner", Planner: "planner",
      Engineer: "engineer", Inspector: "engineer", Reviewer: "engineer",
    };
    Object.entries(NEEDS).forEach(([who, stage]) => {
      if (e.stages && !e.stages.includes(stage)) {
        Office.at(who, "skipped", "this job stops before this desk");
      }
    });
    drawOffice();
    say("crew", `<div class="body"><p>Looking at <b>${esc(e.repo)}</b> ·
      ${esc(e.toolchain)}${e.skills.length ? ` · skill <code>${esc(e.skills[0])}</code>` : ""}</p></div>`);
    // Hidden until there is something to put in it: a job that uses no tools
    // should not leave an empty drawer sitting in the thread.
    live.el.tools = say("", `<details class="tools" style="display:none">
      <summary>working</summary><div class="lines"></div></details>`)
      .querySelector("details").parentElement;
  },
  "baseline": (e) => {
    live.baseline = e;
    station("Verifier", "done", e.green
      ? `${e.tests} tests pass before anything is touched`
      : `${e.failed} failing before anything is touched`);
    const nothing = !e.tests && !e.failed && !e.builds;
    const opening = nothing
      ? `There is nothing here yet - no build, no suite. Nothing can be verified
         until an item creates a way to run something, which is what the first
         item is for.`
      : e.green
      ? `The suite is green before anything is touched: <b>${e.tests} tests</b> pass.`
      : `The suite is <b>not green</b>: ${e.failed} failing. Nothing after this can be called a regression.`;
    const msg = say("crew", `<div class="body"><p>${opening}</p>
      <div class="card"><div class="stats"></div></div></div>`);
    live.el.stats = msg.querySelector(".stats");
    renderStats();
  },
  "agent.tool": (e) => toolLine(e.agent, e.detail),
  "spend": (e) => { live.cost = e.cost; renderStats(); },
  "agent.state": (e) => {
    station(e.agent, e.state, e.note);
    if (e.state === "working") running(true, `${e.agent}: ${e.note}`);
  },
  "survey": (e) => {
    say("analyst", `<div class="body"><p>${e.findings.length} findings,
      ${e.risks.length} risks.</p>
      <div class="card"><h4>What could go wrong</h4>
      ${e.risks.slice(0, 4).map(r => `<p class="why">${esc(r.slice(0, 260))}</p>`).join("")}
      </div></div>`, "dim");
  },
  "plan.ready": (e) => {
    const msg = say("planner", `<div class="body"><p>${esc(e.summary)}</p>
      <div class="card"><h4>${e.items.length} items</h4><div class="steps"></div></div>
      <div class="actions"><button class="btn" id="approve">Approve and start</button>
      <span class="hint" id="planhint">Nothing is changed until you approve.</span></div></div>`);
    live.el.plan = msg.querySelector(".card");
    station("Planner", "done", `${e.items.length} items, waiting for you`);
    e.items.forEach(i => live.items.set(i.id,
      { ...i, status: "waiting", note: i.rationale.split(". ")[0] }));
    live.cost = e.cost || 0;
    renderPlan(); renderStats();
    msg.querySelector("#approve").onclick = async (ev) => {
      ev.target.disabled = true;
      msg.querySelector("#planhint").textContent = "working, one item at a time";
      running(true, "working through the plan");
      await fetch("/api/approve/" + S.key, { method: "POST" });
    };
  },
  "item.start": (e) => {
    const i = live.items.get(e.id);
    if (i) {
      i.status = "working";
      i.note = "the engineer is on this one";
      i.gates = "";
      renderPlan();
    }
    Office.at("Engineer", "working", `item ${e.id}: ${e.title}`);
    Office.send("Engineer");
    drawOffice();
  },
  "gate": (e) => {
    const who = e.who === "inspector" ? "Inspector" : "Reviewer";
    // Each gate reports itself on the item it judged, so the plan shows how
    // far through the three checks a change actually got.
    const item = live.items.get(e.id);
    if (item) {
      item.gates = (item.gates || "") +
        `<span class="gate ${e.passed ? "ok" : "no"}">${esc(who)} ${
          e.passed ? "passed it" : "sent it back"}</span>`;
      renderPlan();
    }
    if (e.passed) { Office.send(who); Office.at(who, "done", e.note); drawOffice(); return; }
    Office.bounce(who);
    Office.at(who, "failed", e.note);
    Office.at("Engineer", "working", "told to try again");
    drawOffice();
    say("crew", `<div class="body"><p><b>${esc(e.who === "inspector"
      ? "The inspector refused item " + e.id : "The reviewer refused item " + e.id)}.</b>
      ${esc(e.note)}</p><p class="why">The suite was green. That is not the same
      as the change being right, which is what this desk is for.</p></div>`, "dim");
  },
  "item.done": (e) => {
    // Every landed item is its own commit, so the diff can be shown exactly
    // as the repository holds it rather than as something reconstructed.
    if (e.outcome === "done") showDiffLink(e);
    const i = live.items.get(e.id);
    if (i) {
      i.status = e.outcome;
      i.note = e.note + (e.attempts > 1 ? ` · ${e.attempts} attempts` : "");
      renderPlan();
    }
    const m = /(\d+) tests/.exec(e.note || "");
    if (m) live.tests = parseInt(m[1], 10);
    live.cost = e.cost || live.cost;
    if (e.outcome === "done") Office.land(); else Office.bounce("Verifier");
    station("Verifier", e.outcome === "done" ? "done" : "failed",
      e.outcome === "done"
        ? `item ${e.id} held the suite, so it stays`
        : `item ${e.id} did not hold the suite, so it was rolled back`);
    renderStats();
    if (e.outcome !== "done") {
      say("crew", `<div class="body"><p><b>Item ${e.id} was rolled back.</b>
        ${esc(e.note)}</p><p class="why">The tree is back where it was. Nothing after
        this item was attempted, because each one assumes the last one landed.</p></div>`);
    }
  },
  "resumed": (e) => {
    say("crew", `<div class="body"><p class="why">${esc(e.note)}</p></div>`, "dim");
  },
  "stopping": (e) => {
    say("crew", `<div class="body"><p>Stopping. ${esc(e.note)}</p></div>`, "dim");
  },
  "run.summary": (e) => {
    running(false);
    $("go").disabled = false;
    Keys.notify(
      e.read_only ? "drydock finished reading" : `${e.done} of ${e.total} items landed`,
      e.read_only ? "Nothing was changed." :
        `${S.projects.find(p => p.path === S.project)?.name || "The project"} · ` +
        `$${(e.cost || 0).toFixed(2)} of work`);
    drawOffice();
    if (e.read_only) {
      const kept = e.remembered
        ? `<p class="why">${e.remembered} facts about this repository were kept,
           so the next job here starts from them.</p>`
        : "";
      say("crew", `<div class="body"><p>That was a read, not a change. Nothing in
        your repository was touched.</p>${kept}</div>`);
      return;
    }
    const kept = e.remembered
      ? `${e.remembered} facts about this repository were kept, so the next job
         here starts from them instead of reading it all again. `
      : "";
    const paid = e.engine === "claude"
      ? `It ran on your Claude plan, so the <b>$${e.cost.toFixed(2)}</b> of API-priced
         work was not billed to you.`
      : `<b>$${e.cost.toFixed(2)}</b> billed.`;
    say("crew", `<div class="body"><p><b>${e.done} of ${e.total} items landed.</b>
      ${paid} The work is on its own branch; nothing touched your main branch.</p>
      <p class="why">${kept}<a href="#" id="see-usage">See what this has cost in
      total.</a></p></div>`);
    const link = $("see-usage");
    if (link) link.onclick = (ev) => {
      ev.preventDefault(); $("sheet").style.display = "flex"; drawSettings();
    };
  },
  "run.error": (e) => (running(false),
    Keys.notify("drydock stopped", e.detail), say("crew", `<div class="body"><p class="why">${esc(e.detail)}</p></div>`)),
  "awaiting.approval": () => {
    running(false);
    Keys.notify("A plan is waiting for you", "Nothing is changed until you approve it.");
  },
};

function watch(key) {
  S.key = key;
  live.items.clear(); live.tests = null; live.baseline = null; live.cost = 0; live.el = {};
  Office.reset();
  const src = new EventSource("/api/stream/" + key);
  src.onmessage = (m) => {
    const e = JSON.parse(m.data);
    (on[e.kind] || (() => {}))(e);
  };
}

/* ---------- the office ---------- */

// The room itself lives in office.js and is built once. This half only says
// what changed: who is at which desk, what is on the board, and where the
// item currently is. Everything that moves, moves there.

const WORDS = {
  idle: "waiting for the station before it",
  working: "working",
  done: "done",
  skipped: "not needed for this job",
  failed: "sent it back",
};

function station(id, state, note) {
  Office.at(id, state, note);
  drawLegend();
}

function drawLegend() {
  const mark = { done: "✓", working: "▸", skipped: "–", failed: "✗", idle: "·" };
  $("who-list").innerHTML = Office.states().map(s => `
    <div class="who-row ${s.state}">
      <span class="mk">${mark[s.state]}</span>
      <b>${esc(s.id)}</b>
      <span class="st">${esc(s.note || WORDS[s.state])}</span>
      ${s.code ? '<span class="tag">no model, just code</span>' : ""}
    </div>`).join("");

  $("shelf").innerHTML = (S.skillsOn || []).length
    ? S.skillsOn.map(n => `<code>${esc(n)}</code>`).join("")
    : `<i>none for this job - the crew is working from the repository alone</i>`;
}

function drawOffice() {
  Office.mount($("room"));
  const items = [...live.items.values()];
  Office.board(items, items.filter(i => i.status === "done").length);
  const b = live.baseline;
  if (b) {
    const now = live.tests === null ? b.tests : live.tests;
    Office.suite(now, b.tests, !!(b.tests || b.failed || b.builds));
  } else {
    Office.suite(null, 0, false);
  }
  drawLegend();
}

function view(which) {
  $("thread").style.display = which === "thread" ? "" : "none";
  $("office").style.display = which === "office" ? "" : "none";
  document.querySelectorAll("#views button").forEach(b =>
    b.classList.toggle("on", b.dataset.view === which));
  if (which === "office") drawOffice(); else Office.pause();
}
document.querySelectorAll("#views button").forEach(b =>
  (b.onclick = () => view(b.dataset.view)));

/* ---------- is it running ---------- */

// Without this the page is indistinguishable from a page that has crashed.
// A job can sit for two minutes inside one tool call, so the question "is it
// still going" has to be answered by something that moves.

let ticker = null;

function running(on, what) {
  S.running = on;
  Keys.awake(on);
  $("running").style.display = on ? "" : "none";
  $("go-icon").innerHTML = on ? "&#9632;" : "&#8593;";
  $("go").className = on ? "go stopping" : "go";
  $("go").title = on ? "stop after the current item" : "send";
  if (what) $("running-what").textContent = what;
  if (on && !ticker) {
    S.since = Date.now();
    ticker = setInterval(() => {
      const t = Math.floor((Date.now() - S.since) / 1000);
      $("clock").textContent = `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
    }, 1000);
  }
  if (!on && ticker) { clearInterval(ticker); ticker = null; }
}

/* ---------- sidebar ---------- */

async function refresh() {
  S.projects = (await (await fetch("/api/state")).json()).projects;
  const full = await (await fetch("/api/state")).json();
  S.commands = full.commands; S.runs = full.runs;
  S.engines = full.engines; S.models = full.models;
  S.model = localStorage.getItem("drydock.model") || S.model;
  const saved = localStorage.getItem("drydock.engine");
  if (saved && S.engines.some(e => e.id === saved && e.ready)) S.engine = saved;
  else S.engine = (S.engines.find(e => e.ready) || S.engines[0]).id;
  drawPicks();
  if (!S.project && S.projects.length) {
    drawSide();
    openProject(S.projects[0].path);
    return;
  }
  drawSide();
}

/* ---------- model and engine pickers ---------- */

// Two choices, kept apart because they answer different questions: which
// account pays for the work, and how hard the model should think about it.
// Both are remembered, because nobody wants to re-pick them every session.

function drawPicks() {
  const m = S.models.find(x => x.id === S.model) || S.models[0];
  const e = S.engines.find(x => x.id === S.engine) || S.engines[0];
  if (m) { S.model = m.id; $("model-label").textContent = m.label; }
  if (e) { S.engine = e.id; $("engine-label").textContent = e.short || e.label; }
}

function popup(id, rows, onpick) {
  const el = $(id);
  const open = el.style.display === "block";
  document.querySelectorAll(".pop").forEach(p => (p.style.display = "none"));
  if (open) return;
  el.innerHTML = rows.map(r => `
    <div class="pi ${r.on ? "on" : ""} ${r.disabled ? "off" : ""}" data-id="${esc(r.id)}">
      <span class="mk">${r.on ? "✓" : ""}</span>
      <div><div class="t">${esc(r.label)}</div>
      <div class="s">${esc(r.note)}</div></div></div>`).join("");
  el.style.display = "block";
  el.querySelectorAll(".pi").forEach(row => {
    row.onclick = () => {
      if (row.classList.contains("off")) return;
      onpick(row.dataset.id);
      el.style.display = "none";
      drawPicks();
      save();
    };
  });
}

function save() {
  localStorage.setItem("drydock.model", S.model);
  localStorage.setItem("drydock.engine", S.engine);
}

$("pick-model").onclick = (ev) => {
  ev.stopPropagation();
  popup("pop-model", S.models.map(m => ({
    id: m.id, label: m.label, note: m.note, on: m.id === S.model,
  })), id => (S.model = id));
};

$("pick-engine").onclick = (ev) => {
  ev.stopPropagation();
  popup("pop-engine", S.engines.map(e => ({
    id: e.id, label: e.label, on: e.id === S.engine,
    disabled: !e.ready, note: e.ready ? e.detail : e.why,
  })), id => (S.engine = id));
};

document.addEventListener("click", () =>
  document.querySelectorAll(".pop").forEach(p => (p.style.display = "none")));

/* ---------- theme ---------- */

function theme(pref) {
  localStorage.setItem("drydock.theme", pref);
  if (pref === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", pref);
  document.querySelectorAll("#theme button").forEach(b =>
    b.classList.toggle("on", b.dataset.theme === pref));
}
theme(localStorage.getItem("drydock.theme") || "system");
document.querySelectorAll("#theme button").forEach(b =>
  (b.onclick = () => theme(b.dataset.theme)));

/* ---------- settings ---------- */

const money = (n) => "$" + Number(n || 0).toFixed(2);

async function drawSettings() {
  const d = await (await fetch("/api/settings")).json();
  const a = d.account, g = d.github, u = d.usage;

  $("acct").textContent = a.headline;
  $("acct-sub").textContent = a.sub;
  $("acct-dot").className = "dot " + (a.signed_in ? "ok" : "bad");

  $("acct-detail").innerHTML = [
    ["Signed in as", a.email || "unknown"],
    ["Plan", a.plan || "none found"],
    ["Claude Code", a.version || "not installed"],
  ].map(([k, v]) => `<div><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("");

  $("use-stats").innerHTML = `
    <div class="stat"><b>${u.runs}</b><span>jobs run</span></div>
    <div class="stat"><b>${u.items}</b><span>items landed</span></div>
    <div class="stat"><b>${money(u.per_item)}</b><span>per landed item</span></div>
    <div class="stat"><b>${money(u.billed)}</b><span>billed to an API key</span></div>`;

  const lines = [];
  if (u.covered > 0) lines.push(`<p><b>${money(u.covered)}</b> of work ran on your
    Claude plan. That is what the same tokens would have cost through the API,
    and on a plan it is not charged.</p>`);
  if (u.routing_saved > 0) lines.push(`<p>Of the work that did go through the API,
    <b>${money(u.routed)}</b> was spent where <b>${money(u.at_opus)}</b> would have
    gone on Opus alone — <b>${money(u.routing_saved)} less</b>, because reading
    files and running commands does not need the expensive model and only the
    deciding does.</p>`);
  if (!lines.length) lines.push(`<p class="why">Nothing to compare yet. After a
    job finishes, this shows what it cost and what it would have cost without
    splitting the work between models.</p>`);
  $("save-box").innerHTML = lines.join("");

  $("gh-detail").innerHTML = `<div><span>Account</span><b>${
    esc(g.ready ? g.user : "not connected")}</b></div>`;
  $("gh-why").textContent = g.note;
}

$("open-settings").onclick = () => { $("sheet").style.display = "flex"; drawSettings(); };
$("close-settings").onclick = () => ($("sheet").style.display = "none");
$("sheet-bg").onclick = () => ($("sheet").style.display = "none");
document.addEventListener("keydown", e => {
  if (e.key === "Escape") $("sheet").style.display = "none";
});

function drawSide() {
  $("projects").innerHTML = S.projects.map(p => `
    <a class="side-item ${p.path === S.project ? "on" : ""}" data-path="${esc(p.path)}"
       title="${esc(p.path)}">
      ${p.pinned ? '<span class="pin">&#9679;</span>' : ""}${esc(p.name)}
      <small>${p.ok ? esc(p.toolchain) : "not a git repository"}${
        p.runs.length ? ` · ${p.runs.length} ${p.runs.length === 1 ? "job" : "jobs"}` : ""
      }</small></a>`).join("")
    || `<p class="empty">Nothing here yet. Press + and give it the path to a
        folder - a git repository, or an empty folder to start something in.</p>`;
  document.querySelectorAll("#projects .side-item").forEach(el => {
    el.onclick = () => openProject(el.dataset.path);
    el.oncontextmenu = (ev) => { ev.preventDefault(); menuFor(el.dataset.path, ev); };
  });
  drawTop();
}

// Opening a project shows what has happened in it. Somebody coming back two
// days later wants the work on this repository, not a global list of
// everything that has ever run on this machine.
function openProject(path) {
  S.project = path;
  S.key = null;
  drawSide();
  view("thread");
  const p = S.projects.find(x => x.path === path);
  if (!p) return;
  Office.reset();
  live.items.clear(); live.tests = null; live.baseline = null; live.cost = 0; live.el = {};

  $("thread-inner").innerHTML = "";
  say("", `<div class="body">
    <h3 class="proj-h">${esc(p.name)}</h3>
    <p class="why">${p.ok ? esc(p.toolchain) : "not a git repository yet"} ·
      <span class="mono dim">${esc(p.path)}</span></p>
    ${p.instructions ? `<div class="standing"><b>Standing instructions</b>
      <p>${esc(p.instructions)}</p></div>` : ""}
    <p>Type a command below. <code>/</code> shows what the crew can do. Work
    happens on its own branch, one item at a time, and nothing is changed until
    you approve the plan.</p>
  </div>`, "intro");

  if (!p.runs.length) return;
  const rows = p.runs.map(r => `
    <div class="past ${r.unfinished ? "unfinished" : ""}" data-run="${esc(r.id)}">
      <div class="when">${esc(r.started)}</div>
      <div class="what">${esc(r.task.split("\n")[0])}</div>
      <div class="outcome">${r.items
        ? `${r.done} of ${r.items} items${r.unfinished ? " · stopped partway" : ""}`
        : "nothing was planned"} · $${r.cost.toFixed(2)}</div>
      ${r.unfinished ? `<button class="btn small" data-carry="${esc(r.id)}">Carry on</button>` : ""}
    </div>`).join("");
  const msg = say("", `<div class="body"><div class="card">
    <h4>Earlier in this project</h4>${rows}</div></div>`, "dim");
  msg.querySelectorAll(".past").forEach(row => {
    row.onclick = (ev) => {
      if (ev.target.dataset.carry) return;
      replay(row.dataset.run);
    };
  });
  msg.querySelectorAll("[data-carry]").forEach(b => {
    b.onclick = (ev) => { ev.stopPropagation(); carryOn(b.dataset.carry); };
  });
  // Opening a project should start at the top of it, not at the bottom of
  // its history. say() scrolls down because a live run belongs at the end.
  $("thread").scrollTop = 0;
}

// Reading back a finished job. Built from the run on disk rather than from
// the event stream, because the stream is gone and the run is not.
async function replay(id) {
  const r = await (await fetch("/api/run/" + id)).json();
  if (!r.ok) { fail(r.reason); return; }
  S.key = id;
  $("thread-inner").innerHTML = "";
  youSaid(r.task);
  say("crew", `<div class="body"><p>${esc(r.started)} · ${esc(r.repo)}${
    r.skills.length ? ` · skill <code>${esc(r.skills[0])}</code>` : ""}</p></div>`, "dim");

  if (r.baseline) {
    const b = r.baseline;
    say("crew", `<div class="body"><p>${b.tests_run
      ? `The suite ran <b>${b.tests_run} tests</b> before anything was touched.`
      : "There was nothing to run before this started."}</p></div>`);
  }
  if (r.findings.length) {
    say("analyst", `<div class="body"><p>${r.findings.length} findings,
      ${r.risks.length} risks.</p><div class="card"><h4>What could go wrong</h4>
      ${r.risks.slice(0, 4).map(x => `<p class="why">${esc(x.slice(0, 260))}</p>`).join("")}
      </div></div>`, "dim");
  }
  if (r.items.length) {
    const by = Object.fromEntries(r.results.map(x => [x.id, x]));
    say("planner", `<div class="body"><p>${esc(r.summary)}</p>
      <div class="card"><h4>${r.items.length} items</h4><div class="steps">
      ${r.items.map(i => {
        const res = by[i.id];
        const st = res ? res.outcome : "waiting";
        return `<div class="step ${st}"><span class="mk">${MK[st] || "·"}</span>
          <span class="n mono">${i.id}</span><div><div class="ttl">${esc(i.title)}</div>
          <div class="why">${esc(res ? res.note : "never reached")}</div></div></div>`;
      }).join("")}</div></div></div>`);
  }
  const landed = r.results.filter(x => x.outcome === "done").length;
  say("crew", `<div class="body"><p><b>${landed} of ${r.items.length} items
    landed.</b> $${r.cost.toFixed(2)} of work on ${
      r.engine === "claude" ? "your Claude plan" : "an API key"}.</p>
    <p class="why">Every item that landed is its own commit on the branch
    <code>drydock/${esc(r.id)}</code>.</p></div>`);
}

// A run whose plan has items with no result was cut off - the application
// closed, the machine slept, the server restarted. The work that landed is
// still landed, because each item is its own commit, so there is nothing to
// do but start the same loop again at the next item.
async function carryOn(id) {
  const r = S.runs.find(x => x.id === id);
  if (!r) return;
  const res = await fetch("/api/resume/" + id, { method: "POST" });
  const body = await res.json();
  if (!body.ok) { fail(body.reason); return; }
  view("thread");
  $("thread-inner").innerHTML = "";
  youSaid(r.task);
  say("crew", `<div class="body"><p>Carrying on where this stopped.
    <b>${body.left} items</b> still have no result; everything that landed is
    already committed.</p></div>`, "dim");
  watch(body.key);
  running(true, "resuming");
}

function drawTop() {
  const p = S.projects.find(x => x.path === S.project);
  $("proj").textContent = p ? p.name : "no project";
  $("chain").textContent = p ? p.toolchain : "";
}

/* ---------- the project menu ---------- */

// Right-click is where anyone looks for rename and remove, so that is where
// they are. Removing a project takes it off this list and leaves the folder
// exactly where it was; nothing in this application deletes anyone's work.

function closeMenu() { $("ctx").style.display = "none"; }

function menuFor(path, ev) {
  const p = S.projects.find(x => x.path === path);
  if (!p) return;
  const rows = [
    { id: "open", label: "Open" },
    { id: "pin", label: p.pinned ? "Unpin" : "Pin to the top" },
    { id: "rename", label: "Rename" },
    { id: "instruct", label: "Standing instructions",
      note: p.instructions ? "set" : "nothing set yet" },
    { id: "copy", label: "Copy path" },
    { id: "forget", label: "Remove from drydock", danger: true,
      note: "the folder stays where it is" },
  ];
  const el = $("ctx");
  el.innerHTML = rows.map(r => `
    <div class="ci ${r.danger ? "danger" : ""}" data-do="${r.id}">
      ${esc(r.label)}${r.note ? `<i>${esc(r.note)}</i>` : ""}</div>`).join("");
  el.style.display = "block";
  // Keep it on screen when the click lands near the bottom edge.
  const h = el.offsetHeight;
  el.style.left = ev.clientX + "px";
  el.style.top = Math.min(ev.clientY, window.innerHeight - h - 12) + "px";
  el.querySelectorAll(".ci").forEach(row => {
    row.onclick = () => { closeMenu(); act(row.dataset.do, p); };
  });
}

async function patch(path, body) {
  await fetch("/api/projects", {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, ...body }),
  });
  await refresh();
}

function act(what, p) {
  if (what === "open") openProject(p.path);
  if (what === "pin") patch(p.path, { pinned: !p.pinned });
  if (what === "copy") navigator.clipboard?.writeText(p.path);
  if (what === "rename") rename(p);
  if (what === "instruct") instruct(p);
  if (what === "forget") forget(p);
}

function rename(p) {
  const el = document.querySelector(`#projects .side-item[data-path="${CSS.escape(p.path)}"]`);
  if (!el) return;
  el.innerHTML = `<input class="rename" value="${esc(p.name)}" spellcheck="false">`;
  const box = el.querySelector("input");
  box.focus(); box.select();
  const save = () => { box.onblur = null; patch(p.path, { label: box.value.trim() }); };
  box.onblur = save;
  box.onkeydown = (e) => {
    if (e.key === "Enter") save();
    if (e.key === "Escape") { box.onblur = null; drawSide(); }
  };
}

// What this person always wants true of work in this repository - the thing
// they would otherwise retype at the end of every command. It is appended to
// the task rather than hidden in a system prompt, so it shows up in the run
// record as part of what was actually asked for.
function instruct(p) {
  $("sheet").style.display = "flex";
  $("sheet").querySelector(".sheet-card").innerHTML = `
    <div class="sheet-top"><b>${esc(p.name)}</b>
      <button class="btn small ghost" id="inst-close">Close</button></div>
    <section>
      <h4>Standing instructions</h4>
      <textarea id="inst" rows="8" spellcheck="false"
        placeholder="Anything that is true of every job in this repository.&#10;&#10;For example: never touch the files under legacy/. Prefer standard library over new dependencies. British spelling in user-facing text."></textarea>
      <p class="why">Added to the end of every command you run here, and
      recorded with the run so it is clear what was asked for. Leave it empty
      and nothing is added.</p>
      <div class="row"><button class="btn" id="inst-save">Save</button>
        <span class="hint" id="inst-said"></span></div>
    </section>`;
  const box = $("inst");
  box.value = p.instructions || "";
  box.focus();
  $("inst-close").onclick = () => { $("sheet").style.display = "none"; refresh(); };
  $("inst-save").onclick = async () => {
    await patch(p.path, { instructions: box.value });
    $("inst-said").textContent = box.value.trim()
      ? "Saved. Every job here will carry this."
      : "Cleared. Nothing will be added.";
  };
}

async function forget(p) {
  const el = document.querySelector(`#projects .side-item[data-path="${CSS.escape(p.path)}"]`);
  if (!el) return;
  el.classList.add("confirming");
  el.innerHTML = `<span class="ask">Remove <b>${esc(p.name)}</b> from the list?</span>
    <span class="row"><button class="btn small" data-yes>Remove</button>
    <button class="btn small ghost" data-no>Keep</button></span>
    <small>The folder on disk is not touched.</small>`;
  el.querySelector("[data-no]").onclick = (e) => { e.stopPropagation(); drawSide(); };
  el.querySelector("[data-yes]").onclick = async (e) => {
    e.stopPropagation();
    await fetch("/api/projects", {
      method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: p.path }),
    });
    if (S.project === p.path) S.project = null;
    await refresh();
  };
}

document.addEventListener("click", closeMenu);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

/* ---------- composer ---------- */

function matching() {
  const t = $("box").value.trim();
  if (!t.startsWith("/") || t.includes(" ")) return [];
  const list = S.commands.filter(c => c.name.startsWith(t.toLowerCase()));
  // A command that is already complete and takes no argument is a finished
  // sentence. Leaving the menu open over it means Enter keeps re-picking the
  // thing that is already typed, and the job never starts.
  if (list.length === 1 && list[0].name === t.toLowerCase() && !list[0].asks) return [];
  return list;
}

function drawMenu() {
  const list = matching();
  if (!list.length) { $("menu").style.display = "none"; S.menu = -1; return; }
  if (S.menu < 0 || S.menu >= list.length) S.menu = 0;
  $("menu").style.display = "block";
  $("menu").innerHTML = list.map((c, i) => `
    <div class="mi ${i === S.menu ? "on" : ""}" data-cmd="${esc(c.name)}">
      <span class="c">${esc(c.name)}</span><span class="s">${esc(c.summary)}</span></div>`).join("");
  document.querySelectorAll(".mi").forEach(el => {
    el.onclick = () => pick(el.dataset.cmd);
  });
}

function pick(name) {
  const c = S.commands.find(x => x.name === name);
  $("box").value = c.name + (c.asks ? " " : "");
  $("menu").style.display = "none";
  $("box").focus();
  $("hint").textContent = c.asks ? `${c.name} needs ${c.asks}` : c.summary;
}

async function send() {
  const text = $("box").value.trim();
  if (!text) return;
  if (!S.project) { fail("Choose a project on the left first."); return; }
  youSaid(text);
  $("box").value = ""; $("menu").style.display = "none"; $("hint").textContent = "";
  const res = await fetch("/api/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project: S.project, command: text, engine: S.engine, model: S.model,
    }),
  });
  const body = await res.json();
  if (!body.ok) { fail(body.reason); return; }
  watch(body.key);
  running(true, "starting");
  Keys.askOnce();
}

function fail(reason) {
  $("hint").textContent = reason;
  $("hint").className = "hint bad";
  setTimeout(() => ($("hint").className = "hint"), 4000);
}

/* ---------- global keyboard ---------- */

// Everything bound here is also a thing you can click, and everything is
// listed in the sheet behind "?". A binding nobody can discover is a binding
// nobody has.
function typing(e) {
  const t = e.target;
  return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
}

function closeEverything() {
  Palette.close();
  closeMenu();
  $("sheet").style.display = "none";
  $("keys").style.display = "none";
  document.querySelectorAll(".pop").forEach(p => (p.style.display = "none"));
}

document.addEventListener("keydown", (e) => {
  if (Keys.hit(e) && e.key.toLowerCase() === "k") {
    e.preventDefault(); Palette.open ? Palette.close() : Palette.show(); return;
  }
  if (Keys.hit(e) && e.key.toLowerCase() === "b") {
    e.preventDefault(); collapse(); return;
  }
  if (Keys.hit(e) && e.key === ",") {
    e.preventDefault(); $("sheet").style.display = "flex"; drawSettings(); return;
  }
  if (Keys.hit(e) && e.key === ".") {
    e.preventDefault(); if (S.running) halt(); return;
  }
  if (Keys.hit(e) && e.key.toLowerCase() === "f") {
    e.preventDefault(); Palette.show(); return;
  }
  if (Keys.hit(e) && (e.key === "1" || e.key === "2")) {
    e.preventDefault(); view(e.key === "1" ? "thread" : "office"); return;
  }
  if (e.key === "Escape") { closeEverything(); return; }
  if (typing(e)) return;
  if (e.key === "?") { e.preventDefault(); Keys.sheet(); return; }
  // A plan waiting for a decision is the one place a bare Return means
  // something, and it is the decision anyone is most likely to be making.
  const approve = document.getElementById("approve");
  if (approve && !approve.disabled && e.key === "Enter") {
    e.preventDefault(); approve.click();
  }
});

document.querySelectorAll("[data-close-keys]").forEach(b =>
  (b.onclick = () => ($("keys").style.display = "none")));

function collapse() {
  document.body.classList.toggle("tucked");
  localStorage.setItem("drydock.sidebar",
    document.body.classList.contains("tucked") ? "tucked" : "open");
}
$("collapse").onclick = collapse;
if (localStorage.getItem("drydock.sidebar") === "tucked")
  document.body.classList.add("tucked");

$("box").addEventListener("input", drawMenu);
$("box").addEventListener("keydown", (e) => {
  const list = matching();
  if (list.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
    e.preventDefault();
    S.menu = (S.menu + (e.key === "ArrowDown" ? 1 : list.length - 1)) % list.length;
    drawMenu();
  } else if (list.length && e.key === "Tab") {
    e.preventDefault(); pick(list[S.menu].name);
  } else if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (list.length) pick(list[S.menu].name); else send();
  }
});

$("plus").onclick = () => {
  $("addbox").classList.toggle("open");
  if ($("addbox").classList.contains("open")) $("newpath").focus();
};
$("cancel").onclick = () => { $("addbox").classList.remove("open"); $("newpath").value = ""; };
$("newpath").onkeydown = (e) => { if (e.key === "Enter") $("add").click(); };

async function halt() {
  running(true, "stopping after this item");
  $("go").disabled = true;
  await fetch("/api/stop/" + S.key, { method: "POST" });
}

$("go").onclick = () => (S.running ? halt() : send());

$("add").onclick = async () => {
  const path = $("newpath").value.trim();
  if (!path) return;
  const res = await fetch("/api/projects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const body = await res.json();
  if (!body.ok) { fail(body.reason); return; }
  $("newpath").value = "";
  $("addbox").classList.remove("open");
  S.project = null;
  await Palette.wire();
refresh();
drawSettings();
};

Palette.wire();
refresh();
drawSettings();
