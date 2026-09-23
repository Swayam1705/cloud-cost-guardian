"""EBS volume reads and the single, guarded destructive action."""

from __future__ import annotations

import logging
from typing import Any

from cloud_cost_guardian.aws._common import paginate, tags_to_dict
from cloud_cost_guardian.aws.errors import translate_client_error
from cloud_cost_guardian.models.resources import EBSVolume

log = logging.getLogger(__name__)


def _to_model(raw: dict[str, Any], region: str) -> EBSVolume | None:
    try:
        attachments = raw.get("Attachments") or []
        attached = next(
            (
                a.get("InstanceId")
                for a in attachments
                if a.get("State") in {"attached", "attaching"}
            ),
            None,
        )
        return EBSVolume(
            resource_id=str(raw["VolumeId"]),
            region=region,
            availability_zone=str(raw.get("AvailabilityZone", "")),
            size_gib=int(raw["Size"]),
            volume_type=str(raw.get("VolumeType", "gp2")),
            state=str(raw.get("State", "unknown")),
            create_time=raw["CreateTime"],
            attached_instance_id=attached,
            iops=raw.get("Iops"),
            encrypted=bool(raw.get("Encrypted", False)),
            tags=tags_to_dict(raw.get("Tags")),
        )
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("skipping malformed volume payload: %s", exc)
        return None


def list_volumes(ec2: Any, region: str, volume_ids: list[str] | None = None) -> list[EBSVolume]:
    kwargs: dict[str, Any] = {"VolumeIds": volume_ids} if volume_ids else {}
    models = (
        _to_model(v, region) for v in paginate(ec2, "ec2", "describe_volumes", "Volumes", **kwargs)
    )
    return [m for m in models if m is not None]


def delete_volume(ec2: Any, volume_id: str, *, dry_run: bool) -> None:
    """Destructive. Only called by the remediation service after all gates pass."""
    try:
        ec2.delete_volume(VolumeId=volume_id, DryRun=dry_run)
    except Exception as exc:
        err = translate_client_error(exc, "ec2", "delete_volume")
        if dry_run and err.code == "DryRunOperation":
            return  # AWS signals "would have succeeded"
        raise err from exc
