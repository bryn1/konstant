#!/usr/bin/env bash
# The proof of level 5 (docs/LEVEL5.md section 7): ONE command that builds the release tarball,
# installs it fresh, and runs the dark factory on the sample project examples/greeter through the
# orchestrator chat, offline: no model, no network, no real GitHub.
#
#   bash tests/e2e/factory.sh [TARBALL]          (KEEP=1 keeps the temp dir)
#
# Every phase runs through the real dsh adapter with the stub dsh (tests/fixtures/stub_dsh.py)
# handing it to the fake harness (tests/fixtures/fake_harness.py), so every phase is in konstant's
# jail. The orchestrator chat is a `konstant dsh headless` session on the stub dsh whose scripted
# actions play the konstant-gate plugin (`chat turn` on each owner message) and the orchestrator
# model (the goal proposal). The github target ships to a local bare repository through the `gh`
# stand-in (tests/fixtures/fake_gh.py). stdin is /dev/null, HOME is a private temp dir, and
# owner.token is unreadable for every factory run (the owner's own steps open it briefly).
#
# Legs (each asserts artifacts: board JSON, git refs, the stand-in's logs, the chat inbox and the
# session's turns, phase logs; tests/e2e/factory_check.py):
#   P0 chat intake      request -> INTAKE block -> proposal -> "yes" -> goal filed from the chat
#   P1 honest           goal -> jobs -> holdouts sealed -> work -> verified -> shipped -> GOAL_DONE
#                       reported in the session's next turn
#   P2 cheating         overfit producer: holdouts fail, never shipped, BLOCKED after 3 attempts
#   P3 reader           store / other tokens / memory denied, judged honestly; jail = false: exit 2
#   P4 post-ship break  rollback by revert PR, follow-up shipped, max_rollbacks -> BLOCKED
#   P5 budget           max_attempts BLOCKED; max_task_runs BUDGET_STOP, goal paused; clean stop
#   P6 github           PRs with --match-head-commit, no force-push; secret in diff and a workflow
#                       change -> DECISION, nothing pushed
#   + the owner-authored holdout check, and every escalation shown once in the chat
# Prints `E2E-FACTORY: PASS (N legs)` only when every leg met its rows.
set -euo pipefail

# a SCRUBBED environment, as the other e2e scripts (REVIEW L5-R1 H-05)
if [ -z "${KONSTANT_E2E_SCRUBBED:-}" ]; then
  keep=(KONSTANT_E2E_SCRUBBED=1 "HOME=$HOME" "PATH=$PATH" "LANG=${LANG:-C.UTF-8}")
  for v in LC_ALL TERM TMPDIR LEFTHOOK PYTHON KEEP KONSTANT_E2E_REQUIRE_JAIL; do
    [ -z "${!v:-}" ] || keep+=("$v=${!v}")
  done
  exec env -i "${keep[@]}" bash "$(readlink -f "$0")" "$@" </dev/null
fi
exec </dev/null
if env | cut -d= -f1 | grep -qiE 'secret|token|password|api_?key'; then
  echo "E2E-FACTORY FAIL: a secret-shaped variable survived the scrub"; exit 1
fi

REPO=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd -P)
PY=${PYTHON:-python3}
BUILD_PY="$REPO/.venv/bin/python"
[ -x "$BUILD_PY" ] || BUILD_PY="$PY"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/konstant-factory-e2e.XXXXXX")
# a private HOME after the install: nothing of the caller's (agent homes, git hooks, git config) is
# loaded or written by the legs (install.sh keeps the caller's HOME: its Python may need a user-site
# virtualenv; it writes nothing outside the folder)
CALLER_HOME=$HOME
export HOME="$WORK/home"
mkdir -p "$HOME" "$WORK/turns" "$WORK/src" "$WORK/bin"
WS=""
STEP=0
LEGS=0
T0=$(date +%s)
S=owner-chat-1

