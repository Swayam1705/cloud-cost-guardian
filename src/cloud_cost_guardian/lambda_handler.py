"""AWS Lambda entry point for the OPTIONAL scheduled read-only scan.

Deployed by ``terraform/`` (optional, may incur AWS charges). Performs a scan and publishes
the report through the configured notifier. It never remediates.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from cloud_cost_guardian.app import Application
from cloud_cost_guardian.config import Mode, load_settings
from cloud_cost_guardian.logging_config import configure_logging

log = logging.getLogger(__name__)


def handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    # Lambda's only writable filesystem is its ephemeral temp dir; nothing sensitive goes there.
    tmp = Path(tempfile.gettempdir())
    settings = load_settings(
        mode=Mode.AWS, artifacts_dir=tmp / "ccg-artifacts", data_dir=tmp / "ccg-data"
    )
    configure_logging(settings.log_level, "json")
    app = Application.build(settings)
    result = app.scan_service(app.notifier()).run(notify=True)
    s = result.report.summary
    return {
        "scan_id": result.report.scan_id,
        "findings": s.total_findings,
        "cleanup_eligible": s.cleanup_eligible,
        "estimated_monthly_savings": s.estimated_monthly_savings,
        "notification": result.notification.delivered if result.notification else None,
    }
