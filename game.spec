# -*- mode: python ; coding: utf-8 -*-
# game.spec - PyInstaller spec for the game (--onedir)

import os

block_cipher = None
ROOT = os.path.abspath('.')

a = Analysis(
    ['main.py'],
    pathex=[ROOT],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('tracks', 'tracks'),
        ('brushes', 'brushes'),
    ],
    hiddenimports=[
        'game',
        'settings',
        'race_progress',
        'track_manager',
        'tile_defs',
        'tile_meta',
        'tile_track',
        'tile_brush',
        'tile_collision',
        'editor',
        'editor_collision',
        'editor_panels',
        'entities',
        'entities.car',
        'entities.track',
        'entities.powerup',
        'entities.particles',
        'systems',
        'systems.input_handler',
        'systems.physics',
        'systems.collision',
        'systems.camera',
        'systems.ai',
        'utils',
        'utils.base_path',
        'utils.sprites',
        'utils.helpers',
        'utils.timer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'email',
        'html',
        'http',
        'xml',
        'pydoc',
        'doctest',
        'launcher',
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='game',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='game',
)
