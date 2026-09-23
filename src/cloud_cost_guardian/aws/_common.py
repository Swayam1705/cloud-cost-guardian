"""Shared helpers for service modules."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from cloud_cost_guardian.aws.errors import translate_client_error


def tags_to_dict(tag_list: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(tag_list, list):
        return result
    for tag in tag_list:
        if isinstance(tag, dict) and "Key" in tag:
            result[str(tag["Key"])] = str(tag.get("Value", ""))
    return result


def paginate(
    client: Any, service: str, operation: str, result_key: str, **kwargs: Any
) -> Iterator[dict[str, Any]]:
    """Yield items from a paginated (or non-paginated) boto3 call with uniform error translation."""
    try:
        if client.can_paginate(operation):
            paginator = client.get_paginator(operation)
            for page in paginator.paginate(**kwargs):
                yield from _items(page, result_key)
        else:
            method = getattr(client, operation)
            yield from _items(method(**kwargs), result_key)
    except Exception as exc:
        raise translate_client_error(exc, service, operation) from exc


def _items(page: Any, key: str) -> Iterator[dict[str, Any]]:
    items = page.get(key, []) if isinstance(page, dict) else []
    for item in items:
        if isinstance(item, dict):
            yield item
