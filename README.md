# Cloud Cost Guardian

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![Security](https://img.shields.io/badge/security-pip--audit_·_semgrep_·_trivy_·_gitleaks_·_checkov-success)](.github/workflows/security.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue?logo=python&logoColor=white)](pyproject.toml)
[![Type checked](https://img.shields.io/badge/mypy-strict-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Cost](https://img.shields.io/badge/required_cost-%240_%2F_%E2%82%B90-brightgreen)](docs/cost-safety.md)

**Find wasteful AWS resources, estimate what they cost, and remediate them only through an
approval-gated, audited, re-verified workflow — all runnable on a laptop with no AWS account.**

```powershell
python -m cloud_cost_guardian.cli.main scan --mode demo      # no credentials, no cloud, no cost
```

---

## The problem

Cloud accounts silently accumulate resources nobody owns anymore: EBS volumes left behind by
terminated instances, Elastic IPs that were "temporarily" detached, snapshots from a migration
two years ago, an `m5.2xlarge` that averages 1.8 % CPU, a reporting database three sizes too big.
Each one is small; together they are a recurring line on the bill and an operational liability.

Most "cleanup scripts" that address this are dangerous: they list resources and delete them in the
same breath, with no notion of protection, evidence, approval or audit.

## The solution

Cloud Cost Guardian separates *detection* from *remediation* and puts a wall of safety checks
between them:

```
Detect → Analyze → Estimate cost → Findings → Report → Notify
                                                          ↓
                       Re-scan ← Verify ← Remediate ← Re-verify ← Human approval ← Dry run
```

* **Five detectors** — unattached EBS, potentially underutilized EC2, unassociated EIP,
  RDS right-sizing, old snapshots — each backed by evidence, not guesses.
* **A policy engine** decides what is a finding, what is protected, and what may ever be cleaned.
* **Tag-based protection** (`cost-guardian-protected=true`, `Environment=production`, configurable)
  is enforced in one place and tested exhaustively.
* **RDS is recommendation-only.** The code has no path that deletes a database.
* **Remediation is per-resource, approval-gated, re-fetched and re-verified** immediately before
  acting, and every attempt — blocked or successful — is written to an audit log.
* **Demo mode** runs the whole lifecycle, including simulated cleanup and re-scan, from fixtures.

## Features

| Area | What you get |
|---|---|
| Detection | EBS, EC2 (CloudWatch CPU), EIP, RDS (CloudWatch CPU), EBS snapshots |
| Cost | Local, editable reference pricing catalog; monthly / annual / savings estimates; explicit disclaimer |
| Policy | Configurable thresholds, min-age gates, protection tags, cleanup eligibility, RDS never remediable |
| Reports | JSON (machine), Markdown (human), Slack Block Kit payload |
| Notifications | `mock` (writes a local file — default), `slack` (webhook), `sns` |
| Remediation | Dry-run by default, exact resource-ID approval, refetch + re-detect gate, audit JSONL, post-verify |
| Modes | `demo` (fixtures, zero AWS), `local` (LocalStack / moto server endpoint), `aws` (read-only boto3) |
| Resilience | Pagination, adaptive retries, timeouts, typed error translation, partial-failure scans |
| Observability | Structured text/JSON logs with a scan ID on every line and secret redaction |
| Packaging | `pip`, Docker (non-root, wheel-based, read-only FS in compose), optional Lambda zip |
| IaC | Optional Terraform: Lambda + EventBridge + SNS + least-privilege IAM (scan role ≠ remediation role) |
| Quality | 149 tests (unit + moto integration), ruff, mypy `--strict`, pip-audit, semgrep, trivy, gitleaks, checkov |

## Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                 cloud_cost_guardian                     │
                    │                                                         │
 CLI (ccg)  ───────▶│  app.Application (composition root)                     │
                    │       │                                                 │
                    │       ▼                                                 │
   ┌──────────┐     │  sources.InventorySource ◀──┬── demo.FixtureInventory   │  ← demo mode
   │ fixtures │────▶│                             └── aws.AWSInventorySource  │  ← local / aws
   └──────────┘     │       │  (pagination, retries, typed errors)            │
   ┌──────────┐     │       ▼                                                 │
   │ AWS API  │────▶│  models.Inventory (validated, immutable)                │
   └──────────┘     │       │                                                 │
                    │       ▼                                                 │
                    │  detectors.* ──▶ policies.Protection ──▶ pricing.Estimator
                    │       │          policies.CleanupPolicy                 │
                    │       ▼                                                 │
                    │  models.Finding (validated: protected ⇒ ¬eligible, ...) │
                    │       │                                                 │
                    │       ├──▶ reporting.ReportBuilder ──▶ JSON / Markdown  │──▶ artifacts/reports/
                    │       └──▶ notifications.* ──────────▶ mock/slack/sns   │──▶ artifacts/notifications/
                    │                                                         │
                    │  remediation.CleanupService                             │
                    │    protection → policy → approval → refetch → re-detect │
                    │    → executor (demo-sim | aws) → audit → verify         │──▶ artifacts/audit/
                    └─────────────────────────────────────────────────────────┘
```

Detailed walk-through: [docs/architecture.md](docs/architecture.md).

## Technology stack (and why)

| Technology | Purpose |
|---|---|
| Python 3.10+ | Ubiquitous in cloud tooling; boto3 is the canonical AWS SDK |
| boto3 / botocore | AWS integration with built-in adaptive retries and pagination |
| pydantic v2 + pydantic-settings | Strong validation of resources, findings, reports and configuration |
| argparse | Zero-dependency, dependable CLI |
| pytest + moto | Fast unit tests plus in-process AWS simulation — no network, no cost |
| ruff, mypy `--strict` | Lint, format, security rules (Bandit set) and full static typing |
| pip-audit, semgrep, trivy, gitleaks, checkov | Free dependency, SAST, container, secret and IaC scanning |
| Docker | Reproducible, non-root runtime |
| Terraform | Declarative, reviewable definition of the *optional* AWS deployment |
| GitHub Actions | Free CI for public repositories |

Nothing else. No web framework, no database server, no message queue — none are needed.

## Zero-cost guarantee

| Component | Runs where | Cost |
|---|---|---|
| Demo scan, reports, notifications, dry-run, simulated cleanup, re-scan | Your machine | **$0** |
| Test suite incl. AWS integration tests (moto) | Your machine / GitHub Actions (public repo) | **$0** |
| Docker image | Your machine | **$0** |
| `scan --mode aws` (read-only Describe/GetMetricStatistics) | Your AWS account | $0 for the API calls themselves*; requires an account |
| Terraform deployment (Lambda + EventBridge + SNS) | Your AWS account | **Optional. May incur charges. Not part of the required project.** |

\*Describe/Get calls are not billed, but you need an AWS account and CloudWatch has request
quotas. See [docs/cost-safety.md](docs/cost-safety.md) for exactly what *not* to do if you want a
guaranteed ₹0 / $0 bill.

## Demo mode (start here)

```powershell
git clone <YOUR_REPOSITORY_URL>
cd cloud-cost-guardian

python -m venv .venv
.venv\Scripts\Activate.ps1                     # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python -m cloud_cost_guardian.cli.main validate-config
python -m cloud_cost_guardian.cli.main scan --mode demo
python -m cloud_cost_guardian.cli.main report --format markdown
python -m cloud_cost_guardian.cli.main cleanup --dry-run
python -m cloud_cost_guardian.cli.main cleanup --resource vol-0a1b2c3d4e5f60001 --approve
python -m cloud_cost_guardian.cli.main scan --mode demo        # finding is gone
python -m cloud_cost_guardian.cli.main demo reset               # start over
```

`ccg` is installed as a console script too, so `ccg scan --mode demo` works once the venv is active.

Or let the script do it: `.\scripts\setup_local.ps1 -Dev` (Windows) / `./scripts/setup_local.sh --dev`.

### The demo scenario

The fixture set in [`demo/sample_aws_inventory.json`](demo/sample_aws_inventory.json) models a
company that has accumulated 29 resources. The scan finds:

```
Resources scanned:  29
Findings:           18

Estimated monthly waste:     $858.16
Estimated annualized waste:  $10,297.92
Estimated monthly savings:   $481.48
Estimated annualized savings: $5,777.76

By category:                By severity:
  old_snapshot         4      high     3
  rds_rightsizing      3      medium   8
  unassociated_eip     2      low      7
  unattached_ebs       6
  underutilized_ec2    3

Protected findings:  6
Cleanup eligible:    7
Recommendation only: 5
```

Every number above comes from the fixtures and the built-in pricing catalog; the test
`tests/test_demo_and_config.py::test_demo_scan_matches_expected_report` pins them against
[`demo/expected_report.json`](demo/expected_report.json). Edge cases covered: attached volume,
2-day-old unattached volume (flagged, not eligible), stopped instance, instance with no metrics,
instance with only 6 h of metrics, `Environment=Production` matched case-insensitively, pending
snapshot, RDS with no metrics.

Full walk-through with expected output for each step: [docs/demo-scenario.md](docs/demo-scenario.md).

## Local installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt        # runtime + test/lint tooling
pytest                                     # 149 tests, ~15 s
.\scripts\validate.ps1                     # ruff + mypy + pytest + pip-audit
```

Configuration is via `CCG_*` environment variables or a local `.env` (copy `.env.example`; `.env`
is git-ignored). See [docs/local-development.md](docs/local-development.md).

## Docker

```powershell
docker build -t cloud-cost-guardian .
docker run --rm cloud-cost-guardian scan --mode demo
docker run --rm -v ${PWD}/artifacts:/app/artifacts -v ${PWD}/data:/app/data cloud-cost-guardian cleanup --dry-run
docker compose up --build                  # same demo scan, artifacts in ./artifacts
docker compose run --rm ccg cleanup --resource vol-0a1b2c3d4e5f60001 --approve
docker compose down
```

The image is built from a wheel in a multi-stage build, runs as UID 10001, contains no secrets,
and compose mounts the root filesystem read-only with all capabilities dropped.

## Optional AWS read-only mode

```powershell
# use any standard credential source: profile, SSO, env vars, instance role
$env:AWS_PROFILE = "readonly"
python -m cloud_cost_guardian.cli.main scan --mode aws --region ap-south-1
```

The scanner only calls `ec2:Describe*`, `rds:DescribeDBInstances` and `cloudwatch:GetMetricStatistics`. The minimal
IAM policy is in [docs/aws-permissions.md](docs/aws-permissions.md). Destructive actions in AWS mode
additionally require `--i-understand-this-deletes-real-resources`, a separate IAM policy, and the
same approval + re-verification gates as demo mode.

`--mode local` points boto3 at `CCG_AWS_ENDPOINT_URL` (LocalStack Community or `moto_server`) —
useful, but not required; the in-process moto tests already cover the AWS code path.

## Terraform (optional)

`terraform/` defines a weekly, read-only scanner Lambda with EventBridge, SNS and two *separate*
IAM policies (scan vs. remediation, the latter MFA-gated and never attached to the Lambda).

```powershell
cd terraform
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan        # review carefully
terraform apply       # creates real AWS resources — optional, may cost money
terraform destroy     # when finished
```

Nothing in CI applies Terraform automatically; `deploy.yml` is manual-only, OIDC-authenticated and
requires typed confirmation. See [docs/deployment.md](docs/deployment.md).

## Security

* No secrets in the repo, image, logs, reports or error messages (webhook URLs are `SecretStr`,
  redacted by the log formatter, and validated to be `https://hooks.slack.com/`).
* Least-privilege IAM, split into scan and remediation policies; remediation denies protected tags
  at the IAM layer as well.
* Cleanup: dry-run default → exact-ID approval → refetch → re-detect → execute → audit → verify.
  Fourteen negative-path tests prove protected / too-young / ineligible / denied / drifted resources
  are all blocked before any executor is called.
* Dependencies audited (`pip-audit`), code scanned (ruff S-rules, semgrep), image scanned (trivy),
  IaC scanned (checkov), history scanned (gitleaks).

Details: [docs/security.md](docs/security.md) · [docs/cleanup-safety.md](docs/cleanup-safety.md) · [SECURITY.md](SECURITY.md)

## Testing

```powershell
pytest                              # everything
pytest -m "not integration"         # unit only
pytest -m integration               # moto-backed AWS simulation
pytest --cov --cov-report=html      # coverage report in htmlcov/
```

149 tests, 91 % line coverage. What is covered, by area: [docs/testing.md](docs/testing.md).

## CI/CD

`ci.yml` on every push/PR: install → ruff lint → ruff format → mypy strict → unit tests → moto
integration tests → PowerShell/bash smoke tests (Windows + Ubuntu × Python 3.10/3.12) → terraform
fmt/validate → docker build → containerised demo + dry-run + non-root check.

`security.yml` on push/PR/weekly: pip-audit → ruff security rules → semgrep → gitleaks → trivy →
checkov.

`deploy.yml`: manual only, OIDC, typed confirmation; never runs on push.

## Example output

<details><summary><code>ccg scan --mode demo</code> (click to expand)</summary>

```text
CLOUD COST GUARDIAN
============================================================
Scan ID:            scan-20260923T081818Z-46377d
Mode / region:      demo / us-east-1
Resources scanned:  29
Findings:           18

Estimated monthly waste:     $858.16
Estimated annualized waste:  $10,297.92
Estimated monthly savings:   $481.48
Estimated annualized savings: $5,777.76

STATUS             SEV    CATEGORY           RESOURCE                      MONTHLY    SAVINGS
--------------------------------------------------------------------------------------------
RECOMMENDATION     high   underutilized_ec2  i-0f1e2d3c4b5a60002           $280.32    $140.16
RECOMMENDATION     high   rds_rightsizing    reporting-db                  $249.66    $124.83
RECOMMENDATION     high   underutilized_ec2  i-0f1e2d3c4b5a60004           $124.10     $62.05
RECOMMENDATION     medium rds_rightsizing    legacy-crm-db                  $99.28     $49.64
CLEANUP-ELIGIBLE   medium unattached_ebs     vol-0a1b2c3d4e5f60002          $40.00     $40.00
CLEANUP-ELIGIBLE   medium old_snapshot       snap-0c1d2e3f4a5b60002         $25.00     $25.00
PROTECTED          medium rds_rightsizing    audit-archive-db               $49.64     $24.82
PROTECTED          medium underutilized_ec2  i-0f1e2d3c4b5a60006            $91.98     $21.90
CLEANUP-ELIGIBLE   medium old_snapshot       snap-0c1d2e3f4a5b60003         $12.50     $12.50
PROTECTED          medium old_snapshot       snap-0c1d2e3f4a5b60005         $10.00     $10.00
CLEANUP-ELIGIBLE   medium unattached_ebs     vol-0a1b2c3d4e5f60001          $10.00     $10.00
PROTECTED          low    unattached_ebs     vol-0a1b2c3d4e5f60005           $6.40      $6.40
CLEANUP-ELIGIBLE   low    unattached_ebs     vol-0a1b2c3d4e5f60003           $6.25      $6.25
CLEANUP-ELIGIBLE   low    old_snapshot       snap-0c1d2e3f4a5b60001          $5.00      $5.00
CLEANUP-ELIGIBLE   low    unassociated_eip   eipalloc-0aa000000000000a2      $3.65      $3.65
PROTECTED          low    unassociated_eip   eipalloc-0aa000000000000a3      $3.65      $3.65
RECOMMENDATION     low    unattached_ebs     vol-0a1b2c3d4e5f60006           $2.40      $2.40
PROTECTED          low    unattached_ebs     vol-0a1b2c3d4e5f60007           $0.60      $0.60

Pricing: ccg-reference-2026-01 — estimates only, not billing data.
JSON report:     artifacts/reports/latest.json
Markdown report: artifacts/reports/latest.md
Notification:    mock sent — written to artifacts/notifications/latest-slack-message.json
```
</details>

<details><summary><code>ccg cleanup --resource vol-0a1b2c3d4e5f60005 --approve</code> (protected → blocked, exit 3)</summary>

```text
Cleanup candidate:
  Resource:               vol-0a1b2c3d4e5f60005
  Type:                   ebs_volume
  Region:                 us-east-1
  Age:                    120.0 days
  Estimated monthly cost: $6.40
  Protected:              YES
  Policy eligible:        NO
  Action:                 delete_volume

Result: BLOCKED at stage 'protection' — BLOCKED: tag cost-guardian-protected=true matches protection rule
Audit:  artifacts/audit/latest-cleanup.json
```
</details>

<details><summary>Audit record after an approved simulated remediation</summary>

```json
{
  "scan_id": "scan-20260923T080308Z-5044eb",
  "resource_id": "vol-0a1b2c3d4e5f60001",
  "resource_type": "ebs_volume",
  "requested_action": "delete_volume",
  "mode": "demo",
  "dry_run": false,
  "approval_result": "approved by cli-flag: explicit approval for vol-0a1b2c3d4e5f60001",
  "policy_result": "passed",
  "protection_result": "passed",
  "verification_result": "passed: resource re-fetched and finding reproduced",
  "action_result": "executed via demo-simulation: simulated delete_volume recorded in data/demo_state.json",
  "error": null,
  "metadata": { "status": "remediated", "stage": "verify-after", "post_verification": "verified: resource no longer present" }
}
```
</details>

Screenshots are intentionally omitted: the tool is CLI-first and the exact text output above is
reproducible on any machine.

## Cost estimation limitations

Prices come from [`src/cloud_cost_guardian/pricing/data/default_catalog.json`](src/cloud_cost_guardian/pricing/data/default_catalog.json),
a hand-maintained table of on-demand list prices, region-overridable and swappable via
`CCG_PRICING_CATALOG_PATH`. They are **reference estimates**, not billing data:

* Reserved Instances, Savings Plans, free tier and enterprise discounts are not modelled.
* Snapshot cost assumes full volume size (an upper bound; real snapshots are incremental).
* Low CPU is *evidence of possible* underutilization; memory, IO and network are not evaluated.
* RDS right-sizing savings assume the next-smaller class in the catalog's downsize map.

Every report embeds these limitations and the catalog name.

## Roadmap

Genuinely not implemented yet — see [docs/contribution-guide.md](docs/contribution-guide.md) for how to pick one up:

* Additional detectors: idle load balancers, unused NAT gateways, orphaned ENIs, empty S3 buckets
* Memory-aware EC2/RDS analysis via CloudWatch agent metrics
* Multi-region scanning in one run
* Azure / GCP inventory sources behind the same `InventorySource` interface
* AWS Price List API–backed pricing provider (still free, but network-dependent)
* SQLite scan history and trend reporting
* Small local read-only dashboard over `artifacts/reports/*.json`
* Additional notification providers (Teams, e-mail via SMTP)
* Multilingual Markdown reports
* Tag-coverage analytics (which teams own the waste)

## Contributing

Issues and pull requests are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security issues: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
