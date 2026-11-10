"""get.sh, the one-line installer (DESIGN §10.1): the release in dist/ is served by a local
http.server laid out like GitHub releases, and `curl -fsSL <url>/latest/download/get.sh | bash`
runs against it through KONSTANT_RELEASE_URL (never the real URL).

The happy-path test creates a venv and pip-installs konstant (network or a warm pip cache); set
KONSTANT_SKIP_INSTALL_TESTS=1 to skip it on an offline machine."""
from __future__ import annotations

import functools
import http.server
import os
import pty
import re
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from konstant import __version__
from konstant.release import build as b

REPO = Path(__file__).resolve().parents[2]
GET = REPO / "get.sh"
V = __version__
TB = f"konstant-{V}.tar.gz"
ONE_LINER = ("curl -fsSL https://github.com/bryn1/konstant/releases/latest/download/get.sh "
             "| bash")


@pytest.fixture(scope="module")
def dist(tmp_path_factory):
    """The release assets, built from the current work tree (scan included)."""
    d = tmp_path_factory.mktemp("dist")
    deny = REPO / "release" / "denylist.local.txt"
    ok, text = b.build(REPO, V, deny if deny.is_file() else None, dist=d, worktree=True)
    assert ok, text
    return d


class Server:
    def __init__(self, root: Path):
        self.root, self.paths = root, []
        log = self.paths

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, fmt, *args):
                log.append(self.path)

        self.httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def downloads(self) -> list:
        return [p for p in self.paths if not p.endswith("/get.sh")]


@pytest.fixture()
def srv(dist, tmp_path):
    """dist/ in the GitHub layout: latest/download/{get.sh,VERSION}, download/v<V>/<assets>."""
    root = tmp_path / "srv"
    latest, tagged = root / "latest" / "download", root / "download" / f"v{V}"
    latest.mkdir(parents=True)
    tagged.mkdir(parents=True)
    for f in ("get.sh", "VERSION"):
        shutil.copy(dist / f, latest / f)
    for f in (TB, f"{TB}.sha256", "get.sh"):
        shutil.copy(dist / f, tagged / f)
    s = Server(root)
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


@pytest.fixture()
def cwd(tmp_path):
    d = tmp_path / "here"
    d.mkdir()
    return d


