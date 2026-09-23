#!/usr/bin/env bash
# Full local quality gate: lint, format, types, tests, dependency audit.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] && PY=.venv/bin/python || PY=python3
step() { echo; echo "== $1 =="; shift; "$@"; }
step "ruff check"        "$PY" -m ruff check .
step "ruff format check" "$PY" -m ruff format --check .
step "mypy"              "$PY" -m mypy
step "pytest"            "$PY" -m pytest -q
step "pip-audit"         "$PY" -m pip_audit --skip-editable
echo; echo "All checks passed."
