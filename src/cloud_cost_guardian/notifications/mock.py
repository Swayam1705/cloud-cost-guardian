"""Mock provider: writes the Slack payload to a local artifact instead of calling anything."""

from __future__ import annotations

import json
from pathlib import Path

from cloud_cost_guardian.models.reports import ScanReport
from cloud_cost_guardian.notifications.base import NotificationProvider, NotificationResult
from cloud_cost_guardian.reporting.slack_format import build_slack_payload


class MockNotificationProvider(NotificationProvider):
    def __init__(self, artifacts_dir: Path) -> None:
        self._dir = artifacts_dir / "notifications"

    @property
    def name(self) -> str:
        return "mock"

    @property
    def latest_path(self) -> Path:
        return self._dir / "latest-slack-message.json"

    def send_report(self, report: ScanReport) -> NotificationResult:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = build_slack_payload(report)
        self.latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (self._dir / f"{report.scan_id}-slack-message.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        return NotificationResult(self.name, True, f"written to {self.latest_path}")
