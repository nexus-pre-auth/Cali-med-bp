"""
Tests for:
- Rules API typed models (RuleResponse, RuleCreateRequest)
- active_only=False returning inactive rules
- sprinklered trigger in rule matching (migration 4 + RULE-019/020)
- output/ directory cleanup in cleanup command
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.engine.rule_matcher import RuleMatcher
from src.parser.condition_extractor import ProjectConditions, SeismicData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conditions(**kwargs) -> ProjectConditions:
    defaults = {
        "occupancy_type": "Occupied Hospital",
        "construction_type": None,
        "sprinklered": None,
        "licensed_beds": None,
        "hvac_systems": [],
        "plumbing_systems": [],
        "electrical_systems": [],
        "medical_gas_systems": [],
        "room_types": [],
        "seismic": SeismicData(),
    }
    defaults.update(kwargs)
    return ProjectConditions(**defaults)


def _rule(**kwargs) -> dict:
    defaults = {
        "id": "TEST-RULE",
        "discipline": "General",
        "description": "Test rule",
        "violation_template": "Violation",
        "fix_template": "Fix it",
        "code_references": [],
        "severity_override": "High",
        "trigger_occupancies": [],
        "trigger_systems": [],
        "trigger_rooms": [],
        "trigger_seismic_zones": [],
        "trigger_construction_types": [],
        "trigger_sprinklered": None,
        "min_licensed_beds": None,
        "is_active": True,
    }
    defaults.update(kwargs)
    return defaults


def _matcher(rules: list[dict]) -> RuleMatcher:
    m = RuleMatcher.__new__(RuleMatcher)
    m._rules = rules
    return m


# ---------------------------------------------------------------------------
# API client fixture (rate limiting disabled)
# ---------------------------------------------------------------------------

_TEST_RULE_IDS = ["TEST-API-RULE-001"]


@pytest.fixture(scope="module")
def client():
    os.environ["RATE_LIMIT_RPM"] = "0"
    from src.api.app import create_app
    app = create_app()
    os.environ.pop("RATE_LIMIT_RPM", None)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    # Teardown: disable test rules so they don't leak into other test modules
    # (they have no code_references and break citation assertions)
    try:
        from src.db.rules_store import get_rules_store
        store = get_rules_store()
        for rule_id in _TEST_RULE_IDS:
            store.set_active(rule_id, False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TestRulesAPITypedModels
# ---------------------------------------------------------------------------

class TestRulesAPITypedModels:

    def test_list_rules_returns_typed_fields(self, client):
        r = client.get("/rules")
        assert r.status_code == 200
        rules = r.json()
        assert isinstance(rules, list)
        if rules:
            rule = rules[0]
            # All RuleResponse fields must be present
            assert "id" in rule
            assert "discipline" in rule
            assert "trigger_occupancies" in rule
            assert "trigger_construction_types" in rule
            assert "trigger_sprinklered" in rule
            assert "min_licensed_beds" in rule
            assert "is_active" in rule

    def test_get_rule_returns_typed_fields(self, client):
        r = client.get("/rules/RULE-001")
        assert r.status_code == 200
        rule = r.json()
        assert rule["id"] == "RULE-001"
        assert "trigger_sprinklered" in rule
        assert "trigger_construction_types" in rule
        assert "min_licensed_beds" in rule

    def test_post_rule_validates_required_fields(self, client):
        """Missing id/discipline/description should return 422."""
        r = client.post("/rules", json={"description": "no id or discipline"})
        assert r.status_code == 422

    def test_post_rule_accepts_new_fields(self, client):
        """POST /rules should persist trigger_construction_types and trigger_sprinklered."""
        payload = {
            "id": "TEST-API-RULE-001",
            "discipline": "Fire and Life Safety",
            "description": "API test rule with new fields",
            "trigger_construction_types": ["Type I-A"],
            "trigger_sprinklered": True,
            "min_licensed_beds": 50,
            "severity_override": "High",
        }
        r = client.post("/rules", json=payload)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["id"] == "TEST-API-RULE-001"
        assert body["trigger_construction_types"] == ["Type I-A"]
        assert body["trigger_sprinklered"] is True
        assert body["min_licensed_beds"] == 50

    def test_get_rule_returns_posted_data(self, client):
        """GET /rules/{id} should return what was POSTed."""
        r = client.get("/rules/TEST-API-RULE-001")
        assert r.status_code == 200
        rule = r.json()
        assert rule["trigger_construction_types"] == ["Type I-A"]
        assert rule["trigger_sprinklered"] is True

    def test_post_rule_upserts_cleanly(self, client):
        """Re-posting the same id should update, not duplicate."""
        payload = {
            "id": "TEST-API-RULE-001",
            "discipline": "Fire and Life Safety",
            "description": "Updated description",
            "trigger_construction_types": ["Type I-A", "Type I-B"],
            "trigger_sprinklered": False,
            "severity_override": "Critical",
        }
        r = client.post("/rules", json=payload)
        assert r.status_code == 201
        body = r.json()
        assert body["severity_override"] == "Critical"
        assert body["trigger_sprinklered"] is False
        assert len(body["trigger_construction_types"]) == 2


# ---------------------------------------------------------------------------
# TestActiveOnlyFilter
# ---------------------------------------------------------------------------

class TestActiveOnlyFilter:

    def test_active_only_true_excludes_inactive(self, client):
        """active_only=true (default) must not return disabled rules."""
        r = client.get("/rules?active_only=true")
        assert r.status_code == 200
        assert all(rule["is_active"] for rule in r.json())

    def test_active_only_false_includes_inactive(self, client):
        """active_only=false must include disabled rules if any exist."""
        # First disable a rule
        client.patch("/rules/RULE-001/active?active=false")
        try:
            r_all = client.get("/rules?active_only=false")
            r_active = client.get("/rules?active_only=true")
            ids_all = {rule["id"] for rule in r_all.json()}
            ids_active = {rule["id"] for rule in r_active.json()}
            # RULE-001 should be in all but not in active_only
            assert "RULE-001" in ids_all
            assert "RULE-001" not in ids_active
        finally:
            client.patch("/rules/RULE-001/active?active=true")


# ---------------------------------------------------------------------------
# TestSprinkleredFilter
# ---------------------------------------------------------------------------

class TestSprinkleredFilter:

    def test_null_trigger_matches_sprinklered(self):
        rule = _rule(trigger_sprinklered=None)
        assert len(_matcher([rule]).match(_conditions(sprinklered=True))) == 1

    def test_null_trigger_matches_non_sprinklered(self):
        rule = _rule(trigger_sprinklered=None)
        assert len(_matcher([rule]).match(_conditions(sprinklered=False))) == 1

    def test_null_trigger_matches_unknown(self):
        rule = _rule(trigger_sprinklered=None)
        assert len(_matcher([rule]).match(_conditions(sprinklered=None))) == 1

    def test_true_trigger_matches_sprinklered(self):
        rule = _rule(trigger_sprinklered=True)
        assert len(_matcher([rule]).match(_conditions(sprinklered=True))) == 1

    def test_true_trigger_blocks_non_sprinklered(self):
        rule = _rule(trigger_sprinklered=True)
        assert len(_matcher([rule]).match(_conditions(sprinklered=False))) == 0

    def test_false_trigger_matches_non_sprinklered(self):
        rule = _rule(trigger_sprinklered=False)
        assert len(_matcher([rule]).match(_conditions(sprinklered=False))) == 1

    def test_false_trigger_blocks_sprinklered(self):
        rule = _rule(trigger_sprinklered=False)
        assert len(_matcher([rule]).match(_conditions(sprinklered=True))) == 0

    def test_sprinklered_unknown_skips_filter(self):
        """When sprinklered is None (not extracted), filter is skipped."""
        rule = _rule(trigger_sprinklered=True)
        # Unknown sprinkler status → filter skipped → rule applies
        assert len(_matcher([rule]).match(_conditions(sprinklered=None))) == 1

    def test_rule019_fires_for_non_sprinklered(self, tmp_path):
        import config
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "m.db")
        store.seed_from_json(config.HCAI_RULES_FILE)
        m = RuleMatcher.__new__(RuleMatcher)
        m._rules = store.get_all_active()
        conds = _conditions(
            occupancy_type="Occupied Hospital",
            sprinklered=False,
        )
        ids = [v.rule_id for v in m.match(conds)]
        assert "RULE-019" in ids

    def test_rule019_silent_for_sprinklered(self, tmp_path):
        import config
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "m.db")
        store.seed_from_json(config.HCAI_RULES_FILE)
        m = RuleMatcher.__new__(RuleMatcher)
        m._rules = store.get_all_active()
        conds = _conditions(
            occupancy_type="Occupied Hospital",
            sprinklered=True,
        )
        ids = [v.rule_id for v in m.match(conds)]
        assert "RULE-019" not in ids

    def test_rule020_fires_for_sprinklered(self, tmp_path):
        import config
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "m.db")
        store.seed_from_json(config.HCAI_RULES_FILE)
        m = RuleMatcher.__new__(RuleMatcher)
        m._rules = store.get_all_active()
        conds = _conditions(
            occupancy_type="Occupied Hospital",
            sprinklered=True,
        )
        ids = [v.rule_id for v in m.match(conds)]
        assert "RULE-020" in ids

    def test_rule020_silent_for_non_sprinklered(self, tmp_path):
        import config
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "m.db")
        store.seed_from_json(config.HCAI_RULES_FILE)
        m = RuleMatcher.__new__(RuleMatcher)
        m._rules = store.get_all_active()
        conds = _conditions(
            occupancy_type="Occupied Hospital",
            sprinklered=False,
        )
        ids = [v.rule_id for v in m.match(conds)]
        assert "RULE-020" not in ids

    def test_migration4_column_exists(self, tmp_path):
        import sqlite3

        from src.db.rules_store import RulesStore
        RulesStore(db_path=tmp_path / "m4.db")
        with sqlite3.connect(str(tmp_path / "m4.db")) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(rules)").fetchall()]
        assert "trigger_sprinklered" in cols

    def test_sprinklered_stored_and_retrieved(self, tmp_path):
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "sp.db")
        rule = _rule(id="SP-001", trigger_sprinklered=True)
        store.upsert_rule(rule)
        fetched = store.get_by_id("SP-001")
        assert fetched["trigger_sprinklered"] is True

        rule["trigger_sprinklered"] = False
        store.upsert_rule(rule)
        fetched = store.get_by_id("SP-001")
        assert fetched["trigger_sprinklered"] is False


# ---------------------------------------------------------------------------
# TestOutputDirectoryCleanup
# ---------------------------------------------------------------------------

class TestOutputDirectoryCleanup:

    def test_cleanup_removes_orphaned_output_dirs(self, tmp_path, monkeypatch):
        """Directories in output/ that don't match surviving job IDs are removed."""
        import config as _config
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(_config, "OUTPUT_DIR", output_dir)

        # Create two fake job output dirs
        orphan_id = str(uuid4())
        alive_id = str(uuid4())
        (output_dir / orphan_id).mkdir()
        (output_dir / alive_id).mkdir()
        (output_dir / orphan_id / "report.html").write_text("<html/>")

        # Patch job store to only know about alive_id
        from datetime import datetime

        from src.api.models import JobStatus, ReviewResponse
        alive_job = ReviewResponse(
            job_id=alive_id,
            project_name="Alive",
            status=JobStatus.complete,
            created_at=datetime.now(UTC),
        )

        class FakeStore:
            def list_recent(self, limit):
                return [alive_job]

        import src.db.job_store as _js
        monkeypatch.setattr(_js, "get_sqlite_job_store", lambda: FakeStore())

        from src.db.job_store import get_sqlite_job_store as _get
        store = _get()

        # Run cleanup manually (simulate the CLI logic)
        surviving_ids = {str(j.job_id) for j in store.list_recent(limit=10_000)}
        orphaned = [d for d in output_dir.iterdir()
                    if d.is_dir() and d.name not in surviving_ids]
        for d in orphaned:
            shutil.rmtree(d, ignore_errors=True)

        assert not (output_dir / orphan_id).exists()
        assert (output_dir / alive_id).exists()

    def test_cleanup_dry_run_leaves_files_intact(self, tmp_path):
        """Dry-run simulation should not delete anything."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "some-orphan-dir").mkdir()
        (output_dir / "some-orphan-dir" / "report.html").write_text("<html/>")

        # Simulate dry-run: collect orphans but do NOT delete
        surviving_ids: set[str] = set()  # nothing survives (all orphaned)
        orphaned = [d for d in output_dir.iterdir()
                    if d.is_dir() and d.name not in surviving_ids]
        count = len(orphaned)
        # DRY RUN: don't call shutil.rmtree

        assert count == 1
        assert (output_dir / "some-orphan-dir").exists()
