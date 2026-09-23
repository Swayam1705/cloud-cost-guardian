"""Turns resources into monthly/annual cost estimates."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cloud_cost_guardian.exceptions import PricingError
from cloud_cost_guardian.models.resources import (
    DBInstance,
    EBSVolume,
    EC2Instance,
    ElasticIP,
    Snapshot,
)
from cloud_cost_guardian.pricing.catalog import CatalogPricingProvider

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CostEstimate:
    monthly: float
    annual: float
    monthly_savings: float
    priced: bool  # False when a price was missing and 0 was used
    note: str | None = None

    @classmethod
    def unpriced(cls, note: str) -> CostEstimate:
        return cls(0.0, 0.0, 0.0, priced=False, note=note)

    @classmethod
    def of(
        cls, monthly: float, savings: float | None = None, note: str | None = None
    ) -> CostEstimate:
        monthly = round(max(monthly, 0.0), 4)
        savings_val = monthly if savings is None else round(min(max(savings, 0.0), monthly), 4)
        return cls(monthly, round(monthly * 12, 4), savings_val, priced=True, note=note)


class CostEstimator:
    def __init__(self, provider: CatalogPricingProvider) -> None:
        self._p = provider

    @property
    def provider(self) -> CatalogPricingProvider:
        return self._p

    def _guard(self, fn: str, error: PricingError) -> CostEstimate:
        log.warning("pricing lookup failed (%s): %s", fn, error)
        return CostEstimate.unpriced(str(error))

    def ebs_volume(self, vol: EBSVolume) -> CostEstimate:
        try:
            rate = self._p.ebs_gb_month(vol.region, vol.volume_type)
        except PricingError as exc:
            return self._guard("ebs", exc)
        return CostEstimate.of(vol.size_gib * rate)

    def snapshot(self, snap: Snapshot) -> CostEstimate:
        try:
            rate = self._p.snapshot_gb_month(snap.region)
        except PricingError as exc:
            return self._guard("snapshot", exc)
        # Snapshots are incremental; full size is an upper bound. Documented in limitations.
        return CostEstimate.of(
            snap.volume_size_gib * rate, note="upper bound: assumes full-size snapshot"
        )

    def elastic_ip(self, eip: ElasticIP) -> CostEstimate:
        try:
            rate = self._p.eip_idle_hourly(eip.region)
        except PricingError as exc:
            return self._guard("eip", exc)
        return CostEstimate.of(rate * self._p.hours_per_month)

    def ec2_instance(self, inst: EC2Instance) -> CostEstimate:
        try:
            rate = self._p.ec2_hourly(inst.region, inst.instance_type)
        except PricingError as exc:
            return self._guard("ec2", exc)
        monthly = rate * self._p.hours_per_month
        target = self._p.ec2_downsize_target(inst.instance_type)
        savings = monthly
        note = "savings assume the instance is stopped"
        if target:
            try:
                target_monthly = self._p.ec2_hourly(inst.region, target) * self._p.hours_per_month
                savings = monthly - target_monthly
                note = f"savings assume right-sizing to {target}"
            except PricingError:
                pass
        return CostEstimate.of(monthly, savings, note)

    def rds_instance(self, db: DBInstance) -> CostEstimate:
        try:
            rate = self._p.rds_hourly(db.region, db.instance_class, db.engine, db.multi_az)
        except PricingError as exc:
            return self._guard("rds", exc)
        monthly = rate * self._p.hours_per_month
        target = self._p.rds_downsize_target(db.instance_class)
        if not target:
            return CostEstimate.of(monthly, 0.0, "no smaller class in catalog; manual review")
        try:
            target_monthly = (
                self._p.rds_hourly(db.region, target, db.engine, db.multi_az)
                * self._p.hours_per_month
            )
        except PricingError:
            return CostEstimate.of(monthly, 0.0, f"target class {target} not priced")
        return CostEstimate.of(
            monthly, monthly - target_monthly, f"savings assume right-sizing to {target}"
        )
