#!/usr/bin/env bash
# konstant installer: turns THIS unpacked folder into a konstant workspace (DESIGN §10).
#
#   ./install.sh [--port N] [--harness "<cmd>"] [--wheels DIR] [--from OLD_FOLDER] [--yes]
#
# Idempotent: a re-run keeps konstant.toml, the tokens and the board data, re-installs the package
# into .venv, migrates the DB and regenerates the agent surfaces. Nothing is written outside this
# folder. Uninstall: `bin/konstant board stop && rm -rf <this folder>`.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: ./install.sh [--port N] [--harness "<cmd>"] [--wheels DIR] [--from OLD_FOLDER] [--yes]

  --port N        board port for a NEW konstant.toml (default: first free port from 8470)
  --harness H     for a NEW konstant.toml: an adapter name (claude, codex, gemini, dsh: written as
                  [harness] name) or an argv template for any other CLI, the command adapter
                  (e.g. "mycli -p {prompt}"; written as [harness] command); default: Claude Code,
                  workspace-scoped (docs/HARNESSES.md)
  --wheels DIR    offline install from pre-downloaded wheels (pip --no-index --find-links DIR);
                  make DIR on a machine with network and a current pip (>= 23):
                    python3 -m pip download -d DIR <this folder> setuptools wheel
  --from OLD      upgrade: copy konstant.toml, var/ and projects/ from an older konstant folder
                  (its board must be stopped; its DB is backed up first)
  --yes           do not ask for confirmation
EOF
}

PORT="" HARNESS="" WHEELS="" FROM="" YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    --harness) HARNESS="${2:?--harness needs a value}"; shift 2 ;;
    --wheels) WHEELS="${2:?--wheels needs a value}"; shift 2 ;;
    --from) FROM="${2:?--from needs a value}"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

say() { printf 'install: %s\n' "$*"; }
die() { printf 'install: ERROR: %s\n' "$*" >&2; exit 1; }

HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd -P)
cd "$HERE"

# 1. preconditions --------------------------------------------------------------------------------
[ "$(id -u)" -ne 0 ] || die "do not run as root: install and run konstant as your own user"
case "$HERE" in *[[:space:]]*) die "the folder path contains whitespace: $HERE (move it)";; esac
[ -w "$HERE" ] || die "this folder is not writable: $HERE"
[ -f "$HERE/pyproject.toml" ] && [ -d "$HERE/src/konstant" ] \
  || die "run install.sh from the unpacked konstant folder (pyproject.toml + src/ not found)"
case "$PORT" in ''|*[!0-9]*) [ -z "$PORT" ] || die "--port must be a number";; esac
if [ -n "$PORT" ] && { [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; }; then
  die "--port must be 1024-65535 (got $PORT)"
fi
if [ -n "$WHEELS" ]; then [ -d "$WHEELS" ] || die "--wheels: no such directory: $WHEELS"; fi
[ "$HARNESS" != command ] \
  || die "--harness command: pass the command template itself, e.g. --harness \"mycli -p {prompt}\" (docs/HARNESSES.md)"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || die "$PY not found: install Python >= 3.10 (e.g. sudo apt install python3)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "konstant needs Python >= 3.10; $PY is $("$PY" -c 'import sys; print(sys.version.split()[0])')"
PYVER=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')

if [ -n "$FROM" ]; then
  FROM=$(cd "$FROM" 2>/dev/null && pwd -P) || die "--from: no such folder"
  [ "$FROM" != "$HERE" ] || die "--from names this folder; unpack the new release elsewhere"
  [ -f "$FROM/konstant.toml" ] || [ -f "$FROM/var/board.db" ] \
    || die "--from $FROM is not a konstant workspace (no konstant.toml or var/board.db)"
  [ ! -e "$HERE/var/board.db" ] || die "this folder already has a board (var/board.db); --from only fills a fresh folder"
  if [ -f "$FROM/var/board.pid" ] && kill -0 "$(cat "$FROM/var/board.pid")" 2>/dev/null; then
    die "the old board is running: stop it first ($FROM/bin/konstant board stop)"
  fi
fi

if [ "$YES" -ne 1 ]; then
  if [ -t 0 ]; then
    printf 'Install konstant into %s%s? [y/N] ' "$HERE" "${FROM:+ (upgrade from $FROM)}"
    read -r answer
    case "$answer" in y|Y|yes|YES) ;; *) say "cancelled"; exit 1 ;; esac
  else
    die "not a terminal: pass --yes to install without asking"
  fi
