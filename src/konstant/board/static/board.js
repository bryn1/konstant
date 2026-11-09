// konstant board: read-only view. Every value is rendered with textContent, never as HTML.
(function () {
  "use strict";
  const KEY = "konstant.viewer.token";
  const $ = (id) => document.getElementById(id);
  const store = {
    get() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } },
    set(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* storage unavailable */ } },
    clear() { try { localStorage.removeItem(KEY); } catch (e) { /* storage unavailable */ } },
  };
  let token = store.get();

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  async function api(path) {
    const r = await fetch(path, { headers: { Authorization: "Bearer " + token } });
    if (r.status === 401) { store.clear(); token = ""; showLogin(); throw new Error("token refused"); }
    if (!r.ok) throw new Error(path + " -> HTTP " + r.status);
    return r.json();
  }

  function showLogin() { $("login").hidden = false; $("forget").hidden = true; $("tabs").hidden = true; }

  function render(jobs) {
    const kids = new Map();
    jobs.forEach((j) => {
      const k = j.parent_id === null ? "root" : j.parent_id;
      if (!kids.has(k)) kids.set(k, []);
      kids.get(k).push(j);
    });
    function branch(key) {
      const ul = el("ul");
      (kids.get(key) || []).forEach((j) => {
        const li = el("li");
        const b = el("button", "job");
        b.type = "button";
        b.append(el("span", "id", j.display_id), el("span", "title", j.title),
                 el("span", "st " + j.status, j.status));
        b.addEventListener("click", () => detail(j.id));
        li.append(b);
        if (kids.has(j.id)) li.append(branch(j.id));
        ul.append(li);
      });
      return ul;
    }
    $("tree").replaceChildren(jobs.length ? branch("root") : el("p", "muted", "No jobs yet."));
  }

  async function detail(id) {
    const j = await api("/api/jobs/" + id + "?trail=true");
    const box = el("div");
    box.append(el("h2", "", j.display_id + "  " + j.title),
               el("p", "muted", j.type + " - " + j.status + " - requested by " + j.requested_by
                  + (j.assignee ? " - assignee " + j.assignee : "")),
               el("h3", "", "Acceptance"), el("pre", "", j.acceptance || "(project root)"));
    if (j.evidence) box.append(el("h3", "", "Evidence"), el("pre", "", JSON.stringify(j.evidence, null, 2)));
    const trail = el("ul");
    (j.trail || []).forEach((t) => trail.append(el("li", "", t.ts + "  " + t.kind + "  " + t.actor + ": " + t.body)));
    box.append(el("h3", "", "Trail"), trail);
    $("detail").replaceChildren(box);
  }

  // Memory (read-only): recent notes, recall, one note. The viewer token never sees the
  // sealed pool (the scenario writer's and the verifier's notes); the board says how many it hides.
  function noteItem(n) {
    const li = el("li");
    const b = el("button", "job");
    b.type = "button";
    b.append(el("span", "id", n.pool), el("span", "title", n.title),
             el("span", "st" + (n.verified ? " verified" : ""), n.trust || ""),
             el("span", "muted", (n.actor || "unattributed") + "  " + (n.updated || "").slice(0, 10)));
    b.addEventListener("click", () => showNote(n.path));
    li.append(b);
    if (n.snippet) li.append(el("div", "muted snippet", n.snippet));
    return li;
  }

  function listNotes(notes, meta) {
    $("mem-list").replaceChildren(...notes.map(noteItem));
    $("mem-meta").textContent = meta;
  }

  async function recentNotes() {
    const r = await api("/api/memory/notes?limit=50");
    listNotes(r.notes, r.notes.length + " recent note(s)" + (r.hidden ? "; " + r.hidden +
              " in pools this token does not read" : "") + (r.shared ? "; shared with the owner's tools" : ""));
  }

  async function recall(q) {
    const r = await api("/api/memory/recall?limit=20&q=" + encodeURIComponent(q));
    listNotes(r.hits, r.hits.length + " note(s) for \u201c" + q + "\u201d (" + r.mode + " recall)");
  }

  async function showNote(path) {
    const n = await api("/api/memory/note?path=" + encodeURIComponent(path));
    const box = el("div");
    box.append(el("h2", "", n.title),
               el("p", "muted", n.pool + " - " + (n.meta.actor || "unattributed") + " - " + (n.trust || "") + " - " + n.path
                  + (n.attributed ? "" : " - not written by konstant")),
               el("p", "muted", "tags: " + (n.tags.join(", ") || "-") + "   links: " + (n.links.join(", ") || "-")),
               el("pre", "", n.body));
    $("mem-detail").replaceChildren(box);
  }

  // Factory (read-only, docs/LEVEL5.md 6.4): the loop, goals with their budget and jobs (attempts
  // left), ships, escalations and the last events. Holdouts appear only as counts.
  function kv(budget) {
    return Object.keys(budget).filter((k) => budget[k].limit || k === "max_attempts")
      .map((k) => k + " " + (budget[k].used === undefined ? "" : budget[k].used + "/") + budget[k].limit).join(", ");
  }

  function goalBox(g) {
    const box = el("div", "goal");
    box.append(el("h3", "", g.goal + " - " + g.status + " (intake " + g.intake + ")"),
               el("p", "muted", "budget: " + kv(g.budget) + (g.exhausted.length ? " - EXHAUSTED: " + g.exhausted.join("; ") : "")));
    const ul = el("ul");
    g.jobs.forEach((j) => ul.append(el("li", "", j.display_id + "  " + j.status + "  attempts left "
      + j.attempts_left + "/" + j.max_attempts + "  holdouts sealed " + j.holdouts_sealed
      + (j.ship ? "  ship " + j.ship.id + " " + j.ship.state : "") + "  " + j.title)));
    box.append(ul);
    g.ships.forEach((s) => box.append(el("p", "muted", "ship " + s.id + " " + s.state + " " + s.target
      + " " + (s.branch || "") + " " + (s.commit_sha || "").slice(0, 12) + (s.rollback_sha ? " rollback " + s.rollback_sha.slice(0, 12) : ""))));
    return box;
  }

  async function factory() {
    const st = await api("/api/factory/status");
    const goals = await api("/api/factory/goals");
    const f = st.factory;
    $("fac-state").textContent = "factory " + f.state + (f.pid ? " (pid " + f.pid + ")" : "")
      + (f.last_tick ? " - last tick " + f.last_tick : "") + (f.state === "stale" ? " - STALE: no heartbeat for three ticks" : "")
      + (st.halted ? " - HALTED: " + st.halt.reason : "") + " - shipping " + st.shipping
      + " - " + st.open_escalations + " open escalation(s)" + (st.spooled ? " - " + st.spooled + " undelivered" : "");
    $("fac-goals").replaceChildren(...(goals.goals.length ? goals.goals.map(goalBox) : [el("p", "muted", "No goals yet.")]));
    const esc = [];
    goals.goals.forEach((g) => g.escalations.forEach((e) => esc.push(e)));
    $("fac-esc").replaceChildren(...esc.map((e) => el("li", e.open ? "" : "muted", e.id + "  " + e.kind + "  "
      + (e.goal || "-") + (e.display_id ? " job " + e.display_id : "") + "  " + (e.open ? "open" : "acknowledged by " + e.acked_by) + ": " + e.reason)));
    $("fac-events").replaceChildren(...st.events.slice().reverse().map((e) => el("li", "", e.at + "  " + e.event
      + "  " + (e.goal || "-") + (e.display_id ? " job " + e.display_id : "") + ": " + e.reason + (e.suppressed ? " (told before)" : ""))));
  }

  function view(name) {
    ["jobs", "memory", "factory"].forEach((v) => {
      $(v + "-view").hidden = v !== name;
      $("tab-" + v).setAttribute("aria-pressed", String(v === name));
    });
    const fail = (e) => { $("error").textContent = e.message; };
    if (name === "memory") recentNotes().catch(fail);
    if (name === "factory") factory().catch(fail);
  }

  async function load() {
    try {
      const me = await api("/api/whoami");
      $("whoami").textContent = "as " + me.label + " (" + me.role + ")";
      $("login").hidden = true; $("forget").hidden = false; $("tabs").hidden = false;
      render((await api("/api/jobs?roots=true&limit=10000")).jobs);
      $("error").textContent = "";
    } catch (e) { $("error").textContent = e.message; }
  }

  $("login").addEventListener("submit", (ev) => {
    ev.preventDefault();
    token = $("token").value.trim(); store.set(token); load();
  });
  $("forget").addEventListener("click", () => { store.clear(); token = ""; showLogin(); });
  $("tab-jobs").addEventListener("click", () => view("jobs"));
  $("tab-memory").addEventListener("click", () => view("memory"));
  $("tab-factory").addEventListener("click", () => view("factory"));
  $("mem-search").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("mem-q").value.trim();
    (q ? recall(q) : recentNotes()).catch((e) => { $("error").textContent = e.message; });
  });
  if (token) load(); else showLogin();
})();
