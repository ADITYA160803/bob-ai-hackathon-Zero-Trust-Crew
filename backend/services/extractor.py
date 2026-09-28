"""
backend/services/extractor.py

Drives entity and relationship extraction from a list of Chunks.

Public API
──────────
extract(chunks: list[Chunk]) -> ExtractionResult

Flow per chunk
──────────────
1. Call bob_client.call_json("extract.md", chunk.text, chunk.source_ref).
2. Parse the response into RawNode / RawEdge objects.
3. Grounding check: drop any item whose value does not appear in the chunk
   text (after light normalization — strip spaces, dashes, +91 prefix).
4. On BobUnavailableError or any parse / validation failure, fall back to
   regex extraction for that chunk and set used_fallback = True.

Regex fallback rules (per rules.md)
------------------------------------
- Phone:  (\\+91)?[6-9]\\d{9}       must be exactly 10 digits after +91 strip
- IMEI:   \\b\\d{15}\\b             15-digit number; takes priority over phone
- UPI:    \\w+@\\w+                 exclude if domain part contains a dot
                                     (that would be an email address)

FORCE_FALLBACK config switch (default False) bypasses Bob entirely;
useful for offline demos and CI without a real API key.

Grounding normalisation helper (also exported for tests)
─────────────────────────────────────────────────────────
_normalise(value) strips spaces, dashes, and leading +91 and lowercases.
A node/edge value is "grounded" if its normalised form appears anywhere in
the normalised chunk text.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from backend.config import settings
from backend.schemas.entities import EdgeType, NodeType, RawEdge, RawNode
from backend.schemas.graph import ExtractionResult
from backend.services.bob_client import BobUnavailableError, call_json
from backend.services.parser import Chunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns (compiled once)
# ---------------------------------------------------------------------------

# IMEI: exactly 15 digits, word-boundary anchored
_RE_IMEI = re.compile(r"\b(\d{15})\b")

# Phone: optional +91, then 10 digits starting [6-9]
# Must NOT be preceded by more digits (would be part of an IMEI or longer number)
_RE_PHONE = re.compile(r"(?<!\d)(\+91)?([6-9]\d{9})(?!\d)")

# UPI: word@word  — domain part must NOT contain a dot (else it's an email)
_RE_UPI = re.compile(r"\b([\w.]+@\w+)\b")


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------

def _normalise(value: str) -> str:
    """Strip spaces, dashes, leading +91; lowercase. Used for grounding checks."""
    v = value.lower().strip()
    v = re.sub(r"[\s\-]", "", v)
    if v.startswith("+91"):
        v = v[3:]
    return v


# ---------------------------------------------------------------------------
# Grounding check
# ---------------------------------------------------------------------------

def _is_grounded(value: str, chunk_text: str) -> bool:
    """Return True if normalised value appears anywhere in normalised chunk text."""
    return _normalise(value) in _normalise(chunk_text)


# ---------------------------------------------------------------------------
# LLM response → RawNode / RawEdge
# ---------------------------------------------------------------------------

def _chunk_evidence(chunk: Chunk) -> str:
    """
    Build the evidence string for the whole chunk.
    Format: "<source_ref>#L<start>" if single line, else "#L<start>-<end>".
    """
    if chunk.start_line == chunk.end_line:
        return f"{chunk.source_ref}#L{chunk.start_line}"
    return f"{chunk.source_ref}#L{chunk.start_line}-{chunk.end_line}"


def _line_evidence(chunk: Chunk, line_no: int) -> str:
    """
    Build an evidence string pinned to a single absolute line number.
    """
    return f"{chunk.source_ref}#L{line_no}"


def _parse_llm_response(
    data: dict[str, Any], chunk: Chunk
) -> tuple[list[RawNode], list[RawEdge]]:
    """
    Validate and ground-check the LLM dict against the chunk text.
    Returns only items that pass validation and grounding.
    Logs a warning for every dropped item.
    """
    nodes: list[RawNode] = []
    edges: list[RawEdge] = []
    # Build the chunk-level evidence ref (overrides whatever LLM returned)
    evidence = _chunk_evidence(chunk)

    for raw in data.get("nodes", []):
        try:
            n = RawNode.model_validate(raw)
        except Exception as exc:
            logger.warning("Dropping invalid node %s: %s", raw, exc)
            continue
        if not _is_grounded(n.value, chunk.text):
            logger.warning(
                "Dropping ungrounded node value=%r (not in chunk %s)",
                n.value, chunk.source_ref,
            )
            continue
        # Overwrite evidence with the correct chunk ref (LLM cannot invent filenames)
        n = n.model_copy(update={"evidence": evidence})
        nodes.append(n)

    for raw in data.get("edges", []):
        try:
            e = RawEdge.model_validate(raw)
        except Exception as exc:
            logger.warning("Dropping invalid edge %s: %s", raw, exc)
            continue
        if not _is_grounded(e.source_value, chunk.text) or not _is_grounded(
            e.target_value, chunk.text
        ):
            logger.warning(
                "Dropping ungrounded edge %s->%s (not in chunk %s)",
                e.source_value, e.target_value, chunk.source_ref,
            )
            continue
        e = e.model_copy(update={"evidence": evidence})
        edges.append(e)

    return nodes, edges


# ---------------------------------------------------------------------------
# Regex fallback
# ---------------------------------------------------------------------------

def _match_line_no(chunk: Chunk, match_start: int) -> int:
    """
    Return the 1-based absolute line number within the source file for the
    character offset ``match_start`` inside ``chunk.text``.
    """
    # Count newlines before the match position to get offset within chunk
    line_offset = chunk.text[:match_start].count("\n")
    return chunk.start_line + line_offset


def _regex_extract(chunk: Chunk) -> tuple[list[RawNode], list[RawEdge]]:
    """
    Extract phones, IMEIs and UPI IDs from chunk text using regexes only.
    Returns RawNode list; no semantic edges (regex cannot know relationships).
    Evidence is pinned to the exact line of each match (or the chunk range if
    the match spans multiple lines, which regexes here never do).
    """
    text = chunk.text
    nodes: list[RawNode] = []
    seen: set[str] = set()

    # Find IMEI first — a 15-digit string is IMEI, never a phone
    imei_spans: set[tuple[int, int]] = set()
    for m in _RE_IMEI.finditer(text):
        imei_val = m.group(1)
        if imei_val not in seen:
            seen.add(imei_val)
            imei_spans.add((m.start(), m.end()))
            line_no = _match_line_no(chunk, m.start())
            nodes.append(
                RawNode(
                    type=NodeType.DEVICE,
                    value=imei_val,
                    attrs={"imei": imei_val},
                    evidence=_line_evidence(chunk, line_no),
                )
            )

    # Phones — skip any match whose span overlaps an IMEI span
    for m in _RE_PHONE.finditer(text):
        digits = m.group(2)  # the 10-digit portion
        span = (m.start(), m.end())
        # Check overlap with any IMEI span
        overlaps = any(
            not (span[1] <= is_[0] or span[0] >= is_[1])
            for is_ in imei_spans
        )
        if overlaps:
            continue
        if digits not in seen:
            seen.add(digits)
            line_no = _match_line_no(chunk, m.start())
            nodes.append(
                RawNode(
                    type=NodeType.PHONE,
                    value=m.group(0),  # as written, e.g. "+919876500001"
                    attrs={},
                    evidence=_line_evidence(chunk, line_no),
                )
            )

    # UPI — exclude if domain part contains a dot (email address)
    for m in _RE_UPI.finditer(text):
        full = m.group(1)
        parts = full.split("@", 1)
        if len(parts) != 2:
            continue
        domain = parts[1]
        if "." in domain:
            continue  # email address, not UPI
        if full not in seen:
            seen.add(full)
            line_no = _match_line_no(chunk, m.start())
            nodes.append(
                RawNode(
                    type=NodeType.UPI_ID,
                    value=full,
                    attrs={},
                    evidence=_line_evidence(chunk, line_no),
                )
            )

    return nodes, []


# ---------------------------------------------------------------------------
# Per-chunk extraction
# ---------------------------------------------------------------------------

def _extract_chunk(chunk: Chunk, force_fallback: bool) -> tuple[list[RawNode], list[RawEdge], bool]:
    """
    Extract from one chunk. Returns (nodes, edges, used_fallback_for_this_chunk).

    Tries structured CSV extraction first for known CSV schemas.  Falls back to
    Bob LLM (or regex if force_fallback / Bob unavailable).
    """
    from backend.services.structured_extractor import detect_and_extract

    # ── Structured CSV extraction (deterministic, no LLM) ────────────────────
    structured = detect_and_extract(chunk.text, chunk.source_ref)
    if structured is not None:
        nodes, edges = structured
        return nodes, edges, False  # deterministic — not a "fallback"

    # ── Regex fallback (bypasses Bob entirely) ────────────────────────────────
    if force_fallback:
        nodes, edges = _regex_extract(chunk)
        return nodes, edges, True

    # ── Bob LLM path ──────────────────────────────────────────────────────────
    try:
        data = call_json("extract.md", chunk.text, chunk.source_ref)
        nodes, edges = _parse_llm_response(data, chunk)
        return nodes, edges, False
    except BobUnavailableError as exc:
        logger.warning(
            "Bob unavailable for chunk %s, falling back to regex: %s",
            chunk.source_ref, exc,
        )
    except Exception as exc:
        logger.warning(
            "Unexpected error extracting chunk %s, falling back: %s",
            chunk.source_ref, exc,
        )

    nodes, edges = _regex_extract(chunk)
    return nodes, edges, True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract(chunks: list[Chunk]) -> ExtractionResult:
    """
    Extract entities and relationships from a list of parsed chunks.

    Parameters
    ----------
    chunks : list[Chunk]
        Output of parser.parse_text / parse_file / parse_batch.

    Returns
    -------
    ExtractionResult
        Merged RawNode / RawEdge lists across all chunks, plus used_fallback.
    """
    force_fallback: bool = getattr(settings, "FORCE_FALLBACK", False)

    all_nodes: list[RawNode] = []
    all_edges: list[RawEdge] = []
    any_fallback = False

    for chunk in chunks:
        nodes, edges, did_fallback = _extract_chunk(chunk, force_fallback)
        all_nodes.extend(nodes)
        all_edges.extend(edges)
        if did_fallback:
            any_fallback = True

    return ExtractionResult(
        nodes=all_nodes,
        edges=all_edges,
        used_fallback=any_fallback,
    )
