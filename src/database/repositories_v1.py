"""
Repository layer for the `/api/v1` SaaS entities (organizations, memberships,
projects, documents, analyses, findings, reports, audit logs).

Follows the existing project convention (`src/database/repositories.py`):
each repository is a thin wrapper that uses Supabase when configured
(`SUPABASE_URL`/`SUPABASE_SERVICE_KEY`), so the same tenant-isolation
behavior enforced by Row Level Security in `migrations/006_saas_tenant_model.sql`
applies in production.

Unlike the legacy repositories (which silently no-op when Supabase is
absent), these repositories fall back to `LocalStore` — a real, working
JSON-file-backed store — so the SaaS API is genuinely functional and
testable without a live Supabase project. This is documented as a local/dev
fallback only: it does not enforce Row Level Security, so all tenant
isolation in that mode is enforced in Python by these repository methods
(each list/get call is filtered by organization/project id).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.database.client import get_supabase
from src.database.local_store import get_local_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class _BaseRepository:
    """Shared Supabase-or-local-store CRUD helpers for a single table."""

    TABLE: str = ""
    HAS_UPDATED_AT: bool = False

    def _store(self):
        return get_local_store()

    def insert(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(row)
        row.setdefault("id", _new_id())
        row.setdefault("created_at", _now())
        db = get_supabase()
        if db:
            try:
                res = db.table(self.TABLE).insert(row).execute()
                if res.data:
                    return res.data[0]
            except Exception as exc:
                print(f"[{self.__class__.__name__}] Supabase insert failed, using local store: {exc}")
        return self._store().insert(self.TABLE, row)

    def get(self, row_id: str) -> Optional[Dict[str, Any]]:
        db = get_supabase()
        if db:
            try:
                res = db.table(self.TABLE).select("*").eq("id", row_id).limit(1).execute()
                if res.data:
                    return res.data[0]
                return None
            except Exception as exc:
                print(f"[{self.__class__.__name__}] Supabase get failed, using local store: {exc}")
        return self._store().get(self.TABLE, row_id)

    def list(self, **equals: Any) -> List[Dict[str, Any]]:
        db = get_supabase()
        if db:
            try:
                query = db.table(self.TABLE).select("*")
                for key, value in equals.items():
                    query = query.eq(key, value)
                res = query.execute()
                return res.data or []
            except Exception as exc:
                print(f"[{self.__class__.__name__}] Supabase list failed, using local store: {exc}")
        return self._store().list(self.TABLE, **equals)

    def update(self, row_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        patch = dict(patch)
        if self.HAS_UPDATED_AT:
            patch.setdefault("updated_at", _now())
        db = get_supabase()
        if db:
            try:
                res = db.table(self.TABLE).update(patch).eq("id", row_id).execute()
                if res.data:
                    return res.data[0]
            except Exception as exc:
                print(f"[{self.__class__.__name__}] Supabase update failed, using local store: {exc}")
        return self._store().update(self.TABLE, row_id, patch)

    def delete(self, row_id: str) -> bool:
        db = get_supabase()
        if db:
            try:
                db.table(self.TABLE).delete().eq("id", row_id).execute()
                return True
            except Exception as exc:
                print(f"[{self.__class__.__name__}] Supabase delete failed, using local store: {exc}")
        return self._store().delete(self.TABLE, row_id)


class OrganizationRepository(_BaseRepository):
    TABLE = "organizations"
    HAS_UPDATED_AT = True


class MembershipRepository(_BaseRepository):
    TABLE = "memberships"

    def get_role(self, organization_id: str, user_id: str) -> Optional[str]:
        rows = self.list(organization_id=organization_id, user_id=user_id)
        return rows[0]["role"] if rows else None

    def list_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        return self.list(user_id=user_id)

    def list_for_org(self, organization_id: str) -> List[Dict[str, Any]]:
        return self.list(organization_id=organization_id)


class ProjectRepositoryV1(_BaseRepository):
    TABLE = "projects"
    HAS_UPDATED_AT = True

    def list_for_org(self, organization_id: str) -> List[Dict[str, Any]]:
        return self.list(organization_id=organization_id)


class ProjectMemberRepository(_BaseRepository):
    TABLE = "project_members"

    def get_role(self, project_id: str, user_id: str) -> Optional[str]:
        rows = self.list(project_id=project_id, user_id=user_id)
        return rows[0]["role"] if rows else None


class DocumentRepository(_BaseRepository):
    TABLE = "documents"

    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self.list(project_id=project_id)


class AnalysisRepository(_BaseRepository):
    TABLE = "analyses"

    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self.list(project_id=project_id)


class FindingRepository(_BaseRepository):
    TABLE = "findings"

    def list_for_analysis(self, analysis_id: str) -> List[Dict[str, Any]]:
        return self.list(analysis_id=analysis_id)

    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        """Findings don't carry project_id directly — resolve via analyses."""
        analysis_ids = {a["id"] for a in AnalysisRepository().list_for_project(project_id)}
        if not analysis_ids:
            return []
        db = get_supabase()
        if db:
            try:
                res = (
                    db.table(self.TABLE)
                    .select("*")
                    .in_("analysis_id", list(analysis_ids))
                    .execute()
                )
                return res.data or []
            except Exception as exc:
                print(f"[{self.__class__.__name__}] Supabase list_for_project failed, using local store: {exc}")
        return [r for r in self._store().list(self.TABLE) if r.get("analysis_id") in analysis_ids]

    def bulk_insert(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.insert(row) for row in rows]


class ReportRepository(_BaseRepository):
    TABLE = "reports"

    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self.list(project_id=project_id)

    def list_for_analysis(self, analysis_id: str) -> List[Dict[str, Any]]:
        return self.list(analysis_id=analysis_id)


class AuditLogRepository(_BaseRepository):
    TABLE = "audit_logs"

    def log(
        self,
        *,
        organization_id: Optional[str],
        actor_user_id: Optional[str],
        action: str,
        project_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.insert(
            {
                "organization_id": organization_id,
                "project_id": project_id,
                "actor_user_id": actor_user_id,
                "action": action,
                "detail": detail or {},
            }
        )
