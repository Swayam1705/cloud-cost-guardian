"""Detection 3 — unassociated Elastic IPs."""

from __future__ import annotations

from cloud_cost_guardian.detectors.base import Detector, severity_from_monthly
from cloud_cost_guardian.models.findings import Category, Finding, RecommendedAction
from cloud_cost_guardian.models.resources import Inventory, ResourceType


class EIPDetector(Detector):
    name = "eip"
    category = Category.UNASSOCIATED_EIP

    @property
    def enabled(self) -> bool:
        return self.ctx.thresholds.eip_enabled

    def detect(self, inventory: Inventory) -> list[Finding]:
        findings: list[Finding] = []
        for eip in inventory.elastic_ips:
            self.resources_inspected += 1
            if eip.is_associated:
                continue
            estimate = self.ctx.estimator.elastic_ip(eip)
            findings.append(
                self.build_finding(
                    resource_id=eip.resource_id,
                    resource_type=ResourceType.ELASTIC_IP,
                    region=eip.region,
                    severity=severity_from_monthly(estimate.monthly),
                    reason=(
                        "Elastic IP is allocated but not associated with any instance "
                        "or network interface"
                    ),
                    evidence={
                        "public_ip": eip.public_ip,
                        "association_id": None,
                        "instance_id": None,
                        "network_interface_id": None,
                        "domain": eip.domain,
                    },
                    estimate=estimate,
                    action=RecommendedAction.RELEASE_EIP,
                    tags=eip.tags,
                )
            )
        return findings
