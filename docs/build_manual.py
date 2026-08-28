#!/usr/bin/env python3
"""QORVENA · Build the User Manual PDF from `user_manual.md`.

Simple Markdown → PDF converter using ReportLab. Reuses the same
Unicode font stack as the invoice PDF so Telugu renders correctly.

Usage:
    python3 /app/docs/build_manual.py

Output:
    /app/frontend/public/qorvena_user_manual.pdf
    /app/docs/build.log  (any warnings)
"""
from __future__ import annotations

import os
import re
import sys
from io import BytesIO

sys.path.insert(0, "/app/backend")

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image,
    KeepTogether,
)

# Reuse invoice font registrations (DejaVu — supports Rupee sign).
# Importing pdf._base triggers font registration as a module side-effect.
import pdf._base as _pdf_base  # noqa: F401  · side-effect: registers DejaVu fonts
from pdf._base import _UNI_FONT as _DEJA, _UNI_FONT_BOLD as _DEJA_B  # type: ignore

# Register Telugu-capable font from bundled Noto Sans Telugu.
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

_TEL_FONT = "NotoSansTelugu"
_TEL_FONT_BOLD = "NotoSansTelugu-Bold"
try:
    if _TEL_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_TEL_FONT, "/app/backend/fonts/NotoSansTelugu-Regular.ttf"))
        pdfmetrics.registerFont(TTFont(_TEL_FONT_BOLD, "/app/backend/fonts/NotoSansTelugu-Bold.ttf"))
        registerFontFamily(_TEL_FONT, normal=_TEL_FONT, bold=_TEL_FONT_BOLD,
                           italic=_TEL_FONT, boldItalic=_TEL_FONT_BOLD)
    _F = _TEL_FONT           # use Telugu-capable font everywhere so both scripts render
    _FB = _TEL_FONT_BOLD
except Exception:
    _F = _DEJA
    _FB = _DEJA_B

MANUAL_MD = "/app/docs/user_manual.md"
OUT_PDF = "/app/frontend/public/qorvena_user_manual.pdf"
SCREENSHOTS_DIR = "/app/docs/screenshots"

C_INK = colors.HexColor("#0F172A")
C_MUTED = colors.HexColor("#64748B")
C_ACCENT = colors.HexColor("#F59E0B")
C_LINE = colors.HexColor("#E2E8F0")
C_CODE = colors.HexColor("#F1F5F9")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("H1c", fontName=_FB, fontSize=22, leading=28, textColor=C_INK, spaceBefore=14, spaceAfter=10))
    s.add(ParagraphStyle("H2c", fontName=_FB, fontSize=16, leading=20, textColor=C_INK, spaceBefore=12, spaceAfter=6))
    s.add(ParagraphStyle("H3c", fontName=_FB, fontSize=13, leading=16, textColor=C_INK, spaceBefore=8, spaceAfter=4))
    s.add(ParagraphStyle("Body2", fontName=_F, fontSize=10, leading=14, textColor=C_INK, spaceAfter=4))
    s.add(ParagraphStyle("BulletC", fontName=_F, fontSize=10, leading=14, textColor=C_INK, leftIndent=14, bulletIndent=4))
    s.add(ParagraphStyle("CodeC", fontName="Courier", fontSize=9, leading=12, textColor=C_INK, backColor=C_CODE, borderPadding=4))
    s.add(ParagraphStyle("MutedC", fontName=_F, fontSize=8, leading=11, textColor=C_MUTED))
    s.add(ParagraphStyle("TblHead", fontName=_FB, fontSize=9, leading=12, textColor=C_INK))
    s.add(ParagraphStyle("TblCell", fontName=_F, fontSize=9, leading=12, textColor=C_INK))
    return s


def _md_inline(txt, styles):
    """Convert **bold**, *italic*, `code`, [link](url) inline markers to ReportLab HTML."""
    # Escape < > & first, then re-inject markup.
    from xml.sax.saxutils import escape
    t = escape(txt)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\s)([^*\n]+?)\*", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r"<font face='Courier'>\1</font>", t)
    return t


def _parse_table(lines, i):
    """Parse a GitHub-style markdown table starting at lines[i]. Returns
    (Table flowable, next_index)."""
    header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
    i += 2  # skip separator row
    rows = [header]
    while i < len(lines) and lines[i].strip().startswith("|"):
        row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        rows.append(row)
        i += 1
    return rows, i


