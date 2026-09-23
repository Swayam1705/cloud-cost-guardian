from __future__ import annotations

import pytest

from cloud_cost_guardian.detectors import (
    EBSDetector,
    EC2Detector,
    EIPDetector,
    RDSDetector,
    SnapshotDetector,
)
from cloud_cost_guardian.detectors.base import DetectorContext
from cloud_cost_guardian.models.findings import Category, RecommendedAction, Severity
from cloud_cost_guardian.policies.thresholds import Thresholds
from tests.conftest import NOW, PROTECTED, db, eip, instance, inventory, series, snapshot, volume


# --------------------------------------------------------------------------- EBS
class TestEBSDetector:
    def test_unattached_old_volume_is_cleanup_eligible(self, ctx: DetectorContext) -> None:
        [f] = EBSDetector(ctx).detect(inventory(volumes=(volume(age_days=93),)))
        assert f.category is Category.UNATTACHED_EBS
        assert f.cleanup_eligible and not f.protected
        assert f.evidence["age_days"] == 93.0
        assert f.recommended_action is RecommendedAction.DELETE_VOLUME
        assert f.estimated_monthly_cost == pytest.approx(100 * 0.08)
        assert f.estimated_annual_cost == pytest.approx(100 * 0.08 * 12)

    def test_attached_volume_not_reported(self, ctx: DetectorContext) -> None:
        assert EBSDetector(ctx).detect(inventory(volumes=(volume(attached="i-1"),))) == []

    def test_new_volume_reported_but_not_eligible(self, ctx: DetectorContext) -> None:
        [f] = EBSDetector(ctx).detect(inventory(volumes=(volume(age_days=2),)))
        assert not f.cleanup_eligible
        assert "below minimum" in f.metadata["cleanup_policy"]
        assert f.severity is Severity.LOW

    def test_protected_volume_never_eligible(self, ctx: DetectorContext) -> None:
        [f] = EBSDetector(ctx).detect(inventory(volumes=(volume(age_days=500, tags=PROTECTED),)))
        assert f.protected and not f.cleanup_eligible
        assert f.protection_reason and "cost-guardian-protected" in f.protection_reason

    def test_environment_production_tag_is_protected_case_insensitively(
        self, ctx: DetectorContext
    ) -> None:
        [f] = EBSDetector(ctx).detect(
            inventory(volumes=(volume(tags={"environment": "PRODUCTION"}),))
        )
        assert f.protected

    def test_min_age_threshold_is_configurable(self, ctx: DetectorContext) -> None:
        ctx.thresholds = Thresholds(ebs_min_age_days=0)
        ctx.cleanup_policy = type(ctx.cleanup_policy)(ctx.thresholds)
        [f] = EBSDetector(ctx).detect(inventory(volumes=(volume(age_days=0.5),)))
        assert f.cleanup_eligible

    def test_disabled(self, ctx: DetectorContext) -> None:
        ctx.thresholds = Thresholds(ebs_enabled=False)
        assert not EBSDetector(ctx).enabled

    def test_unknown_volume_type_is_unpriced_but_reported(self, ctx: DetectorContext) -> None:
        [f] = EBSDetector(ctx).detect(inventory(volumes=(volume(vtype="future9"),)))
        assert f.estimated_monthly_cost == 0
        assert "pricing_note" in f.evidence


# --------------------------------------------------------------------------- EC2
class TestEC2Detector:
    def test_low_cpu_is_recommendation_not_cleanup(self, ctx: DetectorContext) -> None:
        inv = inventory(
            instances=(instance(),), metrics={"i-1": series("i-1", average=1.5, peak=4.0)}
        )
        [f] = EC2Detector(ctx).detect(inv)
        assert f.category is Category.UNDERUTILIZED_EC2
        assert f.recommended_action is RecommendedAction.REVIEW_RIGHTSIZING
        assert not f.cleanup_eligible
        assert "Potentially underutilized" in f.reason
        assert f.evidence["cpu_peak_percent"] == 4.0
        assert f.evidence["samples"] == 72
        assert 0 < f.estimated_monthly_savings < f.estimated_monthly_cost

    def test_normal_cpu_not_reported(self, ctx: DetectorContext) -> None:
        inv = inventory(instances=(instance(),), metrics={"i-1": series("i-1", average=40.0)})
        assert EC2Detector(ctx).detect(inv) == []

    def test_stopped_instance_skipped(self, ctx: DetectorContext) -> None:
        inv = inventory(
            instances=(instance(state="stopped"),), metrics={"i-1": series("i-1", average=0.0)}
        )
        assert EC2Detector(ctx).detect(inv) == []

    def test_missing_metrics_skipped(self, ctx: DetectorContext) -> None:
        assert EC2Detector(ctx).detect(inventory(instances=(instance(),))) == []

    def test_too_few_samples_skipped(self, ctx: DetectorContext) -> None:
        inv = inventory(
            instances=(instance(),), metrics={"i-1": series("i-1", hours=6, average=0.5)}
        )
        assert EC2Detector(ctx).detect(inv) == []

    def test_protected_instance_flagged_protected(self, ctx: DetectorContext) -> None:
        inv = inventory(
            instances=(instance(tags=PROTECTED),), metrics={"i-1": series("i-1", average=0.5)}
        )
        [f] = EC2Detector(ctx).detect(inv)
        assert f.protected and not f.cleanup_eligible

    def test_threshold_boundary_is_exclusive(self, ctx: DetectorContext) -> None:
        inv = inventory(instances=(instance(),), metrics={"i-1": series("i-1", average=5.0)})
        assert EC2Detector(ctx).detect(inv) == []


