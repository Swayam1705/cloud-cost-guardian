"""The Finding model — the single unit of output produced by detectors."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cloud_cost_guardian.models.resources import ResourceType


class Category(str, Enum):
    UNATTACHED_EBS = "unattached_ebs"
    UNDERUTILIZED_EC2 = "underutilized_ec2"
    UNASSOCIATED_EIP = "unassociated_eip"
    RDS_RIGHTSIZING = "rds_rightsizing"
    OLD_SNAPSHOT = "old_snapshot"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {"low": 1, "medium": 2, "high": 3}[self.value]


class RecommendedAction(str, Enum):
    DELETE_VOLUME = "delete_volume"
    STOP_INSTANCE = "stop_instance"
    RELEASE_EIP = "release_eip"
    REVIEW_RIGHTSIZING = "review_rightsizing"
    DELETE_SNAPSHOT = "delete_snapshot"
    REVIEW = "review"


# Actions that the remediation service is *allowed* to execute after approval.
# RDS actions are deliberately absent — RDS is recommendation-only (see docs/cleanup-safety.md).
DESTRUCTIVE_ACTIONS: frozenset[RecommendedAction] = frozenset(
    {
        RecommendedAction.DELETE_VOLUME,
        RecommendedAction.RELEASE_EIP,
        RecommendedAction.DELETE_SNAPSHOT,
        RecommendedAction.STOP_INSTANCE,
    }
)


def make_finding_id(category: Category, resource_id: str, region: str) -> str:
    digest = hashlib.sha256(f"{category.value}|{region}|{resource_id}".encode()).hexdigest()
    return f"ccg-{digest[:12]}"


class Finding(BaseModel):
    """A validated, immutable observation about a potentially wasteful resource."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: str = Field(pattern=r"^ccg-[0-9a-f]{12}$")
    resource_id: str = Field(min_length=1, max_length=256)
    resource_type: ResourceType
    region: str = Field(min_length=1)
    category: Category
    severity: Severity
    reason: str = Field(min_length=1, max_length=1000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    estimated_monthly_cost: float = Field(ge=0)
    estimated_annual_cost: float = Field(ge=0)
    estimated_monthly_savings: float = Field(ge=0)
    recommended_action: RecommendedAction
    cleanup_eligible: bool
    protected: bool
    protection_reason: str | None = None
    detected_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("detected_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("detected_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("estimated_monthly_cost", "estimated_annual_cost", "estimated_monthly_savings")
    @classmethod
    def _finite(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            raise ValueError("cost values must be finite")
        return round(value, 4)

    @model_validator(mode="after")
    def _consistency(self) -> Finding:
        if self.protected and self.cleanup_eligible:
            raise ValueError("a protected finding can never be cleanup-eligible")
        if self.recommended_action not in DESTRUCTIVE_ACTIONS and self.cleanup_eligible:
            raise ValueError("cleanup_eligible requires a destructive recommended_action")
        if self.resource_type is ResourceType.RDS_INSTANCE and self.cleanup_eligible:
            raise ValueError("RDS findings are recommendation-only and never cleanup-eligible")
        if self.estimated_monthly_savings > self.estimated_monthly_cost + 1e-9:
            raise ValueError("savings cannot exceed estimated cost")
        expected_id = make_finding_id(self.category, self.resource_id, self.region)
        if self.finding_id != expected_id:
            raise ValueError("finding_id does not match category/region/resource_id")
        return self

    @property
    def estimated_annual_savings(self) -> float:
        return round(self.estimated_monthly_savings * 12, 4)
