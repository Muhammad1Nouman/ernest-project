"""Structured operational logging without patient payloads."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

CURRENT_RUN_ID: ContextVar[str | None] = ContextVar("current_run_id", default=None)
CURRENT_IMPLEMENTATION: ContextVar[str | None] = ContextVar(
    "current_implementation", default=None
)

SAFE_FIELDS = (
    "run_id",
    "implementation",
    "stage",
    "event",
    "status",
    "resource_type",
    "error_code",
    "count",
    "duration_ms",
    "operation",
    "attempt",
    "max_attempts",
    "delay_seconds",
)


class SafeJSONFormatter(logging.Formatter):
    """Serialize an allow-list of operational fields as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in SAFE_FIELDS:
            value = getattr(record, field, None)
            if value is None and field == "run_id":
                value = CURRENT_RUN_ID.get()
            elif value is None and field == "implementation":
                value = CURRENT_IMPLEMENTATION.get()
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def set_log_context(run_id: str, implementation: str) -> None:
    """Attach non-PHI run context to all logs emitted in this execution context."""
    CURRENT_RUN_ID.set(run_id)
    CURRENT_IMPLEMENTATION.set(implementation)
