"""install.sh (DESIGN §10): refusals, the wrapper it writes, idempotence, --from.

The full-install test creates a venv and pip-installs konstant (network or a warm pip cache);
set KONSTANT_SKIP_INSTALL_TESTS=1 to skip it on an offline machine."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from konstant.release import scan

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install.sh"


def stub(tmp_path, name="ws") -> Path:
    """A folder that passes install.sh's 'is this the unpacked konstant folder' check."""
    d = tmp_path / name
    (d / "src" / "konstant").mkdir(parents=True)
    (d / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    shutil.copy(INSTALL, d / "install.sh")
    return d


def sh(folder, *args, env=None, stdin=subprocess.DEVNULL):
    return subprocess.run(["bash", str(folder / "install.sh"), *args], capture_output=True,
                          text=True, env=env or dict(os.environ), stdin=stdin, timeout=600)


def test_the_tracked_wrapper_is_what_install_writes():
    body = re.search(r"cat > \"\$HERE/bin/konstant.tmp\" <<'EOF'\n(.*?)\nEOF\n",
                     INSTALL.read_text(), re.S).group(1)
    assert (REPO / "bin" / "konstant").read_text() == body + "\n"


def test_help_and_unknown_argument(tmp_path):
    d = stub(tmp_path)
    assert sh(d, "--help").returncode == 0
    res = sh(d, "--frob")
    assert res.returncode == 2 and "unknown argument: --frob" in res.stderr


def test_refuses_a_bare_command_harness(tmp_path):
    """`--harness command` would write the word itself as the argv template."""
    res = sh(stub(tmp_path), "--yes", "--harness", "command")
    assert res.returncode == 1 and "pass the command template itself" in res.stderr


def test_refuses_a_bad_confinement(tmp_path):
    res = sh(stub(tmp_path), "--yes", "--confinement", "ajar")
    assert res.returncode == 1 and "--confinement must be closed or open (got ajar)" in res.stderr


def test_confinement_is_asked_on_a_terminal(tmp_path):
    """Without --confinement and --yes, on a terminal: one question with its trade-off (an
    unknown answer stops before anything is installed)."""
    import pty
    import select
    import time
    folder = stub(tmp_path)
    master, slave = pty.openpty()
    p = subprocess.Popen(["bash", str(folder / "install.sh")], stdin=slave, stdout=slave,
                         stderr=slave, env=dict(os.environ), close_fds=True)
    os.close(slave)
    out, step, deadline = b"", 0, time.time() + 60
    while time.time() < deadline and p.poll() is None:
        r, _, _ = select.select([master], [], [], 0.5)
        if not r:
            continue
        try:
            out += os.read(master, 4096)
        except OSError:
            break
        if step == 0 and b"[y/N]" in out:
            os.write(master, b"y\n")
            step = 1
        elif step == 1 and b"[closed/open]" in out:
            os.write(master, b"ajar\n")
            step = 2
    p.wait(timeout=30)
    try:
        out += os.read(master, 4096)
    except OSError:
        pass
    os.close(master)
    text = out.decode(errors="replace")
    assert "closed keeps every phase inside this workspace; open gives phases your host" in text
    assert p.returncode == 1 and "answer closed or open (got ajar)" in text, text
    assert not (folder / ".venv").exists() and not (folder / "konstant.toml").exists()


def test_refuses_a_path_with_whitespace(tmp_path):
    d = stub(tmp_path, "my ws")
    res = sh(d, "--yes")
    assert res.returncode == 1 and "whitespace" in res.stderr


def test_refuses_without_yes_when_not_a_terminal(tmp_path):
    res = sh(stub(tmp_path))
    assert res.returncode == 1 and "pass --yes" in res.stderr


def test_refuses_outside_an_unpacked_folder(tmp_path):
    d = tmp_path / "bare"
    d.mkdir()
    shutil.copy(INSTALL, d / "install.sh")
    res = sh(d, "--yes")
    assert res.returncode == 1 and "unpacked konstant folder" in res.stderr


def test_refuses_an_old_python(tmp_path):
    d = stub(tmp_path)
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "python3").write_text("#!/bin/sh\n[ \"$1\" = -c ] && case \"$2\" in *version_info\\ \\>=*)"
                                  " exit 1;; *) echo 3.8.1;; esac\n")
    os.chmod(fake / "python3", 0o755)
    res = sh(d, "--yes", env=dict(os.environ, PYTHON=str(fake / "python3")))
    assert res.returncode == 1 and "Python >= 3.10" in res.stderr


