"""
Lightweight JSON-file-backed local store used as a Supabase fallback for the
`/api/v1` SaaS entities (organizations, projects, documents, analyses,
findings, reports, audit logs, ...).

This exists so the SaaS API is fully functional and testable in local
development / CI without requiring a live Supabase project, mirroring the
project's existing "graceful fallback to file storage" convention (see
`src/database/client.py`). It is intentionally simple:

  - One JSON file per table under `data/saas/`.
  - A single process-wide lock guards read-modify-write cycles.
  - Not suitable for multi-instance production deployment — production
    deployments should configure `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` so the
    repository layer talks to real Postgres with Row Level Security instead.

This module never touches Supabase; `src/database/repositories_v1.py`
decides whether to use Supabase or this local store per call.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_BASE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "saas"


class LocalStore:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or _BASE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _table_path(self, table: str) -> Path:
        return self.base_dir / f"{table}.json"

    def _load(self, table: str) -> Dict[str, Dict[str, Any]]:
        path = self._table_path(table)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text() or "{}")
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, table: str, data: Dict[str, Dict[str, Any]]) -> None:
        path = self._table_path(table)
        path.write_text(json.dumps(data, indent=2, default=str))

    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._load(table)
            row = dict(row)
            row.setdefault("id", str(uuid.uuid4()))
            data[row["id"]] = row
            self._save(table, data)
            return dict(row)

    def get(self, table: str, row_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._load(table).get(row_id)
            return dict(row) if row is not None else None

    def list(
        self,
        table: str,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
        **equals: Any,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            rows = list(self._load(table).values())
        if equals:
            rows = [r for r in rows if all(r.get(k) == v for k, v in equals.items())]
        if predicate:
            rows = [r for r in rows if predicate(r)]
        return [dict(r) for r in rows]

    def update(self, table: str, row_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._load(table)
            if row_id not in data:
                return None
            data[row_id].update(patch)
            self._save(table, data)
            return dict(data[row_id])

    def delete(self, table: str, row_id: str) -> bool:
        with self._lock:
            data = self._load(table)
            if row_id not in data:
                return False
            del data[row_id]
            self._save(table, data)
            return True

    def clear(self, table: str) -> None:
        """Test helper: remove all rows from a table."""
        with self._lock:
            self._save(table, {})


_default_store: Optional[LocalStore] = None


def get_local_store() -> LocalStore:
    global _default_store
    if _default_store is None:
        _default_store = LocalStore()
    return _default_store


def reset_local_store(base_dir: Optional[Path] = None) -> LocalStore:
    """Test helper: force a fresh LocalStore (optionally at a custom path)."""
    global _default_store
    _default_store = LocalStore(base_dir)
    return _default_store
