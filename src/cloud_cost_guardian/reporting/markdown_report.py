"""Markdown report rendering — human readable, safe for GitHub/Slack previews."""

from __future__ import annotations

from pathlib import Path

from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.reports import ScanReport

_CATEGORY_LABEL = {
    "unattached_ebs": "Unattached EBS volumes",
    "underutilized_ec2": "Potentially underutilized EC2",
    "unassociated_eip": "Unassociated Elastic IPs",
    "rds_rightsizing": "RDS right-sizing recommendations",
    "old_snapshot": "Old snapshots",
}


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _status(f: Finding) -> str:
    if f.protected:
        return "PROTECTED"
    if f.cleanup_eligible:
        return "CLEANUP CANDIDATE"
    return "RECOMMENDATION"


def _evidence_line(f: Finding) -> str:
    keys = (
        "age_days",
        "cpu_average_percent",
        "cpu_peak_percent",
        "observed_hours",
        "size_gib",
        "volume_size_gib",
        "instance_type",
        "instance_class",
        "suggested_instance_class",
        "public_ip",
    )
    parts = [f"{k}={f.evidence[k]}" for k in keys if k in f.evidence and f.evidence[k] is not None]
    return ", ".join(parts)


def render_markdown(report: ScanReport) -> str:
    s = report.summary
    lines: list[str] = [
        "# Cloud Cost Guardian — Scan Report",
        "",
        f"- **Scan ID:** `{report.scan_id}`",
        f"- **Timestamp:** {report.scan_timestamp.isoformat()}",
        f"- **Mode:** {report.mode}",
        f"- **Region:** {report.region}",
        f"- **Tool version:** {report.tool_version}",
        f"- **Pricing catalog:** {report.pricing_catalog}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Resources scanned | {s.resources_scanned} |",
        f"| Findings | {s.total_findings} |",
        f"| Estimated monthly waste (unprotected) | {_money(s.estimated_monthly_waste)} |",
        f"| Estimated annualized waste | {_money(s.estimated_annual_waste)} |",
        f"| Estimated monthly savings | {_money(s.estimated_monthly_savings)} |",
        f"| Estimated annualized savings | {_money(s.estimated_annual_savings)} |",
        f"| Protected findings | {s.protected_findings} |",
        f"| Cleanup eligible | {s.cleanup_eligible} |",
        f"| Recommendation only | {s.recommendations_only} |",
        "",
        "### Findings by category",
        "",
        "| Category | Count |",
        "|---|---|",
    ]
    for cat, count in s.findings_by_category.items():
        lines.append(f"| {_CATEGORY_LABEL.get(cat, cat)} | {count} |")
    lines += ["", "### Findings by severity", "", "| Severity | Count |", "|---|---|"]
    for sev, count in s.findings_by_severity.items():
        lines.append(f"| {sev} | {count} |")

    if report.findings:
        lines += [
            "",
            "## Findings",
            "",
            "| Status | Severity | Category | Resource | Monthly cost | Monthly savings "
            "| Evidence | Recommendation |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for f in report.findings:
            lines.append(
                f"| {_status(f)} | {f.severity.value} "
                f"| {_CATEGORY_LABEL.get(f.category.value, f.category.value)} "
                f"| `{f.resource_id}` | {_money(f.estimated_monthly_cost)} "
                f"| {_money(f.estimated_monthly_savings)} "
                f"| {_md_escape(_evidence_line(f))} | {f.recommended_action.value} |"
            )
        lines += ["", "### Reasons", ""]
        for f in report.findings:
            lines.append(f"- `{f.resource_id}` — {_md_escape(f.reason)}")
            if f.protected and f.protection_reason:
                lines.append(f"  - protected: {_md_escape(f.protection_reason)}")
            elif not f.cleanup_eligible:
                lines.append(
                    "  - not cleanup-eligible: "
                    f"{_md_escape(str(f.metadata.get('cleanup_policy', '')))}"
                )
    else:
        lines += [
            "",
            "## Findings",
            "",
            "No findings. Nothing looked wasteful under the current policy.",
        ]

    if report.protected_resources:
        lines += ["", "## Protected resources (never auto-remediated)", ""]
        for p in report.protected_resources:
            lines.append(f"- `{p.resource_id}` ({p.resource_type}) — {_md_escape(p.reason)}")

    candidates = report.cleanup_candidates
    lines += ["", "## Cleanup candidates", ""]
    if candidates:
        lines.append(
            "Run `ccg cleanup --dry-run` to preview, then "
            "`ccg cleanup --resource <ID> --approve` per resource."
        )
        lines.append("")
        for f in candidates:
            lines.append(
                f"- `{f.resource_id}` — {f.recommended_action.value} — "
                f"{_money(f.estimated_monthly_savings)}/month"
            )
    else:
        lines.append("None.")

    if report.detector_runs:
        lines += [
            "",
            "## Detector runs",
            "",
            "| Detector | Status | Inspected | Findings | Duration (ms) | Error |",
            "|---|---|---|---|---|---|",
        ]
        for d in report.detector_runs:
            lines.append(
                f"| {d.name} | {d.status} | {d.resources_inspected} | {d.findings} "
                f"| {d.duration_ms} | {_md_escape(d.error or '')} |"
            )

    if report.warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- {_md_escape(w)}" for w in report.warnings]

    lines += ["", "## Limitations", ""]
    lines += [f"- {lim}" for lim in report.limitations]
    lines += ["", "## Pricing disclaimer", "", report.pricing_disclaimer, ""]
    return "\n".join(lines)


def write_markdown(report: ScanReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return path
