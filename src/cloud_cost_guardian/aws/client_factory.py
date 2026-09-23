"""Creates configured, cached boto3 clients."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from cloud_cost_guardian.config import Settings


class AWSClientFactory:
    """One session, one client per service, with retries and timeouts applied uniformly."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = boto3.session.Session(
            profile_name=settings.aws_profile or None, region_name=settings.aws_region
        )
        self._config = BotoConfig(
            region_name=settings.aws_region,
            retries={"max_attempts": settings.aws_max_retries, "mode": "adaptive"},
            connect_timeout=settings.aws_connect_timeout,
            read_timeout=settings.aws_read_timeout,
            user_agent_extra="cloud-cost-guardian",
        )
        self._clients: dict[str, Any] = {}

    @property
    def region(self) -> str:
        return self._settings.aws_region

    def client(self, service: str) -> Any:
        if service not in self._clients:
            kwargs: dict[str, Any] = {"config": self._config}
            if self._settings.aws_endpoint_url:
                kwargs["endpoint_url"] = self._settings.aws_endpoint_url
            # boto3-stubs types `client` per literal service name; we dispatch dynamically.
            factory: Callable[..., Any] = self._session.client
            self._clients[service] = factory(service, **kwargs)
        return self._clients[service]
