"""Aggregates all `/api/v1` sub-routers behind a single `v1_router`."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.v1 import analyses, documents, findings, organizations, projects, reports, revisions

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(organizations.router)
v1_router.include_router(projects.router)
v1_router.include_router(documents.router)
v1_router.include_router(analyses.router)
v1_router.include_router(findings.router)
v1_router.include_router(reports.router)
v1_router.include_router(revisions.router)
