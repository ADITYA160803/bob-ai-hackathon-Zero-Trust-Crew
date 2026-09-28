"""
tests/test_bob_client.py

Tests for backend/services/bob_client.py.

All HTTP calls are mocked — no live API calls, no real BOB_API_KEY needed.
The autouse fixture in conftest.py redirects BOB_LOG_PATH to tmp_path so
no test ever touches logs/bob_calls.jsonl.

Covers:
  - Valid JSON response returned as dict
  - Fenced JSON (```json … ```) repaired and parsed
  - Trailing comma repaired and parsed
  - Invalid JSON on first call, valid JSON on retry → success
  - All retries exhausted with invalid JSON → BobUnavailableError
  - HTTP error on first call, valid JSON on retry → success
  - All retries exhausted with HTTP errors → BobUnavailableError
  - Missing prompt file → FileNotFoundError (not BobUnavailableError)
  - Log file written with correct fields (via redirected path)
  - _repair_json corner cases
  - Real logs/bob_calls.jsonl is never modified by the test suite
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

os.environ.setdefault("JAAL_TESTING", "1")

import pytest
import httpx

from backend.services.bob_client import (
    BobUnavailableError,
    _repair_json,
    call_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(content: str, status_code: int = 200) -> MagicMock:
    """Build a fake httpx.Response-like object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    if status_code >= 400:
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=mock,
        )
    else:
        mock.raise_for_status.return_value = None
    return mock


def _make_client(*responses: MagicMock) -> MagicMock:
    """Return a mock httpx.Client whose .post() cycles through responses."""
    client = MagicMock(spec=httpx.Client)
    client.post.side_effect = list(responses)
    return client


VALID_JSON_STR = '{"nodes": [], "edges": []}'
VALID_DICT: dict[str, Any] = {"nodes": [], "edges": []}

FENCED_JSON = "```json\n" + VALID_JSON_STR + "\n```"
TRAILING_COMMA_JSON = '{"nodes": [], "edges": [],}'   # trailing comma
GARBAGE = "Sorry, I cannot help with that."


# ---------------------------------------------------------------------------
# _repair_json unit tests
# ---------------------------------------------------------------------------

class TestRepairJson:
    def test_plain_json_unchanged(self) -> None:
        assert _repair_json(VALID_JSON_STR) == VALID_JSON_STR

    def test_strips_json_fence(self) -> None:
        result = _repair_json("```json\n{\"k\": 1}\n```")
        assert json.loads(result) == {"k": 1}

    def test_strips_plain_fence(self) -> None:
        result = _repair_json("```\n{\"k\": 2}\n```")
        assert json.loads(result) == {"k": 2}

    def test_extracts_outermost_braces(self) -> None:
        result = _repair_json('Here is your answer: {"x": 99} done.')
        assert json.loads(result) == {"x": 99}

    def test_removes_trailing_comma_in_object(self) -> None:
        result = _repair_json('{"a": 1,}')
        assert json.loads(result) == {"a": 1}

    def test_removes_trailing_comma_in_array(self) -> None:
        result = _repair_json('{"a": [1, 2,]}')
        assert json.loads(result) == {"a": [1, 2]}

    def test_no_braces_raises(self) -> None:
        with pytest.raises(ValueError, match="No JSON object found"):
            _repair_json("totally not json at all")


# ---------------------------------------------------------------------------
# call_json — happy paths
# ---------------------------------------------------------------------------

class TestCallJsonHappyPath:
    def test_valid_json_response(self) -> None:
        client = _make_client(_make_response(VALID_JSON_STR))
        result = call_json("extract.md", "some text", "file.csv#L1", _client=client)
        assert result == VALID_DICT

    def test_fenced_json_repaired(self) -> None:
        client = _make_client(_make_response(FENCED_JSON))
        result = call_json("extract.md", "some text", "file.csv#L2", _client=client)
        assert result == VALID_DICT

    def test_trailing_comma_repaired(self) -> None:
        client = _make_client(_make_response(TRAILING_COMMA_JSON))
        result = call_json("extract.md", "some text", "file.csv#L3", _client=client)
        assert result == VALID_DICT


# ---------------------------------------------------------------------------
# call_json — retry scenarios
# ---------------------------------------------------------------------------

