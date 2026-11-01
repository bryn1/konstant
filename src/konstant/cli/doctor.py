"""`konstant doctor` (DESIGN §10): is this workspace ready, and if not, what fixes it.

Each check prints `PASS|WARN|FAIL|INFO  <name>  <detail>`; a WARN or FAIL names its fix. Exit 0
when no check FAILs. WARN = konstant works but a capability is reduced (no harness binary on PATH,
no OS sandbox); INFO = a fact the user should know (the board is not running, the role-separation
mode in effect).
"""
from __future__ import annotations

import importlib
import os
import shlex
import shutil
import stat
import sys
import tempfile

from konstant import config as config_mod
from konstant.board.policy import ROLES
from konstant.cli.main import EXIT_FAIL, EXIT_OK

DEPENDENCIES = ("fastapi", "uvicorn", "pydantic", "yaml", "pytest") + (
    ("tomli",) if sys.version_info < (3, 11) else ())


class Report:
    def __init__(self):
        self.rows = []

    def add(self, status: str, name: str, detail: str) -> None:
        self.rows.append({"status": status, "check": name, "detail": detail})

    @property
    def failed(self) -> bool:
        return any(r["status"] == "FAIL" for r in self.rows)


def check_python(rep: Report) -> None:
    v = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info >= (3, 10):
        rep.add("PASS", "python", f"{v} ({sys.executable})")
    else:
        rep.add("FAIL", "python", f"{v}: konstant needs Python >= 3.10")


def check_dependencies(rep: Report) -> None:
    missing = []
    for mod in DEPENDENCIES:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        rep.add("FAIL", "dependencies", f"cannot import {', '.join(missing)}: re-run ./install.sh")
    elif not str(getattr(sys.modules["pydantic"], "VERSION", "2")).startswith("2"):
        rep.add("FAIL", "dependencies", "pydantic 2 is required: re-run ./install.sh")
    else:
        rep.add("PASS", "dependencies", ", ".join(DEPENDENCIES))


def check_config(rep: Report, ctx):
    try:
        cfg = ctx.cfg
    except config_mod.ConfigError as exc:
        rep.add("FAIL", "config", f"{exc}")
        return None
    if cfg.source is None:
        rep.add("WARN", "config", f"no {config_mod.CONFIG_NAME} in {cfg.home}; using defaults "
                "(re-run ./install.sh to write one)")
    else:
        rep.add("PASS", "config", str(cfg.source))
    return cfg


def check_var(rep: Report, cfg) -> None:
    try:
        cfg.var.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cfg.var, prefix=".doctor-"):
            pass
        rep.add("PASS", "var", f"{cfg.var} writable")
    except OSError as exc:
        rep.add("FAIL", "var", f"{cfg.var}: {exc.strerror or exc}; fix the folder permissions")


def check_modes(rep: Report, cfg) -> None:
    """var/ and the board DB are private to this user (REVIEW F-25)."""
    paths = [cfg.var] + [cfg.var / d for d in ("runs", "logs", "backups")] + \
        [cfg.db_path.with_name(cfg.db_path.name + s) for s in ("", "-wal", "-shm")]
    loose = [f"{p.relative_to(cfg.home) if p.is_relative_to(cfg.home) else p} is "
             f"{oct(_mode(p))}" for p in paths if p.exists() and _mode(p) & 0o077]
    if loose:
        rep.add("WARN", "file modes", "; ".join(loose) + ": other local users can read (or "
                "write) the board's briefs, evidence and run records; `bin/konstant board init` "
                "makes them private (0700 dirs, 0600 DB)")
    else:
        rep.add("PASS", "file modes", "var/ and the board DB are private to this user")


