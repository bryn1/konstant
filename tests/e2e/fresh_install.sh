#!/usr/bin/env bash
# Fresh-install end-to-end test (DESIGN §14): build the release tarball, unpack it into a new
# temp dir, install, and drive a whole job lifecycle against the installed workspace.
#
#   bash tests/e2e/fresh_install.sh [TARBALL]
#   bash tests/e2e/fresh_install.sh --one-line [DIST_DIR]     (= tests/e2e/one_line.sh)
#
# Without TARBALL the current source tree is archived (`release build --worktree`, scanned with
# release/denylist.local.txt when present). --one-line installs through the documented one-liner
# instead of unpack + install.sh: the release assets (DIST_DIR, or a fresh build) are served by a
# local http.server in the GitHub releases layout and `curl -fsSL <url>/latest/download/get.sh |
# bash -s -- --dir ... --harness ...` runs with KONSTANT_RELEASE_URL pointing at it; the job
# lifecycle steps after it are the same. The fake harness (tests/fixtures/fake_harness.py,
# from the unpacked tarball) stands in for a model, so no model is called. The board runs on a
# free loopback port and is stopped at the end; the temp dir is removed. Exit 0 = every step
# passed; the transcript on stdout is the release evidence.
set -euo pipefail

REPO=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd -P)
PY=${PYTHON:-python3}
BUILD_PY="$REPO/.venv/bin/python"
[ -x "$BUILD_PY" ] || BUILD_PY="$PY"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/konstant-e2e.XXXXXX")
WS=""
STEP=0
ONE_LINE=0
SERVER_PID=""
if [ "${1:-}" = "--one-line" ]; then ONE_LINE=1; shift; fi

cleanup() {
  local rc=$?
  [ -z "$SERVER_PID" ] || kill "$SERVER_PID" 2>/dev/null || true
  if [ -n "$WS" ] && [ -x "$WS/bin/konstant" ] && [ -f "$WS/var/board.pid" ]; then
    "$WS/bin/konstant" board stop >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
  [ $rc -eq 0 ] || echo "E2E: FAILED (exit $rc)"
  exit $rc
}
trap cleanup EXIT

