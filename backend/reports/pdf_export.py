"""
backend/reports/pdf_export.py

Converts a Markdown brief to PDF (WeasyPrint) or HTML fallback.

Public API
──────────
to_html(markdown_text) -> str
    Convert Markdown to HTML string.

to_pdf(markdown_text) -> bytes | None
    Convert Markdown to PDF bytes via WeasyPrint.
    Returns None if WeasyPrint or Markdown lib is unavailable.
    Callers should check for None and fall back to HTML.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Minimal CSS for PDF/HTML output
_CSS = """
body {
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
    line-height: 1.6;
    color: #1f2328;
    max-width: 900px;
    margin: 0 auto;
    padding: 24px;
}
h1, h2, h3 { color: #1f2328; }
blockquote {
    border-left: 4px solid #3b82d4;
    padding-left: 12px;
    color: #57606a;
    margin: 16px 0;
}
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid #e5e7eb; padding: 6px 10px; text-align: left; }
th { background: #f7f8fa; font-weight: 600; }
code { background: #f7f8fa; padding: 2px 5px; border-radius: 3px; font-family: monospace; }
"""


def to_html(markdown_text: str) -> str:
    """
    Convert a Markdown string to a full HTML document.

    Uses 'markdown' library if available, else wraps in <pre> as plain text.
    """
    try:
        import markdown as md_lib
        body = md_lib.markdown(
            markdown_text,
            extensions=["tables", "fenced_code"],
        )
    except ImportError:
        # Wrap as preformatted text
        escaped = markdown_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        body = f"<pre>{escaped}</pre>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JAAL Case Brief</title>
<style>{_CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


def to_pdf(markdown_text: str) -> bytes | None:
    """
    Convert a Markdown brief to PDF bytes.

    Requires WeasyPrint and the markdown library.
    Returns None if either is unavailable; callers should fall back to HTML.
    """
    html = to_html(markdown_text)
    try:
        from weasyprint import HTML
        pdf_bytes: bytes = HTML(string=html).write_pdf()
        return pdf_bytes
    except ImportError:
        logger.info("WeasyPrint not installed; PDF export not available.")
        return None
    except Exception as exc:
        logger.warning("PDF generation failed: %s", exc)
        return None