def check_db(rep: Report, cfg) -> None:
    from konstant.board import migrate
    want = migrate.target_version()
    if not cfg.db_path.exists():
        rep.add("FAIL", "database", f"{cfg.db_path} missing: run `bin/konstant board init`")
        return
    try:
        have = migrate.current_version(cfg.db_path)
    except Exception as exc:  # noqa: BLE001 - any sqlite error is the finding
        rep.add("FAIL", "database", f"{cfg.db_path}: {exc}")
        return
    if have == want:
        rep.add("PASS", "database", f"{cfg.db_path} schema {have}")
    else:
        rep.add("FAIL", "database", f"schema {have}, this konstant needs {want}: run "
                "`bin/konstant board init` (migrates in place; `board backup` first)")


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def check_tokens(rep: Report, cfg) -> None:
    d = cfg.secrets_dir
    if not d.is_dir():
        rep.add("FAIL", "tokens", f"{d} missing: run `bin/konstant board init`")
        return
    bad = [] if _mode(d) == 0o700 else [f"{d.name}/ is {oct(_mode(d))} (want 0700)"]
    for role in ROLES:
        p = d / f"{role}.token"
        if not p.exists():
            bad.append(f"{p.name} missing")
        elif _mode(p) != 0o600:
            bad.append(f"{p.name} is {oct(_mode(p))} (want 0600)")
    if bad:
        rep.add("FAIL", "tokens", "; ".join(bad) + ": run `bin/konstant board init` and "
                f"`chmod 700 {d}; chmod 600 {d}/*.token`")
    else:
        rep.add("PASS", "tokens", f"{len(ROLES)} role tokens, 0600 in a 0700 dir")
    from konstant.verify.verifier import separation
    rerun = cfg.data["verify"]["rerun"]
    if separation(cfg) == "procedural":
        rep.add("INFO", "role separation", "procedural: this OS user can read every token; a "
                "phase acts as worker, the closer cannot verify, and the verifier re-runs the "
                f"closer's verify_cmd as you ({'on' if rerun else 'off'}: [verify] rerun). For "
                "OS-level separation run `konstant verify` as a second user that cannot read the "
                "orchestrator/worker tokens (docs/CONCEPTS.md)")
    else:
        rep.add("INFO", "role separation", "OS-user: this user cannot read the closer-side tokens; "
                "the verifier never executes the closer's verify_cmd (only a DoD VERIFY_CMD)")


def check_exposure(rep: Report, cfg) -> None:
    host = cfg.data["board"]["host"]
    if config_mod.is_loopback(host):
        rep.add("PASS", "board host", f"{host}: loopback only")
    else:
        rep.add("WARN", "board host", f"{host} with [board] allow_remote = true: the board is "
                "reachable from the network over plain HTTP with bearer tokens; put TLS and a "
                "firewall in front of it, or bind 127.0.0.1")


def check_board(rep: Report, cfg) -> None:
    from konstant.cli.board import _healthy, _read_pid
    pid = _read_pid(cfg)
    if _healthy(cfg):
        rep.add("PASS", "board", f"answering /health at {cfg.base_url}"
                + (f" (pid {pid})" if pid else ""))
    elif pid:
        rep.add("FAIL", "board", f"pid {pid} is running but {cfg.base_url}/health does not "
                "answer: see var/logs/board.log, then `bin/konstant board stop` + `board start`")
    elif (cfg.var / "board.pid").exists():
        rep.add("WARN", "board", "stale var/board.pid: it names no running board of this "
                "workspace (a crash, then pid reuse); `bin/konstant board stop` removes it, "
                f"`bin/konstant board start` starts the board ({cfg.base_url})")
    else:
        rep.add("INFO", "board", f"not running: `bin/konstant board start` ({cfg.base_url})")


CLAIMED_IDLE_H, UNVERIFIED_H = 6, 1


