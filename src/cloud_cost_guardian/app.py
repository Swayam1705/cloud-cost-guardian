"""Composition root — wires settings into concrete services for a given mode."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cloud_cost_guardian.config import Mode, Settings
from cloud_cost_guardian.demo.fixture_loader import FixtureInventorySource
from cloud_cost_guardian.demo.state import DemoStateStore
from cloud_cost_guardian.detectors import DetectorContext
from cloud_cost_guardian.notifications.base import NotificationProvider
from cloud_cost_guardian.notifications.factory import build_notification_provider
from cloud_cost_guardian.policies.cleanup_policy import CleanupPolicy
from cloud_cost_guardian.policies.protection import ProtectionPolicy
from cloud_cost_guardian.policies.thresholds import Thresholds
from cloud_cost_guardian.pricing.catalog import CatalogPricingProvider, PricingCatalog
from cloud_cost_guardian.pricing.estimator import CostEstimator
from cloud_cost_guardian.remediation.approval import ApprovalProvider
from cloud_cost_guardian.remediation.audit import AuditLogger
from cloud_cost_guardian.remediation.cleanup_service import CleanupService
from cloud_cost_guardian.remediation.executors import RemediationExecutor
from cloud_cost_guardian.reporting.report_builder import ReportBuilder
from cloud_cost_guardian.services.scan_service import ScanService
from cloud_cost_guardian.sources.base import InventorySource


@dataclass
class Application:
    settings: Settings
    thresholds: Thresholds
    protection: ProtectionPolicy
    cleanup_policy: CleanupPolicy
    pricing: CatalogPricingProvider
    estimator: CostEstimator
    source: InventorySource
    demo_state: DemoStateStore | None
    now: datetime

    # ------------------------------------------------------------------ factories
    @classmethod
    def build(cls, settings: Settings, *, now: datetime | None = None) -> Application:
        now = now or datetime.now(timezone.utc)
        thresholds = Thresholds.from_settings(settings)
        protection = ProtectionPolicy(settings.protected_tag_pairs)
        catalog = (
            PricingCatalog.load_from_path(settings.pricing_catalog_path)
            if settings.pricing_catalog_path
            else PricingCatalog.load_default()
        )
        pricing = CatalogPricingProvider(catalog)
        estimator = CostEstimator(pricing)

        demo_state: DemoStateStore | None = None
        source: InventorySource
        if settings.mode is Mode.DEMO:
            demo_state = DemoStateStore(settings.data_dir)
            source = FixtureInventorySource(
                inventory_path=settings.fixture_inventory_path,
                metrics_path=settings.fixture_metrics_path,
                state_store=demo_state,
                now=now,
            )
        else:
            from cloud_cost_guardian.aws.client_factory import AWSClientFactory
            from cloud_cost_guardian.aws.inventory_source import AWSInventorySource

            source = AWSInventorySource(AWSClientFactory(settings), thresholds, now=now)

        return cls(
            settings=settings,
            thresholds=thresholds,
            protection=protection,
            cleanup_policy=CleanupPolicy(thresholds),
            pricing=pricing,
            estimator=estimator,
            source=source,
            demo_state=demo_state,
            now=now,
        )

    @property
    def detector_context(self) -> DetectorContext:
        return DetectorContext(
            thresholds=self.thresholds,
            protection=self.protection,
            estimator=self.estimator,
            now=self.now,
        )

    @property
    def artifacts_dir(self) -> Path:
        return self.settings.artifacts_dir

    def report_builder(self) -> ReportBuilder:
        return ReportBuilder(
            mode=self.settings.mode.value,
            region=self.settings.aws_region,
            pricing_catalog=self.pricing.name,
            pricing_disclaimer=self.pricing.catalog.disclaimer,
        )

    def notifier(self) -> NotificationProvider:
        return build_notification_provider(self.settings)

    def scan_service(self, notifier: NotificationProvider | None = None) -> ScanService:
        return ScanService(
            source=self.source,
            detector_ctx=self.detector_context,
            report_builder=self.report_builder(),
            notifier=notifier,
            artifacts_dir=self.artifacts_dir,
            policy_description={
                "thresholds": self.thresholds.describe(),
                "protected_tags": self.protection.rules,
            },
        )

    def executor(self, *, allow_aws_destructive: bool) -> RemediationExecutor | None:
        if self.settings.mode is Mode.DEMO:
            assert self.demo_state is not None
            from cloud_cost_guardian.remediation.executors import DemoRemediationExecutor

            return DemoRemediationExecutor(self.demo_state)
        if not allow_aws_destructive:
            return None
        from cloud_cost_guardian.aws.client_factory import AWSClientFactory
        from cloud_cost_guardian.remediation.executors import AWSRemediationExecutor

        return AWSRemediationExecutor(AWSClientFactory(self.settings))

    def cleanup_service(
        self, approval: ApprovalProvider, *, allow_aws_destructive: bool = False
    ) -> CleanupService:
        return CleanupService(
            source=self.source,
            detector_ctx=self.detector_context,
            protection=self.protection,
            cleanup_policy=self.cleanup_policy,
            approval=approval,
            executor=self.executor(allow_aws_destructive=allow_aws_destructive),
            audit=AuditLogger(self.artifacts_dir),
            mode=self.settings.mode.value,
        )
