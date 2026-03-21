"""
PDF Parser — extracts raw text and structured data from project drawings and specs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.monitoring.logger import get_logger

log = get_logger(__name__)

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# PDFCleaner for pre-processing image-based pages.
# Requires Pillow (installed). Full OCR support requires Ghostscript +
# pdfplumber[image]: pip install 'pdfplumber[image]' ghostscript
try:
    from src.preprocessing.pdf_cleaner import PDFCleaner as _PDFCleaner
    _cleaner = _PDFCleaner(enhance_contrast=True, deskew=True)
    HAS_CLEANER = True
except Exception:
    _cleaner = None  # type: ignore[assignment]
    HAS_CLEANER = False

# Pages with fewer characters per 100pt² of area are considered image-based
_MIN_CHARS_PER_AREA = 0.001


@dataclass
class PageContent:
    page_number: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    file_path: str
    total_pages: int
    pages: list[PageContent] = field(default_factory=list)
    full_text: str = ""
    metadata: dict = field(default_factory=dict)

    def get_text_by_keyword(self, keyword: str, context_chars: int = 300) -> list[str]:
        """Return text snippets around keyword occurrences."""
        snippets = []
        text_lower = self.full_text.lower()
        kw_lower = keyword.lower()
        idx = 0
        while True:
            pos = text_lower.find(kw_lower, idx)
            if pos == -1:
                break
            start = max(0, pos - context_chars)
            end = min(len(self.full_text), pos + len(keyword) + context_chars)
            snippets.append(self.full_text[start:end])
            idx = pos + 1
        return snippets


class PDFParser:
    """Extracts text and tables from PDF files (drawings, specifications, reports)."""

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not HAS_PDFPLUMBER:
            raise ImportError("pdfplumber is required: pip install pdfplumber")

        doc = ParsedDocument(file_path=str(path), total_pages=0)

        scanned_pages: list[int] = []

        with pdfplumber.open(path) as pdf:
            doc.total_pages = len(pdf.pages)
            doc.metadata = pdf.metadata or {}

            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                tables = page.extract_tables() or []

                # Detect image-based (scanned) pages that pdfplumber cannot read.
                # Density heuristic: chars per unit area normalised to page size.
                area = (page.width or 1) * (page.height or 1)
                text_density = len(text) / area
                is_image_page = (not text.strip()) and area > 10_000

                if is_image_page:
                    scanned_pages.append(i + 1)
                    # Attempt orientation correction via PDF /Rotate metadata
                    rotation = getattr(page, "rotation", 0) or 0
                    if rotation and HAS_CLEANER:
                        log.info(
                            "Page %d: PDF metadata reports %d° rotation — "
                            "pdfplumber auto-corrects; no text available (image page).",
                            i + 1, rotation,
                        )

                page_content = PageContent(
                    page_number=i + 1,
                    text=text,
                    tables=tables,
                    metadata={"text_density": round(text_density, 6), "is_image_page": is_image_page},
                )
                doc.pages.append(page_content)

        if scanned_pages:
            log.warning(
                "Document '%s' has %d image-based page(s) with no extractable text "
                "(pages: %s). For full compliance review of scanned drawings, "
                "provide a text-searchable PDF. OCR support: pip install pytesseract ghostscript",
                path.name,
                len(scanned_pages),
                ", ".join(str(p) for p in scanned_pages[:10]),
            )
            doc.metadata["scanned_pages"] = scanned_pages

        doc.full_text = "\n".join(p.text for p in doc.pages)
        return doc

    def parse_text_input(self, text: str, source_name: str = "inline") -> ParsedDocument:
        """Wrap raw text as a ParsedDocument (for testing / demo)."""
        doc = ParsedDocument(
            file_path=source_name,
            total_pages=1,
            full_text=text,
        )
        doc.pages.append(PageContent(page_number=1, text=text))
        return doc
