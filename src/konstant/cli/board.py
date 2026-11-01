"""`konstant board init|serve|start|stop|status|tokens|backup`."""
from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from konstant.board import auth, db, migrate
from konstant.cli.main import EXIT_FAIL, EXIT_OK, warn
from konstant.client import Client, ClientError

START_TIMEOUT_S = 20


PRIVATE_DIRS = ("", "logs", "runs", "backups", "locks")


def private_var(cfg) -> None:
    """var/ and its konstant-made folders are 0700 (REVIEW F-25): the DB, run manifests and logs
    hold briefs, evidence and authorship records no other local user may read or rewrite."""
    for name in PRIVATE_DIRS:
        d = cfg.var / name if name else cfg.var
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)


def cmd_init(ctx) -> int:
    cfg = ctx.cfg
    private_var(cfg)
    applied = migrate.migrate(cfg.db_path)
    with db.transaction(cfg.db_path) as conn:
        minted = auth.mint_missing(conn, cfg.secrets_dir)
    data = {"db": str(cfg.db_path), "schema": migrate.current_version(cfg.db_path),
            "migrations_applied": applied, "tokens": minted, "secrets": str(cfg.secrets_dir)}
    lines = [f"board DB {cfg.db_path} at schema {data['schema']}"
             + (f" (applied {applied})" if applied else " (up to date)")]
    lines += [f"token {label}: {state}" for label, state in minted.items()]
    lines.append(f"tokens in {cfg.secrets_dir} (0600; only sha256 in the DB)")
    ctx.out(data, "\n".join(lines))
    return EXIT_OK


def cmd_serve(ctx) -> int:
    import uvicorn

    from konstant.board.app import create_app
    from konstant.board.app import StartupError
    from konstant.board.policy import PolicyError
    from konstant.catalog import CatalogError
    from konstant.config import ConfigError, check_host
    cfg = ctx.cfg
    host = ctx.args.host or cfg.data["board"]["host"]
    port = ctx.args.port or cfg.data["board"]["port"]
    try:
        check_host(host, cfg.data["board"]["allow_remote"], "board serve --host")
        if not 1 <= int(port) <= 65535:
            raise ConfigError(f"board serve --port {port}: must be 1-65535")
    except ConfigError as exc:
        print(f"konstant: board refuses to start: {exc}", file=sys.stderr)
        return EXIT_FAIL
    try:
        app = create_app(cfg)
    except (StartupError, PolicyError, CatalogError) as exc:
        print(f"konstant: board refuses to start: {exc}", file=sys.stderr)
        return EXIT_FAIL
    uvicorn.run(app, host=host, port=port, log_level="info")
    return EXIT_OK


def _pid_file(cfg):
    return cfg.var / "board.pid"


