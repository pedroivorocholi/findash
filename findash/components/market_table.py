"""MarketTable — the shared table widget used by findash's data panels.

A thin ``QTableWidget`` subclass that bakes in the terminal's table conventions
(read-only, row selection, no vertical header, zebra striping, no grid) and adds
two things every data panel wants:

* a **loading overlay** — ``set_loading(True)`` dims the table and shows a
  "Loading…" indicator while a fetch is in flight;
* a right-click **"Export Table to CSV…"** action.

Panels construct it like a normal table (``MarketTable(rows, cols, self)``), set
their own header labels, and populate cells as usual — they just drop the
repeated configuration boilerplate.

Note on the overlay: an item view paints its rows on ``viewport()``, not on the
widget itself, so overriding ``MarketTable.paintEvent`` would only cover the
frame. The overlay is therefore a small transparent child of the viewport with
its own ``paintEvent`` — the correct, flicker-free way to draw over the rows.
"""

from __future__ import annotations

import csv

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QMenu,
    QMessageBox,
    QTableWidget,
    QWidget,
)

from ..theme import ACCENT


class _LoadingOverlay(QWidget):
    """Semi-transparent veil + centered 'Loading…' label, sized to the viewport."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # let clicks/scroll pass through to the table underneath
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))  # dim the rows beneath
        f = self.font()
        f.setPointSizeF(max(f.pointSizeF() + 1.0, 10.0))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(ACCENT))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Loading…")
        p.end()


class MarketTable(QTableWidget):
    """QTableWidget with findash defaults, a loading overlay, and CSV export."""

    def __init__(
        self, rows: int = 0, cols: int = 0, parent: QWidget | None = None
    ) -> None:
        super().__init__(rows, cols, parent)
        self._loading = False

        # -- shared table conventions (previously copied into every panel) --
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setHighlightSections(False)

        # -- right-click CSV export -----------------------------------------
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # -- loading overlay (child of the viewport, see module docstring) --
        self._overlay = _LoadingOverlay(self.viewport())
        # track viewport resizes too — a scrollbar appearing/disappearing
        # resizes the viewport without resizing the table widget itself.
        self.viewport().installEventFilter(self)

    # -- loading state ------------------------------------------------------

    def set_loading(self, loading: bool) -> None:
        """Show/hide the 'Loading…' overlay. Idempotent."""
        loading = bool(loading)
        if loading == self._loading:
            return
        self._loading = loading
        if loading:
            self._overlay.setGeometry(self.viewport().rect())
            self._overlay.show()
            self._overlay.raise_()
        else:
            self._overlay.hide()

    @property
    def is_loading(self) -> bool:
        return self._loading

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._loading:
            self._overlay.setGeometry(self.viewport().rect())

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if (
            self._loading
            and obj is self.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._overlay.setGeometry(self.viewport().rect())
        return super().eventFilter(obj, event)

    # -- CSV export ---------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        export_act = menu.addAction("Export Table to CSV…")
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is export_act:
            self._export_csv()

    def _export_csv(self) -> None:
        rows, cols = self.rowCount(), self.columnCount()
        if rows == 0 or cols == 0:
            QMessageBox.information(
                self, "Export Table to CSV", "The table is empty — nothing to export."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Table to CSV",
            "table.csv",
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return

        headers = []
        for c in range(cols):
            item = self.horizontalHeaderItem(c)
            headers.append(item.text() if item is not None else f"Column {c + 1}")

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(headers)
                for r in range(rows):
                    cells = [self.item(r, c) for c in range(cols)]
                    writer.writerow(
                        [cell.text() if cell is not None else "" for cell in cells]
                    )
        except OSError as exc:
            QMessageBox.warning(
                self, "Export Table to CSV", f"Couldn't write the file:\n{exc}"
            )
            return
