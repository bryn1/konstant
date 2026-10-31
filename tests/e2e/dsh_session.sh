#!/usr/bin/env bash
# Live end-to-end of a dsh SESSION on a local model (docs/DSH.md): a fresh install from the release
# tarball, a board job, then ONE headless dsh session driven by a real model through the
# konstant-gate plugin: job filed -> gate block injected -> phases (dsh subagents) -> DoD MET ->
# job closed -> `konstant verify` PASS -> verified.
#
#   KONSTANT_E2E_DSH_BASE_URL=http://<host>:<port>/v1 KONSTANT_E2E_DSH_MODEL=<served name> \
#     bash tests/e2e/dsh_session.sh [TARBALL]
#
# Needs a stock `dsh` first on PATH (a launcher that forces its own DSH_HOME loads another
# profile; `doctor` says so), node, and an OpenAI-compatible endpoint. The endpoint address is
# taken from the environment and written only into the temp workspace's konstant.toml. The
# workspace goes under $HOME (dsh's sandbox gives a phase an empty private /tmp, so a workspace
# under /tmp cannot work); KONSTANT_E2E_DIR overrides. KEEP=1 keeps it. Exit 0 = verified.
set -euo pipefail

REPO=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd -P)
BUILD_PY="$REPO/.venv/bin/python"
[ -x "$BUILD_PY" ] || BUILD_PY=python3
: "${KONSTANT_E2E_DSH_BASE_URL:?set KONSTANT_E2E_DSH_BASE_URL (an OpenAI-compatible /v1 URL)}"
: "${KONSTANT_E2E_DSH_MODEL:?set KONSTANT_E2E_DSH_MODEL (the served model name)}"
TIMEOUT=${KONSTANT_E2E_DSH_TIMEOUT:-2400}
BASE=$(mktemp -d "${KONSTANT_E2E_DIR:-$HOME}/.konstant-e2e-dsh.XXXXXX")
WS=""
STEP=0
T0=$(date +%s)

cleanup() {
  local rc=$?
  if [ -n "$WS" ] && [ -f "$WS/var/board.pid" ]; then "$WS/bin/konstant" board stop >/dev/null 2>&1 || true; fi
  if [ "${KEEP:-0}" = 1 ]; then echo "kept $BASE"; else rm -rf "$BASE"; fi
  [ $rc -eq 0 ] || echo "E2E-DSH: FAILED (exit $rc)"
  exit $rc
}
trap cleanup EXIT

step() { STEP=$((STEP + 1)); printf '\n== %d. %s (+%ss)\n' "$STEP" "$*" "$(( $(date +%s) - T0 ))"; }
fail() { echo "E2E-DSH FAIL: $*"; exit 1; }
run() {
  printf '$ %s\n' "$*"
  set +e; OUT=$("$@" 2>&1); RC=$?; set -e
  [ -z "$OUT" ] || printf '%s\n' "$OUT" | sed 's/^/  | /'
  printf '  -> exit %d\n' "$RC"
}
want_rc() { [ "$RC" -eq "$1" ] || fail "expected exit $1, got $RC"; }
want_out() { printf '%s' "$OUT" | grep -qE -- "$1" || fail "output lacks /$1/"; }
jget() { "$WS/.venv/bin/python" -c 'import json,sys; d=json.loads(sys.argv[1]); print(eval(sys.argv[2], {}, {"d": d}))' "$1" "$2"; }

export GIT_AUTHOR_NAME=e2e GIT_AUTHOR_EMAIL=e2e@example.com
export GIT_COMMITTER_NAME=e2e GIT_COMMITTER_EMAIL=e2e@example.com
unset KONSTANT_HOME KONSTANT_IN_TASK KONSTANT_RUN KONSTANT_ROLE KONSTANT_CATALOG

