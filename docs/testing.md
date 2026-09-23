# Testing

```powershell
pytest                          # all 149 tests
pytest -m "not integration"     # unit tests only
pytest -m integration           # moto-based AWS simulation
pytest --cov --cov-report=html  # coverage (htmlcov/index.html)
```

Tests never read your real environment: `tests/conftest.py` strips `CCG_*`/`AWS_*` variables,
sets dummy AWS credentials for moto, and `chdir`s into a temp directory.

## Coverage by area

| File | What it proves |
|---|---|
| `test_detectors.py` | Every detector × {positive, negative, protected, edge}: attached/unattached/new/old, low/normal/stopped/no-metrics/short-window CPU, associated/unassociated EIP, RDS underutilized/normal/missing/short/protected/not-available, old/recent/pending/protected snapshots, threshold boundaries, unpriced resource types, deterministic IDs |
| `test_pricing.py` | Catalog loading, region→default fallback, multipliers, estimator math, missing prices, invalid/negative/missing catalog, custom catalog path |
| `test_protection.py` | Tag matching (case, whitespace, wildcard, false positives), settings parsing, `CleanupPolicy` decisions, `Finding` invariants (protected/RDS/review/tampered-id/NaN/savings>cost/naive datetime) |
| `test_cleanup_safety.py` | The full negative matrix — see [cleanup-safety.md](cleanup-safety.md) |
| `test_reports.py` | Empty, aggregated, JSON round-trip, Markdown sections & escaping, Slack payload limits, 2 000-finding report, malformed report rejection |
| `test_notifications.py` | Mock artifact, Slack config/URL validation/success/HTTP-error without leakage, redaction, masked settings, SNS success/failure, factory default, scan survives notifier failure |
| `test_cli.py` | Help/invalid command/invalid mode, version, validate-config (+ bad env), scan (text/json/artifacts), report formats/missing/malformed, cleanup dry-run default, unknown resource, protected blocked (exit 3), interactive denial, full lifecycle incl. reset, real-mode flag refusal, webhook never in stderr |
| `test_demo_and_config.py` | Fixture/package parity, demo scan == `expected_report.json`, fixture edge-case presence, relative ages, refetch, loader errors, corrupt state recovery, settings validation, env overrides, partial detector failure, disabled detector, source errors → warnings |
| `integration/test_moto_aws.py` | Real boto3 code against moto: inventory read, scan + refetch, cleanup blocked without flag, cleanup succeeds with flag and verifies deletion, protected still blocked, drift after scan blocked, error translation, AccessDenied as partial failure |

## Adding tests

* Put pure-logic tests next to the existing module-level files; put anything that needs `mock_aws` in `tests/integration/` and mark it `@pytest.mark.integration`.
* Use the builders in `conftest.py` (`volume()`, `instance()`, `series()`, …) rather than hand-writing models.
* A safety rule without a test that shows it *blocking* is not done.
