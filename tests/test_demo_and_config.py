from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cloud_cost_guardian.app import Application
from cloud_cost_guardian.config import Mode, Settings, load_settings
from cloud_cost_guardian.demo.fixture_loader import FixtureInventorySource
from cloud_cost_guardian.demo.state import DemoStateStore
from cloud_cost_guardian.detectors import ALL_DETECTORS
from cloud_cost_guardian.exceptions import ConfigurationError, InventorySourceError
from cloud_cost_guardian.models.resources import Inventory, ResourceType
from cloud_cost_guardian.sources.base import InventorySource

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repo_fixtures_match_packaged_fixtures() -> None:
    for name in ("sample_aws_inventory.json", "sample_cloudwatch_metrics.json"):
        repo = json.loads((REPO_ROOT / "demo" / name).read_text(encoding="utf-8"))
        packaged = json.loads(
            (REPO_ROOT / "src" / "cloud_cost_guardian" / "demo" / "data" / name).read_text(
                encoding="utf-8"
            )
        )
        assert repo == packaged, f"{name} drifted between demo/ and package data"


def test_demo_scan_matches_expected_report(demo_app: Application) -> None:
    """The committed demo/expected_report.json is the contract for the demo scenario."""
    expected = json.loads((REPO_ROOT / "demo" / "expected_report.json").read_text(encoding="utf-8"))
    result = demo_app.scan_service(None).run(notify=False)
    summary = result.report.summary.model_dump()
    assert summary == expected["summary"]
    statuses = {
        f.resource_id: (
            "protected" if f.protected else "cleanup" if f.cleanup_eligible else "recommendation"
        )
        for f in result.report.findings
    }
    assert statuses == expected["finding_status"]


def test_demo_fixtures_cover_every_edge_case(demo_app: Application) -> None:
    inv = demo_app.source.load()
    assert inv.resource_count == 29
    vols = {v.resource_id: v for v in inv.volumes}
    assert any(v.is_attached for v in vols.values())
    assert any(not v.is_attached and v.age_days(demo_app.now) < 7 for v in vols.values())
    assert any(i.state == "stopped" for i in inv.instances)
    assert any(i.resource_id not in inv.metrics for i in inv.instances)  # missing metrics
    assert any(not e.is_associated for e in inv.elastic_ips) and any(
        e.is_associated for e in inv.elastic_ips
    )
    assert any(s.state == "pending" for s in inv.snapshots)


def test_fixture_loader_relative_ages(tmp_path: Path) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    src = FixtureInventorySource(now=now)
    inv = src.load()
    ages = [v.age_days(now) for v in inv.volumes]
    assert 93.0 in ages  # from fixture age_days


def test_fixture_loader_refetch(demo_app: Application) -> None:
    inv = demo_app.source.refetch(ResourceType.EBS_VOLUME, "vol-0a1b2c3d4e5f60001")
    assert inv.resource_count == 1 and inv.volumes[0].resource_id == "vol-0a1b2c3d4e5f60001"
    assert demo_app.source.refetch(ResourceType.EBS_VOLUME, "vol-missing").resource_count == 0


def test_fixture_loader_errors(tmp_path: Path) -> None:
    missing = FixtureInventorySource(inventory_path=tmp_path / "nope.json")
    with pytest.raises(InventorySourceError, match="not found"):
        missing.load()
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(InventorySourceError, match="valid JSON"):
        FixtureInventorySource(inventory_path=bad).load()
    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps(
            {"region": "us-east-1", "ebs_volumes": [{"id": "vol-1", "size_gib": -5, "age_days": 1}]}
        )
    )
    with pytest.raises(InventorySourceError, match="invalid fixture"):
        FixtureInventorySource(inventory_path=invalid, metrics_path=tmp_path / "m.json").load() if (
            tmp_path / "m.json"
        ).write_text('{"metrics": {}}') else None


def test_demo_state_store(tmp_path: Path) -> None:
    store = DemoStateStore(tmp_path / "data")
    assert store.load().remediated == []
    store.mark_remediated(
        resource_id="vol-1", resource_type="ebs_volume", action="delete_volume", scan_id="s"
    )
    store.mark_remediated(
        resource_id="vol-1", resource_type="ebs_volume", action="delete_volume", scan_id="s"
    )
    assert store.load().remediated_ids == {"vol-1"}
    store.path.write_text("garbage", encoding="utf-8")
    assert store.load().remediated == []  # corrupt -> clean start
    assert store.path.with_suffix(".corrupt.json").exists()
    store.reset()
    assert not store.path.exists()


def test_settings_defaults_and_validation() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.mode is Mode.DEMO and s.ebs_min_age_days == 7
    with pytest.raises(ConfigurationError):
        load_settings(ebs_min_age_days=-1)
    with pytest.raises(ConfigurationError):
        load_settings(log_level="LOUD")
    with pytest.raises(ConfigurationError):
        load_settings(aws_endpoint_url="localhost:4566")
    with pytest.raises(ConfigurationError, match="ENDPOINT"):
        load_settings(mode=Mode.LOCAL)


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCG_SNAPSHOT_MAX_AGE_DAYS", "30")
    monkeypatch.setenv("CCG_PROTECTED_TAGS", "keep=yes")
    s = load_settings()
    assert s.snapshot_max_age_days == 30 and s.protected_tag_pairs == {"keep": "yes"}


def test_partial_detector_failure_does_not_kill_scan(
    demo_app: Application, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cloud_cost_guardian.detectors import EIPDetector

    def boom(self: Any, inventory: Any) -> list[Any]:
        raise RuntimeError("simulated detector crash")

    monkeypatch.setattr(EIPDetector, "detect", boom)
    result = demo_app.scan_service(None).run(notify=False)
    runs = {r.name: r for r in result.report.detector_runs}
    assert runs["eip"].status == "failed" and "RuntimeError" in (runs["eip"].error or "")
    assert runs["ebs"].status == "ok"
    assert result.report.summary.total_findings > 0
    assert any("eip" in w for w in result.report.warnings)


def test_disabled_detector_reported(tmp_path: Path) -> None:
    s = Settings(
        mode=Mode.DEMO,
        rds_enabled=False,
        artifacts_dir=tmp_path / "a",
        data_dir=tmp_path / "d",
        _env_file=None,
    )  # type: ignore[call-arg]
    app = Application.build(s)
    result = app.scan_service(None).run(notify=False)
    runs = {r.name: r.status for r in result.report.detector_runs}
    assert runs["rds"] == "disabled"
    assert "rds_rightsizing" not in result.report.summary.findings_by_category


def test_source_errors_become_warnings(demo_app: Application) -> None:
    class Flaky(InventorySource):
        @property
        def name(self) -> str:
            return "flaky"

        def load(self) -> Inventory:
            return Inventory(region="us-east-1", source_errors=("rds: AccessDenied",))

        def refetch(self, resource_type: ResourceType, resource_id: str) -> Inventory:
            return Inventory(region="us-east-1")

    from cloud_cost_guardian.services.scan_service import ScanService

    svc = ScanService(
        source=Flaky(),
        detector_ctx=demo_app.detector_context,
        report_builder=demo_app.report_builder(),
        notifier=None,
        artifacts_dir=demo_app.artifacts_dir,
        policy_description={},
    )
    report = svc.run(notify=False).report
    assert report.warnings == ("rds: AccessDenied",)
    assert report.summary.total_findings == 0


def test_all_detectors_registered() -> None:
    assert [d.name for d in ALL_DETECTORS] == ["ebs", "ec2", "eip", "rds", "snapshot"]