cleanup() {
  local rc=$?
  if [ -n "$WS" ] && [ -x "$WS/bin/konstant" ]; then
    chmod 600 "$WS/var/secrets/owner.token" 2>/dev/null || true
    [ ! -f "$WS/var/factory/factory.pid" ] || "$WS/bin/konstant" factory stop --now --wait 30 >/dev/null 2>&1 || true
    [ ! -f "$WS/var/board.pid" ] || "$WS/bin/konstant" board stop >/dev/null 2>&1 || true
  fi
  if [ "${KEEP:-0}" = 1 ]; then echo "kept $WORK"; else rm -rf "$WORK"; fi
  [ $rc -eq 0 ] || echo "E2E-FACTORY: FAILED (exit $rc)"
  exit $rc
}
trap cleanup EXIT

step() { STEP=$((STEP + 1)); printf '\n== %d. %s (+%ss)\n' "$STEP" "$*" "$(( $(date +%s) - T0 ))"; }
leg() { LEGS=$((LEGS + 1)); printf '\n######## %s (+%ss)\n' "$*" "$(( $(date +%s) - T0 ))"; }
fail() { echo "E2E-FACTORY FAIL: $*"; exit 1; }
run() {
  printf '$ %s\n' "$*"
  set +e; OUT=$("$@" 2>&1); RC=$?; set -e
  [ -z "$OUT" ] || printf '%s\n' "$OUT" | tail -n 40 | sed 's/^/  | /'
  printf '  -> exit %d\n' "$RC"
}
want_rc() { [ "$RC" -eq "$1" ] || fail "expected exit $1, got $RC"; }
want_out() { printf '%s' "$OUT" | grep -qE -- "$1" || fail "output lacks /$1/"; }
check() { "$VPY" -I "$CHECK" "$@" || fail "leg check $1 failed"; }

export GIT_AUTHOR_NAME=e2e GIT_AUTHOR_EMAIL=e2e@example.com
export GIT_COMMITTER_NAME=e2e GIT_COMMITTER_EMAIL=e2e@example.com
unset KONSTANT_HOME KONSTANT_IN_TASK KONSTANT_RUN KONSTANT_ROLE KONSTANT_CATALOG

