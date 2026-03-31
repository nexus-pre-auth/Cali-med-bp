"""
Performance Metrics — tracks processing time, API costs, and accuracy KPIs.

Usage:
    metrics = SessionMetrics()
    with metrics.timer("pdf_parse"):
        doc = parser.parse(path)
    metrics.record_api_call(tokens_in=500, tokens_out=300)
    metrics.record_violations(enriched)
    print(metrics.summary())
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from src.monitoring.logger import get_logger

log = get_logger(__name__)

# Claude Sonnet pricing (USD per million tokens) — update as needed
_INPUT_COST_PER_1M  = 3.00
_OUTPUT_COST_PER_1M = 15.00


@dataclass
class ApiCallRecord:
    model: str
    tokens_in: int
    tokens_out: int
    duration_ms: float
    purpose: str  # e.g. "ahj_comment"


@dataclass
class SessionMetrics:
    """Accumulates metrics for a single compliance review session."""

    session_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    started_at: float = field(default_factory=time.monotonic)

    # Timing buckets (name → cumulative ms)
    _timers: dict[str, float] = field(default_factory=dict)

    # API usage
    _api_calls: list[ApiCallRecord] = field(default_factory=list)

    # Processing stats
    pages_processed: int = 0
    violations_found: int = 0
    violations_by_severity: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @contextmanager
    def timer(self, name: str):
        """Context manager that records elapsed time for a named stage."""
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._timers[name] = self._timers.get(name, 0.0) + elapsed_ms
            log.debug(
                "Stage '%s' completed in %.1f ms", name, elapsed_ms,
                extra={"session_id": self.session_id, "duration_ms": elapsed_ms},
            )

    def record_api_call(
        self,
        tokens_in: int,
        tokens_out: int,
        model: str = "claude-sonnet-4-6",
        purpose: str = "ahj_comment",
        duration_ms: float = 0.0,
    ) -> None:
        self._api_calls.append(ApiCallRecord(
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
            purpose=purpose,
        ))

    def record_violations(self, enriched: list) -> None:
        """Record violation counts from a list of EnrichedViolation."""
        self.violations_found = len(enriched)
        counts: dict[str, int] = {}
        for ev in enriched:
            sev = ev.violation.severity.value
            counts[sev] = counts.get(sev, 0) + 1
        self.violations_by_severity = counts

    # ------------------------------------------------------------------
    def total_elapsed_ms(self) -> float:
        return (time.monotonic() - self.started_at) * 1000

    def api_cost_usd(self) -> float:
        total_in  = sum(r.tokens_in  for r in self._api_calls)
        total_out = sum(r.tokens_out for r in self._api_calls)
        return (total_in * _INPUT_COST_PER_1M + total_out * _OUTPUT_COST_PER_1M) / 1_000_000

    def summary(self) -> dict:
        return {
            "session_id":           self.session_id,
            "total_elapsed_ms":     round(self.total_elapsed_ms(), 1),
            "pages_processed":      self.pages_processed,
            "violations_found":     self.violations_found,
            "violations_by_severity": self.violations_by_severity,
            "stage_timings_ms":     {k: round(v, 1) for k, v in self._timers.items()},
            "api_calls":            len(self._api_calls),
            "api_tokens_in":        sum(r.tokens_in  for r in self._api_calls),
            "api_tokens_out":       sum(r.tokens_out for r in self._api_calls),
            "estimated_cost_usd":   round(self.api_cost_usd(), 6),
        }

    def log_summary(self) -> None:
        s = self.summary()
        log.info(
            "Session complete: %d violations in %.0f ms, estimated cost $%.4f",
            s["violations_found"],
            s["total_elapsed_ms"],
            s["estimated_cost_usd"],
            extra={"session_id": self.session_id},
        )
