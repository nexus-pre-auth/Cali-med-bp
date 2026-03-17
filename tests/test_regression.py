"""
Regression and edge case tests.

Covers:
  - Mixed occupancy projects
  - Partial / sparse data scenarios
  - Projects with no seismic data
  - Clinic (non-hospital) project — verifies hospital-only rules don't fire
  - Text with no recognisable conditions
  - Surgical center subset of rules
"""

import pytest
from src.parser.pdf_parser import PDFParser
from src.parser.condition_extractor import ConditionExtractor, ProjectConditions, SeismicData
from src.engine.decision_engine import DecisionEngine
from src.engine.severity_scorer import Severity
from src.rag.generator import AHJCommentGenerator


parser = PDFParser()
extractor = ConditionExtractor()
engine = DecisionEngine()
generator = AHJCommentGenerator()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _review(text: str):
    doc = parser.parse_text_input(text)
    cond = extractor.extract(doc)
    violations = engine.evaluate(cond)
    enriched = generator.enrich(violations)
    return cond, violations, enriched


# ---------------------------------------------------------------------------
# Edge case: empty / unrecognisable document
# ---------------------------------------------------------------------------

class TestEmptyDocument:
    def test_no_crash_on_empty_text(self):
        cond, violations, enriched = _review("")
        assert cond.occupancy_type is None
        assert isinstance(violations, list)
        assert isinstance(enriched, list)

    def test_no_crash_on_noise_text(self):
        cond, violations, enriched = _review("Lorem ipsum dolor sit amet consectetur adipiscing elit.")
        assert isinstance(violations, list)


# ---------------------------------------------------------------------------
# Edge case: clinic (non-hospital)
# ---------------------------------------------------------------------------

class TestClinicProject:
    CLINIC_TEXT = """
    PROJECT: West Valley Medical Clinic
    FACILITY: Clinic — Group B occupancy
    Location: City of Fresno, Fresno County, California

    Construction Type: Type V-B
    SYSTEMS: hot water system, backflow preventer
    ROOMS: waiting room, patient room, toilet room
    """

    def test_occupancy_detected(self):
        cond, _, _ = _review(self.CLINIC_TEXT)
        assert cond.occupancy_type == "Clinic"

    def test_hospital_only_rules_do_not_fire(self):
        _, violations, _ = _review(self.CLINIC_TEXT)
        rule_ids = {v.rule_id for v in violations}
        # EES rule (RULE-004) is hospital-only
        assert "RULE-004" not in rule_ids
        # Medical gas rule (RULE-005) is hospital/surgical-only
        assert "RULE-005" not in rule_ids

    def test_no_critical_ees_violations(self):
        _, violations, _ = _review(self.CLINIC_TEXT)
        ees_critical = [
            v for v in violations
            if v.discipline == "Essential Electrical System"
            and v.severity == Severity.CRITICAL
        ]
        assert len(ees_critical) == 0


# ---------------------------------------------------------------------------
# Edge case: surgical center
# ---------------------------------------------------------------------------

class TestSurgicalCenter:
    TEXT = """
    PROJECT: Northgate Ambulatory Surgery Center
    FACILITY: Ambulatory Surgery Center
    Location: City of San Diego, San Diego County, California

    Construction Type: Type I-B, Fully Sprinklered (NFPA 13)
    SYSTEMS: AHU, HEPA filter, medical gas, oxygen manifold, vacuum pump, WAGD
    ROOMS: operating room, OR, procedure room, PACU, recovery room, clean utility

    SEISMIC DESIGN CATEGORY: D
    SDS: 1.0, SD1: 0.5, Importance Factor Ip: 1.5
    """

    def test_occupancy_detected(self):
        cond, _, _ = _review(self.TEXT)
        assert cond.occupancy_type == "Ambulatory Surgery Center"

    def test_or_ventilation_rule_fires(self):
        _, violations, _ = _review(self.TEXT)
        rule_ids = {v.rule_id for v in violations}
        assert "RULE-002" in rule_ids  # OR ventilation rule

    def test_medical_gas_rule_fires(self):
        _, violations, _ = _review(self.TEXT)
        rule_ids = {v.rule_id for v in violations}
        assert "RULE-005" in rule_ids


# ---------------------------------------------------------------------------
# Edge case: hospital with no seismic data
# ---------------------------------------------------------------------------

class TestHospitalNoSeismic:
    TEXT = """
    FACILITY: Occupied Hospital
    County: Alameda County
    ROOMS: patient room, ICU, operating room
    SYSTEMS: essential electrical, EES, generator
    """

    def test_seismic_rule_does_not_fire(self):
        _, violations, _ = _review(self.TEXT)
        rule_ids = {v.rule_id for v in violations}
        # Seismic rule requires zone D or E — should not fire without zone data
        assert "RULE-003" not in rule_ids

    def test_ees_rule_fires(self):
        _, violations, _ = _review(self.TEXT)
        rule_ids = {v.rule_id for v in violations}
        assert "RULE-004" in rule_ids


# ---------------------------------------------------------------------------
# Regression: severity ordering always consistent
# ---------------------------------------------------------------------------

class TestSeverityOrdering:
    TEXTS = [
        "Occupied Hospital seismic zone D operating room ICU essential electrical generator WAGD",
        "Ambulatory Surgery Center operating room HEPA filter medical gas vacuum pump",
        "Clinic patient room waiting room toilet room hot water",
        "",
    ]

    @pytest.mark.parametrize("text", TEXTS)
    def test_violations_always_sorted(self, text):
        _, violations, _ = _review(text)
        for i in range(len(violations) - 1):
            assert violations[i].severity.order <= violations[i + 1].severity.order

    @pytest.mark.parametrize("text", TEXTS)
    def test_enriched_always_has_content(self, text):
        _, violations, enriched = _review(text)
        for ev in enriched:
            assert ev.ahj_comment
            assert ev.fix_instructions
            assert ev.citations is not None


# ---------------------------------------------------------------------------
# Regression: rule IDs are unique and stable
# ---------------------------------------------------------------------------

class TestRuleDataIntegrity:
    def test_rule_ids_unique(self):
        import json
        from pathlib import Path
        rules = json.loads((Path(__file__).parent.parent / "data/hcai_rules.json").read_text())
        ids = [r["id"] for r in rules]
        assert len(ids) == len(set(ids)), "Duplicate rule IDs found"

    def test_all_rules_have_required_fields(self):
        import json
        from pathlib import Path
        rules = json.loads((Path(__file__).parent.parent / "data/hcai_rules.json").read_text())
        required = {"id", "discipline", "description", "code_references"}
        for rule in rules:
            missing = required - rule.keys()
            assert not missing, f"Rule {rule.get('id')} missing fields: {missing}"

    def test_severity_overrides_are_valid(self):
        import json
        from pathlib import Path
        valid = {s.value for s in Severity} | {None}
        rules = json.loads((Path(__file__).parent.parent / "data/hcai_rules.json").read_text())
        for rule in rules:
            assert rule.get("severity_override") in valid, \
                f"Invalid severity_override in rule {rule.get('id')}"
