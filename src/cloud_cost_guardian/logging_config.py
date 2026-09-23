"""Structured logging with secret redaction.

Two formats are supported: human ``text`` and machine ``json``. Every record can carry a
``scan_id`` (via :func:`bind_scan_id`) so that all log lines from one scan can be correlated.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

_scan_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ccg_scan_id", default=None
)

# Patterns that must never reach a log sink. Matched case-insensitively against the final message.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+", re.IGNORECASE),
    re.compile(r"(AKIA|ASIA)[0-9A-Z]{16}"),
    re.compile(
        r"(aws_secret_access_key|secret|token|password|webhook)\s*[=:]\s*\S+", re.IGNORECASE
    ),
)


def redact(text: str) -> str:
    """Replace anything that looks like a credential with ``[REDACTED]``."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def bind_scan_id(scan_id: str | None) -> contextvars.Token[str | None]:
    """Attach a scan identifier to all subsequent log records in this context."""
    return _scan_id_var.set(scan_id)


def reset_scan_id(token: contextvars.Token[str | None]) -> None:
    _scan_id_var.reset(token)


class _ScanIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.scan_id = _scan_id_var.get() or "-"
        return True


class _RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "scan_id": getattr(record, "scan_id", "-"),
            "message": record.getMessage(),
        }
        extra = getattr(record, "ccg_extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, default=str))


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure the root logger once. Safe to call repeatedly."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_ScanIdFilter())
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            _RedactingTextFormatter(
                "%(asctime)s %(levelname)-7s [%(scan_id)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    root.addHandler(handler)
    root.setLevel(level.upper())
    # boto is very chatty at DEBUG; keep it at WARNING regardless.
    for noisy in ("botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a structured event (``event=... key=value``) that is also JSON-friendly."""
    rendered = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info("%s %s", event, rendered, extra={"ccg_extra": {"event": event, **fields}})
