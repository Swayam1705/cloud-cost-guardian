"""Simulated remediation state for demo mode.

Stored as JSON under ``data/demo_state.json``. Resources listed here are treated as
already remediated so re-scans reflect the outcome of an approved (simulated) cleanup.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RemediatedRecord(BaseModel):
    resource_id: str
    resource_type: str
    action: str
    remediated_at: datetime
    scan_id: str


class DemoState(BaseModel):
    remediated: list[RemediatedRecord] = Field(default_factory=list)

    @property
    def remediated_ids(self) -> set[str]:
        return {r.resource_id for r in self.remediated}


class DemoStateStore:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "demo_state.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> DemoState:
        if not self._path.exists():
            return DemoState()
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
            return DemoState.model_validate(raw)
        except (json.JSONDecodeError, ValueError):
            # Corrupt state must never crash a scan; start clean but keep the bad file.
            backup = self._path.with_suffix(".corrupt.json")
            self._path.replace(backup)
            return DemoState()

    def save(self, state: DemoState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def mark_remediated(
        self, *, resource_id: str, resource_type: str, action: str, scan_id: str
    ) -> None:
        state = self.load()
        if resource_id in state.remediated_ids:
            return
        state.remediated.append(
            RemediatedRecord(
                resource_id=resource_id,
                resource_type=resource_type,
                action=action,
                remediated_at=datetime.now(timezone.utc),
                scan_id=scan_id,
            )
        )
        self.save(state)

    def reset(self) -> None:
        if self._path.exists():
            self._path.unlink()