fi

# 2. virtual environment + package ----------------------------------------------------------------
venv_ok() { [ -x "$HERE/.venv/bin/python" ] && "$HERE/.venv/bin/python" -m pip --version >/dev/null 2>&1; }
if venv_ok; then
  say "reusing .venv"
else
  rm -rf "$HERE/.venv"
  if "$PY" -c 'import ensurepip' >/dev/null 2>&1 && "$PY" -m venv "$HERE/.venv"; then
    say "created .venv ($PY -m venv)"
  else
    rm -rf "$HERE/.venv"
    if command -v virtualenv >/dev/null 2>&1; then
      virtualenv -q -p "$PY" "$HERE/.venv" || die "virtualenv failed"
      say "created .venv (virtualenv; $PY has no ensurepip)"
    elif "$PY" -m virtualenv --version >/dev/null 2>&1; then
      "$PY" -m virtualenv -q "$HERE/.venv" || die "virtualenv failed"
      say "created .venv ($PY -m virtualenv; $PY has no ensurepip)"
    else
      die "$PY cannot create a virtual environment: its ensurepip module is missing.
  Fix (Debian/Ubuntu):  sudo apt install python${PYVER}-venv     (or: sudo apt install python3-venv)
  Fix (Fedora/RHEL):    sudo dnf install python3                  (venv is included)
  Fix (Arch):           sudo pacman -S python                     (venv is included)
  Or install virtualenv (e.g. pipx install virtualenv) and re-run ./install.sh"
    fi
  fi
fi
venv_ok || die ".venv has no working pip; remove .venv and re-run"

PIP=("$HERE/.venv/bin/python" -m pip install --quiet --disable-pip-version-check)
RECIPE="make the wheel dir on a machine with network and a current pip (>= 23): python3 -m pip download -d DIR <the konstant folder> setuptools wheel"
if [ -n "$WHEELS" ]; then
  # konstant itself is built from source here, so the build backend must be at hand offline:
  # the venv's own setuptools when it can build a wheel alone (>= 70.1, or >= 61 with `wheel`),
  # else setuptools + wheel from DIR (a `pip download` of the folder alone does not include them)
  backend_ok() {
    "$HERE/.venv/bin/python" - <<'PYEOF' 2>/dev/null
import importlib.util, sys
try:
    import setuptools
except ImportError:
    sys.exit(1)
v = tuple(int(x) for x in setuptools.__version__.split(".")[:2] if x.isdigit())
sys.exit(0 if v >= (70, 1) or (v >= (61, 0) and importlib.util.find_spec("wheel")) else 1)
PYEOF
  }
  if ! backend_ok; then
    "${PIP[@]}" --no-index --find-links "$WHEELS" "setuptools>=70.1" >/dev/null 2>&1 \
      || "${PIP[@]}" --no-index --find-links "$WHEELS" "setuptools>=61" wheel >/dev/null 2>&1 \
      || die "no build backend offline: the venv has no usable setuptools and $WHEELS has none; $RECIPE"
  fi
  "${PIP[@]}" --no-index --find-links "$WHEELS" --no-build-isolation "$HERE" \
    || die "pip install from $WHEELS failed; $RECIPE"
else
  "${PIP[@]}" "$HERE" || die "pip install failed (no network? use --wheels DIR)"
fi
VER=$("$HERE/.venv/bin/python" -c 'import konstant; print(konstant.__version__)')
say "installed konstant $VER into .venv"

