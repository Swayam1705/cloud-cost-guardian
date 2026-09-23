from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from cloud_cost_guardian.config import NotificationProviderName, Settings
from cloud_cost_guardian.exceptions import ConfigurationError, NotificationError
from cloud_cost_guardian.logging_config import redact
from cloud_cost_guardian.notifications.factory import build_notification_provider
from cloud_cost_guardian.notifications.mock import MockNotificationProvider
from cloud_cost_guardian.notifications.slack import SlackNotificationProvider
from cloud_cost_guardian.notifications.sns import SNSNotificationProvider
from cloud_cost_guardian.reporting.report_builder import ReportBuilder
from tests.conftest import NOW


@pytest.fixture
def report() -> Any:
    return ReportBuilder(
        mode="demo", region="us-east-1", pricing_catalog="c", pricing_disclaimer="d"
    ).build(scan_id="scan-x", timestamp=NOW, findings=[], resources_scanned=0)


def test_mock_provider_writes_artifact(tmp_path: Path, report: Any) -> None:
    provider = MockNotificationProvider(tmp_path / "artifacts")
    result = provider.send_report(report)
    assert result.delivered and result.provider == "mock"
    payload = json.loads(provider.latest_path.read_text(encoding="utf-8"))
    assert payload["blocks"][0]["type"] == "header"
    assert (tmp_path / "artifacts" / "notifications" / "scan-x-slack-message.json").exists()


def test_slack_requires_webhook() -> None:
    with pytest.raises(NotificationError, match="not set"):
        SlackNotificationProvider(None)
    with pytest.raises(NotificationError, match=r"hooks\.slack\.com"):
        SlackNotificationProvider(SecretStr("https://evil.example.com/x"))


def test_settings_reject_slack_without_webhook() -> None:
    with pytest.raises(ValueError):
        Settings(notification_provider=NotificationProviderName.SLACK, _env_file=None)  # type: ignore[call-arg]


def test_slack_success_and_failure(monkeypatch: pytest.MonkeyPatch, report: Any) -> None:
    calls: list[Any] = []

    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    def fake_open(req: Any, timeout: int) -> _Resp:
        calls.append(req)
        return _Resp(b"ok")

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    provider = SlackNotificationProvider(
        SecretStr("https://hooks.slack.com/services/T000/B000/XXXX")
    )
    assert provider.send_report(report).delivered
    assert calls[0].get_header("Content-type") == "application/json"

    def fail_open(req: Any, timeout: int) -> _Resp:
        raise urllib.error.HTTPError(req.full_url, 403, "forbidden", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", fail_open)
    with pytest.raises(NotificationError) as exc:
        provider.send_report(report)
    # error message must never leak the webhook
    assert "hooks.slack.com/services" not in str(exc.value)


def test_secret_redaction() -> None:
    assert "XXXX" not in redact("posting to https://hooks.slack.com/services/T000/B000/XXXX now")
    assert "AKIA" not in redact("key AKIAABCDEFGHIJKLMNOP")
    assert redact("password=hunter2") == "[REDACTED]"
    assert redact("plain text") == "plain text"


def test_settings_summary_masks_webhook() -> None:
    s = Settings(
        notification_provider=NotificationProviderName.SLACK,
        slack_webhook_url=SecretStr("https://hooks.slack.com/services/T/B/SECRET"),
        _env_file=None,  # type: ignore[call-arg]
    )
    assert "SECRET" not in json.dumps(s.summary())
    assert "SECRET" not in repr(s)


class _FakeSNS:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> dict[str, str]:
        if self.fail:
            raise RuntimeError("boom")
        self.published.append(kwargs)
        return {"MessageId": "m-1"}


def test_sns_provider(report: Any) -> None:
    sns = _FakeSNS()
    p = SNSNotificationProvider(sns, "arn:aws:sns:us-east-1:123456789012:topic")
    assert p.send_report(report).delivered
    assert sns.published[0]["TopicArn"].endswith(":topic")
    with pytest.raises(NotificationError):
        SNSNotificationProvider(
            _FakeSNS(fail=True), "arn:aws:sns:us-east-1:123456789012:topic"
        ).send_report(report)
    with pytest.raises(NotificationError):
        SNSNotificationProvider(sns, "not-an-arn")


def test_factory_defaults_to_mock(tmp_path: Path) -> None:
    s = Settings(artifacts_dir=tmp_path, _env_file=None)  # type: ignore[call-arg]
    assert isinstance(build_notification_provider(s), MockNotificationProvider)


def test_scan_survives_notification_failure(demo_app: Any) -> None:
    from cloud_cost_guardian.notifications.base import NotificationProvider, NotificationResult

    class Broken(NotificationProvider):
        @property
        def name(self) -> str:
            return "broken"

        def send_report(self, report: Any) -> NotificationResult:
            raise NotificationError("down")

    result = demo_app.scan_service(Broken()).run(notify=True)
    assert result.notification is not None and not result.notification.delivered
    assert result.report.summary.total_findings > 0


def test_invalid_config_error_message_has_no_secret() -> None:
    from cloud_cost_guardian.config import load_settings

    with pytest.raises(ConfigurationError) as exc:
        load_settings(aws_region="not a region")
    assert "invalid configuration" in str(exc.value)
