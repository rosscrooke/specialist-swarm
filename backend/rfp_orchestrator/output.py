"""Render the final proposal markdown to .md and .docx (python-docx).

Supports the markdown subset agents actually produce: headings, paragraphs,
bullet / numbered lists, pipe tables and **bold** / *italic* inline runs.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor

BRAND_COLOR = RGBColor(0x00, 0x6E, 0x6E)
_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")


def _add_inline(paragraph, text: str) -> None:
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*"):
            paragraph.add_run(part[1:-1]).italic = True
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
        else:
            paragraph.add_run(part)


def _is_table_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", line.strip()))


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown_to_docx(markdown: str, path: Path, title: str) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    heading = doc.add_heading(title, level=0)
    for run in heading.runs:
        run.font.color.rgb = BRAND_COLOR

    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Tables
        if stripped.startswith("|") and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
            header = _cells(stripped)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            table = doc.add_table(rows=1, cols=len(header))
            table.style = "Light Grid Accent 1"
            for cell, text in zip(table.rows[0].cells, header):
                cell.text = ""
                _add_inline(cell.paragraphs[0], text)
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            for row in rows:
                cells = table.add_row().cells
                for cell, text in zip(cells, row + [""] * (len(header) - len(row))):
                    cell.text = ""
                    _add_inline(cell.paragraphs[0], text)
            continue

        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            level = min(len(m.group(1)), 4)
            h = doc.add_heading(m.group(2).strip(), level=level)
            for run in h.runs:
                run.font.color.rgb = BRAND_COLOR
        elif re.match(r"^[-*+]\s+", stripped):
            p = doc.add_paragraph(style="List Bullet")
            _add_inline(p, re.sub(r"^[-*+]\s+", "", stripped))
        elif re.match(r"^\d+[.)]\s+", stripped):
            p = doc.add_paragraph(style="List Number")
            _add_inline(p, re.sub(r"^\d+[.)]\s+", "", stripped))
        elif re.fullmatch(r"-{3,}|\*{3,}", stripped):
            pass  # horizontal rule: skip
        else:
            p = doc.add_paragraph()
            _add_inline(p, stripped)
        i += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def write_proposal(final_dir: Path, title: str, markdown: str) -> list[Path]:
    md_path = final_dir / "proposal-response.md"
    docx_path = final_dir / "proposal-response.docx"
    md_path.write_text(f"# {title}\n\n{markdown}", encoding="utf-8")
    markdown_to_docx(markdown, docx_path, title)
    return [md_path, docx_path]
