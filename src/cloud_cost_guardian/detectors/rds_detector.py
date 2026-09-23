"""Detection 4 — RDS right-sizing recommendations (never destructive)."""

from __future__ import annotations

from cloud_cost_guardian.detectors.base import Detector, severity_from_monthly
from cloud_cost_guardian.models.findings import Category, Finding, RecommendedAction
from cloud_cost_guardian.models.resources import Inventory, ResourceType


class RDSDetector(Detector):
    name = "rds"
    category = Category.RDS_RIGHTSIZING

    @property
    def enabled(self) -> bool:
        return self.ctx.thresholds.rds_enabled

    def detect(self, inventory: Inventory) -> list[Finding]:
        t = self.ctx.thresholds
        findings: list[Finding] = []
        for db in inventory.db_instances:
            self.resources_inspected += 1
            if db.status != "available":
                continue
            series = inventory.metrics.get(db.resource_id)
            if series is None or series.sample_count == 0:
                self.log.info("no CPU metrics for %s; skipping", db.resource_id)
                continue
            if (
                series.sample_count < t.rds_min_samples
                or series.observed_hours < t.rds_observation_hours
            ):
                self.log.info("insufficient observation for %s", db.resource_id)
                continue
            avg = series.average or 0.0
            peak = series.maximum or 0.0
            if avg >= t.rds_cpu_threshold_percent:
                continue
            estimate = self.ctx.estimator.rds_instance(db)
            target = self.ctx.estimator.provider.rds_downsize_target(db.instance_class)
            findings.append(
                self.build_finding(
                    resource_id=db.resource_id,
                    resource_type=ResourceType.RDS_INSTANCE,
                    region=db.region,
                    severity=severity_from_monthly(estimate.monthly_savings),
                    reason=(
                        f"Potential right-sizing candidate: average CPU {avg:.2f}% "
                        f"(peak {peak:.2f}%) over {series.observed_hours:.0f}h "
                        f"on {db.instance_class}"
                    ),
                    evidence={
                        "engine": db.engine,
                        "instance_class": db.instance_class,
                        "multi_az": db.multi_az,
                        "cpu_average_percent": round(avg, 3),
                        "cpu_peak_percent": round(peak, 3),
                        "samples": series.sample_count,
                        "observed_hours": round(series.observed_hours, 1),
                        "threshold_percent": t.rds_cpu_threshold_percent,
                        "suggested_instance_class": target,
                        "note": (
                            "Recommendation only. CPU alone does not prove waste; "
                            "review memory, IOPS and connections."
                        ),
                    },
                    estimate=estimate,
                    action=RecommendedAction.REVIEW_RIGHTSIZING,
                    tags=db.tags,
                )
            )
        return findings
