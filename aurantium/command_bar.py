"""The command bar: a QLineEdit with Up/Down history and Tab/prefix completion.

The owning window supplies a ``completions`` callback (panel ids, saved layout
names, watchlist symbols, slash-commands) so the bar stays agnostic about what
can be completed. History persists in QSettings across sessions.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QSettings, QStringListModel
from PySide6.QtWidgets import QCompleter, QLineEdit

_HISTORY_KEY = "command_bar/history"
_MAX_HISTORY = 50


class CommandBar(QLineEdit):
    """Ticker/command entry with history recall and completion."""

    def __init__(
        self,
        parent=None,
        completions: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._completions = completions or (lambda: [])

        stored = QSettings().value(_HISTORY_KEY, [], type=list) or []
        self._history: list[str] = [str(h) for h in stored][-_MAX_HISTORY:]
        self._history_idx = len(self._history)  # past the end == current draft
        self._draft = ""

        self._model = QStringListModel(self)
        completer = QCompleter(self._model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(completer)
        self.textEdited.connect(lambda _t=None: self.refresh_completions())

    # -- completion --------------------------------------------------------

    def refresh_completions(self) -> None:
        try:
            items = [str(x) for x in self._completions()]
        except Exception:
            items = []
        self._model.setStringList(items)

    # -- history -----------------------------------------------------------

    def push_history(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            del self._history[:-_MAX_HISTORY]
            QSettings().setValue(_HISTORY_KEY, self._history)
        self._history_idx = len(self._history)

    def _history_prev(self) -> None:
        if not self._history:
            return
        if self._history_idx == len(self._history):
            self._draft = self.text()  # remember what was being typed
        if self._history_idx > 0:
            self._history_idx -= 1
            self.setText(self._history[self._history_idx])

    def _history_next(self) -> None:
        if self._history_idx >= len(self._history):
            return
        self._history_idx += 1
        if self._history_idx == len(self._history):
            self.setText(self._draft)
        else:
            self.setText(self._history[self._history_idx])

    # -- keys --------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        key = event.key()
        completer = self.completer()
        popup = completer.popup() if completer else None

        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            if completer and self.text():
                completer.setCompletionPrefix(self.text())
                if completer.completionCount() > 0:
                    completer.setCurrentRow(0)
                    self.setText(completer.currentCompletion())
                    if popup is not None:
                        popup.hide()
                    return
            super().keyPressEvent(event)
            return

        # while the completion popup is open, let it own Up/Down/Enter/Esc
        if popup is not None and popup.isVisible():
            super().keyPressEvent(event)
            return

        if key == Qt.Key.Key_Up:
            self._history_prev()
            return
        if key == Qt.Key.Key_Down:
            self._history_next()
            return
        super().keyPressEvent(event)
