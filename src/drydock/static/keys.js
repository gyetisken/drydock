// Keyboard, command palette, notifications and the things a job that takes
// twenty minutes needs from a desktop application.
//
// The rule used throughout: every shortcut here is also a thing you can click,
// and every shortcut is listed in one place you can open with "?". A binding
// nobody can discover is a binding nobody has.

const Keys = (() => {
  const SHORTCUTS = [
    { keys: "⌘K", what: "Open the command palette", group: "Everywhere" },
    { keys: "?", what: "This list", group: "Everywhere" },
    { keys: "⌘B", what: "Show or hide the sidebar", group: "Everywhere" },
    { keys: "⌘,", what: "Settings", group: "Everywhere" },
    { keys: "esc", what: "Close whatever is open", group: "Everywhere" },

    { keys: "⌘↵", what: "Send", group: "Composer" },
    { keys: "/", what: "Command list", group: "Composer" },
    { keys: "tab", what: "Take the highlighted command", group: "Composer" },
    { keys: "⌘.", what: "Stop the running job", group: "Composer" },

    { keys: "↵", what: "Approve the plan", group: "When a plan is waiting" },
    { keys: "esc", what: "Leave it unapproved", group: "When a plan is waiting" },

    { keys: "⌘1", what: "Thread", group: "Views" },
    { keys: "⌘2", what: "Office", group: "Views" },
    { keys: "⌘F", what: "Filter past runs", group: "Views" },
  ];

  const mac = navigator.platform.toLowerCase().includes("mac");
  const label = (k) => (mac ? k : k.replace("⌘", "Ctrl+").replace("⌥", "Alt+"));
  const hit = (e) => (mac ? e.metaKey : e.ctrlKey);

  /* ---------- the shortcut sheet ---------- */

  function sheet() {
    const groups = {};
    SHORTCUTS.forEach(s => (groups[s.group] = groups[s.group] || []).push(s));
    document.getElementById("keys-list").innerHTML = Object.entries(groups)
      .map(([name, rows]) => `
        <h5>${name}</h5>
        ${rows.map(r => `<div class="krow"><span>${r.what}</span>
          <kbd>${label(r.keys)}</kbd></div>`).join("")}`).join("");
    document.getElementById("keys").style.display = "flex";
  }

  /* ---------- notifications ---------- */

  // A run takes twenty minutes. Anyone sensible switches windows, and a result
  // nobody is looking at is a result nobody has. Permission is asked for on
  // the first job rather than on load, because a page that asks before it has
  // done anything is a page that gets refused.
  let asked = false;

  function askOnce() {
    if (asked || !("Notification" in window)) return;
    asked = true;
    if (Notification.permission === "default") Notification.requestPermission();
  }

  function notify(title, body) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    if (!document.hidden) return;   // you are looking at it; do not interrupt
    const n = new Notification(title, { body, icon: "/static/icon.png", tag: "drydock" });
    n.onclick = () => { window.focus(); n.close(); };
  }

  /* ---------- keeping the machine awake ---------- */

  // A job pauses when the laptop sleeps and the run is left half-done with a
  // dirty tree. The lock is taken only while something is actually running.
  let lock = null;

  async function awake(on) {
    try {
      if (on && !lock && navigator.wakeLock) {
        lock = await navigator.wakeLock.request("screen");
        lock.addEventListener("release", () => (lock = null));
      } else if (!on && lock) {
        await lock.release();
        lock = null;
      }
    } catch {
      // Refused, or the tab is in the background. Not worth telling anyone:
      // nothing is broken, the machine may simply sleep.
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !lock && window.S?.running) awake(true);
  });

  return { SHORTCUTS, label, hit, sheet, notify, askOnce, awake };
})();
