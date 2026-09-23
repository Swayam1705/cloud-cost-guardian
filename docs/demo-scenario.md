# Demo scenario walk-through

**Scenario.** A mid-size company's `us-east-1` account has accumulated, over two years:

* 7 EBS volumes (3 forgotten, 1 attached, 1 forensics hold, 1 created two days ago, 1 tagged `Environment=Production`)
* 8 EC2 instances (1 busy API server, 2 idle batch/ML boxes, 1 staging box, 1 stopped dev box,
  1 protected cache node, 1 with no CloudWatch data, 1 launched three days ago)
* 3 Elastic IPs (1 in use, 1 from a decommissioned bastion, 1 reserved for DNS and protected)
* 5 RDS instances (1 oversized reporting DB, 1 busy orders DB, 1 legacy CRM DB, 1 protected audit archive, 1 brand-new with no metrics)
* 6 snapshots (3 old, 1 nightly, 1 compliance-protected, 1 still pending)

All of this is `demo/sample_aws_inventory.json` + `demo/sample_cloudwatch_metrics.json`.

## Step 1 — scan

```powershell
python -m cloud_cost_guardian.cli.main scan --mode demo
```

```
Resources scanned:  29        Findings: 18
Estimated monthly waste:     $858.16      Estimated annualized waste:  $10,297.92
Estimated monthly savings:   $481.48      Estimated annualized savings: $5,777.76
Protected findings: 6   Cleanup eligible: 7   Recommendation only: 5
```

Why 18 findings from 29 resources, and why only 7 are eligible:

| Resource | Outcome | Reason |
|---|---|---|
| `vol-…60001` (100 GiB gp2, 93 d) | **cleanup-eligible** | unattached, older than 7 d |
| `vol-…60002` (500 GiB gp3, 210 d) | **cleanup-eligible** | unattached |
| `vol-…60003` (50 GiB io1, 45 d, no tags) | **cleanup-eligible** | unattached, missing metadata is fine |
| `vol-…60004` | not a finding | attached to `i-…60001` |
| `vol-…60005` | protected | `cost-guardian-protected=true` |
| `vol-…60006` (2 d) | recommendation | unattached but younger than 7 d — flagged, not eligible |
| `vol-…60007` | protected | `Environment=Production` matches `Environment=production` case-insensitively |
| `i-…60001` (42.5 % CPU) | not a finding | busy |
| `i-…60002` (m5.2xlarge, 1.8 % over 168 h) | recommendation (high) | review right-sizing; never auto-stopped |
| `i-…60003` (23 % CPU) | not a finding | busy |
| `i-…60004` (c5.xlarge, 3.2 % over 96 h) | recommendation (high) | |
| `i-…60005` | not a finding | stopped — no compute charge |
| `i-…60006` (0.9 %) | protected | protected tag |
| `i-…60007` | not a finding | no metrics → insufficient evidence |
| `i-…60008` (6 h of data) | not a finding | below 48 h observation window |
| `eipalloc-…a1` | not a finding | associated |
| `eipalloc-…a2` | **cleanup-eligible** | unassociated |
| `eipalloc-…a3` | protected | protected tag |
| `reporting-db` (db.m5.xlarge, 4.1 %) | recommendation | suggested `db.m5.large` |
| `orders-db` (38.7 %) | not a finding | busy |
| `legacy-crm-db` (db.t3.large, 2.4 %) | recommendation | suggested `db.t3.medium` |
| `audit-archive-db` | protected | |
| `metrics-less-db` | not a finding | no metrics |
| `snap-…60001` (400 d) | **cleanup-eligible** | older than 90 d |
| `snap-…60002` (120 d) | **cleanup-eligible** | |
| `snap-…60003` (95 d, orphaned) | **cleanup-eligible** | |
| `snap-…60004` (3 d) | not a finding | recent |
| `snap-…60005` (730 d) | protected | compliance retention |
| `snap-…60006` | not a finding | state `pending` |

Protected findings are listed but excluded from the waste totals — they cannot be acted on.

## Step 2 — read the report

```powershell
python -m cloud_cost_guardian.cli.main report --format markdown
Get-Content artifacts\reports\latest.json | Select-Object -First 40
Get-Content artifacts\notifications\latest-slack-message.json
```

## Step 3 — dry run

```powershell
python -m cloud_cost_guardian.cli.main cleanup --dry-run
```

```
7 candidate(s) would be remediated after explicit approval.
11 finding(s) blocked:
  - i-0f1e2d3c4b5a60002        [policy] BLOCKED: category underutilized_ec2 is review-only; ...
  - reporting-db               [policy] BLOCKED: RDS is recommendation-only; automated cleanup is never permitted; ...
  - vol-0a1b2c3d4e5f60005      [protection] BLOCKED: tag cost-guardian-protected=true matches protection rule
  - vol-0a1b2c3d4e5f60006      [policy] BLOCKED: resource age 2.0d is below minimum 7d
  - vol-0a1b2c3d4e5f60007      [protection] BLOCKED: tag environment=Production matches protection rule
  ...
```

## Step 4 — try to remediate a protected resource (blocked)

```powershell
python -m cloud_cost_guardian.cli.main cleanup --resource vol-0a1b2c3d4e5f60005 --approve
# Result: BLOCKED at stage 'protection' ...      exit code 3
```

## Step 5 — approve one real candidate

```powershell
python -m cloud_cost_guardian.cli.main cleanup --resource vol-0a1b2c3d4e5f60001 --approve
# Result: REMEDIATED at stage 'verify-after' — verified: resource no longer present
```

Or omit `--approve` and type the resource ID when prompted. The audit record is at
`artifacts/audit/latest-cleanup.json`; the simulated state is at `data/demo_state.json`.

## Step 6 — re-scan

```powershell
python -m cloud_cost_guardian.cli.main scan --mode demo
# Findings: 17   Cleanup eligible: 6
python -m cloud_cost_guardian.cli.main demo status
```

## Step 7 — reset

```powershell
python -m cloud_cost_guardian.cli.main demo reset
```

The whole sequence is automated in `scripts/smoke_test.ps1` / `.sh` and in
`tests/test_cli.py::test_full_demo_lifecycle`.
