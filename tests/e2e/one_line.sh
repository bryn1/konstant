#!/usr/bin/env bash
# One-line-install end-to-end test: the fresh-install e2e, installed through
# `curl -fsSL <local release server>/latest/download/get.sh | bash -s -- ...` instead of
# unpack + install.sh. Usage: bash tests/e2e/one_line.sh [DIST_DIR]  (default: a fresh build)
exec bash "$(dirname "$(readlink -f "$0")")/fresh_install.sh" --one-line "$@"
