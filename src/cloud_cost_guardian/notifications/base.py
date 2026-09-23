from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from cloud_cost_guardian.models.reports import ScanReport


@dataclass(frozen=True)
class NotificationResult:
    provider: str
    delivered: bool
    detail: str


class NotificationProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def send_report(self, report: ScanReport) -> NotificationResult: ...
