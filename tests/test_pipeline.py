"""
tests/test_pipeline.py

Focused integration tests for backend/services/pipeline.py.

Uses FORCE_FALLBACK so no Bob API key is needed. Validates the
parser → extractor → resolver chain end-to-end with mock data only.
"""
from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("JAAL_TESTING", "1")

import pytest

from backend.schemas.entities import NodeType
from backend.services.parser import ParserError
from backend.services.pipeline import PipelineInput, PipelineResult, run_extraction_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_with_fallback(inputs: list[PipelineInput]) -> PipelineResult:
    """Run pipeline with FORCE_FALLBACK=True (no Bob calls)."""
    with patch(
        "backend.services.extractor.settings"
    ) as mock_settings:
        mock_settings.FORCE_FALLBACK = True
        mock_settings.MAX_CHUNK_TOKENS = 3000
        return run_extraction_pipeline(inputs)


# ---------------------------------------------------------------------------
# 1. Pasted text — phones extracted via regex fallback
# ---------------------------------------------------------------------------

class TestPipelinePastedText:
    def test_phones_extracted_from_text(self) -> None:
        inp = PipelineInput(text="Suspect called 9876500001 from 8888800000.")
        result = _run_with_fallback([inp])
        assert result.used_fallback is True
        phone_ids = {n.id for n in result.graph.nodes if n.type == NodeType.PHONE}
        # At least one phone found
        assert phone_ids

    def test_stats_populated(self) -> None:
        inp = PipelineInput(text="Transfer from 9876500001 to UPI raj@okaxis.")
        result = _run_with_fallback([inp])
        assert result.stats.chunks >= 1
        assert result.stats.nodes >= 1


# ---------------------------------------------------------------------------
# 2. File input — CSV parsed and phone extracted
# ---------------------------------------------------------------------------

class TestPipelineFileInput:
    def test_csv_file_processed(self) -> None:
        csv_bytes = b"caller,receiver\n9876500001,8888800000"
        inp = PipelineInput(filename="calls.csv", content=csv_bytes)
        result = _run_with_fallback([inp])
        assert result.stats.chunks >= 1

    def test_empty_file_raises_parser_error(self) -> None:
        inp = PipelineInput(filename="empty.txt", content=b"")
        with pytest.raises(ParserError):
            run_extraction_pipeline([inp])


# ---------------------------------------------------------------------------
# 3. Mixed batch
# ---------------------------------------------------------------------------

class TestPipelineMixedBatch:
    def test_text_and_file_combined(self) -> None:
        text_inp = PipelineInput(text="IMEI 353456789012345 detected.")
        file_inp = PipelineInput(filename="calls.txt", content=b"9876500001 called 8888800000")
        result = _run_with_fallback([text_inp, file_inp])
        assert result.stats.chunks >= 2
        node_types = {n.type for n in result.graph.nodes}
        assert NodeType.DEVICE in node_types or NodeType.PHONE in node_types
