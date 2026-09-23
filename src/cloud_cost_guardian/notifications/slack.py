"""Slack incoming-webhook provider (optional; the webhook URL is never logged)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from pydantic import SecretStr

from cloud_cost_guardian.exceptions import NotificationError
from cloud_cost_guardian.models.reports import ScanReport
from cloud_cost_guardian.notifications.base import NotificationProvider, NotificationResult
from cloud_cost_guardian.reporting.slack_format import build_slack_payload

_ALLOWED_PREFIX = "https://hooks.slack.com/"


class SlackNotificationProvider(NotificationProvider):
    def __init__(self, webhook_url: SecretStr | None, *, timeout_seconds: int = 10) -> None:
        if webhook_url is None or not webhook_url.get_secret_value():
            raise NotificationError("Slack provider selected but CCG_SLACK_WEBHOOK_URL is not set")
        url = webhook_url.get_secret_value()
        if not url.startswith(_ALLOWED_PREFIX):
            raise NotificationError("Slack webhook URL must start with https://hooks.slack.com/")
        self._url = webhook_url
        self._timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "slack"

    def send_report(self, report: ScanReport) -> NotificationResult:
        body = json.dumps(build_slack_payload(report)).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 - scheme/host validated in __init__
            self._url.get_secret_value(),
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "cloud-cost-guardian"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
                status = int(resp.status)
        except urllib.error.HTTPError as exc:
            raise NotificationError(f"Slack webhook returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise NotificationError(f"Slack webhook unreachable: {type(exc).__name__}") from None
        if status >= 300:
            raise NotificationError(f"Slack webhook returned HTTP {status}")
        return NotificationResult(self.name, True, "posted to Slack webhook")
