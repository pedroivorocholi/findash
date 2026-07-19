# Indicator Chip Color-on-Add + Discoverable Remove Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick an indicator's color at the moment they add it to the chart, and give every indicator chip an always-visible × button so removing it doesn't require discovering the right-click menu.

**Architecture:** Both changes live entirely in `findash/panels/chart.py`, inside the `ChartPanel` class and its `_IndicatorInstance` helper. No new files, no new dependencies — `QColorDialog` and `QWidget` (PySide6) cover both changes.

**Tech Stack:** Python, PySide6 (Qt widgets), pyqtgraph. No test framework in this repo — `findash` is a GUI app verified by running it (`.venv\Scripts\python -m findash`) and exercising the flow by hand; there is no pytest/unittest suite to extend.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-19-indicator-chip-color-and-remove-design.md`
- Scope is indicators only (the "+" menu / chip system) — chart-type and series colors (candles/bars/line/grid/background) are untouched.
- No confirmation dialogs on remove (× or right-click) — matches existing behavior.
- The too-dark rule (`QColor.lightness() < 60` is rejected) already exists for recoloring (`_recolor_indicator`) and must be reused for the new add-time picker, with the same status message text style.
- All edits target `findash/panels/chart.py`; line numbers below are from the file's current state (1333 lines) and will shift slightly as earlier tasks land — re-locate by the surrounding code shown, not by line number alone.

---

### Task 1: Color picker when adding an indicator

**Files:**
- Modify: `findash/panels/chart.py:17-29` (imports — no change needed here, `QColorDialog` is already imported)
- Modify: `findash/panels/chart.py:641-652` (`_add_indicator_ui`)

**Interfaces:**
- Consumes: `self._next_color() -> str` (chart.py:627-630, already exists — returns next hex color from `INDICATOR_PALETTE` and advances the rotation), `self.set_status(msg: str) -> None` (existing `Panel` method used elsewhere in this file, e.g. chart.py:721), `INDICATOR_SPECS[kind].label -> str` (existing).
- Produces: new method `_pick_new_indicator_color(self, label: str) -> Optional[str]` on `ChartPanel`, used only within this file by `_add_indicator_ui`.

- [x] **Step 1: Add the color-picking helper method**

Insert this new method directly after `_next_color` (chart.py:627-630), before `_show_add_menu`:

```python
    def _pick_new_indicator_color(self, label: str) -> Optional[str]:
        """Prompt for a color when adding a new indicator, seeded with the
        next palette color. Loops on too-dark picks (same rule as
        recoloring) until a valid color is chosen or the user cancels."""
        seed = self._next_color()
        while True:
            picked = QColorDialog.getColor(QColor(seed), self, f"{label} color")
            if not picked.isValid():
                return None
            if picked.lightness() < 60:
                self.set_status("⚠ too dark for the black canvas — pick a lighter color")
                seed = picked.name()
                continue
            return picked.name()
```

- [x] **Step 2: Wire it into `_add_indicator_ui`**

Replace the current body of `_add_indicator_ui` (chart.py:641-652):

```python
    def _add_indicator_ui(self, kind: str) -> None:
        spec = INDICATOR_SPECS[kind]
        params: dict = {}
        if spec.default_window is not None:
            window, ok = QInputDialog.getInt(
                self, f"{spec.label} period", "Period (bars):",
                spec.default_window, 2, 500,
            )
            if not ok:
                return
            params["window"] = window
        self._add_indicator(kind, params)
```

with:

```python
    def _add_indicator_ui(self, kind: str) -> None:
        spec = INDICATOR_SPECS[kind]
        params: dict = {}
        if spec.default_window is not None:
            window, ok = QInputDialog.getInt(
                self, f"{spec.label} period", "Period (bars):",
                spec.default_window, 2, 500,
            )
            if not ok:
                return
            params["window"] = window
        color = self._pick_new_indicator_color(spec.label)
        if color is None:
            return
        self._add_indicator(kind, params, color=color)
