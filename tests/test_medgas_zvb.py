"""
Tests for RULE-024 — Medical Gas Zone Valve Box Accessibility.

Covers:
- Rule fires when zone valve / valve box systems are detected in qualifying occupancies
- Rule does NOT fire when no medical gas systems are present
- Rule does NOT fire for occupancies not in the trigger list
- Condition extractor picks up valve box keywords from text
- Severity is correctly set to High
"""

import pytest
from pathlib import Path
from src.parser.condition_extractor import ConditionExtractor, ProjectConditions, SeismicData
from src.parser.pdf_parser import PDFParser
from src.engine.rule_matcher import RuleMatcher
from src.engine.severity_scorer import Severity


DATA_DIR = Path(__file__).parent.parent / "data"
RULES_FILE = DATA_DIR / "hcai_rules.json"


@pytest.fixture
def matcher():
    return RuleMatcher(RULES_FILE)


def _hospital_with_zone_valves():
    c = ProjectConditions()
    c.occupancy_type = "Occupied Hospital"
    c.medical_gas_systems = ["zone valve", "oxygen manifold", "vacuum pump"]
    c.room_types = ["operating room", "patient room", "ICU"]
    c.seismic = SeismicData()
    return c


def _hospital_with_valve_box():
    c = ProjectConditions()
    c.occupancy_type = "Acute Care Hospital"
    c.medical_gas_systems = ["valve box", "medical air compressor"]
    c.room_types = ["patient room", "ICU"]
    c.seismic = SeismicData()
    return c


def _asc_with_zone_valves():
    # Extractor pulls both "zone valve" and "zone valve box" from text like
    # "zone valve boxes installed" — mirror that here.
    c = ProjectConditions()
    c.occupancy_type = "Ambulatory Surgery Center"
    c.medical_gas_systems = ["zone valve", "zone valve box", "oxygen manifold"]
    c.room_types = ["operating room", "procedure room"]
    c.seismic = SeismicData()
    return c


def _hospital_no_gas():
    """Hospital with no medical gas systems — RULE-024 should NOT fire."""
    c = ProjectConditions()
    c.occupancy_type = "Occupied Hospital"
    c.medical_gas_systems = []
    c.hvac_systems = ["AHU", "exhaust fan"]
    c.room_types = ["patient room"]
    c.seismic = SeismicData()
    return c


def _clinic_with_zone_valves():
    """Clinic is not in RULE-024 trigger occupancies — should NOT fire."""
    c = ProjectConditions()
    c.occupancy_type = "Clinic"
    c.medical_gas_systems = ["zone valve", "oxygen manifold"]
    c.room_types = ["procedure room"]
    c.seismic = SeismicData()
    return c


def _find_rule024(violations):
    return next((v for v in violations if v.rule_id == "RULE-024"), None)


# ---------------------------------------------------------------------------
# Rule trigger tests
# ---------------------------------------------------------------------------

class TestRule024Triggers:
    def test_fires_for_hospital_with_zone_valve(self, matcher):
        violations = matcher.match(_hospital_with_zone_valves())
        v = _find_rule024(violations)
        assert v is not None, "RULE-024 should fire for hospital with zone valve systems"

    def test_fires_for_hospital_with_valve_box(self, matcher):
        violations = matcher.match(_hospital_with_valve_box())
        v = _find_rule024(violations)
        assert v is not None, "RULE-024 should fire when 'valve box' is detected"

    def test_fires_for_ambulatory_surgery_center(self, matcher):
        violations = matcher.match(_asc_with_zone_valves())
        v = _find_rule024(violations)
        assert v is not None, "RULE-024 should fire for Ambulatory Surgery Center with zone valves"

    def test_does_not_fire_without_medical_gas(self, matcher):
        violations = matcher.match(_hospital_no_gas())
        v = _find_rule024(violations)
        assert v is None, "RULE-024 should NOT fire when no zone valve/valve box systems are present"

    def test_does_not_fire_for_clinic(self, matcher):
        violations = matcher.match(_clinic_with_zone_valves())
        v = _find_rule024(violations)
        assert v is None, "RULE-024 should NOT fire for Clinic (not in trigger occupancies)"


