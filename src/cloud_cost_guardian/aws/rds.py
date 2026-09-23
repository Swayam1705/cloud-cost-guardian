"""RDS reads. There is intentionally NO destructive RDS function in this module."""

from __future__ import annotations

import logging
from typing import Any

from cloud_cost_guardian.aws._common import paginate, tags_to_dict
from cloud_cost_guardian.models.resources import DBInstance

log = logging.getLogger(__name__)


def _to_model(raw: dict[str, Any], region: str) -> DBInstance | None:
    try:
        return DBInstance(
            resource_id=str(raw["DBInstanceIdentifier"]),
            region=region,
            engine=str(raw.get("Engine", "unknown")),
            instance_class=str(raw.get("DBInstanceClass", "unknown")),
            status=str(raw.get("DBInstanceStatus", "unknown")),
            allocated_storage_gib=int(raw.get("AllocatedStorage", 0)),
            multi_az=bool(raw.get("MultiAZ", False)),
            create_time=raw.get("InstanceCreateTime"),
            tags=tags_to_dict(raw.get("TagList")),
        )
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("skipping malformed DB payload: %s", exc)
        return None


def list_db_instances(rds: Any, region: str, identifier: str | None = None) -> list[DBInstance]:
    kwargs: dict[str, Any] = {"DBInstanceIdentifier": identifier} if identifier else {}
    models = (
        _to_model(d, region)
        for d in paginate(rds, "rds", "describe_db_instances", "DBInstances", **kwargs)
    )
    return [m for m in models if m is not None]
