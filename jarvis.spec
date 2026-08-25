# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for JARVIS.

The tricky part of this build is that several dependencies load things at
runtime that a static analyser cannot see:

  * openwakeword ships its ONNX models as package data and resolves them by
    path, so the whole package directory has to come along.
  * onnxruntime and ctranslate2 (under faster-whisper) load native shared
    libraries via their own loaders.
  * piper reads its espeak-ng phoneme data from package data.
  * scipy / scikit-learn, pulled in by openwakeword, import submodules lazily.

Anything missed here shows up as a "module not found" crash on the user's
machine, never at build time - hence the explicit lists.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
binaries = []
hiddenimports = []

# Only packages that resolve their own data files by path at runtime need
# collecting by hand. Everything else - onnxruntime, ctranslate2,
# faster-whisper, PyAV, numpy, scipy, scikit-learn - is handled by
# PyInstaller's own hooks, and collect_all() on top of those is actively
# harmful: it re-collects shared binaries under a second set of paths, and the
# duplicate registration makes CPython refuse the extension with "cannot load
# module more than once per process". numpy dies that way, and every package
# that imports it dies after.
for package in ("openwakeword", "piper"):
    try:
        datas += collect_data_files(package)
        hiddenimports += collect_submodules(package)
    except Exception as exc:  # a missing optional package shouldn't kill the build
        print(f"[spec] skipping {package}: {exc}")

# Lazily-imported submodules the analyser won't follow.
hiddenimports += collect_submodules("scipy.special")
hiddenimports += [
    "sklearn.utils._typedefs",
    "sklearn.utils._heap",
    "sklearn.utils._sorting",
    "sklearn.utils._vector_sentinel",
    "sklearn.neighbors._partition_nodes",
    "scipy._lib.messagestream",
    "scipy.io",
    "av",
    "anthropic",
    "httpx",
    "h11",
    "sounddevice",
    "send2trash",
    "psutil",
    "yaml",
    "bs4",
]
hiddenimports += collect_submodules("jarvis")

# sounddevice bundles PortAudio as package data on Windows.
try:
    datas += collect_data_files("_sounddevice_data")
except Exception:
    pass

# Our own defaults, so a fresh install has something to copy from.
datas += [("config.example.yaml", "."), ("README.md", ".")]

# Entry point is run.py, NOT jarvis/__main__.py. PyInstaller executes the entry
# script as top-level "__main__" rather than as a module inside its package, so
# jarvis/__main__.py's relative imports ("from .config import ...") raise
# ImportError the instant the frozen app starts. run.py imports the package
# absolutely, which keeps the package context intact.
a = Analysis(
    ["run.py"],
    pathex=[os.path.dirname(os.path.abspath(SPEC))],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt ships several large modules we never touch; dropping them saves
    # roughly 150 MB in the installer.
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtQuick3D",
        "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtDesigner",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "matplotlib", "tkinter", "PIL", "pytest", "torch", "tensorflow",
        # webrtcvad is optional and detected at runtime. Excluding it keeps
        # PyInstaller from loading the bundled hook-webrtcvad.py, which calls
        # copy_metadata("webrtcvad") and dies when only the renamed
        # webrtcvad-wheels fork is installed.
        "webrtcvad",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# Two executables from one analysis:
#   JARVIS.exe          windowed - no console flashes up behind the dashboard
#   JARVIS-console.exe  console  - the same app, but you can read `doctor`
#                                  output and any crash message
def build_exe(name: str, console: bool):
    return EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon="assets/jarvis.ico" if sys.platform == "win32" else None,
    )


exe_gui = build_exe("JARVIS", console=False)
exe_console = build_exe("JARVIS-console", console=True)

coll = COLLECT(
    exe_gui,
    exe_console,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JARVIS",
)
