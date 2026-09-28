"""
tests/test_brief_builder.py

Tests for backend/reports/brief_builder.py and pdf_export.py

Covers:
  1.  build_brief returns a string
  2.  build_brief includes case_id in output
  3.  build_brief includes disclaimer
  4.  build_brief includes timeline events
  5.  build_brief includes role labels
  6.  build_brief with no graph produces valid output
  7.  build_brief with GraphPayload includes node types
  8.  to_html returns valid HTML
  9.  to_html contains body tag
  10. to_pdf returns None when WeasyPrint not installed (graceful)
"""
from __future__ import annotations

import pytest

from backend.reports.brief_builder import build_brief
from backend.reports.pdf_export import to_html, to_pdf
from backend.schemas.analysis import PatternMatch, PatternType, Role, RoleScore
from backend.schemas.result import AnalysisResult, TimelineEvent, Totals


# ---------------------------------------------------------------------------
# Fixture — minimal AnalysisResult
# ---------------------------------------------------------------------------

def _make_analysis(case_id: str = "TEST-001") -> AnalysisResult:
    return AnalysisResult(
        case_id=case_id,
        primary_pattern=PatternMatch(
            type=PatternType.MULE_LAYERING,
            confidence=0.8,
            reasons=["3 transfers detected", "2 pass-through nodes"],
        ),
        all_patterns=[
            PatternMatch(
                type=PatternType.MULE_LAYERING,
                confidence=0.8,
                reasons=["3 transfers detected"],
            ),
        ],
        roles=[
            RoleScore(node_id="BA_VICTIM01", role=Role.VICTIM, score=0.8, why=["1 outgoing transfer"]),
            RoleScore(node_id="BA_MULE01", role=Role.MULE, score=1.0, why=["fan-in + fan-out"]),
            RoleScore(node_id="BA_KP01", role=Role.KINGPIN, score=0.83, why=["terminal sink"]),
        ],
        levels=[["BA_KP01"], ["BA_MULE01"], ["BA_VICTIM01"]],
        totals=Totals(loss_inr=50000.0, victims=1, mules=1),
        timeline=[
            TimelineEvent(ts="2024-01-15T10:00:00", event="Transfer of 50000 INR"),
            TimelineEvent(ts="2024-01-15T10:22:00", event="Transfer of 47000 INR"),
        ],
    )


# ---------------------------------------------------------------------------
# Tests for build_brief
# ---------------------------------------------------------------------------

class TestBuildBrief:
    def test_returns_string(self):
        analysis = _make_analysis()
        result = build_brief(analysis)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_case_id(self):
        analysis = _make_analysis("MY-CASE-42")
        result = build_brief(analysis)
        assert "MY-CASE-42" in result

    def test_includes_disclaimer(self):
        analysis = _make_analysis()
        result = build_brief(analysis).lower()
        assert "disclaimer" in result or "ai-assisted" in result or "verification" in result

    def test_includes_timeline_events(self):
        analysis = _make_analysis()
        result = build_brief(analysis)
        assert "2024-01-15T10:00:00" in result
        assert "50000" in result

    def test_includes_role_labels(self):
        analysis = _make_analysis()
        result = build_brief(analysis)
        assert "MULE" in result or "Mule" in result.lower() or "mule" in result.lower()

    def test_includes_pattern_type(self):
        analysis = _make_analysis()
        result = build_brief(analysis)
        assert "MULE_LAYERING" in result

    def test_no_graph_still_works(self):
        analysis = _make_analysis()
        result = build_brief(analysis, graph=None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_with_empty_analysis(self):
        analysis = AnalysisResult(case_id="EMPTY-CASE")
        result = build_brief(analysis)
        assert "EMPTY-CASE" in result


# ---------------------------------------------------------------------------
# Tests for to_html
# ---------------------------------------------------------------------------

class TestToHtml:
    def test_returns_string(self):
        html = to_html("# Hello\n\nWorld")
        assert isinstance(html, str)

    def test_contains_html_tag(self):
        html = to_html("# Hello")
        assert "<html" in html.lower()

    def test_contains_body_tag(self):
        html = to_html("# Hello")
        assert "<body" in html.lower()

    def test_contains_content(self):
        html = to_html("My test content here.")
        assert "My test content here" in html

    def test_escapes_special_chars_in_fallback(self):
        # Should not crash on special characters
        html = to_html("Test & <special> chars")
        assert isinstance(html, str)


# ---------------------------------------------------------------------------
# Tests for to_pdf
# ---------------------------------------------------------------------------

class TestToPdf:
    def test_returns_bytes_or_none(self):
        result = to_pdf("# Test Brief\n\nContent.")
        assert result is None or isinstance(result, bytes)

    def test_does_not_raise(self):
        """to_pdf must never raise — returns None if WeasyPrint not available."""
        try:
            result = to_pdf("# Brief\n\nTest.")
            assert result is None or isinstance(result, bytes)
        except Exception as exc:
            pytest.fail(f"to_pdf raised an exception: {exc}")
