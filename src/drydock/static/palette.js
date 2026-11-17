// One box that reaches everything: the projects, the commands, the past runs,
// and the handful of actions that have no other home.
//
// It searches all four at once on purpose. Nobody opening this box knows
// whether what they want is a project or a command; they know the word.

const Palette = (() => {
  let rows = [], cursor = 0, open = false;

  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // Subsequence matching, so "jsj" finds "JSON-java" the way a fuzzy finder
  // does. Scored so that a word-start match beats a match in the middle.
  function score(text, q) {
    if (!q) return 1;
    const t = text.toLowerCase();
    let i = 0, points = 0, run = 0;
    for (const ch of q.toLowerCase()) {
      const at = t.indexOf(ch, i);
      if (at < 0) return 0;
      const starts = at === 0 || /[\s\-_/.]/.test(t[at - 1]);
      run = at === i ? run + 1 : 0;
      points += 1 + (starts ? 4 : 0) + run;
      i = at + 1;
    }
    return points / (1 + t.length * 0.02);
  }

  function build(q) {
    const out = [];

    for (const p of S.projects) {
      out.push({
        kind: "project", label: p.name, hint: p.toolchain || "",
        run: () => { S.project = p.path; drawSide(); drawTop(); },
      });
    }
    for (const c of S.commands) {
      out.push({
        kind: "command", label: c.name, hint: c.summary,
        run: () => { view("thread"); pick(c.name); },
      });
    }
    for (const r of S.runs.slice(0, 40)) {
      out.push({
        kind: "run", label: r.task, hint: `${r.repo} · ${r.done}/${r.items} items`,
        run: () => { view("thread"); },
      });
    }
    for (const a of [
      { label: "Settings", hint: "account, usage, appearance, GitHub",
        run: () => { el("sheet").style.display = "flex"; drawSettings(); } },
      { label: "Keyboard shortcuts", hint: "every binding in one list",
        run: () => Keys.sheet() },
      { label: "Office", hint: "watch the crew work", run: () => view("office") },
      { label: "Thread", hint: "read what happened", run: () => view("thread") },
      { label: "Add a project", hint: "point at a folder, empty or not",
        run: () => el("plus").click() },
      { label: "Stop the running job", hint: "at the next safe point",
        run: () => { if (S.running) halt(); } },
    ]) out.push({ kind: "do", ...a });

    return out
      .map(r => ({ ...r, s: score(r.label + " " + (r.hint || ""), q) }))
      .filter(r => r.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 40);
  }

  function draw() {
    el("pal-list").innerHTML = rows.length
      ? rows.map((r, i) => `
          <div class="pal-row ${i === cursor ? "on" : ""}" data-i="${i}">
            <span class="kind ${r.kind}">${r.kind}</span>
            <span class="lab">${esc(r.label)}</span>
            <span class="hint">${esc(r.hint || "")}</span>
          </div>`).join("")
      : `<p class="empty">Nothing matches that.</p>`;
    el("pal-list").querySelectorAll(".pal-row").forEach(row => {
      row.onmousemove = () => { cursor = +row.dataset.i; mark(); };
      row.onclick = () => choose();
    });
  }

  function mark() {
    el("pal-list").querySelectorAll(".pal-row").forEach((row, i) =>
      row.classList.toggle("on", i === cursor));
  }

  function choose() {
    const r = rows[cursor];
    close();
    if (r) r.run();
  }

  function show() {
    open = true;
    el("palette").style.display = "flex";
    el("pal-q").value = "";
    rows = build(""); cursor = 0; draw();
    el("pal-q").focus();
  }

  function close() { open = false; el("palette").style.display = "none"; }

  function wire() {
    el("pal-q").addEventListener("input", (e) => {
      rows = build(e.target.value); cursor = 0; draw();
    });
    el("pal-q").addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); cursor = (cursor + 1) % rows.length; mark(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); cursor = (cursor - 1 + rows.length) % rows.length; mark(); }
      else if (e.key === "Enter") { e.preventDefault(); choose(); }
      else if (e.key === "Escape") { e.preventDefault(); close(); }
    });
    el("pal-bg").onclick = close;
  }

  return { show, close, wire, get open() { return open; } };
})();
