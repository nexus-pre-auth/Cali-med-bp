"""Tests for document upload security validation."""

from __future__ import annotations

import io

from tests.conftest import auth_header, make_token

PDF_BYTES = b"%PDF-1.4\n%%EOF"


def _setup_project(client):
    token = make_token()
    org = client.post("/api/v1/organizations", json={"name": "Org"}, headers=auth_header(token)).json()
    project = client.post(
        "/api/v1/projects", json={"name": "P", "organization_id": org["id"]}, headers=auth_header(token)
    ).json()
    return token, project["id"]


def test_valid_pdf_upload_succeeds(app_client):
    token, project_id = _setup_project(app_client)
    files = {"file": ("plans.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 201, resp.text


def test_disallowed_extension_rejected(app_client):
    token, project_id = _setup_project(app_client)
    files = {"file": ("malware.exe", io.BytesIO(b"MZ..."), "application/octet-stream")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 400


def test_mismatched_mime_type_rejected(app_client):
    token, project_id = _setup_project(app_client)
    files = {"file": ("plans.pdf", io.BytesIO(PDF_BYTES), "application/x-msdownload")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 400


def test_oversized_file_rejected(app_client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "10")
    token, project_id = _setup_project(app_client)
    files = {"file": ("plans.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 400
    assert "size" in resp.json()["detail"].lower()


def test_path_traversal_filename_rejected(app_client):
    token, project_id = _setup_project(app_client)
    files = {"file": ("../../etc/passwd", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 400


def test_null_byte_filename_rejected(app_client):
    token, project_id = _setup_project(app_client)
    files = {"file": ("evil\x00.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 400


def test_content_does_not_match_pdf_header_rejected(app_client):
    token, project_id = _setup_project(app_client)
    files = {"file": ("plans.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 400


def test_empty_file_rejected(app_client):
    token, project_id = _setup_project(app_client)
    files = {"file": ("plans.pdf", io.BytesIO(b""), "application/pdf")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 400


def test_uploaded_document_stored_with_generated_filename_not_user_supplied(app_client):
    token, project_id = _setup_project(app_client)
    files = {"file": ("Report (final) v2.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    resp = app_client.post(f"/api/v1/projects/{project_id}/documents", files=files, headers=auth_header(token))
    assert resp.status_code == 201
    doc = resp.json()
    assert doc["original_filename"] == "Report (final) v2.pdf"

    from src.database.repositories_v1 import DocumentRepository
    stored = DocumentRepository().get(doc["id"])
    assert "Report (final) v2.pdf" not in stored["storage_path"]
