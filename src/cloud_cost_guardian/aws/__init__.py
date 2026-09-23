"""boto3 integration layer. Read-only unless the remediation module explicitly asks otherwise."""

from cloud_cost_guardian.aws.client_factory import AWSClientFactory
from cloud_cost_guardian.aws.errors import (
    AWSAccessDeniedError,
    AWSServiceError,
    translate_client_error,
)
from cloud_cost_guardian.aws.inventory_source import AWSInventorySource

__all__ = [
    "AWSAccessDeniedError",
    "AWSClientFactory",
    "AWSInventorySource",
    "AWSServiceError",
    "translate_client_error",
]
