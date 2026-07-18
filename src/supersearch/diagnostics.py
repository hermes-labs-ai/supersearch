"""Thread-local runtime diagnostics for search and fetch operations."""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from collections.abc import Iterator

_STATE = threading.local()


@contextmanager
def capture_diagnostics() -> Iterator[list[str]]:
    """Capture diagnostics emitted in the current thread only."""
    messages: list[str] = []
    previous = getattr(_STATE, "sink", None)
    _STATE.sink = messages
    try:
        yield messages
    finally:
        if previous is None:
            delattr(_STATE, "sink")
        else:
            _STATE.sink = previous


def report(message: str) -> None:
    """Record a diagnostic for status propagation and write it to stderr."""
    sink = getattr(_STATE, "sink", None)
    if sink is not None:
        sink.append(message)
    print(message, file=sys.stderr)
