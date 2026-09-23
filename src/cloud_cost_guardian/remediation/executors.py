"""Executors perform the actual (or simulated) destructive action. Nothing else does."""

from __future__ import annotations

from abc import ABC, abstractmethod

from cloud_cost_guardian.aws.client_factory import AWSClientFactory
from cloud_cost_guardian.demo.state import DemoStateStore
from cloud_cost_guardian.exceptions import RemediationFailedError
from cloud_cost_guardian.models.findings import Finding, RecommendedAction


class RemediationExecutor(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def execute(self, finding: Finding, *, scan_id: str) -> str:
        """Perform the action. Return a short human-readable result. Raise on failure."""


class DemoRemediationExecutor(RemediationExecutor):
    """Simulated cleanup: marks the resource as remediated in local demo state."""

    def __init__(self, store: DemoStateStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "demo-simulation"

    def execute(self, finding: Finding, *, scan_id: str) -> str:
        self._store.mark_remediated(
            resource_id=finding.resource_id,
            resource_type=finding.resource_type.value,
            action=finding.recommended_action.value,
            scan_id=scan_id,
        )
        return f"simulated {finding.recommended_action.value} recorded in {self._store.path}"


class AWSRemediationExecutor(RemediationExecutor):
    """Real AWS actions. Requires the *remediation* IAM policy, not the scan policy."""

    def __init__(self, factory: AWSClientFactory) -> None:
        self._f = factory

    @property
    def name(self) -> str:
        return "aws"

    def execute(self, finding: Finding, *, scan_id: str) -> str:
        from cloud_cost_guardian.aws import ebs, eip, snapshots

        ec2 = self._f.client("ec2")
        action = finding.recommended_action
        try:
            if action is RecommendedAction.DELETE_VOLUME:
                ebs.delete_volume(ec2, finding.resource_id, dry_run=False)
            elif action is RecommendedAction.RELEASE_EIP:
                eip.release_address(ec2, finding.resource_id, dry_run=False)
            elif action is RecommendedAction.DELETE_SNAPSHOT:
                snapshots.delete_snapshot(ec2, finding.resource_id, dry_run=False)
            else:
                raise RemediationFailedError(
                    f"action {action.value} is not executable by this tool"
                )
        except RemediationFailedError:
            raise
        except Exception as exc:
            raise RemediationFailedError(str(exc)) from exc
        return f"{action.value} executed on {finding.resource_id}"
