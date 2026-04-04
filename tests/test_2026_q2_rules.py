"""
Tests for Q2 2026 rules:

  RULE-028 — EV Charging Fire Separation (CBC 2025 §406.9, effective Jan 1, 2026)
  RULE-029 — Embodied Carbon / LCA Report (CALGreen 2025 §A5.410.4)
  RULE-030 — Behavioral Health Patient Environment (CBC 2025 §1226.14, CAN 3-2024)
"""

from pathlib import Path

import pytest

from src.engine.rule_matcher import RuleMatcher
from src.engine.severity_scorer import Severity
from src.parser.condition_extractor import ConditionExtractor, ProjectConditions, SeismicData
from src.parser.pdf_parser import PDFParser

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
# RULE-028: EV Charging Fire Separation
# ─────────────────────────────────────────────────────────────────────────────

class TestRule028EVCharging:

    def _hospital_with_ev(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.electrical_systems = ["EV charging", "EVSE", "generator", "EES"]
        c.seismic = SeismicData()
        return c

    def _clinic_with_ev_system(self):
        c = ProjectConditions()
        c.occupancy_type = "Clinic"
        c.electrical_systems = ["electric vehicle charging", "panelboard"]
        c.seismic = SeismicData()
        return c

    def _hospital_no_ev(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.electrical_systems = ["generator", "essential electrical system", "ATS"]
        c.seismic = SeismicData()
        return c

    def test_fires_on_ev_charging_system(self, matcher):
        v = _find(matcher.match(self._hospital_with_ev()), "RULE-028")
        assert v is not None

    def test_fires_on_ev_system_any_occupancy(self, matcher):
        v = _find(matcher.match(self._clinic_with_ev_system()), "RULE-028")
        assert v is not None

    def test_does_not_fire_without_ev(self, matcher):
        v = _find(matcher.match(self._hospital_no_ev()), "RULE-028")
        assert v is None

    def test_severity_is_high(self, matcher):
        v = _find(matcher.match(self._hospital_with_ev()), "RULE-028")
        assert v is not None
        assert v.severity == Severity.HIGH

    def test_violation_mentions_fire_separation(self, matcher):
        v = _find(matcher.match(self._hospital_with_ev()), "RULE-028")
        combined = (v.violation_text + v.fix_text).lower()
        assert "fire" in combined and ("separat" in combined or "rated" in combined)

    def test_citation_includes_cbc_406_9(self, matcher):
        v = _find(matcher.match(self._hospital_with_ev()), "RULE-028")
        assert any("406.9" in c for c in v.code_references)

    def test_extractor_detects_ev_charging_keyword(self):
        cond = _extract(
            "Occupied Hospital. New parking structure with 40 EV charging "
            "stalls (EVSE Level 2) on ground floor."
        )
        ev_hits = [s for s in cond.electrical_systems
                   if "ev" in s.lower() or "evse" in s.lower() or "electric vehicle" in s.lower()]
        assert len(ev_hits) > 0

    def test_end_to_end_rule028(self, matcher):
        cond = _extract(
            "Occupied Hospital, 120 beds. New parking garage includes "
            "24 EVSE Level 2 electric vehicle charging stations adjacent to "
            "the hospital main entrance."
        )
        v = _find(matcher.match(cond), "RULE-028")
        assert v is not None, "End-to-end: RULE-028 should fire for hospital with EV charging"


# ─────────────────────────────────────────────────────────────────────────────
# RULE-029: Embodied Carbon / LCA Report
# ─────────────────────────────────────────────────────────────────────────────

class TestRule029EmbodiedCarbon:

    def _large_hospital(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.licensed_beds = 80
        c.seismic = SeismicData()
        return c

    def _large_asc(self):
        c = ProjectConditions()
        c.occupancy_type = "Ambulatory Surgery Center"
        c.licensed_beds = 40
        c.seismic = SeismicData()
        return c

    def _small_hospital(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.licensed_beds = 15   # below min_licensed_beds = 30
        c.seismic = SeismicData()
        return c

    def _clinic(self):
        # Clinic not in trigger_occupancies for RULE-029
        c = ProjectConditions()
        c.occupancy_type = "Clinic"
        c.seismic = SeismicData()
        return c

    def test_fires_for_large_hospital(self, matcher):
        v = _find(matcher.match(self._large_hospital()), "RULE-029")
        assert v is not None

    def test_fires_for_large_asc(self, matcher):
        v = _find(matcher.match(self._large_asc()), "RULE-029")
        assert v is not None

    def test_does_not_fire_for_small_hospital(self, matcher):
        v = _find(matcher.match(self._small_hospital()), "RULE-029")
        assert v is None

    def test_does_not_fire_for_clinic(self, matcher):
        v = _find(matcher.match(self._clinic()), "RULE-029")
        assert v is None

    def test_severity_is_medium(self, matcher):
        v = _find(matcher.match(self._large_hospital()), "RULE-029")
        assert v is not None
        assert v.severity == Severity.MEDIUM

    def test_violation_mentions_lca(self, matcher):
        v = _find(matcher.match(self._large_hospital()), "RULE-029")
        combined = (v.violation_text + v.fix_text).lower()
        assert "lca" in combined or "life cycle" in combined

    def test_violation_mentions_carbon(self, matcher):
        v = _find(matcher.match(self._large_hospital()), "RULE-029")
        combined = (v.violation_text + v.fix_text).lower()
        assert "carbon" in combined or "gwp" in combined or "co" in combined

    def test_citation_includes_calgreen(self, matcher):
        v = _find(matcher.match(self._large_hospital()), "RULE-029")
        assert any("CALGreen" in c or "A5.410" in c for c in v.code_references)


# ─────────────────────────────────────────────────────────────────────────────
# RULE-030: Behavioral Health Patient Environment
# ─────────────────────────────────────────────────────────────────────────────

class TestRule030BehavioralHealth:

    def _hospital_with_bh(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.room_types = ["behavioral health", "patient room", "ICU"]
        c.seismic = SeismicData()
        return c

    def _psych_facility(self):
        c = ProjectConditions()
        c.occupancy_type = "Psychiatric Facility"
        c.room_types = ["psychiatric", "seclusion room"]
        c.seismic = SeismicData()
        return c

    def _hospital_no_bh(self):
        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.room_types = ["operating room", "ICU", "patient room"]
        c.seismic = SeismicData()
        return c

    def _skilled_nursing(self):
        # SNF not in trigger_occupancies
        c = ProjectConditions()
        c.occupancy_type = "Skilled Nursing Facility"
        c.room_types = ["behavioral health"]
        c.seismic = SeismicData()
        return c

    def test_fires_for_hospital_with_bh_rooms(self, matcher):
        v = _find(matcher.match(self._hospital_with_bh()), "RULE-030")
        assert v is not None

    def test_fires_for_psychiatric_facility(self, matcher):
        v = _find(matcher.match(self._psych_facility()), "RULE-030")
        assert v is not None

    def test_does_not_fire_without_bh_rooms(self, matcher):
        v = _find(matcher.match(self._hospital_no_bh()), "RULE-030")
        assert v is None

    def test_does_not_fire_for_snf(self, matcher):
        v = _find(matcher.match(self._skilled_nursing()), "RULE-030")
        assert v is None

    def test_severity_is_high(self, matcher):
        v = _find(matcher.match(self._hospital_with_bh()), "RULE-030")
        assert v is not None
        assert v.severity == Severity.HIGH

    def test_violation_mentions_ligature(self, matcher):
        v = _find(matcher.match(self._hospital_with_bh()), "RULE-030")
        combined = (v.violation_text + v.fix_text).lower()
        assert "ligature" in combined

    def test_violation_mentions_room_size(self, matcher):
        v = _find(matcher.match(self._hospital_with_bh()), "RULE-030")
        combined = (v.violation_text + v.fix_text).lower()
        assert "120" in combined

    def test_citation_includes_cbc_1226_14(self, matcher):
        v = _find(matcher.match(self._hospital_with_bh()), "RULE-030")
        assert any("1226.14" in c for c in v.code_references)

    def test_citation_includes_can_3_2024(self, matcher):
        v = _find(matcher.match(self._hospital_with_bh()), "RULE-030")
        assert any("CAN 3-2024" in c or "CAN" in c for c in v.code_references)

    def test_extractor_detects_behavioral_health(self):
        cond = _extract(
            "Occupied Hospital. New 20-bed behavioral health unit with "
            "psychiatric patient rooms and one seclusion room."
        )
        bh_rooms = [r for r in cond.room_types if "behavioral" in r.lower() or "psychiatric" in r.lower() or "seclusion" in r.lower()]
        assert len(bh_rooms) > 0

    def test_extractor_detects_mental_health(self):
        cond = _extract("Acute Care Hospital with mental health wing on 3rd floor.")
        mh = [r for r in cond.room_types if "mental health" in r.lower()]
        assert len(mh) > 0

    def test_end_to_end_rule030(self, matcher):
        cond = _extract(
            "Occupied Hospital, 150 beds. Building program includes a 20-bed "
            "inpatient psychiatric unit with behavioral health patient rooms, "
            "group therapy rooms, and one seclusion room."
        )
        v = _find(matcher.match(cond), "RULE-030")
        assert v is not None, "End-to-end: RULE-030 should fire for hospital with behavioral health rooms"
