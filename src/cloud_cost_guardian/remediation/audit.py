"""Append-only JSONL audit trail for every remediation attempt (successful or blocked)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AuditRecord(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scan_id: str
    finding_id: str
    resource_id: str
    resource_type: str
    region: str
    requested_action: str
    mode: str
    dry_run: bool
    approval_result: str
    policy_result: str
    protection_result: str
    verification_result: str
    action_result: str
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditLogger:
    def __init__(self, artifacts_dir: Path) -> None:
        self._dir = artifacts_dir / "audit"

    @property
    def log_path(self) -> Path:
        return self._dir / "cleanup-audit.jsonl"

    @property
    def latest_path(self) -> Path:
        return self._dir / "latest-cleanup.json"

    def record(self, entry: AuditRecord) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        line = entry.model_dump_json()
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self.latest_path.write_text(json.dumps(json.loads(line), indent=2), encoding="utf-8")

    def read_all(self) -> list[AuditRecord]:
        if not self.log_path.exists():
            return []
        records: list[AuditRecord] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(AuditRecord.model_validate_json(line))
        return records
