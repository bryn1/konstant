"""Pinned programs: konstant never runs, outside a jail, a program file a phase could have written
(REVIEW L5-R2 K-01; the class of L5-R1 H-01).

konstant's own processes run unjailed as the operator's user: `doctor`, the dsh composition check
(`--dump-config`, in `task run`, `factory run` and `konstant dsh`), the operator's `konstant dsh`
session itself, the ship step's `gh` and `[ship] ship_cmd` / `rollback_cmd`. tools.py keeps git,
bwrap and konstant's own interpreter on root-owned paths, but a harness launcher (dsh, claude,
codex, gemini), its interpreter and its entry script usually live in the user's home, where a phase
with host writes (the open profile) could rewrite them. So:

  - `agents sync` (install.sh runs it) RECORDS each such program in var/machinery.json under
    `programs`: the path it resolves to, and every program file konstant can identify for it
    (the launcher, its real path, the `#!` interpreter, the script files a shell launcher names;
    harnesses/base.exe_roots) with its sha256 and its stat;
  - before every unjailed run, `check()` walks the program again (the same discovery, the
    environment it will run in) and compares: another path, another set of files, or a file
    whose content changed (its stat differs AND its sha256 differs) refuses the run, naming it.
    No pin at all refuses as well (fail closed): `agents sync` is the one deliberate way to pin;
  - `ro_paths()` lists the pinned files and their install roots (the package directory of a node
    or python install below $HOME) that this user can write: every phase jail binds them
    read-only (harnesses/base.jail_layout), so no phase rewrites them in the first place.

The dsh composition check also runs INSIDE konstant's jail with the integrity core masked
(harnesses/dsh._dump): it needs no token, so even a program the pin cannot see (a module the entry
script imports) reads nothing there. The operator's own `konstant dsh` session is the one place a
harness runs unjailed by design; it starts only from a verified pin.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
from pathlib import Path

HARNESS_KEYS = ("dsh", "claude", "codex", "gemini")
SHIP_KEYS = ("gh", "ship_cmd", "rollback_cmd")
SYNC = "run `bin/konstant agents sync` to pin it (it records the program and its sha256)"


def _home(cfg_or_home) -> Path:
    """The workspace of a Config or a path (a Path has a `home` classmethod: never getattr)."""
    if isinstance(cfg_or_home, (str, os.PathLike)):
        return Path(cfg_or_home)
    return Path(cfg_or_home.home)


def _manifest(home) -> Path:
    return Path(home) / "var" / "machinery.json"


def load(home) -> dict:
    try:
        data = json.loads(_manifest(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    progs = data.get("programs") if isinstance(data, dict) else None
    return progs if isinstance(progs, dict) else {}


def _stat(p: str) -> list:
    st = os.stat(p)
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def _sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _argv(key: str, spec) -> list:
    if isinstance(spec, list):
        return [str(x) for x in spec]
    try:
        return shlex.split(str(spec or ""))
    except ValueError:
        return []


def _path_for(key: str) -> str | None:
    """The PATH a program is resolved on: the ship commands run with konstant's trusted PATH
    (factory/targets.own_env), everything else with the caller's own PATH."""
    if key in ("ship_cmd", "rollback_cmd"):
        from konstant import tools
        return tools.trusted_path()
    return None


def walk(key: str, argv: list) -> tuple:
    """(exe, sorted program files) for `argv`, without hashing anything."""
    from konstant.harnesses.base import _is_program_file, exe_roots
    if not argv:
        return None, []
    argv0 = argv[0]
    exe = argv0 if "/" in argv0 else shutil.which(argv0, path=_path_for(key))
    if not exe or not os.path.isfile(exe):
        return None, []
    exe = os.path.abspath(exe)
    seen: set = set()
    exe_roots(exe, 0, seen)
    for item in argv[1:]:
        for w in str(item).split("="):
            if "/" in w and _is_program_file(w):
                exe_roots(os.path.abspath(w), 1, seen)
    return exe, sorted(f for f in seen if os.path.isfile(f))


def wanted(cfg) -> dict:
    """{key: argv or command string} of every program konstant may run unjailed for workspace
    `cfg`: each harness CLI found on PATH, [ship] gh, ship_cmd and rollback_cmd when set."""
    out: dict = {k: [k] for k in HARNESS_KEYS}
    s = cfg.data.get("ship") or {}
    if s.get("gh"):
        out["gh"] = s["gh"]
    for k in ("ship_cmd", "rollback_cmd"):
        if s.get(k):
            out[k] = s[k]
    return out


def pin_one(key: str, spec) -> dict:
    exe, files = walk(key, _argv(key, spec))
    rec = {"exe": exe, "files": {f: {"sha256": _sha(f), "stat": _stat(f)} for f in files}}
    if isinstance(spec, str):
        rec["value"] = spec
    return rec


def record(cfg) -> dict:
    """The `programs` section of var/machinery.json (integrity.record writes it)."""
    return {k: pin_one(k, v) for k, v in wanted(cfg).items()}