step() { STEP=$((STEP + 1)); printf '\n== %d. %s\n' "$STEP" "$*"; }
fail() { echo "E2E FAIL: $*"; exit 1; }
# run CMD...: print it, run it, show its output, keep its rc in RC and output in OUT
run() {
  printf '$ %s\n' "$*"
  set +e
  OUT=$("$@" 2>&1)
  RC=$?
  set -e
  [ -z "$OUT" ] || printf '%s\n' "$OUT" | sed 's/^/  | /'
  printf '  -> exit %d\n' "$RC"
}
want_rc() { [ "$RC" -eq "$1" ] || fail "expected exit $1, got $RC"; }
want_out() { printf '%s' "$OUT" | grep -qE -- "$1" || fail "output lacks /$1/"; }
json_field() { "$WS/.venv/bin/python" -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$OUT" "$1"; }

export GIT_AUTHOR_NAME=e2e GIT_AUTHOR_EMAIL=e2e@example.com
export GIT_COMMITTER_NAME=e2e GIT_COMMITTER_EMAIL=e2e@example.com
unset KONSTANT_HOME KONSTANT_IN_TASK KONSTANT_RUN KONSTANT_ROLE KONSTANT_CATALOG

# --- release tarball -----------------------------------------------------------------------------
step "release tarball"
VER=$(PYTHONPATH="$REPO/src" "$BUILD_PY" -c 'import konstant; print(konstant.__version__)')
if [ $# -ge 1 ] && [ "$ONE_LINE" -eq 1 ]; then
  DIST=$(readlink -f "$1")
  TARBALL="$DIST/konstant-$VER.tar.gz"
  echo "using the release assets in $DIST"
elif [ $# -ge 1 ]; then
  TARBALL=$(readlink -f "$1")
  echo "using $TARBALL"
else
  DENY=(--no-denylist)
  [ -f "$REPO/release/denylist.local.txt" ] && DENY=(--denylist "$REPO/release/denylist.local.txt")
  run env PYTHONPATH="$REPO/src" "$BUILD_PY" -m konstant.release build --version "$VER" \
      --worktree --root "$REPO" --dist "$WORK/dist" "${DENY[@]}"
  want_rc 0; want_out 'RESULT: CLEAN'
  TARBALL="$WORK/dist/konstant-$VER.tar.gz"
  DIST="$WORK/dist"
fi
[ -f "$TARBALL" ] || fail "no tarball at $TARBALL"
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')

if [ "$ONE_LINE" -eq 1 ]; then
# --- the one-liner against a local release server ---------------------------------------------------
step "serve the release assets locally (GitHub releases layout)"
for f in get.sh VERSION "konstant-$VER.tar.gz" "konstant-$VER.tar.gz.sha256"; do
  [ -f "$DIST/$f" ] || fail "release asset $f missing in $DIST"
done
SRV="$WORK/srv"
mkdir -p "$SRV/latest/download" "$SRV/download/v$VER"
cp "$DIST/get.sh" "$DIST/VERSION" "$SRV/latest/download/"
cp "$DIST/get.sh" "$DIST/konstant-$VER.tar.gz" "$DIST/konstant-$VER.tar.gz.sha256" "$SRV/download/v$VER/"
SPORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
"$PY" -m http.server --bind 127.0.0.1 --directory "$SRV" "$SPORT" >"$WORK/http.log" 2>&1 &
SERVER_PID=$!
export KONSTANT_RELEASE_URL="http://127.0.0.1:$SPORT"
for _ in $(seq 50); do curl -fsS -o /dev/null "$KONSTANT_RELEASE_URL/latest/download/VERSION" 2>/dev/null && break; sleep 0.1; done
run curl -fsS "$KONSTANT_RELEASE_URL/latest/download/VERSION"
want_rc 0; want_out "^$VER\$"

mkdir -p "$WORK/u"
cd "$WORK/u"
WS="$WORK/u/ws"
FAKE="$PY $WS/tests/fixtures/fake_harness.py {prompt_file}"
step "one-liner: curl -fsSL \$KONSTANT_RELEASE_URL/latest/download/get.sh | bash -s -- --dir ws --harness <fake> --port $PORT"
printf '$ curl -fsSL %s/latest/download/get.sh | bash -s -- --dir ws --harness "%s" --port %s\n' \
  "$KONSTANT_RELEASE_URL" "$FAKE" "$PORT"
set +e
OUT=$({ curl -fsSL "$KONSTANT_RELEASE_URL/latest/download/get.sh" | bash -s -- --dir ws --harness "$FAKE" --port "$PORT"; } 2>&1)
RC=$?
set -e
printf '%s\n' "$OUT" | sed 's/^/  | /'
printf '  -> exit %d\n' "$RC"
want_rc 0; want_out "sha256 OK"; want_out "konstant $VER is installed in $WS"; want_out "konstant is ready in $WS"
for f in docs/INVENTORY.md docs/PLAN.md docs/OPEN-QUESTIONS.md release/denylist.local.txt .konstant-get; do
  [ ! -e "$WS/$f" ] || fail "$f must not be in the installed folder"
done
[ "$(ls -A "$WORK/u")" = ws ] || fail "the one-liner wrote outside its folder: $(ls -A "$WORK/u")"
grep -q '^## Operating konstant' "$WS/AGENTS.md" || fail "AGENTS.md lacks the operating section"
echo "installed by the one-liner into $WS (maintainer-only files absent, nothing else written)"
cd "$WS"
else
step "unpack into a new folder"
mkdir -p "$WORK/u"
run tar -xzf "$TARBALL" -C "$WORK/u"
want_rc 0
WS="$WORK/u/konstant-$VER"
[ -x "$WS/install.sh" ] || fail "install.sh missing or not executable in the tarball"
for f in docs/INVENTORY.md docs/PLAN.md docs/OPEN-QUESTIONS.md release/denylist.local.txt; do
  [ ! -e "$WS/$f" ] || fail "$f must not ship"
done
echo "unpacked to $WS (maintainer-only files absent)"

# --- install -------------------------------------------------------------------------------------
FAKE="$PY $WS/tests/fixtures/fake_harness.py {prompt_file}"
step "install.sh --yes --port $PORT --harness <fake harness>"
cd "$WS"
run ./install.sh --yes --port "$PORT" --harness "$FAKE"
want_rc 0; want_out "konstant $VER is installed"
fi
K="$WS/bin/konstant"

step "doctor"
run "$K" doctor
want_rc 0; want_out ' 0 FAIL'
for c in python dependencies config var database tokens agents harness; do
  printf '%s\n' "$OUT" | grep -qE "^PASS +$c " || fail "doctor check $c did not PASS"
done

step "board up"
run "$K" board start
want_rc 0; want_out 'board started'
run "$K" board status
want_rc 0; want_out 'board running'

step "project with a git repository"
run "$K" project add demo --init-git
want_rc 0; want_out 'PROJECT=demo'
run git -C "$WS/projects/demo" commit -q --allow-empty -m init
want_rc 0

# --- job lifecycle: close -> verify PASS -> verified ---------------------------------------------
step "job: add, claim, close with evidence, verify PASS"
printf 'Write the project README.\n\nDoD: README.md exists in the project\nPROBE: test -e projects/demo/README.md => ^ok$\n' > "$WORK/brief1.md"
run "$K" --json job add "T1: write README" --project demo --type docs --brief "$WORK/brief1.md"
want_rc 0
J1=$(json_field id)
run "$K" job claim "$J1"
want_rc 0
echo "# demo" > "$WS/projects/demo/README.md"
printf 'VERIFY_CMD: test -f README.md\nVERIFY_EXIT=0\nDOCS: README.md written\n' > "$WORK/ev1.md"
run "$K" job close "$J1" --evidence "$WORK/ev1.md"
want_rc 0
run "$K" --json job show "$J1"
[ "$(json_field status)" = completed_unverified ] || fail "job $J1 is not completed_unverified"
echo "job $J1 status: completed_unverified"
run "$K" verify "$J1"
want_rc 0; want_out 'verdict=PASS'
run "$K" --json job show "$J1"
[ "$(json_field status)" = verified ] || fail "job $J1 is not verified"
echo "job $J1 status: verified"

# --- the FAIL path: a probe that does not hold -> verify FAIL -> queued ----------------------------
step "job: closed but its probe fails -> verify FAIL -> queued"
printf 'Write the changelog.\n\nDoD: CHANGELOG.md exists in the project\nPROBE: test -e projects/demo/CHANGELOG.md => ^ok$\n' > "$WORK/brief2.md"
run "$K" --json job add "T2: write CHANGELOG" --project demo --type docs --brief "$WORK/brief2.md"
want_rc 0
J2=$(json_field id)
run "$K" job claim "$J2"
want_rc 0
run "$K" job close "$J2" --evidence "$WORK/ev1.md"
want_rc 0
run "$K" verify "$J2"
want_rc 3; want_out 'verdict=FAIL'
run "$K" --json job show "$J2"
[ "$(json_field status)" = queued ] || fail "job $J2 is not queued after FAIL"
echo "job $J2 status: queued"

# --- a typed task through the phase runner (fake harness) + the DoD check -------------------------
step "task run with the fake harness, then task check"
run "$K" task run "[type:code] add greet()" --project demo
want_rc 0
RUN=$(ls -1d "$WS"/var/runs/*/ | tail -n 1)
run "$K" --json task check "$RUN"
want_rc 0; want_out '"result": "MET"'
[ -f "$WS/projects/demo/greet.py" ] || fail "the run did not produce projects/demo/greet.py"

# --- offline install: a wheel dir made by `pip download`, pip's network blocked (REVIEW F-17) -----
step "offline install from a pip-download wheel dir, network blocked for pip"
mkdir -p "$WORK/off"
run tar -xzf "$TARBALL" -C "$WORK/off"
want_rc 0
OFF="$WORK/off/konstant-$VER"
# a current pip (the installed workspace's): an old distribution pip saves nothing useful here
run "$WS/.venv/bin/python" -m pip download -q -d "$WORK/wheels" "$OFF"
if [ "$RC" -ne 0 ]; then
  echo "SKIP: no package index reachable to make the wheel dir (the offline leg needs one first)"
else
  NW=$(ls "$WORK/wheels" | wc -l)
  [ "$NW" -gt 0 ] || fail "pip download saved no wheel"
  echo "wheel dir: $NW files (the folder's dependencies only, no setuptools)"
  DEAD=http://127.0.0.1:9
  run env PIP_INDEX_URL=$DEAD http_proxy=$DEAD https_proxy=$DEAD HTTP_PROXY=$DEAD HTTPS_PROXY=$DEAD \
      "$OFF/install.sh" --yes --port "$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')" \
      --harness "$FAKE" --wheels "$WORK/wheels"
  want_rc 0; want_out "konstant $VER is installed"
fi
rm -rf "$WORK/off" "$WORK/wheels"

# --- teardown --------------------------------------------------------------------------------------
step "board stop, no process left, folder removed"
PID=$(cat "$WS/var/board.pid")
run "$K" board stop
want_rc 0
if kill -0 "$PID" 2>/dev/null; then fail "board pid $PID still alive"; fi
LEFT=$(pgrep -f -- "$WS" || true)
[ -z "$LEFT" ] || fail "processes still running from $WS: $LEFT"
echo "no process from $WS is running"
cd /
rm -rf "$WORK/u"
[ ! -e "$WS" ] || fail "$WS still exists"
echo "removed $WS"
WS=""
printf '\nE2E: PASS (%d steps)\n' "$STEP"