step "release tarball"
if [ $# -ge 1 ]; then TARBALL=$(readlink -f "$1"); echo "using $TARBALL"
else
  DENY=(--no-denylist); [ -f "$REPO/release/denylist.local.txt" ] && DENY=(--denylist "$REPO/release/denylist.local.txt")
  run env PYTHONPATH="$REPO/src" "$BUILD_PY" -m konstant.release build --version 0.1.0 --worktree \
      --root "$REPO" --dist "$BASE/dist" "${DENY[@]}"
  want_rc 0; want_out 'RESULT: CLEAN'; TARBALL="$BASE/dist/konstant-0.1.0.tar.gz"
fi

step "unpack + install (--harness dsh) + local endpoint in konstant.toml"
mkdir -p "$BASE/u"; tar -xzf "$TARBALL" -C "$BASE/u"; WS=$(echo "$BASE"/u/konstant-*)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
run "$WS/install.sh" --yes --port "$PORT" --harness dsh
want_rc 0
"$WS/.venv/bin/python" - "$WS/konstant.toml" "$KONSTANT_E2E_DSH_MODEL" "$KONSTANT_E2E_DSH_BASE_URL" <<'PY'
import sys
p, model, url = sys.argv[1:4]
s = open(p).read().replace('name = "dsh"', f'name = "dsh"\nmodel = "{model}"', 1)
s += f'\n[harness.endpoint]\nbase_url = "{url}"\napi_key_env = ""\n'
open(p, "w").write(s)
PY
cd "$WS"
run bin/konstant agents sync
want_rc 0; want_out 'konstant-session.patch.yml|change'

step "doctor: dsh layers, reach (reads enforced by the jail)"
run bin/konstant doctor
want_out 'PASS +dsh layers'; want_out 'reads enforced'

step "board, project, job with a DoD probe"
run bin/konstant board start; want_rc 0
run bin/konstant project add demo --init-git; want_rc 0
cat > "$BASE/brief.md" <<'EOF'
Write projects/demo/USAGE.md: a short usage note for the demo project (what the project is for and how a user adds a file to it).

DoD:
- projects/demo/USAGE.md exists, is committed, and starts with a "# Usage" heading
PROBE: grep -c "^# Usage" projects/demo/USAGE.md => ^[1-9]
EOF
run bin/konstant job add "T1: usage note for demo" --project demo --type docs --brief "$BASE/brief.md" --json
want_rc 0
JOB=$(jget "$OUT" 'd["id"]'); echo "JOB=$JOB"

step "dsh session (headless) on the local model: gate -> phases -> DoD loop -> close -> verify"
TASK="[job:$JOB] [type:docs] Write projects/demo/USAGE.md as the job's DoD asks: a short usage note for the demo project (what it is for, how a user adds a file). Commit it."
echo "task: $TASK"
TS=$(date +%s)
set +e
printf '%s' "$TASK" | timeout "$TIMEOUT" bin/konstant dsh --project demo headless - \
    > "$BASE/session.out" 2> "$BASE/session.err"
SRC=$?
set -e
echo "dsh session exit $SRC after $(( $(date +%s) - TS ))s"
echo "-- plugin decisions (var/logs/konstant-gate.log):"
sed 's/^/  | /' var/logs/konstant-gate.log || fail "the konstant-gate plugin logged nothing: it did not load"
grep -q 'dod-loop ARMED' var/logs/konstant-gate.log || fail "the gate never armed the loop"
grep -q 'konstant verify PASS' var/logs/konstant-gate.log || fail "the plugin did not see konstant verify PASS"
SESS=var/harness/dsh/session/home
echo "dsh session entries (the orchestrator + its subagent children): $(ls -d "$SESS"/sessions/*/* | wc -l)"
echo "-- the session's final answer (stdout, last 40 lines):"
tail -n 40 "$BASE/session.out" | sed 's/^/  | /'

step "the job was walked to verified"
run bin/konstant job show "$JOB" --trail --json
want_rc 0
STATUS=$(jget "$OUT" 'd["status"]'); echo "status=$STATUS"
echo "-- trail (ts | kind | actor | first line):"
"$WS/.venv/bin/python" - "$OUT" <<'PY'
import json, sys
for r in json.loads(sys.argv[1]).get("trail", []):
    first = (r["body"] or "").splitlines()[0][:110] if r["body"] else ""
    print(f"  {r['ts']} | {r['kind']:9} | {r['actor']:12} | {first}")
PY
echo "verifications: $(jget "$OUT" '[(v["round"], v["verdict"]) for v in d.get("verifications", [])]')"
[ "$STATUS" = verified ] || fail "job $JOB is $STATUS, not verified"

step "independent re-checks"
RUN=$(ls -d var/runs/*/ | while read -r d; do grep -q "\"job\": $JOB" "$d/record.json" 2>/dev/null && echo "${d%/}"; done | tail -1)
echo "run dir: $RUN"
run bin/konstant task check "$RUN"
want_rc 0
run git -C projects/demo log --oneline -- USAGE.md
want_rc 0; want_out '.'
echo "E2E-DSH: PASS ($STEP steps, $(( $(date +%s) - T0 ))s)"
