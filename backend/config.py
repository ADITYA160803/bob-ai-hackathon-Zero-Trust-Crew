"""
JAAL — Application settings.

Loaded from a .env file via python-dotenv. All values are typed and
validated by Pydantic Settings (part of pydantic v2 extras / pydantic-settings).
If pydantic-settings is not available the module falls back to a simple
dataclass populated from os.environ.

BOB_API_KEY is required at runtime.  When the environment variable
JAAL_TESTING=1 is set (as pytest fixtures do) the missing-key check is
skipped so tests can run without a real key.
"""
from __future__ import annotations

import os
from typing import List

# ---------------------------------------------------------------------------
# Try to use pydantic-settings; fall back to a plain class
# ---------------------------------------------------------------------------
try:
    from pydantic_settings import BaseSettings  # pydantic v2 extras
    _USE_PYDANTIC_SETTINGS = True
except ImportError:  # pragma: no cover
    _USE_PYDANTIC_SETTINGS = False

from dotenv import load_dotenv

load_dotenv()  # no-op if .env does not exist


def _csv_list(raw: str) -> List[str]:
    """Split a comma-separated string into a list, stripping whitespace."""
    return [item.strip() for item in raw.split(",") if item.strip()]


if _USE_PYDANTIC_SETTINGS:
    from pydantic import field_validator

    class Settings(BaseSettings):
        BOB_API_KEY: str = ""
        BOB_API_URL: str = "https://api.bob.example.com/v1/chat/completions"
        MODEL_NAME: str = "bob-large"
        TEMPERATURE: float = 0.1
        MAX_RETRIES: int = 2
        MAX_CHUNK_TOKENS: int = 3000
        FORCE_FALLBACK: bool = False
        BOB_LOG_PATH: str = "logs/bob_calls.jsonl"
        # Stored as a comma-separated string in .env; exposed as a list
        CORS_ORIGINS: List[str] = ["http://localhost:5173"]

        model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

        @field_validator("BOB_API_KEY")
        @classmethod
        def _require_api_key(cls, v: str) -> str:
            testing = os.getenv("JAAL_TESTING", "0") == "1"
            if not v and not testing:
                raise ValueError(
                    "BOB_API_KEY is not set. "
                    "Add it to your .env file (see .env.example)."
                )
            return v

    settings = Settings()

else:  # pragma: no cover — fallback when pydantic-settings is absent
    class _SimpleSettings:  # type: ignore[no-redef]
        BOB_API_KEY: str = os.getenv("BOB_API_KEY", "")
        BOB_API_URL: str = os.getenv(
            "BOB_API_URL", "https://api.bob.example.com/v1/chat/completions"
        )
        MODEL_NAME: str = os.getenv("MODEL_NAME", "bob-large")
        TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.1"))
        MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))
        MAX_CHUNK_TOKENS: int = int(os.getenv("MAX_CHUNK_TOKENS", "3000"))
        BOB_LOG_PATH: str = os.getenv("BOB_LOG_PATH", "logs/bob_calls.jsonl")
        CORS_ORIGINS: List[str] = _csv_list(
            os.getenv("CORS_ORIGINS", "http://localhost:5173")
        )

        def __post_init__(self) -> None:
            testing = os.getenv("JAAL_TESTING", "0") == "1"
            if not self.BOB_API_KEY and not testing:
                raise RuntimeError(
                    "BOB_API_KEY is not set. "
                    "Add it to your .env file (see .env.example)."
                )

    settings = _SimpleSettings()
