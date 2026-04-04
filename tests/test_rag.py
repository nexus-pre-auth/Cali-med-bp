"""Tests for the RAG generator (fallback mode — no Claude API required)."""

import pytest

from src.engine.decision_engine import DecisionEngine
from src.engine.severity_scorer import Severity
from src.parser.condition_extractor import ProjectConditions, SeismicData
from src.rag.generator import AHJCommentGenerator


@pytest.fixture
def hospital_conditions():
    cond = ProjectConditions()
    cond.occupancy_type = "Occupied Hospital"
    cond.seismic = SeismicData(seismic_zone="D", sds=1.2)
    cond.electrical_systems = ["essential electrical", "EES", "generator", "critical branch"]
    cond.medical_gas_systems = ["oxygen manifold", "vacuum pump", "WAGD"]
    cond.room_types = ["operating room", "ICU", "isolation room", "patient room"]
    return cond


@pytest.fixture
def violations(hospital_conditions):
    engine = DecisionEngine()
    return engine.evaluate(hospital_conditions)


@pytest.fixture
def enriched(violations):
    # Use fallback mode (no KB, no API key)
    generator = AHJCommentGenerator(knowledge_base=None, api_key=None)
    return generator.enrich(violations)


class TestAHJCommentGenerator:
    def test_returns_enriched_violations(self, enriched, violations):
        assert len(enriched) == len(violations)

    def test_all_have_ahj_comments(self, enriched):
        for ev in enriched:
            assert ev.ahj_comment
            assert len(ev.ahj_comment) > 10

    def test_all_have_fix_instructions(self, enriched):
        for ev in enriched:
            assert ev.fix_instructions
            assert len(ev.fix_instructions) > 10

    def test_all_have_citations(self, enriched):
        for ev in enriched:
            assert len(ev.citations) > 0

    def test_critical_comment_contains_rule_id(self, enriched):
        critical_evs = [ev for ev in enriched if ev.violation.severity == Severity.CRITICAL]
        assert len(critical_evs) > 0
        for ev in critical_evs:
            assert ev.violation.rule_id in ev.ahj_comment
