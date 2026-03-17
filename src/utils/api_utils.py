"""
API utilities — retry logic, rate limiting, and response caching for Claude API calls.
"""

from __future__ import annotations

import hashlib
import json
import time
import threading
from functools import lru_cache
from typing import Any, Callable, Optional

import config

# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Thread-safe token-bucket rate limiter."""

    def __init__(self, calls_per_minute: int = 30) -> None:
        self._capacity = calls_per_minute
        self._tokens = float(calls_per_minute)
        self._refill_rate = calls_per_minute / 60.0  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._capacity,
                    self._tokens + elapsed * self._refill_rate,
                )
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            time.sleep(0.1)


_default_limiter = RateLimiter(calls_per_minute=30)


# ---------------------------------------------------------------------------
# Retry decorator with exponential backoff
# ---------------------------------------------------------------------------

def with_retry(
    max_attempts: int = 3,
    base_delay: float = 4.0,
    max_delay: float = 10.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Decorator: retry on specified exceptions with exponential backoff."""

    def decorator(fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt == max_attempts:
                        raise
                    wait = min(delay, max_delay)
                    from src.monitoring.logger import get_logger
                    get_logger(__name__).warning(
                        "Attempt %d/%d failed (%s). Retrying in %.1fs…",
                        attempt, max_attempts, exc, wait,
                    )
                    time.sleep(wait)
                    delay *= 2
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Simple LRU cache for regulation lookups
# ---------------------------------------------------------------------------

def _make_cache_key(text: str, top_k: int) -> str:
    return hashlib.md5(f"{text}:{top_k}".encode()).hexdigest()


class RegulationCache:
    """
    LRU cache for RAG regulation queries.
    Avoids re-embedding identical queries within a session.
    """

    def __init__(self, maxsize: int = 200) -> None:
        self._maxsize = maxsize
        self._cache: dict[str, list[dict]] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def get(self, query: str, top_k: int) -> Optional[list[dict]]:
        key = _make_cache_key(query, top_k)
        with self._lock:
            return self._cache.get(key)

    def set(self, query: str, top_k: int, result: list[dict]) -> None:
        key = _make_cache_key(query, top_k)
        with self._lock:
            if key in self._cache:
                self._order.remove(key)
            elif len(self._cache) >= self._maxsize:
                oldest = self._order.pop(0)
                del self._cache[oldest]
            self._cache[key] = result
            self._order.append(key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._order.clear()

    def __len__(self) -> int:
        return len(self._cache)


# Module-level singletons
_regulation_cache = RegulationCache(maxsize=200)


def get_regulation_cache() -> RegulationCache:
    return _regulation_cache


def get_rate_limiter() -> RateLimiter:
    return _default_limiter
