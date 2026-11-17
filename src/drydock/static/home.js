// The home screen. Pick a project, type a command, read what it will do.

let state = { projects: [], commands: [], runs: [] };
let chosen = null;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function refresh() {
  state = await (await fetch("/api/state")).json();
  if (!chosen && state.projects.length) chosen = state.projects[0].path;
  drawProjects();
  drawRuns();
  $("meta").textContent = `${state.commands.length} commands installed`;
}

function drawProjects() {
  $("projects").innerHTML = state.projects.length ? state.projects.map(p => `
    <div class="project ${p.path === chosen ? "on" : ""} ${p.ok ? "" : "gone"}"
         data-path="${esc(p.path)}">
      <div class="pname">${esc(p.name)}</div>
      <div class="ppath mono">${esc(p.path)}</div>
      <div class="pmeta">${p.ok ? esc(p.toolchain) : "not a git repository any more"}
        ${p.last_used ? " · last used " + esc(p.last_used) : ""}</div>
    </div>`).join("")
    : `<p class="hint">No projects yet. Give it the path to a git repository below.</p>`;

  document.querySelectorAll(".project").forEach(el => {
    el.onclick = () => { chosen = el.dataset.path; drawProjects(); check(); };
  });
}

function drawRuns() {
  $("runs").innerHTML = state.runs.length ? state.runs.map(r => `
    <div class="runrow">
      <span class="mono dim">${esc(r.started)}</span>
      <span class="rrepo">${esc(r.repo)}</span>
      <span class="rtask">${esc(r.task)}</span>
      <span class="rnum mono">${r.done}/${r.items}</span>
      <span class="rnum mono dim">$${r.cost.toFixed(2)}</span>
    </div>`).join("")
    : `<p class="hint">Nothing run yet.</p>`;
}

function suggestions(text) {
  const t = text.trim().toLowerCase();
  if (!t.startsWith("/")) return [];
  const head = t.split(" ")[0];
  return state.commands.filter(c => c.name.startsWith(head) || head === "/");
}

function drawSuggest() {
  const list = suggestions($("command").value);
  const typed = $("command").value.trim();
  $("suggest").innerHTML = list.length && !typed.includes(" ") ? list.map(c => `
    <div class="sug" data-cmd="${esc(c.name)}">
      <span class="scmd mono">${esc(c.name)}</span>
      <span class="ssum">${esc(c.summary)}</span>
      ${c.skill ? `<span class="sskill mono">${esc(c.skill)}</span>` : ""}
    </div>`).join("") : "";
  document.querySelectorAll(".sug").forEach(el => {
    el.onclick = () => {
      const cmd = state.commands.find(c => c.name === el.dataset.cmd);
      $("command").value = cmd.name + (cmd.asks ? " " : "");
      $("suggest").innerHTML = "";
      $("command").focus();
      check();
    };
  });
}

function check() {
  const text = $("command").value.trim();
  const head = text.split(" ")[0];
  const cmd = state.commands.find(c => c.name === head);
  const rest = text.slice(head.length).trim();
  let problem = "";
  if (!chosen) problem = "Choose a project first.";
  else if (!cmd) problem = text.startsWith("/") ? "" : "Commands start with a slash.";
  else if (cmd.asks && !rest) problem = `${cmd.name} needs ${cmd.asks}.`;
  $("hint").textContent = problem || (cmd ? cmd.summary : "");
  $("go").disabled = Boolean(problem) || !cmd;
}

$("command").oninput = () => { drawSuggest(); check(); };
$("command").onkeydown = (e) => { if (e.key === "Enter" && !$("go").disabled) $("go").click(); };

$("addproject").onclick = async () => {
  const path = $("newpath").value.trim();
  if (!path) return;
  const res = await fetch("/api/projects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const body = await res.json();
  if (!body.ok) { $("hint").textContent = body.reason; return; }
  $("newpath").value = "";
  chosen = null;
  await refresh();
};

$("go").onclick = async () => {
  $("go").disabled = true;
  const res = await fetch("/api/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project: chosen, command: $("command").value }),
  });
  const body = await res.json();
  if (!body.ok) { $("hint").textContent = body.reason; $("go").disabled = false; return; }
  location.href = "/run/" + body.key;
};

refresh();
