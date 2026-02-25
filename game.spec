# -*- mode: python ; coding: utf-8 -*-
# game.spec - PyInstaller spec for the game (--onedir)

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
ROOT = os.path.abspath('.')

# Collect ALL files for RL dependencies (submodules, data, binaries)
gymnasium_datas, gymnasium_binaries, gymnasium_hiddenimports = collect_all('gymnasium')
sb3_datas, sb3_binaries, sb3_hiddenimports = collect_all('stable_baselines3')
cloudpickle_hiddenimports = collect_submodules('cloudpickle')

a = Analysis(
    ['main.py'],
    pathex=[ROOT],
    binaries=gymnasium_binaries + sb3_binaries,
    datas=[
        ('assets', 'assets'),
        ('tracks', 'tracks'),
        ('brushes', 'brushes'),
        ('models', 'models'),
    ] + gymnasium_datas + sb3_datas,
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
        'training',
        'training.racing_env',
        'training.train_ai',
    ] + gymnasium_hiddenimports + sb3_hiddenimports + cloudpickle_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
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
