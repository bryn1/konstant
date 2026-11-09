"""The ship repository: a bare git repository konstant owns, per project, that every ship and
rollback works from (docs/LEVEL5.md 5; REVIEW L5-R1 H-02, H-07: never trust the job clone's .git).

`var/factory/ship/<slug>.git` (machinery: no phase writes var/factory) is created by konstant with
no template, no hooks and no config beyond its own; its object store borrows the TARGET's objects
as an alternate (the owner's repository, read-only to every factory phase). The verified commit
reaches it only through `transfer()`:

  - the job clone is read through a throwaway konstant-owned bare repository whose only link to
    the clone is an alternate on its object directory: no ref, replace ref, graft, shallow file,
    config, hook, attribute or filter of the clone is ever read (GIT_NO_REPLACE_OBJECTS=1 as well);
  - konstant walks the commit itself (commit -> tree + parents, tree -> entries) from the raw
    bytes, stopping at objects the destination already has;
  - every object's bytes are HASHED BY KONSTANT and must equal the id they were asked for (a
    planted loose object or pack entry whose content is not its id is refused), then written as a
    loose object into the destination.

So the commit in the ship repository is exactly the id the evidence names and the verifier ran
the holdouts on: a git id is its content. The same `transfer()` copies shipped and rollback
commits into the local target. Every git command here runs konstant's pinned git (tools.git) with
no system/global config, no hooks path, no fsmonitor, no commit-graph or multi-pack index, and
transports off except for the ship's own push and fetch (`net_env`).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path

from konstant.gate.rules.common import GIT_ISOLATION

PINNED = GIT_ISOLATION + ("-c", "core.commitGraph=false", "-c", "core.multiPackIndex=false",
                          "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                          "-c", "core.sshCommand=/bin/false", "-c", "credential.helper=")
NET = ("-c", "protocol.file.allow=always", "-c", "protocol.https.allow=always",
       "-c", "protocol.ssh.allow=always")
IDENT = {"GIT_AUTHOR_NAME": "konstant", "GIT_AUTHOR_EMAIL": "konstant@konstant.invalid",
         "GIT_COMMITTER_NAME": "konstant", "GIT_COMMITTER_EMAIL": "konstant@konstant.invalid"}
HEX = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
BATCH = 500


class ShipRepoError(Exception):
    """The ship repository cannot be prepared or an object is not what its id says: no ship."""


def git_env(extra: dict | None = None) -> dict:
    """konstant's own git environment for the ship: nothing inherited but HOME and the locale (no
    GIT_* variable of the calling shell: an inherited GIT_ALTERNATE_OBJECT_DIRECTORIES or
    GIT_DIR would change what a ship reads), the trusted PATH, no system/global config, no
    replace objects, no ssh unless the push names one."""
    from konstant import tools
    env = {k: os.environ[k] for k in ("HOME", "LANG", "LC_ALL") if os.environ.get(k)}
    env.update(PATH=tools.trusted_path(), GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_ATTR_NOSYSTEM="1",
               GIT_PAGER="cat", GIT_NO_REPLACE_OBJECTS="1", GIT_SSH_COMMAND="/bin/false")
    env.update(extra or {})
    return env


def run(repo, *args, data: bytes | None = None, env: dict | None = None, net: tuple = (),
        timeout: int = 300) -> subprocess.CompletedProcess:
    from konstant import tools
    full = git_env(env)
    return subprocess.run([tools.git(), *PINNED, *net, "-C", str(repo), *args], input=data,
                          capture_output=True, env=full, timeout=timeout,
                          stdin=None if data is not None else subprocess.DEVNULL)


def out(repo, *args, **kw) -> str:
    r = run(repo, *args, **kw)
    if r.returncode != 0:
        raise ShipRepoError(f"git {args[0]} failed: "
                            f"{(r.stderr or r.stdout).decode('utf-8', 'replace').strip()[-300:]}")
    return r.stdout.decode("utf-8", "replace").strip()


def full_sha(text) -> bool:
    return isinstance(text, str) and bool(HEX.match(text))


def git_dir(repo) -> Path:
    d = out(repo, "rev-parse", "--git-common-dir")
    return Path(d if os.path.isabs(d) else os.path.join(str(repo), d)).resolve()


def object_format(repo) -> str:
    return "sha256" if out(repo, "rev-parse", "--show-object-format") == "sha256" else "sha1"


def path_for(cfg, slug: str) -> Path:
    return cfg.home / "var" / "factory" / "ship" / f"{slug}.git"


def ensure(cfg, slug: str, target) -> Path:
    """The ship repository of project `slug` (created on first use), borrowing the target's objects
    as an alternate. Refuses a target that is not a git repository."""
    tgd = git_dir(target)
    fmt = object_format(target)
    repo = path_for(cfg, slug)
    if not (repo / "objects").is_dir():
        repo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        r = run(repo.parent, "init", "-q", "--bare", "--template=", f"--object-format={fmt}",
                str(repo))
        if r.returncode != 0:
            raise ShipRepoError("cannot create the ship repository: "
                                + r.stderr.decode("utf-8", "replace").strip()[-200:])
    if object_format(repo) != fmt:
        raise ShipRepoError(f"the ship repository {repo} and the target differ in object format")
    info = repo / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(str(tgd / "objects") + "\n", encoding="utf-8")
    return repo


def oid_of(kind: str, data: bytes, algo: str) -> str:
    h = hashlib.new(algo)
    h.update(f"{kind} {len(data)}\0".encode())
    h.update(data)
    return h.hexdigest()


def write_loose(objects: Path, kind: str, data: bytes, algo: str) -> str:
    """Write one object (header + data, zlib) as a loose object; returns its id."""
    oid = oid_of(kind, data, algo)
    dest = Path(objects) / oid[:2] / oid[2:]
    if dest.exists():
        return oid
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix="tmp_obj_")
    with os.fdopen(fd, "wb") as fh:
        fh.write(zlib.compress(f"{kind} {len(data)}\0".encode() + data))
    os.chmod(tmp, 0o444)
    os.replace(tmp, dest)
    return oid


def missing(repo, oids: list) -> list:
    """The ids of `oids` that repository `repo` (own objects + alternates) does not have."""
    if not oids:
        return []
    r = run(repo, "cat-file", "--batch-check", data="".join(o + "\n" for o in oids).encode())
    if r.returncode != 0:
        raise ShipRepoError("cannot check the objects of " + str(repo))
    lines = r.stdout.decode().splitlines()
    return [o for o, ln in zip(oids, lines) if ln.endswith(" missing")]


def read_batch(repo, oids: list) -> dict:
    """{oid: (type, bytes)} from `cat-file --batch` (raw objects, no filter, no textconv)."""
    if not oids:
        return {}
    r = run(repo, "cat-file", "--batch", data="".join(o + "\n" for o in oids).encode())
    if r.returncode != 0:
        raise ShipRepoError("cannot read objects")
    buf, i, res = r.stdout, 0, {}
    for oid in oids:
        nl = buf.index(b"\n", i)
        head = buf[i:nl].split()
        if len(head) != 3:
            raise ShipRepoError(f"object {oid} is missing from the job's result")
        size = int(head[2])
        res[oid] = (head[1].decode(), buf[nl + 1:nl + 1 + size])
        i = nl + 1 + size + 1
    return res


def children(kind: str, data: bytes, algo: str) -> list:
    """The objects a commit or tree names (parsed by konstant from verified bytes)."""
    n = 32 if algo == "sha256" else 20
    out_ = []
    if kind == "commit":
        for line in data.split(b"\n\n", 1)[0].split(b"\n"):
            if line.startswith((b"tree ", b"parent ")):
                out_.append(line.split(b" ", 1)[1].decode())
    elif kind == "tree":
        i = 0
        while i < len(data):
            sp, nul = data.index(b" ", i), data.index(b"\0", i)
            mode = data[i:sp]
            oid = data[nul + 1:nul + 1 + n].hex()
            if mode != b"160000":                 # a submodule commit is another repository
                out_.append(oid)
            i = nul + 1 + n
    elif kind not in ("blob", "tag"):
        raise ShipRepoError(f"unexpected object type {kind}")
    return out_


def transfer(src, dst, tip: str) -> int:
    """Copy the closure of commit `tip` from repository `src` into repository `dst` (its own object
    store), stopping at what `dst` already has. Each object is re-hashed by konstant: bytes that
    do not hash to their id refuse the transfer. Returns the number of objects written."""
    algo = object_format(dst)
    objects = git_dir(dst) / "objects"
    todo, seen, written = [tip], set(), 0
    while todo:
        todo = [o for o in dict.fromkeys(todo) if o not in seen]
        seen.update(todo)
        nxt = []
        for k in range(0, len(todo), BATCH):
            need = missing(dst, todo[k:k + BATCH])
            for oid, (kind, data) in read_batch(src, need).items():
                if oid_of(kind, data, algo) != oid:
                    raise ShipRepoError(f"object {oid} does not hash to its id: the job's result "
                                        "carries a forged object (nothing shipped)")
                write_loose(objects, kind, data, algo)
                written += 1
                nxt += children(kind, data, algo)
        todo = nxt
    if out(dst, "cat-file", "-t", tip) != "commit":
        raise ShipRepoError(f"{tip} is not a commit")
    return written


def import_from_clone(cfg, repo, clone, commit: str) -> int:
    """Copy the verified commit out of the job clone into the ship repository without reading
    anything of the clone but object bytes (see the module doc)."""
    real = os.path.realpath(os.path.join(str(clone), ".git", "objects"))
    if not os.path.isdir(real):
        raise ShipRepoError(f"the job clone {clone} has no object store")
    tmp = Path(tempfile.mkdtemp(prefix="import-", dir=str(Path(repo).parent)))
    try:
        out(tmp.parent, "init", "-q", "--bare", "--template=",
            f"--object-format={object_format(repo)}", str(tmp))
        (tmp / "objects" / "info").mkdir(parents=True, exist_ok=True)
        (tmp / "objects" / "info" / "alternates").write_text(real + "\n", encoding="utf-8")
        return transfer(tmp, repo, commit)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def tree_of(repo, rev: str) -> str:
    return out(repo, "rev-parse", "--verify", "-q", f"{rev}^{{tree}}")


def is_ancestor(repo, a: str, b: str) -> bool:
    return run(repo, "merge-base", "--is-ancestor", a, b).returncode == 0


def commit_tree(repo, tree: str, parents: list, message: str) -> str:
    args = ["commit-tree", tree]
    for p in parents:
        args += ["-p", p]
    return out(repo, *args, "-m", message, env=IDENT)


def update_ref(repo, ref: str, new: str, old: str) -> None:
    """Compare-and-swap: `ref` moves from `old` to `new` or not at all."""
    r = run(repo, "update-ref", ref, new, old)
    if r.returncode != 0:
        raise ShipRepoError(f"target moved: {ref} is no longer {old[:12]} "
                            f"({r.stderr.decode('utf-8', 'replace').strip()[-160:]})")


def changes(repo, pre: str, commit: str) -> list:
    """[(status, path, old_oid, new_oid, new_mode)] of `pre..commit` (plumbing diff-tree, no
    renames, no textconv)."""
    r = run(repo, "diff-tree", "-r", "-z", "--no-renames", "--raw", "--no-commit-id", pre, commit)
    if r.returncode != 0:
        raise ShipRepoError("cannot list the change being shipped")
    parts = r.stdout.split(b"\0")
    res, i = [], 0
    while i + 1 < len(parts):
        meta = parts[i].decode()
        if not meta.startswith(":"):
            i += 1
            continue
        _om, nm, oo, no, st = meta[1:].split()
        res.append((st[0], parts[i + 1].decode("utf-8", "surrogateescape"), oo, no, nm))
        i += 2
    return res
