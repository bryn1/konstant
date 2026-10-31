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

  function showLogin() { $("login").hidden = false; $("forget").hidden = true; }

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

  async function load() {
    try {
      const me = await api("/api/whoami");
      $("whoami").textContent = "as " + me.label + " (" + me.role + ")";
      $("login").hidden = true; $("forget").hidden = false;
      render((await api("/api/jobs?roots=true&limit=10000")).jobs);
      $("error").textContent = "";
    } catch (e) { $("error").textContent = e.message; }
  }

  $("login").addEventListener("submit", (ev) => {
    ev.preventDefault();
    token = $("token").value.trim(); store.set(token); load();
  });
  $("forget").addEventListener("click", () => { store.clear(); token = ""; showLogin(); });
  if (token) load(); else showLogin();
})();
