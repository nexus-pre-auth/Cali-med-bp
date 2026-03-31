"""Tests for session metrics and API cost tracking."""

import time

from src.monitoring.metrics import SessionMetrics


class TestSessionMetrics:
    def test_timer_records_elapsed(self):
        m = SessionMetrics()
        with m.timer("test_stage"):
            time.sleep(0.01)
        assert m._timers["test_stage"] >= 10  # at least 10 ms

    def test_api_cost_zero_with_no_calls(self):
        m = SessionMetrics()
        assert m.api_cost_usd() == 0.0

    def test_api_cost_positive_with_calls(self):
        m = SessionMetrics()
        m.record_api_call(tokens_in=1000, tokens_out=500)
        assert m.api_cost_usd() > 0.0

    def test_summary_keys(self):
        m = SessionMetrics()
        m.record_api_call(tokens_in=100, tokens_out=50)
        s = m.summary()
        for key in ("session_id", "total_elapsed_ms", "violations_found",
                    "api_calls", "estimated_cost_usd"):
            assert key in s

    def test_record_violations(self):
        from src.engine.decision_engine import DecisionEngine
        from src.parser.condition_extractor import ProjectConditions, SeismicData
        from src.rag.generator import AHJCommentGenerator

        c = ProjectConditions()
        c.occupancy_type = "Occupied Hospital"
        c.seismic = SeismicData(seismic_zone="D")
        c.electrical_systems = ["essential electrical", "generator"]
        c.room_types = ["operating room", "ICU"]

        violations = DecisionEngine().evaluate(c)
        enriched = AHJCommentGenerator().enrich(violations)

        m = SessionMetrics()
        m.record_violations(enriched)
        assert m.violations_found == len(enriched)
        assert sum(m.violations_by_severity.values()) == len(enriched)

    def test_total_elapsed_increases(self):
        m = SessionMetrics()
        t0 = m.total_elapsed_ms()
        time.sleep(0.02)
        assert m.total_elapsed_ms() > t0
