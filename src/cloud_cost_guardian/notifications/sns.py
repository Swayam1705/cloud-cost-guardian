"""Amazon SNS provider (optional; used by the Terraform/Lambda deployment)."""

from __future__ import annotations

from typing import Any

from cloud_cost_guardian.exceptions import NotificationError
from cloud_cost_guardian.models.reports import ScanReport
from cloud_cost_guardian.notifications.base import NotificationProvider, NotificationResult
from cloud_cost_guardian.reporting.markdown_report import render_markdown


class SNSNotificationProvider(NotificationProvider):
    def __init__(self, sns_client: Any, topic_arn: str | None) -> None:
        if not topic_arn or not topic_arn.startswith("arn:aws"):
            raise NotificationError(
                "SNS provider selected but CCG_SNS_TOPIC_ARN is not a valid ARN"
            )
        self._sns = sns_client
        self._topic = topic_arn

    @property
    def name(self) -> str:
        return "sns"

    def send_report(self, report: ScanReport) -> NotificationResult:
        s = report.summary
        subject = f"[CCG] {s.total_findings} findings, est. ${s.estimated_monthly_savings:,.2f}/mo"[
            :100
        ]
        try:
            resp = self._sns.publish(
                TopicArn=self._topic, Subject=subject, Message=render_markdown(report)[:262000]
            )
        except Exception as exc:
            raise NotificationError(f"SNS publish failed: {type(exc).__name__}") from None
        return NotificationResult(self.name, True, f"message id {resp.get('MessageId', '?')}")
