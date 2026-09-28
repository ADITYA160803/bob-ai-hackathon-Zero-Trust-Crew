"""
backend/services/parser.py

Converts raw input (pasted text, .txt file, .csv file, or a batch of mixed
files) into a list of Chunk models suitable for the extractor.

Public API
──────────
parse_text(text, source_ref)           -> list[Chunk]
parse_file(path_or_bytes, filename)    -> list[Chunk]
parse_batch(files)                     -> list[Chunk]
    files: list of (filename, bytes) tuples

Each Chunk carries:
  text        — the chunk content
  source_ref  — filename (e.g. "call_logs.csv") or "pasted_text"
  start_line  — 1-based line number of the first line in this chunk
  end_line    — 1-based line number of the last line in this chunk

Token estimate: len(text) / 4  (no external tokenizer).
Chunk size cap: settings.MAX_CHUNK_TOKENS (default 3 000).

Splitting rules
───────────────
Text / .txt
  Split on line boundaries.  Never cut a line in half.  If a single line
  exceeds the token budget it becomes its own chunk (unavoidable).

CSV
  Keep the header row in every chunk.  Line numbers are relative to the
  original file (header = L1).

Errors
──────
ParserError  — raised for empty input, whitespace-only input, non-UTF-8
               bytes, or a CSV with no data rows.  Always carries a human-
               readable message; never crashes with an unhandled exception.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import List, Sequence, Tuple

from pydantic import BaseModel, Field

from backend.config import settings


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Chunk(BaseModel):
    """A piece of source text ready to be sent to the extractor."""

    text: str = Field(..., description="Chunk content.")
    source_ref: str = Field(
        ...,
        description=(
            "File name or 'pasted_text'. Used to build evidence references "
            "like 'call_logs.csv#L14'."
        ),
    )
    start_line: int = Field(..., ge=1, description="1-based first line number.")
    end_line: int = Field(..., ge=1, description="1-based last line number.")


class ParserError(ValueError):
    """Raised when input cannot be parsed into chunks."""


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def _token_estimate(text: str) -> int:
    """Rough token count: len(text) / 4, minimum 1."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Core text splitter (shared by text and CSV paths)
# ---------------------------------------------------------------------------

def _split_lines_into_chunks(
    lines: list[str],
    source_ref: str,
    first_line_number: int = 1,
    header: str | None = None,
) -> list[Chunk]:
    """
    Pack ``lines`` into chunks that stay under MAX_CHUNK_TOKENS.

    Parameters
    ----------
    lines             : content lines (without the CSV header if any).
    source_ref        : passed through to each Chunk.
    first_line_number : 1-based line number of lines[0] in the source file.
    header            : if given, prepended to every chunk (CSV header row).
    """
    max_tokens = settings.MAX_CHUNK_TOKENS
    header_tokens = _token_estimate(header + "\n") if header else 0

    chunks: list[Chunk] = []
    current_lines: list[str] = []
    current_tokens: int = header_tokens
    # line number of the first line in the current accumulator
    chunk_start: int = first_line_number

    def _flush(end_line_number: int) -> None:
        nonlocal current_lines, current_tokens, chunk_start
        if not current_lines:
            return
        body = "\n".join(current_lines)
        text = (header + "\n" + body) if header else body
        chunks.append(
            Chunk(
                text=text,
                source_ref=source_ref,
                start_line=chunk_start,
                end_line=end_line_number,
            )
        )
        current_lines = []
        current_tokens = header_tokens

    for i, line in enumerate(lines):
        line_no = first_line_number + i
        line_tokens = _token_estimate(line + "\n")

        # A single line that alone exceeds the budget → its own chunk
        if line_tokens > max_tokens - header_tokens:
            _flush(line_no - 1)
            body = line
            text = (header + "\n" + body) if header else body
            chunks.append(
                Chunk(
                    text=text,
                    source_ref=source_ref,
                    start_line=line_no,
                    end_line=line_no,
                )
            )
            chunk_start = line_no + 1
            current_tokens = header_tokens
            continue

        # Would adding this line exceed the budget?
        if current_tokens + line_tokens > max_tokens and current_lines:
            _flush(line_no - 1)
            chunk_start = line_no

        current_lines.append(line)
        current_tokens += line_tokens

    _flush(first_line_number + len(lines) - 1)
    return chunks


