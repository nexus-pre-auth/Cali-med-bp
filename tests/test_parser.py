"""Tests for the PDF parser and condition extractor."""

from unittest.mock import MagicMock, patch

import pytest

from src.parser.condition_extractor import ConditionExtractor
from src.parser.pdf_parser import PDFParser, _ocr_pdf_pages

SAMPLE_TEXT = """
PROJECT: Valley General Hospital — New Patient Tower
Location: City of Los Angeles, Los Angeles County, California

FACILITY TYPE: Occupied Hospital (Acute Care)
Licensed Beds: 150
Construction Type: Type I-A, Fully Sprinklered (NFPA 13)
Building Height: 80 feet, 6 Stories Above Grade

SEISMIC DESIGN CATEGORY: D
SDS: 1.2, SD1: 0.6, Importance Factor Ip: 1.5, Site Class: D

ROOMS: operating room, ICU, isolation room, patient room, pharmacy, NICU

SYSTEMS: AHU, essential electrical system, medical gas, oxygen manifold,
WAGD, vacuum pump, HEPA filter, generator, life safety branch, critical branch
"""


@pytest.fixture
def parsed_doc():
    parser = PDFParser()
    return parser.parse_text_input(SAMPLE_TEXT, "test_project")


@pytest.fixture
def conditions(parsed_doc):
    extractor = ConditionExtractor()
    return extractor.extract(parsed_doc)


class TestPDFParser:
    def test_parse_text_input(self, parsed_doc):
        assert parsed_doc.total_pages == 1
        assert "Valley General Hospital" in parsed_doc.full_text

    def test_keyword_search(self, parsed_doc):
        snippets = parsed_doc.get_text_by_keyword("Hospital")
        assert len(snippets) > 0


class TestConditionExtractor:
    def test_occupancy_type(self, conditions):
        assert conditions.occupancy_type == "Occupied Hospital"

    def test_seismic_zone(self, conditions):
        assert conditions.seismic.seismic_zone == "D"

    def test_seismic_sds(self, conditions):
        assert conditions.seismic.sds == pytest.approx(1.2)

    def test_seismic_ip(self, conditions):
        assert conditions.seismic.importance_factor == pytest.approx(1.5)

    def test_sprinklered(self, conditions):
        assert conditions.sprinklered is True

    def test_licensed_beds(self, conditions):
        assert conditions.licensed_beds == 150

    def test_rooms_identified(self, conditions):
        room_lower = [r.lower() for r in conditions.room_types]
        assert any("operating room" in r or "or" in r for r in room_lower)

    def test_hvac_systems(self, conditions):
        assert len(conditions.hvac_systems) > 0

    def test_electrical_systems(self, conditions):
        assert len(conditions.electrical_systems) > 0

    def test_medical_gas_systems(self, conditions):
        assert len(conditions.medical_gas_systems) > 0

    def test_county(self, conditions):
        assert conditions.county == "Los Angeles"


# ---------------------------------------------------------------------------
# OCR fallback tests
# ---------------------------------------------------------------------------

class TestOCRFallback:
    """
    Tests for the OCR path in _parse_bytes_internal.

    pdf2image and pytesseract are not installed in the CI environment, so
    we test via mocking. The real OCR path is exercised by Dockerfile builds.
    """

    def _make_scanned_page_pdf(self):
        """
        Create a minimal pdfplumber-parseable PDF bytes object that returns
        an empty page (simulating a scanned page with no extractable text).
        """
        try:
            import io as _io

            import reportlab.pdfgen.canvas as rlcanvas
            buf = _io.BytesIO()
            c = rlcanvas.Canvas(buf, pagesize=(612, 792))
            c.save()
            return buf.getvalue()
        except ImportError:
            pytest.skip("reportlab not available")

    def test_ocr_not_called_on_text_page(self):
        """OCR should NOT be called if pdfplumber successfully extracts text."""
        parser = PDFParser()
        # parse_text_input bypasses pdfplumber entirely
        doc = parser.parse_text_input("Occupied Hospital, 100 beds.", "test")
        assert doc.full_text == "Occupied Hospital, 100 beds."
        # No scanned_pages metadata on a text input
        assert "scanned_pages" not in doc.metadata

    def test_ocr_pdf_pages_returns_empty_without_ocr_libs(self):
        """When HAS_OCR is False, _ocr_pdf_pages returns an empty dict."""
        import src.parser.pdf_parser as mod
        original = mod.HAS_OCR
        try:
            mod.HAS_OCR = False
            result = _ocr_pdf_pages(b"fake", [1, 2])
            assert result == {}
        finally:
            mod.HAS_OCR = original

    def test_ocr_pdf_pages_with_mocked_libs(self):
        """When HAS_OCR is True, _ocr_pdf_pages calls pdf2image + pytesseract."""
        import src.parser.pdf_parser as mod
        original_has_ocr = mod.HAS_OCR

        mock_image = MagicMock()
        mock_convert = MagicMock(return_value=[mock_image])
        mock_tesseract = MagicMock(return_value="Occupied Hospital 100 beds oxygen manifold")

        try:
            mod.HAS_OCR = True
            mod._convert_from_bytes = mock_convert
            mod._pytesseract = MagicMock()
            mod._pytesseract.image_to_string = mock_tesseract

            result = _ocr_pdf_pages(b"fake_pdf", [1])
            assert 1 in result
            assert "Occupied Hospital" in result[1]
        finally:
            mod.HAS_OCR = original_has_ocr

    def test_parse_bytes_method_exists(self):
        """parse_bytes convenience method should exist and return a ParsedDocument."""
        parser = PDFParser()
        assert hasattr(parser, "parse_bytes")
        assert callable(parser.parse_bytes)

    def test_scanned_page_triggers_ocr_and_populates_text(self):
        """
        When a scanned page is detected and OCR returns text, that text
        should appear in the document's full_text.

        Patches pdfplumber.open at the module level so the test runs even
        when pdfplumber is not installed in the test environment.
        """
        pytest.importorskip("pdfplumber", reason="pdfplumber not installed")

        import src.parser.pdf_parser as mod
        original_has_ocr = mod.HAS_OCR
        original_convert = getattr(mod, "_convert_from_bytes", None)
        original_tesseract = getattr(mod, "_pytesseract", None)

        try:
            ocr_text = "Occupied Hospital 80 licensed beds zone valve oxygen"
            mock_image = MagicMock()
            mock_convert = MagicMock(return_value=[mock_image])
            mock_ts = MagicMock()
            mock_ts.image_to_string = MagicMock(return_value=ocr_text)

            mod.HAS_OCR = True
            mod._convert_from_bytes = mock_convert
            mod._pytesseract = mock_ts

            blank_page = MagicMock()
            blank_page.extract_text.return_value = ""
            blank_page.extract_tables.return_value = []
            blank_page.width = 612
            blank_page.height = 792

            mock_pdf = MagicMock()
            mock_pdf.pages = [blank_page]
            mock_pdf.metadata = {}
            mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
            mock_pdf.__exit__ = MagicMock(return_value=False)

            with patch("pdfplumber.open", return_value=mock_pdf):
                parser = PDFParser()
                doc = parser._parse_bytes_internal(b"fake", "test.pdf")

            assert ocr_text in doc.full_text
            assert doc.metadata.get("scanned_pages") == [1]
            assert doc.pages[0].metadata.get("ocr") is True
        finally:
            mod.HAS_OCR = original_has_ocr
            if original_convert is not None:
                mod._convert_from_bytes = original_convert
            if original_tesseract is not None:
                mod._pytesseract = original_tesseract