```

- [x] **Step 3: Manually verify**

Run: `.venv\Scripts\python -m findash`

In the running app, open the Chart panel for any symbol and, for each of the following, click "+" in the INDICATORS row:

1. Add "SMA…" → enter a period → a color dialog appears, seeded with a palette color → click OK unchanged → chip appears with that exact color (border + text).
2. Add "EMA…" → same, but this time pick a different, valid (light enough) color → chip reflects the picked color.
3. Add "VWAP" (no period prompt) → color dialog still appears immediately → confirm a color → chip appears.
4. Add "MACD" → color dialog appears → pick a color with lightness < 60 (e.g. near-black) → confirm the status bar shows the "⚠ too dark…" warning and the dialog reopens → pick a valid color → indicator is added.
5. Add "BB…" → enter a period → in the color dialog, click Cancel → confirm no chip is added and no error is raised.
6. Add "RSI…" → in the period dialog, click Cancel → confirm the color dialog never opens and no chip is added (unchanged prior behavior).

Expected: all six behave as described, no exceptions in the console.

- [x] **Step 4: Commit**

```bash
git add findash/panels/chart.py
git commit -m "feat: let user pick indicator color when adding it to the chart"
```

---

### Task 2: Always-visible × remove button on indicator chips

**Files:**
- Modify: `findash/panels/chart.py:186-201` (`_IndicatorInstance.__init__`)
- Modify: `findash/panels/chart.py:17-29` (import `QWidget`)
- Modify: `findash/panels/chart.py:666-680` (`_build_chip`)
- Modify: `findash/panels/chart.py:741-746` (`_remove_indicator`)

**Interfaces:**
- Consumes: `self._chips_row: QHBoxLayout` (existing, chart.py:469), `self._add_btn: QPushButton` (existing, chart.py:470-473), `self._style_chip(inst) -> None` (existing, chart.py:682-692), `self._show_chip_menu(inst, pos) -> None` (existing, chart.py:694-707), `self._on_chip_toggled(inst, checked) -> None` (existing, chart.py:709-714), `self._remove_indicator(inst) -> None` (this task modifies it), theme constants `FG_DIM`, `DOWN` (already imported, chart.py:32).
- Produces: `_IndicatorInstance.chip_container: Optional[QWidget]` — new field other tasks/future code can rely on to find the chip's wrapper widget; `inst.chip` keeps its existing meaning (the label/toggle button itself) so `_style_chip`, `_edit_indicator`, `_show_chip_menu` need no changes.

- [x] **Step 1: Add `QWidget` to the imports**

In the `from PySide6.QtWidgets import (...)` block (chart.py:17-29), add `QWidget` after `QVBoxLayout`:

```python
from PySide6.QtWidgets import (
    QColorDialog,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
```

- [x] **Step 2: Add the `chip_container` field**

In `_IndicatorInstance.__init__` (chart.py:191-201), add a line right after `self.chip`:

```python
    def __init__(self, kind: str, params: dict, color: str, on: bool = True) -> None:
        self.uid = next(self._uid_counter)
        self.kind = kind
        self.params = dict(params)
        self.color = color
        self.on = on
        self.chip: Optional[QPushButton] = None
        self.chip_container: Optional[QWidget] = None
        self.pane: Optional[pg.PlotWidget] = None  # osc indicators only
        self.items: list = []       # pg items on the price plot
        self.pane_items: list = []  # pg items inside self.pane
```

- [x] **Step 3: Rebuild `_build_chip` to wrap the toggle button and a × button in a container**

Replace the current `_build_chip` (chart.py:666-680):

```python
    def _build_chip(self, inst: _IndicatorInstance) -> None:
        chip = QPushButton(inst.label(), self)
        chip.setCheckable(True)
        chip.setChecked(inst.on)
        chip.toggled.connect(lambda checked, i=inst: self._on_chip_toggled(i, checked))
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, i=inst: self._show_chip_menu(i, pos)
        )
        chip.setToolTip("Click: toggle · right-click: color / edit / remove")
        # insert before the "+" button
        idx = self._chips_row.indexOf(self._add_btn)
        self._chips_row.insertWidget(idx, chip)
        inst.chip = chip
        self._style_chip(inst)