# ---------------------------------------------------------------------------
# Text / .txt
# ---------------------------------------------------------------------------

def parse_text(text: str, source_ref: str = "pasted_text") -> list[Chunk]:
    """
    Parse plain text (pasted or from a .txt file) into chunks.

    Parameters
    ----------
    text       : raw string content.
    source_ref : evidence prefix; defaults to "pasted_text".

    Raises
    ------
    ParserError  if text is empty or whitespace-only.
    """
    if not text or not text.strip():
        raise ParserError(
            f"Input '{source_ref}' is empty or contains only whitespace."
        )

    lines = text.splitlines()
    # Remove trailing blank lines but keep internal blank lines (they preserve
    # structure and line numbers must remain accurate).
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        raise ParserError(
            f"Input '{source_ref}' is empty or contains only whitespace."
        )

    return _split_lines_into_chunks(lines, source_ref, first_line_number=1)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def parse_csv(content: str, source_ref: str) -> list[Chunk]:
    """
    Parse CSV text into chunks, repeating the header in every chunk.

    Line numbers in Chunk.start_line / end_line refer to the original file
    (header = L1, first data row = L2, …).

    Raises
    ------
    ParserError  if content is empty/whitespace, if CSV cannot be parsed,
                 or if there are no data rows after the header.
    """
    if not content or not content.strip():
        raise ParserError(f"CSV file '{source_ref}' is empty or whitespace-only.")

    try:
        reader = csv.reader(io.StringIO(content))
        all_rows: list[list[str]] = list(reader)
    except csv.Error as exc:
        raise ParserError(
            f"CSV file '{source_ref}' could not be parsed: {exc}"
        ) from exc

    if not all_rows:
        raise ParserError(f"CSV file '{source_ref}' has no rows.")

    header_row = all_rows[0]
    data_rows = all_rows[1:]

    if not data_rows:
        raise ParserError(
            f"CSV file '{source_ref}' has a header but no data rows."
        )

    # Re-serialise each row back to a CSV string so line content matches the
    # original file format (handles quoted fields, commas inside values, etc.)
    def _row_to_str(row: list[str]) -> str:
        buf = io.StringIO()
        csv.writer(buf).writerow(row)
        return buf.getvalue().rstrip("\r\n")

    header_str = _row_to_str(header_row)
    data_line_strs = [_row_to_str(r) for r in data_rows]

    # data rows start at line 2 in the original file (line 1 = header)
    return _split_lines_into_chunks(
        lines=data_line_strs,
        source_ref=source_ref,
        first_line_number=2,
        header=header_str,
    )


# ---------------------------------------------------------------------------
# Single file dispatcher
# ---------------------------------------------------------------------------

def parse_file(content: bytes, filename: str) -> list[Chunk]:
    """
    Decode bytes and route to the correct parser based on file extension.

    Parameters
    ----------
    content  : raw file bytes.
    filename : used as source_ref and to determine file type (.csv vs other).

    Raises
    ------
    ParserError  for encoding errors, empty files, or parse failures.
    """
    if not content:
        raise ParserError(f"File '{filename}' is empty.")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParserError(
            f"File '{filename}' is not valid UTF-8 and cannot be decoded: {exc}"
        ) from exc

    source_ref = Path(filename).name  # strip any directory prefix

    if source_ref.lower().endswith(".csv"):
        return parse_csv(text, source_ref)
    else:
        return parse_text(text, source_ref)


# ---------------------------------------------------------------------------
# Batch dispatcher
# ---------------------------------------------------------------------------

def parse_batch(files: Sequence[Tuple[str, bytes]]) -> list[Chunk]:
    """
    Parse a batch of (filename, bytes) pairs.

    Each file is parsed independently; all resulting chunks are concatenated
    and returned in the order the files were supplied.

    Raises
    ------
    ParserError  if any individual file fails to parse.
    """
    all_chunks: list[Chunk] = []
    for filename, content in files:
        all_chunks.extend(parse_file(content, filename))
    return all_chunks
