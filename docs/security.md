# Security

## Threat model (what we defend against)

* Accidental deletion of production resources by the tool.
* Leakage of credentials or webhook URLs through logs, reports, error messages, images or git history.
* Supply-chain vulnerabilities in dependencies or the container base image.
* Over-privileged IAM that would turn a scanner compromise into an account compromise.

## Secrets

| Control | Where |
|---|---|
| No secrets in source, tests, fixtures, Terraform, scripts, `.env.example` | verified before packaging with grep for `AKIA`, `hooks.slack.com/services`, `password=` |
| `.env`, `*.tfstate`, `*.tfvars`, `*.pem`, `*.key` git-ignored | `.gitignore` |
| Slack webhook typed as `pydantic.SecretStr`; `repr`, `summary()` and JSON dumps mask it | `config.py`, `test_settings_summary_masks_webhook` |
| Log formatter redacts webhook URLs, AWS access key IDs, `secret=…`, `password=…`, `token=…` | `logging_config.redact`, `test_secret_redaction` |
| Slack provider validates the URL prefix and never includes the URL in exceptions | `notifications/slack.py`, `test_slack_success_and_failure` |
| CLI wraps all errors in `redact()` | `cli/main.py::main`, `test_cli_hides_slack_webhook_in_errors` |
| Docker image has no `.env`, `.git`, credentials; `.dockerignore` enforces | `.dockerignore` |
| Terraform: no secret variables; Slack webhook (if ever used) documented as out-of-band SSM SecureString | `terraform/secrets.tf` |
| GitHub Actions deploy uses OIDC (no stored AWS keys) | `.github/workflows/deploy.yml` |
| gitleaks scans full history on every push | `.github/workflows/security.yml` |

## IAM (least privilege)

Two separate policies in `terraform/iam.tf`; the Lambda only ever gets the first:

* **scan-readonly**: `ec2:DescribeVolumes/Instances/Addresses/Snapshots`, `rds:DescribeDBInstances`,
  `cloudwatch:GetMetricStatistics`, `sns:Publish` (own topic only),
  `logs:CreateLogStream/PutLogEvents` (own log group only).
* **remediation** (opt-in, MFA-required assume): `ec2:DeleteVolume`, `ec2:ReleaseAddress`,
  `ec2:DeleteSnapshot`, each with a condition `aws:ResourceTag/cost-guardian-protected ≠ true`,
  so protected resources are protected by IAM even if the application were bypassed.
  No `rds:*`, no `ec2:TerminateInstances`, no `*:*`.

Rationale per permission: [aws-permissions.md](aws-permissions.md).

## Input validation

* All configuration is validated by pydantic (ranges, enums, URL schemes, cross-field rules).
* All resources, findings and reports are validated models; the `Finding` validator enforces the
  safety invariants at construction time.
* Fixture and report files are parsed defensively; malformed JSON becomes a typed error with a clear message.
* CLI `--resource` must match a finding in the latest report exactly; no wildcards, no prefixes.
* Paths: artifacts and data dirs come from config and are created with `mkdir(parents=True)`; no
  user-controlled path segments are joined into them (resource IDs are used only in filenames
  generated from scan IDs, which are tool-generated).

## Cleanup

Covered in depth in [cleanup-safety.md](cleanup-safety.md).

## Dependencies

* Runtime: `boto3`, `pydantic`, `pydantic-settings` only. Version-constrained in `pyproject.toml`.
* `pip-audit` runs in CI and locally via `scripts/validate.*`. Result at packaging time:
  **no known vulnerabilities** in a clean virtual environment.
* Semgrep (`p/python`, `p/secrets`, `p/dockerfile`) and ruff's Bandit-derived `S` rules run in CI.

## Docker

* Multi-stage: build tooling never reaches the runtime image.
* Runs as `ccg` (UID 10001); CI asserts `id -u != 0`.
* Compose: `read_only: true`, `cap_drop: ALL`, `no-new-privileges`, tmpfs `/tmp`.
* Trivy scans the image in CI for HIGH/CRITICAL fixable CVEs.

## Terraform

* No state committed; local state by default; `.gitignore` covers `*.tfstate*`, `.terraform/`, `*.tfvars`.
* Checkov runs in CI. Skipped checks and why (each adds cost/complexity out of scope for an
  optional educational deployment): `CKV_AWS_50` (X-Ray), `CKV_AWS_115` (reserved concurrency),
  `CKV_AWS_116` (DLQ), `CKV_AWS_117` (VPC), `CKV_AWS_173` (env-var KMS), `CKV_AWS_272` (code signing),
  `CKV_AWS_26` (SNS KMS), `CKV_AWS_158` (log group KMS), `CKV_AWS_338` (1-year log retention).

## Logs and notifications

* Structured logs contain IDs, counts and verdicts; never tag values that might be sensitive
  beyond the protection tag, never credentials.
* Notification payloads contain the same data as the Markdown report; the mock provider writes them locally.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
