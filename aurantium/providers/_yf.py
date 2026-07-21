"""Shared yfinance helpers: 429 backoff and a global rate-limit cooldown.

Yahoo Finance throttles by IP and returns HTTP 429 ("Too Many Requests"),
which yfinance raises as ``YFRateLimitError``. yfinance's own ``retries`` config
only retries genuine network blips (timeouts, dropped connections) — it does
*not* retry a 429 — so a single throttle surfaces straight to the panel as a
scary "... fetch failed: Too Many Requests". With several panels each polling on
their own timer, one throttle also tends to cascade: every provider keeps
hitting Yahoo, which only deepens the block.

This module adds three things, used by the yfinance-backed providers:

- ``with_retry`` — a couple of short backoff attempts around a single call, to
  ride out an *isolated* 429 without the user ever seeing it.
- ``RATE_LIMIT_GATE`` — once a call is still throttled after retries, the gate
  trips a short global cooldown. Every yfinance fetch checks it first and skips
  the network entirely during the cooldown (publishing a friendly message and
  serving whatever was last cached), so all panels back off together and give
  Yahoo room to recover instead of hammering it.
- ``publish_fetch_error`` — turns a fetch exception into a published error,
  translating rate-limit errors into ``RATE_LIMIT_MESSAGE`` (and tripping the
  gate) while passing other errors through unchanged.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable, TypeVar

import yfinance as yf

try:
    from yfinance.exceptions import YFRateLimitError
except Exception:  # pragma: no cover - defensive across yfinance versions
    class YFRateLimitError(Exception):  # type: ignore[no-redef]
        pass

T = TypeVar("T")

#: Shown to panels while throttled. The DataHub scheduler re-requests on the
#: next TTL tick, so "will retry shortly" is literally what happens.
RATE_LIMIT_MESSAGE = "Yahoo Finance is rate-limiting requests; will retry shortly"

#: How long every yfinance fetch stays quiet after a throttle (seconds).
_COOLDOWN_S = 20.0


def configure() -> None:
    """Let yfinance retry genuine network blips itself. 429s are handled here
    (yfinance's ``retries`` deliberately does not cover them). Best-effort:
    a config-shape change in a future yfinance is swallowed, not fatal."""
    try:
        yf.config.network.retries = 2
    except Exception:
        pass


def is_rate_limited(exc: BaseException) -> bool:
    """True if ``exc`` looks like a Yahoo 429. Matches the typed exception and,
    defensively, the message text (some paths wrap or re-raise as plain errors)."""
    if isinstance(exc, YFRateLimitError):
        return True
    msg = str(exc).lower()
    return "too many requests" in msg or "429" in msg or "rate limit" in msg


class _RateLimitGate:
    """A global cooldown window shared by all yfinance fetches. Thread-safe:
    fetches run on QThreadPool workers and daemon fetch threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until = 0.0

    def blocked(self) -> bool:
        with self._lock:
            return time.monotonic() < self._until

    def trip(self, cooldown_s: float = _COOLDOWN_S) -> None:
        with self._lock:
            self._until = max(self._until, time.monotonic() + cooldown_s)


#: Process-wide gate; one throttle quiets every yfinance provider for a bit.
RATE_LIMIT_GATE = _RateLimitGate()


def with_retry(fn: Callable[[], T], *, attempts: int = 2, base_delay: float = 1.0) -> T:
    """Call ``fn``; on a rate-limit error, back off (exponential + jitter) and
    retry, up to ``attempts`` times total. When the last attempt is still
    throttled, trip the global cooldown and re-raise so the caller can surface
    ``RATE_LIMIT_MESSAGE``. Non-rate-limit errors propagate immediately.

    Safe to call from provider worker threads only — it sleeps, so never call it
    on the GUI thread."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if not is_rate_limited(exc):
                raise
            if attempt == attempts - 1:
                RATE_LIMIT_GATE.trip()
                raise
            time.sleep(base_delay * (2 ** attempt) + random.uniform(0.0, 0.5))
    raise RuntimeError("unreachable")  # pragma: no cover


def publish_fetch_error(hub: Any, topic: str, prefix: str, exc: BaseException) -> None:
    """Publish a fetch failure. Rate-limit errors trip the cooldown and show the
    calm ``RATE_LIMIT_MESSAGE``; everything else passes through as ``prefix: exc``."""
    if is_rate_limited(exc):
        RATE_LIMIT_GATE.trip()
        hub.publish_error(topic, RATE_LIMIT_MESSAGE)
    else:
        hub.publish_error(topic, f"{prefix}: {exc}")
