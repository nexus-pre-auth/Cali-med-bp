"""Tests for the PDF parser and condition extractor."""

import pytest
from src.parser.pdf_parser import PDFParser
from src.parser.condition_extractor import ConditionExtractor


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
