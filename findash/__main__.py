"""Entry point: ``python -m findash``."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from .paths import BUNDLE_DIR, EXT_DIR

APP_ID = "findash.terminal.desktop.1"


def _set_windows_app_id() -> None:
    """Give Windows an explicit AppUserModelID so the taskbar treats findash
    as its own application — its own icon, its own grouping — instead of
    folding it into the generic ``pythonw.exe`` host process."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # pragma: no cover - cosmetic only
        pass


def _install_crash_logging() -> None:
    """Always record unhandled exceptions to a size-capped ``findash.log`` next to
    the app, so a crash leaves a trace even without FINDASH_DEBUG. Additive — it
    doesn't redirect normal stdout/stderr. PySide6 routes unhandled slot
    exceptions through ``sys.excepthook``, so Qt-callback crashes are captured too."""
    import threading
    import traceback as _tb

    log_path = EXT_DIR / "findash.log"

    def _write(header: str, text: str) -> None:
        try:
            if log_path.exists() and log_path.stat().st_size > 512 * 1024:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-256 * 1024:]
                log_path.write_text(tail, encoding="utf-8")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n{header}\n{text}\n")
        except OSError:
            pass

    def _excepthook(exc_type, exc, tb) -> None:
        _write(
            "=== unhandled exception ===",
            "".join(_tb.format_exception(exc_type, exc, tb)),
        )
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    _default_thread_hook = threading.excepthook

    def _thread_hook(args) -> None:
        _write(
            "=== unhandled thread exception ===",
            "".join(
                _tb.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback
                )
            ),
        )
        _default_thread_hook(args)  # keep default stderr behavior / SystemExit handling

    try:
        threading.excepthook = _thread_hook
    except Exception:
        pass


def _maybe_capture_output() -> None:
    """A frozen build has no console. When FINDASH_DEBUG is set, tee stdout/err
    to a log next to the exe so tracebacks (incl. panel build failures) surface."""
    if os.environ.get("FINDASH_DEBUG"):
        try:
            f = open(EXT_DIR / "findash_stderr.log", "w", encoding="utf-8")
            sys.stdout = f
            sys.stderr = f
        except OSError:
            pass


def main() -> int:
    _maybe_capture_output()
    _install_crash_logging()
    load_dotenv(EXT_DIR / ".env")
    _set_windows_app_id()

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("findash")
    app.setOrganizationName("findash")

    from PySide6.QtGui import QIcon

    icon_path = BUNDLE_DIR / "findash.ico"
    app_icon = QIcon(str(icon_path)) if icon_path.is_file() else None
    if app_icon is not None:
        app.setWindowIcon(app_icon)

    from .theme import apply_theme

    apply_theme(app)

    # Providers first (so panels' initial subscriptions resolve), then panels.
    from .providers import register_all_providers

    register_all_providers()

    from .panel import PanelRegistry, discover_panels

    # Built-in panels load as a package (frozen-safe); a user's optional
    # ``user_panels`` folder next to the app is scanned by file path.
    errors = discover_panels(
        [EXT_DIR / "user_panels"], packages=("findash.panels",)
    )
    for err in errors:
        print(f"[findash] panel failed to load:\n{err}", file=sys.stderr)

    from .app import MainWindow

    win = MainWindow()
    if app_icon is not None:
        win.setWindowIcon(app_icon)
    # launch filling the screen; the 1500x900 set in MainWindow stays as the
    # un-maximized size when the user restores the window
    win.showMaximized()

    startup_err = ""
    try:
        win.default_startup()
    except Exception:
        import traceback as _tb

        startup_err = _tb.format_exc()

    if os.environ.get("FINDASH_DEBUG") or startup_err or errors:
        try:
            default_json = BUNDLE_DIR / "layouts" / "default.json"
            (EXT_DIR / "findash_startup.log").write_text(
                f"frozen: {getattr(sys, 'frozen', False)}\n"
                f"panels registered: {len(PanelRegistry.all())}\n"
                f"BUNDLE_DIR: {BUNDLE_DIR}\n"
                f"default.json exists: {default_json.is_file()}\n"
                f"docks created: {len(win._docks)}\n\n"
                f"discover errors:\n" + "\n".join(errors) + "\n\n"
                f"startup error:\n" + startup_err,
                encoding="utf-8",
            )
        except OSError:
            pass

    # First run: show the onboarding guide once, then offer the API-keys dialog
    # (both no-ops after first launch / once keys are connected). Delayed so the
    # window paints first; run sequentially since each dialog is modal.
    from PySide6.QtCore import QTimer

    def _first_run_dialogs() -> None:
        win.maybe_show_onboarding()
        win.maybe_prompt_api_keys()

    QTimer.singleShot(600, _first_run_dialogs)

    # Auto-update: silent daily check via WinSparkle (Windows only; a no-op if
    # the updater isn't configured/available). Cleaned up after the event loop.
    from . import updater

    updater.init()
    try:
        return app.exec()
    finally:
        updater.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
