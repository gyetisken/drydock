// The office, as pixels.
//
// Everything on screen is a 16x16 tile or a 16x32 sprite from a CC0 art pack
// (see sprites/CREDITS.md), drawn to a canvas with smoothing off and scaled by
// a whole number, which is the only way pixel art stays pixel art.
//
// What it shows is what is actually happening. A character walks to a desk
// because that station started working; the monitor lights because it is still
// working; the paper crossing the floor is one item on its way from the
// engineer to the three stations that are allowed to send it back. Nothing
// here is decoration that moves on a timer - if something is moving, the crew
// moved it.

const Office = (() => {
  const TILE = 16;        // the art's own grid
  const COLS = 34, ROWS = 20;
  const W = COLS * TILE, H = ROWS * TILE;

  const SPRITES = {
    body: "char/body.png", top: "char/top.png", pants: "char/pants.png",
    shoes: "char/shoes.png",
    hair_short: "char/hair_short.png", hair_bob: "char/hair_bob.png",
    hair_spiky: "char/hair_spiky.png", hair_parted: "char/hair_parted.png",
    hair_mop: "char/hair_mop.png", hair_long_waves: "char/hair_long_waves.png",
    hair_slicked_back: "char/hair_slicked_back.png",
    floor: "prop/floor.png", wall: "prop/wall.png",
    desk: "prop/desk.png", chair: "prop/chair.png",
    pc_off: "prop/pc_off.png", pc_on1: "prop/pc_on1.png",
    pc_on2: "prop/pc_on2.png", pc_on3: "prop/pc_on3.png",
    whiteboard: "prop/whiteboard.png", plant: "prop/plant.png",
    plant_big: "prop/plant_big.png", coffee: "prop/coffee.png",
    clock: "prop/clock.png", bookshelf: "prop/bookshelf.png",
  };

  // Sheet geometry, from the pack: 8 columns by 3 rows of 16x32 frames.
  const FW = 16, FH = 32;
  const ROW = { down: 0, up: 1, right: 2 };
  const WALK = [0, 1, 2, 1];
  const TYPE = [3, 4];
  const READ = [5, 6];
  const SEATED = 7;

  // Desks sit on the tile grid. x is the desk's left tile, y its top tile; the
  // chair and the person go one row below, which is how a top-down room reads.
  const CREW = [
    { id: "Analyst",   role: "reads the repository",      tint: "#5b8ddb", hair: "short",        x: 2,  y: 6 },
    { id: "Architect", role: "decides the shape",         tint: "#4cb3c4", hair: "bob",          x: 9,  y: 6 },
    { id: "Planner",   role: "turns it into items",       tint: "#8a7fd0", hair: "parted",       x: 16, y: 6 },
    { id: "Engineer",  role: "one change at a time",      tint: "#5fc08a", hair: "spiky",        x: 23, y: 6 },
    { id: "Verifier",  role: "builds it, runs the suite", tint: "#d6ac5c", hair: "mop",          x: 3,  y: 13, code: true },
    { id: "Inspector", role: "reads the diff",            tint: "#d98bb0", hair: "long_waves",   x: 12, y: 13, code: true },
    { id: "Reviewer",  role: "did it do the item",        tint: "#e2796d", hair: "slicked_back", x: 21, y: 13 },
  ];

  // Where somebody stands when they have nothing to do. Nobody waits at a
  // desk they are not using, so how much of the room is busy is legible from
  // across the room - but only if there is a spot for every one of them.
  // Three spots and seven people meant four invisible people standing inside
  // the other three.
  const LOUNGE = [
    [28.4, 9.4], [30.8, 9.0], [27.9, 11.3],
    [30.3, 11.8], [28.8, 13.6], [31.2, 13.9], [29.6, 15.6],
  ];

  const art = {};
  const tinted = new Map();
  let canvas = null, ctx = null, raf = null, started = 0;
  let board = { items: [], landed: 0 };
  let suite = { now: null, before: 0, started: false };

  const state = new Map(CREW.map(c => [c.id, {
    ...c,
    state: "idle", note: "",
    // Where the sprite actually is, in pixels, and where it is trying to get
    // to. Walking is this pair not yet being equal.
    px: (c.x + 1.5) * TILE, py: (c.y + 2) * TILE + 14,
    tx: (c.x + 1.5) * TILE, ty: (c.y + 2) * TILE + 14,
    face: "up",
  }]));

  // Where somebody actually sits. The chair is the tile directly below the
  // desk, and the sprite's feet land 10px under its anchor, so the anchor has
  // to sit low enough that the body lands on the seat rather than on the
  // floor behind it. Getting this wrong is immediately obvious: everyone was
  // standing in front of their chair with their back to the monitor.
  const SIT_Y = 14;
  const seat = (c) => [(c.x + 1.5) * TILE, (c.y + 2) * TILE + SIT_Y];

  /* ---------- loading ---------- */

  function load(done) {
    const names = Object.keys(SPRITES);
    let left = names.length;
    names.forEach(n => {
      const img = new Image();
      img.onload = img.onerror = () => { if (--left === 0) done(); };
      img.src = "/static/sprites/" + SPRITES[n];
      art[n] = img;
    });
  }

  /* ---------- drawing ---------- */

  function tile(img, x, y, w = 1, h = 1) {
    if (img && img.complete && img.naturalWidth) {
      ctx.drawImage(img, x * TILE, y * TILE, w * TILE, h * TILE);
    }
  }

  // The wall sheet is a 4x4 bitmask grid of 16x32 pieces; mask 10 is the piece
  // with a neighbour either side, which is the only one that tiles a long run
  // without drawing its own end caps. Found by rendering all sixteen and
  // looking, which took less time than reading the packing code.
  //
  // A rug was tried here and taken out again: the carpet sheet is darker than
  // the floor, so under every desk sat a band that read as a hole. A bad
  // decoration removed beats a third attempt at it.
  const WALL_RUN = { sx: 32, sy: 64 };

  // The art is greyscale, so the room's colour is this program's, not the
  // pack's, and it follows the theme like everything else.
  function wash(img, colour, key, mode = "multiply") {
    if (tinted.has(key)) return tinted.get(key);
    // An image that has not arrived yet has no dimensions, and caching the
    // empty canvas made from it means it never arrives at all.
    if (!img || !img.complete || !img.naturalWidth) return null;
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0);
    g.globalCompositeOperation = mode;
    g.fillStyle = colour;
    g.fillRect(0, 0, c.width, c.height);
    g.globalCompositeOperation = "destination-in";
    g.drawImage(img, 0, 0);
    tinted.set(key, c);
    return c;
  }

  function room() {
    const dark = !document.documentElement.getAttribute("data-theme")
      ? matchMedia("(prefers-color-scheme: dark)").matches
      : document.documentElement.getAttribute("data-theme") === "dark";
    const floorHue = dark ? "#6d5f54" : "#cbb9a6";
    const wallHue  = dark ? "#55627d" : "#cfd8e6";

    const floor = wash(art.floor, floorHue, "f" + floorHue);
    const wall = wash(art.wall, wallHue, "w" + wallHue);

    if (floor) {
      for (let y = 2; y < ROWS; y++) {
        for (let x = 0; x < COLS; x++) ctx.drawImage(floor, x * TILE, y * TILE);
      }
    }
    if (wall) {
      for (let x = 0; x < COLS; x++) {
        ctx.drawImage(wall, WALL_RUN.sx, WALL_RUN.sy, 16, 32, x * TILE, 0, TILE, TILE * 2);
      }
    }

    tile(art.bookshelf, 0, 1, 2, 1);
    tile(art.clock, 2, 0, 1, 2);
    tile(art.coffee, 30, 2, 1, 1);
    tile(art.plant_big, 32, 2, 2, 3);
    tile(art.desk, 14, 10, 3, 2);
    tile(art.coffee, 15, 9, 1, 1);
    tile(art.plant, 0, 17, 1, 2);
    tile(art.plant, 32, 17, 1, 2);
  }

  function boardSign() {
    // The wall art is busy and the numbers have to be read at a glance, so
    // they sit on their own strip rather than on top of brickwork.
    ctx.globalAlpha = 0.9;
    ctx.fillStyle = css("--panel");
    roundRect(120, 5, 190, 28, 4); ctx.fill();
    roundRect(318, 5, 180, 28, 4); ctx.fill();
    ctx.globalAlpha = 1;

    // The whiteboard is the plan: one mark per item, and that is the only
    // progress reported anywhere in this room. No bar, no percentage - a job
    // of eleven items that must each hold a test suite has no halfway point.
    tile(art.whiteboard, 4, 0, 2, 2);
    tile(art.whiteboard, 31, 0, 2, 2);

    ctx.imageSmoothingEnabled = true;
    ctx.textAlign = "left";

    ctx.font = "600 7px ui-sans-serif, -apple-system, sans-serif";
    ctx.fillStyle = css("--faint");
    ctx.fillText("THE PLAN", 128, 15);
    board.items.slice(0, 22).forEach((it, n) => {
      ctx.fillStyle = { done: css("--ok"), working: css("--live"),
        reverted: css("--bad"), blocked: css("--bad") }[it.status] || css("--line");
      ctx.fillRect(176 + (n % 11) * 8, 10 + Math.floor(n / 11) * 7, 6, 5);
    });
    ctx.fillStyle = css("--muted");
    ctx.font = "8px ui-sans-serif, -apple-system, sans-serif";
    ctx.fillText(board.items.length
      ? `${board.landed} of ${board.items.length} landed`
      : "nothing pinned up yet", 128, 29);

    ctx.font = "600 7px ui-sans-serif, -apple-system, sans-serif";
    ctx.fillStyle = css("--faint");
    ctx.fillText("THE SUITE", 326, 15);
    ctx.fillStyle = suite.now === null ? css("--muted")
      : suite.now >= suite.before ? css("--ok") : css("--bad");
    ctx.font = "700 15px ui-sans-serif, -apple-system, sans-serif";
    ctx.fillText(suite.now === null ? "-" : String(suite.now), 326, 29);
    ctx.font = "8px ui-sans-serif, -apple-system, sans-serif";
    ctx.fillStyle = css("--muted");
    ctx.fillText(suite.now === null ? "not run yet"
      : suite.started ? `of ${suite.before} before` : "where there were none",
      suite.now === null ? 348 : 356, 28);
    ctx.imageSmoothingEnabled = false;
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function desks() {
    for (const c of CREW) {
      const s = state.get(c.id);
      const dim = s.state === "skipped";
      ctx.globalAlpha = dim ? 0.35 : 1;
      tile(art.desk, c.x, c.y, 3, 2);
      const screen = s.state === "working"
        ? art["pc_on" + (1 + (Math.floor(started / 180) % 3))]
        : art.pc_off;
      tile(screen, c.x + 1, c.y - 1, 1, 2);
      // Drawn before anyone sits down, so the chair is behind the body and
      // its back shows below them.
      tile(art.chair, c.x + 1, c.y + 2, 1, 2);
      ctx.globalAlpha = 1;
    }
  }

  function frameFor(s) {
    if (s.px !== s.tx || s.py !== s.ty) {
      return WALK[Math.floor(started / 130) % WALK.length];
    }
    if (s.state === "working") {
      return s.code
        ? READ[Math.floor(started / 320) % 2]
        : TYPE[Math.floor(started / 150) % 2];
    }
    return SEATED;
  }

  function people() {
    // Painter's order: whoever is further down the room is drawn last, so a
    // character walking in front of a desk is actually in front of it.
    const order = [...state.values()].sort((a, b) => a.py - b.py);
    for (const s of order) {
      if (s.state === "skipped") continue;
      const col = frameFor(s);
      const row = ROW[s.face] ?? ROW.down;
      const sx = col * FW, sy = row * FH;
      const dx = Math.round(s.px - FW / 2), dy = Math.round(s.py - FH + 10);
      const flip = s.face === "left";

      ctx.save();
      if (flip) { ctx.translate(dx + FW, dy); ctx.scale(-1, 1); ctx.translate(-dx, -dy); }
      for (const layer of ["body", "pants", "shoes"]) {
        if (art[layer].complete) ctx.drawImage(art[layer], sx, sy, FW, FH, dx, dy, FW, FH);
      }
      const shirt = wash(art.top, s.tint, "s" + s.tint);
      if (shirt) ctx.drawImage(shirt, sx, sy, FW, FH, dx, dy, FW, FH);
      const hair = art["hair_" + s.hair];
      if (hair && hair.complete) ctx.drawImage(hair, sx, sy, FW, FH, dx, dy, FW, FH);
      ctx.restore();

      badge(s, dx, dy);
    }
  }

  function badge(s, dx, dy) {
    if (s.state !== "done" && s.state !== "failed") return;
    const x = dx + 15, y = dy + 5;
    ctx.imageSmoothingEnabled = true;
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fillStyle = s.state === "done" ? css("--ok") : css("--bad");
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1.6;
    ctx.lineCap = "round";
    ctx.beginPath();
    if (s.state === "done") { ctx.moveTo(x - 3, y); ctx.lineTo(x - 1, y + 2.4); ctx.lineTo(x + 3.2, y - 2.6); }
    else { ctx.moveTo(x - 2.6, y - 2.6); ctx.lineTo(x + 2.6, y + 2.6);
           ctx.moveTo(x + 2.6, y - 2.6); ctx.lineTo(x - 2.6, y + 2.6); }
    ctx.stroke();
    ctx.imageSmoothingEnabled = false;
  }

  /* ---------- the item, crossing the floor ---------- */

  const ROUTE = ["Engineer", "Verifier", "Inspector", "Reviewer"];
  const paper = { on: false, x: 0, y: 0, tx: 0, ty: 0, bad: false, fading: 0 };

  function handOff(to, bad) {
    const c = state.get(to);
    if (!c) return;
    paper.on = true;
    paper.bad = !!bad;
    paper.tx = (c.x + 1.5) * TILE;
    paper.ty = (c.y - 0.4) * TILE;
    paper.fading = 0;
  }

  function drawPaper() {
    if (!paper.on) return;
    ctx.imageSmoothingEnabled = true;
    ctx.globalAlpha = paper.fading ? Math.max(0, 1 - paper.fading / 40) : 1;
    ctx.fillStyle = css("--panel");
    ctx.strokeStyle = paper.bad ? css("--bad") : css("--accent");
    ctx.lineWidth = 1.4;
    const x = Math.round(paper.x), y = Math.round(paper.y);
    ctx.fillRect(x - 5, y - 7, 10, 13);
    ctx.strokeRect(x - 5, y - 7, 10, 13);
    ctx.strokeStyle = paper.bad ? css("--bad") : css("--accent");
    ctx.lineWidth = 1;
    for (let i = 0; i < 3; i++) {
      ctx.beginPath(); ctx.moveTo(x - 3, y - 4 + i * 3.4);
      ctx.lineTo(x + (i === 2 ? 0 : 3), y - 4 + i * 3.4); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.imageSmoothingEnabled = false;
  }

  /* ---------- the loop ---------- */

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
      || "#888";
  }

  function step(dt) {
    for (const s of state.values()) {
      const dx = s.tx - s.px, dy = s.ty - s.py;
      const d = Math.hypot(dx, dy);
      if (d > 0.5) {
        const speed = 0.055 * dt;
        s.px += (dx / d) * Math.min(speed, d);
        s.py += (dy / d) * Math.min(speed, d);
        s.face = Math.abs(dx) > Math.abs(dy)
          ? (dx > 0 ? "right" : "left")
          : (dy > 0 ? "down" : "up");
      } else {
        s.px = s.tx; s.py = s.ty;
        // Arrived. At a desk you face the screen, which is up the room; in
        // the lounge you face the room, which is down it.
        s.face = s.state === "idle" ? "down" : "up";
      }
    }
    if (paper.on) {
      const dx = paper.tx - paper.x, dy = paper.ty - paper.y;
      const d = Math.hypot(dx, dy);
      if (d > 1) {
        const speed = 0.11 * dt;
        paper.x += (dx / d) * Math.min(speed, d);
        paper.y += (dy / d) * Math.min(speed, d);
      } else if (paper.fading) {
        paper.fading += 1;
        if (paper.fading > 40) paper.on = false;
      }
    }
  }

  let last = 0;
  function frame(t) {
    const dt = Math.min(48, t - last || 16);
    last = t; started = t;
    step(dt);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, W, H);
    room();
    boardSign();
    desks();
    drawPaper();
    people();
    raf = requestAnimationFrame(frame);
  }

  function retarget() {
    let waiting = 0;  // never exceeds CREW.length, and LOUNGE has one each
    for (const c of CREW) {
      const s = state.get(c.id);
      if (s.state === "idle") {
        // Each person keeps the same spot for as long as they are idle, so
        // the room does not reshuffle every time somebody else sits down.
        const [lx, ly] = LOUNGE[waiting];
        waiting += 1;
        s.tx = lx * TILE; s.ty = ly * TILE;
      } else if (s.state !== "skipped") {
        const [sx, sy] = seat(c);
        s.tx = sx; s.ty = sy;
      }
    }
  }

  return {
    mount(host) {
      if (canvas) { if (!raf) raf = requestAnimationFrame(frame); return; }
      canvas = document.createElement("canvas");
      canvas.width = W; canvas.height = H;
      canvas.className = "scene";
      host.innerHTML = "";
      host.appendChild(canvas);
      ctx = canvas.getContext("2d");
      load(() => { retarget(); raf = requestAnimationFrame(frame); });
    },

    pause() { if (raf) { cancelAnimationFrame(raf); raf = null; } },

    at(id, st, note) {
      const s = state.get(id);
      if (!s) return;
      s.state = st;
      if (note !== undefined) s.note = note;
      retarget();
    },

    reset() {
      state.forEach(s => {
        s.state = "idle"; s.note = "";
      });
      paper.on = false;
      retarget();
    },

    states() {
      return CREW.map(c => {
        const s = state.get(c.id);
        return { id: c.id, role: c.role, code: c.code, state: s.state, note: s.note };
      });
    },

    send(stage) {
      const i = ROUTE.indexOf(stage);
      if (i < 0) return;
      if (i === 0) {
        const c = state.get("Engineer");
        paper.x = (c.x + 1.5) * TILE; paper.y = (c.y - 0.4) * TILE;
      }
      handOff(stage, false);
    },

    bounce(stage) { handOff("Engineer", true); },

    land() {
      paper.tx = 19 * TILE; paper.ty = 1.4 * TILE;
      paper.bad = false;
      setTimeout(() => { paper.fading = 1; }, 900);
    },

    board(items, landed) { board = { items, landed }; },

    suite(now, before, hadSuite) { suite = { now, before, started: hadSuite }; },
  };
})();
