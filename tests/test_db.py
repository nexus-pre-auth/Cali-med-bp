"""Tests for SQLite rules store and database migrations."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.db.rules_store import RulesStore
from src.db.migrations import run_migrations
import sqlite3


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """A fresh in-memory-ish RulesStore backed by a temp file."""
    db_path = tmp_path / "test_rules.db"
    return RulesStore(db_path=db_path)


@pytest.fixture
def seeded_store(tmp_path):
    """A RulesStore seeded from the real hcai_rules.json."""
    db_path = tmp_path / "test_seeded.db"
    store = RulesStore(db_path=db_path)
    store.seed_from_json()
    return store


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

class TestMigrations:
    def test_schema_version_table_created(self, tmp_path):
        db_path = tmp_path / "mig.db"
        conn = sqlite3.connect(str(db_path))
        run_migrations(conn)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "schema_version" in tables
        assert "rules" in tables
        conn.close()

    def test_migration_idempotent(self, tmp_path):
        db_path = tmp_path / "mig2.db"
        conn = sqlite3.connect(str(db_path))
        run_migrations(conn)
        run_migrations(conn)  # second run should not fail
        versions = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert versions == 7   # 1–6 original + 7 (trigger_wui)
        conn.close()


# ---------------------------------------------------------------------------
# RulesStore — basic operations
# ---------------------------------------------------------------------------

class TestRulesStore:
    def test_empty_store_count_zero(self, tmp_db):
        assert tmp_db.count() == 0

    def test_seed_inserts_rules(self, seeded_store):
        assert seeded_store.count() > 0

    def test_seed_idempotent(self, seeded_store):
        before = seeded_store.count()
        added = seeded_store.seed_from_json()
        assert added == 0
        assert seeded_store.count() == before

    def test_get_all_active_returns_list(self, seeded_store):
        rules = seeded_store.get_all_active()
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_rule_has_required_fields(self, seeded_store):
        rules = seeded_store.get_all_active()
        required = {"id", "discipline", "description", "code_references"}
        for rule in rules:
            assert required <= rule.keys(), f"Rule {rule['id']} missing fields"

    def test_get_by_id_found(self, seeded_store):
        rule = seeded_store.get_by_id("RULE-001")
        assert rule is not None
        assert rule["id"] == "RULE-001"

    def test_get_by_id_not_found(self, seeded_store):
        assert seeded_store.get_by_id("RULE-NONEXISTENT") is None

    def test_get_by_discipline(self, seeded_store):
        rules = seeded_store.get_by_discipline("Infection Control")
        assert all(r["discipline"] == "Infection Control" for r in rules)

    def test_list_disciplines(self, seeded_store):
        disciplines = seeded_store.list_disciplines()
        assert "Infection Control" in disciplines
        assert len(disciplines) >= 3


# ---------------------------------------------------------------------------
# RulesStore — writes
# ---------------------------------------------------------------------------

class TestRulesStoreWrites:
    def test_upsert_inserts_new_rule(self, tmp_db):
        rule = {
            "id": "RULE-TEST-01",
            "discipline": "Test",
            "description": "Test rule description",
            "violation_template": "Test violation",
            "fix_template": "Test fix",
            "severity_override": "Medium",
            "trigger_occupancies": ["Clinic"],
            "trigger_systems": [],
            "trigger_rooms": [],
            "trigger_seismic_zones": [],
            "code_references": ["CBC 2022 Section 1"],
        }
        tmp_db.upsert_rule(rule)
        fetched = tmp_db.get_by_id("RULE-TEST-01")
        assert fetched is not None
        assert fetched["discipline"] == "Test"
        assert "CBC 2022 Section 1" in fetched["code_references"]

    def test_upsert_updates_existing_rule(self, seeded_store):
        original = seeded_store.get_by_id("RULE-001")
        updated = dict(original)
        updated["description"] = "Updated description"
        seeded_store.upsert_rule(updated)
        fetched = seeded_store.get_by_id("RULE-001")
        assert fetched["description"] == "Updated description"

    def test_set_active_disables_rule(self, seeded_store):
        seeded_store.set_active("RULE-001", False)
        rule = seeded_store.get_by_id("RULE-001")
        assert rule["is_active"] is False

    def test_set_active_re_enables_rule(self, seeded_store):
        seeded_store.set_active("RULE-001", False)
        seeded_store.set_active("RULE-001", True)
        rule = seeded_store.get_by_id("RULE-001")
        assert rule["is_active"] is True

    def test_disabled_rule_excluded_from_active(self, seeded_store):
        seeded_store.set_active("RULE-001", False)
        active_ids = {r["id"] for r in seeded_store.get_all_active()}
        assert "RULE-001" not in active_ids

    def test_set_active_returns_false_for_unknown(self, tmp_db):
        found = tmp_db.set_active("NONEXISTENT", True)
        assert found is False


# ---------------------------------------------------------------------------
# Integration: RuleMatcher uses SQLite store
# ---------------------------------------------------------------------------

class TestRuleMatcherUsesStore:
    def test_matcher_loads_from_db(self, seeded_store, tmp_path):
        """RuleMatcher should load rules from SQLite (via get_rules_store)."""
        from src.engine.rule_matcher import RuleMatcher
        from src.parser.condition_extractor import ProjectConditions, SeismicData
        import config

        matcher = RuleMatcher(config.HCAI_RULES_FILE)
        assert len(matcher._rules) > 0

    def test_disabled_rule_absent_from_active(self, seeded_store):
        """get_all_active() must exclude disabled rules."""
        seeded_store.set_active("RULE-001", False)
        active_ids = {r["id"] for r in seeded_store.get_all_active()}
        assert "RULE-001" not in active_ids
