"""
Structured logging — JSON-formatted logs with session context.

All modules import get_logger() from here instead of using logging directly.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import config

# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":      self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Any extra fields passed via `extra=` end up on the record
        for key in ("session_id", "project", "rule_id", "severity", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Log rotation helper (manual, no external dependency)
# ---------------------------------------------------------------------------

def _get_log_path() -> Path:
    log_dir = config.BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    # Rotate: keep at most 5 files of ≤5 MB each
    log_path = log_dir / "hcai_engine.log"
    if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
        for i in range(4, 0, -1):
            src = log_dir / f"hcai_engine.log.{i}"
            dst = log_dir / f"hcai_engine.log.{i + 1}"
            if src.exists():
                src.rename(dst)
        log_path.rename(log_dir / "hcai_engine.log.1")
    return log_path


# ---------------------------------------------------------------------------
# Initialise root HCAI logger once
# ---------------------------------------------------------------------------

_INITIALISED = False

def _init_logging() -> None:
    global _INITIALISED
    if _INITIALISED:
        return

    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    root = logging.getLogger("hcai")
    root.setLevel(log_level)

    # Console handler — plain text for readability during development
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(log_level)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(ch)

    # File handler — JSON structured logs
    try:
        fh = logging.FileHandler(_get_log_path(), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
    except OSError:
        pass  # Non-fatal if log directory is not writable

    _INITIALISED = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'hcai' namespace."""
    _init_logging()
    if name.startswith("hcai."):
        return logging.getLogger(name)
    # Map src.foo.bar → hcai.foo.bar
    clean = name.replace("src.", "").replace(".", ".")
    return logging.getLogger(f"hcai.{clean}")
