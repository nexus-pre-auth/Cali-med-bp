from __future__ import annotations

from src.database.repositories_v1 import DocumentRepository, OrganizationRepository


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, table_name: str, captured: dict):
        self.table_name = table_name
        self.captured = captured

    def update(self, patch):
        self.captured["table"] = self.table_name
        self.captured["patch"] = dict(patch)
        return self

    def eq(self, key, value):
        self.captured["eq"] = (key, value)
        return self

    def execute(self):
        return _FakeResult([{"id": self.captured["eq"][1], **self.captured["patch"]}])


class _FakeSupabase:
    def __init__(self, captured: dict):
        self.captured = captured

    def table(self, table_name: str):
        return _FakeQuery(table_name, self.captured)


def test_update_adds_updated_at_only_for_tables_that_have_it(monkeypatch):
    from src.database import repositories_v1

    captured = {}
    monkeypatch.setattr(repositories_v1, "get_supabase", lambda: _FakeSupabase(captured))

    OrganizationRepository().update("org-1", {"name": "Updated Org"})

    assert captured["table"] == "organizations"
    assert captured["eq"] == ("id", "org-1")
    assert captured["patch"]["name"] == "Updated Org"
    assert "updated_at" in captured["patch"]


def test_update_does_not_add_updated_at_for_tables_without_column(monkeypatch):
    from src.database import repositories_v1

    captured = {}
    monkeypatch.setattr(repositories_v1, "get_supabase", lambda: _FakeSupabase(captured))

    DocumentRepository().update("doc-1", {"status": "processed"})

    assert captured["table"] == "documents"
    assert captured["eq"] == ("id", "doc-1")
    assert captured["patch"] == {"status": "processed"}
