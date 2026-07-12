#!/usr/bin/env bash
# Lint chỉ những file đang có thay đổi (git diff). Không autofix — chỉ báo lỗi,
# để Claude/người review chủ động quyết định sửa gì.
set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$repo_root" || exit 0

py_files=$(git diff --name-only --diff-filter=ACMR -- 'backend/*.py')
if [ -n "$py_files" ]; then
  ( cd backend && echo "$py_files" | sed 's|^backend/||' | xargs -r uv run ruff check )
fi

ts_files=$(git diff --name-only --diff-filter=ACMR -- 'frontend/*.ts' 'frontend/*.tsx')
if [ -n "$ts_files" ]; then
  ( cd frontend && npm run lint )
fi

exit 0
