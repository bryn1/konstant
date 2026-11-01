#!/bin/sh
# konstant one-line installer (DESIGN §10.1). Published as a release asset next to the tarball:
#
#   curl -fsSL https://github.com/bryn1/konstant/releases/latest/download/get.sh | bash
#   curl -fsSL https://github.com/bryn1/konstant/releases/latest/download/get.sh | bash -s -- --dir myproj --harness dsh
#   ... | bash -s -- --confinement open      # phases get your host (docs/CONCEPTS.md "Confinement profiles")
#
# It checks the prerequisites, resolves the version (the latest release unless --version), downloads
# konstant-<V>.tar.gz and its .sha256, verifies the checksum BEFORE unpacking, unpacks into ./konstant
# (or --dir) and runs ./install.sh there. It never uses sudo and writes nothing outside the target
# folder (the download is staged inside it); a failed download or a checksum mismatch leaves nothing
# behind. KONSTANT_RELEASE_URL replaces the release base URL (a mirror, or a local test server); under
# it, `latest/download/VERSION` names the latest version and `download/v<V>/` holds the assets.
#
# POSIX sh. Everything below is a function definition; the only command is on the last line, inside
# braces, so a truncated download is a syntax error and runs nothing.

kg_usage() {
  cat <<'EOF'
usage: curl -fsSL <release>/get.sh | bash -s -- [options]      (or: sh get.sh [options])

  --dir DIR       install into DIR (default: ./konstant); refused when DIR exists and is not empty
  --version V     install release V (default: the latest release)
  --harness H     the agent CLI that runs konstant's phases: claude, codex, gemini, dsh, or a
                  command template for any other CLI (e.g. "mycli -p {prompt}"); without it you are
                  asked on a terminal, otherwise the first of claude/codex/gemini/dsh on PATH is used
  --port N        board port (default: the first free port from 8470)
  --confinement P what phases may see and do: closed (default: inside the workspace only) or open
                  (your host like your own shell: ssh, docker, your credentials; the integrity
                  core is kept in both); without it you are asked on a terminal
  --wheels DIR    offline install of the Python dependencies (see install.sh --help)
  --no-install    download, verify and unpack only; run ./install.sh yourself
  --yes           never ask (non-interactive)
  -h, --help      this help

  env KONSTANT_RELEASE_URL   release base URL (default: the project's GitHub releases)
  env PYTHON                 the Python to use (>= 3.10)
EOF
}

kg_say() { printf 'konstant-get: %s\n' "$*"; }

kg_die() {
  printf 'konstant-get: ERROR: %s\n' "$*" >&2
  kg_cleanup
  exit 1
}

# remove what this run created: the staging folder, and the target folder when this run made it
kg_cleanup() {
  if [ -n "${KG_STAGE:-}" ] && [ -d "$KG_STAGE" ]; then rm -rf "$KG_STAGE"; fi
  if [ "${KG_CREATED:-0}" = 1 ] && [ -n "${KG_DIR:-}" ] && [ -d "$KG_DIR" ]; then rm -rf "$KG_DIR"; fi
  KG_STAGE="" KG_CREATED=0
}

kg_have() { command -v "$1" >/dev/null 2>&1; }

# kg_fetch URL DEST: download URL to DEST (curl or wget); non-zero on any HTTP error
kg_fetch() {
  if kg_have curl; then
    curl -fsSL --retry 2 -o "$2" "$1"
  else
    wget -q -O "$2" "$1"
  fi
}

kg_sha256() {
  if kg_have sha256sum; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# kg_python: print the first Python >= 3.10 ($PYTHON first); non-zero when there is none
kg_python() {
  if [ -n "${PYTHON:-}" ]; then kg_cands=$PYTHON; else kg_cands="python3 python3.14 python3.13 python3.12 python3.11 python3.10"; fi
  for kg_c in $kg_cands; do
    kg_have "$kg_c" || continue
    if "$kg_c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      printf '%s\n' "$kg_c"
      return 0
    fi
  done
  return 1
}

kg_prereqs() {
  case "$(uname -s 2>/dev/null)" in
    Linux|Darwin) ;;
    CYGWIN*|MINGW*|MSYS*) kg_die "Windows shells are not supported: run this inside WSL2" ;;
    *) kg_say "warning: untested OS $(uname -s 2>/dev/null); Linux and macOS are supported" ;;
  esac
  [ "$(id -u)" -ne 0 ] || kg_die "do not run as root (no sudo): konstant installs and runs as your own user"
  kg_missing=""
  kg_have tar || kg_missing="$kg_missing tar"
  kg_have awk || kg_missing="$kg_missing awk"
  kg_have gzip || kg_missing="$kg_missing gzip"
  kg_have sha256sum || kg_have shasum || kg_missing="$kg_missing sha256sum-or-shasum"
  kg_have curl || kg_have wget || kg_missing="$kg_missing curl-or-wget"
  [ -z "$kg_missing" ] || kg_die "missing required tools:$kg_missing (install them with your package manager)"
  if ! KG_PY=$(kg_python); then
    if [ -n "${PYTHON:-}" ]; then
      kg_die "PYTHON=$PYTHON is not a Python >= 3.10"
    elif kg_have python3; then
      kg_die "konstant needs Python >= 3.10; python3 is $(python3 -c 'import sys; print(sys.version.split()[0])' 2>/dev/null) (install a newer python3, or set PYTHON=/path/to/python3.X)"
    fi
    kg_die "Python >= 3.10 not found: install python3 (e.g. sudo apt install python3 python3-venv, brew install python), then re-run"
  fi
  kg_have git || kg_say "warning: git not found; projects are git repositories (install git before adding one)"
  kg_say "system: $(uname -s) $(uname -m), python $("$KG_PY" -c 'import sys; print(sys.version.split()[0])') ($KG_PY)"
}