# ---------------------------------------------------------------------------
# Severity test
# ---------------------------------------------------------------------------

class TestRule024Severity:
    def test_severity_is_high(self, matcher):
        violations = matcher.match(_hospital_with_zone_valves())
        v = _find_rule024(violations)
        assert v is not None
        assert v.severity == Severity.HIGH, f"Expected High, got {v.severity}"


# ---------------------------------------------------------------------------
# Violation content tests
# ---------------------------------------------------------------------------

class TestRule024Content:
    def test_violation_text_mentions_clearance(self, matcher):
        violations = matcher.match(_hospital_with_zone_valves())
        v = _find_rule024(violations)
        assert v is not None
        text = v.violation_text.lower() + v.fix_text.lower()
        assert "36" in text, "Violation/fix text should mention 36-inch clearance"

    def test_violation_text_mentions_50_feet(self, matcher):
        violations = matcher.match(_hospital_with_zone_valves())
        v = _find_rule024(violations)
        assert v is not None
        text = v.violation_text.lower() + v.fix_text.lower()
        assert "50" in text, "Violation/fix text should mention 50-foot proximity limit"

    def test_code_references_include_nfpa99(self, matcher):
        violations = matcher.match(_hospital_with_zone_valves())
        v = _find_rule024(violations)
        assert v is not None
        citations_str = " ".join(v.code_references).lower()
        assert "nfpa 99" in citations_str, "RULE-024 citations should include NFPA 99"

    def test_code_references_include_can(self, matcher):
        violations = matcher.match(_hospital_with_zone_valves())
        v = _find_rule024(violations)
        assert v is not None
        citations_str = " ".join(v.code_references)
        assert "CAN 2-2024" in citations_str, "RULE-024 citations should include CAN 2-2024"

    def test_discipline_is_medical_gas(self, matcher):
        violations = matcher.match(_hospital_with_zone_valves())
        v = _find_rule024(violations)
        assert v is not None
        assert v.discipline == "Medical Gas"


# ---------------------------------------------------------------------------
# Condition extractor keyword tests
# ---------------------------------------------------------------------------

class TestConditionExtractorKeywords:
    """Verify that zone valve / valve box text is picked up by the extractor."""

    def _extract_from_text(self, text: str) -> ProjectConditions:
        parser = PDFParser()
        doc = parser.parse_text_input(text, source_name="test")
        return ConditionExtractor().extract(doc)

    def test_zone_valve_detected(self):
        text = "Occupied hospital project. Medical gas zone valve boxes (ZVBs) to be installed in corridors."
        cond = self._extract_from_text(text)
        assert any("zone valve" in s.lower() for s in cond.medical_gas_systems), (
            "Expected 'zone valve' in medical_gas_systems"
        )

    def test_valve_box_detected(self):
        text = "Acute care hospital. Install valve box at each patient care zone per NFPA 99."
        cond = self._extract_from_text(text)
        assert any("valve box" in s.lower() for s in cond.medical_gas_systems), (
            "Expected 'valve box' in medical_gas_systems"
        )

    def test_zvb_abbreviation_detected(self):
        text = "Hospital addition. ZVB locations shown on medical gas drawings."
        cond = self._extract_from_text(text)
        assert any("zvb" in s.lower() for s in cond.medical_gas_systems), (
            "Expected 'ZVB' abbreviation to be detected"
        )

    def test_end_to_end_rule024_from_text(self, matcher):
        """Full pipeline: text → conditions → RULE-024 fires."""
        text = (
            "Occupied Hospital, 120 licensed beds. Zone valve boxes provided in each "
            "patient wing corridor. Medical air compressor and oxygen manifold on roof. "
            "WAGD system included."
        )
        parser = PDFParser()
        doc = parser.parse_text_input(text, source_name="test-project")
        cond = ConditionExtractor().extract(doc)
        violations = matcher.match(cond)
        v = _find_rule024(violations)
        assert v is not None, "End-to-end: RULE-024 should fire from project text describing zone valve boxes"