def render():
    if not os.path.exists(MANUAL_MD):
        raise SystemExit(f"Manual source missing: {MANUAL_MD}")
    text = open(MANUAL_MD, encoding="utf-8").read()
    lines = text.splitlines()
    styles = _styles()
    story = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Headers
        if stripped.startswith("# "):
            story.append(Paragraph(_md_inline(stripped[2:], styles), styles["H1c"]))
            i += 1; continue
        if stripped.startswith("## "):
            story.append(Paragraph(_md_inline(stripped[3:], styles), styles["H2c"]))
            i += 1; continue
        if stripped.startswith("### "):
            story.append(Paragraph(_md_inline(stripped[4:], styles), styles["H3c"]))
            i += 1; continue
        if stripped.startswith("#### "):
            story.append(Paragraph(_md_inline(stripped[5:], styles), styles["H3c"]))
            i += 1; continue

        # Horizontal rule → page break
        if stripped == "---":
            story.append(Spacer(1, 6))
            story.append(Table([[""]], colWidths=[170 * mm], style=[
                ("LINEABOVE", (0, 0), (-1, -1), 0.5, C_LINE)]))
            story.append(Spacer(1, 6))
            i += 1; continue

        # Screenshot placeholder: `**Screenshot**: screenshots/xx.png`
        m = re.match(r"\*\*Screenshot\*\*:\s*`?(\S+?)`?\s*(\(.+\))?$", stripped)
        if m:
            path = m.group(1)
            abs_path = path if os.path.isabs(path) else os.path.join("/app/docs", path)
            if os.path.exists(abs_path):
                try:
                    story.append(Image(abs_path, width=140 * mm, height=80 * mm, kind="proportional"))
                except Exception:
                    story.append(Paragraph(f"[screenshot: {path} — could not embed]", styles["MutedC"]))
            else:
                story.append(Table([[Paragraph(f"<b>[Screenshot placeholder]</b><br/>{path}<br/><i>Provide real screenshot or run capture_screenshots.py</i>",
                                                 styles["MutedC"])]],
                                    colWidths=[140 * mm], style=[
                                        ("BOX", (0, 0), (-1, -1), 0.5, C_ACCENT),
                                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFBEB")),
                                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                        ("TOPPADDING", (0, 0), (-1, -1), 20),
                                        ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
                                    ]))
            story.append(Spacer(1, 6))
            i += 1; continue

        # Tables
        if stripped.startswith("|") and i + 1 < len(lines) and set(lines[i+1].strip()) <= set("|:- "):
            rows, i = _parse_table(lines, i)
            data = [[Paragraph(_md_inline(c, styles), styles["TblHead" if r == 0 else "TblCell"]) for c in row] for r, row in enumerate(rows)]
            n_cols = max(len(r) for r in data)
            col_w = (170 * mm) / n_cols
            tbl = Table(data, colWidths=[col_w] * n_cols, repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                ("GRID", (0, 0), (-1, -1), 0.4, C_LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 6))
            continue

        # Blockquotes
        if stripped.startswith("> "):
            story.append(Paragraph(_md_inline(stripped[2:], styles), styles["MutedC"]))
            i += 1; continue

        # Bullets
        if re.match(r"^\s*[-*]\s+", line):
            m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
            indent = len(m.group(1)) // 2
            body = m.group(2)
            para = Paragraph("• " + _md_inline(body, styles), styles["BulletC"])
            para.leftIndent = 14 + indent * 12
            story.append(para)
            i += 1; continue

        if re.match(r"^\s*\d+\.\s+", line):
            m = re.match(r"^\s*(\d+)\.\s+(.*)$", line)
            para = Paragraph(f"{m.group(1)}. " + _md_inline(m.group(2), styles), styles["BulletC"])
            story.append(para)
            i += 1; continue

        # Blank line
        if not stripped:
            story.append(Spacer(1, 4))
            i += 1; continue

        # Regular paragraph
        story.append(Paragraph(_md_inline(stripped, styles), styles["Body2"]))
        i += 1

    # Build the PDF
    buf = BytesIO()

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_F, 8)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(20 * mm, 10 * mm, "QORVENA · User Manual · v1.0")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="QORVENA · User Manual",
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    with open(OUT_PDF, "wb") as f:
        f.write(buf.getvalue())
    print(f"Wrote {OUT_PDF} · {len(buf.getvalue())} bytes · story items = {len(story)}")


if __name__ == "__main__":
    render()