def stranded(jobs: list, now) -> list:
    """Jobs nobody is moving (pure: jobs + now in, findings out). `claimed` with no update for
    CLAIMED_IDLE_H hours, `completed_unverified` waiting more than UNVERIFIED_H hours for a verdict."""
    from datetime import datetime, timedelta
    out = []
    for j in jobs:
        try:
            age = now - datetime.strptime(j["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=now.tzinfo)
        except (KeyError, TypeError, ValueError):
            continue
        hours = int(age.total_seconds() // 3600)
        if j.get("status") == "claimed" and age > timedelta(hours=CLAIMED_IDLE_H):
            out.append(f"job {j['display_id']} claimed, no activity for {hours}h (continue it, "
                       "`job block` it or `job reopen` it)")
        elif j.get("status") == "completed_unverified" and age > timedelta(hours=UNVERIFIED_H):
            out.append(f"job {j['display_id']} waits {hours}h for a verdict "
                       "(`bin/konstant verify --pending`)")
    return out


def check_stranded(rep: Report, ctx, cfg) -> None:
    from datetime import datetime, timezone
    from konstant.cli.board import _healthy
    from konstant.client import ClientError
    if not _healthy(cfg):
        return
    try:
        client = ctx.client("viewer")
        jobs = []
        for status in ("claimed", "completed_unverified"):
            jobs += client.get("/api/jobs", status=status)["jobs"]
    except ClientError as exc:
        rep.add("WARN", "stranded jobs", f"could not read the board: {exc.message}")
        return
    found = stranded(jobs, datetime.now(timezone.utc))
    if found:
        rep.add("WARN", "stranded jobs", "; ".join(found[:5])
                + (f"; and {len(found) - 5} more" if len(found) > 5 else ""))
    else:
        rep.add("PASS", "stranded jobs", "no idle claimed job, no job waiting long for a verdict")


def check_agents(rep: Report, cfg) -> None:
    from konstant import catalog as catalog_mod
    from konstant.agents.generate import GenerateError, Generator
    try:
        cat = catalog_mod.load(catalog_mod.find_root(cfg.home, cfg.data["catalog"]["path"]),
                               check_files=True)
        from konstant import harnesses
        harnesses.check_types(cfg.data["harness"], cat)
        gen = Generator(cat, cfg.home, cfg.data["permissions"], harness=cfg.data["harness"],
                        gate=cfg.session_gate(), policy=cfg.data["board"]["policy"])
        drift = gen.check()
    except (catalog_mod.CatalogError, GenerateError, harnesses.HarnessError) as exc:
        rep.add("FAIL", "agents", f"{exc}")
        return
    if drift:
        rep.add("FAIL", "agents", f"{len(drift)} generated file(s) out of date ({drift[0]} ...): "
                "run `bin/konstant agents sync`")
    else:
        rep.add("PASS", "agents", f"generated surfaces for {', '.join(gen.harness_names())} "
                "match the catalog")


def _version(exe: str, args) -> str:
    import subprocess
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = (r.stdout or r.stderr).strip().splitlines()
    return lines[0][:60] if r.returncode == 0 and lines else ""


def check_harness(rep: Report, cfg) -> str:
    """The default harness and every per-type override: the CLI on PATH (and its version), then
    what each one's own permission system enforces for a phase (docs/HARNESSES.md)."""
    from konstant import harnesses
    h = cfg.data["harness"]
    rows = [("harness", None)] + [(f"harness {t}", t) for t in sorted(h.get("types") or {})]
    exe0, reached = "", set()
    for check, t in rows:
        try:
            ch = harnesses.resolve(h, t)
            argv = shlex.split(ch.template) if ch.template is not None else [ch.adapter.binary]
        except (harnesses.HarnessError, ValueError) as exc:
            rep.add("FAIL", check, f"{exc}")
            continue
        exe = argv[0] if argv else ""
        exe0 = exe0 or (exe if t is None else exe0)
        found = shutil.which(exe) if exe else None
        what = f"{ch.name}{' model ' + ch.model if ch.model else ''}"
        if found:
            ver = _version(found, ch.adapter.version_args) if ch.template is None else ""
            rep.add("PASS", check, f"{what}: {exe} -> {found}" + (f" ({ver})" if ver else ""))
        else:
            rep.add("WARN", check, f"{what}: {exe or '(empty)'} not found on PATH: `task run` "
                    "cannot start phases until it is installed or [harness] in konstant.toml "
                    "names another agent CLI (board, gate, check and verify work without it)")
        key = (ch.name, ch.template)
        if key not in reached:
            reached.add(key)
            check_reach(rep, cfg, ch, "reach" if t is None else f"reach {ch.name}")
    return os.path.basename(exe0)


def check_reach(rep: Report, cfg, ch, name: str) -> None:
    if ch.template is not None and ch.name != "command":
        rep.add("INFO", name, f"custom [harness] command for {ch.name}: konstant cannot vouch for "
                "its reach (docs/HARNESSES.md lists what the default command enforces)")
        return
    reach = ch.adapter.reach(cfg.data["harness"], cfg.data["permissions"],
                             jail=bool(cfg.data["gate"]["jail"]))
    for status, check, detail in ch.adapter.doctor(cfg.data["harness"], cfg.home):
        rep.add(status, check, detail)
    weak = [(a, lvl, d) for a, lvl, d in reach.rows() if lvl != "enforced"]
    summary = "; ".join(f"{a} {lvl}" for a, lvl, _d in reach.rows())
    if not weak:
        rep.add("PASS", name, f"{ch.name}: {summary} (workspace-scoped)")
    else:
        rep.add("WARN", name, f"{ch.name}: {summary}. " + " ".join(
            f"{a.upper()}: {d}." for a, _l, d in weak))


def check_sandbox(rep: Report, cfg, harness: str) -> None:
    if harness != "claude":
        rep.add("INFO", "sandbox", f"harness is {harness or '(none)'}; Claude Code's sandbox "
                "settings do not apply")
        return
    if not cfg.data["permissions"]["sandbox"]:
        rep.add("INFO", "sandbox", "off ([permissions] sandbox = false): the allow list alone "
                "decides what a phase may run")
        return
    missing = [b for b in ("bwrap", "socat") if shutil.which(b) is None]
    if sys.platform == "darwin":
        rep.add("PASS", "sandbox", "macOS: Claude Code uses the built-in Seatbelt sandbox")
    elif missing:
        rep.add("WARN", "sandbox", f"{', '.join(missing)} not on PATH: Claude Code runs Bash "
                "UNSANDBOXED, and then the allow list does NOT confine a phase (an allowed test "
                "runner executes agent-written code with your full rights); install bubblewrap "
                "and socat (e.g. `sudo apt install bubblewrap socat`)")
    else:
        rep.add("PASS", "sandbox", "bubblewrap + socat present (Bash writes confined to the "
                "workspace)")


def check_jail(rep: Report, cfg) -> None:
    from konstant import jail
    if not cfg.data["gate"]["jail"]:
        rep.add("INFO", "jail", "off ([gate] jail = false): task check and the verifier's re-run "
                "execute agent-written code with your full rights")
    elif jail.available():
        rep.add("PASS", "jail", "bubblewrap works: agent-written tests, verifier re-runs, dsh "
                "phases and every phase of a holdout job run with var/secrets/ and the credential and agent homes konstant lists "
                "masked (~/.ssh, ~/.dsh, ~/.codex, ~/.claude, ...: docs/CONCEPTS.md; other files "
                "in your home stay readable), writes confined, konstant's machinery read-only, "
                "no network for tests")
    else:
        rep.add("INFO", "jail", "bubblewrap unavailable: task check and the verifier's re-run "
                "execute agent-written code unjailed, with your full rights (docs/CONCEPTS.md)")


def cmd_doctor(ctx) -> int:
    rep = Report()
    check_python(rep)
    check_dependencies(rep)
    cfg = check_config(rep, ctx)
    if cfg is not None:
        check_var(rep, cfg)
        check_db(rep, cfg)
        check_modes(rep, cfg)
        check_tokens(rep, cfg)
        check_exposure(rep, cfg)
        check_board(rep, cfg)
        check_stranded(rep, ctx, cfg)
        check_agents(rep, cfg)
        check_sandbox(rep, cfg, check_harness(rep, cfg))
        check_jail(rep, cfg)
        from konstant.holdout.store import doctor_row
        rep.add(*doctor_row(cfg))
        from konstant.factory.doctor import intake_rows, rows as factory_rows
        for row in factory_rows(cfg) + intake_rows(cfg):
            rep.add(*row)
    counts = {s: sum(r["status"] == s for r in rep.rows) for s in ("PASS", "WARN", "FAIL", "INFO")}
    summary = (f"doctor: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL, "
               f"{counts['INFO']} INFO")
    ctx.out({"ok": not rep.failed, "checks": rep.rows, "counts": counts},
            "\n".join(f"{r['status']:<5} {r['check']:<16} {r['detail']}" for r in rep.rows)
            + "\n" + summary)
    return EXIT_FAIL if rep.failed else EXIT_OK


def register(sub, leaf) -> None:
    p = sub.add_parser("doctor", parents=[leaf], help="check that this workspace is ready "
                       "(exit 0 when nothing FAILs)")
    p.set_defaults(func=cmd_doctor)
