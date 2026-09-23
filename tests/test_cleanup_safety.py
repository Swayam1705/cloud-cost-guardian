"""Negative-path tests for the remediation pipeline. These are the most important tests here."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloud_cost_guardian.detectors import DetectorContext, EBSDetector
from cloud_cost_guardian.exceptions import InventorySourceError, RemediationFailedError
from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.resources import Inventory, ResourceType
from cloud_cost_guardian.policies.cleanup_policy import CleanupPolicy
from cloud_cost_guardian.policies.protection import ProtectionPolicy
from cloud_cost_guardian.remediation.approval import DenyAll, ExplicitApproval, InteractiveApproval
from cloud_cost_guardian.remediation.audit import AuditLogger
from cloud_cost_guardian.remediation.cleanup_service import CleanupService
from cloud_cost_guardian.remediation.executors import RemediationExecutor
from cloud_cost_guardian.sources.base import InventorySource
from tests.conftest import PROTECTED, inventory, volume


class FakeSource(InventorySource):
    """Scriptable source: ``current`` is what refetch returns; ``fail`` raises."""

    def __init__(self, current: Inventory) -> None:
        self.current = current
        self.fail = False
        self.refetch_calls = 0

    @property
    def name(self) -> str:
        return "fake"

    def load(self) -> Inventory:
        return self.current

    def refetch(self, resource_type: ResourceType, resource_id: str) -> Inventory:
        self.refetch_calls += 1
        if self.fail:
            raise InventorySourceError("simulated API failure")
        if self.refetch_calls > 1:
            return Inventory(region=self.current.region)
        return Inventory(
            region=self.current.region,
            volumes=tuple(v for v in self.current.volumes if v.resource_id == resource_id),
        )


class RecordingExecutor(RemediationExecutor):
    def __init__(self, fail: bool = False) -> None:
        self.executed: list[str] = []
        self.fail = fail

    @property
    def name(self) -> str:
        return "recording"

    def execute(self, finding: Finding, *, scan_id: str) -> str:
        if self.fail:
            raise RemediationFailedError("simulated delete failure")
        self.executed.append(finding.resource_id)
        return "ok"


@pytest.fixture
def old_volume_finding(ctx: DetectorContext) -> Finding:
    [f] = EBSDetector(ctx).detect(inventory(volumes=(volume("vol-old", age_days=93),)))
    assert f.cleanup_eligible
    return f


def make_service(
    ctx: DetectorContext,
    source: FakeSource,
    executor: RemediationExecutor | None,
    approval: object,
    tmp_path: Path,
) -> tuple[CleanupService, AuditLogger]:
    audit = AuditLogger(tmp_path / "artifacts")
    svc = CleanupService(
        source=source,
        detector_ctx=ctx,
        protection=ctx.protection,
        cleanup_policy=CleanupPolicy(ctx.thresholds),
        approval=approval,  # type: ignore[arg-type]
        executor=executor,
        audit=audit,
        mode="test",
    )
    return svc, audit


# ---------------------------------------------------------------------- happy path
def test_full_pipeline_success(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    executor = RecordingExecutor()
    svc, audit = make_service(ctx, source, executor, ExplicitApproval("vol-old"), tmp_path)

    outcome = svc.remediate(old_volume_finding, "scan-1")

    assert outcome.remediated
    assert executor.executed == ["vol-old"]
    assert source.refetch_calls == 2  # once before, once after
    [record] = audit.read_all()
    assert record.approval_result.startswith("approved")
    assert record.policy_result == "passed"
    assert record.protection_result == "passed"
    assert record.verification_result.startswith("passed")
    assert record.dry_run is False
    assert record.error is None


# ---------------------------------------------------------------------- dry-run
def test_dry_run_never_executes(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    executor = RecordingExecutor()
    svc, audit = make_service(ctx, source, executor, ExplicitApproval("vol-old"), tmp_path)

    outcomes = svc.dry_run([old_volume_finding], "scan-1")

    assert [o.status for o in outcomes] == ["dry-run"]
    assert executor.executed == []
    assert audit.read_all()[0].dry_run is True


# ---------------------------------------------------------------------- negative paths
def test_protected_resource_blocked(ctx: DetectorContext, tmp_path: Path) -> None:
    [f] = EBSDetector(ctx).detect(
        inventory(volumes=(volume("vol-p", age_days=300, tags=PROTECTED),))
    )
    source = FakeSource(inventory(volumes=(volume("vol-p", age_days=300, tags=PROTECTED),)))
    executor = RecordingExecutor()
    svc, audit = make_service(ctx, source, executor, ExplicitApproval("vol-p"), tmp_path)

    outcome = svc.remediate(f, "scan-1")

    assert outcome.status == "blocked" and outcome.stage == "protection"
    assert executor.executed == []
    assert source.refetch_calls == 0
    assert audit.read_all()[0].protection_result.startswith("BLOCKED")


def test_forged_finding_with_protected_tags_still_blocked(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    """Even if someone hands the service a finding whose `protected` flag is False, the
    protection policy is re-evaluated against the tags carried in metadata."""
    forged = old_volume_finding.model_copy(update={"metadata": {"tags": PROTECTED}})
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    executor = RecordingExecutor()
    svc, _ = make_service(ctx, source, executor, ExplicitApproval("vol-old"), tmp_path)
    outcome = svc.remediate(forged, "scan-1")
    assert outcome.stage == "protection" and executor.executed == []


def test_not_old_enough_blocked(ctx: DetectorContext, tmp_path: Path) -> None:
    [f] = EBSDetector(ctx).detect(inventory(volumes=(volume("vol-new", age_days=2),)))
    source = FakeSource(inventory(volumes=(volume("vol-new", age_days=2),)))
    executor = RecordingExecutor()
    svc, _ = make_service(ctx, source, executor, ExplicitApproval("vol-new"), tmp_path)

    outcome = svc.remediate(f, "scan-1")

    assert outcome.status == "blocked" and outcome.stage == "policy"
    assert "below minimum" in outcome.detail
    assert executor.executed == []


def test_not_policy_eligible_blocked(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    """A finding with cleanup_eligible=False is blocked even when the policy itself would pass."""
    ineligible = old_volume_finding.model_copy(update={"cleanup_eligible": False})
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    executor = RecordingExecutor()
    svc, _ = make_service(ctx, source, executor, ExplicitApproval("vol-old"), tmp_path)
    outcome = svc.remediate(ineligible, "scan-1")
    assert outcome.stage == "policy" and executor.executed == []


def test_approval_denied_blocked(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    executor = RecordingExecutor()
    svc, audit = make_service(ctx, source, executor, DenyAll(), tmp_path)

    outcome = svc.remediate(old_volume_finding, "scan-1")

    assert outcome.status == "blocked" and outcome.stage == "approval"
    assert executor.executed == []
    assert source.refetch_calls == 0  # we do not even touch AWS without approval
    assert audit.read_all()[0].approval_result.startswith("denied")


def test_approval_for_wrong_resource_id_is_denied(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    executor = RecordingExecutor()
    svc, _ = make_service(ctx, source, executor, ExplicitApproval("vol-OTHER"), tmp_path)
    outcome = svc.remediate(old_volume_finding, "scan-1")
    assert outcome.stage == "approval" and executor.executed == []


def test_interactive_approval_requires_exact_id(old_volume_finding: Finding) -> None:
    assert not InteractiveApproval(lambda _: "yes").request(old_volume_finding).approved
    assert not InteractiveApproval(lambda _: "").request(old_volume_finding).approved
    assert InteractiveApproval(lambda _: " vol-old ").request(old_volume_finding).approved

    def boom(_: str) -> str:
        raise EOFError

    assert not InteractiveApproval(boom).request(old_volume_finding).approved


def test_resource_changed_between_scan_and_cleanup_blocked(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    """Scan saw an unattached volume; by cleanup time it was attached -> block."""
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93, attached="i-99"),)))
    executor = RecordingExecutor()
    svc, audit = make_service(ctx, source, executor, ExplicitApproval("vol-old"), tmp_path)

    outcome = svc.remediate(old_volume_finding, "scan-1")

    assert outcome.status == "blocked" and outcome.stage == "verification"
    assert "changed" in outcome.detail
    assert executor.executed == []
    assert audit.read_all()[0].verification_result.startswith("BLOCKED")


def test_resource_became_protected_after_scan_blocked(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93, tags=PROTECTED),)))
    executor = RecordingExecutor()
    svc, _ = make_service(ctx, source, executor, ExplicitApproval("vol-old"), tmp_path)
    outcome = svc.remediate(old_volume_finding, "scan-1")
    assert outcome.stage == "verification" and "protected" in outcome.detail
    assert executor.executed == []


def test_resource_disappeared_blocked(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory())
    executor = RecordingExecutor()
    svc, _ = make_service(ctx, source, executor, ExplicitApproval("vol-old"), tmp_path)
    outcome = svc.remediate(old_volume_finding, "scan-1")
    assert outcome.stage == "verification" and "no longer exists" in outcome.detail
    assert executor.executed == []


def test_refetch_api_failure_blocked(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    source.fail = True
    executor = RecordingExecutor()
    svc, _ = make_service(ctx, source, executor, ExplicitApproval("vol-old"), tmp_path)
    outcome = svc.remediate(old_volume_finding, "scan-1")
    assert outcome.stage == "verification" and "re-fetch failed" in outcome.detail
    assert executor.executed == []


def test_executor_failure_is_recorded(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    svc, audit = make_service(
        ctx, source, RecordingExecutor(fail=True), ExplicitApproval("vol-old"), tmp_path
    )
    outcome = svc.remediate(old_volume_finding, "scan-1")
    assert outcome.status == "failed" and outcome.stage == "execution"
    record = audit.read_all()[0]
    assert record.error == "simulated delete failure"
    assert record.action_result == "failed"


def test_no_executor_blocks_after_all_gates(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    svc, _ = make_service(ctx, source, None, ExplicitApproval("vol-old"), tmp_path)
    outcome = svc.remediate(old_volume_finding, "scan-1")
    assert outcome.status == "blocked" and outcome.stage == "execution"


def test_every_attempt_writes_audit(
    ctx: DetectorContext, old_volume_finding: Finding, tmp_path: Path
) -> None:
    source = FakeSource(inventory(volumes=(volume("vol-old", age_days=93),)))
    svc, audit = make_service(ctx, source, RecordingExecutor(), DenyAll(), tmp_path)
    svc.remediate(old_volume_finding, "scan-1")
    svc.dry_run([old_volume_finding], "scan-1")
    svc.remediate(old_volume_finding, "scan-2")
    records = audit.read_all()
    assert len(records) == 3
    assert {r.scan_id for r in records} == {"scan-1", "scan-2"}
    assert audit.latest_path.exists()


def test_rds_finding_never_reaches_executor(ctx: DetectorContext, tmp_path: Path) -> None:
    from cloud_cost_guardian.detectors import RDSDetector
    from tests.conftest import db, series

    [f] = RDSDetector(ctx).detect(
        inventory(db_instances=(db(),), metrics={"db-1": series("db-1", hours=200, average=1.0)})
    )
    source = FakeSource(inventory())
    executor = RecordingExecutor()
    svc, _ = make_service(ctx, source, executor, ExplicitApproval("db-1"), tmp_path)
    outcome = svc.remediate(f, "scan-1")
    assert outcome.stage == "policy" and "RDS" in outcome.detail
    assert executor.executed == []


def test_protection_policy_used_by_service_is_the_shared_one(
    ctx: DetectorContext, tmp_path: Path
) -> None:
    """Changing the configured protected tags changes cleanup behaviour with no other code path."""
    [f] = EBSDetector(ctx).detect(
        inventory(volumes=(volume("vol-t", age_days=100, tags={"Team": "finance"}),))
    )
    assert f.cleanup_eligible
    strict_ctx = DetectorContext(
        thresholds=ctx.thresholds,
        protection=ProtectionPolicy({"Team": "finance"}),
        estimator=ctx.estimator,
        now=ctx.now,
    )
    source = FakeSource(
        inventory(volumes=(volume("vol-t", age_days=100, tags={"Team": "finance"}),))
    )
    executor = RecordingExecutor()
    svc, _ = make_service(strict_ctx, source, executor, ExplicitApproval("vol-t"), tmp_path)
    outcome = svc.remediate(f, "scan-1")
    assert outcome.stage == "protection" and executor.executed == []
