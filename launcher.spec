# -*- mode: python ; coding: utf-8 -*-
# launcher.spec - PyInstaller spec for the launcher (--onefile)

import os

block_cipher = None
ROOT = os.path.abspath('.')

a = Analysis(
    ['launcher/main.py'],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pygame',
        'requests',
        'launcher',
        'launcher.config',
        'launcher.version_checker',
        'launcher.updater',
        'launcher.ui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'email',
        'html',
        'xml',
        'pydoc',
        'doctest',
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
