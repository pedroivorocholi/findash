# Indicator chip: color-on-add + discoverable remove

Date: 2026-07-19
File touched: `aurantium/panels/chart.py`

## Problem

In the chart panel's indicator system (SMA/EMA/BB/VWAP/Volume/RSI/MACD, added
via the "+" button in the INDICATORS row):

1. A newly added indicator always gets an auto-assigned color from
   `INDICATOR_PALETTE`, in rotation. There is no way to choose the color at
   add time — only afterward, via right-click → "Color…" on the chip.
2. An indicator can only be fully removed via right-click → "Remove" on its
   chip. Left-click only toggles visibility (on/off). This path works but
   isn't discoverable — the only hint is a hover tooltip
   ("Click: toggle · right-click: color / edit / remove"). Users who don't
   right-click assume there is no way to delete an indicator, only hide it.

## Scope

Indicators only (the "+" menu / chip system). Chart-type and series colors
(candles/bars/line/area, grid, background — set via the chart's right-click
"Colors" submenu) are unaffected.

## Design

### 1. Color picker when adding an indicator

`_add_indicator_ui(kind)` gains a color-picking step between collecting
params and calling `_add_indicator`:

- New method `_pick_new_indicator_color(label: str) -> Optional[str]`:
  - Seeds `QColorDialog` with `self._next_color()` — the same color that
    would have been auto-assigned today, so accepting the dialog unchanged
    reproduces current behavior.
  - If the user cancels the dialog → return `None`.
  - If the picked color has `lightness() < 60` ("too dark for the black
    canvas") → show the existing status warning, then reopen the dialog
    seeded with the rejected color so the user can adjust and retry. Loop
    until a valid color is chosen or the user cancels.
  - Otherwise return the picked color's hex name.
- `_add_indicator_ui` calls this after collecting `params` (period dialog
  for SMA/EMA/BB/RSI, or immediately for VWAP/Volume/MACD, which currently
  have no dialog at all). If it returns `None`, abort the whole add — no
  indicator, no chip, no side effects. This matches today's behavior when
  the period dialog is canceled.
- Applies uniformly to every indicator kind, including the three
  (VWAP/Volume/MACD) that currently skip any dialog and are added
  instantly.
- `_add_indicator`'s existing `color or self._next_color()` fallback is
  unchanged and still used by:
  - `restore()` when loading a saved layout (colors come from saved state).
  - The three default indicators added in `build()` and `_reset_defaults()`
    (SMA50, SMA200, RSI) — these bypass the UI dialog entirely and keep
    their hardcoded colors.

### 2. Always-visible × remove button on chips

Right-click → Remove continues to work exactly as today (and stays in the
right-click menu for muscle memory). In addition, each chip becomes a small
two-widget container so removal doesn't require discovering right-click:

- `_build_chip` wraps the existing toggle `QPushButton` (label; click =
  show/hide; right-click = Color…/Edit period…/Remove, unchanged) in a
  `QWidget` container with a tight `QHBoxLayout`, plus a new fixed-size
  (16×16) `×` `QPushButton` placed beside it.
  - Style: `FG_DIM` text idle, `DOWN` (theme's down/red) on hover, no
    border, tooltip "Remove".
  - Clicking it calls `_remove_indicator(inst)` directly — no confirmation
    dialog, matching today's right-click Remove (which also has none).
- `_IndicatorInstance` gains a `chip_container` field holding the wrapper
  widget (the `chip` field keeps pointing at the label button itself, since
  `_style_chip`, `_edit_indicator`, and `_show_chip_menu` all reference
  `inst.chip` directly).
- `_remove_indicator` removes/deletes `inst.chip_container` (instead of
  `inst.chip`) from `self._chips_row` — deleting the container cleans up
  both child buttons since they're Qt children of it.
- `QWidget` needs to be added to the `PySide6.QtWidgets` import list in
  `chart.py` (not currently imported there).

## Out of scope

- No confirmation dialog on remove (via × or right-click) — consistent with
  existing behavior.
- No change to the right-click chip menu structure.
- No change to chart-type or series (up/down/line/grid/background) coloring.
- No change to how default indicators (SMA50/SMA200/RSI) are seeded on
  `build()`/`_reset_defaults()`.

## Testing

Manual, in the running app (no automated test suite for this panel):

1. Add each indicator kind via "+"; confirm the color dialog appears, seeded
   with the next palette color, for every kind including VWAP/Volume/MACD.
2. Accept the seeded color unchanged → indicator added with that color
   (same as today's auto-assign).
3. Pick a custom valid color → indicator added with that color; chip border/
   text reflects it.
4. Pick a too-dark color → warning shown, dialog reopens seeded with the
   rejected color; repeat until a valid pick or Cancel.
5. Cancel the color dialog → no indicator added, no chip appears.
6. Cancel the period dialog (SMA/EMA/BB/RSI) → color dialog never opens,
   same as today.
7. Click the × on a chip → indicator fully removed (chip disappears, its
   plot items/pane are gone, `_indicators` no longer contains it) — same end
   state as using right-click → Remove.
8. Right-click menu still offers Color…/Edit period…/Remove and all three
   continue to work as before.
9. Toggle (left-click) still just hides/shows without removing.
