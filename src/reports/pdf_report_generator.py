"""
PDF Report Generator — produces official HCAI-style plan review reports as PDF.

Requires: reportlab
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from src.rag.generator import EnrichedViolation
from src.engine.severity_scorer import Severity
from src.parser.condition_extractor import ProjectConditions

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


# ---------------------------------------------------------------------------
# Colour palette matching the HTML report
# ---------------------------------------------------------------------------

_SEVERITY_COLORS = {
    "Critical": colors.HexColor("#E53E3E"),
    "High":     colors.HexColor("#DD6B20"),
    "Medium":   colors.HexColor("#D69E2E"),
    "Low":      colors.HexColor("#38A169"),
}
_NAVY     = colors.HexColor("#1A365D")
_LIGHT_BG = colors.HexColor("#F7FAFC")
_BORDER   = colors.HexColor("#E2E8F0")
_BLUE_BG  = colors.HexColor("#EBF8FF")
_GREEN_BG = colors.HexColor("#F0FFF4")
_GREY     = colors.HexColor("#718096")


def _styles():
    base = getSampleStyleSheet()
    custom = {
        "Title": ParagraphStyle(
            "HCAITitle",
            parent=base["Normal"],
            fontSize=18,
            fontName="Helvetica-Bold",
            textColor=colors.white,
            alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "Subtitle": ParagraphStyle(
            "HCAISubtitle",
            parent=base["Normal"],
            fontSize=9,
            fontName="Helvetica",
            textColor=colors.HexColor("#BEE3F8"),
            alignment=TA_LEFT,
        ),
        "SectionLabel": ParagraphStyle(
            "SectionLabel",
            parent=base["Normal"],
            fontSize=7,
            fontName="Helvetica-Bold",
            textColor=_GREY,
            spaceAfter=2,
        ),
        "Body": ParagraphStyle(
            "HCAIBody",
            parent=base["Normal"],
            fontSize=9,
            fontName="Helvetica",
            leading=13,
            spaceAfter=4,
        ),
        "FixBody": ParagraphStyle(
            "HCAIFixBody",
            parent=base["Normal"],
            fontSize=9,
            fontName="Helvetica",
            leading=13,
            spaceAfter=2,
            leftIndent=6,
        ),
        "Footer": ParagraphStyle(
            "HCAIFooter",
            parent=base["Normal"],
            fontSize=7,
            fontName="Helvetica",
            textColor=_GREY,
            alignment=TA_CENTER,
        ),
    }
    return custom


# ---------------------------------------------------------------------------
# Header / footer callback
# ---------------------------------------------------------------------------

class _HeaderFooter:
    def __init__(self, project_name: str, generated_at: str) -> None:
        self._project = project_name
        self._date = generated_at

    def __call__(self, canvas, doc) -> None:
        canvas.saveState()
        w, h = letter

        # Header bar
        canvas.setFillColor(_NAVY)
        canvas.rect(0, h - 0.55 * inch, w, 0.55 * inch, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(0.4 * inch, h - 0.35 * inch, "HCAI Plan Review — Compliance Report")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(w - 0.4 * inch, h - 0.35 * inch, self._project)

        # Footer
        canvas.setFillColor(_GREY)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(0.4 * inch, 0.3 * inch, f"Generated: {self._date}")
        canvas.drawRightString(
            w - 0.4 * inch, 0.3 * inch,
            f"Page {doc.page}  |  Autonomous HCAI Compliance Engine",
        )
        canvas.setStrokeColor(_BORDER)
        canvas.line(0.4 * inch, 0.45 * inch, w - 0.4 * inch, 0.45 * inch)

        canvas.restoreState()


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def render_pdf_report(
    enriched: list[EnrichedViolation],
    conditions: ProjectConditions,
    project_name: str = "Healthcare Project",
    output_path: Optional[str | Path] = None,
) -> Path:
    """
    Build an HCAI-style official PDF report.

    Returns the Path where the PDF was written.
    Raises ImportError if reportlab is not installed.
    """
    if not HAS_REPORTLAB:
        raise ImportError("reportlab is required: pip install reportlab")

    if output_path is None:
        output_path = config.OUTPUT_DIR / "hcai_report.pdf"

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    st = _styles()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    doc = SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.6 * inch,
    )

    story = []

    # ------------------------------------------------------------------
    # Cover header block (navy background table)
    # ------------------------------------------------------------------
    header_data = [[
        Paragraph(f"HCAI Plan Review — Compliance Report", st["Title"]),
    ]]
    header_tbl = Table(header_data, colWidths=[doc.width])
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 6))

    # Project meta
    meta_rows = [
        ["Project", project_name],
        ["Facility", conditions.occupancy_type or "N/A"],
        ["County", conditions.county or "N/A"],
        ["Construction Type", conditions.construction_type or "N/A"],
        ["Seismic Zone", conditions.seismic.seismic_zone or "N/A"],
        ["Generated", generated_at],
    ]
    meta_tbl = Table(
        [[Paragraph(k, st["SectionLabel"]), Paragraph(v, st["Body"])]
         for k, v in meta_rows],
        colWidths=[1.1 * inch, doc.width - 1.1 * inch],
    )
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, _LIGHT_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 10))

    # ------------------------------------------------------------------
    # Severity summary pills
    # ------------------------------------------------------------------
    counts = {s.value: sum(1 for ev in enriched if ev.violation.severity.value == s.value)
              for s in Severity}

    pill_data = [[
        Paragraph(f"<font color='white'><b>Critical: {counts['Critical']}</b></font>", st["Body"]),
        Paragraph(f"<font color='white'><b>High: {counts['High']}</b></font>", st["Body"]),
        Paragraph(f"<font color='white'><b>Medium: {counts['Medium']}</b></font>", st["Body"]),
        Paragraph(f"<font color='white'><b>Low: {counts['Low']}</b></font>", st["Body"]),
        Paragraph(f"<font color='white'><b>Total: {len(enriched)}</b></font>", st["Body"]),
    ]]
    pill_tbl = Table(pill_data, colWidths=[doc.width / 5] * 5)
    pill_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), _SEVERITY_COLORS["Critical"]),
        ("BACKGROUND", (1, 0), (1, 0), _SEVERITY_COLORS["High"]),
        ("BACKGROUND", (2, 0), (2, 0), _SEVERITY_COLORS["Medium"]),
        ("BACKGROUND", (3, 0), (3, 0), _SEVERITY_COLORS["Low"]),
        ("BACKGROUND", (4, 0), (4, 0), colors.HexColor("#4A5568")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    story.append(pill_tbl)
    story.append(Spacer(1, 14))

    # ------------------------------------------------------------------
    # Violations
    # ------------------------------------------------------------------
    for ev in enriched:
        v = ev.violation
        sev_color = _SEVERITY_COLORS[v.severity.value]

        # Violation header row
        hdr_data = [[
            Paragraph(
                f"<font color='white'><b> {v.severity.value.upper()} </b></font>",
                st["Body"],
            ),
            Paragraph(
                f"<font color='#718096'>{v.rule_id}</font>  <b>{v.discipline}</b>",
                st["Body"],
            ),
            Paragraph(
                f"<font color='#718096'>{v.trigger_condition}</font>",
                ParagraphStyle("rt", parent=st["Body"], alignment=TA_RIGHT),
            ),
        ]]
        hdr_tbl = Table(
            hdr_data,
            colWidths=[0.9 * inch, doc.width - 2.0 * inch, 1.1 * inch],
        )
        hdr_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), sev_color),
            ("BACKGROUND", (1, 0), (2, 0), colors.HexColor("#EDF2F7")),
            ("ALIGN", (0, 0), (0, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
        ]))

        # AHJ comment block
        ahj_data = [[
            Paragraph("<b>AHJ PLAN REVIEW COMMENT</b>", st["SectionLabel"]),
        ], [
            Paragraph(ev.ahj_comment, st["Body"]),
        ]]
        ahj_tbl = Table(ahj_data, colWidths=[doc.width])
        ahj_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _BLUE_BG),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEAFTER", (0, 0), (0, -1), 3, colors.HexColor("#3182CE")),
        ]))

        # Fix block
        fix_data = [[
            Paragraph("<b>STEP-BY-STEP COMPLIANCE FIX</b>", st["SectionLabel"]),
        ], [
            Paragraph(ev.fix_instructions.replace("\n", "<br/>"), st["FixBody"]),
        ]]
        fix_tbl = Table(fix_data, colWidths=[doc.width])
        fix_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _GREEN_BG),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEAFTER", (0, 0), (0, -1), 3, _SEVERITY_COLORS["Low"]),
        ]))

        # Citations
        citation_text = "  •  ".join(ev.citations) if ev.citations else "N/A"
        cit_data = [[
            Paragraph("<b>CODE CITATIONS</b>", st["SectionLabel"]),
        ], [
            Paragraph(citation_text, ParagraphStyle(
                "Cit", parent=st["Body"], fontSize=8, textColor=_GREY,
            )),
        ]]
        cit_tbl = Table(cit_data, colWidths=[doc.width])
        cit_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))

        story.append(KeepTogether([
            hdr_tbl,
            ahj_tbl,
            fix_tbl,
            cit_tbl,
            Spacer(1, 10),
        ]))

    # Disclaimer
    story.append(HRFlowable(width="100%", thickness=0.5, color=_BORDER))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This report is generated by the Autonomous HCAI Compliance Engine for plan review "
        "purposes. Always verify compliance with the current adopted edition of Title 24 CBC "
        "and official HCAI policy documents before making design decisions.",
        st["Footer"],
    ))

    doc.build(
        story,
        onFirstPage=_HeaderFooter(project_name, generated_at),
        onLaterPages=_HeaderFooter(project_name, generated_at),
    )

    return out