# --- release tarball, fresh install ------------------------------------------------------------
step "release tarball"
VER=$(PYTHONPATH="$REPO/src" "$BUILD_PY" -c 'import konstant; print(konstant.__version__)')
if [ $# -ge 1 ]; then
  TARBALL=$(readlink -f "$1"); echo "using $TARBALL"
else
  DENY=(--no-denylist)
  [ -f "$REPO/release/denylist.local.txt" ] && DENY=(--denylist "$REPO/release/denylist.local.txt")
  run env PYTHONPATH="$REPO/src" "$BUILD_PY" -m konstant.release build --version "$VER" \
      --worktree --root "$REPO" --dist "$WORK/dist" "${DENY[@]}"
  want_rc 0; want_out 'RESULT: CLEAN'
  TARBALL="$WORK/dist/konstant-$VER.tar.gz"
fi
[ -f "$TARBALL" ] || fail "no tarball at $TARBALL"

step "unpack, put the stub dsh first on PATH, install.sh --harness dsh"
mkdir -p "$WORK/u"
run tar -xzf "$TARBALL" -C "$WORK/u"
want_rc 0
WS="$WORK/u/konstant-$VER"
K="$WS/bin/konstant"
VPY="$WS/.venv/bin/python"
CHECK="$WS/tests/e2e/factory_check.py"
for f in examples/greeter/greeter.py examples/greeter/goal.toml tests/e2e/factory_check.py \
         tests/fixtures/stub_dsh.py tests/fixtures/fake_gh.py; do
  [ -f "$WS/$f" ] || fail "$f is not in the release tarball"
done
# the stub dsh runs under the workspace's own Python (the fake harness calls `python -m konstant`)
printf '#!/bin/sh\nexec %s %s "$@"\n' "$VPY" "$WS/tests/fixtures/stub_dsh.py" > "$WORK/bin/dsh"
chmod 755 "$WORK/bin/dsh"
export PATH="$WORK/bin:$PATH"
PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
cd "$WS"
run env HOME="$CALLER_HOME" ./install.sh --yes --port "$PORT" --harness dsh
want_rc 0; want_out "konstant $VER is installed"
export KONSTANT_E2E_WS="$WS" KONSTANT_E2E_SESSION="$S"
# the stand-ins are scripted through FAKE_*/STUB_*; a closed phase keeps only the named prefixes
export KONSTANT_ENV_PASSTHROUGH='FAKE_*,STUB_*' STUB_DSH_THEN=fake FAKE_HARNESS_MODULE=greeter

if ! "$VPY" -c 'import sys; from konstant import jail; sys.exit(0 if jail.available() else 1)'; then
  if [ "${KONSTANT_E2E_REQUIRE_JAIL:-0}" = 1 ]; then fail "bubblewrap cannot run here"; fi
  echo "E2E-FACTORY: SKIPPED (bubblewrap cannot create a jail here: holdouts, the factory and ship need it)"
  exit 0
fi

step "workspace configuration: the owner's setup (chat intake, chat notifications)"
cat >> "$WS/konstant.toml" <<'EOF'

[factory]
tick_s = 1
goal_roles = ["owner", "orchestrator"]

[notify]
kind = "chat"
EOF
cp "$WS/konstant.toml" "$WORK/konstant.base.toml"
# config GATE SHIP: konstant.toml = the base + [gate] + [ship] lines; the board restarts
config() {
  { cat "$WORK/konstant.base.toml"
    printf '\n[gate]\nmax_cycles = 1\nmax_resumes = 0\n%s\n' "$1"
    printf '\n[ship]\n%s\n' "$2"; } > "$WS/konstant.toml"
  if [ -f "$WS/var/board.pid" ]; then "$K" board stop >/dev/null; fi
  "$K" agents sync >/dev/null || fail "agents sync"     # [notify] chat renders the session patch
  "$K" board start >/dev/null || fail "the board did not start"
}
config "" ""
run "$K" doctor
want_rc 0; want_out ' 0 FAIL'
run "$K" board status
want_rc 0; want_out 'board running'

step "the sample project, once per leg: examples/greeter (without its goal file), on branch main"
mkproject() {
  local p="$WS/projects/$1"
  cp -r "$WS/examples/greeter" "$p"
  rm -f "$p/goal.toml"
  git -C "$p" init -q -b main && git -C "$p" add -A && git -C "$p" commit -qm "greeter: the sample" \
    || fail "git init of $1"
  "$K" project add "$1" >/dev/null || fail "project add $1"
}
for p in greeter overfit reader breaks attempts runs secret workflow ownerset; do mkproject "$p"; done
run "$K" project list
want_rc 0
base() { git -C "$WS/projects/$1" rev-parse main; }

# github PROJECT: a bare repository standing in for GitHub + the gh stand-in on a pinned path;
# [ship] remote / gh are operator keys of konstant.toml, so each github leg points them at its repo
github() {
  REMOTE="$WORK/github/$1.git"; GHLOG="$WORK/gh-$1.log"
  mkdir -p "$WORK/github"
  git clone -q --bare "$WS/projects/$1" "$REMOTE"
  GH=$("$VPY" -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from tests.fixtures import fake_gh; print(fake_gh.install(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))' \
       "$WS" "$WORK/pinned-$1" "$REMOTE" "$GHLOG")
  config "" "remote = \"$REMOTE\"
gh = \"$GH\""
  echo "github stand-in for $1: a bare repository + gh on a pinned path (config: [ship] remote, gh)"
}
GITHUB_GOAL=(--ship 'target = "github"')

# --- the orchestrator chat ----------------------------------------------------------------------
TURN=0
TURNLOGS=""
# turn TEXT [MODEL-COMMAND...]: one owner message in the orchestrator session: the plugin runs
# `chat turn` on it, then the orchestrator model runs its commands (the stub dsh's run: actions)
turn() {
  TURN=$((TURN + 1))
  local msg="$WORK/turns/$TURN.msg" log="$WORK/turns/$TURN.jsonl" acts a
  printf '%s' "$1" > "$msg"; shift
  acts="run:$K chat turn --session $S - < $msg"
  for a in "$@"; do acts="$acts;run:$a"; done
  printf '$ [owner -> orchestrator session %s, turn %d] %s\n' "$S" "$TURN" "$(cat "$msg")"
  set +e
  OUT=$(env -u STUB_DSH_THEN STUB_DSH_LOG="$log" STUB_DSH_ACTIONS="$acts" "$K" dsh headless - < "$msg" 2>&1)
  RC=$?
  set -e
  [ "$RC" -eq 0 ] || { printf '%s\n' "$OUT" | sed 's/^/  | /'; fail "the session turn failed ($RC)"; }
  "$VPY" -I "$CHECK" turn "$log"
  TURNLOG=$log
  TURNLOGS="${TURNLOGS:+$TURNLOGS,}$log"
}
# chat_goal ID PROJECT [spec options...]: the owner asks, the orchestrator proposes, the owner says yes
chat_goal() {
  local id=$1 proj=$2; shift 2
  "$VPY" -I "$CHECK" spec "$id" "$proj" "$@" > "$WORK/src/$id.toml"
  turn "make $proj greet by name, with a CLI and a README" \
       "KONSTANT_CHAT_SESSION=$S $K goal add - --from-chat < $WORK/src/$id.toml"
  REQ_LOG=$TURNLOG
  "$K" --as viewer goal show "$id" --json > "$WORK/src/$id.before-yes.json"
  turn "yes"
  YES_LOG=$TURNLOG
}
status_turn() { turn "how is the factory doing?"; }
OWNER="$WS/var/secrets/owner.token"
owner_open() { chmod 600 "$OWNER"; }
owner_shut() { chmod 000 "$OWNER"; }
# factory GOAL [VAR=value...]: one `factory run GOAL --until-idle`, owner.token unreadable
factory() {
  local g=$1; shift
  owner_shut
  [ ! -r "$OWNER" ] || fail "owner.token is still readable"
  printf '$ %s bin/konstant factory run %s --until-idle   (owner.token mode 000, stdin /dev/null)\n' \
    "$(printf '%s ' "$@" | sed 's/FAKE_HARNESS_EXTRA_TEXT=[^ ]*/FAKE_HARNESS_EXTRA_TEXT=<hidden>/')" "$g"
  set +e
  OUT=$(env "$@" "$K" factory run "$g" --until-idle 2>&1)
  RC=$?
  set -e
  printf '%s\n' "$OUT" | tail -n 25 | sed 's/^/  | /'
  printf '  -> exit %d\n' "$RC"
}
owner_shut

# --- P0 + P1 + P6 (github) ----------------------------------------------------------------------
leg "P0 chat intake: the owner asks in chat, the orchestrator proposes, the owner's yes files it"
github greeter
B_GREETER=$(base greeter)
chat_goal greeter greeter "${GITHUB_GOAL[@]}" --ship 'github_repo = "example-org/greeter"'
check p0 goal=greeter request_log="$REQ_LOG" yes_log="$YES_LOG" spec="$WORK/src/greeter.toml" \
  before_yes="$WORK/src/greeter.before-yes.json"

leg "P1 honest: intake -> jobs -> holdouts sealed -> work -> verified -> shipped -> GOAL_DONE"
factory greeter
want_rc 0
status_turn
check p1 goal=greeter base="$B_GREETER" next_turn="$TURNLOG"
echo "P0 (rest): the goal ran from the chat; its outcome came back in the session's next turn"

leg "P6 github: P1's ships arrived on the remote's main through recorded pull requests"
check p6 goal=greeter log="$GHLOG" remote="$REMOTE" rollbacks=0
P1_LOG=$GHLOG

# --- P2 -----------------------------------------------------------------------------------------
leg "P2 cheating producer: overfits the visible DoD, caught by the holdouts, never shipped"
config "" ""
B=$(base overfit)
chat_goal overfit overfit
factory overfit FAKE_HARNESS_MODE=overfit
want_rc 4
status_turn
check p2 goal=overfit base="$B"

# --- P3 -----------------------------------------------------------------------------------------
leg "P3 reader: the producer looks for the holdouts, other tokens and the memory vault"
chat_goal reader reader
config "jail = false" ""
NRUNS=$(ls "$WS/var/runs" | wc -l)
factory reader FAKE_HARNESS_MODE=peek
want_rc 2; want_out 'confined'
check p3-jail goal=reader runs_before="$NRUNS"
config "" ""
run "$K" memory store "greeter lesson: keep the default greeting" --tag e2e
want_rc 0
factory reader FAKE_HARNESS_MODE=peek
want_rc 0
status_turn
check p3 goal=reader

# --- P4 + P6 rollback ---------------------------------------------------------------------------
leg "P4 post-ship failure: rollback through a revert PR, a follow-up job, then max_rollbacks"
github breaks
chat_goal breaks breaks "${GITHUB_GOAL[@]}" --ship 'github_repo = "example-org/breaks"' \
  --limits 'max_rollbacks = 1'
owner_shut
run "$K" factory run breaks --once
want_rc 0
JOBS=$("$VPY" -c 'import json,sys; print(",".join(str(j["id"]) for j in json.load(sys.stdin) if j.get("goal") == "breaks"))' \
       < <("$K" --as viewer job list --project breaks --json))
B1=${JOBS%%,*}; B2=${JOBS##*,}
[ -n "$B1" ] && [ "$B1" != "$B2" ] || fail "intake did not file two jobs for breaks ($JOBS)"
echo "filed: B1 = job $B1, B2 = job $B2 (the producer breaks both; a follow-up job is honest)"
factory breaks FAKE_HARNESS_MODE=ship-break FAKE_HARNESS_BREAK_JOBS="$B1,$B2"
want_rc 4
status_turn
check p4 goal=breaks b1="$B1" b2="$B2"
check p6 goal=breaks log="$GHLOG" remote="$REMOTE" rollbacks=2

# --- P5 -----------------------------------------------------------------------------------------
leg "P5 budget: max_attempts BLOCKs a job; the optional max_task_runs stops the goal"
config "" ""
chat_goal attempts attempts
factory attempts FAKE_HARNESS_MODE=tester-fails-3x
want_rc 4
chat_goal runs runs --limits 'max_task_runs = 2'
factory runs FAKE_HARNESS_MODE=tester-fails-3x
want_rc 4
status_turn
check p5a goal=attempts
check p5b goal=runs

# --- P6 refusals ----------------------------------------------------------------------------------
leg "P6 github refusals: a secret in the diff and a CI workflow change are owner DECISIONs"
github secret
B=$(base secret)
REFS=$(git -C "$REMOTE" for-each-ref --format='%(refname) %(objectname)')
chat_goal secret secret "${GITHUB_GOAL[@]}" --ship 'github_repo = "example-org/secret"'
# a token-shaped string, built at run time (never in the repository, never printed)
SHAPE="gh""p_$(printf 'Zz9%.0s' $(seq 12))"
export FAKE_HARNESS_EXTRA_TEXT="TOKEN = '$SHAPE'"
factory secret FAKE_HARNESS_MODE=ship-extra FAKE_HARNESS_EXTRA=settings.py
want_rc 4
if printf '%s' "$OUT" | grep -qF "$SHAPE"; then fail "the token-shaped string was printed"; fi
check p6-refused goal=secret log="$GHLOG" remote="$REMOTE" refs_before="$REFS" base="$B" \
  reason="secret scan finding in settings.py" secret=1
unset FAKE_HARNESS_EXTRA_TEXT SHAPE
github workflow
B=$(base workflow)
REFS=$(git -C "$REMOTE" for-each-ref --format='%(refname) %(objectname)')
chat_goal workflow workflow "${GITHUB_GOAL[@]}" --ship 'github_repo = "example-org/workflow"'
factory workflow FAKE_HARNESS_MODE=ship-extra FAKE_HARNESS_EXTRA=.github/workflows/ci.yml \
  FAKE_HARNESS_EXTRA_TEXT=on:push
want_rc 4
status_turn
check p6-refused goal=workflow log="$GHLOG" remote="$REMOTE" refs_before="$REFS" base="$B" \
  reason=".github/workflows/ci.yml"
check p6 goal=greeter log="$P1_LOG" remote="$WORK/github/greeter.git" rollbacks=0

# --- the owner writes the scenarios (author = "owner") -------------------------------------------
leg "owner-authored holdouts: two scenarios per job from the e2e's own dir, sealed by the owner"
config "" ""
chat_goal ownerset ownerset --holdout 'author = "owner"'
factory ownerset
want_rc 4
status_turn
check owner-wait goal=ownerset
mkdir -p "$WORK/owner"
cat > "$WORK/owner/b1-proof.scenario" <<'EOF'
SCENARIO: greet uses the caller's name
KIND: proof
RUN: python3 -c "from greeter import greet; print(greet('Ada'))"
EXPECT_EXIT: 0
EXPECT_OUT: hello Ada
HINT: names other than the default are used verbatim
EOF
cat > "$WORK/owner/b1-regression.scenario" <<'EOF'
SCENARIO: the default greeting still works
KIND: regression
RUN: python3 -c "from greeter import greet; print(greet().upper())"
EXPECT_EXIT: 0
EXPECT_OUT: HELLO WORLD
HINT: calling it without an argument keeps working
EOF
cat > "$WORK/owner/b2-proof.scenario" <<'EOF'
SCENARIO: the command line greets the name it is given
KIND: proof
RUN: python3 greeter.py Ada
EXPECT_EXIT: 0
EXPECT_OUT: hello Ada
HINT: the first argument is the name
EOF
cat > "$WORK/owner/b2-regression.scenario" <<'EOF'
SCENARIO: the library default is unchanged
KIND: regression
RUN: python3 -c "from greeter import greet; print(greet().title())"
EXPECT_EXIT: 0
EXPECT_OUT: Hello World
HINT: importing the module keeps working
EOF
JOBS=$("$VPY" -c 'import json,sys; print(" ".join(str(j["id"]) for j in json.load(sys.stdin) if j.get("goal") == "ownerset"))' \
       < <("$K" --as viewer job list --project ownerset --json))
read -r O1 O2 <<<"$JOBS"
owner_open
run "$K" --as owner holdout add "$O1" --file "$WORK/owner/b1-proof.scenario" --file "$WORK/owner/b1-regression.scenario"
want_rc 0
run "$K" --as owner holdout add "$O2" --file "$WORK/owner/b2-proof.scenario" --file "$WORK/owner/b2-regression.scenario"
want_rc 0
ESC=$("$VPY" -c 'import json,sys; print(" ".join(str(e["id"]) for e in json.load(sys.stdin) if e.get("goal") == "ownerset"))' \
      < <("$K" --as viewer factory escalations --open --json))
for e in $ESC; do run "$K" --as owner factory ack "$e"; want_rc 0; done
owner_shut
factory ownerset
want_rc 0
status_turn
check owner-done goal=ownerset

leg "P0 (all): every escalation of the run reached the chat and was shown there once"
check chat-all logs="$TURNLOGS"

# --- teardown -----------------------------------------------------------------------------------
step "board stop, no process left, folder removed"
owner_open
PID=$(cat "$WS/var/board.pid")
run "$K" board stop
want_rc 0
if kill -0 "$PID" 2>/dev/null; then fail "board pid $PID still alive"; fi
LEFT=$(pgrep -f -- "$WS" || true)
[ -z "$LEFT" ] || fail "processes still running from $WS: $LEFT"
echo "no process from $WS is running"
cd /
WSDONE=$WS
WS=""
if [ "${KEEP:-0}" != 1 ]; then rm -rf "$WORK/u"; [ ! -e "$WSDONE" ] || fail "$WSDONE still exists"; fi
printf '\nE2E-FACTORY: PASS (%d legs, %d session turns, %ss)\n' "$LEGS" "$TURN" "$(( $(date +%s) - T0 ))"
