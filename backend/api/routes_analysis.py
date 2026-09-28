"""
backend/api/routes_analysis.py

Analysis routes:
  GET /api/cases/{id}/analysis  — pattern, roles, scores, timeline.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/cases/{case_id}/analysis")
def get_analysis(case_id: str) -> dict:
    """
    Return pattern classification, role scores and timeline for a case.

    Returns the AnalysisResult stored when the case was analysed.
    """
    from backend.api.routes_cases import _CASES  # noqa: PLC0415

    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    if case["status"] != "done":
        raise HTTPException(
            status_code=409,
            detail=f"Case '{case_id}' has not been analyzed yet.",
        )
    analysis = case.get("analysis")
    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analysis result available for case '{case_id}'.",
        )
    if hasattr(analysis, "model_dump"):
        return analysis.model_dump()
    return analysis
