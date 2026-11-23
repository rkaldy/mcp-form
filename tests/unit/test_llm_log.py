import json
import logging

import pytest

from form.llm.llm import LLM


def test_log_truncates_nested_json_values(caplog: pytest.LogCaptureFixture):
    """Truncate long nested string values while preserving other JSON values."""
    json_data = json.dumps(
        {
            "nested": {"text": "ž" * 31},
            "values": ["", "a" * 30, "b" * 45, 123, True, None],
            "mapping": {"key" * 20: "c" * 32},
            "date": "2026-01-02",
        }
    )

    with caplog.at_level(logging.DEBUG, logger="form.llm.llm"):
        LLM._log("SCAN", json_data)

    assert len(caplog.records) == 1
    event, payload = caplog.records[0].getMessage().split(": ", 1)
    assert event == "SCAN"
    assert json.loads(payload) == {
        "nested": {"text": "ž" * 30 + "... (31 chars)"},
        "values": ["", "a" * 30, "b" * 30 + "... (45 chars)", 123, True, None],
        "mapping": {"key" * 20: "c" * 30 + "... (32 chars)"},
        "date": "2026-01-02",
    }


def test_log_supports_json_string_at_root(caplog: pytest.LogCaptureFixture):
    """Truncate a JSON document whose root value is a string."""
    with caplog.at_level(logging.DEBUG, logger="form.llm.llm"):
        LLM._log("scan.request", json.dumps("x" * 40))

    assert len(caplog.records) == 1
    event, payload = caplog.records[0].getMessage().split(": ", 1)
    assert event == "scan.request"
    assert json.loads(payload) == "x" * 30 + "... (40 chars)"


def test_log_rejects_invalid_json_when_debug_enabled(caplog: pytest.LogCaptureFixture):
    """Raise a JSON decoding error for invalid input when debug logging is enabled."""
    with (
        caplog.at_level(logging.DEBUG, logger="form.llm.llm"),
        pytest.raises(json.JSONDecodeError),
    ):
        LLM._log("SCAN", "invalid json")


def test_log_skips_parsing_when_debug_disabled(caplog: pytest.LogCaptureFixture):
    """Ignore invalid JSON without parsing or logging it when debug is disabled."""
    with caplog.at_level(logging.WARNING, logger="form.llm.llm"):
        LLM._log("SCAN", "invalid json")

    assert caplog.records == []
