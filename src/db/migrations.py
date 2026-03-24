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
# Migration 2 — jobs table
# ---------------------------------------------------------------------------

@migration(2, "Create jobs table for persistent async job storage")
def _m2(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id       TEXT    PRIMARY KEY,
            project_name TEXT    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'pending',
            created_at   TEXT    NOT NULL,
            updated_at   TEXT    NOT NULL,
            completed_at TEXT,
            result_json  TEXT,
            error        TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status     ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
    """)


# ---------------------------------------------------------------------------
# Migration 3 — construction type and licensed-bed triggers
# ---------------------------------------------------------------------------

@migration(3, "Add rule_construction_types table and min_licensed_beds column")
def _m3(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        ALTER TABLE rules ADD COLUMN min_licensed_beds INTEGER DEFAULT NULL;

        CREATE TABLE IF NOT EXISTS rule_construction_types (
            rule_id           TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            construction_type TEXT NOT NULL,
            PRIMARY KEY (rule_id, construction_type)
        );

        CREATE INDEX IF NOT EXISTS idx_rule_construction_types
            ON rule_construction_types(rule_id);
    """)


# ---------------------------------------------------------------------------
# Migration 4 — sprinkler trigger
# ---------------------------------------------------------------------------

@migration(4, "Add trigger_sprinklered column to rules")
def _m4(conn: sqlite3.Connection) -> None:
    """
    NULL  = rule applies regardless of sprinkler status (default)
    1     = rule applies only when facility IS sprinklered
    0     = rule applies only when facility is NOT sprinklered
    """
    conn.executescript("""
        ALTER TABLE rules ADD COLUMN trigger_sprinklered INTEGER DEFAULT NULL;
    """)


# ---------------------------------------------------------------------------
# Migration 5 — building height and stories triggers
# ---------------------------------------------------------------------------

@migration(5, "Add min_building_height_ft and min_stories columns to rules")
def _m5(conn: sqlite3.Connection) -> None:
    """
    min_building_height_ft : rule only fires when building height >= this value (ft)
    min_stories            : rule only fires when stories above grade >= this value
    Both NULL = no height/story threshold (applies to all buildings).
    """
    conn.executescript("""
        ALTER TABLE rules ADD COLUMN min_building_height_ft REAL DEFAULT NULL;
        ALTER TABLE rules ADD COLUMN min_stories            INTEGER DEFAULT NULL;
    """)


# ---------------------------------------------------------------------------
# Migration 6 — county and city triggers
# ---------------------------------------------------------------------------

@migration(6, "Add rule_counties and rule_cities tables for local-amendment triggers")
def _m6(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rule_counties (
            rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            county  TEXT NOT NULL,
            PRIMARY KEY (rule_id, county)
        );

        CREATE TABLE IF NOT EXISTS rule_cities (
            rule_id TEXT NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
            city    TEXT NOT NULL,
            PRIMARY KEY (rule_id, city)
        );

        CREATE INDEX IF NOT EXISTS idx_rule_counties ON rule_counties(rule_id);
        CREATE INDEX IF NOT EXISTS idx_rule_cities   ON rule_cities(rule_id);
    """)


# ---------------------------------------------------------------------------
# Migration 7 — WUI / wildfire zone trigger
# ---------------------------------------------------------------------------

@migration(7, "Add trigger_wui column to rules for wildfire zone filtering")
def _m7(conn: sqlite3.Connection) -> None:
    """
    NULL  = rule applies regardless of WUI zone status (default)
    1     = rule applies ONLY when project is in a WUI / FHSZ zone
    """
    conn.executescript("""
        ALTER TABLE rules ADD COLUMN trigger_wui INTEGER DEFAULT NULL;
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
