"""CloudWatch metric reads (CPUUtilization for EC2 and RDS)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from cloud_cost_guardian.aws.errors import translate_client_error
from cloud_cost_guardian.models.resources import MetricDatapoint, MetricSeries

log = logging.getLogger(__name__)

_PERIOD_SECONDS = 3600


def _fetch(
    cw: Any, namespace: str, dimension_name: str, resource_id: str, now: datetime, hours: int
) -> MetricSeries:
    try:
        resp = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName="CPUUtilization",
            Dimensions=[{"Name": dimension_name, "Value": resource_id}],
            StartTime=now - timedelta(hours=hours),
            EndTime=now,
            Period=_PERIOD_SECONDS,
            Statistics=["Average"],
            Unit="Percent",
        )
    except Exception as exc:
        raise translate_client_error(exc, "cloudwatch", "get_metric_statistics") from exc
    points: list[MetricDatapoint] = []
    for dp in resp.get("Datapoints", []):
        try:
            points.append(MetricDatapoint(timestamp=dp["Timestamp"], average=float(dp["Average"])))
        except (KeyError, ValueError, TypeError):
            continue
    points.sort(key=lambda p: p.timestamp)
    return MetricSeries(
        resource_id=resource_id,
        metric_name="CPUUtilization",
        period_seconds=_PERIOD_SECONDS,
        datapoints=tuple(points),
    )


def ec2_cpu(cw: Any, instance_id: str, now: datetime, hours: int) -> MetricSeries:
    return _fetch(cw, "AWS/EC2", "InstanceId", instance_id, now, hours)


def rds_cpu(cw: Any, db_identifier: str, now: datetime, hours: int) -> MetricSeries:
    return _fetch(cw, "AWS/RDS", "DBInstanceIdentifier", db_identifier, now, hours)
