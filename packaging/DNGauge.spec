# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

SCRIPT_DIR = (Path(os.getcwd()) / "packaging").resolve()
PROJECT_ROOT = SCRIPT_DIR.parent

hiddenimports = []
hiddenimports += collect_submodules("pidng")
hiddenimports += collect_submodules("rawpy")

binaries = []
binaries += collect_dynamic_libs("rawpy")

datas = []
for asset_name in ["DNGauge.png", "DNGauge.ico"]:
    asset_path = SCRIPT_DIR / asset_name
    if asset_path.exists():
        datas.append((str(asset_path), "."))

extra_linux_libs = [
    "/home/wenjingxun/app/miniconda3/envs/dng_compare/lib/libxcb-xinerama.so.0",
]

for lib_path in extra_linux_libs:
    if os.path.exists(lib_path):
        binaries.append((lib_path, "."))


a = Analysis(
    [str(PROJECT_ROOT / "shotwell_compare.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DNGauge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon=str(SCRIPT_DIR / "DNGauge.ico") if (SCRIPT_DIR / "DNGauge.ico").exists() else None,
    codesign_identity=None,
    entitlements_file=None,
)
