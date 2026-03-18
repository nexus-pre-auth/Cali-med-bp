"""
Database migrations — creates and upgrades the SQLite schema.

Migration strategy: version table + sequential migration functions.
Each migration is applied exactly once and its version number recorded.

Usage:
    from src.db.migrations import run_migrations
    run_migrations(conn)
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from src.monitoring.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Schema version history
# ---------------------------------------------------------------------------

Migration = Callable[[sqlite3.Connection], None]
_MIGRATIONS: list[tuple[int, str, Migration]] = []


def migration(version: int, description: str):
    """Decorator that registers a migration function."""
    def decorator(fn: Migration) -> Migration:
        _MIGRATIONS.append((version, description, fn))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Migration 1 — initial schema
# ---------------------------------------------------------------------------

@migration(1, "Create rules, rule_tags, and schema_version tables")
def _m1(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT    NOT NULL,
            applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rules (
            id                  TEXT    PRIMARY KEY,
            discipline          TEXT    NOT NULL,
            description         TEXT    NOT NULL,
            violation_template  TEXT    NOT NULL DEFAULT '',
            fix_template        TEXT    NOT NULL DEFAULT '',
            severity_override   TEXT,
            is_active           INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rule_occupancies (
            rule_id   TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            occupancy TEXT NOT NULL,
            PRIMARY KEY (rule_id, occupancy)
        );

        CREATE TABLE IF NOT EXISTS rule_systems (
            rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            system  TEXT NOT NULL,
            PRIMARY KEY (rule_id, system)
        );

        CREATE TABLE IF NOT EXISTS rule_rooms (
            rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            room    TEXT NOT NULL,
            PRIMARY KEY (rule_id, room)
        );

        CREATE TABLE IF NOT EXISTS rule_seismic_zones (
            rule_id      TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            seismic_zone TEXT NOT NULL,
            PRIMARY KEY (rule_id, seismic_zone)
        );

        CREATE TABLE IF NOT EXISTS rule_code_references (
            rule_id   TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            reference TEXT NOT NULL,
            PRIMARY KEY (rule_id, reference)
        );

        CREATE INDEX IF NOT EXISTS idx_rules_discipline  ON rules(discipline);
        CREATE INDEX IF NOT EXISTS idx_rules_is_active   ON rules(is_active);
    """)


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations in order."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT    NOT NULL,
            applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    applied = {row[0] for row in conn.execute("SELECT version FROM schema_version")}

    for version, description, fn in sorted(_MIGRATIONS, key=lambda m: m[0]):
        if version in applied:
            continue
        log.info("Applying migration %d: %s", version, description)
        fn(conn)
        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (version, description),
        )
        conn.commit()
        log.info("Migration %d applied.", version)
