"""
FastAPI endpoint tests using httpx TestClient.

All tests run synchronously without a live server.
RAG and Claude API calls are bypassed (no_rag=True or mocked).
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    import os
    os.environ["RATE_LIMIT_RPM"] = "0"  # disable rate limiting for API tests
    app = create_app()
    os.environ.pop("RATE_LIMIT_RPM", None)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


HOSPITAL_TEXT = """
FACILITY: Occupied Hospital (Acute Care)
Location: City of San Francisco, San Francisco County, California
Construction Type: Type I-A, Fully Sprinklered (NFPA 13)
Licensed Beds: 80

SEISMIC DESIGN CATEGORY: D
SDS: 1.1, SD1: 0.55, Importance Factor Ip: 1.5, Site Class: D

SYSTEMS: AHU, essential electrical system, EES, generator, critical branch,
life safety branch, medical gas, oxygen manifold, vacuum pump, WAGD, HEPA filter

ROOMS: operating room, OR, ICU, intensive care, isolation room, patient room, pharmacy
"""


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "rules_loaded" in data
        assert data["rules_loaded"] > 0

    def test_health_no_auth_required(self, client):
        r = client.get("/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /review
# ---------------------------------------------------------------------------

class TestSubmitReview:
    def test_submit_returns_202(self, client):
        r = client.post("/review", json={
            "project_name": "Test Hospital",
            "text": HOSPITAL_TEXT,
            "no_rag": True,
        })
        assert r.status_code == 202

    def test_submit_returns_job_id(self, client):
        r = client.post("/review", json={
            "project_name": "Test Hospital",
            "text": HOSPITAL_TEXT,
            "no_rag": True,
        })
        data = r.json()
        assert "job_id" in data
        assert uuid.UUID(data["job_id"])  # valid UUID

    def test_submit_initial_status_pending_or_processing(self, client):
        r = client.post("/review", json={
            "text": HOSPITAL_TEXT,
            "no_rag": True,
        })
        assert r.json()["status"] in ("pending", "processing")

    def test_submit_without_text_returns_422(self, client):
        r = client.post("/review", json={"project_name": "No Input"})
        assert r.status_code == 422

    def test_submit_empty_text_returns_422(self, client):
        r = client.post("/review", json={"text": None, "project_name": "Empty"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /review/{job_id}
# ---------------------------------------------------------------------------

class TestGetReview:
    def _submit_and_wait(self, client, max_wait: float = 5.0) -> dict:
        r = client.post("/review", json={
            "project_name": "Poll Test",
            "text": HOSPITAL_TEXT,
            "no_rag": True,
        })
        job_id = r.json()["job_id"]
        deadline = time.time() + max_wait
        while time.time() < deadline:
            poll = client.get(f"/review/{job_id}")
            if poll.json()["status"] in ("complete", "failed"):
                return poll.json()
            time.sleep(0.1)
        return client.get(f"/review/{job_id}").json()

    def test_get_unknown_job_404(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/review/{fake_id}")
        assert r.status_code == 404

    def test_completed_job_has_violations(self, client):
        result = self._submit_and_wait(client)
        assert result["status"] == "complete", f"Job failed: {result.get('error')}"
        assert len(result["violations"]) > 0

    def test_completed_job_has_conditions(self, client):
        result = self._submit_and_wait(client)
        assert result["conditions"] is not None
        assert result["conditions"]["occupancy_type"] == "Occupied Hospital"

    def test_completed_job_has_summary(self, client):
        result = self._submit_and_wait(client)
        summary = result["summary"]
        assert summary["total"] == len(result["violations"])

    def test_violations_have_required_fields(self, client):
        result = self._submit_and_wait(client)
        for v in result["violations"]:
            for field in ("rule_id", "discipline", "severity", "ahj_comment",
                          "fix_instructions", "citations"):
                assert field in v, f"Missing field: {field}"

    def test_violations_sorted_critical_first(self, client):
        result = self._submit_and_wait(client)
        order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        severities = [v["severity"] for v in result["violations"]]
        for i in range(len(severities) - 1):
            assert order[severities[i]] <= order[severities[i + 1]]

    def test_completed_job_has_metrics(self, client):
        result = self._submit_and_wait(client)
        assert result["metrics"] is not None
        assert "total_elapsed_ms" in result["metrics"]

    def test_confidence_scores_in_range(self, client):
        result = self._submit_and_wait(client)
        for v in result["violations"]:
            if v.get("confidence") is not None:
                assert 0.0 <= v["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# GET /reviews
# ---------------------------------------------------------------------------

class TestListReviews:
    def test_list_returns_array(self, client):
        r = client.get("/reviews")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_limit_respected(self, client):
        r = client.get("/reviews?limit=2")
        assert r.status_code == 200
        assert len(r.json()) <= 2

    def test_items_have_status(self, client):
        r = client.get("/reviews")
        for item in r.json():
            assert "status" in item
            assert "job_id" in item


# ---------------------------------------------------------------------------
# POST /validate
# ---------------------------------------------------------------------------

class TestValidate:
    def test_validate_returns_200(self, client):
        r = client.post("/validate", json={"text": HOSPITAL_TEXT})
        assert r.status_code == 200

    def test_validate_has_score(self, client):
        r = client.post("/validate", json={"text": HOSPITAL_TEXT})
        data = r.json()
        assert "overall_score" in data
        assert 0.0 <= data["overall_score"] <= 1.0

    def test_validate_has_items(self, client):
        r = client.post("/validate", json={"text": HOSPITAL_TEXT})
        data = r.json()
        assert "items" in data
        assert len(data["items"]) > 0

    def test_validate_with_ground_truth(self, client):
        gt = [{"rule_id": "RULE-001", "severity": "Critical",
               "keywords_in_ahj": ["isolation"]}]
        r = client.post("/validate", json={"text": HOSPITAL_TEXT, "ground_truth": gt})
        assert r.status_code == 200
        data = r.json()
        assert "ground_truth" in data["by_category"]

    def test_validate_empty_text(self, client):
        r = client.post("/validate", json={"text": ""})
        assert r.status_code == 200  # Valid call, just no violations
