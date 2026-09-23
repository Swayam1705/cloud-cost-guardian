"""Loads the demo inventory and simulated CloudWatch metrics from JSON fixtures.

Fixture timestamps are *relative* (``"age_days": 93``) so the demo never goes stale.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from cloud_cost_guardian.demo.state import DemoStateStore
from cloud_cost_guardian.exceptions import InventorySourceError
from cloud_cost_guardian.models.resources import (
    DBInstance,
    EBSVolume,
    EC2Instance,
    ElasticIP,
    Inventory,
    MetricDatapoint,
    MetricSeries,
    ResourceType,
    Snapshot,
)
from cloud_cost_guardian.sources.base import InventorySource


def _read_json(path: Path | None, packaged_name: str) -> Any:
    try:
        if path is not None:
            return json.loads(path.read_text(encoding="utf-8"))
        ref = resources.files("cloud_cost_guardian.demo").joinpath(f"data/{packaged_name}")
        return json.loads(ref.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InventorySourceError(f"fixture file not found: {path or packaged_name}") from exc
    except json.JSONDecodeError as exc:
        raise InventorySourceError(
            f"fixture file is not valid JSON: {path or packaged_name}: {exc}"
        ) from exc


def _ago(now: datetime, item: dict[str, Any], key: str) -> datetime:
    days = item.get(key)
    if not isinstance(days, (int, float)) or days < 0:
        raise InventorySourceError(f"fixture entry {item.get('id')} needs numeric '{key}'")
    return now - timedelta(days=float(days))


class FixtureInventorySource(InventorySource):
    def __init__(
        self,
        *,
        inventory_path: Path | None = None,
        metrics_path: Path | None = None,
        state_store: DemoStateStore | None = None,
        now: datetime | None = None,
    ) -> None:
        self._inventory_path = inventory_path
        self._metrics_path = metrics_path
        self._state = state_store
        self._now = now or datetime.now(timezone.utc)

    @property
    def name(self) -> str:
        return "fixtures"

    def load(self) -> Inventory:
        raw = _read_json(self._inventory_path, "sample_aws_inventory.json")
        metrics_raw = _read_json(self._metrics_path, "sample_cloudwatch_metrics.json")
        remediated = self._state.load().remediated_ids if self._state else set()
        try:
            return self._build(raw, metrics_raw, remediated)
        except (ValidationError, KeyError, TypeError) as exc:
            raise InventorySourceError(f"invalid fixture data: {exc}") from exc

    def refetch(self, resource_type: ResourceType, resource_id: str) -> Inventory:
        full = self.load()
        return Inventory(
            region=full.region,
            volumes=tuple(v for v in full.volumes if v.resource_id == resource_id),
            instances=tuple(i for i in full.instances if i.resource_id == resource_id),
            elastic_ips=tuple(e for e in full.elastic_ips if e.resource_id == resource_id),
            db_instances=tuple(d for d in full.db_instances if d.resource_id == resource_id),
            snapshots=tuple(s for s in full.snapshots if s.resource_id == resource_id),
            metrics={k: v for k, v in full.metrics.items() if k == resource_id},
        )

    # ------------------------------------------------------------------ builders
    def _build(
        self, raw: dict[str, Any], metrics_raw: dict[str, Any], remediated: set[str]
    ) -> Inventory:
        region = str(raw.get("region", "us-east-1"))
        now = self._now
        volumes = [
            EBSVolume(
                resource_id=v["id"],
                region=region,
                availability_zone=v.get("availability_zone", f"{region}a"),
                size_gib=int(v["size_gib"]),
                volume_type=v.get("volume_type", "gp3"),
                state=v.get("state", "available"),
                create_time=_ago(now, v, "age_days"),
                attached_instance_id=v.get("attached_instance_id"),
                encrypted=bool(v.get("encrypted", False)),
                tags=dict(v.get("tags", {})),
            )
            for v in raw.get("ebs_volumes", [])
            if v["id"] not in remediated
        ]
        instances = [
            EC2Instance(
                resource_id=i["id"],
                region=region,
                instance_type=i["instance_type"],
                state=i.get("state", "running"),
                launch_time=_ago(now, i, "age_days"),
                availability_zone=i.get("availability_zone"),
                platform=i.get("platform"),
                name=i.get("tags", {}).get("Name"),
                tags=dict(i.get("tags", {})),
            )
            for i in raw.get("ec2_instances", [])
            if i["id"] not in remediated
        ]
        eips = [
            ElasticIP(
                resource_id=e["allocation_id"],
                region=region,
                public_ip=e["public_ip"],
                association_id=e.get("association_id"),
                instance_id=e.get("instance_id"),
                network_interface_id=e.get("network_interface_id"),
                domain=e.get("domain", "vpc"),
                tags=dict(e.get("tags", {})),
            )
            for e in raw.get("elastic_ips", [])
            if e["allocation_id"] not in remediated
        ]
        dbs = [
            DBInstance(
                resource_id=d["id"],
                region=region,
                engine=d["engine"],
                instance_class=d["instance_class"],
                status=d.get("status", "available"),
                allocated_storage_gib=int(d.get("allocated_storage_gib", 20)),
                multi_az=bool(d.get("multi_az", False)),
                create_time=_ago(now, d, "age_days") if "age_days" in d else None,
                tags=dict(d.get("tags", {})),
            )
            for d in raw.get("rds_instances", [])
            if d["id"] not in remediated
        ]
        snaps = [
            Snapshot(
                resource_id=s["id"],
                region=region,
                volume_id=s.get("volume_id"),
                volume_size_gib=int(s.get("volume_size_gib", 0)),
                start_time=_ago(now, s, "age_days"),
                state=s.get("state", "completed"),
                description=s.get("description", ""),
                tags=dict(s.get("tags", {})),
            )
            for s in raw.get("snapshots", [])
            if s["id"] not in remediated
        ]
        metrics = self._build_metrics(metrics_raw, now)
        return Inventory(
            region=region,
            volumes=tuple(volumes),
            instances=tuple(instances),
            elastic_ips=tuple(eips),
            db_instances=tuple(dbs),
            snapshots=tuple(snaps),
            metrics=metrics,
        )

    @staticmethod
    def _build_metrics(raw: dict[str, Any], now: datetime) -> dict[str, MetricSeries]:
        """Expand compact fixture metrics into hourly datapoints.

        Fixture format per resource::

            {"metric": "CPUUtilization", "hours": 72, "average": 2.1, "peak": 4.0}

        or an explicit ``"datapoints": [..]`` list of averages (one per hour).
        """
        series: dict[str, MetricSeries] = {}
        for resource_id, spec in raw.get("metrics", {}).items():
            metric = spec.get("metric", "CPUUtilization")
            period = int(spec.get("period_seconds", 3600))
            if "datapoints" in spec:
                values = [float(x) for x in spec["datapoints"]]
            else:
                hours = int(spec.get("hours", 0))
                avg = float(spec.get("average", 0.0))
                peak = float(spec.get("peak", avg))
                values = [avg] * hours
                if hours and peak > avg:
                    # deterministic "spike" so peak is visible in evidence without
                    # changing the mean much
                    values[hours // 2] = peak
            points = tuple(
                MetricDatapoint(
                    timestamp=now - timedelta(seconds=period * (len(values) - idx)), average=v
                )
                for idx, v in enumerate(values)
            )
            series[resource_id] = MetricSeries(
                resource_id=resource_id,
                metric_name=metric,
                period_seconds=period,
                datapoints=points,
            )
        return series
