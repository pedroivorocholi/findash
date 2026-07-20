"""First-run onboarding / help modal.

A tabbed dialog with a keyboard & mouse cheat sheet and a short dashboard
guide. Shown automatically on first launch (gated by a ``QSettings`` flag) and
on demand from ``Help ▸ Keyboard Shortcuts & Guide…`` or the F1 key.

The cheat sheet is hand-audited against the codebase — every shortcut listed is
one the app actually binds (see ``app.py`` and ``panels/watchlist.py``) plus the
PyQtGraph default chart controls; nothing aspirational.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT, BG_ELEV, CHROME_TEXT, FG, FG_DIM

#: bump the suffix if the content changes enough to warrant re-showing everyone
_SETTINGS_KEY = "has_seen_onboarding_v1"


def _page_css() -> str:
    return f"""
    <style>
      body {{ color: {FG}; font-size: 13px; }}
      h2 {{ color: {ACCENT}; font-size: 15px; margin: 14px 0 4px 0; }}
      p  {{ color: {FG_DIM}; margin: 2px 0 10px 0; }}
      table {{ border-collapse: collapse; margin: 2px 0 12px 0; width: 100%; }}
      td {{ padding: 3px 10px 3px 0; vertical-align: top; }}
      td.k {{ white-space: nowrap; width: 34%; }}
      kbd {{
        background: {BG_ELEV}; color: {CHROME_TEXT};
        border-radius: 3px; padding: 1px 6px; font-family: monospace;
      }}
      td.d {{ color: {FG}; }}
    </style>
    """


def _kbd(*keys: str) -> str:
    return " ".join(f"<kbd>{k}</kbd>" for k in keys)


def _row(keys_html: str, desc: str) -> str:
    return f'<tr><td class="k">{keys_html}</td><td class="d">{desc}</td></tr>'


_SHORTCUTS_HTML = _page_css() + f"""
<body>
<h2>Global</h2>
<table>
  {_row(_kbd("Ctrl", "F"), "Jump to the SYMBOL box and select its text")}
  {_row(_kbd("Enter"), "In the SYMBOL box: send the ticker to every linked panel")}
  {_row(_kbd("F5"), "Refresh all live feeds (quotes, news, charts, financials)")}
  {_row(_kbd("F11"), "Maximize the focused panel — press again to restore")}
  {_row(_kbd("Esc"), "Restore a maximized panel")}
  {_row(_kbd("Ctrl", "W"), "Close the focused panel")}
  {_row(_kbd("Ctrl", "Shift", "T"), "Reopen the last panel you closed")}
  {_row(_kbd("F1"), "Open this Keyboard Shortcuts &amp; Guide window")}
  {_row(_kbd("Ctrl", "S"), "Save the current layout under a name")}
  {_row(_kbd("Ctrl", "Q"), "Quit findash")}
</table>

<h2>Panels &amp; symbols</h2>
<table>
  {_row("Click a row", "Set that symbol for the panel's link group — linked panels follow")}
  {_row("Link badge (top-right)", "Change a panel's link group, or unlink it")}
  {_row(_kbd("Ctrl", "1") + "–" + _kbd("Ctrl", "4"), "Set the focused panel's link group (A/B/C/D)")}
  {_row("Drag a panel tab", "Move &amp; snap it into a new position (panels never float free)")}
  {_row("Middle-click a tab", "Close that panel")}
</table>

<h2>Charts (PyQtGraph defaults)</h2>
<table>
  {_row("Left-drag", "Pan the view")}
  {_row("Mouse wheel", "Zoom in / out")}
  {_row("Right-drag", "Scale the axes independently")}
  {_row("Right-click", "Chart menu — view options, export image/data")}
  {_row("“A” button (bottom-left)", "Auto-range: reset the view to fit the data")}
</table>

<h2>Tables</h2>
<table>
  {_row("Right-click", "Export Table to CSV…")}
  {_row("Click header", "Sort / resize columns (where enabled)")}
  {_row(_kbd("↑"), "/ " + _kbd("↓") + " — move the row selection")}
