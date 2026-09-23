"""Tests for the post-remediation verification state machine."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloud_cost_guardian.detectors import DetectorContext, EBSDetector
from cloud_cost_guardian.exceptions import InventorySourceError
from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.resources import Inventory, ResourceType
from cloud_cost_guardian.policies.cleanup_policy import CleanupPolicy
from cloud_cost_guardian.remediation.approval import ExplicitApproval
from cloud_cost_guardian.remediation.audit import AuditLogger
from cloud_cost_guardian.remediation.cleanup_service import CleanupService
from cloud_cost_guardian.sources.base import InventorySource
from tests.conftest import inventory, volume
from tests.test_cleanup_safety import RecordingExecutor


@pytest.fixture
def old_volume_finding(ctx: DetectorContext) -> Finding:
    [f] = EBSDetector(ctx).detect(inventory(volumes=(volume("vol-old", age_days=93),)))
    assert f.cleanup_eligible
    return f


class MockRedetectSource(InventorySource):
    """Source that simulates whether a resource still reproduces finding after action."""

    def __init__(
        self,
        current: Inventory,
        still_reproduces: bool = True,
        refetch_error: bool = False,
    ) -> None:
        self.current = current
        self.still_reproduces = still_reproduces
        self.refetch_error = refetch_error
        self.refetch_calls = 0

    @property
    def name(self) -> str:
        return "mock_redetect"

    def load(self) -> Inventory:
        return self.current

    def refetch(self, resource_type: ResourceType, resource_id: str) -> Inventory:
        self.refetch_calls += 1
        if self.refetch_error and self.refetch_calls > 1:
            raise InventorySourceError("Network timeout during post-action re-fetch")
        if self.refetch_calls > 1 and not self.still_reproduces:
            return Inventory(region=self.current.region)
        return Inventory(
            region=self.current.region,
            volumes=tuple(v for v in self.current.volumes if v.resource_id == resource_id),
        )


def test_post_action_verification_failure_sets_verification_failed(
    old_volume_finding: Finding,
    ctx: DetectorContext,
    tmp_path: Path,
) -> None:
    """When finding still reproduces after action, status is 'verification_failed'."""
    src = MockRedetectSource(
        inventory(volumes=(volume("vol-old", age_days=93),)), still_reproduces=True
    )
    executor = RecordingExecutor()
    service = CleanupService(
        source=src,
        detector_ctx=ctx,
        protection=ctx.protection,
        cleanup_policy=CleanupPolicy(ctx.thresholds),
        approval=ExplicitApproval(old_volume_finding.resource_id),
        executor=executor,
        audit=AuditLogger(tmp_path / "artifacts"),
        mode="test",
    )

    outcome = service.remediate(old_volume_finding, "scan-123")

    assert outcome.status == "verification_failed"
    assert outcome.remediated is False
    assert outcome.stage == "verify-after"
    assert "WARNING: resource still matches the finding after remediation" in outcome.detail
    assert len(executor.executed) == 1


def test_post_action_verification_success_sets_remediated(
    old_volume_finding: Finding,
    ctx: DetectorContext,
    tmp_path: Path,
) -> None:
    """When a resource no longer matches finding after action, status MUST be 'remediated'."""
    src = MockRedetectSource(
        inventory(volumes=(volume("vol-old", age_days=93),)), still_reproduces=False
    )
    executor = RecordingExecutor()
    service = CleanupService(
        source=src,
        detector_ctx=ctx,
        protection=ctx.protection,
        cleanup_policy=CleanupPolicy(ctx.thresholds),
        approval=ExplicitApproval(old_volume_finding.resource_id),
        executor=executor,
        audit=AuditLogger(tmp_path / "artifacts"),
        mode="test",
    )

    outcome = service.remediate(old_volume_finding, "scan-123")

    assert outcome.status == "remediated"
    assert outcome.remediated is True
    assert outcome.stage == "verify-after"
    assert "verified:" in outcome.detail


def test_post_action_refetch_error_sets_verification_pending(
    old_volume_finding: Finding,
    ctx: DetectorContext,
    tmp_path: Path,
) -> None:
    """When post-action re-fetch throws InventorySourceError, status is 'verification_pending'."""
    src = MockRedetectSource(
        inventory(volumes=(volume("vol-old", age_days=93),)), refetch_error=True
    )
    executor = RecordingExecutor()
    service = CleanupService(
        source=src,
        detector_ctx=ctx,
        protection=ctx.protection,
        cleanup_policy=CleanupPolicy(ctx.thresholds),
        approval=ExplicitApproval(old_volume_finding.resource_id),
        executor=executor,
        audit=AuditLogger(tmp_path / "artifacts"),
        mode="test",
    )

    outcome = service.remediate(old_volume_finding, "scan-123")

    assert outcome.status == "verification_pending"
    assert outcome.remediated is False
    assert outcome.stage == "verify-after"
    assert "could not re-fetch" in outcome.detail
