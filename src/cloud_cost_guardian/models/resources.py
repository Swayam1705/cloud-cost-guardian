"""Normalised representations of AWS resources.

Every inventory source (fixtures, moto, real AWS) converts raw API payloads into these
models so detectors and policies never touch boto3 dictionaries directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResourceType(str, Enum):
    EBS_VOLUME = "ebs_volume"
    EC2_INSTANCE = "ec2_instance"
    ELASTIC_IP = "elastic_ip"
    RDS_INSTANCE = "rds_instance"
    EBS_SNAPSHOT = "ebs_snapshot"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class _Resource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    tags: dict[str, str] = Field(default_factory=dict)

    @property
    def resource_type(self) -> ResourceType:  # pragma: no cover - overridden
        raise NotImplementedError

    def age_days(self, now: datetime) -> float | None:
        return None


class EBSVolume(_Resource):
    availability_zone: str
    size_gib: int = Field(ge=1)
    volume_type: str = Field(min_length=1)
    state: str
    create_time: datetime
    attached_instance_id: str | None = None
    iops: int | None = None
    encrypted: bool = False

    _utc = field_validator("create_time")(_ensure_utc)

    @property
    def resource_type(self) -> ResourceType:
        return ResourceType.EBS_VOLUME

    @property
    def is_attached(self) -> bool:
        return self.attached_instance_id is not None

    def age_days(self, now: datetime) -> float:
        return (now - self.create_time).total_seconds() / 86400


class EC2Instance(_Resource):
    instance_type: str = Field(min_length=1)
    state: str
    launch_time: datetime
    availability_zone: str | None = None
    platform: str | None = None
    name: str | None = None

    _utc = field_validator("launch_time")(_ensure_utc)

    @property
    def resource_type(self) -> ResourceType:
        return ResourceType.EC2_INSTANCE

    def age_days(self, now: datetime) -> float:
        return (now - self.launch_time).total_seconds() / 86400


class ElasticIP(_Resource):
    """``resource_id`` is the allocation ID."""

    public_ip: str
    association_id: str | None = None
    instance_id: str | None = None
    network_interface_id: str | None = None
    domain: str = "vpc"

    @property
    def resource_type(self) -> ResourceType:
        return ResourceType.ELASTIC_IP

    @property
    def is_associated(self) -> bool:
        return bool(self.association_id or self.instance_id or self.network_interface_id)


class DBInstance(_Resource):
    """``resource_id`` is the DB instance identifier."""

    engine: str
    instance_class: str
    status: str
    allocated_storage_gib: int = Field(ge=0)
    multi_az: bool = False
    create_time: datetime | None = None

    @field_validator("create_time")
    @classmethod
    def _utc_optional(cls, value: datetime | None) -> datetime | None:
        return _ensure_utc(value) if value else None

    @property
    def resource_type(self) -> ResourceType:
        return ResourceType.RDS_INSTANCE


class Snapshot(_Resource):
    volume_id: str | None = None
    volume_size_gib: int = Field(ge=0)
    start_time: datetime
    state: str
    description: str = ""
    owner_id: str | None = None

    _utc = field_validator("start_time")(_ensure_utc)

    @property
    def resource_type(self) -> ResourceType:
        return ResourceType.EBS_SNAPSHOT

    def age_days(self, now: datetime) -> float:
        return (now - self.start_time).total_seconds() / 86400


class MetricDatapoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    timestamp: datetime
    average: float = Field(ge=0)

    _utc = field_validator("timestamp")(_ensure_utc)


class MetricSeries(BaseModel):
    """A CloudWatch-like series for one resource/metric."""

    model_config = ConfigDict(frozen=True)

    resource_id: str
    metric_name: str
    unit: str = "Percent"
    period_seconds: int = Field(default=3600, ge=60)
    datapoints: tuple[MetricDatapoint, ...] = ()

    @property
    def sample_count(self) -> int:
        return len(self.datapoints)

    @property
    def average(self) -> float | None:
        if not self.datapoints:
            return None
        return sum(d.average for d in self.datapoints) / len(self.datapoints)

    @property
    def maximum(self) -> float | None:
        if not self.datapoints:
            return None
        return max(d.average for d in self.datapoints)

    @property
    def observed_hours(self) -> float:
        if len(self.datapoints) < 2:
            return self.period_seconds / 3600 if self.datapoints else 0.0
        stamps = sorted(d.timestamp for d in self.datapoints)
        span = (stamps[-1] - stamps[0]).total_seconds() + self.period_seconds
        return span / 3600


class Inventory(BaseModel):
    """Everything a scan looks at, plus optional metrics keyed by resource id."""

    model_config = ConfigDict(frozen=True)

    region: str
    volumes: tuple[EBSVolume, ...] = ()
    instances: tuple[EC2Instance, ...] = ()
    elastic_ips: tuple[ElasticIP, ...] = ()
    db_instances: tuple[DBInstance, ...] = ()
    snapshots: tuple[Snapshot, ...] = ()
    metrics: dict[str, MetricSeries] = Field(default_factory=dict)
    source_errors: tuple[str, ...] = ()

    @property
    def resource_count(self) -> int:
        return (
            len(self.volumes)
            + len(self.instances)
            + len(self.elastic_ips)
            + len(self.db_instances)
            + len(self.snapshots)
        )