</table>

<h2>Watchlist</h2>
<table>
  {_row(_kbd("Delete"), "/ " + _kbd("Backspace") + " — remove the selected watchlist row")}
</table>
</body>
"""


_GUIDE_HTML = _page_css() + """
<body>
<h2>Getting started</h2>
<p>Type a ticker (e.g. <b>AAPL</b>, <b>MSFT</b>, <b>ES=F</b>) in the SYMBOL box
at the top and press Enter. Every panel in the same <i>link group</i> updates to
that symbol at once. A fresh install opens to an empty workspace — add panels
from the <b>Panels</b> menu.</p>

<h2>Arranging your workspace</h2>
<p>Drag a panel by its tab to move and snap it beside, above, or below another
panel; drop it onto a tab strip to stack them as tabs. Panels relocate and snap
but never tear off into free-floating windows. Pin a panel to a window edge to
turn it into a slide-out tab. Press <b>F11</b> to focus on one panel full-window,
Esc or F11 to bring the rest back.</p>

<h2>Theme</h2>
<p>Switch between the <b>dark</b> (default) and <b>light</b> theme under
<b>View &#9656; Theme</b>. findash restarts to apply it, so the whole interface —
charts included — matches the theme you pick.</p>

<h2>Symbol search &amp; link groups</h2>
<p>Each panel carries a colored <b>link badge</b> in its top-right corner. Panels
in the same group share a symbol, so clicking a name in one (a mover, a holding,
a commodity) drives the others. Use the badge to move a panel to another group,
or Unlink it so it navigates on its own.</p>

<h2>Tables &amp; CSV export</h2>
<p>Any data table can be exported: right-click it and choose
<b>Export Table to CSV…</b>. The file contains the column headers and every row
exactly as shown. The Financials panel additionally offers styled Excel export
and clipboard copy from its toolbar.</p>

<h2>Layouts</h2>
<p>Use the <b>Layout</b> menu to save the current arrangement under a name
(<b>Ctrl+S</b>), reload a saved one, or reset to the default. Layouts can be
exported to a shareable <code>.findashlayout</code> file and imported on another
machine. Your last arrangement is auto-saved and restored on the next launch.</p>

<h2>Data sources</h2>
<p>findash runs out of the box on free, keyless sources (Yahoo Finance, Google
News — delayed). Connect optional free API keys from the <b>APIs</b> menu
(Finnhub, Twelve Data, FRED, EIA, NewsAPI) for richer, faster data. Press
<b>F5</b> anytime to force-refresh every live feed. Recently-seen data is cached
locally, so panels fill in instantly on the next launch — even offline — before
a fresh refresh runs.</p>
</body>
"""


class OnboardingDialog(QDialog):
    """Tabbed shortcuts + guide modal with a 'don't auto-show' preference."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("findash — Keyboard Shortcuts & Guide")
        self.resize(660, 580)

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._browser(_SHORTCUTS_HTML), "Shortcuts")
        tabs.addTab(self._browser(_GUIDE_HTML), "Dashboard Guide")
        layout.addWidget(tabs, 1)

        self._dont_show = QCheckBox(
            "Don't show this automatically on startup", self
        )
        # pre-checked: first-run shows it once, then it stays out of the way
        # unless the user opens it via F1 / the Help menu.
        self._dont_show.setChecked(True)
        layout.addWidget(self._dont_show)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)  # Close is the only button
        layout.addWidget(buttons)

    def _browser(self, html: str) -> QTextBrowser:
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setHtml(html)
        return browser

    def done(self, result: int) -> None:  # noqa: N802 (Qt override)
        """Persist the auto-show preference on any close (OK / Close / Esc)."""
        QSettings().setValue(_SETTINGS_KEY, self._dont_show.isChecked())
        super().done(result)

    @staticmethod
    def should_auto_show() -> bool:
        """True on first launch (flag unset) — i.e. show the modal once."""
        return not QSettings().value(_SETTINGS_KEY, False, type=bool)