# 3. the wrapper (bin/konstant) -------------------------------------------------------------------
mkdir -p "$HERE/bin"
cat > "$HERE/bin/konstant.tmp" <<'EOF'
#!/bin/sh
# konstant wrapper (written by install.sh): runs konstant from this folder's venv with this folder
# as the workspace (KONSTANT_HOME), unless KONSTANT_HOME is already set.
HERE=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
: "${KONSTANT_HOME:=$HERE}"
export KONSTANT_HOME
exec "$HERE/.venv/bin/python" -m konstant "$@"
EOF
chmod 0755 "$HERE/bin/konstant.tmp"
mv -f "$HERE/bin/konstant.tmp" "$HERE/bin/konstant"
K() { KONSTANT_HOME="$HERE" "$HERE/bin/konstant" "$@"; }

# 4. upgrade: bring the old workspace's data over (before anything is created here) -----------------
if [ -n "$FROM" ]; then
  if [ -f "$FROM/var/board.db" ]; then
    KONSTANT_HOME="$FROM" "$HERE/.venv/bin/python" -m konstant board backup \
      || die "backup of $FROM/var/board.db failed; nothing was copied"
  fi
  for item in konstant.toml var projects; do
    if [ -e "$FROM/$item" ]; then cp -a "$FROM/$item" "$HERE/" && say "copied $item from $FROM"; fi
  done
fi

# 5. folders + konstant.toml (only when absent) ---------------------------------------------------
mkdir -p "$HERE/var/logs" "$HERE/var/runs" "$HERE/var/backups" "$HERE/projects"
if [ -f "$HERE/konstant.toml" ]; then
  say "kept existing konstant.toml"
  [ -z "$PORT$HARNESS" ] || say "note: --port/--harness only apply to a NEW konstant.toml; edit it instead"
else
  KONSTANT_PORT="$PORT" KONSTANT_HARNESS="$HARNESS" "$HERE/.venv/bin/python" - "$HERE/konstant.toml" <<'EOF'
import json, os, socket, sys

def free(port):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False

port = os.environ.get("KONSTANT_PORT") or next(str(p) for p in range(8470, 8570) if free(p))
harness = os.environ.get("KONSTANT_HARNESS", "")
lines = ["# konstant workspace configuration; every key and its default: docs/DESIGN.md section 13.",
         "# Run `bin/konstant agents sync` after changing [permissions].", "",
         "[board]", f"port = {port}", ""]
if harness in ("claude", "codex", "gemini", "dsh"):
    lines += ["[harness]", f"name = {json.dumps(harness)}",
              "# model = \"\"   # the harness's own model key; per type: [harness.types.<type>]",
              "# a local OpenAI-compatible endpoint (codex, dsh): [harness.endpoint] base_url",
              "# docs/HARNESSES.md", ""]
elif harness:
    lines += ["[harness]", f"command = {json.dumps(harness)}", ""]
else:
    lines += ["[harness]",
              "# name = \"claude\"   # claude | codex | gemini | dsh | command (docs/HARNESSES.md)",
              "# default: Claude Code, headless, workspace-scoped (see docs/CONCEPTS.md)",
              '# command = "claude -p --permission-mode dontAsk --setting-sources project,local '
              '--strict-mcp-config --add-dir {workspace} --settings '
              '{workspace}/.claude/settings.json {prompt}"', ""]
lines += ["[permissions]",
          "# extra Claude Code rules for headless phases, e.g. your test runner:",
          '# allow = ["Bash(pytest *)", "Bash(python -m pytest *)", "Bash(npm test *)"]', ""]
path = sys.argv[1]
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
with os.fdopen(fd, "w") as fh:
    fh.write("\n".join(lines))
print(f"install: wrote konstant.toml (board port {port})")
EOF
fi

# 6. board DB + tokens, generated agent surfaces, doctor ------------------------------------------
K board init
K agents sync | tail -n 1
say "running doctor"
if K doctor; then
  cat <<EOF

konstant $VER is installed in $HERE

Next steps:
  cd $HERE
  bin/konstant board start            # the job board, $(KONSTANT_HOME="$HERE" "$HERE/.venv/bin/python" -c 'from konstant import config; print(config.load().base_url)')
  bin/konstant project add demo --init-git
  claude                              # or your agent CLI: open it in this folder
  bin/konstant dsh web                # with dsh: its web UI with konstant's gate (docs/DSH.md)
See docs/QUICKSTART.md.
EOF
else
  die "doctor reported a FAIL (above); fix it and re-run ./install.sh"
fi