kg_check_version() {
  case "$1" in
    v[0-9]*) KG_VERSION=${1#v} ;;
    [0-9]*) KG_VERSION=$1 ;;
    *) kg_die "not a release version: '$1' (expected e.g. 0.1.0)" ;;
  esac
  case "$KG_VERSION" in
    *[!0-9A-Za-z.+-]*|*..*) kg_die "not a release version: '$1' (expected e.g. 0.1.0)" ;;
  esac
}

kg_target() {
  case "$KG_DIR" in /*) ;; *) KG_DIR="$(pwd -P)/$KG_DIR" ;; esac
  case "$KG_DIR" in *[[:space:]]*) kg_die "the folder path contains whitespace: $KG_DIR (pick another --dir)" ;; esac
  if [ -e "$KG_DIR" ] || [ -L "$KG_DIR" ]; then
    [ -d "$KG_DIR" ] || kg_die "$KG_DIR exists and is not a folder"
    # fail closed: a folder that cannot be listed may hold anything (G-06)
    [ -r "$KG_DIR" ] && [ -x "$KG_DIR" ] \
      || kg_die "$KG_DIR exists and cannot be read: refusing to install into it (pick another --dir)"
    kg_ls=$(ls -A "$KG_DIR") || kg_die "$KG_DIR cannot be listed: refusing to install into it (pick another --dir)"
    [ -z "$kg_ls" ] \
      || kg_die "$KG_DIR exists and is not empty: refusing to overwrite it (pick another --dir; to upgrade, install into a new folder and run ./install.sh --from <old folder> there)"
    [ -w "$KG_DIR" ] || kg_die "$KG_DIR is not writable"
  else
    kg_parent=$(dirname "$KG_DIR")
    [ -d "$kg_parent" ] && [ -w "$kg_parent" ] || kg_die "cannot create $KG_DIR: $kg_parent is missing or not writable"
    mkdir "$KG_DIR" || kg_die "cannot create $KG_DIR"
    KG_CREATED=1
  fi
}

# the agent CLI: --harness, else ask on a terminal, else the first one found on PATH
kg_harness() {
  [ -z "$KG_HARNESS" ] || return 0
  kg_found=""
  for kg_h in claude codex gemini dsh; do
    if kg_have "$kg_h"; then kg_found="$kg_found $kg_h"; fi
  done
  kg_found=${kg_found# }
  kg_default=${kg_found%% *}
  if [ "$KG_YES" != 1 ] && ( : </dev/tty ) 2>/dev/null && [ -t 2 ]; then
    {
      printf '\nWhich agent CLI should run konstant'"'"'s phases?\n'
      printf '  claude | codex | gemini | dsh  (found on PATH: %s)\n' "${kg_found:-none}"
      printf '  or a command template for any other CLI, e.g. "mycli -p {prompt}"\n'
      printf '  (local models: codex or dsh with [harness.endpoint]; docs/HARNESSES.md)\n'
      printf 'harness [%s]: ' "${kg_default:-claude}"
    } >&2
    read -r KG_HARNESS </dev/tty || KG_HARNESS=""
  fi
  [ -n "$KG_HARNESS" ] || KG_HARNESS=$kg_default
  if [ -n "$KG_HARNESS" ]; then
    kg_say "harness: $KG_HARNESS (change it later in konstant.toml [harness]; docs/HARNESSES.md)"
  else
    kg_say "harness: none found on PATH; konstant.toml defaults to Claude Code (claude, codex, gemini, dsh or any CLI: docs/HARNESSES.md)"
  fi
}

# the confinement profile: --confinement, else ask on a terminal, else closed (install.sh's default)
kg_confinement() {
  [ -z "$KG_CONFINEMENT" ] || return 0
  if [ "$KG_YES" != 1 ] && ( : </dev/tty ) 2>/dev/null && [ -t 2 ]; then
    {
      printf '\nConfinement: closed keeps every phase inside the workspace; open gives phases your\n'
      printf 'host like your own shell (ssh, docker, your credentials), convenient but a model can act as you.\n'
      printf 'confinement [closed]: '
    } >&2
    read -r KG_CONFINEMENT </dev/tty || KG_CONFINEMENT=""
  fi
  case "$KG_CONFINEMENT" in
    ''|closed|open) ;;
    *) kg_die "confinement: answer closed or open (got $KG_CONFINEMENT)" ;;
  esac
  if [ -n "$KG_CONFINEMENT" ]; then
    kg_say "confinement: $KG_CONFINEMENT (change it later in konstant.toml [confinement]; docs/CONCEPTS.md)"
  fi
}

kg_download() {
  kg_base=${KONSTANT_RELEASE_URL:-https://github.com/bryn1/konstant/releases}
  kg_base=${kg_base%/}
  KG_STAGE="$KG_DIR/.konstant-get"
  mkdir "$KG_STAGE" || kg_die "cannot create $KG_STAGE"
  if [ -z "$KG_VERSION" ]; then
    kg_fetch "$kg_base/latest/download/VERSION" "$KG_STAGE/VERSION" \
      || kg_die "could not resolve the latest version from $kg_base/latest/download/VERSION (pass --version V)"
    kg_check_version "$(tr -d ' \r\n' <"$KG_STAGE/VERSION")"
  fi
  kg_tb="konstant-$KG_VERSION.tar.gz"
  kg_url="$kg_base/download/v$KG_VERSION"
  kg_say "downloading konstant $KG_VERSION from $kg_url/"
  kg_fetch "$kg_url/$kg_tb" "$KG_STAGE/$kg_tb" || kg_die "download failed: $kg_url/$kg_tb"
  kg_fetch "$kg_url/$kg_tb.sha256" "$KG_STAGE/$kg_tb.sha256" || kg_die "download failed: $kg_url/$kg_tb.sha256"
  # the checksum is verified BEFORE anything is unpacked
  kg_want=$(awk 'NR == 1 { print $1 }' "$KG_STAGE/$kg_tb.sha256")
  kg_name=$(awk 'NR == 1 { sub(/^\*/, "", $2); print $2 }' "$KG_STAGE/$kg_tb.sha256")
  case "$kg_want" in *[!0-9a-f]*|"") kg_die "$kg_tb.sha256 is malformed; nothing was installed" ;; esac
  [ "${#kg_want}" -eq 64 ] && [ "$kg_name" = "$kg_tb" ] \
    || kg_die "$kg_tb.sha256 is malformed or names another file; nothing was installed"
  kg_got=$(kg_sha256 "$KG_STAGE/$kg_tb")
  [ "$kg_got" = "$kg_want" ] \
    || kg_die "CHECKSUM MISMATCH for $kg_tb (expected $kg_want, got $kg_got): refusing to unpack; nothing was installed"
  kg_say "sha256 OK ($kg_want)"
  # every member must live under konstant-<V>/ with no absolute path and no '..'
  tar -tzf "$KG_STAGE/$kg_tb" >"$KG_STAGE/members" 2>/dev/null || kg_die "$kg_tb is not a readable tar.gz"
  # and be a regular file or a folder: the release ships no links or devices, so a symlink or
  # hardlink member (whose target tar -t does not show) is refused (G-07)
  tar -tvzf "$KG_STAGE/$kg_tb" >"$KG_STAGE/types" 2>/dev/null || kg_die "$kg_tb is not a readable tar.gz"
  kg_bad=$(awk 'substr($1, 1, 1) != "-" && substr($1, 1, 1) != "d" { print; exit }' "$KG_STAGE/types")
  [ -z "$kg_bad" ] || kg_die "unsafe member in $kg_tb (only files and folders are allowed): $kg_bad"
  while IFS= read -r kg_m; do
    case "$kg_m" in
      "konstant-$KG_VERSION/"*) ;;
      *) kg_die "unexpected member in $kg_tb: $kg_m" ;;
    esac
    case "/$kg_m/" in */../*) kg_die "unsafe member in $kg_tb: $kg_m" ;; esac
  done <"$KG_STAGE/members"
  tar -xzf "$KG_STAGE/$kg_tb" -C "$KG_DIR" --strip-components=1 || kg_die "unpacking $kg_tb failed"
  rm -rf "$KG_STAGE"
  KG_STAGE=""
  [ -f "$KG_DIR/install.sh" ] || kg_die "the release has no install.sh"
  kg_say "unpacked konstant $KG_VERSION into $KG_DIR"
}

kg_install() {
  if [ "$KG_NOINSTALL" = 1 ]; then
    kg_say "not installed (--no-install). Next: cd $KG_DIR && ./install.sh --yes"
    return 0
  fi
  KG_CREATED=0   # unpacked: from here on a failure keeps the folder so ./install.sh can be re-run
  set -- --yes
  [ -z "$KG_HARNESS" ] || set -- "$@" --harness "$KG_HARNESS"
  [ -z "$KG_CONFINEMENT" ] || set -- "$@" --confinement "$KG_CONFINEMENT"
  [ -z "$KG_PORT" ] || set -- "$@" --port "$KG_PORT"
  [ -z "$KG_WHEELS" ] || set -- "$@" --wheels "$KG_WHEELS"
  kg_say "running ./install.sh $*"
  if ! PYTHON="$KG_PY" "$KG_DIR/install.sh" "$@" </dev/null; then
    printf 'konstant-get: ERROR: ./install.sh failed (above); the files stay in %s: fix the cause, then run: cd %s && ./install.sh --yes\n' "$KG_DIR" "$KG_DIR" >&2
    exit 1
  fi
  printf '\nkonstant is ready in %s. Start here:\n  cd %s\n' "$KG_DIR" "$KG_DIR"
  case "$KG_HARNESS" in
    dsh) printf '  bin/konstant board start && bin/konstant dsh web     # dsh web UI with the konstant gate (docs/DSH.md)\n' ;;
    codex|gemini) printf '  bin/konstant board start && %s     # open %s in this folder; it reads AGENTS.md\n' "$KG_HARNESS" "$KG_HARNESS" ;;
    claude|"") printf '  bin/konstant board start && claude     # Claude Code reads CLAUDE.md and .claude/\n' ;;
    *) printf '  bin/konstant board start     # then open your agent CLI here; it reads AGENTS.md\n' ;;
  esac
  printf '  Any agent driving konstant: read AGENTS.md ("Operating konstant"). Docs: docs/QUICKSTART.md\n'
}

konstant_get() {
  set -u
  KG_DIR=konstant KG_VERSION="" KG_HARNESS="" KG_PORT="" KG_WHEELS="" KG_NOINSTALL=0 KG_YES=0
  KG_CONFINEMENT=""
  KG_STAGE="" KG_CREATED=0 KG_PY=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --dir|--version|--harness|--port|--wheels|--confinement)
        [ $# -ge 2 ] && [ -n "$2" ] || { printf 'konstant-get: %s needs a value\n' "$1" >&2; exit 2; }
        case "$1" in
          --dir) KG_DIR=$2 ;;
          --version) KG_VERSION=$2 ;;
          --harness) KG_HARNESS=$2 ;;
          --port) KG_PORT=$2 ;;
          --wheels) KG_WHEELS=$2 ;;
          --confinement) KG_CONFINEMENT=$2 ;;
        esac
        shift 2 ;;
      --no-install) KG_NOINSTALL=1; shift ;;
      --yes|-y) KG_YES=1; shift ;;
      -h|--help) kg_usage; exit 0 ;;
      *) printf 'konstant-get: unknown argument: %s\n' "$1" >&2; kg_usage >&2; exit 2 ;;
    esac
  done
  [ "$KG_HARNESS" != command ] \
    || { printf 'konstant-get: --harness command: pass the command itself, e.g. --harness "mycli -p {prompt}"\n' >&2; exit 2; }
  case "$KG_CONFINEMENT" in
    ''|closed|open) ;;
    *) printf 'konstant-get: --confinement must be closed or open\n' >&2; exit 2 ;;
  esac
  if [ -n "$KG_VERSION" ]; then kg_check_version "$KG_VERSION"; fi
  trap 'kg_cleanup; exit 130' INT TERM HUP
  kg_prereqs
  kg_target
  [ "$KG_NOINSTALL" = 1 ] || kg_harness
  [ "$KG_NOINSTALL" = 1 ] || kg_confinement
  kg_download
  trap - INT TERM HUP
  kg_install
}

{ konstant_get "$@"; }
