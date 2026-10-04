"""FinOps Markdown report generation."""

from __future__ import annotations

from cloud_cost_guardian.models.reports import ScanReport


def render_markdown(report: ScanReport) -> str:
    lines = [
        "# Cloud Cost Guardian — FinOps Intelligence Report",
        "",
        f"- **Scan ID:** `{report.scan_id}`",
        f"- **Timestamp:** {report.timestamp.isoformat()}",
        f"- **Mode:** {report.settings.mode}",
        f"- **Region:** {report.settings.aws_region}",
        f"- **Pricing catalog:** {report.settings.pricing_catalog}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Resources scanned | {report.summary.resources_scanned} |",
        f"| Findings | {report.summary.total_findings} |",
        f"| Estimated monthly waste | ${report.summary.estimated_monthly_waste:,.2f} |",
        f"| Estimated annualized waste | ${report.summary.estimated_annual_waste:,.2f} |",
        f"| Estimated monthly savings | ${report.summary.estimated_monthly_savings:,.2f} |",
        f"| Protected findings | {report.summary.protected_findings} |",
        "",
        "## Tag Quality & Ownership",
        "",
    ]

    for team, waste in report.summary.waste_by_team.items():
        lines.append(f"- **{team}**: ${waste:,.2f} / month")

    lines.extend(
        [
            "",
            f"- Resources missing Team tag: {report.summary.missing_team_count}",
            f"- Resources missing Owner tag: {report.summary.missing_owner_count}",
            f"- Resources missing Environment tag: {report.summary.missing_environment_count}",
            "",
        ]
    )

    if not report.findings:
        lines.extend(["## Top Actions", "", "No findings. Architecture is cost-efficient."])
    else:
        lines.extend(
            [
                "## Top 10 FinOps Actions",
                "",
                "Ordered by deterministic priority model (Cost, Confidence, Actionability).",
                "",
            ]
        )

        # Sort by priority score
        top_findings = sorted(report.findings, key=lambda x: x.priority_score, reverse=True)[:10]

        for i, f in enumerate(top_findings, 1):
            lines.extend(
                [
                    f"### {i}. {f.category.value.replace('_', ' ').title()} ({f.resource_id})",
                    f"- **Priority:** {f.priority} (Score: {f.priority_score})",
                    f"- **Confidence:** {f.confidence}",
                    f"- **Financial Impact:** ${f.estimated_monthly_cost:,.2f}/mo cost, **${f.estimated_monthly_savings:,.2f}/mo potential savings**",
                    f"- **Ownership:** Team: {f.team or 'Unknown'} | Owner: {f.owner or 'Unknown'} | Env: {f.environment or 'Unknown'}",
                    f"- **Protection Status:** {'PROTECTED (Action Blocked)' if f.protected else 'Unprotected'}",
                    "",
                    "**Why was this flagged?**",
                    f"> {f.description}",
                ]
            )
            for reason in f.confidence_reasons:
                lines.append(f"> {reason}")

            lines.extend(["", "**Recommended Action:**", f"`{f.recommended_action.value}`", ""])

    return "\n".join(lines) + "\n"
