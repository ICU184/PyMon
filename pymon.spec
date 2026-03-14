# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for PyMon."""

a = Analysis(
    ['pymon/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pymon.api',
        'pymon.auth',
        'pymon.core',
        'pymon.models',
        'pymon.sde',
        'pymon.services',
        'pymon.ui',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'numpy.testing',
        'pytest',
        'mypy',
        'ruff',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PyMon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (GUI app)
    icon=None,  # TODO: Add icon file (pymon.ico)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PyMon',
)
