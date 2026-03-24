"""
Tests for 2026 regulatory rules:

  RULE-025 — PIN 26-01 Telehealth Room Infrastructure (effective April 1, 2026)
  RULE-026 — NFPA 99-2024 IoT Medical Gas BAS Monitoring (effective Jan 1, 2026)
  RULE-027 — CBC 2025 Wildfire / WUI Construction Requirements (effective Jan 1, 2026)
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


def _find(violations, rule_id):
    return next((v for v in violations if v.rule_id == rule_id), None)


def _extract(text):
    parser = PDFParser()
    doc = parser.parse_text_input(text, source_name="test")
    return ConditionExtractor().extract(doc)


# ─────────────────────────────────────────────────────────────────────────────
# RULE-025: PIN 26-01 Telehealth Room Infrastructure
# ─────────────────────────────────────────────────────────────────────────────

class TestRule025Telehealth:

    def _hospital_with_telehealth(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.room_types = ["telehealth room", "patient room", "ICU"]
        c.seismic = SeismicData()
        return c

    def _clinic_with_telemedicine(self):
        c = ProjectConditions()
        c.occupancy_type = "Clinic"
        c.room_types = ["telemedicine room", "exam room"]
        c.seismic = SeismicData()
        return c

    def _hospital_no_telehealth(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.room_types = ["patient room", "ICU", "operating room"]
        c.seismic = SeismicData()
        return c

    def _skilled_nursing_no_telehealth_occupancy(self):
        # Skilled Nursing is not in RULE-025 trigger occupancies
        c = ProjectConditions()
        c.occupancy_type = "Skilled Nursing Facility"
        c.room_types = ["telehealth room"]
        c.seismic = SeismicData()
        return c

    def test_fires_for_hospital_with_telehealth_room(self, matcher):
        v = _find(matcher.match(self._hospital_with_telehealth()), "RULE-025")
        assert v is not None

    def test_fires_for_clinic_with_telemedicine(self, matcher):
        v = _find(matcher.match(self._clinic_with_telemedicine()), "RULE-025")
        assert v is not None

    def test_does_not_fire_without_telehealth_rooms(self, matcher):
        v = _find(matcher.match(self._hospital_no_telehealth()), "RULE-025")
        assert v is None

    def test_does_not_fire_for_skilled_nursing(self, matcher):
        v = _find(matcher.match(self._skilled_nursing_no_telehealth_occupancy()), "RULE-025")
        assert v is None

    def test_severity_is_medium(self, matcher):
        v = _find(matcher.match(self._hospital_with_telehealth()), "RULE-025")
        assert v is not None
        assert v.severity == Severity.MEDIUM

    def test_violation_mentions_dedicated_circuit(self, matcher):
        v = _find(matcher.match(self._hospital_with_telehealth()), "RULE-025")
        assert v is not None
        combined = (v.violation_text + v.fix_text).lower()
        assert "20" in combined and "circuit" in combined

    def test_violation_mentions_stc(self, matcher):
        v = _find(matcher.match(self._hospital_with_telehealth()), "RULE-025")
        assert v is not None
        assert "stc" in (v.violation_text + v.fix_text).lower()

    def test_citation_includes_pin_26_01(self, matcher):
        v = _find(matcher.match(self._hospital_with_telehealth()), "RULE-025")
        assert v is not None
        assert any("PIN 26-01" in c for c in v.code_references)

    def test_extractor_detects_telehealth_keyword(self):
        cond = _extract(
            "Occupied hospital renovation including three new telehealth rooms "
            "for remote patient consultations."
        )
        assert "telehealth" in cond.room_types or "telehealth room" in cond.room_types

    def test_extractor_detects_telemedicine_keyword(self):
        cond = _extract("Clinic addition with two telemedicine rooms for virtual visits.")
        assert any("telemedicine" in r for r in cond.room_types)

    def test_end_to_end_rule025(self, matcher):
        cond = _extract(
            "Occupied Hospital, 200 beds. New telehealth room suite for remote patient "
            "consultations. Audio/video equipment provided."
        )
        v = _find(matcher.match(cond), "RULE-025")
        assert v is not None, "End-to-end: RULE-025 should fire for hospital with telehealth rooms"


# ─────────────────────────────────────────────────────────────────────────────
# RULE-026: NFPA 99-2024 IoT Medical Gas BAS Monitoring
# ─────────────────────────────────────────────────────────────────────────────

class TestRule026IoTGas:

    def _hospital_with_zone_valves(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.medical_gas_systems = ["zone valve", "oxygen manifold", "vacuum pump"]
        c.seismic = SeismicData()
        return c

    def _asc_with_valve_boxes(self):
        c = ProjectConditions()
        c.occupancy_type = "Ambulatory Surgery Center"
        c.medical_gas_systems = ["valve box", "zone valve", "medical air compressor"]
        c.seismic = SeismicData()
        return c

    def _clinic_with_gas(self):
        # Clinic is not in RULE-026 trigger occupancies (only hospitals/surgical)
        c = ProjectConditions()
        c.occupancy_type = "Clinic"
        c.medical_gas_systems = ["zone valve", "oxygen manifold"]
        c.seismic = SeismicData()
        return c

    def _hospital_no_gas(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.medical_gas_systems = []
        c.seismic = SeismicData()
        return c

    def test_fires_for_hospital_with_zone_valves(self, matcher):
        v = _find(matcher.match(self._hospital_with_zone_valves()), "RULE-026")
        assert v is not None

    def test_fires_for_asc_with_valve_boxes(self, matcher):
        v = _find(matcher.match(self._asc_with_valve_boxes()), "RULE-026")
        assert v is not None

    def test_does_not_fire_for_clinic(self, matcher):
        v = _find(matcher.match(self._clinic_with_gas()), "RULE-026")
        assert v is None

    def test_does_not_fire_without_gas_systems(self, matcher):
        v = _find(matcher.match(self._hospital_no_gas()), "RULE-026")
        assert v is None

    def test_severity_is_high(self, matcher):
        v = _find(matcher.match(self._hospital_with_zone_valves()), "RULE-026")
        assert v is not None
        assert v.severity == Severity.HIGH

    def test_violation_mentions_bas(self, matcher):
        v = _find(matcher.match(self._hospital_with_zone_valves()), "RULE-026")
        assert v is not None
        combined = (v.violation_text + v.fix_text).lower()
        assert "bas" in combined or "building automation" in combined

    def test_citation_includes_nfpa_99_2024(self, matcher):
        v = _find(matcher.match(self._hospital_with_zone_valves()), "RULE-026")
        assert v is not None
        assert any("NFPA 99-2024" in c for c in v.code_references)

    def test_distinct_from_rule_024(self, matcher):
        """RULE-026 (BAS integration) is a different finding than RULE-024 (clearance)."""
        violations = matcher.match(self._hospital_with_zone_valves())
        ids = {v.rule_id for v in violations}
        assert "RULE-024" in ids, "RULE-024 (clearance) should also fire"
        assert "RULE-026" in ids, "RULE-026 (BAS monitoring) should fire independently"


# ─────────────────────────────────────────────────────────────────────────────
# RULE-027: CBC 2025 Wildfire / WUI Construction Requirements
# ─────────────────────────────────────────────────────────────────────────────

class TestRule027WUI:

    def _hospital_in_wui(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.wui_zone = True
        c.seismic = SeismicData()
        return c

    def _clinic_in_wui(self):
        c = ProjectConditions()
        c.occupancy_type = "Clinic"
        c.wui_zone = True
        c.seismic = SeismicData()
        return c

    def _hospital_not_wui(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.wui_zone = None   # not detected
        c.seismic = SeismicData()
        return c

    def _hospital_wui_false(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.wui_zone = False
        c.seismic = SeismicData()
        return c

    def test_fires_for_hospital_in_wui(self, matcher):
        v = _find(matcher.match(self._hospital_in_wui()), "RULE-027")
        assert v is not None

    def test_fires_for_any_occupancy_in_wui(self, matcher):
        # RULE-027 has empty trigger_occupancies → applies to all
        v = _find(matcher.match(self._clinic_in_wui()), "RULE-027")
        assert v is not None

    def test_does_not_fire_when_not_wui(self, matcher):
        v = _find(matcher.match(self._hospital_not_wui()), "RULE-027")
        assert v is None

    def test_does_not_fire_when_wui_false(self, matcher):
        v = _find(matcher.match(self._hospital_wui_false()), "RULE-027")
        assert v is None

    def test_severity_is_critical(self, matcher):
        v = _find(matcher.match(self._hospital_in_wui()), "RULE-027")
        assert v is not None
        assert v.severity == Severity.CRITICAL

    def test_violation_mentions_class_a_roofing(self, matcher):
        v = _find(matcher.match(self._hospital_in_wui()), "RULE-027")
        assert v is not None
        combined = (v.violation_text + v.fix_text).lower()
        assert "class a" in combined

    def test_violation_mentions_defensible_space(self, matcher):
        v = _find(matcher.match(self._hospital_in_wui()), "RULE-027")
        assert v is not None
        combined = (v.violation_text + v.fix_text).lower()
        assert "defensible space" in combined

    def test_citation_includes_cbc_2025_chapter_7a(self, matcher):
        v = _find(matcher.match(self._hospital_in_wui()), "RULE-027")
        assert v is not None
        assert any("7A" in c for c in v.code_references)

    # ── Condition extractor WUI detection tests ──

    def test_extractor_detects_wui(self):
        cond = _extract(
            "Occupied Hospital located in a Wildland-Urban Interface (WUI) zone "
            "per CALFire mapping. Fire Hazard Severity Zone: Very High."
        )
        assert cond.wui_zone is True

    def test_extractor_detects_fhsz(self):
        cond = _extract(
            "Project site is within a designated Very High Fire Hazard Severity Zone (FHSZ). "
            "CBC Chapter 7A applies."
        )
        assert cond.wui_zone is True

    def test_extractor_detects_defensible_space(self):
        cond = _extract(
            "Acute care hospital. Site plan provides 100-foot defensible space per Title 19."
        )
        assert cond.wui_zone is True

    def test_extractor_does_not_set_wui_without_keywords(self):
        cond = _extract(
            "Occupied Hospital, 120 beds, Sacramento County. Type I-A construction. "
            "Fully sprinklered per NFPA 13."
        )
        assert cond.wui_zone is None

    def test_end_to_end_rule027(self, matcher):
        cond = _extract(
            "Acute Care Hospital, 80 beds, Los Angeles County. Project is located in a "
            "State Responsibility Area with Very High Fire Hazard Severity Zone designation. "
            "Wildland-Urban Interface construction standards apply."
        )
        v = _find(matcher.match(cond), "RULE-027")
        assert v is not None, "End-to-end: RULE-027 should fire for WUI-zone hospital"
