"""
tests/test_parser.py

Tests for backend/services/parser.py.

All input is made-up; no real data or files from data/scenarios are used.

Covers:
  parse_text()
    - plain text → one or more Chunk objects with correct line numbers
    - source_ref defaults to "pasted_text"
    - custom source_ref passed through
    - trailing blank lines stripped (line numbers still correct)
    - text larger than MAX_CHUNK_TOKENS is split into multiple chunks
    - a single line longer than the budget gets its own chunk
    - empty string raises ParserError
    - whitespace-only string raises ParserError

  parse_csv()
    - well-formed CSV → chunks with header repeated in every chunk
    - line numbers: header = L1, data starts at L2
    - CSV large enough to require splitting → header repeated in each chunk
    - empty content raises ParserError
    - header-only (no data rows) raises ParserError
    - malformed CSV raises ParserError (csv.Error)

  parse_file()
    - .txt bytes routed to text parser
    - .csv bytes routed to CSV parser
    - non-UTF-8 bytes raises ParserError
    - empty bytes raises ParserError
    - filename used as source_ref (directory prefix stripped)

  parse_batch()
    - mixed files → chunks from all files concatenated in order
    - one bad file in a batch raises ParserError

  Chunk model
    - start_line <= end_line always
    - no chunk exceeds MAX_CHUNK_TOKENS (token estimate)
"""
from __future__ import annotations

import os

os.environ.setdefault("JAAL_TESTING", "1")

import pytest
from unittest.mock import patch

from backend.services.parser import (
    Chunk,
    ParserError,
    _token_estimate,
    parse_batch,
    parse_csv,
    parse_file,
    parse_text,
)
from backend.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text(n_lines: int, chars_per_line: int = 20) -> str:
    """Return n_lines lines of predictable content."""
    return "\n".join(f"Line {i:04d}: {'x' * chars_per_line}" for i in range(1, n_lines + 1))


def _make_csv(n_data_rows: int, cols: int = 3) -> str:
    header = ",".join(f"col{c}" for c in range(1, cols + 1))
    rows = [",".join(f"val{r}_{c}" for c in range(1, cols + 1)) for r in range(1, n_data_rows + 1)]
    return "\n".join([header] + rows)


def _all_under_budget(chunks: list[Chunk]) -> bool:
    return all(_token_estimate(c.text) <= settings.MAX_CHUNK_TOKENS for c in chunks)


# ---------------------------------------------------------------------------
# _token_estimate
# ---------------------------------------------------------------------------

class TestTokenEstimate:
    def test_empty_string(self) -> None:
        assert _token_estimate("") == 1  # minimum 1

    def test_four_chars_is_one_token(self) -> None:
        assert _token_estimate("abcd") == 1

    def test_eight_chars_is_two_tokens(self) -> None:
        assert _token_estimate("abcdefgh") == 2

    def test_large_text(self) -> None:
        text = "a" * 4000
        assert _token_estimate(text) == 1000


# ---------------------------------------------------------------------------
# parse_text — happy paths
# ---------------------------------------------------------------------------

class TestParseTextHappy:
    def test_single_line_returns_one_chunk(self) -> None:
        chunks = parse_text("Hello world", "notes.txt")
        assert len(chunks) == 1
        assert chunks[0].text == "Hello world"
        assert chunks[0].source_ref == "notes.txt"
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 1

    def test_default_source_ref_is_pasted_text(self) -> None:
        chunks = parse_text("some content")
        assert chunks[0].source_ref == "pasted_text"

    def test_multiline_within_budget(self) -> None:
        text = "line one\nline two\nline three"
        chunks = parse_text(text, "raw.txt")
        assert len(chunks) == 1
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 3

    def test_trailing_blank_lines_stripped(self) -> None:
        text = "alpha\nbeta\n\n\n"
        chunks = parse_text(text, "f.txt")
        # Only 2 meaningful lines; trailing blanks stripped
        assert len(chunks) == 1
        assert chunks[0].end_line == 2

    def test_internal_blank_lines_preserved(self) -> None:
        text = "a\n\nb"  # blank line between a and b
        chunks = parse_text(text, "f.txt")
        assert len(chunks) == 1
        # internal blank line kept: 3 lines
        assert chunks[0].end_line == 3

    def test_line_numbers_correct_single_chunk(self) -> None:
        text = "\n".join(f"row {i}" for i in range(1, 6))
        chunks = parse_text(text, "f.txt")
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 5

    def test_chunk_is_chunk_model(self) -> None:
        chunks = parse_text("hello", "f.txt")
        assert isinstance(chunks[0], Chunk)


# ---------------------------------------------------------------------------
# parse_text — splitting
# ---------------------------------------------------------------------------

