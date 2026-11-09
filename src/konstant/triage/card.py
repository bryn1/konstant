"""The intake card (docs/CONCEPTS.md "Triage"): the first step of every non-inline task, computed by
code before any model plans it, injected into every phase prompt (and the gate block), kept in
the run record and recorded on the job (`POST /api/jobs/{ref}/intake-card`).

It answers the orchestrator's first questions in order:
  1. what type of task, what tier (tiers.py);
  2. new or continuation: a run bound to an existing job (`--job`, `[job:N]`, the session's job)
     continues it; otherwise an OPEN job or an ACTIVE goal of the same project that shares paths
     or keywords with the task makes it a continuation; else it is new;
  3. what has been done before: board jobs and goals that share keywords or paths (closed ones
     are similar work), and memory recall over the shared pool, verified-job lessons first (the
     board ranks them: memory/service.py label);
  4. what to reuse: files the task names that exist in the project, project files whose name
     matches a keyword, catalog skills whose name or description shares a keyword;
  5. research_required: a NEW task where nothing was found (no related job or goal, no memory
     hit). An unreachable board is a warning, as for every gate read: no lookup, no requirement
     (the card says so). The plan then
     starts with the closed researcher phase (research.py); `[triage] research = "off"` turns
     that requirement off (doctor WARNs).
Board reads use the viewer token: the card is information for the planner, never a permission.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from konstant.triage import tiers

VERSION = 1
WORD = re.compile(r"[a-z][a-z0-9_]{3,}")
STOP = set("""
this that these those with from into onto over under about above below after before again also
just only than then them they their there here where when what which while whom whose would could
should shall will must make made makes making take takes need needs want wants like using used use
your yours ours have having been being does doing done each every some such very more most other
same both many much well good best please task tasks work works project projects file files code
type tier agent agents small large huge medium sure keep give gave show list write writes written
change changes update updates create creates build builds implement implements thing things into
konstant dod definition probe probes verify_cmd verify_exit pass passes test tests
""".split())
OPEN = ("queued", "waiting_approval", "claimed", "blocked", "completed_unverified")
DONE = ("verified", "reviewed")
SKIP_DIRS = {".git", ".audits", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist",
             "build", ".mypy_cache", ".pytest_cache"}
MAX_WALK = 4000
SNIPPET = 160


def keywords(task: str, limit: int = 8) -> list:
    text = tiers.TAG.sub(" ", tiers.scope_text(task))
    text = re.sub(r"\[(?:type|job):[^\]]*\]", " ", text).lower()
    out: list = []
    for w in WORD.findall(text):
        w = w.strip("_")
        if len(w) >= 4 and w not in STOP and not w.isdigit() and w not in out:
            out.append(w)
    return out[:limit]


def named_paths(task: str) -> list:
    return list(dict.fromkeys(tiers.PATH.findall(tiers.scope_text(task))))


def _one_line(text: str, n: int = SNIPPET) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:n]


class Lookup:
    """The board reads the card needs, through a client (viewer); `ok` False once unreachable."""

    def __init__(self, client):
        self.client, self.ok, self.errors = client, client is not None, []

    def get(self, path: str, /, **params):
        from konstant.client import ClientError
        if self.client is None:
            return None
        try:
            return self.client.get(path, **params)
        except ClientError as exc:
            if not exc.status:
                self.ok = False
            self.errors.append(f"{path}: {exc.message}"[:200])
            return None


def related_jobs(look: Lookup, words: list, paths: list, slug: str) -> list:
    score: dict = {}
    rows: dict = {}
    for i, term in enumerate(paths[:3] + words[:6]):
        params = {"q": term, "limit": 50}
        if slug:
            params["project"] = slug
        res = look.get("/api/search", **params)
        for j in (res or {}).get("jobs", []):
            rows[j["id"]] = j
            hit = score.setdefault(j["id"], {"score": 0, "matched": []})
            hit["score"] += 2 if i < len(paths[:3]) else 1
            hit["matched"].append(term)
    out = []
    for jid, s in score.items():
        j = rows[jid]
        if s["score"] < 2:
            continue
        out.append({"kind": "job", "id": jid, "display_id": j.get("display_id") or str(jid),
                    "status": j.get("status"), "title": _one_line(j.get("title"), 100),
                    "project": j.get("project"), "type": j.get("type"),
                    "score": s["score"], "matched": s["matched"][:6]})
    return sorted(out, key=lambda r: (-r["score"], -int(r["id"])))[:8]


def related_goals(look: Lookup, words: list, slug: str) -> list:
    res = look.get("/api/goals")
    out = []
    for g in (res or {}).get("goals", []):
        text = " ".join([str(g.get("slug") or ""),
                         str(((g.get("spec") or {}).get("goal") or {}).get("text") or "")]).lower()
        matched = [w for w in words if w in text]
        same = bool(slug) and g.get("project") == slug
        if len(matched) >= 2 or (same and matched):
            out.append({"kind": "goal", "id": g.get("slug"), "status": g.get("status"),
                        "project": g.get("project"), "score": len(matched) + (1 if same else 0),
                        "matched": matched[:6], "title": _one_line(text, 100)})
    return sorted(out, key=lambda r: -r["score"])[:4]


def prior_notes(look: Lookup, words: list, limit: int) -> tuple:
    """(hits, note): memory recall over what the viewer reads (the shared pool and the owner's
    notes; never the sealed pool), verified-job lessons first (the board's order)."""
    if not words:
        return [], "no keywords to recall with"
    res = look.get("/api/memory/recall", q=" ".join(words), limit=limit)
    if res is None:
        return [], ("memory not recalled: " + (look.errors[-1] if look.errors else "no board"))
    hits = [{"path": h.get("path"), "title": _one_line(h.get("title"), 100),
             "trust": h.get("trust"), "verified": h.get("verified"), "job": h.get("job"),
             "snippet": _one_line(h.get("snippet"))} for h in res.get("hits", [])]
    return hits[:limit], f"{res.get('mode', 'lexical')} recall, {len(hits)} hit(s)"


def project_files(project, words: list, paths: list) -> list:
    """Files the task names that exist in the project, then files whose name holds a keyword."""
    if not project or not Path(project).is_dir():
        return []
    root = Path(project)
    out = []
    for p in paths:
        cand = (root / p)
        if cand.is_file():
            out.append({"kind": "file", "path": p, "why": "named in the task"})
    if not words:
        return out[:8]
    seen, n = {o["path"] for o in out}, 0
    for d, dirs, fnames in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")
                         and "@" not in x)
        for fn in sorted(fnames):
            n += 1
            if n > MAX_WALK:
                return out[:8]
            stem = fn.rsplit(".", 1)[0].lower()
            hit = next((w for w in words if w in stem or (len(stem) >= 4 and stem in w)), None)
            rel = os.path.relpath(os.path.join(d, fn), root)
            if hit and rel not in seen:
                out.append({"kind": "file", "path": rel, "why": f"name matches {hit!r}"})
                seen.add(rel)
    return out[:8]


