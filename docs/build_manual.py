#!/usr/bin/env python3
"""QORVENA · User Manual (English) — professional PDF builder.

Reads /app/docs/user_manual.md and produces a designed, print-ready PDF at
/app/frontend/public/qorvena_user_manual.pdf.

Design goals:
  * Cover page with accent bar and metadata block
  * Auto-generated Table of Contents (two-pass build) with dot leaders
  * Coloured chapter numbers on H2 (##) section headers
  * IMPORTANT · WARNING · TIP callout boxes rendered from `> IMPORTANT ·`,
    `> WARNING ·`, `> TIP ·` markdown blockquotes
  * Clean tables with header shading
  * Running header (chapter title) and footer (product / Page X of Y)
  * Screenshots rendered from `**Screenshot**: screenshots/…png` markers,
    followed by an optional `**Caption**: …` line rendered in muted text

Fonts: DejaVuSans / DejaVuSans-Bold only. NO Telugu (English-only build).

Run:
    python3 /app/docs/build_manual.py
"""
from __future__ import annotations

import os
import re
import sys
from io import BytesIO

sys.path.insert(0, "/app/backend")

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


# ---------------------------------------------------------------------------
# Fonts — DejaVu only (English build)
# ---------------------------------------------------------------------------
FONT_DIR = "/app/backend/fonts"
_F = "DejaVuSans"
_FB = "DejaVuSans-Bold"
if _F not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(_F, f"{FONT_DIR}/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont(_FB, f"{FONT_DIR}/DejaVuSans-Bold.ttf"))
    registerFontFamily(_F, normal=_F, bold=_FB, italic=_F, boldItalic=_FB)


# ---------------------------------------------------------------------------
# Palette — professional / restrained
# ---------------------------------------------------------------------------
C_INK = colors.HexColor("#0F172A")         # slate-900
C_INK_SOFT = colors.HexColor("#334155")    # slate-700
C_MUTED = colors.HexColor("#64748B")       # slate-500
C_LINE = colors.HexColor("#E2E8F0")        # slate-200
C_BG_ROW = colors.HexColor("#F8FAFC")      # slate-50
C_BG_HEAD = colors.HexColor("#F1F5F9")     # slate-100

C_ACCENT = colors.HexColor("#1E3A8A")      # blue-900 (chapter numbers, cover bar)
C_ACCENT_SOFT = colors.HexColor("#3B82F6") # blue-500

# Callout palettes
C_TIP_BG = colors.HexColor("#FEF9C3")      # amber-100
C_TIP_BAR = colors.HexColor("#B45309")     # amber-700
C_IMP_BG = colors.HexColor("#DBEAFE")      # blue-100
C_IMP_BAR = colors.HexColor("#1D4ED8")     # blue-700
C_WARN_BG = colors.HexColor("#FEE2E2")     # red-100
C_WARN_BAR = colors.HexColor("#B91C1C")    # red-700


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MANUAL_MD = "/app/docs/user_manual.md"
OUT_PDF = "/app/frontend/public/qorvena_user_manual.pdf"
SCREENSHOTS_ROOT = "/app/docs"

PAGE_W, PAGE_H = A4
LEFT_M = RIGHT_M = 20 * mm
TOP_M = 22 * mm
BOT_M = 18 * mm
CONTENT_W = PAGE_W - LEFT_M - RIGHT_M


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    s: dict[str, ParagraphStyle] = {}
    s["CoverTitle"] = ParagraphStyle(
        "CoverTitle", parent=base["Title"],
        fontName=_FB, fontSize=34, leading=40, textColor=C_INK,
        alignment=0, spaceAfter=8,
    )
    s["CoverSub"] = ParagraphStyle(
        "CoverSub", fontName=_F, fontSize=14, leading=18,
        textColor=C_INK_SOFT, alignment=0, spaceAfter=4,
    )
    s["CoverMeta"] = ParagraphStyle(
        "CoverMeta", fontName=_F, fontSize=10, leading=14,
        textColor=C_MUTED, alignment=0,
    )
    s["H1"] = ParagraphStyle(
        "H1", fontName=_FB, fontSize=22, leading=28,
        textColor=C_INK, spaceBefore=8, spaceAfter=6,
    )
    s["H2"] = ParagraphStyle(
        "H2", fontName=_FB, fontSize=17, leading=22,
        textColor=C_INK, spaceBefore=14, spaceAfter=6,
    )
    s["H3"] = ParagraphStyle(
        "H3", fontName=_FB, fontSize=13, leading=17,
        textColor=C_ACCENT, spaceBefore=10, spaceAfter=4,
    )
    s["H4"] = ParagraphStyle(
        "H4", fontName=_FB, fontSize=11, leading=15,
        textColor=C_INK_SOFT, spaceBefore=8, spaceAfter=2,
    )
    s["Body"] = ParagraphStyle(
        "Body", fontName=_F, fontSize=10, leading=14.5,
        textColor=C_INK, spaceAfter=4, alignment=0,
    )
    s["Bullet"] = ParagraphStyle(
        "Bullet", fontName=_F, fontSize=10, leading=14.5,
        textColor=C_INK, leftIndent=16, bulletIndent=4, spaceAfter=2,
    )
    s["Numbered"] = ParagraphStyle(
        "Numbered", fontName=_F, fontSize=10, leading=14.5,
        textColor=C_INK, leftIndent=18, bulletIndent=4, spaceAfter=2,
    )
    s["Caption"] = ParagraphStyle(
        "Caption", fontName=_F, fontSize=8.5, leading=11,
        textColor=C_MUTED, alignment=1, spaceBefore=2, spaceAfter=10,
    )
    s["Code"] = ParagraphStyle(
        "Code", fontName="Courier", fontSize=9, leading=12,
        textColor=C_INK, backColor=C_BG_HEAD, borderPadding=3,
    )
    s["TblHead"] = ParagraphStyle(
        "TblHead", fontName=_FB, fontSize=9, leading=12, textColor=C_INK,
    )
    s["TblCell"] = ParagraphStyle(
        "TblCell", fontName=_F, fontSize=9, leading=12, textColor=C_INK,
    )
    s["CalloutLabel"] = ParagraphStyle(
        "CalloutLabel", fontName=_FB, fontSize=8.5, leading=11,
        textColor=colors.white, alignment=0,
    )
    s["CalloutBody"] = ParagraphStyle(
        "CalloutBody", fontName=_F, fontSize=10, leading=14,
        textColor=C_INK, alignment=0,
    )
    s["TOCEntry1"] = ParagraphStyle(
        "TOCEntry1", fontName=_FB, fontSize=11, leading=16,
        textColor=C_INK, leftIndent=0, firstLineIndent=0, spaceAfter=0,
    )
    s["TOCEntry2"] = ParagraphStyle(
        "TOCEntry2", fontName=_F, fontSize=10, leading=14,
        textColor=C_INK_SOFT, leftIndent=18, firstLineIndent=0, spaceAfter=0,
    )
    s["TOCEntry3"] = ParagraphStyle(
        "TOCEntry3", fontName=_F, fontSize=9.5, leading=13,
        textColor=C_MUTED, leftIndent=36, firstLineIndent=0, spaceAfter=0,
    )
    return s


# ---------------------------------------------------------------------------
# Inline markdown → mini-HTML for Paragraph
# ---------------------------------------------------------------------------
def md_inline(txt: str) -> str:
    from xml.sax.saxutils import escape
    t = escape(txt)
    # **bold**
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    # *italic* (avoid touching **)
    t = re.sub(r"(?<!\*)\*(?!\s)([^*\n]+?)\*(?!\*)", r"<i>\1</i>", t)
    # `code`
    t = re.sub(r"`([^`]+)`", r"<font face='Courier'>\1</font>", t)
    return t


# ---------------------------------------------------------------------------
# Callout box (IMPORTANT / WARNING / TIP)
# ---------------------------------------------------------------------------
CALLOUT_MAP = {
    "IMPORTANT": (C_IMP_BG, C_IMP_BAR, "IMPORTANT"),
    "WARNING": (C_WARN_BG, C_WARN_BAR, "WARNING"),
    "TIP": (C_TIP_BG, C_TIP_BAR, "TIP"),
    "NOTE": (C_BG_HEAD, C_MUTED, "NOTE"),
}


def make_callout(kind: str, body: str, styles: dict) -> Table:
    bg, bar, label = CALLOUT_MAP[kind]
    label_para = Paragraph(f"<b>{label}</b>", styles["CalloutLabel"])
    body_para = Paragraph(md_inline(body), styles["CalloutBody"])

    label_cell = Table(
        [[label_para]],
        colWidths=[16 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bar),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )

    outer = Table(
        [[label_cell, body_para]],
        colWidths=[16 * mm, CONTENT_W - 16 * mm],
        style=TableStyle([
            ("BACKGROUND", (1, 0), (1, 0), bg),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("TOPPADDING", (0, 0), (0, 0), 0),
            ("BOTTOMPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 8),
            ("RIGHTPADDING", (1, 0), (1, 0), 8),
            ("TOPPADDING", (1, 0), (1, 0), 6),
            ("BOTTOMPADDING", (1, 0), (1, 0), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
        hAlign="LEFT",
    )
    return outer


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------
def parse_md_table(lines, i, styles):
    header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
    i += 2
    rows = [header]
    while i < len(lines) and lines[i].strip().startswith("|"):
        row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        rows.append(row)
        i += 1
    data = [
        [Paragraph(md_inline(c), styles["TblHead" if r == 0 else "TblCell"])
         for c in row]
        for r, row in enumerate(rows)
    ]
    n_cols = max(len(r) for r in data)
    for row in data:
        while len(row) < n_cols:
            row.append(Paragraph("", styles["TblCell"]))
    col_w = CONTENT_W / n_cols
    tbl = Table(data, colWidths=[col_w] * n_cols, repeatRows=1, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_BG_HEAD),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, C_LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_BG_ROW]),
    ]))
    return tbl, i


