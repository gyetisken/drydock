// One window. The sidebar picks a project, the thread shows what the crew did,
// the composer starts the next job. Everything in the thread arrived as an
// event from the server, so nothing here can claim progress that was not made.

const S = { projects: [], commands: [], runs: [], project: null, key: null, menu: -1 };
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
  live.el.stats.innerHTML = `
    <div class="stat ${now < b.tests ? "bad" : "ok"}"><b>${now}</b><span>tests running</span></div>
    <div class="stat"><b>${b.tests}</b><span>before any change</span></div>
    <div class="stat"><b>${landed}</b><span>items landed</span></div>
    <div class="stat"><b>$${live.cost.toFixed(2)}</b><span>spent</span></div>`;
  $("spend").textContent = `$${live.cost.toFixed(2)}`;
}

function toolLine(agent, detail) {
  if (!live.el.tools) return;
  const box = live.el.tools.querySelector(".lines");
  const row = document.createElement("div");
  row.className = "toolline";
  row.textContent = `${agent}  ${detail}`;
  box.appendChild(row);
  live.el.tools.querySelector("summary").textContent =
    `${box.children.length} steps taken`;
}

const on = {
  "run.started": (e) => {
    say("crew", `<div class="body"><p>Looking at <b>${esc(e.repo)}</b> ·
      ${esc(e.toolchain)}${e.skills.length ? ` · skill <code>${esc(e.skills[0])}</code>` : ""}</p></div>`);
    live.el.tools = say("", `<details class="tools"><summary>working</summary>
      <div class="lines"></div></details>`).querySelector("details").parentElement;
  },
  "baseline": (e) => {
    live.baseline = e;
    const msg = say("crew", `<div class="body"><p>${e.green
      ? `The suite is green before anything is touched: <b>${e.tests} tests</b> pass.`
      : `The suite is <b>not green</b>: ${e.failed} failing. Nothing after this can be called a regression.`}</p>
      <div class="card"><div class="stats"></div></div></div>`);
    live.el.stats = msg.querySelector(".stats");
    renderStats();
  },
  "agent.tool": (e) => toolLine(e.agent, e.detail),
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
    e.items.forEach(i => live.items.set(i.id,
      { ...i, status: "waiting", note: i.rationale.split(". ")[0] }));
    live.cost = e.cost || 0;
    renderPlan(); renderStats();
    msg.querySelector("#approve").onclick = async (ev) => {
      ev.target.disabled = true;
      msg.querySelector("#planhint").textContent = "working, one item at a time";
      await fetch("/api/approve/" + S.key, { method: "POST" });
    };
  },
  "item.start": (e) => {
    const i = live.items.get(e.id);
    if (i) { i.status = "working"; i.note = "working on it"; renderPlan(); }
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
    renderStats();
    if (e.outcome !== "done") {
      say("crew", `<div class="body"><p><b>Item ${e.id} was rolled back.</b>
        ${esc(e.note)}</p><p class="why">The tree is back where it was. Nothing after
        this item was attempted, because each one assumes the last one landed.</p></div>`);
    }
  },
  "run.summary": (e) => {
    say("crew", `<div class="body"><p><b>${e.done} of ${e.total} items landed.</b>
      $${e.cost.toFixed(2)} spent. The work is on its own branch; nothing touched
      your main branch.</p></div>`);
  },
  "run.error": (e) => say("crew", `<div class="body"><p class="why">${esc(e.detail)}</p></div>`),
  "awaiting.approval": () => {},
};

function watch(key) {
  S.key = key;
  live.items.clear(); live.tests = null; live.baseline = null; live.cost = 0; live.el = {};
  const src = new EventSource("/api/stream/" + key);
  src.onmessage = (m) => {
    const e = JSON.parse(m.data);
    (on[e.kind] || (() => {}))(e);
  };
}

/* ---------- sidebar ---------- */

async function refresh() {
  S.projects = (await (await fetch("/api/state")).json()).projects;
  const full = await (await fetch("/api/state")).json();
  S.commands = full.commands; S.runs = full.runs; S.engines = full.engines;
  drawEngines();
  if (!S.project && S.projects.length) S.project = S.projects[0].path;
  drawSide();
}

function drawEngines() {
  const el = $("engine");
  if (!el || el.options.length) return;
  el.innerHTML = S.engines.map(e =>
    `<option value="${esc(e.id)}" ${e.ready ? "" : "disabled"}>${esc(e.label)}${
      e.ready ? "" : " — " + esc(e.why)}</option>`).join("");
  const ready = S.engines.find(e => e.ready);
  if (ready) el.value = ready.id;
}

function drawSide() {
  $("projects").innerHTML = S.projects.map(p => `
    <a class="side-item ${p.path === S.project ? "on" : ""}" data-path="${esc(p.path)}">
      ${esc(p.name)}<small>${p.ok ? esc(p.toolchain) : "not a git repository"}</small></a>`).join("")
    || `<p class="hint" style="padding:0 10px">No projects yet.</p>`;
  document.querySelectorAll("#projects .side-item").forEach(el => {
    el.onclick = () => { S.project = el.dataset.path; drawSide(); drawTop(); };
  });
  $("history").innerHTML = S.runs.slice(0, 10).map(r => `
    <a class="side-item">${esc(r.task.slice(0, 34))}<small>${esc(r.repo)} · ${r.done}/${r.items} · $${r.cost.toFixed(2)}</small></a>`).join("");
  drawTop();
}

function drawTop() {
  const p = S.projects.find(x => x.path === S.project);
  $("proj").textContent = p ? p.name : "no project";
  $("chain").textContent = p ? p.toolchain : "";
}

/* ---------- composer ---------- */

function matching() {
  const t = $("box").value.trim();
  if (!t.startsWith("/") || t.includes(" ")) return [];
  return S.commands.filter(c => c.name.startsWith(t.toLowerCase()));
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
      project: S.project, command: text, engine: $("engine").value,
    }),
  });
  const body = await res.json();
  if (!body.ok) { fail(body.reason); return; }
  watch(body.key);
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

$("add").onclick = async () => {
  const path = $("newpath").value.trim();
  if (!path) return;
  const res = await fetch("/api/projects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const body = await res.json();
  if (!body.ok) { fail(body.reason); return; }
  $("newpath").value = ""; S.project = null;
  await refresh();
};

refresh();
