"""Global undo stack for dashboard edits.

A single app-wide stack of undo actions. Any panel (or the main window) records
an undoable edit with :meth:`UndoStack.push` — a short label plus a callable that
reverts it — and the global Ctrl+Z (wired in ``MainWindow``) pops and invokes the
most recent one.

Undo callables must be defensive: the panel that made the edit may have been
closed since. Invocation is wrapped in ``try/except`` and a raising callable is
simply skipped, so a stale entry never blocks older, still-valid ones. While an
undo is running, further ``push`` calls are ignored, so a revert that mutates
state can't spawn a new undo entry (which would make Ctrl+Z loop).
"""

from __future__ import annotations

from typing import Callable, Optional

_MAX_DEPTH = 200


class UndoStack:
    """Process-wide singleton stack of ``(label, undo_callable)`` edits."""

    _instance: Optional["UndoStack"] = None

    @classmethod
    def instance(cls) -> "UndoStack":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._stack: list[tuple[str, Callable[[], None]]] = []
        self._suspended = False

    def push(self, label: str, undo: Callable[[], None]) -> None:
        """Record an undoable edit. Ignored while an undo is in progress."""
        if self._suspended:
            return
        self._stack.append((label, undo))
        if len(self._stack) > _MAX_DEPTH:
            del self._stack[0]

    def undo(self) -> Optional[str]:
        """Revert the most recent still-valid edit; return its label, or None
        when nothing could be undone."""
        while self._stack:
            label, fn = self._stack.pop()
            self._suspended = True
            try:
                fn()
                return label
            except Exception:
                continue  # stale/dead target — skip it, try the next
            finally:
                self._suspended = False
        return None

    def can_undo(self) -> bool:
        return bool(self._stack)

    def clear(self) -> None:
        """Drop all pending undo actions (e.g. when a whole layout is swapped)."""
        self._stack.clear()
