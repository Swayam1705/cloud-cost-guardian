# Architecture

## Design goals

1. **Local-first, zero-cost.** The required path never touches a network.
2. **Detection and remediation are separate concerns** with a policy layer in between.
3. **One place decides protection; one place executes destructive actions.**
4. **Every model is validated** so an invalid finding cannot reach a report or the cleanup service.
5. **Fail partially, not totally.** One broken detector or one denied API call yields a warning, not a crash.

## Layer map

```
cli/main.py            argparse commands; exit codes 0 ok · 1 error · 2 usage · 3 blocked
app.py                 composition root: Settings -> concrete objects for a Mode
config.py              pydantic-settings; CCG_* env / .env; cross-field validation; masked summary
logging_config.py      text/json formatter, scan-id contextvar, secret redaction

sources/base.py        InventorySource: load() (read-only) and refetch(type, id)
demo/fixture_loader.py FixtureInventorySource: relative-age JSON fixtures -> Inventory
demo/state.py          DemoStateStore: simulated remediation state (data/demo_state.json)
aws/                   boto3 layer, one module per service + client_factory + typed errors
  inventory_source.py  AWSInventorySource: per-service partial failure, CloudWatch metrics

models/resources.py    EBSVolume, EC2Instance, ElasticIP, DBInstance, Snapshot, MetricSeries, Inventory
models/findings.py     Finding (+ invariants), Category, Severity, RecommendedAction, DESTRUCTIVE_ACTIONS
models/reports.py      ScanReport, ScanSummary, DetectorRun, ProtectedResource

policies/thresholds.py Thresholds (from Settings)
policies/protection.py ProtectionPolicy — THE protection decision
policies/cleanup_policy.py CleanupPolicy — may this finding ever be remediated?

pricing/base.py        PricingProvider ABC
pricing/catalog.py     JSON catalog (region -> default fallback), CatalogPricingProvider
pricing/estimator.py   CostEstimator: resource -> CostEstimate (monthly, annual, savings, priced?)

detectors/base.py      Detector ABC + build_finding() which applies protection + cleanup policy
detectors/*_detector.py one per category

reporting/             ReportBuilder (aggregation, ordering), json/markdown renderers, slack payload
notifications/         NotificationProvider ABC; mock (file), slack (webhook), sns; factory
services/scan_service.py  orchestration + structured events + artifact writing

remediation/approval.py   ExplicitApproval (exact id), InteractiveApproval (type the id), DenyAll
remediation/executors.py  DemoRemediationExecutor (state file), AWSRemediationExecutor (boto3)
remediation/audit.py      AuditLogger: JSONL + latest-cleanup.json
remediation/cleanup_service.py  the gate pipeline
lambda_handler.py         optional scheduled read-only scan entry point
```

## Data flow of a scan

1. `Application.build(settings)` selects a source (`fixtures` or `aws`), loads the pricing catalog,
   builds `ProtectionPolicy` from `CCG_PROTECTED_TAGS` and `Thresholds` from settings.
2. `ScanService.run()` creates a `scan_id`, binds it to the logging context, calls `source.load()`.
3. Each enabled detector receives the immutable `Inventory` and returns `Finding`s. Detector
   exceptions are caught, logged with traceback, recorded as a failed `DetectorRun`, and the scan continues.
4. `Detector.build_finding()` is the single constructor path: it evaluates protection, builds a
   provisional finding with `cleanup_eligible=False`, runs `CleanupPolicy`, and only then sets
   eligibility. The `Finding` model validator re-checks the invariants
   (`protected ⇒ ¬eligible`, `RDS ⇒ ¬eligible`, non-destructive action ⇒ ¬eligible, savings ≤ cost, id matches content).
5. `ReportBuilder` sorts (severity desc, savings desc), aggregates totals (protected findings are
   excluded from waste totals because they cannot be acted on), and attaches limitations + disclaimer.
6. JSON and Markdown are written to `artifacts/reports/`; the notifier is invoked; failures are
   recorded on the result, not raised.

## Data flow of a remediation

See [cleanup-safety.md](cleanup-safety.md). In short: protection → policy → approval → refetch →
re-detect → compare → execute → audit → post-verify, with an audit record written on every exit path.

## Modes

| Mode | Source | Executor | Network |
|---|---|---|---|
| `demo` | `FixtureInventorySource` (+ demo state) | `DemoRemediationExecutor` | none |
| `local` | `AWSInventorySource` via `CCG_AWS_ENDPOINT_URL` | `AWSRemediationExecutor` (with flag) | local endpoint |
| `aws` | `AWSInventorySource` | `AWSRemediationExecutor` (with flag) | AWS |

## Extension points

* New detector: subclass `Detector`, add a `Category`, register in `detectors/__init__.py::ALL_DETECTORS`,
  add fixture entries and tests. If it should be remediable, also add its action to `DESTRUCTIVE_ACTIONS`,
  its category to `REMEDIABLE_CATEGORIES`, and an executor branch.
* New inventory source (Azure, GCP, another mock): implement `InventorySource`.
* New pricing provider: implement `PricingProvider` (keep it free of paid APIs).
* New notifier: implement `NotificationProvider` and add it to the factory + `NotificationProviderName`.