# ---------------------------------------------------------------------------
# H2 with coloured chapter number
# ---------------------------------------------------------------------------
def make_h2(title: str, styles: dict) -> Table:
    """Render an H2 with a coloured chapter-number chip + title.

    If the title begins with "N." we split it into (chip, rest); otherwise
    the whole string is rendered without a chip.
    """
    m = re.match(r"^(\d+)\.\s+(.*)$", title.strip())
    if not m:
        return Paragraph(md_inline(title), styles["H2"])

    num, rest = m.group(1), m.group(2)
    chip = Table(
        [[Paragraph(f"<b>{num}</b>",
                    ParagraphStyle("chip", fontName=_FB, fontSize=13,
                                   leading=17, textColor=colors.white,
                                   alignment=1))]],
        colWidths=[11 * mm], rowHeights=[9 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_ACCENT),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]),
    )
    title_para = Paragraph(f"<b>{md_inline(rest)}</b>", styles["H2"])
    row = Table(
        [[chip, title_para]],
        colWidths=[13 * mm, CONTENT_W - 13 * mm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
        hAlign="LEFT",
    )
    return row


# ---------------------------------------------------------------------------
# Screenshot rendering — with caption below
# ---------------------------------------------------------------------------
def make_screenshot(path: str, caption: str | None, styles: dict):
    abs_path = path if os.path.isabs(path) else os.path.join(SCREENSHOTS_ROOT, path)
    if not os.path.exists(abs_path):
        return None
    try:
        img = Image(abs_path, width=CONTENT_W - 10 * mm, height=95 * mm,
                    kind="proportional")
    except Exception:
        return None
    frame_tbl = Table(
        [[img]],
        colWidths=[CONTENT_W],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, C_LINE),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]),
        hAlign="CENTER",
    )
    parts = [frame_tbl]
    if caption:
        parts.append(Paragraph(f"<i>{md_inline(caption)}</i>", styles["Caption"]))
    return KeepTogether(parts)


