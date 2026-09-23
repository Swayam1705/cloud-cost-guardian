"""JSON-backed pricing catalog."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cloud_cost_guardian.exceptions import PricingError
from cloud_cost_guardian.pricing.base import PricingProvider


class RegionPrices(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ebs_gb_month: dict[str, float] = Field(default_factory=dict)
    snapshot_gb_month: float | None = Field(default=None, ge=0)
    eip_idle_hourly: float | None = Field(default=None, ge=0)
    ec2_hourly: dict[str, float] = Field(default_factory=dict)
    rds_hourly: dict[str, float] = Field(default_factory=dict)
    rds_engine_multiplier: dict[str, float] = Field(default_factory=dict)
    rds_multi_az_multiplier: float | None = Field(default=None, ge=1)


class PricingCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_name: str
    currency: str = "USD"
    disclaimer: str
    hours_per_month: int = Field(default=730, ge=1)
    regions: dict[str, RegionPrices]
    rds_downsize_map: dict[str, str] = Field(default_factory=dict)
    ec2_downsize_map: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def load_default(cls) -> PricingCatalog:
        ref = resources.files("cloud_cost_guardian.pricing").joinpath("data/default_catalog.json")
        return cls.from_json_text(ref.read_text(encoding="utf-8"))

    @classmethod
    def load_from_path(cls, path: Path) -> PricingCatalog:
        try:
            return cls.from_json_text(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PricingError(f"pricing catalog not found: {path}") from exc

    @classmethod
    def from_json_text(cls, text: str) -> PricingCatalog:
        try:
            data: Any = json.loads(text)
            catalog = cls.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise PricingError(f"invalid pricing catalog: {exc}") from exc
        if "default" not in catalog.regions:
            raise PricingError("pricing catalog must contain a 'default' region block")
        for value in _all_numbers(catalog):
            if value < 0:
                raise PricingError("pricing catalog contains negative price")
        return catalog


def _all_numbers(catalog: PricingCatalog) -> list[float]:
    values: list[float] = []
    for region in catalog.regions.values():
        values.extend(region.ebs_gb_month.values())
        values.extend(region.ec2_hourly.values())
        values.extend(region.rds_hourly.values())
        if region.snapshot_gb_month is not None:
            values.append(region.snapshot_gb_month)
        if region.eip_idle_hourly is not None:
            values.append(region.eip_idle_hourly)
    return values


class CatalogPricingProvider(PricingProvider):
    """Resolves prices region-first, then falls back to the ``default`` block."""

    def __init__(self, catalog: PricingCatalog) -> None:
        self._catalog = catalog

    @property
    def name(self) -> str:
        return self._catalog.catalog_name

    @property
    def catalog(self) -> PricingCatalog:
        return self._catalog

    @property
    def hours_per_month(self) -> int:
        return self._catalog.hours_per_month

    def _lookup(self, region: str, attr: str, key: str | None = None) -> float:
        for block_name in (region, "default"):
            block = self._catalog.regions.get(block_name)
            if block is None:
                continue
            value = getattr(block, attr)
            if key is None:
                if value is not None:
                    return float(value)
            elif isinstance(value, dict) and key in value:
                return float(value[key])
        label = f"{attr}[{key}]" if key else attr
        raise PricingError(f"no reference price for {label} in region {region}")

    def ebs_gb_month(self, region: str, volume_type: str) -> float:
        return self._lookup(region, "ebs_gb_month", volume_type.lower())

    def ec2_hourly(self, region: str, instance_type: str) -> float:
        return self._lookup(region, "ec2_hourly", instance_type.lower())

    def eip_idle_hourly(self, region: str) -> float:
        return self._lookup(region, "eip_idle_hourly")

    def rds_hourly(self, region: str, instance_class: str, engine: str, multi_az: bool) -> float:
        base = self._lookup(region, "rds_hourly", instance_class.lower())
        try:
            multiplier = self._lookup(region, "rds_engine_multiplier", engine.lower())
        except PricingError:
            multiplier = 1.0
        if multi_az:
            try:
                multiplier *= self._lookup(region, "rds_multi_az_multiplier")
            except PricingError:
                multiplier *= 2.0
        return base * multiplier

    def snapshot_gb_month(self, region: str) -> float:
        return self._lookup(region, "snapshot_gb_month")

    def rds_downsize_target(self, instance_class: str) -> str | None:
        return self._catalog.rds_downsize_map.get(instance_class.lower())

    def ec2_downsize_target(self, instance_type: str) -> str | None:
        return self._catalog.ec2_downsize_map.get(instance_type.lower())
