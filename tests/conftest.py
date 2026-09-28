"""
tests/conftest.py

Session-wide pytest configuration for JAAL tests.

Fixtures
────────
redirect_bob_log (autouse, session-scoped helper + function-scoped autouse)
    Redirects settings.BOB_LOG_PATH to a temporary directory for EVERY test
    so that no test ever writes to the real logs/bob_calls.jsonl.

    Implementation note: we patch the attribute on the already-instantiated
    settings object.  bob_client._append_log reads settings.BOB_LOG_PATH at
    call time (not at import time), so the patch takes effect immediately.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("JAAL_TESTING", "1")

import pytest


# Real log file path — used by the sentinel test below.
_REAL_LOG = Path("logs") / "bob_calls.jsonl"


@pytest.fixture(autouse=True)
def redirect_bob_log(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Redirect BOB_LOG_PATH to a per-test temp directory.
    Runs automatically for every test in the suite.
    """
    from backend.config import settings  # imported here so JAAL_TESTING is already set

    fake_log = str(tmp_path / "bob_calls.jsonl")
    monkeypatch.setattr(settings, "BOB_LOG_PATH", fake_log)
