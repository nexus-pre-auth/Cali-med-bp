"""
Supabase client singleton.

Usage:
    from src.database.client import get_supabase, HAS_SUPABASE

    db = get_supabase()
    if db:
        db.table("feedback_records").insert({...}).execute()

Falls back gracefully to file-based storage when SUPABASE_URL is not set,
so local dev and CLI commands work without any cloud dependency.
"""

from __future__ import annotations

import os
from typing import Optional

HAS_SUPABASE = False
_client = None


def get_supabase():
    """Return a connected Supabase client, or None if not configured."""
    global _client, HAS_SUPABASE

    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL", "")
    # Use service-role key server-side so RLS doesn't block writes
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")

    if not url or not key:
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
        HAS_SUPABASE = True
        print("[Supabase] Connected.")
    except Exception as exc:
        print(f"[Supabase] Connection failed — falling back to file storage. ({exc})")
        _client = None

    return _client


def reset_client() -> None:
    """Force re-initialisation (useful in tests)."""
    global _client, HAS_SUPABASE
    _client = None
    HAS_SUPABASE = False
