"""Tests for audit logging."""

from __future__ import annotations

import json

import pytest

import src.monitoring.audit as audit_module


@pytest.fixture(autouse=True)
def tmp_audit(tmp_path, monkeypatch):
    """Redirect audit log to a temp file for each test."""
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_module, "_AUDIT_PATH", audit_path)
    return audit_path


class TestAuditWriter:
    def test_log_review_submitted(self, tmp_audit):
        audit_module.log_review_submitted(
            job_id="job-123",
            project_name="Test Hospital",
            source="api_text",
        )
        lines = tmp_audit.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "REVIEW_SUBMITTED"
        assert record["job_id"] == "job-123"
        assert record["project_name"] == "Test Hospital"
        assert "ts" in record

    def test_log_review_complete(self, tmp_audit):
        audit_module.log_review_complete(
            job_id="job-123",
            project_name="Test Hospital",
            occupancy_type="Occupied Hospital",
            total_violations=5,
            by_severity={"Critical": 2, "High": 3},
            elapsed_ms=1234.5,
            extraction_confidence=0.87,
        )
        record = json.loads(tmp_audit.read_text().strip())
        assert record["event"] == "REVIEW_COMPLETE"
        assert record["total_violations"] == 5
        assert record["extraction_confidence"] == 0.87

    def test_log_review_failed(self, tmp_audit):
        audit_module.log_review_failed("job-999", "Bad Project", "Something went wrong")
        record = json.loads(tmp_audit.read_text().strip())
        assert record["event"] == "REVIEW_FAILED"
        assert record["error"] == "Something went wrong"

    def test_log_violation_detected(self, tmp_audit):
        audit_module.log_violation_detected(
            job_id="job-123",
            rule_id="RULE-001",
            discipline="Infection Control",
            severity="Critical",
            trigger_condition="Occupied Hospital",
            confidence=0.91,
        )
        record = json.loads(tmp_audit.read_text().strip())
        assert record["event"] == "VIOLATION_DETECTED"
        assert record["rule_id"] == "RULE-001"
        assert record["severity"] == "Critical"

    def test_multiple_entries_appended(self, tmp_audit):
        for i in range(3):
            audit_module.log_review_submitted(f"job-{i}", f"Project {i}", "cli")
        lines = [line for line in tmp_audit.read_text().strip().split("\n") if line]
        assert len(lines) == 3

    def test_all_entries_valid_json(self, tmp_audit):
        audit_module.log_review_submitted("j1", "P1", "cli")
        audit_module.log_review_complete("j1", "P1", None, 0, {}, 100.0, 0.5)
        for line in tmp_audit.read_text().strip().split("\n"):
            json.loads(line)  # should not raise


class TestAuditReader:
    def test_read_returns_empty_when_no_log(self, tmp_audit):
        result = audit_module.read_audit_log()
        assert result == []

    def test_read_returns_all_entries(self, tmp_audit):
        audit_module.log_review_submitted("j1", "P1", "cli")
        audit_module.log_review_submitted("j2", "P2", "api_text")
        result = audit_module.read_audit_log()
        assert len(result) == 2

    def test_filter_by_event(self, tmp_audit):
        audit_module.log_review_submitted("j1", "P1", "cli")
        audit_module.log_review_complete("j1", "P1", None, 0, {}, 100.0, 0.5)
        result = audit_module.read_audit_log(event_filter="REVIEW_SUBMITTED")
        assert all(r["event"] == "REVIEW_SUBMITTED" for r in result)
        assert len(result) == 1

    def test_filter_by_job_id(self, tmp_audit):
        audit_module.log_review_submitted("job-AAA", "P1", "cli")
        audit_module.log_review_submitted("job-BBB", "P2", "cli")
        result = audit_module.read_audit_log(job_id_filter="job-AAA")
        assert len(result) == 1
        assert result[0]["job_id"] == "job-AAA"

    def test_limit_respected(self, tmp_audit):
        for i in range(10):
            audit_module.log_review_submitted(f"job-{i}", f"P{i}", "cli")
        result = audit_module.read_audit_log(limit=3)
        assert len(result) == 3

    def test_most_recent_first(self, tmp_audit):
        audit_module.log_review_submitted("job-1", "First", "cli")
        audit_module.log_review_submitted("job-2", "Second", "cli")
        result = audit_module.read_audit_log()
        # Most recent (job-2) should be first
        assert result[0]["job_id"] == "job-2"
