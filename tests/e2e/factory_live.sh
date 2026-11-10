#!/usr/bin/env bash
# The optional LIVE run of the level-5 proof (docs/LEVEL5.md section 7; not part of CI): the sample
# goal through the REAL chat path on dsh with a real model behind a local OpenAI-compatible
# endpoint, the same model playing every role (orchestrator, planner, DoD reviewer, scenario writer,
# producers, verifying phases). Legs P0 + P1, shipped through the github target to a LOCAL bare
# repository with the `gh` stand-in (never a real GitHub).
#
#   KONSTANT_E2E_DSH_BASE_URL=http://<host>:<port>/v1 KONSTANT_E2E_DSH_MODEL=<served name> \
#   KONSTANT_E2E_DSH=<a plain dsh executable> bash tests/e2e/factory_live.sh [TARBALL]
#
# KONSTANT_E2E_DSH must be a stock dsh (e.g. a two-line shim running dsh's apps/cli/lib/bin.js
# with node by absolute paths outside /tmp), never a launcher that forces its own DSH_HOME; it is
# copied first on PATH as `dsh`.
# The endpoint address and the model name go only into the temp workspace's konstant.toml.
# KONSTANT_E2E_LIVE_TIMEOUT (default 21600 s = 6 h) boxes the whole run; the endpoint is probed
# every 30 s and the factory is stopped when it has answered with errors for more than 2 minutes.
# The workspace goes under $HOME (dsh's sandbox gives a phase an empty private /tmp). KEEP=1 keeps
# it. Prints `E2E-FACTORY-LIVE: PASS` (the goal done, every job shipped) or `E2E-FACTORY-LIVE:
# PARTIAL (<where it stopped>)` with the trail of what was reached.
set -euo pipefail

if [ -z "${KONSTANT_E2E_SCRUBBED:-}" ]; then
  keep=(KONSTANT_E2E_SCRUBBED=1 "HOME=$HOME" "PATH=$PATH" "LANG=${LANG:-C.UTF-8}")
  for v in LC_ALL TERM TMPDIR LEFTHOOK PYTHON KEEP KONSTANT_E2E_DSH KONSTANT_E2E_DSH_BASE_URL \
           KONSTANT_E2E_DSH_MODEL KONSTANT_E2E_LIVE_TIMEOUT KONSTANT_E2E_DIR; do
    [ -z "${!v:-}" ] || keep+=("$v=${!v}")
  done
  exec env -i "${keep[@]}" bash "$(readlink -f "$0")" "$@" </dev/null
fi
exec </dev/null
if env | cut -d= -f1 | grep -qiE 'secret|token|password|api_?key'; then
  echo "E2E-FACTORY-LIVE FAIL: a secret-shaped variable survived the scrub"; exit 1
fi
: "${KONSTANT_E2E_DSH_BASE_URL:?set KONSTANT_E2E_DSH_BASE_URL (an OpenAI-compatible /v1 URL)}"
: "${KONSTANT_E2E_DSH_MODEL:?set KONSTANT_E2E_DSH_MODEL (the served model name)}"
: "${KONSTANT_E2E_DSH:?set KONSTANT_E2E_DSH (a plain dsh executable)}"
[ -x "$KONSTANT_E2E_DSH" ] || { echo "KONSTANT_E2E_DSH is not executable"; exit 2; }

REPO=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd -P)
BUILD_PY="$REPO/.venv/bin/python"
[ -x "$BUILD_PY" ] || BUILD_PY=python3
BOX=${KONSTANT_E2E_LIVE_TIMEOUT:-21600}
T0=$(date +%s)
DEADLINE=$((T0 + BOX))
BASE=$(mktemp -d "${KONSTANT_E2E_DIR:-$HOME}/.konstant-e2e-live.XXXXXX")
mkdir -p "$BASE/bin" "$BASE/src"
# a COPY, not a link: a jailed phase has its own private /tmp, so a link into /tmp would dangle
cp -L "$KONSTANT_E2E_DSH" "$BASE/bin/dsh"; chmod 755 "$BASE/bin/dsh"
export PATH="$BASE/bin:$PATH"
WS=""
FPID=""
WPID=""
STAGE="install"

