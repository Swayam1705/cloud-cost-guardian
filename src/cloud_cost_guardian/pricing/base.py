"""Pricing provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PricingProvider(ABC):
    """Returns reference on-demand prices. Implementations must never call paid APIs."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def ebs_gb_month(self, region: str, volume_type: str) -> float: ...

    @abstractmethod
    def ec2_hourly(self, region: str, instance_type: str) -> float: ...

    @abstractmethod
    def eip_idle_hourly(self, region: str) -> float: ...

    @abstractmethod
    def rds_hourly(
        self, region: str, instance_class: str, engine: str, multi_az: bool
    ) -> float: ...

    @abstractmethod
    def snapshot_gb_month(self, region: str) -> float: ...
