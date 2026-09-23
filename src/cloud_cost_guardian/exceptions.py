"""Project-wide exception hierarchy."""

from __future__ import annotations


class CloudCostGuardianError(Exception):
    """Base class for all project exceptions."""


class ConfigurationError(CloudCostGuardianError):
    """Raised when configuration is missing or invalid."""


class InventorySourceError(CloudCostGuardianError):
    """Raised when an inventory source (fixtures, AWS) cannot provide data."""


class PricingError(CloudCostGuardianError):
    """Raised when a price cannot be resolved."""


class NotificationError(CloudCostGuardianError):
    """Raised when a notification provider fails."""


class RemediationBlockedError(CloudCostGuardianError):
    """Raised when a remediation is blocked by policy, protection, approval or verification."""


class RemediationFailedError(CloudCostGuardianError):
    """Raised when a remediation action was attempted but failed."""
