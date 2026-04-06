"""
PDF Parser — extracts raw text and structured data from project drawings and specs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except BaseException:
    # Catches ImportError *and* pyo3_runtime.PanicException (Rust panic when
    # the cryptography wheel's native extension is missing or broken in CI).
    HAS_PDFPLUMBER = False


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

        with pdfplumber.open(path) as pdf:
            doc.total_pages = len(pdf.pages)
            doc.metadata = pdf.metadata or {}

            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                tables = page.extract_tables() or []
                page_content = PageContent(
                    page_number=i + 1,
                    text=text,
                    tables=tables,
                )
                doc.pages.append(page_content)

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
