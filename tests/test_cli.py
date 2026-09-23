from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloud_cost_guardian import __version__
from cloud_cost_guardian.cli.main import EXIT_BLOCKED, EXIT_ERROR, EXIT_OK, EXIT_USAGE, main


@pytest.fixture(autouse=True)
def _isolated_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CCG_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CCG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CCG_LOG_LEVEL", "ERROR")


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_USAGE
    assert "usage: ccg" in capsys.readouterr().out


def test_invalid_command() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["explode"])
    assert exc.value.code == 2


def test_invalid_mode() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["scan", "--mode", "prod"])
    assert exc.value.code == 2


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == EXIT_OK
    assert __version__ in capsys.readouterr().out


def test_validate_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate-config"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Configuration OK" in out and "mode" in out


def test_validate_config_rejects_bad_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CCG_EC2_CPU_THRESHOLD_PERCENT", "150")
    assert main(["validate-config"]) == EXIT_USAGE
    assert "configuration error" in capsys.readouterr().err


def test_scan_demo_writes_artifacts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", "--mode", "demo"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "CLOUD COST GUARDIAN" in out and "Cleanup eligible" in out
    assert (tmp_path / "artifacts" / "reports" / "latest.json").exists()
    assert (tmp_path / "artifacts" / "reports" / "latest.md").exists()
    assert (tmp_path / "artifacts" / "notifications" / "latest-slack-message.json").exists()


def test_scan_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", "--mode", "demo", "--json", "--no-notify"]) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "demo" and data["summary"]["total_findings"] > 0


def test_report_without_scan_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report"]) == EXIT_ERROR
    assert "no report found" in capsys.readouterr().err


def test_report_formats(capsys: pytest.CaptureFixture[str]) -> None:
    main(["scan", "--mode", "demo", "--no-notify"])
    capsys.readouterr()
    assert main(["report"]) == EXIT_OK
    assert "Findings:" in capsys.readouterr().out
    assert main(["report", "--format", "markdown"]) == EXIT_OK
    assert "# Cloud Cost Guardian" in capsys.readouterr().out
    assert main(["report", "--format", "json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["schema_version"] == "1.0"


def test_report_malformed_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert main(["report", "--path", str(bad)]) == EXIT_ERROR
    assert "not valid" in capsys.readouterr().err


def test_cleanup_defaults_to_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    main(["scan", "--mode", "demo", "--no-notify"])
    capsys.readouterr()
    assert main(["cleanup"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "No action taken" in out
    assert "would be remediated after explicit approval" in out
    assert "[protection]" in out and "[policy]" in out


def test_cleanup_dry_run_flag(capsys: pytest.CaptureFixture[str]) -> None:
    main(["scan", "--mode", "demo", "--no-notify"])
    capsys.readouterr()
    assert main(["cleanup", "--dry-run", "--resource", "vol-0a1b2c3d4e5f60001"]) == EXIT_OK
    assert "Dry run only" in capsys.readouterr().out


def test_cleanup_unknown_resource(capsys: pytest.CaptureFixture[str]) -> None:
    main(["scan", "--mode", "demo", "--no-notify"])
    capsys.readouterr()
    assert main(["cleanup", "--resource", "vol-nope", "--approve"]) == EXIT_USAGE
    assert "not in the latest report" in capsys.readouterr().out


def test_cleanup_protected_blocked(capsys: pytest.CaptureFixture[str]) -> None:
    main(["scan", "--mode", "demo", "--no-notify"])
    capsys.readouterr()
    assert main(["cleanup", "--resource", "vol-0a1b2c3d4e5f60005", "--approve"]) == EXIT_BLOCKED
    assert "BLOCKED at stage 'protection'" in capsys.readouterr().out


def test_cleanup_interactive_denial(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["scan", "--mode", "demo", "--no-notify"])
    capsys.readouterr()
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    assert main(["cleanup", "--resource", "vol-0a1b2c3d4e5f60001"]) == EXIT_BLOCKED
    assert "stage 'approval'" in capsys.readouterr().out


def test_full_demo_lifecycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["scan", "--mode", "demo", "--no-notify", "--json"])
    before = json.loads(capsys.readouterr().out)["summary"]

    assert main(["cleanup", "--resource", "vol-0a1b2c3d4e5f60001", "--approve"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "REMEDIATED" in out
    audit = json.loads((tmp_path / "artifacts" / "audit" / "latest-cleanup.json").read_text())
    assert (
        audit["resource_id"] == "vol-0a1b2c3d4e5f60001"
        and audit["metadata"]["status"] == "remediated"
    )

    main(["scan", "--mode", "demo", "--no-notify", "--json"])
    after = json.loads(capsys.readouterr().out)["summary"]
    assert after["total_findings"] == before["total_findings"] - 1
    assert after["cleanup_eligible"] == before["cleanup_eligible"] - 1

    assert main(["demo", "status"]) == EXIT_OK
    assert "vol-0a1b2c3d4e5f60001" in capsys.readouterr().out
    assert main(["demo", "reset"]) == EXIT_OK
    capsys.readouterr()
    main(["scan", "--mode", "demo", "--no-notify", "--json"])
    reset_summary = json.loads(capsys.readouterr().out)["summary"]
    assert reset_summary["total_findings"] == before["total_findings"]


def test_cleanup_real_mode_requires_explicit_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["scan", "--mode", "demo", "--no-notify"])
    capsys.readouterr()
    # Pretend the operator asks for aws mode: must refuse before touching any client.
    assert (
        main(["cleanup", "--mode", "aws", "--resource", "vol-0a1b2c3d4e5f60001", "--approve"])
        == EXIT_USAGE
    )
    assert "--i-understand-this-deletes-real-resources" in capsys.readouterr().out


def test_cli_hides_slack_webhook_in_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CCG_NOTIFICATION_PROVIDER", "slack")
    monkeypatch.setenv(
        "CCG_SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T1/B1/SECRETTOKEN"
    )
    monkeypatch.setenv("CCG_MODE", "local")  # invalid: no endpoint -> configuration error
    assert main(["validate-config"]) == EXIT_USAGE
    assert "SECRETTOKEN" not in capsys.readouterr().err
