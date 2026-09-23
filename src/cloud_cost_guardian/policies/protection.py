"""Centralised, tag-based resource protection.

Every code path that could touch a resource (detectors, cleanup) must go through
:class:`ProtectionPolicy`. There is intentionally no other place that decides protection.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ProtectionResult:
    protected: bool
    reason: str | None = None


class ProtectionPolicy:
    """A resource is protected when any of its tags matches a configured protected tag.

    Matching is case-insensitive on both key and value. A configured value of ``*`` matches
    any value for that key.
    """

    def __init__(self, protected_tags: Mapping[str, str]) -> None:
        if not protected_tags:
            raise ValueError("ProtectionPolicy requires at least one protected tag")
        self._rules: dict[str, str] = {
            k.strip().lower(): v.strip().lower() for k, v in protected_tags.items()
        }

    @property
    def rules(self) -> dict[str, str]:
        return dict(self._rules)

    def evaluate(self, tags: Mapping[str, str] | None) -> ProtectionResult:
        if not tags:
            return ProtectionResult(False)
        normalised = {str(k).strip().lower(): str(v).strip().lower() for k, v in tags.items()}
        for key, wanted in self._rules.items():
            if key not in normalised:
                continue
            actual = normalised[key]
            if wanted in ("*", actual):
                return ProtectionResult(
                    True, f"tag {key}={tags_original(tags, key)} matches protection rule"
                )
        return ProtectionResult(False)

    def is_protected(self, tags: Mapping[str, str] | None) -> bool:
        return self.evaluate(tags).protected


def tags_original(tags: Mapping[str, str], lowered_key: str) -> str:
    for k, v in tags.items():
        if str(k).strip().lower() == lowered_key:
            return str(v)
    return ""
