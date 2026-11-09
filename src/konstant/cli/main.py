"""`konstant` entry point: global flags, subcommand dispatch, exit codes (DESIGN §12).

Exit codes: 0 ok, 1 refused or failed, 2 usage error or not found.
Global flags (`--as ROLE`, `--json`, `--config PATH`) are accepted before the subcommand and on
every leaf command.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from konstant import __version__
from konstant import config as config_mod
from konstant.board.policy import LABELS
from konstant.client import Client, ClientError, default_role, token_for

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


class Ctx:
    def __init__(self, args):
        self.args = args
        self._cfg = None

    @property
    def cfg(self):
        if self._cfg is None:
            self._cfg = config_mod.load(config_path=self.args.config)
        return self._cfg

    @property
    def role(self) -> str:
        return self.args.as_role or default_role(self.cfg.data["client"]["default_role"])

    def client(self, role: str | None = None) -> Client:
        return Client(self.cfg.base_url, token_for(self.cfg, role or self.role))

    def out(self, data, human: str | None = None) -> None:
        if self.args.json or human is None:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            print(human)


def warn(msg: str) -> None:
    print(f"konstant WARN: {msg}", file=sys.stderr)


def common_flags(suppress: bool) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    d = {"default": argparse.SUPPRESS} if suppress else {}
    p.add_argument("--as", dest="as_role", choices=LABELS, metavar="ROLE",
                   help="act with this role's token, or a factory identity's (planner, "
                   "dod-reviewer, scenario, factory) (default [client] default_role)",
                   **({"default": None} if not suppress else d))
    p.add_argument("--json", action="store_true", help="print JSON", **d)
    p.add_argument("--config", metavar="PATH", help="konstant.toml to use",
                   **({"default": None} if not suppress else d))
    return p


def build_parser() -> argparse.ArgumentParser:
    from konstant.cli import (agents, board, confinement, doctor, dsh, factory, goal, holdout,
                              job, memory, project, ship, task, verify)
    parser = argparse.ArgumentParser(prog="konstant", parents=[common_flags(False)],
                                     description="konstant: job board, task gate and verifier "
                                                 "for coding agents.")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    leaf = common_flags(True)
    board.register(sub, leaf)
    project.register(sub, leaf)
    job.register(sub, leaf)
    task.register(sub, leaf)
    verify.register(sub, leaf)
    holdout.register(sub, leaf)
    goal.register(sub, leaf)
    ship.register(sub, leaf)
    factory.register(sub, leaf)
    memory.register(sub, leaf)
    agents.register(sub, leaf)
    dsh.register(sub, leaf)
    confinement.register(sub, leaf)
    doctor.register(sub, leaf)
    v = sub.add_parser("version", parents=[leaf], help="print the version")
    v.set_defaults(func=lambda ctx: ctx.out({"version": __version__},
                                            f"konstant {__version__}") or EXIT_OK)
    return parser


def drop_shim_dir() -> None:
    """Inside a `konstant dsh` session the PATH starts with the refusing agent-CLI shims
    (cli/dsh.py, [confinement] host_agents): konstant itself drops them, so the harness CLIs of
    its own phases (which it jails and composes) are found."""
    shim = os.environ.get("KONSTANT_SHIM_DIR")
    if shim:
        parts = os.environ.get("PATH", "").split(os.pathsep)
        os.environ["PATH"] = os.pathsep.join(p for p in parts if p and p != shim)


def main(argv=None) -> int:
    # everything konstant writes (DB, tokens, run records, logs) is private to this user
    # (REVIEW F-25); harness phases get the caller's own umask back (gate/harness.py)
    config_mod.ORIG_UMASK = os.umask(0o077)
    drop_shim_dir()
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = Ctx(args)
    try:
        rc = args.func(ctx)
    except ClientError as exc:
        print(f"konstant: {exc.message}", file=sys.stderr)
        if exc.exit_code is not None:
            return exc.exit_code
        return EXIT_USAGE if exc.status == 404 else EXIT_FAIL
    except config_mod.ConfigError as exc:
        print(f"konstant: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except KeyboardInterrupt:
        return 130
    return EXIT_OK if rc is None else int(rc)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
