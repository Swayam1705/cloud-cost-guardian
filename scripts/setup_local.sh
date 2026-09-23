#!/usr/bin/env bash
# One-shot local setup for Linux/macOS (zero cost, no AWS needed).
#   ./scripts/setup_local.sh          # runtime only
#   ./scripts/setup_local.sh --dev    # + test/lint tooling
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "Python 3.10+ not found"; exit 1; }
"$PY" - <<'PYCHK'
import sys
assert sys.version_info >= (3, 10), f"Python 3.10+ required, found {sys.version.split()[0]}"
PYCHK

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --quiet --upgrade pip
REQ=requirements.txt
[ "${1:-}" = "--dev" ] && REQ=requirements-dev.txt
python -m pip install --quiet -r "$REQ"
[ -f .env ] || { [ -f .env.example ] && cp .env.example .env && echo "Created .env from .env.example"; }
python -m cloud_cost_guardian.cli.main validate-config >/dev/null
echo
echo "Setup complete."
echo "  source .venv/bin/activate"
echo "  python -m cloud_cost_guardian.cli.main scan --mode demo"
echo "  python -m cloud_cost_guardian.cli.main cleanup --dry-run"
