"""Structured logging and redaction tests."""

import json
import logging

from tis.log import JsonFormatter, redact, reset_correlation_id, set_correlation_id


def test_recursive_redaction_removes_personal_and_secret_data() -> None:
    value = redact(
        {
            "email": "person@example.com",
            "name": "Synthetic Person",
            "phone": "+1 (555) 555-0100",
            "authorization": "Bearer synthetic",
            "message": "private body",
            "notes": "private note",
        }
    )
    rendered = json.dumps(value)
    assert "person" not in rendered
    assert "Synthetic Person" not in rendered
    assert "555" not in rendered
    assert "Bearer" not in rendered
    assert "private" not in rendered
    assert "example.com" in rendered


def test_json_formatter_includes_correlation_id_without_raw_fields() -> None:
    token = set_correlation_id("run-synthetic")
    try:
        record = logging.LogRecord("tis.test", logging.INFO, "", 1, "safe_event", (), None)
        record.fields = {"email": "local@example.com", "body": "hidden"}
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_correlation_id(token)
    assert payload["correlation_id"] == "run-synthetic"
    assert payload["email"] == "[redacted]@example.com"
    assert payload["body"] == "[REDACTED]"
