"""Detection 1 — unattached EBS volumes."""

from __future__ import annotations

from cloud_cost_guardian.detectors.base import Detector, severity_from_monthly
from cloud_cost_guardian.models.findings import Category, Finding, RecommendedAction
from cloud_cost_guardian.models.resources import Inventory, ResourceType


class EBSDetector(Detector):
    name = "ebs"
    category = Category.UNATTACHED_EBS

    @property
    def enabled(self) -> bool:
        return self.ctx.thresholds.ebs_enabled

    def detect(self, inventory: Inventory) -> list[Finding]:
        findings: list[Finding] = []
        min_age = self.ctx.thresholds.ebs_min_age_days
        for vol in inventory.volumes:
            self.resources_inspected += 1
            if vol.is_attached or vol.state not in {"available", "error"}:
                continue
            age = round(vol.age_days(self.ctx.now), 1)
            estimate = self.ctx.estimator.ebs_volume(vol)
            meets_age = age >= min_age
            reason = (
                f"Volume is in state '{vol.state}' with no attachment for {age:.0f} days"
                if meets_age
                else f"Volume is unattached but only {age:.0f} days old (minimum {min_age}); "
                "flagged for awareness, not cleanup"
            )
            findings.append(
                self.build_finding(
                    resource_id=vol.resource_id,
                    resource_type=ResourceType.EBS_VOLUME,
                    region=vol.region,
                    severity=severity_from_monthly(estimate.monthly)
                    if meets_age
                    else severity_from_monthly(0),
                    reason=reason,
                    evidence={
                        "state": vol.state,
                        "attached_instance_id": None,
                        "age_days": age,
                        "minimum_age_days": min_age,
                        "size_gib": vol.size_gib,
                        "volume_type": vol.volume_type,
                        "availability_zone": vol.availability_zone,
                        "create_time": vol.create_time.isoformat(),
                        "encrypted": vol.encrypted,
                    },
                    estimate=estimate,
                    action=RecommendedAction.DELETE_VOLUME,
                    tags=vol.tags,
                )
            )
        return findings
