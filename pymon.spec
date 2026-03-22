# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for PyMon."""

import certifi

a = Analysis(
    ['pymon/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        # certifi CA bundle – needed for HTTPS in frozen builds
        (certifi.where(), 'certifi'),
    ],
    hiddenimports=[
        # ── PyMon sub-packages ──
        'pymon.api',
        'pymon.auth',
        'pymon.core',
        'pymon.models',
        'pymon.sde',
        'pymon.services',
        'pymon.ui',
        # ── Qt extras ──
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        # ── HTTP / SSO / JWT ──
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'httpcore',
        'httpcore._async',
        'httpcore._sync',
        'h11',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        'certifi',
        'idna',
        'jwt',
        'jwt.algorithms',
        'jwt.api_jwt',
        'jwt.api_jws',
        'jwt.jwks_client',
        # ── Callback server (uvicorn + starlette) ──
        'uvicorn',
        'uvicorn.config',
        'uvicorn.server',
        'uvicorn.main',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.logging',
        'starlette',
        'starlette.applications',
        'starlette.requests',
        'starlette.responses',
        'starlette.routing',
        'starlette.types',
        'starlette.datastructures',
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
