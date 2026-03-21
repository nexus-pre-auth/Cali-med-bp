"""
SQLite Rules Store — persistent, queryable replacement for hcai_rules.json.

The store is the single source of truth for compliance rules. On first
startup it seeds itself from hcai_rules.json; thereafter the JSON file
is only used for bulk imports or resets.

Key capabilities over the JSON file:
  - Filter rules by discipline, severity, occupancy, seismic zone
  - Enable / disable individual rules without deleting them
  - Append new rules at runtime (via CLI or API) without a redeploy
  - Version-controlled schema via migrations
  - ACID writes — no partial-load corruption
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import config
from src.db.migrations import run_migrations
from src.monitoring.logger import get_logger

log = get_logger(__name__)

_DB_PATH = config.BASE_DIR / "hcai_rules.db"
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

@contextmanager
def _get_conn(db_path: Path = _DB_PATH):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Rules Store
# ---------------------------------------------------------------------------

class RulesStore:
    """
    Thread-safe SQLite-backed rules store.

    Usage
    -----
    store = RulesStore()
    store.seed_from_json()          # only needed on first run
    rules = store.get_all_active()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DB_PATH
        with _get_conn(self._db_path) as conn:
            run_migrations(conn)

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def seed_from_json(self, json_path: Path | str | None = None) -> int:
        """
        Import rules from the JSON file into the database.
        Skips rules whose ID already exists (idempotent).
        Returns the number of new rules inserted.
        """
        path = Path(json_path) if json_path else config.HCAI_RULES_FILE
        if not path.exists():
            log.warning("Rules JSON not found at %s — skipping seed.", path)
            return 0

        with open(path) as f:
            rules = json.load(f)

        inserted = 0
        with _lock, _get_conn(self._db_path) as conn:
            for rule in rules:
                existing = conn.execute(
                    "SELECT id FROM rules WHERE id = ?", (rule["id"],)
                ).fetchone()
                if existing:
                    continue
                self._insert_rule(conn, rule)
                inserted += 1
            conn.commit()

        log.info("Seeded %d new rules from %s.", inserted, path)
        return inserted

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_all_active(self) -> list[dict]:
        """Return all active rules as dicts matching the JSON schema."""
        with _get_conn(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM rules WHERE is_active = 1 ORDER BY id"
            ).fetchall()
            return [self._hydrate(conn, row) for row in rows]

    def get_by_id(self, rule_id: str) -> Optional[dict]:
        with _get_conn(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM rules WHERE id = ?", (rule_id,)
            ).fetchone()
            return self._hydrate(conn, row) if row else None

    def get_by_discipline(self, discipline: str, active_only: bool = True) -> list[dict]:
        active_clause = "AND is_active = 1" if active_only else ""
        with _get_conn(self._db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM rules WHERE discipline = ? {active_clause} ORDER BY id",
                (discipline,),
            ).fetchall()
            return [self._hydrate(conn, row) for row in rows]

    def count(self, active_only: bool = True) -> int:
        clause = "WHERE is_active = 1" if active_only else ""
        with _get_conn(self._db_path) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM rules {clause}").fetchone()[0]

    def list_disciplines(self) -> list[str]:
        with _get_conn(self._db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT discipline FROM rules WHERE is_active = 1 ORDER BY discipline"
            ).fetchall()
            return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert_rule(self, rule: dict) -> None:
        """Insert or replace a rule (full upsert)."""
        with _lock, _get_conn(self._db_path) as conn:
            # Remove existing child rows
            for tbl in ("rule_occupancies", "rule_systems", "rule_rooms",
                        "rule_seismic_zones", "rule_code_references",
                        "rule_construction_types"):
                conn.execute(f"DELETE FROM {tbl} WHERE rule_id = ?", (rule["id"],))
            # Upsert main row
            conn.execute("""
                INSERT INTO rules
                    (id, discipline, description, violation_template, fix_template,
                     severity_override, min_licensed_beds, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    discipline         = excluded.discipline,
                    description        = excluded.description,
                    violation_template = excluded.violation_template,
                    fix_template       = excluded.fix_template,
                    severity_override  = excluded.severity_override,
                    min_licensed_beds  = excluded.min_licensed_beds,
                    is_active          = 1,
                    updated_at         = datetime('now')
            """, (
                rule["id"],
                rule.get("discipline", "General"),
                rule.get("description", ""),
                rule.get("violation_template", ""),
                rule.get("fix_template", ""),
                rule.get("severity_override"),
                rule.get("min_licensed_beds"),
            ))
            self._insert_children(conn, rule)
            conn.commit()

    def set_active(self, rule_id: str, active: bool) -> bool:
        """Enable or disable a rule. Returns True if the rule was found."""
        with _lock, _get_conn(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE rules SET is_active = ?, updated_at = datetime('now') WHERE id = ?",
                (1 if active else 0, rule_id),
            )
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert_rule(self, conn: sqlite3.Connection, rule: dict) -> None:
        conn.execute("""
            INSERT OR IGNORE INTO rules
                (id, discipline, description, violation_template, fix_template,
                 severity_override, min_licensed_beds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            rule["id"],
            rule.get("discipline", "General"),
            rule.get("description", ""),
            rule.get("violation_template", ""),
            rule.get("fix_template", ""),
            rule.get("severity_override"),
            rule.get("min_licensed_beds"),
        ))
        self._insert_children(conn, rule)

    def _insert_children(self, conn: sqlite3.Connection, rule: dict) -> None:
        rid = rule["id"]
        for occ in rule.get("trigger_occupancies", []):
            conn.execute("INSERT OR IGNORE INTO rule_occupancies VALUES (?, ?)", (rid, occ))
        for sys_ in rule.get("trigger_systems", []):
            conn.execute("INSERT OR IGNORE INTO rule_systems VALUES (?, ?)", (rid, sys_))
        for room in rule.get("trigger_rooms", []):
            conn.execute("INSERT OR IGNORE INTO rule_rooms VALUES (?, ?)", (rid, room))
        for zone in rule.get("trigger_seismic_zones", []):
            conn.execute("INSERT OR IGNORE INTO rule_seismic_zones VALUES (?, ?)", (rid, zone))
        for ref in rule.get("code_references", []):
            conn.execute("INSERT OR IGNORE INTO rule_code_references VALUES (?, ?)", (rid, ref))
        for ct in rule.get("trigger_construction_types", []):
            conn.execute("INSERT OR IGNORE INTO rule_construction_types VALUES (?, ?)", (rid, ct))

    def _hydrate(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        """Reconstruct a full rule dict from the database row + child tables."""
        rid = row["id"]

        def _fetch(tbl: str, col: str) -> list[str]:
            return [r[0] for r in conn.execute(
                f"SELECT {col} FROM {tbl} WHERE rule_id = ?", (rid,)
            ).fetchall()]

        return {
            "id":                         row["id"],
            "discipline":                 row["discipline"],
            "description":                row["description"],
            "violation_template":         row["violation_template"],
            "fix_template":               row["fix_template"],
            "severity_override":          row["severity_override"],
            "min_licensed_beds":          row["min_licensed_beds"],
            "is_active":                  bool(row["is_active"]),
            "trigger_occupancies":        _fetch("rule_occupancies", "occupancy"),
            "trigger_systems":            _fetch("rule_systems", "system"),
            "trigger_rooms":              _fetch("rule_rooms", "room"),
            "trigger_seismic_zones":      _fetch("rule_seismic_zones", "seismic_zone"),
            "trigger_construction_types": _fetch("rule_construction_types", "construction_type"),
            "code_references":            _fetch("rule_code_references", "reference"),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: Optional[RulesStore] = None


def get_rules_store() -> RulesStore:
    global _store
    if _store is None:
        _store = RulesStore()
        if _store.count() == 0:
            _store.seed_from_json()
    return _store
