"""
Tests for:
- Construction type and licensed_beds rule triggers (migration 3 + rule_matcher)
- PDFCleaner wiring in PDFParser (scanned page detection)
- Job cleanup and audit log trimming
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from src.engine.rule_matcher import RuleMatcher
from src.parser.condition_extractor import ProjectConditions, SeismicData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conditions(**kwargs) -> ProjectConditions:
    """Build minimal ProjectConditions with sensible defaults."""
    defaults = dict(
        occupancy_type="Occupied Hospital",
        construction_type=None,
        licensed_beds=None,
        hvac_systems=[],
        plumbing_systems=[],
        electrical_systems=[],
        medical_gas_systems=[],
        room_types=[],
        seismic=SeismicData(),
    )
    defaults.update(kwargs)
    return ProjectConditions(**defaults)


def _rule(**kwargs) -> dict:
    """Build a minimal rule dict."""
    defaults = dict(
        id="TEST-RULE",
        discipline="General",
        description="Test rule",
        violation_template="Violation for {construction_type} in {occupancy}",
        fix_template="Fix it",
        code_references=["CBC 2022"],
        severity_override="High",
        trigger_occupancies=[],
        trigger_systems=[],
        trigger_rooms=[],
        trigger_seismic_zones=[],
        trigger_construction_types=[],
        min_licensed_beds=None,
        is_active=True,
    )
    defaults.update(kwargs)
    return defaults


def _make_rules_json(tmp_path: Path, rules: list[dict]) -> Path:
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(rules))
    return p


# ---------------------------------------------------------------------------
# TestConstructionTypeFilter
# ---------------------------------------------------------------------------

class TestConstructionTypeFilter:

    def _matcher_with(self, tmp_path, rules):
        rules_file = _make_rules_json(tmp_path, rules)
        # Patch RuleMatcher to use JSON (bypass SQLite) by pointing at rules_file
        m = RuleMatcher.__new__(RuleMatcher)
        m._rules = rules
        return m

    def test_no_filter_matches_any_construction_type(self, tmp_path):
        rule = _rule(trigger_construction_types=[])
        matcher = self._matcher_with(tmp_path, [rule])
        conds = _conditions(construction_type="Type V-A")
        assert len(matcher.match(conds)) == 1

    def test_construction_type_filter_blocks_mismatch(self, tmp_path):
        rule = _rule(trigger_construction_types=["Type I-A", "Type I-B"])
        matcher = self._matcher_with(tmp_path, [rule])
        conds = _conditions(construction_type="Type V-A")
        assert len(matcher.match(conds)) == 0

    def test_construction_type_filter_allows_match(self, tmp_path):
        rule = _rule(trigger_construction_types=["Type I-A", "Type I-B"])
        matcher = self._matcher_with(tmp_path, [rule])
        conds = _conditions(construction_type="Type I-A, Fully Sprinklered")
        assert len(matcher.match(conds)) == 1

    def test_construction_type_substring_match(self, tmp_path):
        """Filter value 'I-A' should match 'Type I-A, Fully Sprinklered'."""
        rule = _rule(trigger_construction_types=["I-A"])
        matcher = self._matcher_with(tmp_path, [rule])
        conds = _conditions(construction_type="Type I-A, Fully Sprinklered")
        assert len(matcher.match(conds)) == 1

    def test_construction_type_filter_skipped_when_not_extracted(self, tmp_path):
        """When construction_type is None, construction_type filter is skipped (assume applies)."""
        rule = _rule(trigger_construction_types=["Type I-A"])
        matcher = self._matcher_with(tmp_path, [rule])
        conds = _conditions(construction_type=None)
        # Filter is skipped when construction_type is unknown
        assert len(matcher.match(conds)) == 1

    def test_multiple_construction_type_values(self, tmp_path):
        rule_wood = _rule(id="WOOD", trigger_construction_types=["Type III", "Type V"])
        rule_steel = _rule(id="STEEL", trigger_construction_types=["Type I", "Type II"])
        matcher = self._matcher_with(tmp_path, [rule_wood, rule_steel])
        conds_wood = _conditions(construction_type="Type V-B")
        conds_steel = _conditions(construction_type="Type II-A")
        wood_violations = [v.rule_id for v in matcher.match(conds_wood)]
        steel_violations = [v.rule_id for v in matcher.match(conds_steel)]
        assert "WOOD" in wood_violations
        assert "STEEL" not in wood_violations
        assert "STEEL" in steel_violations
        assert "WOOD" not in steel_violations


# ---------------------------------------------------------------------------
# TestLicensedBedsFilter
# ---------------------------------------------------------------------------

class TestLicensedBedsFilter:

    def _matcher_with(self, rules):
        m = RuleMatcher.__new__(RuleMatcher)
        m._rules = rules
        return m

    def test_no_threshold_matches_any_bed_count(self):
        rule = _rule(min_licensed_beds=None)
        matcher = self._matcher_with([rule])
        assert len(matcher.match(_conditions(licensed_beds=5))) == 1
        assert len(matcher.match(_conditions(licensed_beds=None))) == 1

    def test_threshold_blocks_below_minimum(self):
        rule = _rule(min_licensed_beds=100)
        matcher = self._matcher_with([rule])
        conds = _conditions(licensed_beds=80)
        assert len(matcher.match(conds)) == 0

    def test_threshold_allows_exact_minimum(self):
        rule = _rule(min_licensed_beds=100)
        matcher = self._matcher_with([rule])
        conds = _conditions(licensed_beds=100)
        assert len(matcher.match(conds)) == 1

    def test_threshold_allows_above_minimum(self):
        rule = _rule(min_licensed_beds=100)
        matcher = self._matcher_with([rule])
        conds = _conditions(licensed_beds=250)
        assert len(matcher.match(conds)) == 1

    def test_threshold_blocks_when_beds_unknown(self):
        """If beds not extracted, treat as 0 — rule does not apply."""
        rule = _rule(min_licensed_beds=100)
        matcher = self._matcher_with([rule])
        conds = _conditions(licensed_beds=None)
        assert len(matcher.match(conds)) == 0

    def test_trigger_string_includes_beds(self):
        """Trigger condition string should mention bed count."""
        rule = _rule(min_licensed_beds=100)
        matcher = self._matcher_with([rule])
        conds = _conditions(licensed_beds=200, construction_type="Type I-A")
        violations = matcher.match(conds)
        assert violations, "Expected at least one violation"
        assert "200" in violations[0].trigger_condition
        assert "beds" in violations[0].trigger_condition

    def test_trigger_string_includes_construction_type(self):
        rule = _rule()
        matcher = self._matcher_with([rule])
        conds = _conditions(construction_type="Type II-A", licensed_beds=50)
        violations = matcher.match(conds)
        assert violations
        assert "Type II-A" in violations[0].trigger_condition

    def test_licensed_beds_template_substitution(self):
        rule = _rule(violation_template="Facility has {licensed_beds} beds")
        matcher = self._matcher_with([rule])
        conds = _conditions(licensed_beds=150)
        violations = matcher.match(conds)
        assert violations
        assert "150" in violations[0].violation_text


# ---------------------------------------------------------------------------
# TestMigration3
# ---------------------------------------------------------------------------

class TestMigration3:

    def test_rule_construction_types_table_exists(self, tmp_path):
        import sqlite3
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "test.db")
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "rule_construction_types" in tables

    def test_min_licensed_beds_column_exists(self, tmp_path):
        import sqlite3
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "test.db")
        with sqlite3.connect(str(tmp_path / "test.db")) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(rules)").fetchall()]
        assert "min_licensed_beds" in cols

    def test_upsert_and_hydrate_construction_types(self, tmp_path):
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "test.db")
        rule = _rule(
            id="RULE-CT-001",
            trigger_construction_types=["Type I-A", "Type I-B"],
            min_licensed_beds=50,
        )
        store.upsert_rule(rule)
        fetched = store.get_by_id("RULE-CT-001")
        assert fetched is not None
        assert set(fetched["trigger_construction_types"]) == {"Type I-A", "Type I-B"}
        assert fetched["min_licensed_beds"] == 50

    def test_seed_preserves_new_rules(self, tmp_path):
        """Seeding from hcai_rules.json should load RULE-016/017/018."""
        from src.db.rules_store import RulesStore
        import config
        store = RulesStore(db_path=tmp_path / "seed_test.db")
        store.seed_from_json(config.HCAI_RULES_FILE)
        rule16 = store.get_by_id("RULE-016")
        rule17 = store.get_by_id("RULE-017")
        rule18 = store.get_by_id("RULE-018")
        assert rule16 is not None, "RULE-016 (wood-frame prohibition) should be seeded"
        assert rule17 is not None, "RULE-017 (100+ beds seismic) should be seeded"
        assert rule18 is not None, "RULE-018 (Type I-A fire resistance) should be seeded"
        assert len(rule16["trigger_construction_types"]) > 0
        assert rule17["min_licensed_beds"] == 100


# ---------------------------------------------------------------------------
# TestNewRulesIntegration
# ---------------------------------------------------------------------------

class TestNewRulesIntegration:
    """RULE-016/017/018 must fire when conditions match and stay silent otherwise."""

    @pytest.fixture
    def matcher(self, tmp_path):
        from src.db.rules_store import RulesStore
        import config
        store = RulesStore(db_path=tmp_path / "m.db")
        store.seed_from_json(config.HCAI_RULES_FILE)
        m = RuleMatcher.__new__(RuleMatcher)
        m._rules = store.get_all_active()
        return m

    def test_rule016_fires_for_wood_frame_hospital(self, matcher):
        conds = _conditions(
            occupancy_type="Occupied Hospital",
            construction_type="Type V-A",
        )
        ids = [v.rule_id for v in matcher.match(conds)]
        assert "RULE-016" in ids

    def test_rule016_silent_for_type_i(self, matcher):
        conds = _conditions(
            occupancy_type="Occupied Hospital",
            construction_type="Type I-A",
        )
        ids = [v.rule_id for v in matcher.match(conds)]
        assert "RULE-016" not in ids

    def test_rule017_fires_for_100plus_beds(self, matcher):
        conds = _conditions(
            occupancy_type="Occupied Hospital",
            licensed_beds=150,
        )
        ids = [v.rule_id for v in matcher.match(conds)]
        assert "RULE-017" in ids

    def test_rule017_silent_for_small_hospital(self, matcher):
        conds = _conditions(
            occupancy_type="Occupied Hospital",
            licensed_beds=50,
        )
        ids = [v.rule_id for v in matcher.match(conds)]
        assert "RULE-017" not in ids

    def test_rule018_fires_for_type_i_a(self, matcher):
        conds = _conditions(construction_type="Type I-A")
        ids = [v.rule_id for v in matcher.match(conds)]
        assert "RULE-018" in ids

    def test_rule018_silent_for_type_ii(self, matcher):
        conds = _conditions(construction_type="Type II-A")
        ids = [v.rule_id for v in matcher.match(conds)]
        assert "RULE-018" not in ids


# ---------------------------------------------------------------------------
# TestPDFParserScannedDetection
# ---------------------------------------------------------------------------

class TestPDFParserScannedDetection:

    def test_parse_text_input_not_flagged_as_scanned(self):
        from src.parser.pdf_parser import PDFParser
        parser = PDFParser()
        doc = parser.parse_text_input("This is normal text from a hospital plan.")
        # Inline text input should not set scanned_pages metadata
        assert doc.metadata.get("scanned_pages") is None or doc.metadata.get("scanned_pages") == []

    def test_cleaner_imported_without_error(self):
        """PDFCleaner should import cleanly (Pillow is installed)."""
        from src.preprocessing.pdf_cleaner import PDFCleaner
        cleaner = PDFCleaner()
        assert cleaner is not None


# ---------------------------------------------------------------------------
# TestJobCleanup
# ---------------------------------------------------------------------------

class TestJobCleanup:

    def test_cleanup_removes_old_completed_jobs(self, tmp_path):
        from src.db.job_store import SQLiteJobStore
        from src.api.models import JobStatus
        store = SQLiteJobStore(db_path=tmp_path / "cleanup.db")

        # Create a job and mark it complete
        job = store.create("Old Project")
        job.status = JobStatus.complete
        store.update(job)

        # Force the created_at to be old in the DB
        import sqlite3
        with sqlite3.connect(str(tmp_path / "cleanup.db")) as conn:
            conn.execute(
                "UPDATE jobs SET created_at = ? WHERE job_id = ?",
                ("2020-01-01T00:00:00+00:00", str(job.job_id)),
            )
            conn.commit()

        removed = store.cleanup_old_jobs(keep_days=30)
        assert removed == 1
        assert store.get(job.job_id) is None

    def test_cleanup_preserves_recent_jobs(self, tmp_path):
        from src.db.job_store import SQLiteJobStore
        from src.api.models import JobStatus
        store = SQLiteJobStore(db_path=tmp_path / "recent.db")

        job = store.create("Recent Project")
        job.status = JobStatus.complete
        store.update(job)

        removed = store.cleanup_old_jobs(keep_days=30)
        assert removed == 0
        assert store.get(job.job_id) is not None

    def test_cleanup_never_deletes_pending_jobs(self, tmp_path):
        from src.db.job_store import SQLiteJobStore
        import sqlite3
        store = SQLiteJobStore(db_path=tmp_path / "pending.db")

        job = store.create("Pending Project")
        # Force created_at to be old
        with sqlite3.connect(str(tmp_path / "pending.db")) as conn:
            conn.execute(
                "UPDATE jobs SET created_at = ? WHERE job_id = ?",
                ("2020-01-01T00:00:00+00:00", str(job.job_id)),
            )
            conn.commit()

        removed = store.cleanup_old_jobs(keep_days=30)
        assert removed == 0  # pending jobs are never deleted
        assert store.get(job.job_id) is not None


# ---------------------------------------------------------------------------
# TestAuditLogTrim
# ---------------------------------------------------------------------------

class TestAuditLogTrim:

    def _write_entries(self, path: Path, entries: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_trim_removes_old_entries(self, tmp_path, monkeypatch):
        from src.monitoring import audit as audit_mod
        log_path = tmp_path / "logs" / "audit.jsonl"
        monkeypatch.setattr(audit_mod, "_AUDIT_PATH", log_path)

        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=120)).isoformat()
        new_ts = now.isoformat()
        self._write_entries(log_path, [
            {"ts": old_ts, "event": "REVIEW_COMPLETE", "job_id": "a"},
            {"ts": new_ts, "event": "REVIEW_COMPLETE", "job_id": "b"},
        ])

        removed = audit_mod.trim_audit_log(keep_days=90)
        assert removed == 1

        remaining = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert len(remaining) == 1
        assert remaining[0]["job_id"] == "b"

    def test_trim_zero_when_all_recent(self, tmp_path, monkeypatch):
        from src.monitoring import audit as audit_mod
        log_path = tmp_path / "logs" / "audit.jsonl"
        monkeypatch.setattr(audit_mod, "_AUDIT_PATH", log_path)

        now = datetime.now(timezone.utc).isoformat()
        self._write_entries(log_path, [
            {"ts": now, "event": "REVIEW_COMPLETE", "job_id": "x"},
        ])

        removed = audit_mod.trim_audit_log(keep_days=90)
        assert removed == 0

    def test_trim_nonexistent_log_returns_zero(self, tmp_path, monkeypatch):
        from src.monitoring import audit as audit_mod
        monkeypatch.setattr(audit_mod, "_AUDIT_PATH", tmp_path / "nonexistent.jsonl")
        assert audit_mod.trim_audit_log(keep_days=90) == 0

    def test_trim_preserves_entries_with_bad_timestamps(self, tmp_path, monkeypatch):
        from src.monitoring import audit as audit_mod
        log_path = tmp_path / "logs" / "audit.jsonl"
        monkeypatch.setattr(audit_mod, "_AUDIT_PATH", log_path)

        self._write_entries(log_path, [
            {"ts": "not-a-date", "event": "MYSTERY"},
            {"ts": datetime.now(timezone.utc).isoformat(), "event": "RECENT"},
        ])

        removed = audit_mod.trim_audit_log(keep_days=90)
        assert removed == 0  # bad timestamp → kept, recent → kept
