# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds a standalone aurantium app.

Windows:  .venv\\Scripts\\pyinstaller aurantium.spec --noconfirm  ->  dist\\aurantium.exe
macOS:    .venv/bin/pyinstaller aurantium.spec --noconfirm        ->  dist/aurantium.app
(Run PyInstaller on the target OS — you can't cross-build a Mac app from Windows.)
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all

IS_MAC = sys.platform == "darwin"

# Make the app package importable while this spec is parsed.
_APP_DIR = os.path.abspath(os.getcwd())
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# Per-OS app icon (.icns for the macOS .app, .ico for the Windows .exe).
_ICON = "aurantium.icns" if IS_MAC else "aurantium.ico"
if not os.path.exists(_ICON):
    _ICON = None

datas = [("layouts", "layouts"), (".env.example", ".")]
for _asset in ("aurantium.ico", "aurantium.icns"):
    if os.path.exists(_asset):
        datas.append((_asset, "."))
binaries = []
# QtNetwork drives the single-instance QLocalServer/QLocalSocket guard in
# __main__.py. It's the only PySide6 module reached solely via runtime import,
# so PyInstaller's PySide6 hook won't detect it — list it explicitly.
hiddenimports = ["PySide6.QtNetwork"]

# WinSparkle auto-updater DLL (Windows only). Drop the 64-bit WinSparkle.dll
# next to this spec — see RELEASING.md. Bundled at the app root so
# updater.py can load it from BUNDLE_DIR at runtime.
if not IS_MAC and os.path.exists("WinSparkle.dll"):
    binaries.append(("WinSparkle.dll", "."))

# Panels are imported dynamically at runtime (importlib), so PyInstaller's
# static analysis never sees them — list them explicitly from the package's
# BUILTIN table. (collect_submodules can't help: it runs in an isolated
# subprocess that cannot import the non-installed `aurantium` package.)
from aurantium.panels import BUILTIN as _PANELS

hiddenimports += ["aurantium.panels", "aurantium.panels._news_common"]
hiddenimports += [f"aurantium.panels.{m}" for m in _PANELS]
hiddenimports += [
    "aurantium.providers",
    "aurantium.providers.econ",
    "aurantium.providers.fundamentals",
    "aurantium.providers.market",
    "aurantium.providers.news",
]
# Shared UI components (imported by panels) and the onboarding dialog (imported
# lazily inside app.py). Listed explicitly so the frozen build never misses them.
hiddenimports += [
    "aurantium.components",
    "aurantium.components.market_table",
    "aurantium.onboarding_dialog",
    "aurantium.alerts",
    "aurantium.command_bar",
    "aurantium.undo",
]

# yfinance / news deps that static analysis under-collects.
hiddenimports += [
    "multitasking", "frozendict", "peewee", "platformdirs",
    "websockets", "html5lib", "bs4",
    "openpyxl",  # imported lazily by the Financials xlsx export
]

# Packages with data files or native binaries to bundle fully.
for _pkg in ("yfinance", "gnews", "feedparser", "curl_cffi", "PySide6QtAds"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

a = Analysis(
    ["run_aurantium.py"],
    pathex=[_APP_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# One-FOLDER build (dist/aurantium/): the exe runs directly from the install
# dir with its DLLs in _internal/ beside it — no per-launch %TEMP% unpack.
# That means instant startup and, crucially, a reliable relaunch when the
# installer starts the app after a silent auto-update (a one-file exe unpacking
# 100 MB in the installer's context is what broke the post-update relaunch).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aurantium",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="aurantium",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="aurantium.app",
        icon=_ICON,
        bundle_identifier="aurantium.terminal.desktop",
        info_plist={
            "CFBundleName": "aurantium",
            "CFBundleDisplayName": "aurantium",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.finance",
        },
    )
