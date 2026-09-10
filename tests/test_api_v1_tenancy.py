"""
Tests for multi-tenant isolation, role-based access, and the full
end-to-end analysis workflow across the `/api/v1` SaaS API.
"""

from __future__ import annotations

import io

from tests.conftest import auth_header, make_token

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF"


def _create_org(client, token, name="Acme Health"):
    resp = client.post("/api/v1/organizations", json={"name": name}, headers=auth_header(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_project(client, token, org_id, name="Test Hospital Wing"):
    resp = client.post(
        "/api/v1/projects",
        json={"name": name, "organization_id": org_id},
        headers=auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_user_can_create_org_and_project(app_client):
    token = make_token()
    org = _create_org(app_client, token)
    assert org["name"] == "Acme Health"

    project = _create_project(app_client, token, org["id"])
    assert project["organization_id"] == org["id"]


def test_cross_org_project_access_is_denied(app_client):
    token_a = make_token()
    token_b = make_token()

    org_a = _create_org(app_client, token_a, name="Org A")
    project_a = _create_project(app_client, token_a, org_a["id"])

    # User B (a different organization entirely) must not be able to read,
    # modify, or delete User A's project.
    resp = app_client.get(f"/api/v1/projects/{project_a['id']}", headers=auth_header(token_b))
    assert resp.status_code == 404

    resp = app_client.patch(
        f"/api/v1/projects/{project_a['id']}", json={"name": "hijacked"}, headers=auth_header(token_b)
    )
    assert resp.status_code == 404

    resp = app_client.delete(f"/api/v1/projects/{project_a['id']}", headers=auth_header(token_b))
    assert resp.status_code == 404

    # And User B's organization list must not include Org A.
    resp = app_client.get("/api/v1/organizations", headers=auth_header(token_b))
    assert resp.status_code == 200
    assert org_a["id"] not in [o["id"] for o in resp.json()]


def test_cross_org_project_listing_is_isolated(app_client):
    token_a = make_token()
    token_b = make_token()
    org_a = _create_org(app_client, token_a, name="Org A")
    org_b = _create_org(app_client, token_b, name="Org B")
    project_a = _create_project(app_client, token_a, org_a["id"], name="Project A")
    project_b = _create_project(app_client, token_b, org_b["id"], name="Project B")

    resp_a = app_client.get("/api/v1/projects", params={"organization_id": org_a["id"]}, headers=auth_header(token_a))
    assert resp_a.status_code == 200
    ids_a = [p["id"] for p in resp_a.json()]
    assert project_a["id"] in ids_a
    assert project_b["id"] not in ids_a

    # User A must not be able to list Org B's projects at all.
    resp_cross = app_client.get(
        "/api/v1/projects", params={"organization_id": org_b["id"]}, headers=auth_header(token_a)
    )
    assert resp_cross.status_code == 404


def test_viewer_cannot_create_project(app_client):
    owner_token = make_token()
    viewer_token = make_token()
    org = _create_org(app_client, owner_token)

    # Demote: simulate a VIEWER by directly inserting a membership row via
    # the repository layer (no invite-flow exists yet in this MVP).
    from src.database.repositories_v1 import MembershipRepository
    import jwt as pyjwt
    from tests.conftest import TEST_JWT_SECRET

    claims = pyjwt.decode(viewer_token, TEST_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
    MembershipRepository().insert({"organization_id": org["id"], "user_id": claims["sub"], "role": "VIEWER"})

    resp = app_client.post(
        "/api/v1/projects",
        json={"name": "Should Fail", "organization_id": org["id"]},
        headers=auth_header(viewer_token),
    )
    assert resp.status_code == 403


def test_full_workflow_upload_analyze_findings_report(app_client):
    token = make_token()
    org = _create_org(app_client, token)
    project = _create_project(app_client, token, org["id"])
    project_id = project["id"]

    # Upload a document
    files = {"file": ("plans.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 201, resp.text
    document = resp.json()
    assert document["status"] == "uploaded"

    # Create an analysis (runs synchronously under TestClient's background
    # task execution, so we can assert on the outcome immediately).
    resp = app_client.post(
        f"/api/v1/projects/{project_id}/analyses",
        json={"document_id": document["id"]},
        headers=auth_header(token),
    )
    assert resp.status_code == 202, resp.text
    analysis = resp.json()
    analysis_id = analysis["id"]

    resp = app_client.get(f"/api/v1/projects/{project_id}/analyses/{analysis_id}", headers=auth_header(token))
    assert resp.status_code == 200
    completed = resp.json()
    assert completed["status"] in ("COMPLETED", "FAILED")

    # Findings and reports should be retrievable regardless of outcome (an
    # empty PDF may produce zero findings, which is a valid result).
    resp = app_client.get(f"/api/v1/projects/{project_id}/findings", headers=auth_header(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    resp = app_client.get(f"/api/v1/projects/{project_id}/reports", headers=auth_header(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_health_and_readiness_endpoints_not_required_for_v1_tests(app_client):
    # /health and /ready are wired in main.py's serve(), not this test app;
    # this test simply documents that the v1 router itself doesn't shadow
    # them (no route collision at "/health" or "/ready").
    resp = app_client.get("/health")
    assert resp.status_code == 404
