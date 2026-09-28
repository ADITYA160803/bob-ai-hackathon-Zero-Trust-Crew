"""
backend/services/bob_client.py

Thin wrapper around the Bob LLM API.  ALL provider-specific HTTP details
live here — change only this file if the Bob API changes.

Public API
──────────
call_json(prompt_file, text, source_ref) -> dict
    Load backend/prompts/<prompt_file>, fill {{chunk}} and {{source_ref}},
    POST to the Bob API, parse and return a dict.

Errors
──────
BobUnavailableError   raised when all retries are exhausted (HTTP error or
                      JSON that cannot be repaired).

JSON repair pipeline (applied before each retry):
  1. Strip Markdown code fences (``` … ```)
  2. Extract the outermost { … } block
  3. Remove trailing commas before ] or }

Logging
───────
Every attempt is appended to the path given by settings.BOB_LOG_PATH
(default: logs/bob_calls.jsonl) as one JSON line:
  {timestamp, prompt_file, source_ref, attempt, request_text, response_raw, ok}
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class BobUnavailableError(RuntimeError):
    """Raised when the Bob API cannot return valid JSON after all retries."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_prompt(prompt_file: str, text: str, source_ref: str) -> str:
    """Load a prompt template and substitute {{chunk}} and {{source_ref}}."""
    path = _PROMPTS_DIR / prompt_file
    try:
        template = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Prompt file not found: {path}. "
            "Ensure backend/prompts/<prompt_file> exists."
        )
    prompt = template.replace("{{chunk}}", text).replace("{{source_ref}}", source_ref)
    return prompt


def _repair_json(raw: str) -> str:
    """
    Best-effort JSON repair.  Applies three transformations in order:
      1. Strip Markdown code fences.
      2. Extract the outermost { … } block.
      3. Remove trailing commas before ] or }.
    Returns the (possibly repaired) string; raises ValueError if no
    { } block can be found at all.
    """
    # 1. Strip ``` fences (with optional language tag)
    raw = re.sub(r"```[a-zA-Z]*\s*", "", raw).strip()

    # 2. Extract outermost { … }
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in response.")
    raw = raw[start : end + 1]

    # 3. Remove trailing commas before ] or }
    raw = re.sub(r",\s*([}\]])", r"\1", raw)

    return raw


def _append_log(
    *,
    prompt_file: str,
    source_ref: str,
    attempt: int,
    request_text: str,
    response_raw: str,
    ok: bool,
) -> None:
    """Append one structured line to the configured BOB_LOG_PATH."""
    log_file = Path(settings.BOB_LOG_PATH)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_file": prompt_file,
        "source_ref": source_ref,
        "attempt": attempt,
        "request_text": request_text,
        "response_raw": response_raw,
        "ok": ok,
    }
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _parse_content(raw: str) -> dict[str, Any]:
    """Try plain parse, then repair-and-parse. Raise ValueError on failure."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = _repair_json(raw)
        return json.loads(repaired)


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def call_json(
    prompt_file: str,
    text: str,
    source_ref: str,
    *,
    _client: httpx.Client | None = None,
) -> dict[str, Any]:
    """
    Call the Bob LLM API and return a parsed JSON dict.

    Parameters
    ----------
    prompt_file : str
        Filename inside backend/prompts/ (e.g. "extract.md").
    text : str
        The chunk of source text to analyse.
    source_ref : str
        Evidence reference included in the prompt (e.g. "call_logs.csv#L14").
    _client : httpx.Client | None
        Injected in tests to avoid live HTTP calls.

    Raises
    ------
    BobUnavailableError
        When every retry is exhausted without a valid JSON response.
    """
    prompt = _load_prompt(prompt_file, text, source_ref)

    headers = {
        "Authorization": f"Bearer {settings.BOB_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.MODEL_NAME,
        "temperature": settings.TEMPERATURE,
        "messages": [{"role": "user", "content": prompt}],
    }

    client = _client or httpx.Client(timeout=30)
    last_error: Exception = BobUnavailableError("No attempts made.")

    for attempt in range(1, settings.MAX_RETRIES + 2):  # 1-based; +1 for initial try
        response_raw = ""
        ok = False
        try:
            resp = client.post(
                settings.BOB_API_URL,
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            # Bob API returns OpenAI-compatible chat completion
            response_raw = resp.json()["choices"][0]["message"]["content"]
            result = _parse_content(response_raw)
            ok = True
            _append_log(
                prompt_file=prompt_file,
                source_ref=source_ref,
                attempt=attempt,
                request_text=text,
                response_raw=response_raw,
                ok=True,
            )
            return result

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_error = exc
            logger.warning(
                "Bob response not valid JSON (attempt %d/%d): %s",
                attempt,
                settings.MAX_RETRIES + 1,
                exc,
            )

        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning(
                "Bob HTTP error (attempt %d/%d): %s",
                attempt,
                settings.MAX_RETRIES + 1,
                exc,
            )

        finally:
            if not ok:
                _append_log(
                    prompt_file=prompt_file,
                    source_ref=source_ref,
                    attempt=attempt,
                    request_text=text,
                    response_raw=response_raw,
                    ok=False,
                )

        if attempt >= settings.MAX_RETRIES + 1:
            break

    raise BobUnavailableError(
        f"Bob API unavailable after {settings.MAX_RETRIES + 1} attempt(s). "
        f"Last error: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# BobClient class — for test_integration.py compatibility
# ---------------------------------------------------------------------------

class BobClient:
    """
    Object-oriented wrapper around the Bob LLM API.

    When api_key is empty or None, the client operates in offline mode and
    returns safe stub responses without making any network calls.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key or ""
        self._base_url = base_url

    @property
    def offline(self) -> bool:
        """True when no API key is configured."""
        return not bool(self._api_key)

    def extract(self, prompt: str, context: dict) -> dict:
        """
        Call Bob to extract entities from a text prompt.

        In offline mode, returns a safe stub with empty nodes/edges lists.
        """
        if self.offline:
            return {
                "_offline": True,
                "nodes": [],
                "edges": [],
            }
        # Online path — delegate to call_json
        try:
            return call_json("extract.md", prompt, context.get("source_ref", "unknown"))
        except (BobUnavailableError, Exception):
            return {"_offline": True, "nodes": [], "edges": []}

    def summarise(self, prompt: str) -> str:
        """
        Ask Bob to write a narrative summary.

        In offline mode, returns a clearly labelled OFFLINE stub string.
        """
        if self.offline:
            return (
                "[OFFLINE MODE] Bob API key not configured. "
                "This is an offline stub response — no real summary was generated. "
                "Configure BOB_API_KEY to enable live summarisation."
            )
        # Online path — not yet wired to a specific endpoint
        return f"[Bob summary not yet implemented for: {prompt[:80]}]"
