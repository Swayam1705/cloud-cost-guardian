"""Detection 5 — old EBS snapshots."""

from __future__ import annotations

from cloud_cost_guardian.detectors.base import Detector, severity_from_monthly
from cloud_cost_guardian.models.findings import Category, Finding, RecommendedAction
from cloud_cost_guardian.models.resources import Inventory, ResourceType


class SnapshotDetector(Detector):
    name = "snapshot"
    category = Category.OLD_SNAPSHOT

    @property
    def enabled(self) -> bool:
        return self.ctx.thresholds.snapshot_enabled

    def detect(self, inventory: Inventory) -> list[Finding]:
        max_age = self.ctx.thresholds.snapshot_max_age_days
        findings: list[Finding] = []
        for snap in inventory.snapshots:
            self.resources_inspected += 1
            if snap.state != "completed":
                continue
            age = round(snap.age_days(self.ctx.now), 1)
            if age < max_age:
                continue
            estimate = self.ctx.estimator.snapshot(snap)
            findings.append(
                self.build_finding(
                    resource_id=snap.resource_id,
                    resource_type=ResourceType.EBS_SNAPSHOT,
                    region=snap.region,
                    severity=severity_from_monthly(estimate.monthly),
                    reason=f"Snapshot is {age:.0f} days old (threshold {max_age} days)",
                    evidence={
                        "volume_id": snap.volume_id,
                        "age_days": age,
                        "max_age_days": max_age,
                        "volume_size_gib": snap.volume_size_gib,
                        "start_time": snap.start_time.isoformat(),
                        "description": snap.description[:200],
                    },
                    estimate=estimate,
                    action=RecommendedAction.DELETE_SNAPSHOT,
                    tags=snap.tags,
                )
            )
        return findings