def skills(cat, ttype, words: list) -> list:
    own = set(cat.skills_of(ttype)) if ttype in cat.types else set()
    out = []
    for name in cat.skill_names():
        if name in own:
            continue
        desc = ""
        f = Path(cat.root) / "skills" / name / "SKILL.md"
        try:
            head = f.read_text(encoding="utf-8")[:1500]
            m = re.search(r"(?m)^description:\s*(.+)$", head)
            desc = (m.group(1) if m else "").lower()
        except OSError:
            pass
        matched = [w for w in words if w in name or re.search(rf"\b{re.escape(w)}", desc)]
        if matched:
            out.append({"kind": "skill", "name": name, "why": f"matches {', '.join(matched[:3])}"})
    return out[:4]


def build(*, task: str, ttype, why: str, tier, project_slug: str = "", project=None,
          job: dict | None = None, bound_how: str = "", client=None, cat=None,
          cfg_data: dict | None = None, goal: str = "") -> dict:
    """The card (a JSON-able dict). `client`: a viewer client, None when there is no board;
    `goal`: the goal an intake run plans (it is not its own prior work)."""
    tri = (cfg_data or {}).get("triage") or {}
    limit = int(tri.get("prior_limit", 5))
    look = Lookup(client)
    words, paths = keywords(task), named_paths(task)
    slug = project_slug or (job or {}).get("project") or ""
    jobs = related_jobs(look, words, paths, slug) if look.ok else []
    goals = [g for g in (related_goals(look, words, slug) if look.ok else []) if g["id"] != goal]
    notes, mem = prior_notes(look, words, limit) if look.ok else ([], "board unreachable")
    own = int(job["id"]) if job else None
    jobs = [j for j in jobs if j["id"] != own]
    if job and bound_how in ("flag", "tag", "session"):
        cont = "continuation"
        cwhy = f"bound to job {job.get('display_id') or job['id']} ({bound_how})"
    else:
        live = [r for r in jobs if r["status"] in OPEN] + \
            [g for g in goals if g["status"] in ("active", "proposed", "paused")]
        cont = "continuation" if live else "new"
        cwhy = (f"open {live[0]['kind']} {live[0].get('display_id') or live[0]['id']} shares "
                f"{', '.join(live[0]['matched'][:4])}" if live else
                ("a job filed for this task" if bound_how == "filed" else
                 "no open job or active goal shares its paths or keywords"))
    reuse = project_files(project, words, paths) + (skills(cat, ttype, words) if cat else [])
    found = bool(jobs or goals or notes)
    if tier.name == "inline":
        need, rwhy = False, "inline: no plan"
    elif not look.ok:
        need, rwhy = False, ("prior work not looked up: the board is unreachable (a warning, as "
                             "every gate read of an unreachable board; nothing was found because "
                             "nothing was asked)")
    elif cont == "continuation":
        need, rwhy = False, "a continuation: the earlier work is the prior work"
    elif found:
        need, rwhy = False, "similar work found: reuse it first"
    else:
        need, rwhy = True, "nothing similar on the board or in memory: research before planning"
    policy = tri.get("research", "required")
    if need and policy == "off":
        need, rwhy = False, rwhy + " ([triage] research = \"off\": not required here)"
    card = {"version": VERSION, "type": ttype, "type_why": why, "tier": tier.as_dict(),
            "continuation": cont, "continuation_why": cwhy, "keywords": words,
            "related": jobs + goals, "prior_work": notes, "memory": mem, "reuse": reuse,
            "research_required": need, "research_why": rwhy,
            "board": "ok" if look.ok else "unreachable"}
    card["sha256"] = digest(card)
    return card


