"""EBS snapshot reads and the guarded delete action."""

from __future__ import annotations

import logging
from typing import Any

from cloud_cost_guardian.aws._common import paginate, tags_to_dict
from cloud_cost_guardian.aws.errors import translate_client_error
from cloud_cost_guardian.models.resources import Snapshot

log = logging.getLogger(__name__)


def _to_model(raw: dict[str, Any], region: str) -> Snapshot | None:
    try:
        return Snapshot(
            resource_id=str(raw["SnapshotId"]),
            region=region,
            volume_id=raw.get("VolumeId"),
            volume_size_gib=int(raw.get("VolumeSize", 0)),
            start_time=raw["StartTime"],
            state=str(raw.get("State", "unknown")),
            description=str(raw.get("Description", "")),
            owner_id=raw.get("OwnerId"),
            tags=tags_to_dict(raw.get("Tags")),
        )
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("skipping malformed snapshot payload: %s", exc)
        return None


def list_snapshots(ec2: Any, region: str, snapshot_ids: list[str] | None = None) -> list[Snapshot]:
    kwargs: dict[str, Any] = {"OwnerIds": ["self"]}
    if snapshot_ids:
        kwargs = {"SnapshotIds": snapshot_ids}
    models = (
        _to_model(s, region)
        for s in paginate(ec2, "ec2", "describe_snapshots", "Snapshots", **kwargs)
    )
    return [m for m in models if m is not None]


def delete_snapshot(ec2: Any, snapshot_id: str, *, dry_run: bool) -> None:
    try:
        ec2.delete_snapshot(SnapshotId=snapshot_id, DryRun=dry_run)
    except Exception as exc:
        err = translate_client_error(exc, "ec2", "delete_snapshot")
        if dry_run and err.code == "DryRunOperation":
            return
        raise err from exc
