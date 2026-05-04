#!/bin/sh
# Install the tracked pre-commit hook into this clone's hooks dir.
#
# Run once after cloning, and re-run after any change to
# tools/hooks/pre-commit. No frameworks, no silent side-effects --
# just a copy + chmod.
#
# Worktree-safe: writes to git's --git-common-dir (the shared gitdir
# at <repo>/.git) rather than --show-toplevel/.git. From a worktree
# `--show-toplevel` is the worktree dir whose .git is a *file* (not a
# directory), so the legacy `$REPO_ROOT/.git/hooks/pre-commit` path
# silently fails. The common dir is shared across the main checkout
# and every worktree, so installing once applies everywhere.

set -e

GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
if [ -z "$GIT_COMMON_DIR" ]; then
    echo "[install-hooks] ERROR: not inside a git working tree." >&2
    exit 1
fi

# `--git-common-dir` may be relative when cwd is inside the repo root.
# Resolve to absolute so the cp works regardless of cwd.
case "$GIT_COMMON_DIR" in
    /*|[A-Za-z]:*) ;;  # already absolute (POSIX or Windows drive)
    *) GIT_COMMON_DIR="$(cd "$GIT_COMMON_DIR" && pwd)" ;;
esac

# `--show-toplevel` is the directory we're in (worktree dir if we're
# in a worktree, repo root if we're in the main checkout). The tracked
# source we want to copy lives at <show-toplevel>/tools/hooks/pre-commit
# in either case (worktrees mirror tracked content).
TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null)"
SRC="$TOPLEVEL/tools/hooks/pre-commit"
DST="$GIT_COMMON_DIR/hooks/pre-commit"

if [ ! -f "$SRC" ]; then
    echo "[install-hooks] ERROR: source hook missing at $SRC" >&2
    exit 1
fi

mkdir -p "$GIT_COMMON_DIR/hooks"
cp -f "$SRC" "$DST"
chmod +x "$DST" 2>/dev/null || true

echo "[install-hooks] Installed: $SRC -> $DST"
echo "[install-hooks] (Hook is shared across main + all worktrees via git's common dir.)"
echo "[install-hooks] Done. Re-run this script if tools/hooks/pre-commit changes."
