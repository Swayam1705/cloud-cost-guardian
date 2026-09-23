"""Uniform error translation for botocore exceptions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)

from cloud_cost_guardian.exceptions import InventorySourceError


class AWSServiceError(InventorySourceError):
    def __init__(self, service: str, operation: str, code: str, message: str) -> None:
        self.service = service
        self.operation = operation
        self.code = code
        super().__init__(f"{service}.{operation} failed [{code}]: {message}")


class AWSAccessDeniedError(AWSServiceError):
    """Permission error — surfaces the missing IAM action clearly."""


class AWSThrottledError(AWSServiceError):
    """Rate limited after retries were exhausted."""


class AWSUnavailableError(AWSServiceError):
    """Network / endpoint / timeout problem."""


_ACCESS_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "UnauthorizedAccess",
}
_THROTTLE_CODES = {
    "Throttling",
    "ThrottlingException",
    "RequestLimitExceeded",
    "TooManyRequestsException",
}


def translate_client_error(exc: Exception, service: str, operation: str) -> AWSServiceError:
    if isinstance(exc, ClientError):
        error: Mapping[str, Any] = exc.response.get("Error") or {}
        code = str(error.get("Code", "ClientError"))
        message = str(error.get("Message", str(exc)))
        if code in _ACCESS_CODES:
            return AWSAccessDeniedError(service, operation, code, message)
        if code in _THROTTLE_CODES:
            return AWSThrottledError(service, operation, code, message)
        return AWSServiceError(service, operation, code, message)
    if isinstance(exc, NoCredentialsError):
        return AWSAccessDeniedError(
            service, operation, "NoCredentials", "no AWS credentials found in the credential chain"
        )
    if isinstance(exc, (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError)):
        return AWSUnavailableError(
            service, operation, type(exc).__name__, "endpoint unreachable or timed out"
        )
    if isinstance(exc, BotoCoreError):
        return AWSServiceError(service, operation, type(exc).__name__, str(exc))
    return AWSServiceError(service, operation, type(exc).__name__, str(exc))
