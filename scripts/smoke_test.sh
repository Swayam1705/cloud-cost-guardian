#!/usr/bin/env bash
# End-to-end smoke test of the zero-cost demo lifecycle.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] && PY=.venv/bin/python || PY="${PYTHON:-python3}"
TMP="$(mktemp -d)"
export CCG_ARTIFACTS_DIR="$TMP/artifacts" CCG_DATA_DIR="$TMP/data" CCG_LOG_LEVEL=WARNING
trap 'rm -rf "$TMP"' EXIT

run() { # desc expected_exit args...
  local desc="$1" expect="$2"; shift 2
  echo "-> $desc"
  set +e; "$PY" -m cloud_cost_guardian.cli.main "$@" >/dev/null; local rc=$?; set -e
  [ "$rc" -eq "$expect" ] || { echo "$desc: expected exit $expect, got $rc"; exit 1; }
}
run "validate-config"                0 validate-config
run "demo scan"                      0 scan --mode demo
run "report"                         0 report
run "cleanup dry-run"                0 cleanup --dry-run
run "protected resource is blocked"  3 cleanup --resource vol-0a1b2c3d4e5f60005 --approve
run "approved simulated remediation" 0 cleanup --resource vol-0a1b2c3d4e5f60001 --approve
run "re-scan after remediation"      0 scan --mode demo --no-notify
run "demo reset"                     0 demo reset
for f in reports/latest.json reports/latest.md notifications/latest-slack-message.json audit/latest-cleanup.json; do
  [ -f "$CCG_ARTIFACTS_DIR/$f" ] || { echo "missing artifact $f"; exit 1; }
done
echo "Smoke test passed."
