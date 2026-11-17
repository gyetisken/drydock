// The page holds no logic of its own. Every number on it arrived in an event,
// which is what keeps it honest: it cannot show progress the run did not make.

const DESKS = ["Analyst", "Planner", "Engineer"];
const MARKS = { done: "✓", reverted: "✗", blocked: "✗", working: "▸", waiting: "·" };

const state = { items: new Map(), baseline: null, tests: null, cost: 0 };

const $ = (id) => document.getElementById(id);

function desk(name) {
  return $("desk-" + name.toLowerCase());
}

function setDesk(name, phase, note, action) {
  const el = desk(name);
  if (!el) return;
  el.className = "desk " + (phase || "");
  if (note !== undefined) el.querySelector(".note").textContent = note;
  if (action !== undefined) el.querySelector(".act").textContent = action;
}

function scoreboard() {
  const b = state.baseline;
  if (!b) return;
  const now = state.tests === null ? b.tests : state.tests;
  const delta = now - b.tests;
  $("scores").innerHTML = `
    <div class="score ${delta < 0 ? "bad" : "ok"}">
      <b>${now}</b><span>tests running${delta ? ` (${delta > 0 ? "+" : ""}${delta})` : ""}</span>
    </div>
    <div class="score"><b>${b.tests}</b><span>baseline, before any change</span></div>
    <div class="score"><b>${[...state.items.values()].filter(i => i.status === "done").length}</b>
      <span>items landed</span></div>
    <div class="score"><b>$${state.cost.toFixed(2)}</b><span>spent so far</span></div>`;
}

function renderItems() {
  $("items").innerHTML = [...state.items.values()].map(i => `
    <div class="item ${i.status}">
      <span class="mark">${MARKS[i.status] || "·"}</span>
      <span class="num mono">${i.id}</span>
      <div>
        <div class="title">${escape(i.title)}</div>
        ${i.note ? `<div class="why">${escape(i.note)}</div>` : ""}
      </div>
    </div>`).join("");
}

function log(who, text) {
  const line = document.createElement("div");
  line.innerHTML = `<span class="t mono">${new Date().toTimeString().slice(0, 8)}</span>` +
                   `<span class="who">${escape(who)}</span>${escape(text)}`;
  const feed = $("feed");
  feed.appendChild(line);
  feed.scrollTop = feed.scrollHeight;
}

function escape(s) {
  return String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

const handlers = {
  "run.started": (e) => {
    $("task").textContent = e.task;
    $("meta").textContent = `${e.repo} · ${e.toolchain}` +
      (e.skills?.length ? ` · skills: ${e.skills.join(", ")}` : " · no skills");
  },
  "baseline": (e) => {
    state.baseline = e;
    scoreboard();
    setDesk("Analyst", "working", e.green
      ? `${e.tests} tests pass before anything is touched`
      : `the suite is not green: ${e.failed} failing`);
  },
  "agent.state": (e) => setDesk(e.agent, e.state, e.note),
  "agent.tool": (e) => {
    setDesk(e.agent, "working", undefined, e.detail);
    log(e.agent, e.detail);
  },
  "plan.ready": (e) => {
    $("summary").textContent = e.summary;
    state.cost = e.cost || 0;
    e.items.forEach(i => state.items.set(i.id, { ...i, status: "waiting", note: i.rationale.split(". ")[0] }));
    renderItems();
    scoreboard();
  },
  "awaiting.approval": () => {
    $("approve").disabled = false;
    $("hint").textContent = "Read the plan. Nothing is changed until you approve it.";
  },
  "item.start": (e) => {
    const item = state.items.get(e.id);
    if (item) { item.status = "working"; item.note = "working on it"; renderItems(); }
  },
  "item.done": (e) => {
    const item = state.items.get(e.id);
    if (item) {
      item.status = e.outcome;
      item.note = e.note + (e.attempts > 1 ? ` (after ${e.attempts} attempts)` : "");
      renderItems();
    }
    const m = /(\d+) tests/.exec(e.note || "");
    if (m) state.tests = parseInt(m[1], 10);
    state.cost = e.cost || state.cost;
    scoreboard();
  },
  "run.summary": (e) => {
    $("hint").textContent = `${e.done} of ${e.total} items landed. $${e.cost.toFixed(2)}.`;
    $("approve").disabled = true;
  },
  "run.error": (e) => {
    setDesk("Engineer", "failed", e.detail);
    $("hint").textContent = e.detail;
  },
};

function connect() {
  $("desks").innerHTML = DESKS.map(name => `
    <div class="desk" id="desk-${name.toLowerCase()}">
      <div class="who"><span class="dot"></span>${name}</div>
      <div class="note">waiting</div>
      <div class="act mono"></div>
    </div>`).join("");

  const key = location.pathname.split("/").pop();
  const source = new EventSource("/api/stream/" + key);
  source.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    (handlers[event.kind] || (() => {}))(event);
  };
}

$("approve").onclick = async () => {
  $("approve").disabled = true;
  $("hint").textContent = "working the plan, one item at a time";
  await fetch("/api/approve/" + location.pathname.split("/").pop(), { method: "POST" });
};

connect();