def _label(key: str) -> str:
    return {"gh": "[ship] gh", "ship_cmd": "[ship] ship_cmd",
            "rollback_cmd": "[ship] rollback_cmd"}.get(key, key)


def check(cfg_or_home, key: str, value=None) -> str | None:
    """None when the program of `key` may run unjailed; else why not (fail closed)."""
    home = _home(cfg_or_home)
    rec = load(home).get(key)
    label = _label(key)
    if not isinstance(rec, dict):
        return f"{label} is not pinned: {SYNC} (REVIEW L5-R2 K-01)"
    if value is not None and isinstance(value, str) and rec.get("value", value) != value:
        return f"{label} differs from the one pinned at `agents sync`: {SYNC}"
    if not rec.get("exe"):
        return f"{label} was not installed at `agents sync`: {SYNC}"
    argv = _argv(key, value if value is not None else rec.get("value") or [rec["exe"]])
    if key in HARNESS_KEYS or key == "gh":
        argv = [rec["exe"]] + argv[1:]
    exe, files = walk(key, argv)
    if exe != rec["exe"]:
        return (f"{label} now resolves to {exe or 'nothing'}, not the pinned {rec['exe']}: "
                f"konstant will not run it; {SYNC} if that is intended")
    want = rec.get("files") or {}
    extra = sorted(set(files) - set(want))
    gone = sorted(set(want) - set(files))
    if extra or gone:
        return (f"{label} changed since `agents sync` (program files "
                f"{'added ' + ', '.join(extra) if extra else ''}"
                f"{' removed ' + ', '.join(gone) if gone else ''}): konstant will not run it; "
                f"{SYNC} if you upgraded it")
    for f, meta in want.items():
        try:
            if _stat(f) == meta.get("stat"):
                continue
            if _sha(f) == meta.get("sha256"):
                continue
        except OSError:
            pass
        return (f"{label} changed since `agents sync` ({f} is not the file that was pinned): "
                f"konstant will not run it; {SYNC} if you upgraded it")
    return None


def is_pinned(cfg_or_home, key: str) -> bool:
    rec = load(_home(cfg_or_home)).get(key)
    return isinstance(rec, dict) and bool(rec.get("exe"))


def resolve(cfg_or_home, key: str) -> tuple:
    """(the pinned path, None) when it may run, else (None, why)."""
    why = check(cfg_or_home, key)
    if why:
        return None, why
    return load(_home(cfg_or_home))[key]["exe"], None


def _install_roots(real: str) -> list:
    from konstant.harnesses.base import _install_root
    home = os.path.realpath(os.path.expanduser("~"))
    out = []
    root = _install_root(real, home)
    if root:
        out.append(root)
    parts = Path(real).parts
    for i, part in enumerate(parts):
        if part in ("node_modules", "versions") and i > 1:
            out.append(str(Path(*parts[:i])))
            break
    return out


def ro_paths(home) -> list:
    """The pinned program files and their install roots this user can write: bound read-only in
    every phase jail. Never $HOME itself, `/`, the workspace or a directory holding it."""
    ws = os.path.realpath(str(home))
    me = os.path.realpath(os.path.expanduser("~"))
    out = []
    for rec in load(home).values():
        for f in (rec.get("files") or {}) if isinstance(rec, dict) else ():
            if not os.path.isfile(f):
                continue
            if os.access(f, os.W_OK) or os.access(os.path.dirname(f), os.W_OK):
                out.append(f)
            out += [r for r in _install_roots(f) if os.access(r, os.W_OK)]
    keep = []
    for p in dict.fromkeys(os.path.realpath(x) for x in out):
        if p in ("/", me) or p == ws or ws.startswith(p.rstrip("/") + "/"):
            continue
        keep.append(p)
    return keep


def version(exe: str, args, home) -> str:
    """`exe --version` inside konstant's jail (integrity core masked, no network): doctor never
    runs a harness CLI unjailed (K-01; the caller passes the PINNED path)."""
    import subprocess

    from konstant import jail
    try:
        r = subprocess.run(jail.wrap([exe, *args], hide=jail.hidden(home), home=home, net=False),
                           capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = (r.stdout or r.stderr).strip().splitlines()
    return lines[0][:60] if r.returncode == 0 and lines else ""


def doctor_row(home, key: str, check: str, head: str, found: str, version_args) -> tuple:
    """doctor's row for a harness CLI found on PATH: WARN unpinned, FAIL changed, PASS pinned
    (with its version, probed jailed)."""
    pinned, why = resolve(home, key)
    if why and not is_pinned(home, key):
        return ("WARN", check, f"{head}{found}: {why}; until then konstant runs no check on it "
                "outside its jail")
    if why:
        return ("FAIL", check, f"{head}{found}: {why}; konstant runs no unpinned or changed "
                "harness program outside its jail (no phase, no check and no `konstant dsh` "
                "session starts on it)")
    ver = version(pinned, version_args, home)
    return ("PASS", check, f"{head}{pinned} (pinned, sha256 checked)" + (f" ({ver})" if ver
                                                                         else ""))