def _read_pid(cfg):
    """The pid in var/board.pid when that process is alive AND is this workspace's board."""
    try:
        pid = int(_pid_file(cfg).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return None                    # another user's process is never ours to signal
    return pid if is_board(pid, cfg) else None


def is_board(pid: int, cfg) -> bool:
    """`konstant board serve` of THIS workspace (REVIEW F-23: a stale pid file after a crash and
    pid reuse must never make `board stop` signal an unrelated process)."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
    except OSError:
        r = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True,
                           text=True)
        argv = r.stdout.split()
    if not ("konstant" in argv and "board" in argv and "serve" in argv):
        return False
    try:
        return os.path.realpath(os.readlink(f"/proc/{pid}/cwd")) == os.path.realpath(cfg.home)
    except OSError:
        return True                    # no /proc (macOS): the command line is all we can check


def _healthy(cfg) -> bool:
    try:
        return bool(Client(cfg.base_url, timeout=2).get("/health").get("ok"))
    except ClientError:
        return False


def cmd_start(ctx) -> int:
    cfg = ctx.cfg
    pid = _read_pid(cfg)
    if pid and _healthy(cfg):
        ctx.out({"pid": pid, "url": cfg.base_url, "state": "running"},
                f"board already running (pid {pid}) at {cfg.base_url}")
        return EXIT_OK
    (cfg.var / "logs").mkdir(parents=True, exist_ok=True)
    log_path = cfg.var / "logs" / "board.log"
    env = dict(os.environ, KONSTANT_HOME=str(cfg.home))
    cmd = [sys.executable, "-m", "konstant", "board", "serve"]
    if ctx.args.config:
        cmd += ["--config", ctx.args.config]
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=env, cwd=str(cfg.home), start_new_session=True)
    _pid_file(cfg).write_text(f"{proc.pid}\n")
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _pid_file(cfg).unlink(missing_ok=True)
            tail = log_path.read_text(errors="replace").splitlines()[-15:]
            print("\n".join(tail), file=sys.stderr)
            print(f"konstant: board failed to start (exit {proc.returncode}); log {log_path}",
                  file=sys.stderr)
            return EXIT_FAIL
        if _healthy(cfg):
            ctx.out({"pid": proc.pid, "url": cfg.base_url, "state": "started"},
                    f"board started (pid {proc.pid}) at {cfg.base_url}; log {log_path}")
            return EXIT_OK
        time.sleep(0.2)
    print(f"konstant: board did not answer /health within {START_TIMEOUT_S}s; log {log_path}",
          file=sys.stderr)
    return EXIT_FAIL


def cmd_stop(ctx) -> int:
    cfg = ctx.cfg
    pid = _read_pid(cfg)
    if pid is None:
        stale = _pid_file(cfg).exists()
        _pid_file(cfg).unlink(missing_ok=True)
        ctx.out({"state": "stopped", "stale_pid_file": stale},
                "board not running" + (" (removed a stale pid file; its pid is not this "
                                       "workspace's board)" if stale else ""))
        return EXIT_OK
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)
    _pid_file(cfg).unlink(missing_ok=True)
    ctx.out({"pid": pid, "state": "stopped"}, f"board stopped (pid {pid})")
    return EXIT_OK


def cmd_status(ctx) -> int:
    cfg = ctx.cfg
    pid, up = _read_pid(cfg), _healthy(cfg)
    state = "running" if up else "down"
    ctx.out({"pid": pid, "url": cfg.base_url, "state": state},
            f"board {state} at {cfg.base_url}" + (f" (pid {pid})" if pid else ""))
    return EXIT_OK if up else EXIT_FAIL


def cmd_tokens(ctx) -> int:
    client = ctx.client(ctx.args.as_role or "owner")      # token administration is the owner's
    if ctx.args.label and not ctx.args.rotate:
        print("konstant: --label goes with --rotate ROLE", file=sys.stderr)
        return EXIT_FAIL
    if ctx.args.rotate:
        res = client.post("/api/tokens/rotate", {"role": ctx.args.rotate,
                                                 "label": ctx.args.label or ""})
        label = res.get("label") or res["role"]
        auth.write_token(ctx.cfg.secrets_dir, label, res["token"])
        ctx.out({"role": res["role"], "label": label, "rotated": True},
                f"token {label} ({res['role']}) rotated; new value in "
                f"{ctx.cfg.secrets_dir / (label + '.token')}")
        return EXIT_OK
    rows = client.get("/api/tokens")["tokens"]
    ctx.out(rows, "\n".join(f"{r['role']:<13} label={r['label']:<14} "
                            f"{'active' if r['active'] else 'revoked'}  {r['created_at']}"
                            for r in rows))
    return EXIT_OK


def backup(db_path: Path, dest: Path) -> Path:
    """SQLite online backup (consistent while the board runs); the copy is 0600."""
    if not Path(db_path).is_file():
        raise FileNotFoundError(f"no board DB at {db_path} (run `konstant board init`)")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"{dest} exists; choose another --to")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def cmd_backup(ctx) -> int:
    cfg = ctx.cfg
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(ctx.args.to) if ctx.args.to else cfg.var / "backups" / f"board-{stamp}.db"
    try:
        out = backup(cfg.db_path, dest)
    except (FileNotFoundError, FileExistsError, sqlite3.Error) as exc:
        print(f"konstant: backup failed: {exc}", file=sys.stderr)
        return EXIT_FAIL
    ctx.out({"backup": str(out), "bytes": out.stat().st_size},
            f"board DB backed up to {out} ({out.stat().st_size} bytes)")
    return EXIT_OK


def register(sub, leaf) -> None:
    b = sub.add_parser("board", help="the job board server")
    bs = b.add_subparsers(dest="board_cmd", metavar="ACTION")
    bs.required = True
    bs.add_parser("init", parents=[leaf], help="create/migrate the DB, mint missing tokens"
                  ).set_defaults(func=cmd_init)
    s = bs.add_parser("serve", parents=[leaf], help="run the server in the foreground")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.set_defaults(func=cmd_serve)
    bs.add_parser("start", parents=[leaf], help="start the server in the background"
                  ).set_defaults(func=cmd_start)
    bs.add_parser("stop", parents=[leaf], help="stop the background server"
                  ).set_defaults(func=cmd_stop)
    bs.add_parser("status", parents=[leaf], help="is the server up").set_defaults(func=cmd_status)
    t = bs.add_parser("tokens", parents=[leaf], help="list roles/labels; rotate one (acts as "
                      "owner unless --as says otherwise)")
    t.add_argument("--rotate", metavar="ROLE", help="replace this role's token (owner only)")
    t.add_argument("--label", metavar="LABEL", help="with --rotate: the factory identity of that "
                   "role to replace (planner, dod-reviewer, scenario: worker; factory: "
                   "orchestrator); default the role's own token")
    t.set_defaults(func=cmd_tokens)
    k = bs.add_parser("backup", parents=[leaf], help="online backup of the board DB "
                      "(default var/backups/board-<utc>.db)")
    k.add_argument("--to", metavar="PATH", help="write the copy here instead")
    k.set_defaults(func=cmd_backup)


__all__ = ["register", "warn"]
