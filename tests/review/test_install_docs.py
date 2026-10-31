"""Install / release / docs findings: F-17 (offline wheels), F-32 (install.sh port range),
F-33 (suite inside an installed folder), F-34 (DESIGN drift)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.release import test_install

REPO = Path(__file__).resolve().parents[2]
SKIP_INSTALL = os.environ.get("KONSTANT_SKIP_INSTALL_TESTS") == "1"


def _mini_tree(dest: Path) -> Path:
    dest.mkdir(parents=True)
    shutil.copy2(REPO / "install.sh", dest / "install.sh")
    shutil.copy2(REPO / "pyproject.toml", dest / "pyproject.toml")
    (dest / "src" / "konstant").mkdir(parents=True)
    return dest


@pytest.mark.parametrize("port", ["99999", "80", "0"])
def test_F32_install_refuses_an_out_of_range_port(tmp_path, port):
    tree = _mini_tree(tmp_path / "k")
    res = subprocess.run(["bash", str(tree / "install.sh"), "--yes", "--port", port],
                         capture_output=True, text=True, timeout=60, cwd=str(tree))
    assert res.returncode == 1 and "--port" in res.stderr, res.stderr
    assert not (tree / ".venv").exists()


def test_F33_the_release_copy_skips_workspace_state(tmp_path, monkeypatch):
    src = tmp_path / "installed"
    for rel in ("pyproject.toml", "src/konstant/__init__.py", "var/board.db",
                ".venv/bin/python", "projects/demo/x.py", "konstant.toml", "bin/konstant"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("x\n")
    monkeypatch.setattr(test_install, "REPO", src)
    dest = test_install._copy_release_tree(tmp_path / "copy")
    for rel in ("var/board.db", ".venv/bin/python", "projects/demo/x.py", "konstant.toml"):
        assert not (dest / rel).exists(), rel
    assert (dest / "src" / "konstant" / "__init__.py").is_file()


def test_F34_design_lists_no_job_close_verify_flag():
    design = REPO / "docs" / "DESIGN.md"
    if not design.is_file():
        pytest.skip("DESIGN.md not in this tree")
    rows = [ln for ln in design.read_text().splitlines() if ln.startswith("| `job close")]
    assert rows and not any("--verify" in r for r in rows), rows


@pytest.mark.skipif(SKIP_INSTALL, reason="KONSTANT_SKIP_INSTALL_TESTS=1")
def test_F17_offline_install_from_a_pip_download_dir(tmp_path):
    tree = test_install._copy_release_tree(tmp_path / "k")
    wheels = tmp_path / "wheels"
    # REVIEW F-17 exactly: `pip download -d wheels <folder>` (no setuptools in the dir)
    dl = subprocess.run([sys.executable, "-m", "pip", "download", "-q", "-d", str(wheels),
                         str(tree)], capture_output=True, text=True, timeout=600)
    if dl.returncode != 0:
        pytest.skip(f"no package index reachable to build the wheel dir: {dl.stderr[-200:]}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("KONSTANT_")}
    dead = "http://127.0.0.1:9"      # the network is blocked: any index or proxy use fails
    env.update(PIP_INDEX_URL=dead, http_proxy=dead, https_proxy=dead, HTTP_PROXY=dead,
               HTTPS_PROXY=dead, PIP_NO_INPUT="1")
    res = subprocess.run(["./install.sh", "--yes", "--port", "18997", "--wheels", str(wheels),
                          "--harness", "python3 -c pass {prompt}"], capture_output=True,
                         text=True, timeout=900, cwd=str(tree), env=env)
    assert res.returncode == 0, res.stdout[-2000:] + res.stderr[-2000:]
    assert "konstant" in res.stdout and "installed" in res.stdout
