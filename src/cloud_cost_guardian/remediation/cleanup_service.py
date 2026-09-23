"""The remediation pipeline.

    finding -> protection -> policy -> approval -> re-fetch -> re-verify
            -> execute -> audit -> verify

Every gate writes an audit record whether it passes or blocks. Dry-run stops before approval
and never calls an executor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cloud_cost_guardian.detectors import ALL_DETECTORS, DetectorContext
from cloud_cost_guardian.exceptions import InventorySourceError, RemediationFailedError
from cloud_cost_guardian.logging_config import log_event
from cloud_cost_guardian.models.findings import Finding
from cloud_cost_guardian.models.resources import Inventory
from cloud_cost_guardian.policies.cleanup_policy import CleanupPolicy
from cloud_cost_guardian.policies.protection import ProtectionPolicy
from cloud_cost_guardian.remediation.approval import ApprovalProvider
from cloud_cost_guardian.remediation.audit import AuditLogger, AuditRecord
from cloud_cost_guardian.remediation.executors import RemediationExecutor
from cloud_cost_guardian.sources.base import InventorySource

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanupOutcome:
    finding: Finding
    status: str  # dry-run | blocked | remediated | failed
    stage: str  # protection | policy | approval | verification | execution | verify-after | dry-run
    detail: str
    audit: AuditRecord | None = None

    @property
    def remediated(self) -> bool:
        return self.status == "remediated"


@dataclass
class _Gates:
    approval: str = "not-evaluated"
    policy: str = "not-evaluated"
    protection: str = "not-evaluated"
    verification: str = "not-evaluated"
    action: str = "not-attempted"
    error: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class CleanupService:
    def __init__(
        self,
        *,
        source: InventorySource,
        detector_ctx: DetectorContext,
        protection: ProtectionPolicy,
        cleanup_policy: CleanupPolicy,
        approval: ApprovalProvider,
        executor: RemediationExecutor | None,
        audit: AuditLogger,
        mode: str,
    ) -> None:
        self._source = source
        self._ctx = detector_ctx
        self._protection = protection
        self._policy = cleanup_policy
        self._approval = approval
        self._executor = executor
        self._audit = audit
        self._mode = mode

    # ------------------------------------------------------------------ public API
    def dry_run(self, findings: list[Finding], scan_id: str) -> list[CleanupOutcome]:
        outcomes: list[CleanupOutcome] = []
        for f in findings:
            gates = _Gates()
            if self._gate_protection(f, gates) and self._gate_policy(f, gates):
                gates.action = "dry-run (no action taken)"
                outcomes.append(
                    self._finish(
                        f,
                        scan_id,
                        gates,
                        dry_run=True,
                        status="dry-run",
                        stage="dry-run",
                        detail="would remediate after approval",
                    )
                )
            else:
                outcomes.append(
                    self._finish(
                        f,
                        scan_id,
                        gates,
                        dry_run=True,
                        status="blocked",
                        stage=_blocked_stage(gates),
                        detail=_blocked_detail(gates),
                    )
                )
        return outcomes

    def remediate(self, finding: Finding, scan_id: str) -> CleanupOutcome:
        gates = _Gates()
        log_event(
            log,
            "cleanup_initiated",
            resource_id=finding.resource_id,
            action=finding.recommended_action.value,
            mode=self._mode,
        )

        if not self._gate_protection(finding, gates):
            return self._finish(
                finding,
                scan_id,
                gates,
                dry_run=False,
                status="blocked",
                stage="protection",
                detail=gates.protection,
            )
        if not self._gate_policy(finding, gates):
            return self._finish(
                finding,
                scan_id,
                gates,
                dry_run=False,
                status="blocked",
                stage="policy",
                detail=gates.policy,
            )

        decision = self._approval.request(finding)
        verdict = "approved" if decision.approved else "denied"
        gates.approval = f"{verdict} by {decision.approver}: {decision.detail}"
        if not decision.approved:
            return self._finish(
                finding,
                scan_id,
                gates,
                dry_run=False,
                status="blocked",
                stage="approval",
                detail=decision.detail,
            )

        fresh = self._reverify(finding, gates)
        if fresh is None:
            return self._finish(
                finding,
                scan_id,
                gates,
                dry_run=False,
                status="blocked",
                stage="verification",
                detail=gates.verification,
            )

        if self._executor is None:
            gates.action = "no executor configured"
            return self._finish(
                finding,
                scan_id,
                gates,
                dry_run=False,
                status="blocked",
                stage="execution",
                detail="no remediation executor available for this mode",
            )

        try:
            result = self._executor.execute(fresh, scan_id=scan_id)
        except RemediationFailedError as exc:
            gates.action = "failed"
            gates.error = str(exc)
            return self._finish(
                finding,
                scan_id,
                gates,
                dry_run=False,
                status="failed",
                stage="execution",
                detail=str(exc),
            )
        gates.action = f"executed via {self._executor.name}: {result}"

        after = self._verify_after(fresh)
        gates.metadata["post_verification"] = after
        outcome = self._finish(
            finding,
            scan_id,
            gates,
            dry_run=False,
            status="remediated",
            stage="verify-after",
            detail=after,
        )
        log_event(
            log,
            "cleanup_result",
            resource_id=finding.resource_id,
            status=outcome.status,
            detail=after,
        )
        return outcome

    # ------------------------------------------------------------------ gates
    def _gate_protection(self, f: Finding, gates: _Gates) -> bool:
        prot = self._protection.evaluate(f.metadata.get("tags") or {})
        if f.protected or prot.protected:
            gates.protection = (
                f"BLOCKED: {prot.reason or f.protection_reason or 'finding marked protected'}"
            )
            return False
        gates.protection = "passed"
        return True

    def _gate_policy(self, f: Finding, gates: _Gates) -> bool:
        decision = self._policy.evaluate(f)
        if not decision.eligible or not f.cleanup_eligible:
            why = (
                decision.blocked_reason if not decision.eligible else "finding not cleanup-eligible"
            )
            gates.policy = f"BLOCKED: {why}"
            return False
        gates.policy = "passed"
        return True

    def _reverify(self, f: Finding, gates: _Gates) -> Finding | None:
        """Re-fetch the resource and re-run the detector. Any drift blocks the action."""
        try:
            inventory: Inventory = self._source.refetch(f.resource_type, f.resource_id)
        except InventorySourceError as exc:
            gates.verification = f"BLOCKED: re-fetch failed: {exc}"
            return None
        if inventory.resource_count == 0:
            gates.verification = "BLOCKED: resource no longer exists (already removed?)"
            return None
        fresh = self._redetect(f, inventory)
        if fresh is None:
            gates.verification = (
                "BLOCKED: resource state changed since scan; finding no longer reproduces"
            )
            return None
        if fresh.protected:
            gates.verification = f"BLOCKED: resource is now protected ({fresh.protection_reason})"
            return None
        if not fresh.cleanup_eligible or not self._policy.evaluate(fresh).eligible:
            gates.verification = "BLOCKED: resource no longer satisfies cleanup policy"
            return None
        if fresh.recommended_action is not f.recommended_action:
            gates.verification = "BLOCKED: recommended action changed since scan"
            return None
        gates.verification = "passed: resource re-fetched and finding reproduced"
        return fresh

    def _redetect(self, f: Finding, inventory: Inventory) -> Finding | None:
        for det_cls in ALL_DETECTORS:
            if det_cls.category is not f.category:
                continue
            detector = det_cls(self._ctx)
            for candidate in detector.detect(inventory):
                if candidate.resource_id == f.resource_id:
                    return candidate
        return None

    def _verify_after(self, f: Finding) -> str:
        try:
            inventory = self._source.refetch(f.resource_type, f.resource_id)
        except InventorySourceError as exc:
            return f"post-action verification could not re-fetch: {exc}"
        if inventory.resource_count == 0:
            return "verified: resource no longer present"
        if self._redetect(f, inventory) is None:
            return "verified: finding no longer reproduces"
        return (
            "WARNING: resource still matches the finding after remediation (eventual consistency?)"
        )

    # ------------------------------------------------------------------ audit
    def _finish(
        self,
        f: Finding,
        scan_id: str,
        gates: _Gates,
        *,
        dry_run: bool,
        status: str,
        stage: str,
        detail: str,
    ) -> CleanupOutcome:
        record = AuditRecord(
            timestamp=datetime.now(timezone.utc),
            scan_id=scan_id,
            finding_id=f.finding_id,
            resource_id=f.resource_id,
            resource_type=f.resource_type.value,
            region=f.region,
            requested_action=f.recommended_action.value,
            mode=self._mode,
            dry_run=dry_run,
            approval_result=gates.approval,
            policy_result=gates.policy,
            protection_result=gates.protection,
            verification_result=gates.verification,
            action_result=gates.action,
            error=gates.error,
            metadata={"status": status, "stage": stage, **gates.metadata},
        )
        self._audit.record(record)
        return CleanupOutcome(finding=f, status=status, stage=stage, detail=detail, audit=record)


def _blocked_stage(g: _Gates) -> str:
    if g.protection.startswith("BLOCKED"):
        return "protection"
    if g.policy.startswith("BLOCKED"):
        return "policy"
    return "unknown"


def _blocked_detail(g: _Gates) -> str:
    return g.protection if g.protection.startswith("BLOCKED") else g.policy