def _no_venv_tools() -> bool:
    env = dict(os.environ, PATH="/usr/bin:/bin", PYTHONNOUSERSITE="1")
    ensurepip = subprocess.run(["/usr/bin/python3", "-c", "import ensurepip"], env=env,
                               capture_output=True).returncode == 0
    venvmod = subprocess.run(["/usr/bin/python3", "-m", "virtualenv", "--version"], env=env,
                             capture_output=True).returncode == 0
    return not (ensurepip or venvmod or Path("/usr/bin/virtualenv").exists()
                or Path("/bin/virtualenv").exists())


@pytest.mark.skipif(not Path("/usr/bin/python3").exists() or not _no_venv_tools(),
                    reason="needs a python3 without ensurepip and without virtualenv")
def test_names_the_exact_fix_when_venv_cannot_be_created(tmp_path):
    d = stub(tmp_path)
    res = sh(d, "--yes", env=dict(os.environ, PATH="/usr/bin:/bin", PYTHONNOUSERSITE="1",
                                  PYTHON="/usr/bin/python3"))
    assert res.returncode == 1
    assert "ensurepip module is missing" in res.stderr and "sudo apt install python3" in res.stderr
    assert not (d / ".venv").exists()


WORKSPACE_STATE = ("var/", ".venv/", "projects/", "dist/")


def _copy_release_tree(dest: Path) -> Path:
    """The release files of REPO, never an installed folder's own state (REVIEW F-33: the suite
    run inside an installed folder copied its var/board.db into the 'fresh' tree)."""
    for rel in scan.tree_files(REPO):
        if rel == "konstant.toml" or rel.startswith(WORKSPACE_STATE):
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dest / rel)
    return dest


def _hashes(folder: Path) -> dict:
    files = sorted((folder / "var" / "secrets").glob("*.token")) + [folder / "konstant.toml"]
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


@pytest.mark.skipif(os.environ.get("KONSTANT_SKIP_INSTALL_TESTS") == "1",
                    reason="KONSTANT_SKIP_INSTALL_TESTS=1")
def test_install_twice_is_idempotent_then_upgrade_with_from(tmp_path):
    old = _copy_release_tree(tmp_path / "old")
    env = {k: v for k, v in os.environ.items() if not k.startswith("KONSTANT_")}
    harness = "python3 -c pass {prompt}"
    first = sh(old, "--yes", "--port", "18999", "--harness", harness, "--confinement", "open",
               env=env)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "0 FAIL" in first.stdout and os.access(old / "bin" / "konstant", os.X_OK)
    assert "(board port 18999, confinement open)" in first.stdout          # L5-2b
    assert '[confinement]' in (old / "konstant.toml").read_text() and \
        'profile = "open"' in (old / "konstant.toml").read_text()
    before = _hashes(old)
    assert len(before) == 10        # 9 tokens (5 roles + 4 factory identities, LEVEL5 2.2) + konstant.toml
    second = sh(old, "--yes", env=env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "kept existing konstant.toml" in second.stdout and "token owner: kept" in second.stdout
    assert _hashes(old) == before

    (old / "memory" / "owner").mkdir(parents=True)                 # the memory vault (L5-M)
    (old / "memory" / "owner" / "Kept.md").write_text("---\ntitle: Kept\n---\nkept\n")
    new = _copy_release_tree(tmp_path / "new")
    up = sh(new, "--yes", "--from", str(old), env=env)
    assert up.returncode == 0, up.stdout + up.stderr
    assert _hashes(new) == before
    assert (new / "memory" / "owner" / "Kept.md").read_text().endswith("kept\n")
    assert list((old / "var" / "backups").glob("board-*.db")), "the old DB was not backed up"
    assert sh(new, "--yes", "--from", str(old), env=env).returncode == 1   # new already has a DB