# ---------------------------------------------------------------------------
# Heading Paragraphs that emit TOC entries (via doc.afterFlowable)
# ---------------------------------------------------------------------------
class TocParagraph(Paragraph):
    """Paragraph carrying TOC metadata; the doc-template picks it up in
    afterFlowable and issues the TOCEntry notify."""

    def __init__(self, text: str, style: ParagraphStyle, level: int, plain: str):
        super().__init__(text, style)
        self._toc_level = level
        self._toc_plain = plain
        self._bookmark = f"toc_{id(self)}"

    def draw(self):  # type: ignore[override]
        self.canv.bookmarkPage(self._bookmark)
        self.canv.addOutlineEntry(self._toc_plain, self._bookmark, level=self._toc_level)
        super().draw()


# ---------------------------------------------------------------------------
# Cover + TOC pages
# ---------------------------------------------------------------------------
def build_cover(styles: dict):
    """Return the flowables for the cover page."""
    story = []
    # Top accent bar
    story.append(Table(
        [[""]], colWidths=[CONTENT_W], rowHeights=[6 * mm],
        style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), C_ACCENT)]),
    ))
    story.append(Spacer(1, 60 * mm))
    story.append(Paragraph(
        "<font color='#1E3A8A'>QORVENA</font>",
        ParagraphStyle("brand", fontName=_FB, fontSize=44, leading=52,
                       alignment=0, textColor=C_ACCENT),
    ))
    story.append(Paragraph(
        "Bitumen Transport ERP",
        ParagraphStyle("brandsub", fontName=_F, fontSize=16, leading=22,
                       textColor=C_INK_SOFT),
    ))
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph("User Manual", styles["CoverTitle"]))
    story.append(Paragraph(
        "A practical, print-ready guide for every module of QORVENA — "
        "written for office staff, accountants, managers, and new users.",
        styles["CoverSub"],
    ))
    story.append(Spacer(1, 30 * mm))

    meta = Table(
        [
            [Paragraph("<b>Version</b>", styles["CoverMeta"]),
             Paragraph("1.0 (English) · <b>Draft — awaiting UAT approval</b>", styles["CoverMeta"])],
            [Paragraph("<b>Compiled</b>", styles["CoverMeta"]),
             Paragraph("February 2026 · Official release date pending", styles["CoverMeta"])],
            [Paragraph("<b>Audience</b>", styles["CoverMeta"]),
             Paragraph("Owners · Admins · Accountants · Managers · Viewers", styles["CoverMeta"])],
            [Paragraph("<b>Scope</b>", styles["CoverMeta"]),
             Paragraph("All modules and current locked business rules", styles["CoverMeta"])],
        ],
        colWidths=[30 * mm, CONTENT_W - 30 * mm],
        style=TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, C_LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
        hAlign="LEFT",
    )
    story.append(meta)
    story.append(PageBreak())
    return story


