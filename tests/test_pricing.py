from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloud_cost_guardian.exceptions import PricingError
from cloud_cost_guardian.pricing.catalog import CatalogPricingProvider, PricingCatalog
from cloud_cost_guardian.pricing.estimator import CostEstimate, CostEstimator
from tests.conftest import db, eip, instance, snapshot, volume


@pytest.fixture
def provider() -> CatalogPricingProvider:
    return CatalogPricingProvider(PricingCatalog.load_default())


def test_default_catalog_loads(provider: CatalogPricingProvider) -> None:
    assert provider.name.startswith("ccg-reference")
    assert provider.hours_per_month == 730


def test_region_override_then_default_fallback(provider: CatalogPricingProvider) -> None:
    assert provider.ebs_gb_month("ap-south-1", "gp3") == pytest.approx(0.0912)
    assert provider.ebs_gb_month("eu-west-1", "gp3") == pytest.approx(0.08)  # falls back to default
    # ap-south-1 has no ec2 block -> default
    assert provider.ec2_hourly("ap-south-1", "t3.micro") == pytest.approx(0.0104)


def test_missing_price_raises(provider: CatalogPricingProvider) -> None:
    with pytest.raises(PricingError):
        provider.ec2_hourly("us-east-1", "z99.mega")


def test_rds_multipliers(provider: CatalogPricingProvider) -> None:
    single = provider.rds_hourly("us-east-1", "db.m5.large", "postgres", False)
    multi = provider.rds_hourly("us-east-1", "db.m5.large", "postgres", True)
    aurora = provider.rds_hourly("us-east-1", "db.m5.large", "aurora-postgresql", False)
    assert multi == pytest.approx(single * 2)
    assert aurora == pytest.approx(single * 1.2)


def test_estimator_values(provider: CatalogPricingProvider) -> None:
    est = CostEstimator(provider)
    assert est.ebs_volume(volume(size=100, vtype="gp2")).monthly == pytest.approx(10.0)
    assert est.snapshot(snapshot(size=250)).monthly == pytest.approx(12.5)
    assert est.elastic_ip(eip()).monthly == pytest.approx(3.65)
    ec2 = est.ec2_instance(instance(itype="m5.xlarge"))
    assert ec2.monthly == pytest.approx(0.192 * 730)
    assert ec2.monthly_savings == pytest.approx((0.192 - 0.096) * 730)
    rds = est.rds_instance(db(klass="db.m5.xlarge"))
    assert rds.monthly_savings == pytest.approx((0.342 - 0.171) * 730)
    assert rds.annual == pytest.approx(rds.monthly * 12)


def test_estimator_missing_price_is_graceful(provider: CatalogPricingProvider) -> None:
    est = CostEstimator(provider)
    result = est.ec2_instance(instance(itype="unknown.type"))
    assert result == CostEstimate.unpriced(result.note or "")
    assert result.priced is False and result.monthly == 0


def test_rds_without_downsize_target_has_zero_savings(provider: CatalogPricingProvider) -> None:
    est = CostEstimator(provider)
    result = est.rds_instance(db(klass="db.t4g.micro"))
    assert result.monthly > 0 and result.monthly_savings == 0


def test_savings_never_exceed_cost() -> None:
    e = CostEstimate.of(10.0, savings=50.0)
    assert e.monthly_savings == 10.0
    assert CostEstimate.of(-5.0).monthly == 0.0


def test_invalid_catalog_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PricingError):
        PricingCatalog.load_from_path(bad)
    with pytest.raises(PricingError):
        PricingCatalog.load_from_path(tmp_path / "missing.json")
    no_default = tmp_path / "nodefault.json"
    no_default.write_text(
        json.dumps({"catalog_name": "x", "disclaimer": "d", "regions": {"us-east-1": {}}})
    )
    with pytest.raises(PricingError, match="default"):
        PricingCatalog.load_from_path(no_default)


def test_negative_price_rejected() -> None:
    text = json.dumps(
        {"catalog_name": "x", "disclaimer": "d", "regions": {"default": {"snapshot_gb_month": -1}}}
    )
    with pytest.raises(PricingError):
        PricingCatalog.from_json_text(text)


def test_custom_catalog_path(tmp_path: Path) -> None:
    custom = tmp_path / "c.json"
    custom.write_text(
        json.dumps(
            {
                "catalog_name": "mine",
                "disclaimer": "d",
                "regions": {"default": {"eip_idle_hourly": 0.01}},
            }
        )
    )
    p = CatalogPricingProvider(PricingCatalog.load_from_path(custom))
    assert p.eip_idle_hourly("anywhere") == 0.01
