"""Tests for the decision engine and severity scorer."""

from pathlib import Path

import pytest

from src.engine.decision_engine import DecisionEngine
from src.engine.rule_matcher import RuleMatcher
from src.engine.severity_scorer import Severity, score_violation
from src.parser.condition_extractor import ProjectConditions, SeismicData

DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture
def hospital_conditions():
    cond = ProjectConditions()
    cond.occupancy_type = "Occupied Hospital"
    cond.sprinklered = True
    cond.seismic = SeismicData(seismic_zone="D", sds=1.2, sd1=0.6, importance_factor=1.5)
    cond.hvac_systems = ["AHU", "HEPA filter", "exhaust fan"]
    cond.electrical_systems = ["essential electrical", "EES", "generator", "critical branch", "life safety branch"]
    cond.medical_gas_systems = ["oxygen manifold", "vacuum pump", "WAGD"]
    cond.room_types = ["operating room", "ICU", "isolation room", "patient room", "pharmacy", "sterile processing"]
    cond.county = "Sacramento"
    return cond


@pytest.fixture
def engine():
    return DecisionEngine()


class TestSeverityScorer:
    def test_infection_control_critical(self):
        sev = score_violation("Infection Control", "Occupied Hospital", "Title 24 Part 2", "isolation room life safety")
        assert sev == Severity.CRITICAL

    def test_hvac_high(self):
        sev = score_violation("HVAC", "General", "ASHRAE 170", "ventilation air changes operating room")
        assert sev == Severity.HIGH

    def test_low_severity(self):
        sev = score_violation("Landscaping", "General", "CBC Chapter 3", "decorative paving pattern")
        assert sev == Severity.LOW


class TestDecisionEngine:
    def test_returns_violations(self, engine, hospital_conditions):
        violations = engine.evaluate(hospital_conditions)
        assert len(violations) > 0

    def test_sorted_by_severity(self, engine, hospital_conditions):
        violations = engine.evaluate(hospital_conditions)
        for i in range(len(violations) - 1):
            assert violations[i].severity.order <= violations[i + 1].severity.order

    def test_critical_violations_present(self, engine, hospital_conditions):
        violations = engine.evaluate(hospital_conditions)
        severities = [v.severity for v in violations]
        assert Severity.CRITICAL in severities

    def test_summary_counts(self, engine, hospital_conditions):
        violations = engine.evaluate(hospital_conditions)
        summary = engine.summary(violations)
        assert summary["total"] == len(violations)
        assert sum(summary["by_severity"].values()) == summary["total"]

    def test_seismic_rule_triggered(self, engine, hospital_conditions):
        violations = engine.evaluate(hospital_conditions)
        rule_ids = [v.rule_id for v in violations]
        assert "RULE-003" in rule_ids  # Seismic anchorage rule

    def test_no_seismic_rule_without_zone(self, engine):
        cond = ProjectConditions()
        cond.occupancy_type = "Occupied Hospital"
        cond.seismic = SeismicData(seismic_zone="A")  # Low seismic zone — rule shouldn't fire
        violations = engine.evaluate(cond)
        rule_ids = [v.rule_id for v in violations]
        assert "RULE-003" not in rule_ids


class TestRuleMatcher:
    def test_loads_rules(self):
        matcher = RuleMatcher(DATA_DIR / "hcai_rules.json")
        assert len(matcher._rules) > 0

    def test_occupancy_filter(self):
        matcher = RuleMatcher(DATA_DIR / "hcai_rules.json")
        cond = ProjectConditions()
        cond.occupancy_type = "Clinic"
        cond.seismic = SeismicData()
        violations = matcher.match(cond)
        # Rules specific to Occupied Hospital should not fire for Clinic
        rule_ids = [v.rule_id for v in violations]
        assert "RULE-004" not in rule_ids  # EES rule is hospital-only