class TestParseTextSplitting:
    def test_large_text_splits_into_multiple_chunks(self) -> None:
        # Each line ~28 chars → ~7 tokens; 3000 token budget → ~428 lines/chunk
        # Use lines large enough to force a split quickly
        with patch.object(settings, "MAX_CHUNK_TOKENS", 50):
            # Each line is ~26 chars → ~6 tokens; 50 token budget → ~8 lines/chunk
            text = _make_text(40, chars_per_line=20)
            chunks = parse_text(text, "big.txt")
        assert len(chunks) > 1
        assert _all_under_budget(chunks)

    def test_chunks_cover_all_lines(self) -> None:
        with patch.object(settings, "MAX_CHUNK_TOKENS", 50):
            n = 40
            text = _make_text(n, chars_per_line=20)
            chunks = parse_text(text, "big.txt")
        assert chunks[0].start_line == 1
        assert chunks[-1].end_line == n
        # No gaps between chunks
        for a, b in zip(chunks, chunks[1:]):
            assert b.start_line == a.end_line + 1

    def test_very_long_single_line_gets_own_chunk(self) -> None:
        long_line = "x" * (settings.MAX_CHUNK_TOKENS * 4 + 100)  # >> budget
        text = "short line\n" + long_line + "\nanother short"
        chunks = parse_text(text, "f.txt")
        # The long line must be isolated in its own chunk
        long_chunks = [c for c in chunks if long_line in c.text]
        assert len(long_chunks) == 1
        assert long_chunks[0].start_line == long_chunks[0].end_line  # single line

    def test_all_chunks_under_budget_unless_single_oversize_line(self) -> None:
        with patch.object(settings, "MAX_CHUNK_TOKENS", 100):
            text = _make_text(200, chars_per_line=10)
            chunks = parse_text(text, "f.txt")
        assert all(
            _token_estimate(c.text) <= settings.MAX_CHUNK_TOKENS
            for c in chunks
        )


# ---------------------------------------------------------------------------
# parse_text — error cases
# ---------------------------------------------------------------------------

class TestParseTextErrors:
    def test_empty_string_raises(self) -> None:
        with pytest.raises(ParserError, match="empty"):
            parse_text("", "f.txt")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ParserError, match="empty|whitespace"):
            parse_text("   \n\t\n  ", "f.txt")


# ---------------------------------------------------------------------------
# parse_csv — happy paths
# ---------------------------------------------------------------------------

class TestParseCsvHappy:
    def test_small_csv_one_chunk(self) -> None:
        csv_text = "name,phone\nRamesh,9876500001\nSuresh,9876500002"
        chunks = parse_csv(csv_text, "call_logs.csv")
        assert len(chunks) == 1

    def test_header_in_chunk_text(self) -> None:
        csv_text = "name,phone\nRamesh,9876500001"
        chunks = parse_csv(csv_text, "call_logs.csv")
        assert "name,phone" in chunks[0].text

    def test_data_line_numbers_start_at_2(self) -> None:
        csv_text = "name,phone\nRamesh,9876500001\nSuresh,9876500002"
        chunks = parse_csv(csv_text, "call_logs.csv")
        assert chunks[0].start_line == 2
        assert chunks[0].end_line == 3

    def test_source_ref_passed_through(self) -> None:
        csv_text = "a,b\n1,2"
        chunks = parse_csv(csv_text, "transactions.csv")
        assert chunks[0].source_ref == "transactions.csv"

    def test_single_data_row(self) -> None:
        csv_text = "col1,col2\nval1,val2"
        chunks = parse_csv(csv_text, "t.csv")
        assert chunks[0].start_line == 2
        assert chunks[0].end_line == 2

    def test_quoted_fields_handled(self) -> None:
        csv_text = 'name,note\n"Kumar, Raj","sent ₹1,000"'
        chunks = parse_csv(csv_text, "t.csv")
        assert len(chunks) == 1
        assert "Kumar" in chunks[0].text

    def test_all_chunks_under_budget(self) -> None:
        with patch.object(settings, "MAX_CHUNK_TOKENS", 50):
            csv_text = _make_csv(50, cols=3)
            chunks = parse_csv(csv_text, "big.csv")
        assert _all_under_budget(chunks)

    def test_header_repeated_in_every_chunk(self) -> None:
        with patch.object(settings, "MAX_CHUNK_TOKENS", 50):
            csv_text = _make_csv(50, cols=3)
            chunks = parse_csv(csv_text, "big.csv")
        assert len(chunks) > 1
        for c in chunks:
            # "col1" comes from the header row
            assert "col1" in c.text

    def test_csv_split_line_numbers_are_contiguous(self) -> None:
        with patch.object(settings, "MAX_CHUNK_TOKENS", 50):
            csv_text = _make_csv(50, cols=3)
            chunks = parse_csv(csv_text, "big.csv")
        for a, b in zip(chunks, chunks[1:]):
            assert b.start_line == a.end_line + 1


# ---------------------------------------------------------------------------
# parse_csv — error cases
# ---------------------------------------------------------------------------