stamp() { printf '[%s +%ss]' "$(date -u +%H:%M:%SZ)" "$(( $(date +%s) - T0 ))"; }
say() { printf '\n%s %s\n' "$(stamp)" "$*"; }
left() { echo $(( DEADLINE - $(date +%s) )); }
cleanup() {
  local rc=$?
  [ -z "$WPID" ] || kill "$WPID" 2>/dev/null || true
  if [ -n "$WS" ] && [ -x "$WS/bin/konstant" ]; then
    [ ! -f "$WS/var/factory/factory.pid" ] || "$WS/bin/konstant" factory stop --now --wait 60 >/dev/null 2>&1 || true
    [ -z "$FPID" ] || kill -TERM "$FPID" 2>/dev/null || true
    [ ! -f "$WS/var/board.pid" ] || "$WS/bin/konstant" board stop >/dev/null 2>&1 || true
  fi
  if [ "${KEEP:-0}" = 1 ]; then echo "kept $BASE"; else rm -rf "$BASE"; fi
  exit $rc
}
trap cleanup EXIT
fail() { say "E2E-FACTORY-LIVE FAIL ($STAGE): $*"; exit 1; }

export GIT_AUTHOR_NAME=e2e GIT_AUTHOR_EMAIL=e2e@example.com
export GIT_COMMITTER_NAME=e2e GIT_COMMITTER_EMAIL=e2e@example.com
unset KONSTANT_HOME KONSTANT_IN_TASK KONSTANT_RUN KONSTANT_ROLE KONSTANT_CATALOG

