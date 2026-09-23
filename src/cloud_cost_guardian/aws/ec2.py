"""EC2 instance reads (and the optional stop action)."""

from __future__ import annotations

import logging
from typing import Any

from cloud_cost_guardian.aws._common import paginate, tags_to_dict
from cloud_cost_guardian.aws.errors import translate_client_error
from cloud_cost_guardian.models.resources import EC2Instance

log = logging.getLogger(__name__)


def _to_model(raw: dict[str, Any], region: str) -> EC2Instance | None:
    try:
        tags = tags_to_dict(raw.get("Tags"))
        return EC2Instance(
            resource_id=str(raw["InstanceId"]),
            region=region,
            instance_type=str(raw.get("InstanceType", "unknown")),
            state=str((raw.get("State") or {}).get("Name", "unknown")),
            launch_time=raw["LaunchTime"],
            availability_zone=(raw.get("Placement") or {}).get("AvailabilityZone"),
            platform=raw.get("PlatformDetails") or raw.get("Platform"),
            name=tags.get("Name"),
            tags=tags,
        )
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("skipping malformed instance payload: %s", exc)
        return None


def list_instances(
    ec2: Any, region: str, instance_ids: list[str] | None = None
) -> list[EC2Instance]:
    kwargs: dict[str, Any] = {"InstanceIds": instance_ids} if instance_ids else {}
    result: list[EC2Instance] = []
    for reservation in paginate(ec2, "ec2", "describe_instances", "Reservations", **kwargs):
        for raw in reservation.get("Instances", []):
            model = _to_model(raw, region)
            if model is not None:
                result.append(model)
    return result


def stop_instance(ec2: Any, instance_id: str, *, dry_run: bool) -> None:
    try:
        ec2.stop_instances(InstanceIds=[instance_id], DryRun=dry_run)
    except Exception as exc:
        err = translate_client_error(exc, "ec2", "stop_instances")
        if dry_run and err.code == "DryRunOperation":
            return
        raise err from exc