# --------------------------------------------------------------------------- EIP
class TestEIPDetector:
    def test_unassociated(self, ctx: DetectorContext) -> None:
        [f] = EIPDetector(ctx).detect(inventory(elastic_ips=(eip(),)))
        assert f.cleanup_eligible
        assert f.recommended_action is RecommendedAction.RELEASE_EIP
        assert f.estimated_monthly_cost == pytest.approx(0.005 * 730)
        assert f.evidence["public_ip"] == "203.0.113.5"

    def test_associated(self, ctx: DetectorContext) -> None:
        assert EIPDetector(ctx).detect(inventory(elastic_ips=(eip(associated=True),))) == []

    def test_protected(self, ctx: DetectorContext) -> None:
        [f] = EIPDetector(ctx).detect(inventory(elastic_ips=(eip(tags=PROTECTED),)))
        assert f.protected and not f.cleanup_eligible


# --------------------------------------------------------------------------- RDS
class TestRDSDetector:
    def test_underutilized_is_recommendation_only(self, ctx: DetectorContext) -> None:
        inv = inventory(
            db_instances=(db(),),
            metrics={"db-1": series("db-1", hours=200, average=3.0, peak=12.0)},
        )
        [f] = RDSDetector(ctx).detect(inv)
        assert f.category is Category.RDS_RIGHTSIZING
        assert not f.cleanup_eligible
        assert f.recommended_action is RecommendedAction.REVIEW_RIGHTSIZING
        assert f.evidence["suggested_instance_class"] == "db.m5.large"
        assert f.estimated_monthly_savings > 0

    def test_normal(self, ctx: DetectorContext) -> None:
        inv = inventory(
            db_instances=(db(),), metrics={"db-1": series("db-1", hours=200, average=45.0)}
        )
        assert RDSDetector(ctx).detect(inv) == []

    def test_missing_metrics(self, ctx: DetectorContext) -> None:
        assert RDSDetector(ctx).detect(inventory(db_instances=(db(),))) == []

    def test_short_window_skipped(self, ctx: DetectorContext) -> None:
        inv = inventory(
            db_instances=(db(),), metrics={"db-1": series("db-1", hours=48, average=1.0)}
        )
        assert RDSDetector(ctx).detect(inv) == []

    def test_protected(self, ctx: DetectorContext) -> None:
        inv = inventory(
            db_instances=(db(tags=PROTECTED),),
            metrics={"db-1": series("db-1", hours=200, average=1.0)},
        )
        [f] = RDSDetector(ctx).detect(inv)
        assert f.protected and not f.cleanup_eligible

    def test_not_available_status_skipped(self, ctx: DetectorContext) -> None:
        inv = inventory(
            db_instances=(db(status="stopped"),),
            metrics={"db-1": series("db-1", hours=200, average=1.0)},
        )
        assert RDSDetector(ctx).detect(inv) == []


# --------------------------------------------------------------------------- Snapshots
class TestSnapshotDetector:
    def test_old(self, ctx: DetectorContext) -> None:
        [f] = SnapshotDetector(ctx).detect(inventory(snapshots=(snapshot(age_days=120),)))
        assert f.cleanup_eligible
        assert f.recommended_action is RecommendedAction.DELETE_SNAPSHOT
        assert f.estimated_monthly_cost == pytest.approx(100 * 0.05)
        assert "upper bound" in f.evidence["pricing_note"]

    def test_recent(self, ctx: DetectorContext) -> None:
        assert SnapshotDetector(ctx).detect(inventory(snapshots=(snapshot(age_days=3),))) == []

    def test_protected(self, ctx: DetectorContext) -> None:
        [f] = SnapshotDetector(ctx).detect(inventory(snapshots=(snapshot(tags=PROTECTED),)))
        assert f.protected and not f.cleanup_eligible

    def test_pending_snapshot_skipped(self, ctx: DetectorContext) -> None:
        assert SnapshotDetector(ctx).detect(inventory(snapshots=(snapshot(state="pending"),))) == []

    def test_exact_threshold_counts_as_old(self, ctx: DetectorContext) -> None:
        [f] = SnapshotDetector(ctx).detect(inventory(snapshots=(snapshot(age_days=90),)))
        assert f.cleanup_eligible


def test_finding_ids_are_deterministic(ctx: DetectorContext) -> None:
    a = EBSDetector(ctx).detect(inventory(volumes=(volume(),)))[0]
    b = EBSDetector(ctx).detect(inventory(volumes=(volume(),)))[0]
    assert a.finding_id == b.finding_id
    assert a.detected_at == NOW
