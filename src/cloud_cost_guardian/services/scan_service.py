"""Orchestrates: inventory -> detectors -> report -> artifacts -> notification."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cloud_cost_guardian.detectors import ALL_DETECTORS, DetectorContext
from cloud_cost_guardian.exceptions import NotificationError
from cloud_cost_guardian.logging_config import bind_scan_id, log_event, reset_scan_id
from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.reports import DetectorRun, ScanReport
from cloud_cost_guardian.notifications.base import NotificationProvider, NotificationResult
from cloud_cost_guardian.reporting.json_report import write_json
from cloud_cost_guardian.reporting.markdown_report import write_markdown
from cloud_cost_guardian.reporting.report_builder import ReportBuilder
from cloud_cost_guardian.sources.base import InventorySource

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    report: ScanReport
    json_path: Path
    markdown_path: Path
    notification: NotificationResult | None


class ScanService:
    def __init__(
        self,
        *,
        source: InventorySource,
        detector_ctx: DetectorContext,
        report_builder: ReportBuilder,
        notifier: NotificationProvider | None,
        artifacts_dir: Path,
        policy_description: dict[str, object],
    ) -> None:
        self._source = source
        self._ctx = detector_ctx
        self._builder = report_builder
        self._notifier = notifier
        self._artifacts = artifacts_dir
        self._policy = policy_description

    def run(self, *, notify: bool = True) -> ScanResult:
        scan_id = (
            f"scan-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        )
        token = bind_scan_id(scan_id)
        try:
            return self._run(scan_id, notify)
        finally:
            reset_scan_id(token)

    def _run(self, scan_id: str, notify: bool) -> ScanResult:
        started = time.perf_counter()
        log_event(log, "scan_started", source=self._source.name)
        inventory = self._source.load()
        log_event(
            log,
            "inventory_loaded",
            resources=inventory.resource_count,
            source_errors=len(inventory.source_errors),
        )

        findings: list[Finding] = []
        runs: list[DetectorRun] = []
        warnings: list[str] = list(inventory.source_errors)
        for det_cls in ALL_DETECTORS:
            detector = det_cls(self._ctx)
            if not detector.enabled:
                runs.append(DetectorRun(name=detector.name, status="disabled"))
                continue
            t0 = time.perf_counter()
            log_event(log, "detector_started", detector=detector.name)
            try:
                found = detector.detect(inventory)
            except Exception as exc:
                log.exception("detector %s failed", detector.name)
                runs.append(
                    DetectorRun(
                        name=detector.name,
                        status="failed",
                        resources_inspected=detector.resources_inspected,
                        duration_ms=int((time.perf_counter() - t0) * 1000),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                warnings.append(f"detector {detector.name} failed: {type(exc).__name__}")
                continue
            findings.extend(found)
            runs.append(
                DetectorRun(
                    name=detector.name,
                    status="ok",
                    resources_inspected=detector.resources_inspected,
                    findings=len(found),
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                )
            )
            log_event(
                log,
                "detector_finished",
                detector=detector.name,
                inspected=detector.resources_inspected,
                findings=len(found),
            )

        report = self._builder.build(
            scan_id=scan_id,
            timestamp=self._ctx.now,
            findings=findings,
            resources_scanned=inventory.resource_count,
            detector_runs=runs,
            policy=self._policy,
            warnings=warnings,
        )
        log_event(
            log,
            "findings_generated",
            total=report.summary.total_findings,
            cleanup_eligible=report.summary.cleanup_eligible,
        )

        reports_dir = self._artifacts / "reports"
        json_path = write_json(report, reports_dir / "latest.json")
        md_path = write_markdown(report, reports_dir / "latest.md")
        write_json(report, reports_dir / f"{scan_id}.json")
        log_event(log, "report_created", json=str(json_path), markdown=str(md_path))

        notification: NotificationResult | None = None
        if notify and self._notifier is not None:
            try:
                notification = self._notifier.send_report(report)
                log_event(
                    log,
                    "notification_sent",
                    provider=notification.provider,
                    detail=notification.detail,
                )
            except NotificationError as exc:
                log.warning("notification failed: %s", exc)
                notification = NotificationResult(self._notifier.name, False, str(exc))

        log_event(log, "scan_completed", duration_ms=int((time.perf_counter() - started) * 1000))
        return ScanResult(
            report=report, json_path=json_path, markdown_path=md_path, notification=notification
        )
