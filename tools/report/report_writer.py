"""Markdown report file writer.

Single module that performs ALL markdown file emission — section builders
must never write files directly.
"""

from __future__ import annotations


def _write_markdown_reports(symbol_dirs, directive_name: str, md_content: str):
    """Write the same md content into each symbol_dir's REPORT_<directive>.md."""
    for s_dir in symbol_dirs:
        out_path = s_dir / f"REPORT_{directive_name}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"[REPORT] Successfully generated: {out_path}")
