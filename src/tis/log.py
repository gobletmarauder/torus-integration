"""Structured JSON logging with conservative personal-data redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar, Token
from typing import Any
from uuid import uuid4

_CORRELATION_ID: ContextVar[str] = ContextVar("correlation_id", default="")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .()\-]{7,}\d)(?!\w)")
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "token",
        "access_token",
        "refresh_token",
        "code",
        "name",
        "first_name",
        "last_name",
        "phone",
        "message",
        "body",
        "note",
        "notes",
        "payload",
        "api_key",
    }
)


def set_correlation_id(value: str | None = None) -> Token[str]:
    """Set a correlation id for the current context and return its reset token."""
    return _CORRELATION_ID.set(value or str(uuid4()))


def reset_correlation_id(token: Token[str]) -> None:
    """Restore the preceding correlation id; this has no external side effects."""
    _CORRELATION_ID.reset(token)


def correlation_id() -> str:
    """Return the current correlation id, creating one for this context if absent."""
    current = _CORRELATION_ID.get()
    if current:
        return current
    current = str(uuid4())
    _CORRELATION_ID.set(current)
    return current


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-safe, recursively redacted representation without logging it."""
    if key and key.lower() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        without_email_local = _EMAIL.sub(
            lambda match: f"[redacted]@{match.group(1).lower()}", value
        )
        return _PHONE.sub("[REDACTED_PHONE]", without_email_local)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[REDACTED]"


class JsonFormatter(logging.Formatter):
    """Serialize approved log metadata as one JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "event": redact(record.getMessage()),
            "correlation_id": correlation_id(),
        }
        fields = getattr(record, "fields", {})
        if isinstance(fields, dict):
            payload.update(redact(fields))
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the `tis` logger to emit redacted JSON to stdout."""
    logger = logging.getLogger("tis")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.handlers[:] = [handler]
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced child of the centrally configured logger."""
    return logging.getLogger(f"tis.{name}")
