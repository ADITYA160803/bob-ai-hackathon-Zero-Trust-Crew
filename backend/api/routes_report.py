"""
backend/api/routes_report.py

Report generation routes:
  GET /api/cases/{id}/brief?format=md|pdf|html
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/cases/{case_id}/brief")
def get_brief(
    case_id: str,
    format: str = Query(default="md", description="Output format: md | pdf | html"),
) -> Response:
    """
    Generate and return a case brief in the requested format.

    Parameters
    ----------
    case_id : str
        The case ID (must exist and be analyzed).
    format : str
        Output format — 'md' (default), 'html', or 'pdf'.
    """
    from backend.api.routes_cases import _CASES
    from backend.reports.brief_builder import build_brief
    from backend.reports.pdf_export import to_html, to_pdf

    case = _CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    if case.get("status") != "done":
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

    graph = case.get("result", {})
    graph_payload = getattr(graph, "graph", None) if graph else None

    markdown_text = build_brief(analysis, graph_payload)

    fmt = format.lower()
    if fmt == "md":
        return PlainTextResponse(
            content=markdown_text,
            media_type="text/markdown",
        )
    elif fmt == "html":
        html = to_html(markdown_text)
        return HTMLResponse(content=html)
    elif fmt == "pdf":
        pdf_bytes = to_pdf(markdown_text)
        if pdf_bytes is None:
            # Fall back to HTML if WeasyPrint unavailable
            html = to_html(markdown_text)
            return HTMLResponse(content=html)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="brief_{case_id}.pdf"'},
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format '{format}'. Use: md, html, pdf",
        )
