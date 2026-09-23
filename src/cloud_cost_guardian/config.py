"""Application configuration.

All settings can be provided by environment variables prefixed with ``CCG_`` or a local
``.env`` file (never committed). Defaults are deliberately conservative.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cloud_cost_guardian.exceptions import ConfigurationError


class Mode(str, Enum):
    DEMO = "demo"  # fixtures only, zero AWS calls
    LOCAL = "local"  # boto3 against a local endpoint (moto server / LocalStack)
    AWS = "aws"  # real AWS, read-only unless explicitly remediating


class NotificationProviderName(str, Enum):
    MOCK = "mock"
    SLACK = "slack"
    SNS = "sns"


class Settings(BaseSettings):
    """Runtime settings. Instantiate with ``Settings()`` or ``Settings(mode=Mode.DEMO)``."""

    model_config = SettingsConfigDict(
        env_prefix="CCG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Mode & region
    mode: Mode = Mode.DEMO
    aws_region: str = Field(default="us-east-1", pattern=r"^[a-z]{2}(-gov)?-[a-z]+-\d$")
    aws_profile: str | None = None
    aws_endpoint_url: str | None = None
    aws_max_retries: int = Field(default=5, ge=0, le=20)
    aws_connect_timeout: int = Field(default=5, ge=1, le=60)
    aws_read_timeout: int = Field(default=30, ge=1, le=300)

    # Detection thresholds
    ebs_min_age_days: int = Field(default=7, ge=0)
    ebs_enabled: bool = True
    ec2_cpu_threshold_percent: float = Field(default=5.0, ge=0, le=100)
    ec2_observation_hours: int = Field(default=48, ge=1)
    ec2_min_samples: int = Field(default=12, ge=1)
    ec2_enabled: bool = True
    eip_enabled: bool = True
    rds_cpu_threshold_percent: float = Field(default=10.0, ge=0, le=100)
    rds_observation_hours: int = Field(default=168, ge=1)
    rds_min_samples: int = Field(default=24, ge=1)
    rds_enabled: bool = True
    snapshot_max_age_days: int = Field(default=90, ge=1)
    snapshot_enabled: bool = True

    # Protection
    protected_tags: str = "cost-guardian-protected=true,Environment=production"

    # Notifications
    notification_provider: NotificationProviderName = NotificationProviderName.MOCK
    slack_webhook_url: SecretStr | None = None
    sns_topic_arn: str | None = None

    # Paths (relative to CWD unless absolute)
    artifacts_dir: Path = Path("artifacts")
    data_dir: Path = Path("data")
    pricing_catalog_path: Path | None = None
    fixture_inventory_path: Path | None = None
    fixture_metrics_path: Path | None = None

    # Logging
    log_level: str = "INFO"
    log_format: str = "text"

    @field_validator("log_level")
    @classmethod
    def _valid_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {value}")
        return upper

    @field_validator("log_format")
    @classmethod
    def _valid_format(cls, value: str) -> str:
        lower = value.lower()
        if lower not in {"text", "json"}:
            raise ValueError("log_format must be 'text' or 'json'")
        return lower

    @field_validator("aws_endpoint_url")
    @classmethod
    def _valid_endpoint(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("aws_endpoint_url must start with http:// or https://")
        return value

    @model_validator(mode="after")
    def _cross_checks(self) -> Settings:
        if (
            self.notification_provider is NotificationProviderName.SLACK
            and not self.slack_webhook_url
        ):
            raise ValueError("CCG_SLACK_WEBHOOK_URL is required when provider is 'slack'")
        if self.notification_provider is NotificationProviderName.SNS and not self.sns_topic_arn:
            raise ValueError("CCG_SNS_TOPIC_ARN is required when provider is 'sns'")
        if self.mode is Mode.LOCAL and not self.aws_endpoint_url:
            raise ValueError("CCG_AWS_ENDPOINT_URL is required for 'local' mode")
        return self

    # ------------------------------------------------------------------ helpers
    @property
    def protected_tag_pairs(self) -> dict[str, str]:
        """Parse ``k=v,k2=v2`` into a dict. Invalid entries raise ``ConfigurationError``."""
        pairs: dict[str, str] = {}
        for raw in self.protected_tags.split(","):
            item = raw.strip()
            if not item:
                continue
            if "=" not in item:
                raise ConfigurationError(f"protected tag '{item}' must be in key=value form")
            key, _, value = item.partition("=")
            if not key.strip():
                raise ConfigurationError(f"protected tag '{item}' has an empty key")
            pairs[key.strip()] = value.strip()
        if not pairs:
            raise ConfigurationError("at least one protected tag must be configured")
        return pairs

    def summary(self) -> dict[str, Any]:
        """Configuration summary safe to print (secrets masked)."""
        return {
            "mode": self.mode.value,
            "aws_region": self.aws_region,
            "aws_profile": self.aws_profile or "(default chain)",
            "aws_endpoint_url": self.aws_endpoint_url or "(none)",
            "ebs_min_age_days": self.ebs_min_age_days,
            "ec2_cpu_threshold_percent": self.ec2_cpu_threshold_percent,
            "ec2_observation_hours": self.ec2_observation_hours,
            "rds_cpu_threshold_percent": self.rds_cpu_threshold_percent,
            "rds_observation_hours": self.rds_observation_hours,
            "snapshot_max_age_days": self.snapshot_max_age_days,
            "protected_tags": self.protected_tag_pairs,
            "notification_provider": self.notification_provider.value,
            "slack_webhook_url": "***configured***" if self.slack_webhook_url else "(not set)",
            "sns_topic_arn": self.sns_topic_arn or "(not set)",
            "artifacts_dir": str(self.artifacts_dir),
            "data_dir": str(self.data_dir),
            "pricing_catalog_path": str(self.pricing_catalog_path or "(built-in)"),
            "log_level": self.log_level,
            "log_format": self.log_format,
        }


def load_settings(**overrides: Any) -> Settings:
    """Build settings, converting validation errors to ``ConfigurationError``."""
    try:
        return Settings(**overrides)
    except ValueError as exc:  # pydantic ValidationError subclasses ValueError
        raise ConfigurationError(f"invalid configuration: {exc}") from exc