def oneliner(srv, cwd, *args, shell="bash", env=None, timeout=900):
    """The documented one-liner with KONSTANT_RELEASE_URL pointing at the local server."""
    e = {k: v for k, v in (env or os.environ).items() if k not in ("PYTHON", "KONSTANT_HOME")}
    e["KONSTANT_RELEASE_URL"] = srv.url
    cmd = f'curl -fsSL "$KONSTANT_RELEASE_URL/latest/download/get.sh" | {shell} -s -- "$@"'
    return subprocess.run(["bash", "-c", cmd, "one-liner", *args], cwd=cwd, env=e, text=True,
                          capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout,
                          start_new_session=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def farm(tmp_path, drop=("python",), add=None,
         sources=(Path("/usr/bin"), Path("/bin"))) -> str:
    """A PATH of symlinks to /usr/bin and /bin without the tools named in drop, plus fakes.
    On a merged-/usr system both name the same directory, and a dangling link there (the CI
    runner has some) made `exists()` false for the link already made: lexists, once per name."""
    d = tmp_path / "farm"
    d.mkdir()
    for src in sources:
        for p in src.iterdir():
            if not p.name.startswith(drop) and not os.path.lexists(d / p.name):
                (d / p.name).symlink_to(p)
    for name, body in (add or {}).items():
        (d / name).unlink(missing_ok=True)
        (d / name).write_text("#!/bin/sh\n" + body + "\n")
        (d / name).chmod(0o755)
    return str(d)


def test_farm_survives_merged_usr_with_a_dangling_link(tmp_path):
    """The CI runner's merged /usr: /bin and /usr/bin are one directory holding a dangling link
    (grub-ntldr-img); the farm made it twice -> FileExistsError in six tests."""
    real = tmp_path / "usr-bin"
    real.mkdir()
    (real / "broken").symlink_to(tmp_path / "nowhere")
    (real / "tool").write_text("#!/bin/sh\n")
    (tmp_path / "bin").symlink_to(real)
    d = Path(farm(tmp_path, sources=(real, tmp_path / "bin")))
    assert sorted(p.name for p in d.iterdir()) == ["broken", "tool"]


# --- static: the script itself ---------------------------------------------------------------

def test_shellcheck_clean():
    exe = shutil.which("shellcheck") or str(Path(sys.executable).parent / "shellcheck")
    if not os.access(exe, os.X_OK):
        pytest.skip("shellcheck not installed (pip install shellcheck-py into the dev venv)")
    res = subprocess.run([exe, "-s", "sh", str(GET)], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout


def test_every_top_level_line_is_a_definition_except_the_braced_last_call():
    """The truncation guarantee rests on this shape: no command runs before the last line."""
    lines = GET.read_text().splitlines()
    assert lines[-1] == '{ konstant_get "$@"; }'
    depth, stray = 0, []
    for ln in lines[:-1]:
        if depth == 0 and ln and not ln.startswith("#"):
            if not re.match(r"^[a-z0-9_]+\(\) \{", ln):
                stray.append(ln)
        if re.match(r"^[a-z0-9_]+\(\) \{$", ln):
            depth += 1
        elif ln == "}":
            depth -= 1
        elif re.match(r"^[a-z0-9_]+\(\) \{ .*\}$", ln):
            pass
    assert depth == 0 and not stray, stray


def test_readme_and_quickstart_carry_the_one_liner_and_get_sh_its_url():
    for doc in ("README.md", "docs/QUICKSTART.md"):
        assert ONE_LINER in (REPO / doc).read_text(), doc
    text = GET.read_text()
    assert "${KONSTANT_RELEASE_URL:-https://github.com/bryn1/konstant/releases}" in text
    assert ONE_LINER in text


def test_usage_errors_exit_2(cwd):
    for args, msg in ((["--frob"], "unknown argument: --frob"), (["--dir"], "--dir needs a value"),
                      (["--harness", "command"], "pass the command itself")):
        res = subprocess.run(["sh", str(GET), *args], cwd=cwd, capture_output=True, text=True)
        assert res.returncode == 2 and msg in res.stderr, res.stderr
    assert subprocess.run(["sh", str(GET), "--help"], capture_output=True).returncode == 0
    assert not list(cwd.iterdir())


@pytest.mark.parametrize("bad", ["latest", "1.0;rm", "../1.0", "1..2"])
def test_a_bad_version_is_refused_before_anything_is_written(cwd, bad):
    res = subprocess.run(["sh", str(GET), "--version", bad, "--no-install"], cwd=cwd,
                         capture_output=True, text=True)
    assert res.returncode == 1 and "not a release version" in res.stderr
    assert not list(cwd.iterdir())


# --- truncation: a partial download runs nothing -----------------------------------------------

def _cuts(n: int) -> list:
    return sorted(set(range(0, n - 1, 7)) | set(range(max(0, n - 120), n - 1)))


def test_every_truncation_runs_nothing(tmp_path):
    """Feed every 7th prefix and every one of the last 120 to bash (and the tail ones to sh):
    nothing is created, nothing is printed by the script, nothing is downloaded."""
    data = GET.read_bytes()
    env = dict(os.environ, KONSTANT_RELEASE_URL="http://127.0.0.1:9")
    ran = []
    for cut in _cuts(len(data)):
        for shell in (("bash", "sh") if cut >= len(data) - 120 else ("bash",)):
            d = tmp_path / f"c{cut}{shell}"
            d.mkdir()
            res = subprocess.run([shell, "-s", "--", "--no-install"], input=data[:cut], cwd=d,
                                 env=env, capture_output=True, timeout=30)
            # bash's syntax error may quote a script line; a line the script printed starts
            # with its prefix
            said = [ln for ln in (res.stdout + res.stderr).splitlines()
                    if ln.startswith(b"konstant-get")]
            if list(d.iterdir()) or said:
                ran.append((shell, cut, (res.stdout + res.stderr)[-200:]))
            shutil.rmtree(d)
    assert not ran, ran[:5]


def test_a_truncated_download_through_curl_runs_nothing(srv, cwd):
    full = (srv.root / "latest" / "download" / "get.sh").read_bytes()
    # cuts inside a function body and inside the last line: a syntax error, so a non-zero exit
    # (a cut between two definitions only defines functions: it runs nothing either, exit 0, as
    # test_every_truncation_runs_nothing checks; a fixed `len // 2` landed there once)
    for cut in (full.index(b"kg_download() {") + 40, len(full) - 3):
        (srv.root / "latest" / "download" / "get.sh").write_bytes(full[:cut])
        res = oneliner(srv, cwd)
        said = [ln for ln in (res.stdout + res.stderr).splitlines()
                if ln.startswith("konstant-get")]
        assert res.returncode != 0 and not said, res.stderr
        assert not list(cwd.iterdir()) and srv.downloads() == []


# --- refusals: nothing left behind ---------------------------------------------------------------

def test_checksum_mismatch_refuses_and_leaves_nothing_behind(srv, cwd):
    tb = srv.root / "download" / f"v{V}" / TB
    tb.write_bytes(tb.read_bytes() + b"\0")
    res = oneliner(srv, cwd, "--no-install")
    assert res.returncode == 1 and "CHECKSUM MISMATCH" in res.stderr, res.stderr
    assert "refusing to unpack" in res.stderr
    assert not list(cwd.iterdir())
    (cwd / "empty").mkdir()            # a pre-existing empty target stays, and stays empty
    res = oneliner(srv, cwd, "--no-install", "--dir", "empty")
    assert res.returncode == 1 and not list((cwd / "empty").iterdir())
    assert [p.name for p in cwd.iterdir()] == ["empty"]


def test_a_malformed_or_foreign_checksum_file_is_refused(srv, cwd):
    sums = srv.root / "download" / f"v{V}" / f"{TB}.sha256"
    good = sums.read_text()
    for bad in ("not-a-sum\n", good.replace(TB, "other.tar.gz"), ""):
        sums.write_text(bad)
        res = oneliner(srv, cwd, "--no-install")
        assert res.returncode == 1 and "malformed" in res.stderr, (bad, res.stderr)
        assert not list(cwd.iterdir())


def test_a_missing_release_is_refused_and_leaves_nothing(srv, cwd):
    res = oneliner(srv, cwd, "--no-install", "--version", "9.9.9")
    assert res.returncode == 1 and "download failed" in res.stderr
    assert not list(cwd.iterdir())


def test_an_existing_non_empty_dir_is_refused(srv, cwd):
    (cwd / "konstant").mkdir()
    (cwd / "konstant" / "notes.txt").write_text("mine\n")
    res = oneliner(srv, cwd)
    assert res.returncode == 1 and "not empty: refusing to overwrite" in res.stderr
    assert [p.name for p in (cwd / "konstant").iterdir()] == ["notes.txt"]
    assert srv.downloads() == []


def test_missing_python_is_reported_before_any_download(srv, cwd, tmp_path):
    path = farm(tmp_path)
    res = oneliner(srv, cwd, "--no-install", env=dict(os.environ, PATH=path))
    assert res.returncode == 1 and "Python >= 3.10 not found" in res.stderr, res.stderr
    assert not list(cwd.iterdir()) and srv.downloads() == []


def test_an_old_python_is_named(srv, cwd, tmp_path):
    path = farm(tmp_path, add={"python3": 'case "$*" in *version_info*) exit 1;; '
                               '*) echo 3.8.10;; esac'})
    res = oneliner(srv, cwd, "--no-install", env=dict(os.environ, PATH=path))
    assert res.returncode == 1 and "python3 is 3.8.10" in res.stderr, res.stderr
    assert not list(cwd.iterdir())


def test_root_is_refused(srv, cwd, tmp_path):
    path = farm(tmp_path, drop=("id",), add={"id": "echo 0"})
    res = oneliner(srv, cwd, "--no-install", env=dict(os.environ, PATH=path))
    assert res.returncode == 1 and "do not run as root" in res.stderr
    assert not list(cwd.iterdir())


def test_missing_tools_are_named(srv, cwd, tmp_path):
    path = farm(tmp_path, drop=("python", "sha256sum", "shasum", "wget"))
    # curl stays (the one-liner needs it); the script itself must find no checksum tool
    res = oneliner(srv, cwd, "--no-install", env=dict(os.environ, PATH=path))
    assert res.returncode == 1 and "sha256sum-or-shasum" in res.stderr, res.stderr


# --- the happy paths ----------------------------------------------------------------------------

@pytest.mark.parametrize("shell", ["bash", "sh"])
def test_download_verify_unpack_latest_by_default(srv, cwd, shell):
    res = oneliner(srv, cwd, "--no-install", shell=shell)
    assert res.returncode == 0, res.stderr
    ws = cwd / "konstant"
    assert (ws / "install.sh").is_file() and (ws / "get.sh").is_file()
    assert not (ws / ".konstant-get").exists() and [p.name for p in cwd.iterdir()] == ["konstant"]
    assert "sha256 OK" in res.stdout and "./install.sh --yes" in res.stdout
    assert srv.downloads() == ["/latest/download/VERSION", f"/download/v{V}/{TB}",
                               f"/download/v{V}/{TB}.sha256"]


def test_version_flag_skips_the_latest_lookup(srv, cwd):
    res = oneliner(srv, cwd, "--no-install", "--version", f"v{V}", "--dir", "pinned")
    assert res.returncode == 0, res.stderr
    assert (cwd / "pinned" / "install.sh").is_file()
    assert "/latest/download/VERSION" not in srv.paths


def test_harness_is_detected_on_path_when_not_asked(srv, cwd, tmp_path):
    """No terminal, no --harness: the first agent CLI on PATH is chosen and passed on."""
    path = farm(tmp_path, drop=("python", "claude", "codex", "gemini", "dsh"),
                add={"codex": "echo codex-cli 1"})
    env = dict(os.environ, PATH=path, PYTHON=sys.executable)
    e = {**env, "KONSTANT_RELEASE_URL": srv.url}
    res = subprocess.run(["sh", str(GET), "--port", "80"], cwd=cwd, env=e, text=True,
                         capture_output=True, stdin=subprocess.DEVNULL, start_new_session=True)
    # --port 80 makes install.sh stop at once: the harness decision is what is under test
    assert "harness: codex" in res.stdout, res.stdout + res.stderr
    assert "running ./install.sh --yes --harness codex --port 80" in res.stdout
    assert res.returncode == 1 and "--port must be 1024-65535" in res.stderr
    assert "the files stay in" in res.stderr and (cwd / "konstant" / "install.sh").is_file()


def test_harness_is_asked_on_a_terminal(srv, cwd):
    """`curl | bash` has the script on stdin: the question goes to /dev/tty."""
    master, slave = pty.openpty()
    env = {**os.environ, "KONSTANT_RELEASE_URL": srv.url}
    cmd = f'curl -fsSL "{srv.url}/latest/download/get.sh" | bash -s -- --port 80'

    def ctty():
        import fcntl
        import termios
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    p = subprocess.Popen(["bash", "-c", cmd], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=slave, stderr=slave, preexec_fn=ctty, pass_fds=(slave,))
    os.close(slave)
    out, answered, deadline = b"", False, time.time() + 120
    while time.time() < deadline:
        r, _, _ = select.select([master], [], [], 0.5)
        if r:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if not answered and b"harness [" in out:
                os.write(master, b"mycli -p {prompt}\n")
                answered = True
            if answered is True and b"confinement [closed]: " in out:
                os.write(master, b"\n")              # the default: closed (L5-2b question)
                answered = "both"
        elif p.poll() is not None:
            break
    p.wait(timeout=30)
    os.close(master)
    text = out.decode(errors="replace")
    assert "Which agent CLI should run konstant's phases?" in text, text
    assert "harness: mycli -p {prompt}" in text, text
    assert "--harness mycli -p {prompt} --port 80" in text, text
    assert "open gives phases your" in text and answered == "both", text


def test_confinement_is_passed_on_and_checked(srv, cwd, tmp_path):
    """--confinement reaches install.sh; a bad value stops before anything is written."""
    path = farm(tmp_path, drop=("python", "claude", "codex", "gemini", "dsh"),
                add={"codex": "echo codex-cli 1"})
    e = dict(os.environ, PATH=path, PYTHON=sys.executable, KONSTANT_RELEASE_URL=srv.url)
    res = subprocess.run(["sh", str(GET), "--confinement", "open", "--port", "80"], cwd=cwd,
                         env=e, text=True, capture_output=True, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    assert "running ./install.sh --yes --harness codex --confinement open --port 80" in \
        res.stdout, res.stdout + res.stderr
    bad = subprocess.run(["sh", str(GET), "--confinement", "ajar"], cwd=cwd, env=e, text=True,
                         capture_output=True, stdin=subprocess.DEVNULL)
    assert bad.returncode == 2 and "--confinement must be closed or open" in bad.stderr


@pytest.mark.skipif(os.environ.get("KONSTANT_SKIP_INSTALL_TESTS") == "1",
                    reason="KONSTANT_SKIP_INSTALL_TESTS=1 (needs pip network or cache)")
def test_one_liner_installs_a_working_workspace(srv, cwd):
    fake = f"{sys.executable} {cwd}/myproj/tests/fixtures/fake_harness.py {{prompt_file}}"
    res = oneliner(srv, cwd, "--dir", "myproj", "--harness", fake, "--port", str(free_port()))
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-3000:]
    ws = cwd / "myproj"
    assert f"konstant {V} is installed in {ws}" in res.stdout
    assert f"konstant is ready in {ws}" in res.stdout and f"cd {ws}" in res.stdout
    assert [p.name for p in cwd.iterdir()] == ["myproj"] and not (ws / ".konstant-get").exists()
    ver = subprocess.run([str(ws / "bin" / "konstant"), "version"], capture_output=True,
                         text=True, env={k: v for k, v in os.environ.items()
                                         if k != "KONSTANT_HOME"})
    assert ver.returncode == 0 and V in ver.stdout
    assert "fake_harness.py" in (ws / "konstant.toml").read_text()
    agents = (ws / "AGENTS.md").read_text()
    assert "## Operating konstant (any agent, any model)" in agents
    assert "bin/konstant job close <id> --evidence <file>" in agents
