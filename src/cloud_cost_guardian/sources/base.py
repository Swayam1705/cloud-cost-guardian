"""Inventory source interface used by scanning and remediation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from cloud_cost_guardian.models.resources import Inventory, ResourceType


class InventorySource(ABC):
    """Reads resources. Implementations must be read-only in :meth:`load`."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def load(self) -> Inventory: ...

    @abstractmethod
    def refetch(self, resource_type: ResourceType, resource_id: str) -> Inventory:
        """Return a fresh, minimal inventory containing only the requested resource (or empty)."""
