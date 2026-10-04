"""Deterministic FinOps Intelligence Engine."""

from __future__ import annotations

from cloud_cost_guardian.models.findings import Finding


def enrich_findings(findings: list[Finding]) -> None:
    """Run the deterministic FinOps intelligence pipeline on all findings."""
    for f in findings:
        _enrich_tags(f)
        _enrich_confidence(f)
        _enrich_priority(f)


def _enrich_tags(f: Finding) -> None:
    """Extract standardized ownership/context from raw tags."""
    tags = {k.lower(): v for k, v in f.metadata.get("tags", {}).items()}
    f.team = tags.get("team") or tags.get("project") or tags.get("costcenter")
    f.owner = tags.get("owner") or tags.get("contact")
    f.environment = tags.get("environment") or tags.get("env")


def _enrich_confidence(f: Finding) -> None:
    """
    Determine confidence based on objective observation metrics.
    No AI involved: strictly deterministic rules.
    """
    reasons = []
    confidence = "LOW"

    # Evaluate observation period for compute/db
    obs_hours = f.metadata.get("observed_hours", 0)
    if obs_hours > 0:
        if obs_hours >= 168:  # 7 days
            confidence = "HIGH"
            reasons.append(f"Analyzed {obs_hours} hours of continuous telemetry data.")
        elif obs_hours >= 24:
            confidence = "MEDIUM"
            reasons.append(f"Analyzed {obs_hours} hours of telemetry data (minimum 168h ideal).")
        else:
            confidence = "LOW"
            reasons.append(f"Insufficient observation window ({obs_hours} hours).")

    # Evaluate static resource age for storage/ips
    age = f.metadata.get("age_days", 0)
    if age > 0 and obs_hours == 0:
        if age >= 30:
            confidence = "HIGH"
            reasons.append(f"Resource has been orphaned/idle for {age} days.")
        elif age >= 7:
            confidence = "MEDIUM"
            reasons.append(f"Resource is recently orphaned ({age} days).")
        else:
            confidence = "LOW"
            reasons.append(f"Resource is very new ({age} days).")

    if f.protected:
        reasons.append(f"Protection tag detected: {f.protection_reason}.")

    if not reasons:
        reasons.append("Insufficient metadata to establish high confidence.")

    f.confidence = confidence
    f.confidence_reasons = reasons


def _enrich_priority(f: Finding) -> None:
    """
    Calculate a deterministic business priority score.
    Formula: Base (savings) * Confidence Multiplier * Severity Multiplier
    """
    if f.protected:
        f.priority = "P4"
        f.priority_score = 0.0
        return

    # Base score is the monthly savings
    score = f.estimated_monthly_savings
    if score == 0 and f.estimated_monthly_cost > 0:
        # For recommendations without direct savings, use a fraction of cost
        score = f.estimated_monthly_cost * 0.2

    # Confidence modifier
    conf_multipliers = {"HIGH": 1.2, "MEDIUM": 0.8, "LOW": 0.3}
    score *= conf_multipliers.get(f.confidence, 0.3)

    # Severity modifier
    sev_multipliers = {"high": 1.5, "medium": 1.0, "low": 0.5}
    score *= sev_multipliers.get(f.severity.value, 1.0)

    # Actionability modifier
    if f.cleanup_eligible:
        score *= 1.5

    f.priority_score = round(score, 2)

    if score >= 50.0:
        f.priority = "P1"
    elif score >= 15.0:
        f.priority = "P2"
    elif score > 0.0:
        f.priority = "P3"
    else:
        f.priority = "P4"