say "release tarball + install (--harness dsh) under $BASE"
VER=$(PYTHONPATH="$REPO/src" "$BUILD_PY" -c 'import konstant; print(konstant.__version__)')
if [ $# -ge 1 ]; then TARBALL=$(readlink -f "$1")
else
  DENY=(--no-denylist); [ -f "$REPO/release/denylist.local.txt" ] && DENY=(--denylist "$REPO/release/denylist.local.txt")
  PYTHONPATH="$REPO/src" "$BUILD_PY" -m konstant.release build --version "$VER" --worktree \
    --root "$REPO" --dist "$BASE/dist" "${DENY[@]}" | grep -E '^(RESULT|SHA256)' || fail "release build"
  TARBALL="$BASE/dist/konstant-$VER.tar.gz"
fi
mkdir -p "$BASE/u"; tar -xzf "$TARBALL" -C "$BASE/u"; WS="$BASE/u/konstant-$VER"; K="$WS/bin/konstant"
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
(cd "$WS" && ./install.sh --yes --port "$PORT" --harness dsh >"$BASE/install.log" 2>&1) || fail "install.sh (see $BASE/install.log)"
VPY="$WS/.venv/bin/python"
REMOTE="$BASE/github/greeter.git"
"$VPY" - "$WS/konstant.toml" "$KONSTANT_E2E_DSH_MODEL" "$KONSTANT_E2E_DSH_BASE_URL" <<'PY'
import sys
p, model, url = sys.argv[1:4]
s = open(p).read().replace('name = "dsh"', f'name = "dsh"\nmodel = "{model}"\nmax_concurrency = 2', 1)
s += (f'\n[harness.endpoint]\nbase_url = "{url}"\napi_key_env = ""\n'
      '\n[factory]\ntick_s = 10\nstall_after_s = 21600\ngoal_roles = ["owner", "orchestrator"]\n'
      '\n[notify]\nkind = "chat"\n')
open(p, "w").write(s)
PY
cd "$WS"
"$K" agents sync >/dev/null || fail "agents sync"
"$K" board start >/dev/null || fail "board start"
mkdir -p "$WS/projects/greeter" "$BASE/github"
cp -r examples/greeter/. projects/greeter/ && rm -f projects/greeter/goal.toml
git -C projects/greeter init -q -b main && git -C projects/greeter add -A && git -C projects/greeter commit -qm "greeter: the sample"
"$K" project add greeter >/dev/null || fail "project add"
git clone -q --bare projects/greeter "$REMOTE"
GH=$("$VPY" -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from tests.fixtures import fake_gh; print(fake_gh.install(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))' \
     "$WS" "$BASE/pinned" "$REMOTE" "$BASE/gh.log")
printf '\n[ship]\nremote = "%s"\ngh = "%s"\ngithub_repo = "example-org/greeter"\n\n[factory.defaults]\nship_target = "github"\n' \
  "$REMOTE" "$GH" >> konstant.toml
"$K" board stop >/dev/null; "$K" agents sync >/dev/null; "$K" board start >/dev/null || fail "board restart"
"$K" doctor > "$BASE/doctor.log" 2>&1 || true
grep -E '^(FAIL|WARN) ' "$BASE/doctor.log" || true
BASE_COMMIT=$(git -C projects/greeter rev-parse main)
echo "target greeter main = $BASE_COMMIT; ship target github -> a local bare repository + the gh stand-in"

# the endpoint watcher: errors for more than 2 minutes stop the factory
watch_endpoint() {
  local bad_since=0 now
  while sleep 30; do
    now=$(date +%s)
    if python3 -c 'import sys,urllib.request; urllib.request.urlopen(sys.argv[1].rstrip("/")+"/models", timeout=20).read()' \
         "$KONSTANT_E2E_DSH_BASE_URL" 2>/dev/null; then
      [ "$bad_since" -eq 0 ] || echo "$(stamp) endpoint healthy again" >> "$BASE/endpoint.log"
      bad_since=0
    else
      [ "$bad_since" -ne 0 ] || bad_since=$now
      echo "$(stamp) endpoint error (since +$(( now - bad_since ))s)" >> "$BASE/endpoint.log"
      if [ $(( now - bad_since )) -gt 120 ]; then
        echo "$(stamp) endpoint failing > 2 min: stopping the factory" >> "$BASE/endpoint.log"
        touch "$BASE/ENDPOINT_DOWN"
        "$K" factory stop --now --wait 120 >/dev/null 2>&1 || true
        return
      fi
    fi
  done
}
watch_endpoint &
WPID=$!

SID=""
# owner_turn TEXT: one owner message into the orchestrator session (dsh headless --json)
owner_turn() {
  local n=$1 text=$2 t; t=$(date +%s)
  say "owner turn $n: $text"
  local extra=(); [ -z "$SID" ] || extra=(--session-id "$SID")
  set +e
  printf '%s' "$text" | timeout "$(left)" "$K" dsh headless --json "${extra[@]}" - \
    > "$BASE/turn$n.jsonl" 2> "$BASE/turn$n.err"
  local rc=$?
  set -e
  [ -n "$SID" ] || SID=$("$VPY" -c 'import json,re,sys
for ln in open(sys.argv[1]):
    m = re.search(r"\"(session-[0-9a-f-]{8,})\"", ln)
    if m: print(m.group(1)); break' "$BASE/turn$n.jsonl")
  echo "turn $n: dsh exit $rc after $(( $(date +%s) - t ))s; session ${SID:-?}"
  grep -h 'chat turn\|goal add\|INTAKE\|konstant' "$WS/var/logs/konstant-gate.log" 2>/dev/null | tail -n 5 | sed 's/^/  gate | /' || true
  "$VPY" - "$BASE/turn$n.jsonl" <<'PY' | tail -n 12 | sed 's/^/  model | /'
import json, sys
last = []
for ln in open(sys.argv[1]):
    try:
        e = json.loads(ln)
    except ValueError:
        continue
    t = e.get("text") or e.get("content") or (e.get("message") or {}).get("content") if isinstance(e, dict) else None
    if isinstance(t, str) and t.strip():
        last.append(t.strip().replace("\n", " ")[:300])
print("\n".join(last[-6:]) or "(no text events)")
PY
}

STAGE="P0 chat intake"
owner_turn 1 "make greeter greet by name, with a CLI and a README"
[ -n "$SID" ] || fail "no dsh session id in the first turn's events"
GOAL=$("$K" --as viewer goal list --json | "$VPY" -c 'import json,sys; s=sys.argv[1]; g=[x for x in json.load(sys.stdin) if x.get("session")==s and x["status"]=="proposed"]; print(g[-1]["slug"] if g else "")' "$SID")
[ -n "$GOAL" ] || fail "the orchestrator proposed no goal in the request's turn"
echo "proposed: goal $GOAL (session $SID)"
owner_turn 2 "yes"
"$K" --as viewer goal show "$GOAL" --json > "$BASE/goal.json"
"$VPY" -c 'import json,sys; g=json.load(open(sys.argv[1])); print("goal", g["slug"], g["status"], "source", g["source"], "limits", {k:v for k,v in g["limits"].items() if v not in (0,"0",None)}); sys.exit(0 if g["status"]=="active" and g["source"]=="chat" else 1)' "$BASE/goal.json" \
  || fail "the owner's yes did not file the goal"
T_P0=$(( $(date +%s) - T0 ))

STAGE="P1 the factory"
say "factory run $GOAL --until-idle (time box $(left)s; [harness] max_concurrency = 2)"
set +e
timeout --signal=TERM --kill-after=120 "$(left)" "$K" factory run "$GOAL" --until-idle > "$BASE/factory.log" 2>&1 &
FPID=$!
wait "$FPID"; FRC=$?
FPID=""
set -e
T_F=$(( $(date +%s) - T0 ))
echo "factory exit $FRC at +${T_F}s"
[ ! -f "$BASE/ENDPOINT_DOWN" ] || echo "the endpoint watcher stopped the factory (see the endpoint log)"
"$K" factory resume >/dev/null 2>&1 || true            # clear a kill switch the watcher set

STAGE="report"
if [ "$(left)" -gt 300 ]; then owner_turn 3 "what is the status of the factory?"; fi
say "trail (board artifacts)"
"$VPY" - "$K" "$GOAL" "$REMOTE" "$BASE_COMMIT" "$BASE/gh.log" > "$BASE/trail.txt" <<'PY' || true
import json, subprocess, sys
K, goal, remote, base, ghlog = sys.argv[1:6]
def kj(*a):
    r = subprocess.run([K, "--as", "viewer", *a, "--json"], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
g = kj("goal", "show", goal) or {}
print(f"goal {goal}: status {g.get('status')} intake {g.get('intake')}")
jobs = [j for j in (kj("job", "list", "--project", "greeter") or []) if j.get("goal") == goal]
ships = kj("ship", "list") or []
for j in jobs:
    d = kj("job", "show", j["id"]) or {}
    seal = [h["hid"] for h in d.get("holdouts", []) if h["state"] == "sealed"]
    vers = [v["verdict"] for v in d.get("verifications", [])]
    sh = [s["state"] for s in ships if s["job_id"] == j["id"]]
    print(f"job {j['display_id']} ({j['type']}) {j['status']}: holdouts sealed {seal}, "
          f"attempts {len(d.get('runs', []))}, verdicts {vers}, ships {sh}")
log = subprocess.run(["git", "-C", remote, "log", "--oneline", "--first-parent", f"{base}..main"],
                     capture_output=True, text=True).stdout.strip()
print("remote main since the base:\n" + (log or "(unchanged)"))
try:
    print("gh stand-in calls:", [json.loads(x)["call"] for x in open(ghlog)])
except OSError:
    print("gh stand-in calls: none")
done = g.get("status") == "done" and jobs and all(
    any(s["job_id"] == j["id"] and s["state"] == "shipped" for s in ships) for j in jobs)
print("RESULT", "DONE" if done else "PARTIAL")
PY
cat "$BASE/trail.txt"
echo "events:"; sed 's/^/  /' "$WS/var/factory/events.jsonl" 2>/dev/null | cut -c1-240 || true
[ ! -f "$BASE/endpoint.log" ] || { echo "endpoint log:"; sed 's/^/  /' "$BASE/endpoint.log"; }
echo "times: P0 chat intake done at +${T_P0}s, factory ended at +${T_F}s (exit $FRC), total +$(( $(date +%s) - T0 ))s"
if grep -q '^RESULT DONE' "$BASE/trail.txt"; then
  echo "E2E-FACTORY-LIVE: PASS"
else
  why="factory exit $FRC"; [ "$(left)" -gt 0 ] || why="time box ${BOX}s reached"
  [ ! -f "$BASE/ENDPOINT_DOWN" ] || why="endpoint errors > 2 min"
  echo "E2E-FACTORY-LIVE: PARTIAL ($why)"
fi
