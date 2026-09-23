"""Approval-gated remediation with audit trail."""

from cloud_cost_guardian.remediation.approval import (
    ApprovalDecision,
    ApprovalProvider,
    ExplicitApproval,
    InteractiveApproval,
)
from cloud_cost_guardian.remediation.audit import AuditLogger, AuditRecord
from cloud_cost_guardian.remediation.cleanup_service import CleanupOutcome, CleanupService
from cloud_cost_guardian.remediation.executors import DemoRemediationExecutor, RemediationExecutor

__all__ = [
    "ApprovalDecision",
    "ApprovalProvider",
    "AuditLogger",
    "AuditRecord",
    "CleanupOutcome",
    "CleanupService",
    "DemoRemediationExecutor",
    "ExplicitApproval",
    "InteractiveApproval",
    "RemediationExecutor",
]
