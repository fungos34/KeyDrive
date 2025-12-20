# -*- mode: python ; coding: utf-8 -*-

# Import constants for configurable naming
GUI_EXE_NAME = 'KeyDriveGUI'


a = Analysis(
    ['gui_launcher.py'],
    pathex=['scripts'],
    binaries=[],
    datas=[('static', 'static'), ('scripts', 'scripts')],
    hiddenimports=['PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets'],
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
    name=GUI_EXE_NAME,
    icon='static/LOGO_main.ico',
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
    codesign_identity=None,
    entitlements_file=None,
)
