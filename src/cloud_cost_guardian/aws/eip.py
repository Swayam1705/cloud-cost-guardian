"""Elastic IP reads and the guarded release action."""

from __future__ import annotations

import logging
from typing import Any

from cloud_cost_guardian.aws._common import paginate, tags_to_dict
from cloud_cost_guardian.aws.errors import translate_client_error
from cloud_cost_guardian.models.resources import ElasticIP

log = logging.getLogger(__name__)


def _to_model(raw: dict[str, Any], region: str) -> ElasticIP | None:
    try:
        allocation_id = raw.get("AllocationId") or raw.get("PublicIp")
        return ElasticIP(
            resource_id=str(allocation_id),
            region=region,
            public_ip=str(raw["PublicIp"]),
            association_id=raw.get("AssociationId"),
            instance_id=raw.get("InstanceId") or None,
            network_interface_id=raw.get("NetworkInterfaceId") or None,
            domain=str(raw.get("Domain", "vpc")),
            tags=tags_to_dict(raw.get("Tags")),
        )
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("skipping malformed address payload: %s", exc)
        return None


def list_addresses(
    ec2: Any, region: str, allocation_ids: list[str] | None = None
) -> list[ElasticIP]:
    kwargs: dict[str, Any] = {"AllocationIds": allocation_ids} if allocation_ids else {}
    models = (
        _to_model(a, region)
        for a in paginate(ec2, "ec2", "describe_addresses", "Addresses", **kwargs)
    )
    return [m for m in models if m is not None]


def release_address(ec2: Any, allocation_id: str, *, dry_run: bool) -> None:
    try:
        ec2.release_address(AllocationId=allocation_id, DryRun=dry_run)
    except Exception as exc:
        err = translate_client_error(exc, "ec2", "release_address")
        if dry_run and err.code == "DryRunOperation":
            return
        raise err from exc
