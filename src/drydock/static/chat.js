// One window. The sidebar picks a project, the thread shows what the crew did,
// the composer starts the next job. Everything in the thread arrived as an
// event from the server, so nothing here can claim progress that was not made.

const S = { projects: [], commands: [], runs: [], project: null, key: null, menu: -1,
  engines: [], models: [], engine: "claude", model: "opus" };
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
  live.el.plan.querySelector(".steps").innerHTML =
    [...live.items.values()].map(i => `
      <div class="step ${i.status}">
        <span class="mk">${MK[i.status] || "·"}</span>
        <span class="n mono">${i.id}</span>
        <div><div class="ttl">${esc(i.title)}</div>
        ${i.note ? `<div class="why">${esc(i.note)}</div>` : ""}</div>
      </div>`).join("");
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
    if (i) { i.status = "working"; i.note = "working on it"; renderPlan(); }
    Office.at("Engineer", "working", `item ${e.id}: ${e.title}`);
    Office.send("Engineer");
    drawOffice();
  },
  "gate": (e) => {
    const who = e.who === "inspector" ? "Inspector" : "Reviewer";
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
  "stopping": (e) => {
    say("crew", `<div class="body"><p>Stopping. ${esc(e.note)}</p></div>`, "dim");
  },
  "run.summary": (e) => {
    running(false);
    $("go").disabled = false;
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
  "run.error": (e) => (running(false), say("crew", `<div class="body"><p class="why">${esc(e.detail)}</p></div>`)),
  "awaiting.approval": () => running(false),
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
  if (!S.project && S.projects.length) S.project = S.projects[0].path;
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
      <small>${p.ok ? esc(p.toolchain) : "not a git repository"}</small></a>`).join("")
    || `<p class="empty">Nothing here yet. Press + and give it the path to a
        git repository, empty or not.</p>`;
  document.querySelectorAll("#projects .side-item").forEach(el => {
    el.onclick = () => { S.project = el.dataset.path; drawSide(); drawTop(); };
    el.oncontextmenu = (ev) => { ev.preventDefault(); menuFor(el.dataset.path, ev); };
  });
  $("history").innerHTML = S.runs.slice(0, 12).map(r => `
    <a class="side-item" title="${esc(r.task)}">${esc(r.task)}<small>${esc(r.repo)} · ${r.done}/${r.items} items · $${r.cost.toFixed(2)}</small></a>`).join("")
    || `<p class="empty">No runs yet.</p>`;
  drawTop();
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
  if (what === "open") { S.project = p.path; drawSide(); drawTop(); }
  if (what === "pin") patch(p.path, { pinned: !p.pinned });
  if (what === "copy") navigator.clipboard?.writeText(p.path);
  if (what === "rename") rename(p);
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
}

function fail(reason) {
  $("hint").textContent = reason;
  $("hint").className = "hint bad";
  setTimeout(() => ($("hint").className = "hint"), 4000);
}

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
  await refresh();
drawSettings();
};

refresh();
drawSettings();
