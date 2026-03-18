"""
Audit Logger — append-only compliance audit trail.

Every review submission, violation detection, report generation, and
configuration change is recorded as an immutable JSON-Lines entry in
the audit log. This supports:

  - Regulatory accountability (who reviewed what, when)
  - Forensic replay of past decisions
  - Drift detection (rule changes affecting historical results)

Log location: logs/audit.jsonl  (one JSON object per line)

Events
------
REVIEW_SUBMITTED    — user/API submitted a project for review
REVIEW_COMPLETE     — pipeline finished; violation summary recorded
REVIEW_FAILED       — pipeline errored; error message recorded
VIOLATION_DETECTED  — individual violation flagged (one entry per violation)
REPORT_GENERATED    — output file written
KB_INDEXED          — regulatory knowledge base updated
RULE_LOADED         — rules dataset loaded at startup
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import config

_AUDIT_PATH = config.BASE_DIR / "logs" / "audit.jsonl"
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal writer
# ---------------------------------------------------------------------------

def _write(event: str, payload: dict[str, Any]) -> None:
    """Append a single audit record (thread-safe)."""
    record = {
        "ts":    datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    line = json.dumps(record, default=str) + "\n"

    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(line)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_review_submitted(
    job_id: str | UUID,
    project_name: str,
    source: str,            # "api_text" | "api_pdf" | "cli"
    api_key_hint: Optional[str] = None,  # first 8 chars only — never full key
    filename: Optional[str] = None,
) -> None:
    _write("REVIEW_SUBMITTED", {
        "job_id":       str(job_id),
        "project_name": project_name,
        "source":       source,
        "api_key_hint": api_key_hint,
        "filename":     filename,
    })


def log_review_complete(
    job_id: str | UUID,
    project_name: str,
    occupancy_type: Optional[str],
    total_violations: int,
    by_severity: dict[str, int],
    elapsed_ms: float,
    extraction_confidence: float,
) -> None:
    _write("REVIEW_COMPLETE", {
        "job_id":                str(job_id),
        "project_name":          project_name,
        "occupancy_type":        occupancy_type,
        "total_violations":      total_violations,
        "by_severity":           by_severity,
        "elapsed_ms":            round(elapsed_ms, 1),
        "extraction_confidence": round(extraction_confidence, 3),
    })


def log_review_failed(
    job_id: str | UUID,
    project_name: str,
    error: str,
) -> None:
    _write("REVIEW_FAILED", {
        "job_id":       str(job_id),
        "project_name": project_name,
        "error":        error[:500],  # cap length
    })


def log_violation_detected(
    job_id: str | UUID,
    rule_id: str,
    discipline: str,
    severity: str,
    trigger_condition: str,
    confidence: float,
) -> None:
    _write("VIOLATION_DETECTED", {
        "job_id":            str(job_id),
        "rule_id":           rule_id,
        "discipline":        discipline,
        "severity":          severity,
        "trigger_condition": trigger_condition,
        "confidence":        round(confidence, 3),
    })


def log_report_generated(
    job_id: str | UUID,
    fmt: str,
    path: str,
    size_bytes: int,
) -> None:
    _write("REPORT_GENERATED", {
        "job_id":     str(job_id),
        "format":     fmt,
        "path":       path,
        "size_bytes": size_bytes,
    })


def log_kb_indexed(
    documents_added: int,
    total_documents: int,
    triggered_by: str = "startup",  # "startup" | "api" | "cli"
) -> None:
    _write("KB_INDEXED", {
        "documents_added": documents_added,
        "total_documents": total_documents,
        "triggered_by":    triggered_by,
    })


def log_rule_loaded(
    rules_count: int,
    rules_file: str,
) -> None:
    _write("RULE_LOADED", {
        "rules_count": rules_count,
        "rules_file":  rules_file,
    })


# ---------------------------------------------------------------------------
# Reader (for audit queries)
# ---------------------------------------------------------------------------

def read_audit_log(
    event_filter: Optional[str] = None,
    job_id_filter: Optional[str] = None,
    limit: int = 1000,
) -> list[dict]:
    """
    Read and optionally filter audit log entries.

    Parameters
    ----------
    event_filter   : keep only entries where event == value
    job_id_filter  : keep only entries matching this job_id
    limit          : max entries to return (most recent first)
    """
    if not _AUDIT_PATH.exists():
        return []

    entries = []
    with open(_AUDIT_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_filter and record.get("event") != event_filter:
                continue
            if job_id_filter and record.get("job_id") != job_id_filter:
                continue
            entries.append(record)

    # Most recent first, capped
    return entries[-limit:][::-1]