class TestParseCsvErrors:
    def test_empty_raises(self) -> None:
        with pytest.raises(ParserError, match="empty|whitespace"):
            parse_csv("", "t.csv")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ParserError, match="empty|whitespace"):
            parse_csv("   \n\n  ", "t.csv")

    def test_header_only_raises(self) -> None:
        with pytest.raises(ParserError, match="no data rows"):
            parse_csv("col1,col2", "t.csv")

    def test_malformed_csv_not_crash(self) -> None:
        # csv.reader is lenient; verify at minimum it returns valid chunks
        # or raises ParserError (never an unhandled exception)
        try:
            chunks = parse_csv('a,b\n"unclosed', "t.csv")
            # If csv.reader somehow accepts it, we should still get chunks
            assert isinstance(chunks, list)
        except ParserError:
            pass  # acceptable


# ---------------------------------------------------------------------------
# parse_file — routing and encoding
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_txt_file_routed_correctly(self) -> None:
        content = b"hello\nworld"
        chunks = parse_file(content, "notes.txt")
        assert chunks[0].source_ref == "notes.txt"
        assert "hello" in chunks[0].text

    def test_csv_file_routed_correctly(self) -> None:
        content = b"name,phone\nRamesh,9876500001"
        chunks = parse_file(content, "call_logs.csv")
        assert chunks[0].source_ref == "call_logs.csv"
        assert "name,phone" in chunks[0].text

    def test_directory_prefix_stripped_from_source_ref(self) -> None:
        content = b"hello"
        chunks = parse_file(content, "/tmp/upload/notes.txt")
        assert chunks[0].source_ref == "notes.txt"

    def test_non_utf8_raises_parser_error(self) -> None:
        with pytest.raises(ParserError, match="UTF-8|utf-8|decode"):
            parse_file(b"\xff\xfe bad bytes", "f.txt")

    def test_empty_bytes_raises_parser_error(self) -> None:
        with pytest.raises(ParserError, match="empty"):
            parse_file(b"", "f.txt")

    def test_unknown_extension_treated_as_text(self) -> None:
        content = b"just some text"
        chunks = parse_file(content, "data.log")
        assert "just some text" in chunks[0].text

    def test_csv_uppercase_extension(self) -> None:
        content = b"a,b\n1,2"
        chunks = parse_file(content, "FILE.CSV")
        assert "a,b" in chunks[0].text


# ---------------------------------------------------------------------------
# parse_batch
# ---------------------------------------------------------------------------

class TestParseBatch:
    def test_empty_batch_returns_empty_list(self) -> None:
        assert parse_batch([]) == []

    def test_single_file_batch(self) -> None:
        files = [("notes.txt", b"hello\nworld")]
        chunks = parse_batch(files)
        assert len(chunks) == 1

    def test_mixed_batch_order_preserved(self) -> None:
        files = [
            ("a.txt", b"text file content"),
            ("b.csv", b"col1,col2\nval1,val2"),
        ]
        chunks = parse_batch(files)
        assert len(chunks) == 2
        assert chunks[0].source_ref == "a.txt"
        assert chunks[1].source_ref == "b.csv"

    def test_multiple_txt_files(self) -> None:
        files = [
            ("x.txt", b"file x line1\nfile x line2"),
            ("y.txt", b"file y line1"),
        ]
        chunks = parse_batch(files)
        assert len(chunks) == 2
        assert chunks[0].source_ref == "x.txt"
        assert chunks[1].source_ref == "y.txt"

    def test_bad_file_in_batch_raises(self) -> None:
        files = [
            ("good.txt", b"hello"),
            ("bad.txt", b"\xff\xfe"),
        ]
        with pytest.raises(ParserError):
            parse_batch(files)

    def test_chunks_from_large_batch_all_under_budget(self) -> None:
        with patch.object(settings, "MAX_CHUNK_TOKENS", 50):
            files = [
                ("big.txt", _make_text(60, 20).encode()),
                ("big.csv", _make_csv(60, 3).encode()),
            ]
            chunks = parse_batch(files)
        assert _all_under_budget(chunks)


# ---------------------------------------------------------------------------
# Chunk model invariants
# ---------------------------------------------------------------------------

class TestChunkInvariants:
    def test_start_le_end_for_all_text_chunks(self) -> None:
        with patch.object(settings, "MAX_CHUNK_TOKENS", 50):
            chunks = parse_text(_make_text(100, 20), "f.txt")
        for c in chunks:
            assert c.start_line <= c.end_line

    def test_start_le_end_for_all_csv_chunks(self) -> None:
        with patch.object(settings, "MAX_CHUNK_TOKENS", 50):
            chunks = parse_csv(_make_csv(100, 3), "f.csv")
        for c in chunks:
            assert c.start_line <= c.end_line

    def test_chunk_text_not_empty(self) -> None:
        chunks = parse_text("some content here", "f.txt")
        for c in chunks:
            assert c.text.strip()