```

with:

```python
    def _build_chip(self, inst: _IndicatorInstance) -> None:
        container = QWidget(self)
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        chip = QPushButton(inst.label(), self)
        chip.setCheckable(True)
        chip.setChecked(inst.on)
        chip.toggled.connect(lambda checked, i=inst: self._on_chip_toggled(i, checked))
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, i=inst: self._show_chip_menu(i, pos)
        )
        chip.setToolTip("Click: toggle · right-click: color / edit / remove")
        row.addWidget(chip)

        close_btn = QPushButton("×", container)
        close_btn.setFixedSize(16, 16)
        close_btn.setToolTip("Remove")
        close_btn.setStyleSheet(
            f"QPushButton {{ color: {FG_DIM}; border: none; font-weight: bold; }}"
            f"QPushButton:hover {{ color: {DOWN}; }}"
        )
        close_btn.clicked.connect(lambda: self._remove_indicator(inst))
        row.addWidget(close_btn)

        # insert before the "+" button
        idx = self._chips_row.indexOf(self._add_btn)
        self._chips_row.insertWidget(idx, container)
        inst.chip = chip
        inst.chip_container = container
        self._style_chip(inst)
```

- [x] **Step 4: Update `_remove_indicator` to remove the container**

Replace the current `_remove_indicator` (chart.py:741-746):

```python
    def _remove_indicator(self, inst: _IndicatorInstance) -> None:
        self._teardown_indicator_items(inst)
        if inst.chip is not None:
            self._chips_row.removeWidget(inst.chip)
            inst.chip.deleteLater()
        self._indicators.remove(inst)
```

with:

```python
    def _remove_indicator(self, inst: _IndicatorInstance) -> None:
        self._teardown_indicator_items(inst)
        if inst.chip_container is not None:
            self._chips_row.removeWidget(inst.chip_container)
            inst.chip_container.deleteLater()
        self._indicators.remove(inst)
```

- [x] **Step 5: Manually verify**

Run: `.venv\Scripts\python -m findash`

In the running app, open the Chart panel for any symbol:

1. Confirm the three default indicators (SMA 50, SMA 200, RSI 14) each show their label chip plus a small `×` beside it.
2. Click a chip's label (not the ×) → it toggles on/off as before (background/border style changes); the indicator is not removed.
3. Click the `×` on a chip → the chip and its `×` both disappear immediately; for an overlay indicator (e.g. SMA) confirm its line vanishes from the price plot; for a paned indicator (e.g. RSI) confirm its whole sub-pane disappears.
4. Add a new indicator via "+" (exercising Task 1's flow) → confirm its chip also has a working `×`.
5. Right-click a chip → confirm the Color…/Edit period…/Remove menu still opens and each entry still works (Remove from the menu also fully removes the chip+×, same as clicking ×).
6. Hover the `×` → confirm it changes to the theme's "down" red color; move away → confirm it returns to the dim color.

Expected: all six behave as described, no exceptions in the console, no leftover chip artifacts in the INDICATORS row after removal.

- [x] **Step 6: Commit**

```bash
git add findash/panels/chart.py
git commit -m "feat: add always-visible remove button to indicator chips"
```

---

## Self-Review Notes

- **Spec coverage:** Spec section 1 (color picker on add) → Task 1. Spec section 2 (× remove button) → Task 2. "Out of scope" items (no confirmation dialogs, no chart-type/series color changes, no right-click menu restructuring, no change to default-indicator seeding) are respected — no task touches `_recolor_indicator`, `_pick_color`, `_apply_colors`, `build()`'s default `_add_indicator` calls, or `_reset_defaults()`.
- **Placeholder scan:** No TBD/TODO; every step has complete, copy-pasteable code and exact manual-verification instructions (no automated test suite exists in this repo to write `pytest` steps against).
- **Type consistency:** `_pick_new_indicator_color(self, label: str) -> Optional[str]` (Task 1) matches its call site `color = self._pick_new_indicator_color(spec.label)` where `spec.label: str` (from `_IndicatorSpec`, chart.py:169). `inst.chip_container: Optional[QWidget]` (Task 2, Step 2) matches its use in `_build_chip` (Step 3: `inst.chip_container = container`) and `_remove_indicator` (Step 4: `inst.chip_container is not None`). `inst.chip` keeps type `Optional[QPushButton]` throughout — unchanged by either task.
