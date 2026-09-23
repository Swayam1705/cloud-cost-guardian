"""Slack Block Kit payload for a scan report (also used by the mock provider)."""

from __future__ import annotations

from typing import Any

from cloud_cost_guardian.models.reports import ScanReport


def build_slack_payload(report: ScanReport, *, max_findings: int = 10) -> dict[str, Any]:
    s = report.summary
    header = (
        f"Cloud Cost Guardian — {s.total_findings} findings, "
        f"est. ${s.estimated_monthly_savings:,.2f}/month savings"
    )
    fields = [
        f"*Mode:* {report.mode}",
        f"*Region:* {report.region}",
        f"*Resources scanned:* {s.resources_scanned}",
        f"*Monthly waste (est.):* ${s.estimated_monthly_waste:,.2f}",
        f"*Annual waste (est.):* ${s.estimated_annual_waste:,.2f}",
        f"*Cleanup eligible:* {s.cleanup_eligible}",
        f"*Protected:* {s.protected_findings}",
        f"*Recommendations:* {s.recommendations_only}",
    ]
    top = report.findings[:max_findings]
    rows = [
        f"• `{f.resource_id}` — {f.category.value} — ${f.estimated_monthly_savings:,.2f}/mo"
        + (" (protected)" if f.protected else "")
        for f in top
    ]
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": header[:150]}},
        {"type": "section", "fields": [{"type": "mrkdwn", "text": t} for t in fields]},
    ]
    if rows:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(rows)[:2900]}}
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"scan `{report.scan_id}` · estimates only · "
                        f"catalog {report.pricing_catalog}"
                    ),
                }
            ],
        }
    )
    return {"text": header, "blocks": blocks}
