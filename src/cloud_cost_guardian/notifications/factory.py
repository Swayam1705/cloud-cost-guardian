from __future__ import annotations

from typing import Any

from cloud_cost_guardian.config import NotificationProviderName, Settings
from cloud_cost_guardian.notifications.base import NotificationProvider
from cloud_cost_guardian.notifications.mock import MockNotificationProvider
from cloud_cost_guardian.notifications.slack import SlackNotificationProvider
from cloud_cost_guardian.notifications.sns import SNSNotificationProvider


def build_notification_provider(
    settings: Settings, sns_client: Any | None = None
) -> NotificationProvider:
    if settings.notification_provider is NotificationProviderName.SLACK:
        return SlackNotificationProvider(settings.slack_webhook_url)
    if settings.notification_provider is NotificationProviderName.SNS:
        if sns_client is None:
            from cloud_cost_guardian.aws.client_factory import AWSClientFactory

            sns_client = AWSClientFactory(settings).client("sns")
        return SNSNotificationProvider(sns_client, settings.sns_topic_arn)
    return MockNotificationProvider(settings.artifacts_dir)