def build_toc(styles: dict):
    toc = TableOfContents()
    toc.levelStyles = [
        styles["TOCEntry1"], styles["TOCEntry2"], styles["TOCEntry3"],
    ]
    story = [
        Paragraph("Table of Contents", styles["H1"]),
        Spacer(1, 6),
        toc,
        PageBreak(),
    ]
    return story


# ---------------------------------------------------------------------------
# Main markdown → flowables
# ---------------------------------------------------------------------------
def parse_manual(styles: dict):
    text = open(MANUAL_MD, encoding="utf-8").read()
    lines = text.splitlines()
    story: list = []

    i = 0
    in_first_h1 = True  # skip the title H1 (# ...) inside content; cover already shows brand
    skip_title_block = True
    # Skip the top-of-file front matter until first `---`
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Front-matter skip: from `# QORVENA...` down to first `---`
        if skip_title_block:
            if stripped == "---":
                skip_title_block = False
                i += 1
                continue
            i += 1
            continue

        # Skip Table of Contents section entirely (auto-generated later)
        if stripped == "## Table of Contents":
            # advance until next `---`
            i += 1
            while i < len(lines) and lines[i].strip() != "---":
                i += 1
            i += 1  # skip the `---`
            continue

        # Section headers
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            plain = re.sub(r"^\d+\.\s*", "", title)
            # Page break before every top-level chapter (except the very first).
            # Skip the break for Appendix headings so short appendices flow and
            # fill the tail of the previous page instead of wasting a full page.
            is_appendix = title.strip().lower().startswith("appendix")
            if any(isinstance(f, Table) or isinstance(f, Paragraph) for f in story) and not is_appendix:
                story.append(PageBreak())
            elif is_appendix:
                story.append(Spacer(1, 10))
            story.append(make_h2(title, styles))
            # Emit a TOC entry via an invisible TocParagraph
            story.append(TocParagraph(f"<b>{plain}</b>", ParagraphStyle(
                "hidden", fontName=_F, fontSize=0.1, leading=0.1,
                textColor=colors.white), level=0, plain=title))
            # Accent underline
            story.append(Table(
                [[""]], colWidths=[CONTENT_W], rowHeights=[1.5],
                style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), C_ACCENT_SOFT)]),
            ))
            story.append(Spacer(1, 6))
            i += 1
            continue

        if stripped.startswith("### "):
            title = stripped[4:].strip()
            story.append(TocParagraph(md_inline(title), styles["H3"], level=1, plain=title))
            i += 1
            continue

        if stripped.startswith("#### "):
            title = stripped[5:].strip()
            story.append(TocParagraph(md_inline(title), styles["H4"], level=2, plain=title))
            i += 1
            continue

        # Horizontal rule → thin divider
        if stripped == "---":
            story.append(Spacer(1, 4))
            i += 1
            continue

        # Blockquote → callout or muted note
        if stripped.startswith("> "):
            body = stripped[2:].strip()
            kind = None
            for k in CALLOUT_MAP:
                # Support "IMPORTANT ·", "IMPORTANT:", or plain "IMPORTANT "
                m = re.match(rf"^{k}\b[·:.\-\s]*\s*(.*)$", body)
                if m:
                    kind = k
                    body = m.group(1).strip()
                    break
            if kind is None:
                # multi-line blockquote: gather subsequent > lines
                buf = [body]
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith("> "):
                    buf.append(lines[j].strip()[2:].strip())
                    j += 1
                story.append(Paragraph("<i>" + md_inline(" ".join(buf)) + "</i>", styles["Body"]))
                i = j
                continue
            story.append(make_callout(kind, body, styles))
            story.append(Spacer(1, 4))
            i += 1
            continue

        # Screenshot marker (with optional caption on the next line)
        m_shot = re.match(r"\*\*Screenshot\*\*:\s*`?([^`\s]+)`?\s*$", stripped)
        if m_shot:
            path = m_shot.group(1)
            caption = None
            if i + 1 < len(lines):
                m_cap = re.match(r"\*\*Caption\*\*:\s*(.+)$", lines[i + 1].strip())
                if m_cap:
                    caption = m_cap.group(1).strip()
            shot = make_screenshot(path, caption, styles)
            if shot is not None:
                story.append(Spacer(1, 4))
                story.append(shot)
                story.append(Spacer(1, 4))
            # advance past caption if consumed
            i += 2 if caption else 1
            continue

        # Table
        if stripped.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].strip()) <= set("|:- "):
            tbl, i = parse_md_table(lines, i, styles)
            story.append(Spacer(1, 3))
            story.append(tbl)
            story.append(Spacer(1, 6))
            continue

        # Numbered list
        m_num = re.match(r"^\s*(\d+)\.\s+(.*)$", line)
        if m_num:
            para = Paragraph(f"<b>{m_num.group(1)}.</b> {md_inline(m_num.group(2))}",
                             styles["Numbered"])
            story.append(para)
            i += 1
            continue

        # Bulleted list
        m_b = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m_b:
            para = Paragraph("• " + md_inline(m_b.group(1)), styles["Bullet"])
            story.append(para)
            i += 1
            continue

        # Blank
        if not stripped:
            story.append(Spacer(1, 3))
            i += 1
            continue

        # Regular paragraph
        story.append(Paragraph(md_inline(stripped), styles["Body"]))
        i += 1

    return story


