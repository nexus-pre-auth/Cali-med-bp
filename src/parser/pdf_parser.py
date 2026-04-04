"""
PDF Parser — extracts raw text and structured data from project drawings and specs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.monitoring.logger import get_logger

log = get_logger(__name__)

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# PDFCleaner for pre-processing image-based pages.
try:
    from src.preprocessing.pdf_cleaner import PDFCleaner as _PDFCleaner
    _cleaner = _PDFCleaner(enhance_contrast=True, deskew=True)
    HAS_CLEANER = True
except Exception:
    _cleaner = None  # type: ignore[assignment]
    HAS_CLEANER = False

# OCR fallback — activated when pdf2image + pytesseract are installed.
# Handles scanned drawings that pdfplumber cannot read.
# Dockerfile includes: tesseract-ocr, tesseract-ocr-eng
# requirements.txt includes: pdf2image, pytesseract
try:
    import pytesseract as _pytesseract
    from pdf2image import convert_from_bytes as _convert_from_bytes
    HAS_OCR = True
    log.debug("OCR support available (pytesseract + pdf2image).")
except ImportError:
    HAS_OCR = False

# Pages with fewer characters per 100pt² of area are considered image-based
_MIN_CHARS_PER_AREA = 0.001


def _ocr_pdf_pages(pdf_bytes: bytes, page_numbers: list[int]) -> dict[int, str]:
    """
    Run Tesseract OCR on specific pages of a PDF (1-indexed).
    Returns {page_number: ocr_text}.
    Silently returns empty strings on any failure.
    """
    if not HAS_OCR or not page_numbers:
        return {}

    results: dict[int, str] = {}
    try:
        images = _convert_from_bytes(pdf_bytes, dpi=200)
        for page_no in page_numbers:
            idx = page_no - 1
            if 0 <= idx < len(images):
                results[page_no] = _pytesseract.image_to_string(
                    images[idx], config="--psm 6"
                )
    except Exception as exc:
        log.warning("OCR failed: %s", exc)
    return results


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

        pdf_bytes = path.read_bytes()
        return self._parse_bytes_internal(pdf_bytes, source_name=str(path))

    def parse_bytes(self, pdf_bytes: bytes, source_name: str = "upload.pdf") -> ParsedDocument:
        """Parse a PDF from raw bytes (e.g. uploaded file)."""
        if not HAS_PDFPLUMBER:
            raise ImportError("pdfplumber is required: pip install pdfplumber")
        return self._parse_bytes_internal(pdf_bytes, source_name=source_name)

    def _parse_bytes_internal(self, pdf_bytes: bytes, source_name: str) -> ParsedDocument:
        import io
        doc = ParsedDocument(file_path=source_name, total_pages=0)
        scanned_page_numbers: list[int] = []
        page_contents: list[PageContent] = []

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            doc.total_pages = len(pdf.pages)
            doc.metadata = pdf.metadata or {}

            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                tables = page.extract_tables() or []

                area = (page.width or 1) * (page.height or 1)
                text_density = len(text) / area
                is_image_page = (not text.strip()) and area > 10_000

                if is_image_page:
                    scanned_page_numbers.append(i + 1)

                page_contents.append(PageContent(
                    page_number=i + 1,
                    text=text,
                    tables=tables,
                    metadata={"text_density": round(text_density, 6), "is_image_page": is_image_page},
                ))

        # OCR pass — batch-process all scanned pages in one pdf2image call
        if scanned_page_numbers:
            if HAS_OCR:
                log.info(
                    "'%s': %d scanned page(s) detected — running OCR (pages: %s).",
                    source_name, len(scanned_page_numbers),
                    ", ".join(str(p) for p in scanned_page_numbers[:10]),
                )
                ocr_results = _ocr_pdf_pages(pdf_bytes, scanned_page_numbers)
                for page_no, ocr_text in ocr_results.items():
                    if ocr_text.strip():
                        pc = page_contents[page_no - 1]
                        pc.text = ocr_text
                        pc.metadata["ocr"] = True
            else:
                log.warning(
                    "'%s': %d scanned page(s) with no extractable text. "
                    "Install pytesseract + pdf2image for OCR support.",
                    source_name, len(scanned_page_numbers),
                )
            doc.metadata["scanned_pages"] = scanned_page_numbers

        doc.pages = page_contents
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
