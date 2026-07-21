"""Price-alert engine.

A process-wide singleton that watches ``quote:*`` for the symbols named in the
user's alert rules and emits :attr:`AlertEngine.alert_triggered` when a rule's
threshold is crossed. Rules persist in ``QSettings``. Alerts are **edge**
triggered — a rule fires once when its condition becomes true and re-arms only
after the condition goes false again — so a symbol sitting past a threshold
doesn't spam a notification every tick.
"""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QObject, QSettings, Signal

from .datahub import DataHub

_RULES_KEY = "alerts/rules"

FIELDS = ("price", "change_pct")
OPS = ("gt", "lt")
_FIELD_LABEL = {"price": "price", "change_pct": "chg%"}
_OP_LABEL = {"gt": ">", "lt": "<"}


def normalize_rule(raw: dict) -> Optional[dict]:
    """Validate/normalize a rule dict, or None if it's unusable."""
    if not isinstance(raw, dict):
        return None
    symbol = str(raw.get("symbol", "")).strip().upper()
    field = raw.get("field")
    op = raw.get("op")
    if not symbol or field not in FIELDS or op not in OPS:
        return None
    try:
        threshold = float(raw.get("threshold"))
    except (TypeError, ValueError):
        return None
    return {
        "symbol": symbol,
        "field": field,
        "op": op,
        "threshold": threshold,
        "enabled": bool(raw.get("enabled", True)),
    }


def rule_matches(rule: dict, value: float) -> bool:
    return value > rule["threshold"] if rule["op"] == "gt" else value < rule["threshold"]


def rule_message(rule: dict, value: float) -> str:
    """A clear one-line notification, e.g. 'AAPL rose above 200.00 — now 201.35'
    or 'TSLA change fell below -5.00% — now -6.20%'."""
    sym = rule["symbol"]
    direction = "rose above" if rule["op"] == "gt" else "fell below"
    if rule["field"] == "price":
        return f"{sym} {direction} {rule['threshold']:,.2f} — now {value:,.2f}"
    return f"{sym} change {direction} {rule['threshold']:+.2f}% — now {value:+.2f}%"


class AlertEngine(QObject):
    """Singleton quote watcher that fires threshold alerts."""

    alert_triggered = Signal(str)   # human-readable message
    rules_changed = Signal()

    _instance: Optional["AlertEngine"] = None

    @classmethod
    def instance(cls) -> "AlertEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        self._hub = DataHub.instance()
        self._rules: list[dict] = self._load()
        self._fired: dict[int, bool] = {}  # rule index -> currently-past-threshold
        self._resubscribe()

    # -- rule management ---------------------------------------------------

    def rules(self) -> list[dict]:
        return self._rules

    def add_rule(self, rule: dict) -> bool:
        norm = normalize_rule(rule)
        if norm is None:
            return False
        self._rules.append(norm)
        self._save()
        self._resubscribe()
        self.rules_changed.emit()
        return True

    def remove_rule(self, index: int) -> None:
        if 0 <= index < len(self._rules):
            del self._rules[index]
            self._save()
            self._resubscribe()
            self.rules_changed.emit()

    def set_enabled(self, index: int, enabled: bool) -> None:
        if 0 <= index < len(self._rules):
            self._rules[index]["enabled"] = bool(enabled)
            self._save()
            self._resubscribe()
            self.rules_changed.emit()

    # -- persistence -------------------------------------------------------

    def _load(self) -> list[dict]:
        raw = QSettings().value(_RULES_KEY, "", type=str)
        try:
            data = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            data = []
        out = []
        for entry in data if isinstance(data, list) else []:
            norm = normalize_rule(entry)
            if norm is not None:
                out.append(norm)
        return out

    def _save(self) -> None:
        QSettings().setValue(_RULES_KEY, json.dumps(self._rules))

    # -- evaluation --------------------------------------------------------

    def _resubscribe(self) -> None:
        self._hub.unsubscribe_all(self)
        self._fired.clear()
        symbols = {r["symbol"] for r in self._rules if r.get("enabled", True)}
        for sym in symbols:
            self._hub.subscribe(
                self, f"quote:{sym}",
                lambda data, s=sym: self._on_quote(s, data),
                lambda _e: None,
            )

    def _on_quote(self, symbol: str, data) -> None:
        if not isinstance(data, dict):
            return
        for i, rule in enumerate(self._rules):
            if not rule.get("enabled", True) or rule["symbol"] != symbol:
                continue
            value = data.get("price") if rule["field"] == "price" else data.get("change_pct")
            if value is None:
                continue
            hit = rule_matches(rule, float(value))
            if hit and not self._fired.get(i, False):
                self._fired[i] = True
                self.alert_triggered.emit(rule_message(rule, float(value)))
            elif not hit:
                self._fired[i] = False