# ---------------------------------------------------------------------------
# Header / Footer canvas — two-pass for Page X of Y
# ---------------------------------------------------------------------------
from reportlab.pdfgen.canvas import Canvas as _RLCanvas


class NumberedCanvas(_RLCanvas):
    """Records each page's state and renders header/footer with Page X of Y."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._saved_page_states: list = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            _draw_page_chrome(self, total)
            _RLCanvas.showPage(self)
        _RLCanvas.save(self)


class QorvenaDocTemplate(BaseDocTemplate):
    """Custom doc-template that emits TOCEntry notifications for TocParagraphs."""

    def afterFlowable(self, flowable):  # type: ignore[override]
        if isinstance(flowable, TocParagraph):
            self.notify(
                "TOCEntry",
                (flowable._toc_level, flowable._toc_plain, self.page, flowable._bookmark),
            )


def _draw_page_chrome(canv, total):
    """Draw header + footer on every page except the cover (page 1)."""
    p = canv.getPageNumber()
    if p == 1:
        return
    canv.saveState()
    # Header: brand left, section label right (kept generic to avoid stale titles)
    canv.setFont(_FB, 8.5)
    canv.setFillColor(C_ACCENT)
    canv.drawString(LEFT_M, PAGE_H - 12 * mm, "QORVENA")
    canv.setFont(_F, 8.5)
    canv.setFillColor(C_MUTED)
    canv.drawString(LEFT_M + 24 * mm, PAGE_H - 12 * mm, "Bitumen Transport ERP · User Manual")
    canv.drawRightString(PAGE_W - RIGHT_M, PAGE_H - 12 * mm, "v1.0 Draft · English")
    canv.setStrokeColor(C_LINE)
    canv.setLineWidth(0.4)
    canv.line(LEFT_M, PAGE_H - 14 * mm, PAGE_W - RIGHT_M, PAGE_H - 14 * mm)

    # Footer
    canv.setStrokeColor(C_LINE)
    canv.line(LEFT_M, 14 * mm, PAGE_W - RIGHT_M, 14 * mm)
    canv.setFont(_F, 8.5)
    canv.setFillColor(C_MUTED)
    canv.drawString(LEFT_M, 10 * mm, "© QORVENA · User Manual · v1.0 Draft (English)")
    # Page X of Y — but page 1 is the cover, so we display (p) of (total)
    canv.drawRightString(PAGE_W - RIGHT_M, 10 * mm, f"Page {p} of {total}")
    canv.restoreState()


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
def render():
    styles = _styles()

    story = []
    story.extend(build_cover(styles))
    story.extend(build_toc(styles))
    story.extend(parse_manual(styles))

    # Buffer for two-pass build (TOC needs a rebuild to resolve page numbers)
    buf = BytesIO()

    doc = QorvenaDocTemplate(
        buf, pagesize=A4,
        leftMargin=LEFT_M, rightMargin=RIGHT_M,
        topMargin=TOP_M, bottomMargin=BOT_M,
        title="QORVENA · User Manual (English)",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="normal", showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])

    # multiBuild resolves TOC page numbers; NumberedCanvas draws chrome + Page X of Y
    doc.multiBuild(story, canvasmaker=NumberedCanvas)

    with open(OUT_PDF, "wb") as f:
        f.write(buf.getvalue())
    print(f"Wrote {OUT_PDF} · {len(buf.getvalue())} bytes")


if __name__ == "__main__":
    render()
