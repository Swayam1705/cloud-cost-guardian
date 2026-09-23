from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from cloud_cost_guardian.detectors import DetectorContext, EBSDetector, RDSDetector
from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.reports import DetectorRun, ScanReport
from cloud_cost_guardian.reporting.json_report import load_json, render_json, write_json
from cloud_cost_guardian.reporting.markdown_report import render_markdown, write_markdown
from cloud_cost_guardian.reporting.report_builder import STANDARD_LIMITATIONS, ReportBuilder
from cloud_cost_guardian.reporting.slack_format import build_slack_payload
from tests.conftest import NOW, PROTECTED, db, inventory, series, volume


@pytest.fixture
def builder() -> ReportBuilder:
    return ReportBuilder(
        mode="demo", region="us-east-1", pricing_catalog="test-cat", pricing_disclaimer="estimates"
    )


def _findings(ctx: DetectorContext) -> list[Finding]:
    vols = (
        volume("vol-a", age_days=100),
        volume("vol-b", age_days=100, tags=PROTECTED),
        volume("vol-c", age_days=1),
    )
    f = EBSDetector(ctx).detect(inventory(volumes=vols))
    f += RDSDetector(ctx).detect(
        inventory(db_instances=(db(),), metrics={"db-1": series("db-1", hours=200, average=1.0)})
    )
    return f


def test_empty_report(builder: ReportBuilder) -> None:
    r = builder.build(scan_id="s", timestamp=NOW, findings=[], resources_scanned=0)
    assert r.summary.total_findings == 0
    assert r.summary.estimated_monthly_waste == 0
    assert "No findings" in render_markdown(r)
    assert r.summary.findings_by_severity == {"high": 0, "medium": 0, "low": 0}
    assert list(r.limitations) == list(STANDARD_LIMITATIONS)


def test_report_aggregates(builder: ReportBuilder, ctx: DetectorContext) -> None:
    findings = _findings(ctx)
    r = builder.build(
        scan_id="s",
        timestamp=NOW,
        findings=findings,
        resources_scanned=4,
        detector_runs=[DetectorRun(name="ebs", status="ok")],
    )
    s = r.summary
    assert s.total_findings == 4
    assert s.protected_findings == 1
    assert s.cleanup_eligible == 1
    assert s.recommendations_only == 2  # too-new volume + RDS
    assert s.findings_by_category == {"rds_rightsizing": 1, "unattached_ebs": 3}
    # protected finding excluded from waste totals
    expected = round(sum(f.estimated_monthly_cost for f in findings if not f.protected), 2)
    assert s.estimated_monthly_waste == expected
    assert s.estimated_annual_waste == round(expected * 12, 2)
    assert [p.resource_id for p in r.protected_resources] == ["vol-b"]
    assert [f.resource_id for f in r.cleanup_candidates] == ["vol-a"]
    # ordering: highest severity / savings first
    ranks = [f.severity.rank for f in r.findings]
    assert ranks == sorted(ranks, reverse=True)


def test_json_roundtrip(builder: ReportBuilder, ctx: DetectorContext, tmp_path: Path) -> None:
    r = builder.build(scan_id="s", timestamp=NOW, findings=_findings(ctx), resources_scanned=4)
    path = write_json(r, tmp_path / "x" / "r.json")
    loaded = load_json(path)
    assert loaded == r
    assert json.loads(render_json(r))["schema_version"] == "1.0"


def test_markdown_contains_key_sections(
    builder: ReportBuilder, ctx: DetectorContext, tmp_path: Path
) -> None:
    r = builder.build(
        scan_id="s", timestamp=NOW, findings=_findings(ctx), resources_scanned=4, warnings=["w1"]
    )
    md = render_markdown(r)
    for heading in (
        "## Summary",
        "## Findings",
        "## Protected resources",
        "## Cleanup candidates",
        "## Limitations",
        "## Pricing disclaimer",
        "## Warnings",
    ):
        assert heading in md
    assert "PROTECTED" in md and "CLEANUP CANDIDATE" in md and "RECOMMENDATION" in md
    write_markdown(r, tmp_path / "r.md")
    assert (tmp_path / "r.md").read_text(encoding="utf-8") == md


def test_markdown_escapes_pipes(builder: ReportBuilder, ctx: DetectorContext) -> None:
    [f] = EBSDetector(ctx).detect(inventory(volumes=(volume("vol-a", age_days=100),)))
    f = f.model_copy(update={"reason": "has | pipe"})
    md = render_markdown(
        builder.build(scan_id="s", timestamp=NOW, findings=[f], resources_scanned=1)
    )
    assert "has \\| pipe" in md


def test_slack_payload_shape(builder: ReportBuilder, ctx: DetectorContext) -> None:
    r = builder.build(scan_id="s", timestamp=NOW, findings=_findings(ctx), resources_scanned=4)
    payload = build_slack_payload(r)
    assert payload["text"].startswith("Cloud Cost Guardian")
    assert payload["blocks"][0]["type"] == "header"
    assert len(payload["blocks"][0]["text"]["text"]) <= 150
    assert "vol-a" in payload["blocks"][2]["text"]["text"]


def test_large_report(builder: ReportBuilder, ctx: DetectorContext) -> None:
    vols = tuple(volume(f"vol-{i:05d}", age_days=100 + i) for i in range(2000))
    findings = EBSDetector(ctx).detect(inventory(volumes=vols))
    r = builder.build(scan_id="s", timestamp=NOW, findings=findings, resources_scanned=2000)
    assert r.summary.total_findings == 2000
    md = render_markdown(r)
    assert md.count("vol-0") >= 2000
    payload = build_slack_payload(r)
    assert len(payload["blocks"][2]["text"]["text"]) <= 2900


def test_malformed_report_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"scan_id": "x"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_json(bad)
    with pytest.raises(ValueError):
        ScanReport.model_validate({"scan_id": 1})


def test_finding_serialization_is_stable(ctx: DetectorContext) -> None:
    [f] = EBSDetector(ctx).detect(inventory(volumes=(volume("vol-a", age_days=100),)))
    dumped = f.model_dump(mode="json")
    assert Finding.model_validate(dumped) == f
    assert dumped["detected_at"].endswith("Z") or "+00:00" in dumped["detected_at"]
    assert (NOW + timedelta(0)).isoformat().startswith(dumped["detected_at"][:19])
