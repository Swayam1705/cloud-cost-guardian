"""Detection 2 — potentially underutilized EC2 instances (CPU-based)."""

from __future__ import annotations

from cloud_cost_guardian.detectors.base import Detector, severity_from_monthly
from cloud_cost_guardian.models.findings import Category, Finding, RecommendedAction
from cloud_cost_guardian.models.resources import Inventory, ResourceType


class EC2Detector(Detector):
    name = "ec2"
    category = Category.UNDERUTILIZED_EC2

    @property
    def enabled(self) -> bool:
        return self.ctx.thresholds.ec2_enabled

    def detect(self, inventory: Inventory) -> list[Finding]:
        t = self.ctx.thresholds
        findings: list[Finding] = []
        for inst in inventory.instances:
            self.resources_inspected += 1
            if inst.state != "running":
                # Stopped instances incur no compute charge; EBS costs are covered by EBSDetector.
                self.log.debug("skip %s: state=%s", inst.resource_id, inst.state)
                continue
            series = inventory.metrics.get(inst.resource_id)
            if series is None or series.sample_count == 0:
                self.log.info(
                    "no CPU metrics for %s; skipping (insufficient evidence)", inst.resource_id
                )
                continue
            if (
                series.sample_count < t.ec2_min_samples
                or series.observed_hours < t.ec2_observation_hours
            ):
                self.log.info(
                    "insufficient observation for %s: samples=%d hours=%.1f",
                    inst.resource_id,
                    series.sample_count,
                    series.observed_hours,
                )
                continue
            avg = series.average or 0.0
            peak = series.maximum or 0.0
            if avg >= t.ec2_cpu_threshold_percent:
                continue
            estimate = self.ctx.estimator.ec2_instance(inst)
            findings.append(
                self.build_finding(
                    resource_id=inst.resource_id,
                    resource_type=ResourceType.EC2_INSTANCE,
                    region=inst.region,
                    severity=severity_from_monthly(estimate.monthly_savings),
                    reason=(
                        f"Potentially underutilized: average CPU {avg:.2f}% "
                        f"(peak {peak:.2f}%) over {series.observed_hours:.0f}h, "
                        f"below threshold {t.ec2_cpu_threshold_percent}%"
                    ),
                    evidence={
                        "instance_type": inst.instance_type,
                        "state": inst.state,
                        "cpu_average_percent": round(avg, 3),
                        "cpu_peak_percent": round(peak, 3),
                        "samples": series.sample_count,
                        "observed_hours": round(series.observed_hours, 1),
                        "threshold_percent": t.ec2_cpu_threshold_percent,
                        "age_days": round(inst.age_days(self.ctx.now), 1),
                        "launch_time": inst.launch_time.isoformat(),
                    },
                    estimate=estimate,
                    action=RecommendedAction.REVIEW_RIGHTSIZING,
                    tags=inst.tags,
                    metadata={"name": inst.name},
                )
            )
        return findings
