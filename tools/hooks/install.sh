#!/bin/sh
# Install the tracked pre-commit hook into this clone's .git/hooks/.
#
# Run once after cloning, and re-run after any change to
# tools/hooks/pre-commit. No frameworks, no silent side-effects --
# just a copy + chmod.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "[install-hooks] ERROR: not inside a git working tree." >&2
    exit 1
fi

SRC="$REPO_ROOT/tools/hooks/pre-commit"
DST="$REPO_ROOT/.git/hooks/pre-commit"

if [ ! -f "$SRC" ]; then
    echo "[install-hooks] ERROR: source hook missing at $SRC" >&2
    exit 1
fi

cp -f "$SRC" "$DST"
chmod +x "$DST" 2>/dev/null || true

echo "[install-hooks] Installed: $SRC -> $DST"
echo "[install-hooks] Done. Re-run this script if tools/hooks/pre-commit changes."
