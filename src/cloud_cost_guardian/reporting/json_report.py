"""JSON report rendering."""

from __future__ import annotations

from pathlib import Path

from cloud_cost_guardian.models.reports import ScanReport


def render_json(report: ScanReport) -> str:
    return report.model_dump_json(indent=2)


def write_json(report: ScanReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_json(report), encoding="utf-8")
    return path


def load_json(path: Path) -> ScanReport:
    return ScanReport.model_validate_json(path.read_text(encoding="utf-8"))
