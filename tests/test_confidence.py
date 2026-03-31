"""Tests for confidence scorer."""

import pytest

from src.engine.confidence_scorer import ConfidenceReport, ConfidenceScorer
from src.engine.decision_engine import DecisionEngine
from src.engine.severity_scorer import Severity
from src.parser.condition_extractor import ProjectConditions, SeismicData


@pytest.fixture
def full_conditions():
    c = ProjectConditions()
    c.occupancy_type = "Occupied Hospital"
    c.construction_type = "Type I-A"
    c.sprinklered = True
    c.licensed_beds = 120
    c.county = "Sacramento"
    c.city = "Sacramento"
    c.seismic = SeismicData(seismic_zone="D", sds=1.2, sd1=0.6, importance_factor=1.5, site_class="D")
    c.hvac_systems = ["AHU", "HEPA filter"]
    c.electrical_systems = ["essential electrical", "generator"]
    c.plumbing_systems = ["hot water", "medical gas"]
    c.medical_gas_systems = ["oxygen manifold", "vacuum pump"]
    c.room_types = ["operating room", "ICU", "isolation room", "patient room"]
    return c


@pytest.fixture
def sparse_conditions():
    c = ProjectConditions()
    c.occupancy_type = "Clinic"
    c.seismic = SeismicData()
    return c


@pytest.fixture
def scorer():
    return ConfidenceScorer()


class TestExtractionConfidence:
    def test_full_conditions_high_score(self, scorer, full_conditions):
        score = scorer.score_extraction(full_conditions)
        assert score >= 0.75

    def test_sparse_conditions_low_score(self, scorer, sparse_conditions):
        score = scorer.score_extraction(sparse_conditions)
        assert score < 0.5

    def test_score_in_range(self, scorer, full_conditions):
        score = scorer.score_extraction(full_conditions)
        assert 0.0 <= score <= 1.0


class TestRuleMatchConfidence:
    def test_high_overlap(self, scorer):
        from src.engine.rule_matcher import MatchedViolation
        v = MatchedViolation(
            rule_id="RULE-001",
            discipline="Infection Control",
            severity=Severity.CRITICAL,
            trigger_condition="Occupied Hospital",
            description="isolation room negative pressure airborne infection control",
            violation_text="isolation room",
            fix_text="fix",
            code_references=["Title 24 Part 4"],
        )
        text = "Project includes isolation room negative pressure design for airborne infection control"
        score = scorer.score_rule_match(v, text)
        assert score > 0.4

    def test_empty_text_neutral(self, scorer):
        from src.engine.rule_matcher import MatchedViolation
        v = MatchedViolation(
            rule_id="RULE-001",
            discipline="Infection Control",
            severity=Severity.CRITICAL,
            trigger_condition="Occupied Hospital",
            description="isolation room",
            violation_text="x",
            fix_text="y",
            code_references=[],
        )
        score = scorer.score_rule_match(v, "")
        assert score == 0.5


class TestViolationScoring:
    def test_returns_pairs(self, scorer, full_conditions):
        engine = DecisionEngine()
        violations = engine.evaluate(full_conditions)
        full_text = "occupied hospital operating room ICU isolation room seismic zone D"
        pairs = scorer.score_violations(violations, full_text, full_conditions)
        assert len(pairs) == len(violations)

    def test_confidence_report_structure(self, scorer, full_conditions):
        engine = DecisionEngine()
        violations = engine.evaluate(full_conditions)[:1]
        pairs = scorer.score_violations(violations, "test text", full_conditions)
        _, report = pairs[0]
        assert isinstance(report, ConfidenceReport)
        assert 0.0 <= report.overall <= 1.0
        assert report.label in ("High", "Medium", "Low")

    def test_overall_is_weighted(self, scorer, full_conditions):
        engine = DecisionEngine()
        violations = engine.evaluate(full_conditions)[:1]
        pairs = scorer.score_violations(violations, "occupied hospital", full_conditions)
        _, report = pairs[0]
        expected = 0.5 * report.extraction + 0.5 * report.rule_match
        assert abs(report.overall - expected) < 1e-6