def digest(card: dict) -> str:
    body = {k: v for k, v in card.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def render(card: dict, research_cmd: str = "") -> str:
    """The card as text for a prompt or the gate block (compact; content is board data)."""
    t = card["tier"]
    lines = ["=== INTAKE CARD (computed by konstant before any planning) ===",
             f"TYPE: {card['type'] or 'small'} ({card['type_why']})",
             f"TIER: {t['name']} ({t['why']})" + (f"; run at most {t['agents']} typed run(s) "
                                                  f"at once (cap {t['cap']}: {t['cap_source']})"
                                                  if t["name"] in ("fanout", "max") else ""),
             f"TASK: {card['continuation']} ({card['continuation_why']})"]
    if t.get("note"):
        lines.append(f"TIER-NOTE: {t['note']}")
    for r in card["related"][:6]:
        ref = r.get("display_id") or r["id"]
        lines.append(f"RELATED: {r['kind']} {ref} [{r['status']}] {r['title']} "
                     f"(shares {', '.join(r['matched'][:4])})")
    lines.append(f"PRIOR WORK ({card['memory']}; verified lessons first):"
                 if card["prior_work"] else f"PRIOR WORK: none in memory ({card['memory']})")
    for n in card["prior_work"]:
        lines.append(f"  - [{n.get('trust') or 'unlabelled'}] {n['title']}: {n['snippet']}")
    for r in card["reuse"]:
        lines.append(f"REUSE: {r['kind']} {r.get('path') or r.get('name')} ({r['why']})")
    if card["research_required"]:
        how = (f" Run `{research_cmd}` before planning; producers get its cited summary, never "
               "raw pages." if research_cmd else " konstant runs the closed researcher phase "
               "before the first phase.")
        lines.append(f"RESEARCH: REQUIRED - {card['research_why']}.{how}")
    else:
        lines.append(f"RESEARCH: not required ({card['research_why']})")
    lines.append("=== END INTAKE CARD ===")
    return "\n".join(lines)


def summary(card: dict) -> str:
    """One trail line for the job."""
    t = card["tier"]
    return (f"intake card: [type:{card['type']}] tier {t['name']}, {card['continuation']}, "
            f"{len(card['related'])} related, {len(card['prior_work'])} prior note(s), "
            f"{len(card['reuse'])} reuse candidate(s), research "
            f"{'required' if card['research_required'] else 'not required'} "
            f"(sha256 {card['sha256'][:12]})")
