# Cleanup safety

Automated deletion is where cost tools become incident generators. This document describes every
gate between "the scanner found something" and "something was deleted", and which test proves it.

## Principles

1. **Default is dry-run.** `ccg cleanup` with no arguments never calls an executor.
2. **One resource per approval.** There is no "approve all". The approval must carry the exact resource ID.
3. **Protection wins over everything** and is evaluated three times: at detection, at cleanup entry
   (against the tags stored in the finding), and after re-fetching the live resource.
4. **Trust nothing from the report.** A finding in `latest.json` is a *claim*; the live resource is
   re-fetched and the detector is re-run on it. If the finding does not reproduce, nothing happens.
5. **RDS is never remediated.** There is no code path, IAM permission, action enum member or
   executor branch that can modify a database. The `Finding` model rejects an eligible RDS finding at construction.
6. **Every attempt is audited**, including blocked ones and dry-runs.
7. **Real-mode destruction needs a second, explicit flag** (`--i-understand-this-deletes-real-resources`)
   in addition to approval, and a separate IAM policy.

## The pipeline

```
finding (from latest report)
   │
   ├─ 1. protection gate      ProtectionPolicy.evaluate(finding.metadata.tags) or finding.protected
   │        └─ BLOCKED  → audit(status=blocked, stage=protection)
   ├─ 2. policy gate          CleanupPolicy.evaluate(finding) and finding.cleanup_eligible
   │        └─ BLOCKED  → audit(stage=policy)          (RDS, review-only, too young, missing age)
   ├─ 3. approval gate        ApprovalProvider.request(finding) — exact resource id required
   │        └─ BLOCKED  → audit(stage=approval)        (no AWS call has been made yet)
   ├─ 4. re-fetch             source.refetch(type, id)
   │        ├─ error    → BLOCKED (stage=verification)
   │        └─ missing  → BLOCKED "resource no longer exists"
   ├─ 5. re-detect            run the same detector on the fresh single-resource inventory
   │        ├─ no finding            → BLOCKED "state changed since scan"
   │        ├─ now protected         → BLOCKED
   │        ├─ no longer eligible    → BLOCKED
   │        └─ action changed        → BLOCKED
   ├─ 6. execute              executor.execute(fresh_finding)   ← the only destructive call site
   │        └─ failure  → audit(status=failed, error=...)
   ├─ 7. audit                AuditRecord with all gate results
   └─ 8. post-verify          refetch again; "no longer present" / "finding no longer reproduces" / WARNING
```

Dry-run runs gates 1 and 2 only, writes an audit record with `dry_run=true`, and returns.

## Proof by test (`tests/test_cleanup_safety.py`)

| Scenario | Test | Blocked at |
|---|---|---|
| Protected resource | `test_protected_resource_blocked` | protection |
| Finding with `protected=False` but protected tags in metadata | `test_forged_finding_with_protected_tags_still_blocked` | protection |
| Volume younger than `ebs_min_age_days` | `test_not_old_enough_blocked` | policy |
| `cleanup_eligible` flipped to false | `test_not_policy_eligible_blocked` | policy |
| RDS finding | `test_rds_finding_never_reaches_executor` | policy |
| Approval denied | `test_approval_denied_blocked` | approval (0 AWS calls) |
| Approval for a different resource id | `test_approval_for_wrong_resource_id_is_denied` | approval |
| Interactive prompt: "yes", empty, EOF | `test_interactive_approval_requires_exact_id` | approval |
| Volume attached between scan and cleanup | `test_resource_changed_between_scan_and_cleanup_blocked` | verification |
| Resource tagged protected after scan | `test_resource_became_protected_after_scan_blocked` | verification |
| Resource already gone | `test_resource_disappeared_blocked` | verification |
| API failure on re-fetch | `test_refetch_api_failure_blocked` | verification |
| Executor raises | `test_executor_failure_is_recorded` | execution (status failed, error audited) |
| No executor for mode | `test_no_executor_blocks_after_all_gates` | execution |
| Dry-run | `test_dry_run_never_executes` | — (executor never called) |
| Different protected-tag config | `test_protection_policy_used_by_service_is_the_shared_one` | protection |

The same is proven against a simulated AWS account in `tests/integration/test_moto_aws.py`
(`test_aws_cleanup_without_destructive_flag_is_blocked`, `test_resource_changed_after_scan_in_aws`,
`test_aws_cleanup_with_explicit_destructive_flag_deletes_and_verifies`).

## What the CLI shows before acting

```
Cleanup candidate:
  Resource:               vol-0a1b2c3d4e5f60001
  Type:                   ebs_volume
  Region:                 us-east-1
  Age:                    93.0 days
  Estimated monthly cost: $10.00
  Protected:              NO
  Policy eligible:        YES
  Action:                 delete_volume
```

Then, without `--approve`, the operator must type the exact resource ID.

## Audit record

`artifacts/audit/cleanup-audit.jsonl` (append-only) and `artifacts/audit/latest-cleanup.json`:

```
timestamp, scan_id, finding_id, resource_id, resource_type, region, requested_action, mode, dry_run,
approval_result, policy_result, protection_result, verification_result, action_result, error, metadata{status, stage, post_verification}
```

No secrets are ever written; the record contains IDs and gate verdicts only.

## Things this tool deliberately does not have

* A "delete everything eligible" command.
* Termination of EC2 instances (EC2 findings are review-only; `STOP_INSTANCE` exists in the enum for
  future opt-in use but no detector emits it and no CLI path triggers it).
* Any RDS modification.
* A way to skip the re-fetch/re-detect step.
