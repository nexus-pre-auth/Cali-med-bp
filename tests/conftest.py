"""
pytest configuration — session-level fixtures shared across all test modules.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Guard against test-inserted rules leaking into other tests.
# Any rule whose ID starts with "TEST-" is deactivated before the session
# starts so it doesn't affect citation assertions, match counts, etc.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def deactivate_test_rules():
    """Disable any TEST-* rules left in the shared DB from prior runs."""
    try:
        from src.db.rules_store import get_rules_store
        store = get_rules_store()
        for rule in store.get_all():
            if rule["id"].startswith("TEST-") and rule["is_active"]:
                store.set_active(rule["id"], False)
    except Exception:
        pass
    yield
