# Contribution guide

Thanks for considering a contribution. This project aims to stay small, safe and free.

## Ground rules

1. **Zero-cost stays zero-cost.** No new required service, API key or paid dependency.
2. **Safety first.** Anything that can delete must go through `CleanupService`, be covered by
   `CleanupPolicy`, respect `ProtectionPolicy`, and ship with negative tests.
3. **RDS stays recommendation-only.**
4. Quality gate must be green: `ruff check`, `ruff format --check`, `mypy`, `pytest`, `pip-audit`.

## Workflow

```powershell
git checkout -b feat/<short-name>
.\scripts\setup_local.ps1 -Dev
# ... make changes, add tests ...
.\scripts\validate.ps1
git commit -m "feat: <what and why>"
git push -u origin feat/<short-name>
```

Open a PR. Describe *why*, link an issue if there is one, and paste the relevant test output.
Conventional commit prefixes (`feat`, `fix`, `docs`, `test`, `refactor`, `chore`) are appreciated.

## Good first contributions

| Idea | Where to start | Difficulty |
|---|---|---|
| New detector: unused NAT gateways / idle ALBs / orphaned ENIs | copy `eip_detector.py`; add fixtures + tests | medium |
| Multi-region scan (`--region all`) | `app.py` + `AWSInventorySource` | medium |
| Azure or GCP inventory source | implement `sources.InventorySource` | hard |
| AWS Price List API pricing provider (free but online) | implement `pricing.PricingProvider` | medium |
| SQLite scan history + `ccg history` | new `storage/` module | medium |
| Microsoft Teams / SMTP notification provider | implement `NotificationProvider` | easy |
| Local read-only HTML dashboard over `artifacts/reports/*.json` | stdlib `http.server`, no framework | medium |
| Multilingual Markdown report | `reporting/markdown_report.py` string tables | easy |
| Tag-coverage analytics (waste by `Team`) | `ReportBuilder` | easy |
| More policy rules (e.g. min size, name patterns) | `policies/cleanup_policy.py` | easy |
| Property-based tests for models | `hypothesis` (dev-only dependency) | medium |
| Terraform module per region | `terraform/modules/` | medium |

## Adding a detector — checklist

- [ ] `Category` member in `models/findings.py`
- [ ] Resource model (if new) in `models/resources.py`
- [ ] Fixture loader support + fixture entries (positive, negative, protected, edge)
- [ ] AWS service module with pagination and typed errors
- [ ] Detector class registered in `ALL_DETECTORS`
- [ ] Pricing entries in the catalog
- [ ] Threshold settings in `config.py` / `Thresholds`
- [ ] If remediable: `DESTRUCTIVE_ACTIONS`, `REMEDIABLE_CATEGORIES`, executor branch, IAM statement, **negative tests**
- [ ] Update `demo/expected_report.json` and docs

## Reporting bugs

Open an issue with: command, expected vs. actual, `ccg validate-config` output (secrets are masked),
`ccg version`, OS and Python version. Never paste real resource IDs or account IDs if that is sensitive to you.
