"""Report models produced by a scan."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cloud_cost_guardian.models.findings import Finding


class DetectorRun(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    status: str  # ok | failed | disabled
    resources_inspected: int = 0
    findings: int = 0
    duration_ms: int = 0
    error: str | None = None


class ProtectedResource(BaseModel):
    model_config = ConfigDict(frozen=True)
    resource_id: str
    resource_type: str
    reason: str


class ScanSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    resources_scanned: int
    total_findings: int
    estimated_monthly_waste: float
    estimated_annual_waste: float
    estimated_monthly_savings: float
    estimated_annual_savings: float
    findings_by_category: dict[str, int]
    findings_by_severity: dict[str, int]
    protected_findings: int
    cleanup_eligible: int
    recommendations_only: int


class ScanReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    scan_id: str
    scan_timestamp: datetime
    mode: str
    region: str
    tool_version: str
    summary: ScanSummary
    findings: tuple[Finding, ...]
    protected_resources: tuple[ProtectedResource, ...] = ()
    detector_runs: tuple[DetectorRun, ...] = ()
    limitations: tuple[str, ...] = ()
    pricing_disclaimer: str
    pricing_catalog: str
    policy: dict[str, Any] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def cleanup_candidates(self) -> list[Finding]:
        return [f for f in self.findings if f.cleanup_eligible]

    @property
    def recommendations(self) -> list[Finding]:
        return [f for f in self.findings if not f.cleanup_eligible and not f.protected]
