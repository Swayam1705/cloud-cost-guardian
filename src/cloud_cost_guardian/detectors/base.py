"""Detector base class and shared helpers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from cloud_cost_guardian.models.findings import (
    Category,
    Finding,
    RecommendedAction,
    Severity,
    make_finding_id,
)
from cloud_cost_guardian.models.resources import Inventory, ResourceType
from cloud_cost_guardian.policies.cleanup_policy import CleanupPolicy
from cloud_cost_guardian.policies.protection import ProtectionPolicy
from cloud_cost_guardian.policies.thresholds import Thresholds
from cloud_cost_guardian.pricing.estimator import CostEstimate, CostEstimator


class DetectorContext:
    """Everything a detector needs, injected once."""

    def __init__(
        self,
        *,
        thresholds: Thresholds,
        protection: ProtectionPolicy,
        estimator: CostEstimator,
        now: datetime,
    ) -> None:
        self.thresholds = thresholds
        self.protection = protection
        self.estimator = estimator
        self.cleanup_policy = CleanupPolicy(thresholds)
        self.now = now


class Detector(ABC):
    name: str = "base"
    category: Category

    def __init__(self, ctx: DetectorContext) -> None:
        self.ctx = ctx
        self.log = logging.getLogger(f"{__name__}.{self.name}")
        self.resources_inspected = 0

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    def detect(self, inventory: Inventory) -> list[Finding]: ...

    # ------------------------------------------------------------------ helpers
    def build_finding(
        self,
        *,
        resource_id: str,
        resource_type: ResourceType,
        region: str,
        severity: Severity,
        reason: str,
        evidence: Mapping[str, Any],
        estimate: CostEstimate,
        action: RecommendedAction,
        tags: Mapping[str, str],
        metadata: Mapping[str, Any] | None = None,
    ) -> Finding:
        """Assemble a finding, applying protection and cleanup policy centrally."""
        prot = self.ctx.protection.evaluate(tags)
        ev = dict(evidence)
        if not estimate.priced:
            ev["pricing_note"] = estimate.note or "price unavailable; cost shown as 0"
        elif estimate.note:
            ev["pricing_note"] = estimate.note
        provisional = Finding(
            finding_id=make_finding_id(self.category, resource_id, region),
            resource_id=resource_id,
            resource_type=resource_type,
            region=region,
            category=self.category,
            severity=severity,
            reason=reason,
            evidence=ev,
            estimated_monthly_cost=estimate.monthly,
            estimated_annual_cost=estimate.annual,
            estimated_monthly_savings=estimate.monthly_savings,
            recommended_action=action,
            cleanup_eligible=False,
            protected=prot.protected,
            protection_reason=prot.reason,
            detected_at=self.ctx.now,
            metadata={"tags": dict(tags), **(metadata or {})},
        )
        decision = self.ctx.cleanup_policy.evaluate(provisional)
        return provisional.model_copy(
            update={
                "cleanup_eligible": decision.eligible,
                "metadata": {**provisional.metadata, "cleanup_policy": decision.blocked_reason},
            }
        )


def severity_from_monthly(monthly: float) -> Severity:
    if monthly >= 50:
        return Severity.HIGH
    if monthly >= 10:
        return Severity.MEDIUM
    return Severity.LOW
