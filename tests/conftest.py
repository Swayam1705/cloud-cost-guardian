"""Shared fixtures: deterministic clock, in-memory inventories and an isolated Application."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cloud_cost_guardian.app import Application
from cloud_cost_guardian.config import Mode, Settings
from cloud_cost_guardian.detectors import DetectorContext
from cloud_cost_guardian.models.resources import (
    DBInstance,
    EBSVolume,
    EC2Instance,
    ElasticIP,
    Inventory,
    MetricDatapoint,
    MetricSeries,
    Snapshot,
)
from cloud_cost_guardian.policies.protection import ProtectionPolicy
from cloud_cost_guardian.policies.thresholds import Thresholds
from cloud_cost_guardian.pricing.catalog import CatalogPricingProvider, PricingCatalog
from cloud_cost_guardian.pricing.estimator import CostEstimator

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
REGION = "us-east-1"
PROTECTED = {"cost-guardian-protected": "true"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Tests never read the developer's real env/.env or write outside tmp_path."""
    for key in list(os.environ):
        if key.startswith("CCG_") or key.startswith("AWS_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def thresholds() -> Thresholds:
    return Thresholds()


@pytest.fixture
def protection() -> ProtectionPolicy:
    return ProtectionPolicy({"cost-guardian-protected": "true", "Environment": "production"})


@pytest.fixture
def estimator() -> CostEstimator:
    return CostEstimator(CatalogPricingProvider(PricingCatalog.load_default()))


@pytest.fixture
def ctx(
    thresholds: Thresholds, protection: ProtectionPolicy, estimator: CostEstimator
) -> DetectorContext:
    return DetectorContext(
        thresholds=thresholds, protection=protection, estimator=estimator, now=NOW
    )


@pytest.fixture
def demo_settings(tmp_path: Path) -> Settings:
    return Settings(
        mode=Mode.DEMO,
        artifacts_dir=tmp_path / "artifacts",
        data_dir=tmp_path / "data",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def demo_app(demo_settings: Settings) -> Application:
    return Application.build(demo_settings, now=NOW)


# ------------------------------------------------------------------ resource builders
def volume(
    rid: str = "vol-1",
    *,
    age_days: float = 30,
    attached: str | None = None,
    state: str | None = None,
    tags: dict[str, str] | None = None,
    size: int = 100,
    vtype: str = "gp3",
) -> EBSVolume:
    return EBSVolume(
        resource_id=rid,
        region=REGION,
        availability_zone=f"{REGION}a",
        size_gib=size,
        volume_type=vtype,
        state=state or ("in-use" if attached else "available"),
        create_time=NOW - timedelta(days=age_days),
        attached_instance_id=attached,
        tags=tags or {},
    )


def instance(
    rid: str = "i-1",
    *,
    itype: str = "m5.xlarge",
    state: str = "running",
    age_days: float = 100,
    tags: dict[str, str] | None = None,
) -> EC2Instance:
    return EC2Instance(
        resource_id=rid,
        region=REGION,
        instance_type=itype,
        state=state,
        launch_time=NOW - timedelta(days=age_days),
        tags=tags or {},
    )


def eip(
    rid: str = "eipalloc-1", *, associated: bool = False, tags: dict[str, str] | None = None
) -> ElasticIP:
    return ElasticIP(
        resource_id=rid,
        region=REGION,
        public_ip="203.0.113.5",
        association_id="eipassoc-1" if associated else None,
        instance_id="i-1" if associated else None,
        tags=tags or {},
    )


def db(
    rid: str = "db-1",
    *,
    klass: str = "db.m5.xlarge",
    tags: dict[str, str] | None = None,
    status: str = "available",
) -> DBInstance:
    return DBInstance(
        resource_id=rid,
        region=REGION,
        engine="postgres",
        instance_class=klass,
        status=status,
        allocated_storage_gib=100,
        tags=tags or {},
    )


def snapshot(
    rid: str = "snap-1",
    *,
    age_days: float = 120,
    tags: dict[str, str] | None = None,
    state: str = "completed",
    size: int = 100,
) -> Snapshot:
    return Snapshot(
        resource_id=rid,
        region=REGION,
        volume_id="vol-x",
        volume_size_gib=size,
        start_time=NOW - timedelta(days=age_days),
        state=state,
        tags=tags or {},
    )


def series(
    rid: str, *, hours: int = 72, average: float = 2.0, peak: float | None = None
) -> MetricSeries:
    values = [average] * hours
    if peak is not None and hours:
        values[hours // 2] = peak
    points = tuple(
        MetricDatapoint(timestamp=NOW - timedelta(hours=hours - i), average=v)
        for i, v in enumerate(values)
    )
    return MetricSeries(resource_id=rid, metric_name="CPUUtilization", datapoints=points)


def inventory(**kwargs: object) -> Inventory:
    return Inventory(region=REGION, **kwargs)  # type: ignore[arg-type]
