"""
Repository layer — thin wrappers around Supabase table operations.

Each repository handles one domain. All methods fall back silently when
Supabase is not configured so the file-based pipeline continues to work.
"""

from __future__ import annotations

import json
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from src.database.client import get_supabase


# ---------------------------------------------------------------------------
# FeedbackRepository
# ---------------------------------------------------------------------------

class FeedbackRepository:
    TABLE = "feedback_records"

    def insert(self, feedback_dict: Dict) -> Optional[Dict]:
        db = get_supabase()
        if not db:
            return None
        try:
            res = db.table(self.TABLE).insert(feedback_dict).execute()
            return res.data[0] if res.data else None
        except Exception as exc:
            print(f"[FeedbackRepository] insert failed: {exc}")
            return None

    def get_by_id(self, feedback_id: str) -> Optional[Dict]:
        db = get_supabase()
        if not db:
            return None
        try:
            res = db.table(self.TABLE).select("*").eq("feedback_id", feedback_id).single().execute()
            return res.data
        except Exception:
            return None

    def count_recent(self, since_iso: str) -> int:
        db = get_supabase()
        if not db:
            return 0
        try:
            res = (
                db.table(self.TABLE)
                .select("id", count="exact")
                .gte("created_at", since_iso)
                .execute()
            )
            return res.count or 0
        except Exception:
            return 0

    def mark_processed(self, feedback_id: str) -> None:
        db = get_supabase()
        if not db:
            return
        try:
            db.table(self.TABLE).update({
                "is_processed": True,
                "processing_date": datetime.now().isoformat(),  # fixed: removed 'processing_date' typo
            }).eq("feedback_id", feedback_id).execute()
        except Exception as exc:
            print(f"[FeedbackRepository] mark_processed failed: {exc}")

    def list_by_type(self, feedback_type: str, limit: int = 500) -> List[Dict]:
        db = get_supabase()
        if not db:
            return []
        try:
            res = (
                db.table(self.TABLE)
                .select("*")
                .eq("feedback_type", feedback_type)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception:
            return []


# ---------------------------------------------------------------------------
# MetricsRepository
# ---------------------------------------------------------------------------

class MetricsRepository:
    TABLE = "performance_metrics"

    def upsert(self, metric_type: str, value: float, model_version: str = "", sample_size: int = 0) -> None:
        db = get_supabase()
        if not db:
            return
        try:
            db.table(self.TABLE).upsert({
                "metric_date":    date.today().isoformat(),
                "metric_type":    metric_type,
                "value":          value,
                "model_version":  model_version,
                "sample_size":    sample_size,
            }, on_conflict="metric_date,metric_type").execute()
        except Exception as exc:
            print(f"[MetricsRepository] upsert failed: {exc}")

    def get_recent(self, days: int = 30) -> List[Dict]:
        db = get_supabase()
        if not db:
            return []
        try:
            from datetime import timedelta
            since = (datetime.now() - timedelta(days=days)).date().isoformat()
            res = (
                db.table(self.TABLE)
                .select("*")
                .gte("metric_date", since)
                .order("metric_date", desc=False)
                .execute()
            )
            return res.data or []
        except Exception:
            return []


# ---------------------------------------------------------------------------
# ModelRepository
# ---------------------------------------------------------------------------

class ModelRepository:
    TABLE = "model_versions"

    def register(self, version: str, model_type: str, model_path: str,
                 metrics: Dict, retrain_reason: str = "", training_data_count: int = 0) -> None:
        db = get_supabase()
        if not db:
            return
        try:
            # Deactivate previous active model of this type
            db.table(self.TABLE).update({"is_active": False}).eq("model_type", model_type).eq("is_active", True).execute()
            # Insert new version
            db.table(self.TABLE).insert({
                "version":              version,
                "model_type":           model_type,
                "model_path":           model_path,
                "metrics":              metrics,
                "is_active":            True,
                "retrain_reason":       retrain_reason,
                "training_data_count":  training_data_count,
            }).execute()
        except Exception as exc:
            print(f"[ModelRepository] register failed: {exc}")

    def get_active(self, model_type: str) -> Optional[Dict]:
        db = get_supabase()
        if not db:
            return None
        try:
            res = (
                db.table(self.TABLE)
                .select("*")
                .eq("model_type", model_type)
                .eq("is_active", True)
                .single()
                .execute()
            )
            return res.data
        except Exception:
            return None

    def history(self, limit: int = 20) -> List[Dict]:
        db = get_supabase()
        if not db:
            return []
        try:
            res = (
                db.table(self.TABLE)
                .select("*")
                .order("trained_on_date", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception:
            return []


# ---------------------------------------------------------------------------
# ReviewRepository  (tracks billable reviews per firm)
# ---------------------------------------------------------------------------

class ReviewRepository:
    PROJECTS_TABLE  = "projects"
    REVIEWS_TABLE   = "reviews"
    VIOLATIONS_TABLE = "violations"
    FIRMS_TABLE     = "firms"

    def create_project(self, firm_id: str, name: str, jurisdiction_id: str,
                       product_slug: str = "medblueprints") -> Optional[str]:
        """Insert a project row and return its UUID."""
        db = get_supabase()
        if not db:
            return None
        try:
            res = db.table(self.PROJECTS_TABLE).insert({
                "firm_id":         firm_id,
                "name":            name,
                "jurisdiction_id": jurisdiction_id,
                "product_slug":    product_slug,
                "status":          "processing",
            }).execute()
            return res.data[0]["id"] if res.data else None
        except Exception as exc:
            print(f"[ReviewRepository] create_project failed: {exc}")
            return None

    def save_review(self, project_id: str, review_dict: Dict) -> Optional[str]:
        """Persist review results and return review UUID."""
        db = get_supabase()
        if not db:
            return None
        try:
            review_dict["project_id"]   = project_id
            review_dict["completed_at"] = datetime.now().isoformat()
            res = db.table(self.REVIEWS_TABLE).insert(review_dict).execute()
            review_id = res.data[0]["id"] if res.data else None
            # Mark project complete
            db.table(self.PROJECTS_TABLE).update({"status": "complete"}).eq("id", project_id).execute()
            return review_id
        except Exception as exc:
            print(f"[ReviewRepository] save_review failed: {exc}")
            return None

    def increment_firm_usage(self, firm_id: str) -> None:
        """Bump reviews_used counter for billing enforcement."""
        db = get_supabase()
        if not db:
            return
        try:
            # Supabase doesn't support atomic increment via SDK directly;
            # use rpc or fetch-then-update pattern
            res = db.table(self.FIRMS_TABLE).select("reviews_used").eq("id", firm_id).single().execute()
            if res.data:
                new_count = (res.data.get("reviews_used") or 0) + 1
                db.table(self.FIRMS_TABLE).update({"reviews_used": new_count}).eq("id", firm_id).execute()
        except Exception as exc:
            print(f"[ReviewRepository] increment_firm_usage failed: {exc}")

    def check_quota(self, firm_id: str) -> bool:
        """Return True if firm has reviews remaining. -1 limit = unlimited."""
        db = get_supabase()
        if not db:
            return True   # offline mode — always allow
        try:
            res = db.table(self.FIRMS_TABLE).select("reviews_used,reviews_limit").eq("id", firm_id).single().execute()
            if not res.data:
                return False
            limit = res.data.get("reviews_limit", 1)
            used  = res.data.get("reviews_used", 0)
            return limit == -1 or used < limit
        except Exception:
            return True


# ---------------------------------------------------------------------------
# RulesRepository  (reads from blueprintIQ rules tables)
# ---------------------------------------------------------------------------

class RulesRepository:
    TABLE = "rules"

    def get_by_jurisdiction(self, state_code: str, discipline: str = "Healthcare") -> List[Dict]:
        """Fetch active rules for a state from the platform DB."""
        db = get_supabase()
        if not db:
            return []
        try:
            res = (
                db.table(self.TABLE)
                .select("*, rule_packs(jurisdiction_id, jurisdictions(state_code))")
                .eq("is_active", True)
                .execute()
            )
            # Filter by state_code via joined data
            rows = res.data or []
            return [
                r for r in rows
                if r.get("rule_packs", {})
                    .get("jurisdictions", {})
                    .get("state_code") == state_code
            ]
        except Exception as exc:
            print(f"[RulesRepository] get_by_jurisdiction failed: {exc}")
            return []

    def search(self, query: str, limit: int = 20) -> List[Dict]:
        """Full-text search across rule descriptions."""
        db = get_supabase()
        if not db:
            return []
        try:
            res = (
                db.table(self.TABLE)
                .select("*")
                .text_search("description", query)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception:
            return []
