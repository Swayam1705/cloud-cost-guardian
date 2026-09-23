"""Cleanup eligibility policy.

Decides, for a given finding, whether automated remediation may even be *offered*. The
remediation service re-runs these checks (plus a live re-fetch) before acting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cloud_cost_guardian.models.findings import DESTRUCTIVE_ACTIONS, Category, Finding
from cloud_cost_guardian.models.resources import ResourceType
from cloud_cost_guardian.policies.thresholds import Thresholds

# Categories where automated remediation is permitted at all.
REMEDIABLE_CATEGORIES: frozenset[Category] = frozenset(
    {Category.UNATTACHED_EBS, Category.UNASSOCIATED_EIP, Category.OLD_SNAPSHOT}
)


@dataclass(frozen=True)
class CleanupDecision:
    eligible: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocked_reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "eligible"


class CleanupPolicy:
    def __init__(self, thresholds: Thresholds) -> None:
        self._t = thresholds

    def evaluate(self, finding: Finding) -> CleanupDecision:
        reasons: list[str] = []
        if finding.protected:
            reasons.append("resource is protected")
        if finding.resource_type is ResourceType.RDS_INSTANCE:
            reasons.append("RDS is recommendation-only; automated cleanup is never permitted")
        if finding.category not in REMEDIABLE_CATEGORIES:
            reasons.append(f"category {finding.category.value} is review-only")
        if finding.recommended_action not in DESTRUCTIVE_ACTIONS:
            reasons.append("recommended action is not a remediation action")
        age = finding.evidence.get("age_days")
        min_age = self.minimum_age_days(finding.category)
        if min_age is not None:
            if not isinstance(age, (int, float)):
                reasons.append("age evidence missing; cannot verify minimum age")
            elif age < min_age:
                reasons.append(f"resource age {age:.1f}d is below minimum {min_age}d")
        return CleanupDecision(eligible=not reasons, reasons=tuple(reasons))

    def minimum_age_days(self, category: Category) -> int | None:
        if category is Category.UNATTACHED_EBS:
            return self._t.ebs_min_age_days
        if category is Category.OLD_SNAPSHOT:
            return self._t.snapshot_max_age_days
        return None
