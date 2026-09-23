from __future__ import annotations

import pytest

from cloud_cost_guardian.config import Settings
from cloud_cost_guardian.exceptions import ConfigurationError
from cloud_cost_guardian.models.findings import (
    Category,
    Finding,
    RecommendedAction,
    Severity,
    make_finding_id,
)
from cloud_cost_guardian.models.resources import ResourceType
from cloud_cost_guardian.policies.cleanup_policy import CleanupPolicy
from cloud_cost_guardian.policies.protection import ProtectionPolicy
from cloud_cost_guardian.policies.thresholds import Thresholds
from tests.conftest import NOW


@pytest.fixture
def policy() -> ProtectionPolicy:
    return ProtectionPolicy(
        {"cost-guardian-protected": "true", "Environment": "production", "Owner": "*"}
    )


@pytest.mark.parametrize(
    "tags",
    [
        {"cost-guardian-protected": "true"},
        {"COST-GUARDIAN-PROTECTED": "TRUE"},
        {" cost-guardian-protected ": " true "},
        {"Environment": "production"},
        {"environment": "Production"},
        {"Owner": "anyone-at-all"},
        {"Name": "x", "Environment": "production", "Team": "y"},
    ],
)
def test_protected_tags(policy: ProtectionPolicy, tags: dict[str, str]) -> None:
    result = policy.evaluate(tags)
    assert result.protected
    assert result.reason


@pytest.mark.parametrize(
    "tags",
    [
        {},
        None,
        {"cost-guardian-protected": "false"},
        {"cost-guardian-protected": "yes"},
        {"Environment": "staging"},
        {"Name": "production"},
        {"cost-guardian-protected-old": "true"},
    ],
)
def test_unprotected_tags(policy: ProtectionPolicy, tags: dict[str, str] | None) -> None:
    assert not policy.is_protected(tags)


def test_policy_requires_rules() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ProtectionPolicy({})


def test_settings_parse_protected_tags() -> None:
    s = Settings(protected_tags=" a=1 , b = 2 ,, ", _env_file=None)  # type: ignore[call-arg]
    assert s.protected_tag_pairs == {"a": "1", "b": "2"}


@pytest.mark.parametrize("raw", ["novalue", "=x", "   "])
def test_settings_reject_bad_protected_tags(raw: str) -> None:
    s = Settings(protected_tags=raw, _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ConfigurationError):
        _ = s.protected_tag_pairs


def _finding(**overrides: object) -> Finding:
    base: dict[str, object] = {
        "finding_id": make_finding_id(Category.UNATTACHED_EBS, "vol-1", "us-east-1"),
        "resource_id": "vol-1",
        "resource_type": ResourceType.EBS_VOLUME,
        "region": "us-east-1",
        "category": Category.UNATTACHED_EBS,
        "severity": Severity.LOW,
        "reason": "test",
        "evidence": {"age_days": 30},
        "estimated_monthly_cost": 1.0,
        "estimated_annual_cost": 12.0,
        "estimated_monthly_savings": 1.0,
        "recommended_action": RecommendedAction.DELETE_VOLUME,
        "cleanup_eligible": False,
        "protected": False,
        "detected_at": NOW,
    }
    base.update(overrides)
    return Finding(**base)  # type: ignore[arg-type]


class TestCleanupPolicy:
    def test_eligible(self) -> None:
        assert CleanupPolicy(Thresholds()).evaluate(_finding()).eligible

    def test_protected_blocked(self) -> None:
        d = CleanupPolicy(Thresholds()).evaluate(_finding(protected=True))
        assert not d.eligible and "protected" in d.blocked_reason

    def test_too_young_blocked(self) -> None:
        d = CleanupPolicy(Thresholds(ebs_min_age_days=60)).evaluate(
            _finding(evidence={"age_days": 30})
        )
        assert not d.eligible and "below minimum" in d.blocked_reason

    def test_missing_age_blocked(self) -> None:
        d = CleanupPolicy(Thresholds()).evaluate(_finding(evidence={}))
        assert not d.eligible and "age evidence missing" in d.blocked_reason

    def test_rds_always_blocked(self) -> None:
        f = _finding(
            finding_id=make_finding_id(Category.RDS_RIGHTSIZING, "db", "us-east-1"),
            resource_id="db",
            resource_type=ResourceType.RDS_INSTANCE,
            category=Category.RDS_RIGHTSIZING,
            recommended_action=RecommendedAction.REVIEW_RIGHTSIZING,
        )
        d = CleanupPolicy(Thresholds()).evaluate(f)
        assert not d.eligible and "RDS" in d.blocked_reason

    def test_ec2_review_only(self) -> None:
        f = _finding(
            finding_id=make_finding_id(Category.UNDERUTILIZED_EC2, "i-1", "us-east-1"),
            resource_id="i-1",
            resource_type=ResourceType.EC2_INSTANCE,
            category=Category.UNDERUTILIZED_EC2,
            recommended_action=RecommendedAction.REVIEW_RIGHTSIZING,
        )
        assert not CleanupPolicy(Thresholds()).evaluate(f).eligible


class TestFindingModelInvariants:
    def test_protected_cannot_be_eligible(self) -> None:
        with pytest.raises(ValueError, match="protected"):
            _finding(protected=True, cleanup_eligible=True)

    def test_rds_cannot_be_eligible(self) -> None:
        with pytest.raises(ValueError):
            _finding(
                finding_id=make_finding_id(Category.RDS_RIGHTSIZING, "db", "us-east-1"),
                resource_id="db",
                resource_type=ResourceType.RDS_INSTANCE,
                category=Category.RDS_RIGHTSIZING,
                recommended_action=RecommendedAction.DELETE_VOLUME,
                cleanup_eligible=True,
            )

    def test_review_action_cannot_be_eligible(self) -> None:
        with pytest.raises(ValueError, match="destructive"):
            _finding(recommended_action=RecommendedAction.REVIEW, cleanup_eligible=True)

    def test_tampered_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="finding_id"):
            _finding(finding_id="ccg-000000000000")

    def test_negative_or_nan_cost_rejected(self) -> None:
        with pytest.raises(ValueError):
            _finding(estimated_monthly_cost=-1)
        with pytest.raises(ValueError):
            _finding(estimated_monthly_cost=float("nan"))

    def test_savings_cannot_exceed_cost(self) -> None:
        with pytest.raises(ValueError, match="savings"):
            _finding(estimated_monthly_savings=5.0)

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            _finding(detected_at=NOW.replace(tzinfo=None))
