# Local development

## Prerequisites

* Python 3.10 or newer (3.12 recommended). Windows: install from python.org and tick "Add to PATH".
* Git.
* Optional: Docker Desktop, Terraform ≥ 1.5.

No AWS account is needed for anything in this document.

## Windows (PowerShell)

```powershell
git clone <YOUR_REPOSITORY_URL>
cd cloud-cost-guardian

# Option A — script
.\scripts\setup_local.ps1 -Dev

# Option B — manual
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

python -m cloud_cost_guardian.cli.main validate-config
python -m cloud_cost_guardian.cli.main scan --mode demo
python -m cloud_cost_guardian.cli.main cleanup --dry-run
pytest
.\scripts\validate.ps1        # full quality gate
.\scripts\smoke_test.ps1      # end-to-end demo lifecycle
```

If `Activate.ps1` is refused: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (once).

## Linux / macOS

```bash
./scripts/setup_local.sh --dev
source .venv/bin/activate
make demo dry-run test check
```

## Configuration

All settings are `CCG_*` environment variables (or a git-ignored `.env`). Copy `.env.example` to
start. `ccg validate-config` prints the effective configuration with secrets masked.

Frequently tuned:

| Variable | Default | Meaning |
|---|---|---|
| `CCG_EBS_MIN_AGE_DAYS` | 7 | unattached volumes younger than this are flagged but not eligible |
| `CCG_EC2_CPU_THRESHOLD_PERCENT` / `CCG_EC2_OBSERVATION_HOURS` / `CCG_EC2_MIN_SAMPLES` | 5 / 48 / 12 | EC2 evidence bar |
| `CCG_RDS_CPU_THRESHOLD_PERCENT` / `CCG_RDS_OBSERVATION_HOURS` / `CCG_RDS_MIN_SAMPLES` | 10 / 168 / 24 | RDS evidence bar |
| `CCG_SNAPSHOT_MAX_AGE_DAYS` | 90 | snapshot age threshold (also the cleanup min-age) |
| `CCG_PROTECTED_TAGS` | `cost-guardian-protected=true,Environment=production` | comma-separated `key=value`; `*` matches any value |
| `CCG_PRICING_CATALOG_PATH` | built-in | your own catalog JSON |
| `CCG_FIXTURE_INVENTORY_PATH` / `CCG_FIXTURE_METRICS_PATH` | packaged copies of `demo/*.json` | custom demo scenarios |
| `CCG_LOG_FORMAT` | `text` | `json` for machine-readable logs |

## Artifacts and state

```
artifacts/reports/latest.json, latest.md, <scan-id>.json
artifacts/notifications/latest-slack-message.json
artifacts/audit/cleanup-audit.jsonl, latest-cleanup.json
data/demo_state.json               # simulated remediations (ccg demo reset clears it)
```

Both directories are git-ignored.

## Editing the demo scenario

`demo/sample_aws_inventory.json` and `demo/sample_cloudwatch_metrics.json` are the source of truth.
Ages are relative (`age_days`) so the demo never goes stale. A copy lives in
`src/cloud_cost_guardian/demo/data/` so the installed wheel/Docker image is self-contained;
`tests/test_demo_and_config.py::test_repo_fixtures_match_packaged_fixtures` fails if they drift —
copy after editing. If you change the scenario, regenerate `demo/expected_report.json`:

```powershell
python - <<'PY'
import json, tempfile
from datetime import datetime, timezone
from pathlib import Path
from cloud_cost_guardian.app import Application
from cloud_cost_guardian.config import Settings, Mode
tmp = Path(tempfile.mkdtemp())
app = Application.build(Settings(mode=Mode.DEMO, artifacts_dir=tmp/"a", data_dir=tmp/"d", _env_file=None),
                        now=datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc))
r = app.scan_service(None).run(notify=False).report
status = lambda f: "protected" if f.protected else "cleanup" if f.cleanup_eligible else "recommendation"
Path("demo/expected_report.json").write_text(json.dumps({
  "_comment": "Expected demo-scan outcome; tests assert the live demo scan matches this exactly.",
  "summary": r.summary.model_dump(),
  "finding_status": {f.resource_id: status(f) for f in r.findings},
  "findings": [{"resource_id": f.resource_id, "category": f.category.value, "severity": f.severity.value,
                "estimated_monthly_cost": f.estimated_monthly_cost, "estimated_monthly_savings": f.estimated_monthly_savings,
                "recommended_action": f.recommended_action.value, "reason": f.reason} for f in r.findings]}, indent=2) + "\n")
PY
```

## Optional: LocalStack / moto server (`--mode local`)

```powershell
pip install "moto[server]"
moto_server -p 4566            # or: docker run --rm -p 4566:4566 localstack/localstack
$env:CCG_AWS_ENDPOINT_URL = "http://localhost:4566"
$env:AWS_ACCESS_KEY_ID = "test"; $env:AWS_SECRET_ACCESS_KEY = "test"
python -m cloud_cost_guardian.cli.main scan --mode local
```

This is optional; the in-process moto tests already exercise the AWS code path.

## Project conventions

* `ruff format` decides formatting; line length 100.
* `mypy --strict` must pass; prefer precise types over `Any`.
* Every new behaviour ships with a test; every new safety rule ships with a *negative* test.
* Docstrings explain *why*; names explain *what*.
