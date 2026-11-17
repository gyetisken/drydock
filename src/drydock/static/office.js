// The office.
//
// The earlier version redrew the whole room on every event, which is why
// nothing could move: an element replaced between two frames has no previous
// position to animate from. So the room is built once and then only changed -
// a transform here, a class there - and the browser does the moving.
//
// What it shows is the thing that is actually true about this program: work
// arrives at a desk, someone does it, and then it has to get past three
// stations that are allowed to send it back. The token you see crossing the
// floor is one item, and it reaches the board only by passing all three.

const Office = (() => {
  const W = 940, H = 640;

  const CREW = [
    { id: "Analyst",   role: "reads the repository",     shirt: "#5b8ddb", desk: 0 },
    { id: "Architect", role: "decides the shape",        shirt: "#4cb3c4", desk: 1 },
    { id: "Planner",   role: "turns it into items",      shirt: "#8a7fd0", desk: 2 },
    { id: "Engineer",  role: "one change at a time",     shirt: "#5fc08a", desk: 3 },
    { id: "Verifier",  role: "builds it, runs the suite", shirt: "#d6ac5c", gate: 0, code: true },
    { id: "Inspector", role: "reads the diff",           shirt: "#d98bb0", gate: 1, code: true },
    { id: "Reviewer",  role: "did it do the item",       shirt: "#e2796d", gate: 2 },
  ];

  const DESK_X = [148, 350, 552, 754];
  const DESK_Y = 246;
  const GATE_X = [238, 470, 702];
  const GATE_Y = 470;

  // Where someone stands when they have nothing to do. Nobody waits at a desk
  // they are not using; they wait by the window, which is also how you can
  // tell at a glance how much of the room is busy.
  const LOUNGE = [[846, 300], [880, 348], [836, 372]];

  const seat = (c) => c.desk !== undefined
    ? [DESK_X[c.desk], DESK_Y + 74]
    : [GATE_X[c.gate], GATE_Y + 74];

  const state = new Map(CREW.map(c => [c.id, { ...c, state: "idle", note: "" }]));
  let root = null, built = false;

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, ch =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

  /* ---------- the parts ---------- */

  function desk(x, y, id, w = 152) {
    return `
      <g class="ws" id="ws-${id}">
        <ellipse class="deskshadow" cx="${x}" cy="${y + 54}" rx="${w / 2}" ry="9"/>
        <rect class="deskleg" x="${x - w / 2 + 10}" y="${y + 40}" width="7" height="16"/>
        <rect class="deskleg" x="${x + w / 2 - 17}" y="${y + 40}" width="7" height="16"/>
        <rect class="desktop" x="${x - w / 2}" y="${y}" width="${w}" height="44" rx="6"/>
        <rect class="deskedge" x="${x - w / 2}" y="${y + 38}" width="${w}" height="8" rx="4"/>

        <g class="screen">
          <rect class="case" x="${x - 31}" y="${y - 40}" width="62" height="40" rx="5"/>
          <rect class="glass" x="${x - 26}" y="${y - 35}" width="52" height="30" rx="2"/>
          <g class="code">
            <rect x="${x - 21}" y="${y - 29}" width="26" height="3" rx="1.5"/>
            <rect x="${x - 21}" y="${y - 23}" width="38" height="3" rx="1.5"/>
            <rect x="${x - 21}" y="${y - 17}" width="18" height="3" rx="1.5"/>
          </g>
          <rect class="stand" x="${x - 7}" y="${y - 2}" width="14" height="6" rx="2"/>
        </g>

        <g class="deskstuff">
          <rect class="mug" x="${x + 42}" y="${y + 8}" width="13" height="15" rx="3"/>
          <path class="steam" d="M${x + 48} ${y + 4} q 4 -6 0 -12"/>
          <rect class="paper" x="${x - 62} " y="${y + 12}" width="24" height="18" rx="2"/>
        </g>
      </g>`;
  }

  function person(c) {
    const [x, y] = seat(c);
    return `
      <g class="p" id="p-${c.id}" data-id="${c.id}" transform="translate(${x},${y})">
        <ellipse class="shadow" cx="0" cy="30" rx="19" ry="7"/>
        <g class="legs">
          <rect class="leg l" x="-9" y="14" width="7" height="18" rx="3.5"/>
          <rect class="leg r" x="2"  y="14" width="7" height="18" rx="3.5"/>
        </g>
        <g class="chair"><rect x="-19" y="-4" width="38" height="34" rx="12"/></g>
        <g class="torso">
          <rect class="shirt" x="-17" y="2" width="34" height="28" rx="13" fill="${c.shirt}"/>
          <g class="arms">
            <rect class="arm l" x="-24" y="8"  width="10" height="19" rx="5" fill="${c.shirt}"/>
            <rect class="arm r" x="14"  y="8"  width="10" height="19" rx="5" fill="${c.shirt}"/>
          </g>
          <circle class="head" cx="0" cy="-12" r="12.5"/>
          <path class="hair" d="M-12.5 -14 a 12.5 12.5 0 0 1 25 0 q -12.5 -6 -25 0 z"/>
        </g>
        <g class="think">
          <circle cx="22" cy="-30" r="3"/><circle cx="31" cy="-30" r="3"/>
          <circle cx="40" cy="-30" r="3"/>
        </g>
        <g class="badge ok">
          <circle cx="24" cy="-26" r="11"/>
          <path d="M18.5 -26 l 4 4 l 7 -8"/>
        </g>
        <g class="badge no">
          <circle cx="24" cy="-26" r="11"/>
          <path d="M19 -31 l 10 10 M29 -31 l -10 10"/>
        </g>
      </g>`;
  }

  function build(host) {
    root = host;
    host.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="scene">
        <defs>
          <linearGradient id="dayglass" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" class="sky-top"/><stop offset="100%" class="sky-bottom"/>
          </linearGradient>
          <pattern id="boards" width="56" height="56" patternUnits="userSpaceOnUse">
            <rect width="56" height="56" class="floor"/>
            <path d="M0 56 H56 M56 0 V56" class="grout"/>
          </pattern>
        </defs>

        <rect x="0" y="150" width="${W}" height="${H - 150}" fill="url(#boards)"/>
        <rect x="0" y="0" width="${W}" height="150" class="wall"/>
        <rect x="0" y="144" width="${W}" height="7" class="skirting"/>

        <!-- window, and a sky that is simply a gradient pretending -->
        <g class="window">
          <rect x="36" y="26" width="150" height="96" rx="4" fill="url(#dayglass)"/>
          <rect x="36" y="26" width="150" height="96" rx="4" class="frame"/>
          <path d="M111 26 V122 M36 74 H186" class="mullion"/>
        </g>

        <!-- the board -->
        <g class="sign">
          <rect x="218" y="22" width="346" height="104" rx="8"/>
          <text x="238" y="46" class="sign-h">THE BOARD</text>
          <g id="board-items"></g>
          <text id="board-count" x="238" y="112" class="sign-s"></text>
        </g>

        <!-- the suite -->
        <g class="sign" id="suite-sign">
          <rect x="596" y="22" width="310" height="104" rx="8"/>
          <text x="616" y="46" class="sign-h">THE SUITE</text>
          <text id="suite-big" x="616" y="86" class="sign-big">-</text>
          <text id="suite-note" x="616" y="112" class="sign-s">not run yet</text>
        </g>

        <!-- the floor: desks, then the line, then the gates -->
        ${DESK_X.map((x, i) => desk(x, DESK_Y, "d" + i)).join("")}

        <g class="divider">
          <path d="M60 ${GATE_Y - 108} H880" class="dash"/>
          <text x="470" y="${GATE_Y - 118}" text-anchor="middle" class="sign-h">
            ANY OF THESE CAN SEND AN ITEM BACK</text>
        </g>

        ${GATE_X.map((x, i) => desk(x, GATE_Y, "g" + i, 136)).join("")}

        <!-- break corner -->
        <g class="props">
          <rect x="856" y="236" width="34" height="54" rx="6" class="cooler"/>
          <rect x="862" y="242" width="22" height="26" rx="3" class="coolerwater"/>
          <g class="plant">
            <rect x="862" y="566" width="38" height="30" rx="6" class="pot"/>
            <path class="leaf a" d="M881 566 q -26 -22 -12 -46 q 22 10 12 46 z"/>
            <path class="leaf b" d="M881 566 q 26 -19 14 -40 q -22 9 -14 40 z"/>
          </g>
        </g>

        <!-- one item, crossing the floor -->
        <g id="token" class="token" transform="translate(-100,-100)">
          <rect x="-13" y="-16" width="26" height="32" rx="3"/>
          <path d="M-7 -8 H7 M-7 -2 H7 M-7 4 H2" class="lines"/>
        </g>

        ${CREW.map(person).join("")}

        <!-- labels sit above everything so a walking figure never covers one -->
        ${CREW.map(c => {
          const [x, y] = seat(c);
          return `<g class="label" id="lb-${c.id}">
            <text x="${x}" y="${y + 62}" text-anchor="middle" class="nm">${esc(c.id)}</text>
            <text x="${x}" y="${y + 78}" text-anchor="middle" class="rl">${esc(c.role)}</text>
          </g>`;
        }).join("")}
      </svg>`;
    built = true;
  }

  /* ---------- movement ---------- */

  function walk(id, to, then) {
    const el = root.querySelector("#p-" + id);
    if (!el) return;
    const now = el.getAttribute("transform");
    const target = `translate(${to[0]},${to[1]})`;
    if (now === target) { if (then) then(); return; }
    el.classList.add("walking");
    el.setAttribute("transform", target);
    const done = () => {
      el.classList.remove("walking");
      el.removeEventListener("transitionend", done);
      if (then) then();
    };
    el.addEventListener("transitionend", done);
    // A transition that never fires - because the element was hidden, say -
    // must not leave someone walking on the spot forever.
    setTimeout(done, 1500);
  }

  function place() {
    let waiting = 0;
    for (const c of CREW) {
      const s = state.get(c.id);
      const el = root.querySelector("#p-" + c.id);
      const lb = root.querySelector("#lb-" + c.id);
      if (!el) continue;
      el.classList.toggle("absent", s.state === "skipped");
      el.classList.toggle("busy", s.state === "working");
      el.classList.toggle("finished", s.state === "done");
      el.classList.toggle("rejected", s.state === "failed");
      if (lb) lb.classList.toggle("faded", s.state === "skipped");

      const ws = root.querySelector("#ws-" + (c.desk !== undefined ? "d" + c.desk : "g" + c.gate));
      if (ws) {
        ws.classList.toggle("lit", s.state === "working");
        ws.classList.toggle("unused", s.state === "skipped");
      }

      if (s.state === "idle") {
        walk(c.id, LOUNGE[waiting % LOUNGE.length]);
        waiting += 1;
      } else if (s.state !== "skipped") {
        walk(c.id, seat(c));
      }
    }
  }

  /* ---------- the token ---------- */

  const ROUTE = ["Engineer", "Verifier", "Inspector", "Reviewer"];
  let trip = null;

  function stop(id) {
    const c = state.get(id);
    const [x, y] = seat(c);
    return [x, y - 54];
  }

  function moveToken(to, cls) {
    const t = root && root.querySelector("#token");
    if (!t) return;
    t.setAttribute("class", "token " + (cls || ""));
    t.setAttribute("transform", `translate(${to[0]},${to[1]})`);
  }

  function carry(from, to, cls, after) {
    moveToken(stop(from), cls);
    requestAnimationFrame(() => {
      setTimeout(() => { moveToken(stop(to), cls); if (after) setTimeout(after, 900); }, 60);
    });
  }

  /* ---------- the public parts ---------- */

  return {
    mount(host) { if (!built) build(host); place(); },

    at(id, st, note) {
      const s = state.get(id);
      if (!s) return;
      s.state = st;
      if (note !== undefined) s.note = note;
      if (built) place();
    },

    reset() {
      state.forEach(s => { s.state = "idle"; s.note = ""; });
      if (built) { place(); moveToken([-100, -100]); }
    },

    states() { return CREW.map(c => ({ ...state.get(c.id) })); },

    // One item leaving the Engineer's desk and trying to get to the board.
    send(stage) {
      if (!built) return;
      const i = ROUTE.indexOf(stage);
      if (i <= 0) { moveToken(stop("Engineer")); return; }
      carry(ROUTE[i - 1], ROUTE[i], "");
    },

    // Refused: the item goes back the way it came, in red.
    bounce(stage) {
      if (!built) return;
      trip = stage;
      moveToken(stop(stage), "bad");
      setTimeout(() => carry(stage, "Engineer", "bad"), 700);
    },

    // Accepted: the item goes up onto the board and stops being a token.
    land(n) {
      if (!built) return;
      moveToken([250 + (n % 20) * 15, 78], "landed");
      setTimeout(() => moveToken([-100, -100], ""), 900);
    },

    board(items, landed) {
      if (!built) return;
      const g = root.querySelector("#board-items");
      const count = root.querySelector("#board-count");
      if (!g) return;
      g.innerHTML = items.slice(0, 20).map((it, n) => `
        <rect class="card ${it.status}" x="${238 + n * 15}" y="62" width="11" height="26"
          rx="2"><title>${esc(it.title)}</title></rect>`).join("");
      count.textContent = items.length
        ? `${landed} of ${items.length} landed`
        : "nothing pinned up yet";
    },

    suite(now, before, started) {
      if (!built) return;
      const big = root.querySelector("#suite-big");
      const note = root.querySelector("#suite-note");
      const sign = root.querySelector("#suite-sign");
      if (!big) return;
      if (now === null) {
        big.textContent = "-";
        note.textContent = "not run yet";
        sign.setAttribute("class", "sign");
        return;
      }
      big.textContent = now;
      note.textContent = started
        ? `running now, against ${before} before anyone touched it`
        : "tests exist now, where there were none";
      sign.setAttribute("class", "sign " + (now >= before ? "held" : "dropped"));
    },
  };
})();
