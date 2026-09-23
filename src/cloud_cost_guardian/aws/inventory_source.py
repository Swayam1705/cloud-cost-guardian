"""Read-only AWS inventory source. Partial failures are recorded, not fatal."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from cloud_cost_guardian.aws import cloudwatch, ebs, ec2, eip, rds, snapshots
from cloud_cost_guardian.aws.client_factory import AWSClientFactory
from cloud_cost_guardian.aws.errors import AWSServiceError
from cloud_cost_guardian.models.resources import (
    DBInstance,
    EBSVolume,
    EC2Instance,
    ElasticIP,
    Inventory,
    MetricSeries,
    ResourceType,
    Snapshot,
)
from cloud_cost_guardian.policies.thresholds import Thresholds
from cloud_cost_guardian.sources.base import InventorySource

log = logging.getLogger(__name__)
T = TypeVar("T")


class AWSInventorySource(InventorySource):
    def __init__(
        self, factory: AWSClientFactory, thresholds: Thresholds, *, now: datetime | None = None
    ) -> None:
        self._f = factory
        self._t = thresholds
        self._now = now or datetime.now(timezone.utc)

    @property
    def name(self) -> str:
        return "aws"

    def load(self) -> Inventory:
        region = self._f.region
        errors: list[str] = []
        ec2c = self._f.client("ec2")

        volumes: list[EBSVolume] = []
        instances: list[EC2Instance] = []
        eips: list[ElasticIP] = []
        dbs: list[DBInstance] = []
        snaps: list[Snapshot] = []

        if self._t.ebs_enabled:
            volumes = self._safe("ebs", lambda: ebs.list_volumes(ec2c, region), errors) or []
        if self._t.ec2_enabled:
            instances = self._safe("ec2", lambda: ec2.list_instances(ec2c, region), errors) or []
        if self._t.eip_enabled:
            eips = self._safe("eip", lambda: eip.list_addresses(ec2c, region), errors) or []
        if self._t.rds_enabled:
            dbs = (
                self._safe(
                    "rds", lambda: rds.list_db_instances(self._f.client("rds"), region), errors
                )
                or []
            )
        if self._t.snapshot_enabled:
            snaps = (
                self._safe("snapshots", lambda: snapshots.list_snapshots(ec2c, region), errors)
                or []
            )

        metrics = self._metrics(instances, dbs, errors)
        return Inventory(
            region=region,
            volumes=tuple(volumes),
            instances=tuple(instances),
            elastic_ips=tuple(eips),
            db_instances=tuple(dbs),
            snapshots=tuple(snaps),
            metrics=metrics,
            source_errors=tuple(errors),
        )

    def refetch(self, resource_type: ResourceType, resource_id: str) -> Inventory:
        region = self._f.region
        ec2c = self._f.client("ec2")
        try:
            if resource_type is ResourceType.EBS_VOLUME:
                return Inventory(
                    region=region, volumes=tuple(ebs.list_volumes(ec2c, region, [resource_id]))
                )
            if resource_type is ResourceType.ELASTIC_IP:
                return Inventory(
                    region=region,
                    elastic_ips=tuple(eip.list_addresses(ec2c, region, [resource_id])),
                )
            if resource_type is ResourceType.EBS_SNAPSHOT:
                return Inventory(
                    region=region,
                    snapshots=tuple(snapshots.list_snapshots(ec2c, region, [resource_id])),
                )
            if resource_type is ResourceType.EC2_INSTANCE:
                return Inventory(
                    region=region, instances=tuple(ec2.list_instances(ec2c, region, [resource_id]))
                )
            db_list = rds.list_db_instances(self._f.client("rds"), region, resource_id)
            return Inventory(region=region, db_instances=tuple(db_list))
        except AWSServiceError as exc:
            # "NotFound" family means the resource is gone -> empty inventory;
            # anything else propagates.
            if "NotFound" in exc.code or exc.code.endswith(".Malformed"):
                return Inventory(region=region)
            raise

    # ------------------------------------------------------------------ internals
    def _metrics(
        self, instances: list[EC2Instance], dbs: list[DBInstance], errors: list[str]
    ) -> dict[str, MetricSeries]:
        result: dict[str, MetricSeries] = {}
        cw = self._f.client("cloudwatch")
        for inst in instances:
            if inst.state != "running":
                continue
            series = self._safe(
                f"cloudwatch:{inst.resource_id}",
                functools.partial(
                    cloudwatch.ec2_cpu,
                    cw,
                    inst.resource_id,
                    self._now,
                    self._t.ec2_observation_hours,
                ),
                errors,
            )
            if series is not None:
                result[inst.resource_id] = series
        for db in dbs:
            series = self._safe(
                f"cloudwatch:{db.resource_id}",
                functools.partial(
                    cloudwatch.rds_cpu, cw, db.resource_id, self._now, self._t.rds_observation_hours
                ),
                errors,
            )
            if series is not None:
                result[db.resource_id] = series
        return result

    @staticmethod
    def _safe(label: str, fn: Callable[[], T], errors: list[str]) -> T | None:
        try:
            return fn()
        except AWSServiceError as exc:
            log.warning("inventory partial failure in %s: %s", label, exc)
            errors.append(f"{label}: {exc}")
            return None
