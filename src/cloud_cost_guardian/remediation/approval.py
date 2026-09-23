"""Approval providers. Approval is *per resource* and must echo the exact resource ID."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from cloud_cost_guardian.models.findings import Finding


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    approver: str
    detail: str


class ApprovalProvider(ABC):
    @abstractmethod
    def request(self, finding: Finding) -> ApprovalDecision: ...


class ExplicitApproval(ApprovalProvider):
    """Non-interactive approval: caller passed ``--approve`` with the exact resource ID."""

    def __init__(self, approved_resource_id: str | None, approver: str = "cli-flag") -> None:
        self._rid = approved_resource_id
        self._approver = approver

    def request(self, finding: Finding) -> ApprovalDecision:
        if self._rid is None:
            return ApprovalDecision(False, self._approver, "no approval flag supplied")
        if self._rid != finding.resource_id:
            return ApprovalDecision(
                False, self._approver, "approval was for a different resource id"
            )
        return ApprovalDecision(
            True, self._approver, f"explicit approval for {finding.resource_id}"
        )


class InteractiveApproval(ApprovalProvider):
    """Prompts the operator to type the exact resource ID. Anything else is a denial."""

    def __init__(self, prompt: Callable[[str], str] | None = None) -> None:
        self._prompt = prompt

    def _ask(self, message: str) -> str:
        if self._prompt is not None:
            return self._prompt(message)
        return input(message)  # resolved lazily so tests/tools can substitute builtins.input

    def request(self, finding: Finding) -> ApprovalDecision:
        try:
            answer = self._ask(
                f"Type the resource id '{finding.resource_id}' to approve "
                f"{finding.recommended_action.value}, "
                "or anything else to abort: "
            )
        except (EOFError, KeyboardInterrupt):
            return ApprovalDecision(False, "interactive", "prompt aborted")
        if answer.strip() == finding.resource_id:
            return ApprovalDecision(True, "interactive", "operator typed matching resource id")
        return ApprovalDecision(False, "interactive", "operator input did not match resource id")


class DenyAll(ApprovalProvider):
    def request(self, finding: Finding) -> ApprovalDecision:
        return ApprovalDecision(False, "deny-all", "approval provider denies everything")
