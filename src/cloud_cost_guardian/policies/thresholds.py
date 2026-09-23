"""Detection thresholds — the tunable knobs every detector reads from."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cloud_cost_guardian.config import Settings


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    ebs_enabled: bool = True
    ebs_min_age_days: int = Field(default=7, ge=0)

    ec2_enabled: bool = True
    ec2_cpu_threshold_percent: float = Field(default=5.0, ge=0, le=100)
    ec2_observation_hours: int = Field(default=48, ge=1)
    ec2_min_samples: int = Field(default=12, ge=1)

    eip_enabled: bool = True

    rds_enabled: bool = True
    rds_cpu_threshold_percent: float = Field(default=10.0, ge=0, le=100)
    rds_observation_hours: int = Field(default=168, ge=1)
    rds_min_samples: int = Field(default=24, ge=1)

    snapshot_enabled: bool = True
    snapshot_max_age_days: int = Field(default=90, ge=1)

    @classmethod
    def from_settings(cls, settings: Settings) -> Thresholds:
        return cls(
            ebs_enabled=settings.ebs_enabled,
            ebs_min_age_days=settings.ebs_min_age_days,
            ec2_enabled=settings.ec2_enabled,
            ec2_cpu_threshold_percent=settings.ec2_cpu_threshold_percent,
            ec2_observation_hours=settings.ec2_observation_hours,
            ec2_min_samples=settings.ec2_min_samples,
            eip_enabled=settings.eip_enabled,
            rds_enabled=settings.rds_enabled,
            rds_cpu_threshold_percent=settings.rds_cpu_threshold_percent,
            rds_observation_hours=settings.rds_observation_hours,
            rds_min_samples=settings.rds_min_samples,
            snapshot_enabled=settings.snapshot_enabled,
            snapshot_max_age_days=settings.snapshot_max_age_days,
        )

    def describe(self) -> dict[str, Any]:
        return self.model_dump()