class TestCallJsonRetry:
    def test_invalid_then_valid_succeeds(self) -> None:
        """First response is garbage JSON; second is valid → success."""
        client = _make_client(
            _make_response(GARBAGE),
            _make_response(VALID_JSON_STR),
        )
        result = call_json("extract.md", "text", "file.csv#L4", _client=client)
        assert result == VALID_DICT
        assert client.post.call_count == 2

    def test_two_invalids_then_valid_succeeds(self) -> None:
        """Two garbage responses, then valid (MAX_RETRIES=2 → 3 total attempts)."""
        client = _make_client(
            _make_response(GARBAGE),
            _make_response(GARBAGE),
            _make_response(VALID_JSON_STR),
        )
        result = call_json("extract.md", "text", "file.csv#L5", _client=client)
        assert result == VALID_DICT

    def test_all_retries_exhausted_raises(self) -> None:
        """All responses are garbage → BobUnavailableError."""
        client = _make_client(
            _make_response(GARBAGE),
            _make_response(GARBAGE),
            _make_response(GARBAGE),
        )
        with pytest.raises(BobUnavailableError):
            call_json("extract.md", "text", "file.csv#L6", _client=client)

    def test_http_error_then_valid_succeeds(self) -> None:
        """HTTP 500 on first call, valid JSON on retry."""
        client = _make_client(
            _make_response("", status_code=500),
            _make_response(VALID_JSON_STR),
        )
        result = call_json("extract.md", "text", "file.csv#L7", _client=client)
        assert result == VALID_DICT

    def test_all_http_errors_raises(self) -> None:
        """All calls return HTTP 500 → BobUnavailableError."""
        client = _make_client(
            _make_response("", status_code=500),
            _make_response("", status_code=500),
            _make_response("", status_code=500),
        )
        with pytest.raises(BobUnavailableError):
            call_json("extract.md", "text", "file.csv#L8", _client=client)


# ---------------------------------------------------------------------------
# call_json — prompt file not found
# ---------------------------------------------------------------------------

class TestCallJsonPromptNotFound:
    def test_missing_prompt_raises_file_not_found(self) -> None:
        client = _make_client(_make_response(VALID_JSON_STR))
        with pytest.raises(FileNotFoundError):
            call_json("nonexistent_prompt.md", "text", "x#L1", _client=client)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Logging — conftest.py autouse fixture redirects BOB_LOG_PATH to tmp_path
# so these tests read from the same redirected file without any extra patching.
# ---------------------------------------------------------------------------

class TestCallJsonLogging:
    def test_log_file_written_on_success(self, tmp_path: Path) -> None:
        # conftest autouse fixture already set settings.BOB_LOG_PATH → tmp_path/bob_calls.jsonl
        from backend.config import settings
        log_file = Path(settings.BOB_LOG_PATH)

        client = _make_client(_make_response(VALID_JSON_STR))
        call_json("extract.md", "hello", "notes.txt#p1", _client=client)

        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["ok"] is True
        assert record["prompt_file"] == "extract.md"
        assert record["source_ref"] == "notes.txt#p1"
        assert record["attempt"] == 1
        assert "timestamp" in record

    def test_log_file_written_on_failure(self, tmp_path: Path) -> None:
        from backend.config import settings
        log_file = Path(settings.BOB_LOG_PATH)

        client = _make_client(
            _make_response(GARBAGE),
            _make_response(GARBAGE),
            _make_response(GARBAGE),
        )

        with pytest.raises(BobUnavailableError):
            call_json("extract.md", "hello", "notes.txt#p2", _client=client)

        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        # One log line per attempt (3 attempts for MAX_RETRIES=2)
        assert len(lines) == 3
        records = [json.loads(l) for l in lines]
        assert all(r["ok"] is False for r in records)
        assert [r["attempt"] for r in records] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Sentinel: real log must never be modified by the test suite
# ---------------------------------------------------------------------------

class TestRealLogUntouched:
    def test_real_log_not_modified_by_suite(self) -> None:
        """
        Fail if tests have written to the real logs/bob_calls.jsonl.
        The conftest autouse fixture redirects all calls to tmp_path;
        if this file is non-empty something bypassed the fixture.
        """
        real_log = Path("logs") / "bob_calls.jsonl"
        if real_log.exists():
            content = real_log.read_text(encoding="utf-8").strip()
            assert content == "", (
                f"logs/bob_calls.jsonl was modified by the test suite "
                f"(first 200 chars): {content[:200]!r}"
            )
