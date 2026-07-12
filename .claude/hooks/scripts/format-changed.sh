#!/usr/bin/env bash
# Format chỉ những file đang có thay đổi (git diff), không format toàn repo mỗi lần —
# tránh chậm và tránh reformat file không liên quan.
set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$repo_root" || exit 0

py_files=$(git diff --name-only --diff-filter=ACMR -- 'backend/*.py')
if [ -n "$py_files" ]; then
  ( cd backend && echo "$py_files" | sed 's|^backend/||' | xargs -r uv run ruff format )
fi

ts_files=$(git diff --name-only --diff-filter=ACMR -- 'frontend/*.ts' 'frontend/*.tsx')
if [ -n "$ts_files" ]; then
  ( cd frontend && echo "$ts_files" | sed 's|^frontend/||' | xargs -r npx prettier --write )
fi

exit 0
