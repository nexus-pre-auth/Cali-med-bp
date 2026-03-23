"""
Tests for:
- Building height and stories triggers (migration 5)
- County and city triggers for local amendments (migration 6)
- GET /rules/disciplines and GET /jobs/stats endpoints
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from src.engine.rule_matcher import RuleMatcher
from src.parser.condition_extractor import ProjectConditions, SeismicData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conditions(**kwargs) -> ProjectConditions:
    defaults = dict(
        occupancy_type="Occupied Hospital",
        construction_type=None,
        sprinklered=None,
        licensed_beds=None,
        building_height_ft=None,
        stories_above_grade=None,
        county=None,
        city=None,
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
    defaults = dict(
        id="TEST-RULE",
        discipline="General",
        description="Test",
        violation_template="V: height={height_ft} stories={stories}",
        fix_template="Fix",
        code_references=["CBC 2022"],
        severity_override="High",
        trigger_occupancies=[],
        trigger_systems=[],
        trigger_rooms=[],
        trigger_seismic_zones=[],
        trigger_construction_types=[],
        trigger_sprinklered=None,
        min_licensed_beds=None,
        min_building_height_ft=None,
        min_stories=None,
        trigger_counties=[],
        trigger_cities=[],
        is_active=True,
    )
    defaults.update(kwargs)
    return defaults


def _matcher(rules):
    m = RuleMatcher.__new__(RuleMatcher)
    m._rules = rules
    return m


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    os.environ["RATE_LIMIT_RPM"] = "0"
    from src.api.app import create_app
    app = create_app()
    os.environ.pop("RATE_LIMIT_RPM", None)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# TestBuildingHeightFilter
# ---------------------------------------------------------------------------

class TestBuildingHeightFilter:

    def test_no_height_threshold_matches_any_height(self):
        rule = _rule(min_building_height_ft=None)
        assert len(_matcher([rule]).match(_conditions(building_height_ft=100))) == 1

    def test_no_height_threshold_matches_unknown_height(self):
        rule = _rule(min_building_height_ft=None)
        assert len(_matcher([rule]).match(_conditions(building_height_ft=None))) == 1

    def test_height_threshold_blocks_below(self):
        rule = _rule(min_building_height_ft=55.0)
        assert len(_matcher([rule]).match(_conditions(building_height_ft=40.0))) == 0

    def test_height_threshold_allows_exact(self):
        rule = _rule(min_building_height_ft=55.0)
        assert len(_matcher([rule]).match(_conditions(building_height_ft=55.0))) == 1

    def test_height_threshold_allows_above(self):
        rule = _rule(min_building_height_ft=55.0)
        assert len(_matcher([rule]).match(_conditions(building_height_ft=120.0))) == 1

    def test_height_threshold_blocks_when_unknown(self):
        rule = _rule(min_building_height_ft=55.0)
        assert len(_matcher([rule]).match(_conditions(building_height_ft=None))) == 0

    def test_height_template_substitution(self):
        rule = _rule(violation_template="Building is {height_ft} ft tall")
        m = _matcher([rule])
        violations = m.match(_conditions(building_height_ft=80.0))
        assert violations
        assert "80" in violations[0].violation_text

    def test_height_template_unknown_when_not_extracted(self):
        rule = _rule(violation_template="Height: {height_ft}")
        m = _matcher([rule])
        violations = m.match(_conditions(building_height_ft=None))
        assert violations
        assert "unknown" in violations[0].violation_text


# ---------------------------------------------------------------------------
# TestStoriesFilter
# ---------------------------------------------------------------------------

class TestStoriesFilter:

    def test_no_stories_threshold_matches_any(self):
        rule = _rule(min_stories=None)
        assert len(_matcher([rule]).match(_conditions(stories_above_grade=10))) == 1

    def test_stories_threshold_blocks_below(self):
        rule = _rule(min_stories=4)
        assert len(_matcher([rule]).match(_conditions(stories_above_grade=3))) == 0

    def test_stories_threshold_allows_exact(self):
        rule = _rule(min_stories=4)
        assert len(_matcher([rule]).match(_conditions(stories_above_grade=4))) == 1

    def test_stories_threshold_blocks_when_unknown(self):
        rule = _rule(min_stories=4)
        assert len(_matcher([rule]).match(_conditions(stories_above_grade=None))) == 0

    def test_stories_template_substitution(self):
        rule = _rule(violation_template="Building has {stories} stories")
        m = _matcher([rule])
        violations = m.match(_conditions(stories_above_grade=6))
        assert violations
        assert "6" in violations[0].violation_text


# ---------------------------------------------------------------------------
# TestCountyAndCityFilters
# ---------------------------------------------------------------------------

class TestCountyAndCityFilters:

    def test_no_county_filter_matches_any_county(self):
        rule = _rule(trigger_counties=[])
        assert len(_matcher([rule]).match(_conditions(county="Los Angeles"))) == 1

    def test_county_filter_allows_match(self):
        rule = _rule(trigger_counties=["Los Angeles"])
        assert len(_matcher([rule]).match(_conditions(county="Los Angeles"))) == 1

    def test_county_filter_blocks_mismatch(self):
        rule = _rule(trigger_counties=["Los Angeles"])
        assert len(_matcher([rule]).match(_conditions(county="San Francisco"))) == 0

    def test_county_filter_case_insensitive(self):
        rule = _rule(trigger_counties=["los angeles"])
        assert len(_matcher([rule]).match(_conditions(county="Los Angeles"))) == 1

    def test_county_filter_blocks_when_county_unknown(self):
        """When county is not extracted, a county-scoped rule does not fire."""
        rule = _rule(trigger_counties=["Los Angeles"])
        assert len(_matcher([rule]).match(_conditions(county=None))) == 0

    def test_multiple_counties(self):
        rule = _rule(trigger_counties=["Los Angeles", "San Francisco"])
        assert len(_matcher([rule]).match(_conditions(county="San Francisco"))) == 1
        assert len(_matcher([rule]).match(_conditions(county="San Diego"))) == 0

    def test_city_filter_allows_match(self):
        rule = _rule(trigger_cities=["Los Angeles"])
        assert len(_matcher([rule]).match(_conditions(city="Los Angeles"))) == 1

    def test_city_filter_blocks_mismatch(self):
        rule = _rule(trigger_cities=["Los Angeles"])
        assert len(_matcher([rule]).match(_conditions(city="Oakland"))) == 0

    def test_city_filter_blocks_when_unknown(self):
        rule = _rule(trigger_cities=["San Francisco"])
        assert len(_matcher([rule]).match(_conditions(city=None))) == 0


# ---------------------------------------------------------------------------
# TestMigrations5And6
# ---------------------------------------------------------------------------

class TestMigrations5And6:

    def test_min_building_height_ft_column_exists(self, tmp_path):
        import sqlite3
        from src.db.rules_store import RulesStore
        RulesStore(db_path=tmp_path / "m.db")
        with sqlite3.connect(str(tmp_path / "m.db")) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(rules)").fetchall()]
        assert "min_building_height_ft" in cols
        assert "min_stories" in cols

    def test_rule_counties_table_exists(self, tmp_path):
        import sqlite3
        from src.db.rules_store import RulesStore
        RulesStore(db_path=tmp_path / "m.db")
        with sqlite3.connect(str(tmp_path / "m.db")) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "rule_counties" in tables
        assert "rule_cities" in tables

    def test_height_and_county_stored_and_retrieved(self, tmp_path):
        from src.db.rules_store import RulesStore
        store = RulesStore(db_path=tmp_path / "store.db")
        rule = _rule(
            id="RULE-HT-001",
            min_building_height_ft=55.0,
            min_stories=4,
            trigger_counties=["Los Angeles"],
            trigger_cities=["Pasadena"],
        )
        store.upsert_rule(rule)
        fetched = store.get_by_id("RULE-HT-001")
        assert fetched["min_building_height_ft"] == 55.0
        assert fetched["min_stories"] == 4
        assert "Los Angeles" in fetched["trigger_counties"]
        assert "Pasadena" in fetched["trigger_cities"]


# ---------------------------------------------------------------------------
# TestNewRulesIntegration (RULE-021, 022, 023)
# ---------------------------------------------------------------------------

class TestNewRulesIntegration:

    @pytest.fixture
    def matcher(self, tmp_path):
        from src.db.rules_store import RulesStore
        import config
        store = RulesStore(db_path=tmp_path / "m.db")
        store.seed_from_json(config.HCAI_RULES_FILE)
        m = RuleMatcher.__new__(RuleMatcher)
        m._rules = store.get_all_active()
        return m

    def test_rule021_fires_for_high_rise_hospital(self, matcher):
        conds = _conditions(occupancy_type="Occupied Hospital", building_height_ft=80.0)
        assert "RULE-021" in [v.rule_id for v in matcher.match(conds)]

    def test_rule021_silent_for_low_rise(self, matcher):
        conds = _conditions(occupancy_type="Occupied Hospital", building_height_ft=40.0)
        assert "RULE-021" not in [v.rule_id for v in matcher.match(conds)]

    def test_rule021_silent_when_height_unknown(self, matcher):
        conds = _conditions(occupancy_type="Occupied Hospital", building_height_ft=None)
        assert "RULE-021" not in [v.rule_id for v in matcher.match(conds)]

    def test_rule022_fires_for_4plus_stories(self, matcher):
        conds = _conditions(occupancy_type="Occupied Hospital", stories_above_grade=5)
        assert "RULE-022" in [v.rule_id for v in matcher.match(conds)]

    def test_rule022_silent_for_3_stories(self, matcher):
        conds = _conditions(occupancy_type="Occupied Hospital", stories_above_grade=3)
        assert "RULE-022" not in [v.rule_id for v in matcher.match(conds)]

    def test_rule023_fires_for_la_county(self, matcher):
        conds = _conditions(occupancy_type="Occupied Hospital", county="Los Angeles")
        assert "RULE-023" in [v.rule_id for v in matcher.match(conds)]

    def test_rule023_silent_for_other_county(self, matcher):
        conds = _conditions(occupancy_type="Occupied Hospital", county="Sacramento")
        assert "RULE-023" not in [v.rule_id for v in matcher.match(conds)]

    def test_rule023_silent_when_county_unknown(self, matcher):
        conds = _conditions(occupancy_type="Occupied Hospital", county=None)
        assert "RULE-023" not in [v.rule_id for v in matcher.match(conds)]


# ---------------------------------------------------------------------------
# TestNewAPIEndpoints
# ---------------------------------------------------------------------------

class TestNewAPIEndpoints:

    def test_disciplines_returns_list_of_strings(self, client):
        r = client.get("/rules/disciplines")
        assert r.status_code == 200
        disciplines = r.json()
        assert isinstance(disciplines, list)
        assert len(disciplines) > 0
        assert all(isinstance(d, str) for d in disciplines)

    def test_disciplines_includes_known_categories(self, client):
        r = client.get("/rules/disciplines")
        disciplines = r.json()
        assert "Infection Control" in disciplines
        assert "Structural / Seismic" in disciplines

    def test_disciplines_sorted_alphabetically(self, client):
        r = client.get("/rules/disciplines")
        disciplines = r.json()
        assert disciplines == sorted(disciplines)

    def test_job_stats_returns_total_and_by_status(self, client):
        r = client.get("/jobs/stats")
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "by_status" in body
        assert isinstance(body["total"], int)
        assert isinstance(body["by_status"], dict)

    def test_job_stats_total_matches_sum_of_statuses(self, client):
        r = client.get("/jobs/stats")
        body = r.json()
        assert body["total"] == sum(body["by_status"].values())

    def test_rules_response_includes_new_trigger_fields(self, client):
        r = client.get("/rules/RULE-021")
        assert r.status_code == 200
        rule = r.json()
        assert "min_building_height_ft" in rule
        assert "min_stories" in rule
        assert "trigger_counties" in rule
        assert "trigger_cities" in rule
        assert rule["min_building_height_ft"] == 55.0

    def test_post_rule_accepts_height_and_county(self, client):
        payload = {
            "id": "TEST-HEIGHT-RULE-001",
            "discipline": "Fire and Life Safety",
            "description": "Test height rule",
            "min_building_height_ft": 75.0,
            "min_stories": 6,
            "trigger_counties": ["San Francisco"],
            "trigger_cities": ["San Francisco"],
            "severity_override": "High",
            "code_references": ["CBC 2022 Section 403"],
        }
        r = client.post("/rules", json=payload)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["min_building_height_ft"] == 75.0
        assert body["min_stories"] == 6
        assert "San Francisco" in body["trigger_counties"]
        assert "San Francisco" in body["trigger_cities"]
