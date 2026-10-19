# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
# pyinstaller --noconfirm StatueMaker.spec   ->  dist/StatueMaker.exe

a = Analysis(
    ['statuemaker.py'],
    pathex=['tools'],
    binaries=[],
    datas=[('tools', 'tools')] + collect_data_files('archspec'),   # etcpak (BC7) picks its CPU build via archspec
    hiddenimports=['conv', 'gl', 'preview', 'rd', 'standalone', 'orient', 'bc7', 'etcpak', 'PIL.ImageTk', 'fast_simplification', 'scipy.spatial._ckdtree'] + collect_submodules('etcpak') + collect_submodules('archspec'),
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
    name='StatueMaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
