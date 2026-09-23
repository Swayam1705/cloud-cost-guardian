"""Aggregates findings into a ScanReport."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from cloud_cost_guardian import __version__
from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.reports import (
    DetectorRun,
    ProtectedResource,
    ScanReport,
    ScanSummary,
)

STANDARD_LIMITATIONS: tuple[str, ...] = (
    "Costs are reference estimates from a local pricing catalog, not billing data.",
    "Snapshot cost assumes full volume size; real incremental snapshots are usually cheaper.",
    "Low CPU utilization does not prove waste; memory, network and IO are not evaluated.",
    "RDS findings are recommendations only and are never remediated automatically.",
    "Reserved Instances, Savings Plans and free-tier allowances are not modelled.",
)


class ReportBuilder:
    def __init__(
        self, *, mode: str, region: str, pricing_catalog: str, pricing_disclaimer: str
    ) -> None:
        self._mode = mode
        self._region = region
        self._catalog = pricing_catalog
        self._disclaimer = pricing_disclaimer

    def build(
        self,
        *,
        scan_id: str,
        timestamp: datetime,
        findings: Iterable[Finding],
        resources_scanned: int,
        detector_runs: Iterable[DetectorRun] = (),
        policy: dict[str, Any] | None = None,
        warnings: Iterable[str] = (),
        extra_limitations: Iterable[str] = (),
    ) -> ScanReport:
        ordered = sorted(
            findings,
            key=lambda f: (
                -f.severity.rank,
                -f.estimated_monthly_savings,
                f.category.value,
                f.resource_id,
            ),
        )
        by_cat = Counter(f.category.value for f in ordered)
        by_sev = Counter(f.severity.value for f in ordered)
        unprotected = [f for f in ordered if not f.protected]
        monthly_waste = round(sum(f.estimated_monthly_cost for f in unprotected), 2)
        monthly_savings = round(sum(f.estimated_monthly_savings for f in unprotected), 2)
        summary = ScanSummary(
            resources_scanned=resources_scanned,
            total_findings=len(ordered),
            estimated_monthly_waste=monthly_waste,
            estimated_annual_waste=round(monthly_waste * 12, 2),
            estimated_monthly_savings=monthly_savings,
            estimated_annual_savings=round(monthly_savings * 12, 2),
            findings_by_category=dict(sorted(by_cat.items())),
            findings_by_severity={s: by_sev.get(s, 0) for s in ("high", "medium", "low")},
            protected_findings=sum(1 for f in ordered if f.protected),
            cleanup_eligible=sum(1 for f in ordered if f.cleanup_eligible),
            recommendations_only=sum(
                1 for f in ordered if not f.cleanup_eligible and not f.protected
            ),
        )
        protected = tuple(
            ProtectedResource(
                resource_id=f.resource_id,
                resource_type=f.resource_type.value,
                reason=f.protection_reason or "protected",
            )
            for f in ordered
            if f.protected
        )
        return ScanReport(
            scan_id=scan_id,
            scan_timestamp=timestamp,
            mode=self._mode,
            region=self._region,
            tool_version=__version__,
            summary=summary,
            findings=tuple(ordered),
            protected_resources=protected,
            detector_runs=tuple(detector_runs),
            limitations=(*STANDARD_LIMITATIONS, *extra_limitations),
            pricing_disclaimer=self._disclaimer,
            pricing_catalog=self._catalog,
            policy=policy or {},
            warnings=tuple(warnings),
        )
