"""
backend/api/routes_cases.py

Case management routes:
  POST /api/cases                    — create a case from pasted text + uploaded files.
  POST /api/cases/{id}/analyze       — run the extraction pipeline on the stored inputs.
  GET  /api/cases/{id}/graph         — return the resolved GraphPayload.
  GET  /api/demo/{scenario}          — load a mock scenario from data/scenarios/<name>/.
  GET  /api/demo/{scenario}/analysis — return AnalysisResult for a scenario.

In-memory store (dict) is sufficient for the hackathon.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from backend.schemas.entities import ResolvedGraph
from backend.schemas.graph import GraphPayload
from backend.services.parser import ParserError
from backend.services.pipeline import PipelineInput, PipelineResult, run_extraction_pipeline

router = APIRouter(prefix="/api", tags=["cases"])

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
# { case_id: { "inputs": list[PipelineInput], "result": PipelineResult | None,
#              "status": "pending" | "done" | "error", "error_msg": str } }
_CASES: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# POST /api/cases
# ---------------------------------------------------------------------------

@router.post("/cases", status_code=201)
async def create_case(
    text: Annotated[Optional[str], Form()] = None,
    files: Annotated[list[UploadFile], File()] = [],
) -> dict:
    """
    Create a new case from pasted text and/or uploaded files.

    At least one of `text` or `files` must be provided.
    Returns the new case_id.
    """
    if not text and not files:
        raise HTTPException(status_code=422, detail="Provide at least one of: text, files.")

    inputs: list[PipelineInput] = []

    if text and text.strip():
        inputs.append(PipelineInput(text=text))

    for upload in files:
        content = await upload.read()
        if not content:
            raise HTTPException(
                status_code=422,
                detail=f"Uploaded file '{upload.filename}' is empty.",
            )
        inputs.append(PipelineInput(filename=upload.filename, content=content))

    case_id = str(uuid.uuid4())
    _CASES[case_id] = {"inputs": inputs, "result": None, "status": "pending", "error_msg": ""}
    return {"case_id": case_id, "status": "pending"}


# ---------------------------------------------------------------------------
# POST /api/cases/{id}/analyze
# ---------------------------------------------------------------------------

@router.post("/cases/{case_id}/analyze")
def analyze_case(
    case_id: str,
    resolved_graph: Optional[ResolvedGraph] = Body(default=None),
) -> dict:
    """
    Run the extraction pipeline on the stored inputs for this case.

    If a ResolvedGraph body is provided, run the analysis pipeline directly
    on it (used by contract tests and the frontend).  Otherwise, run on
    the stored pipeline inputs.
    """
    from backend.analysis.pipeline import run_pipeline as _run_analysis
    from backend.schemas.result import AnalysisResult

    # ------------------------------------------------------------------
    # Fast path: ResolvedGraph body provided directly
    # ------------------------------------------------------------------
    if resolved_graph is not None:
        analysis_result: AnalysisResult = _run_analysis(resolved_graph)
        # Store in case store (create entry if missing)
        if case_id not in _CASES:
            _CASES[case_id] = {"inputs": [], "result": None, "status": "pending", "error_msg": ""}
        _CASES[case_id]["analysis"] = analysis_result
        _CASES[case_id]["status"] = "done"
        return analysis_result.model_dump()

    # ------------------------------------------------------------------
    # Normal path: run full extraction + analysis on stored inputs
    # ------------------------------------------------------------------
    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")

    try:
        result: PipelineResult = run_extraction_pipeline(case["inputs"], case_id=case_id)
        case["result"] = result
        case["analysis"] = result.analysis
        case["status"] = "done"
        return {
            "case_id": case_id,
            "status": "done",
            "used_fallback": result.used_fallback,
            "stats": result.stats.model_dump(),
        }
    except ParserError as exc:
        case["status"] = "error"
        case["error_msg"] = str(exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        case["status"] = "error"
        case["error_msg"] = str(exc)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc


# ---------------------------------------------------------------------------
# GET /api/cases/{id}/graph
# ---------------------------------------------------------------------------

@router.get("/cases/{case_id}/graph", response_model=GraphPayload)
def get_graph(case_id: str) -> GraphPayload:
    """Return the resolved GraphPayload for this case."""
    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    if case["status"] != "done" or case["result"] is None:
        raise HTTPException(
            status_code=409,
            detail=f"Case '{case_id}' has not been analyzed yet (status: {case['status']}).",
        )
    return case["result"].graph


# ---------------------------------------------------------------------------
# GET /api/demo/{scenario}
# ---------------------------------------------------------------------------

_SCENARIOS_DIR = Path(__file__).parent.parent.parent / "data" / "scenarios"
_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_SAMPLE_ANALYSIS = _DATA_DIR / "sample_analysis.json"


def _load_sample_analysis():
    """Load and return the offline sample_analysis.json as a dict."""
    from backend.schemas.result import AnalysisResult
    raw = _SAMPLE_ANALYSIS.read_text(encoding="utf-8")
    return AnalysisResult.model_validate_json(raw).model_dump()


@router.get("/demo/{scenario}/analysis")
def demo_scenario_analysis(scenario: str) -> dict:
    """
    Return AnalysisResult for a named demo scenario.

    Falls back to data/sample_analysis.json for the 'sample' scenario or
    when the named scenario is not found.
    """
    from backend.schemas.result import AnalysisResult

    # For the special 'sample' scenario, always use the static file
    if scenario == "sample":
        return _load_sample_analysis()

    scenario_dir = _SCENARIOS_DIR / scenario
    if not scenario_dir.exists():
        # Graceful fallback for unknown scenarios
        return _load_sample_analysis()

    # Run the pipeline and return the analysis
    known_files = ["raw_notes.txt", "call_logs.csv", "transactions.csv"]
    inputs: list[PipelineInput] = []
    for fname in known_files:
        fpath = scenario_dir / fname
        if fpath.exists():
            inputs.append(PipelineInput(filename=fname, content=fpath.read_bytes()))

    if not inputs:
        return _load_sample_analysis()

    case_id = scenario
    try:
        result = run_extraction_pipeline(inputs, case_id=case_id)
        _CASES[case_id] = {
            "inputs": inputs,
            "result": result,
            "analysis": result.analysis,
            "status": "done",
            "error_msg": "",
        }
        if result.analysis:
            return result.analysis.model_dump()
        return _load_sample_analysis()
    except Exception:
        return _load_sample_analysis()


@router.get("/demo/{scenario}")
def demo_scenario(scenario: str) -> dict:
    """
    Load a mock scenario from data/scenarios/<scenario>/ and run the pipeline.

    Looks for: raw_notes.txt, call_logs.csv, transactions.csv (any that exist).
    Falls back to sample_analysis.json for unknown scenarios (offline demo).
    """
    scenario_dir = _SCENARIOS_DIR / scenario
    if not scenario_dir.exists():
        # Fallback to sample — required for offline demo to always work
        sample = _load_sample_analysis()
        return sample

    known_files = ["raw_notes.txt", "call_logs.csv", "transactions.csv"]
    inputs: list[PipelineInput] = []
    for fname in known_files:
        fpath = scenario_dir / fname
        if fpath.exists():
            inputs.append(PipelineInput(filename=fname, content=fpath.read_bytes()))

    if not inputs:
        return _load_sample_analysis()

    case_id = str(uuid.uuid4())
    _CASES[case_id] = {"inputs": inputs, "result": None, "status": "pending", "error_msg": ""}

    try:
        result = run_extraction_pipeline(inputs, case_id=case_id)
        _CASES[case_id]["result"] = result
        _CASES[case_id]["analysis"] = result.analysis
        _CASES[case_id]["status"] = "done"
    except ParserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "case_id": case_id,
        "status": "done",
        "used_fallback": result.used_fallback,
        "stats": result.stats.model_dump(),
        "graph": result.graph.model_dump(),
    }
