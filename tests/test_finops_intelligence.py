"""Tests for the deterministic FinOps Intelligence engine."""

from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.resources import ResourceType
from cloud_cost_guardian.services.finops import enrich_findings


def _dummy_finding(
    cost: float,
    savings: float,
    tags: dict,
    hours: int = 0,
    age: int = 0,
    protected: bool = False,
    eligible: bool = True,
) -> Finding:
    return Finding(
        finding_id="123",
        resource_id="res-1",
        resource_type=ResourceType.EC2_INSTANCE,
        region="us-east-1",
        severity="medium",
        category="underutilized_ec2",
        description="test",
        estimated_monthly_cost=cost,
        estimated_monthly_savings=savings,
        protected=protected,
        cleanup_eligible=eligible,
        metadata={"tags": tags, "observed_hours": hours, "age_days": age},
    )


def test_tag_parsing():
    f = _dummy_finding(0, 0, {"Team": "Data", "Owner": "Alice", "env": "Prod"})
    enrich_findings([f])
    assert f.team == "Data"
    assert f.owner == "Alice"
    assert f.environment == "Prod"


def test_confidence_scoring_hours():
    # > 168 hours = HIGH
    f1 = _dummy_finding(0, 0, {}, hours=200)
    enrich_findings([f1])
    assert f1.confidence == "HIGH"

    # > 24 hours = MEDIUM
    f2 = _dummy_finding(0, 0, {}, hours=48)
    enrich_findings([f2])
    assert f2.confidence == "MEDIUM"

    # < 24 hours = LOW
    f3 = _dummy_finding(0, 0, {}, hours=12)
    enrich_findings([f3])
    assert f3.confidence == "LOW"


def test_priority_scoring_logic():
    # Base savings: 100
    # HIGH confidence (* 1.2)
    # Medium severity (* 1.0)
    # Cleanup eligible (* 1.5)
    # Total = 100 * 1.2 * 1.0 * 1.5 = 180 (P1)
    f = _dummy_finding(100, 100, {}, hours=200, eligible=True)
    enrich_findings([f])
    assert f.priority == "P1"
    assert f.priority_score == 180.0


def test_protected_resources_are_p4():
    f = _dummy_finding(1000, 1000, {}, hours=200, protected=True)
    enrich_findings([f])
    assert f.priority == "P4"
    assert f.priority_score == 0.0


def test_tie_breaking_determinism():
    f1 = _dummy_finding(10, 10, {}, hours=10)  # LOW Conf
    f2 = _dummy_finding(10, 10, {}, hours=200)  # HIGH Conf
    enrich_findings([f1, f2])
    assert f2.priority_score > f1.priority_score
