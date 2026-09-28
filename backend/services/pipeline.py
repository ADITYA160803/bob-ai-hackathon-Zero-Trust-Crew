"""
backend/services/pipeline.py

Thin integration layer that chains the three extraction services:
  parser → extractor → resolver

Public API
──────────
run_extraction_pipeline(inputs) -> PipelineResult

inputs is a list of PipelineInput items — each is either:
  • pasted text (text=str, filename=None)
  • a file upload (filename=str, content=bytes)

Returns PipelineResult with:
  • graph       : GraphPayload (nodes + edges, fully resolved)
  • used_fallback: bool
  • stats       : {chunks, nodes, edges}

Hook points for future modules are marked as TODO comments so Aditya
and Aksh can slot in without touching this file's logic.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.schemas.graph import GraphPayload
from backend.services.extractor import extract
from backend.services.parser import Chunk, parse_batch, parse_text
from backend.services.resolver import resolve




# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------

class PipelineInput(BaseModel):
    """One piece of input: either pasted text or an uploaded file."""

    text: Optional[str] = Field(
        default=None,
        description="Pasted text. Supply text OR (filename + content), not both.",
    )
    filename: Optional[str] = Field(
        default=None,
        description="Original filename, e.g. 'call_logs.csv'.",
    )
    content: Optional[bytes] = Field(
        default=None,
        description="Raw file bytes. Required when filename is set.",
    )


class PipelineStats(BaseModel):
    chunks: int
    nodes: int
    edges: int


class PipelineResult(BaseModel):
    graph: GraphPayload
    used_fallback: bool
    stats: PipelineStats
    analysis: Optional["AnalysisResult"] = None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_extraction_pipeline(
    inputs: list[PipelineInput],
    case_id: str = "default",
) -> PipelineResult:
    """
    Run the full extraction pipeline on a list of inputs.

    Steps
    ─────
    1. Parse   — convert inputs to Chunk objects.
    2. Extract — call Bob (or regex fallback) per chunk → ExtractionResult.
    3. Resolve — deduplicate, assign stable IDs → GraphPayload.
    4. Analyse — run graph analytics pipeline → AnalysisResult.
    """
    # ------------------------------------------------------------------
    # Step 1: Parse all inputs into chunks
    # ------------------------------------------------------------------
    chunks: list[Chunk] = []

    file_inputs = [
        (inp.filename, inp.content)
        for inp in inputs
        if inp.filename is not None and inp.content is not None
    ]
    if file_inputs:
        chunks.extend(parse_batch(file_inputs))  # type: ignore[arg-type]

    for inp in inputs:
        if inp.text is not None:
            chunks.extend(parse_text(inp.text, source_ref="pasted_text"))

    # ------------------------------------------------------------------
    # Step 2: Extract entities from all chunks
    # ------------------------------------------------------------------
    extraction_result = extract(chunks)

    # ------------------------------------------------------------------
    # Step 3: Resolve raw nodes/edges into stable GraphPayload
    # ------------------------------------------------------------------
    graph = resolve(extraction_result)

    # Step 4: Run the full analysis pipeline
    from backend.analysis.pipeline import run_pipeline as _run_analysis
    from backend.schemas.result import AnalysisResult  # noqa: F401 (used in type hint)
    resolved = graph.to_resolved(case_id=case_id)
    analysis_result = _run_analysis(resolved)

    return PipelineResult(
        graph=graph,
        used_fallback=extraction_result.used_fallback,
        stats=PipelineStats(
            chunks=len(chunks),
            nodes=len(graph.nodes),
            edges=len(graph.edges),
        ),
        analysis=analysis_result,
    )
