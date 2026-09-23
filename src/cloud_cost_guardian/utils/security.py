"""Security and validation utilities for Cloud Cost Guardian."""

from __future__ import annotations

import re
from typing import Any

PROTECTION_TAG_KEYS = {
    "cloud-cost-guardian:protected",
    "ccg:protected",
    "do-not-delete",
    "protected",
    "donotdelete",
    "cloudcostguardian:protected",
}

TRUTHY_VALUES = {"true", "1", "yes", "enabled", "y"}


def sanitize_resource_id(resource_id: str) -> str:
    """Sanitize resource identifiers to prevent path traversal and injection attacks."""
    if not resource_id or not isinstance(resource_id, str):
        raise ValueError("Resource ID must be a non-empty string.")

    cleaned = resource_id.strip()
    if not cleaned or cleaned in (".", ".."):
        raise ValueError("Invalid resource ID: cannot be dot sequences.")

    # Block path traversal attempts
    cleaned = (
        cleaned.replace("..", "")
        .replace("/", "_")
        .replace("\\", "_")
        .replace("\x00", "")
        .replace("\0", "")
    )

    # Strip dangerous shell metacharacters
    cleaned = re.sub(r"[^a-zA-Z0-9\-_\.:]", "_", cleaned)
    cleaned = cleaned.lstrip(".-")

    if not cleaned:
        raise ValueError(f"Resource ID '{resource_id}' contains no valid characters.")

    return cleaned[:256]


def is_resource_protected(tags: dict[str, Any] | None) -> bool:
    """Check if resource has protection tags preventing automated destructive remediation."""
    if not tags or not isinstance(tags, dict):
        return False

    for k, v in tags.items():
        if str(k).strip().lower() in PROTECTION_TAG_KEYS:
            val_str = str(v).strip().lower()
            if val_str in TRUTHY_VALUES:
                return True
    return False


def validate_exact_resource_id(target_id: str, candidate_id: str) -> bool:
    """Perform exact, case-sensitive matching on AWS resource IDs."""
    if not target_id or not candidate_id:
        return False
    return target_id.strip() == candidate_id.strip()


def assert_safe_remediation_action(resource_type: str, action: str) -> str:
    """Ensure safe remediation policies are strictly enforced."""
    r_type = (resource_type or "").strip().lower()
    act = (action or "").strip().lower()

    if r_type in ("rds", "rds_instance", "rds_cluster", "database"):
        destructive_verbs = {"delete", "terminate", "destroy", "drop", "purge", "remove"}
        if any(v in act for v in destructive_verbs):
            return "recommend_downsize"

    return action
