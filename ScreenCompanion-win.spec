# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

ROOT = os.path.dirname(os.path.abspath(SPEC))

ctk_path = os.path.join(ROOT, 'venv', 'Lib', 'site-packages', 'customtkinter')
assets_dir = os.path.join(ROOT, 'assets')

datas = [
    (ctk_path, 'customtkinter'),
    (assets_dir, 'assets'),
]
binaries = []
hiddenimports = [
    'customtkinter',
    'pystray',
    'PIL',
    'PIL._tkinter_finder',
    'pdfplumber',
    'pdfminer',
    'pdfminer.high_level',
    'docx',
    'openpyxl',
    'pptx',
    'anthropic',
    'openai',
    'google.generativeai',
    'google.ai.generativelanguage',
    'tkinter',
    'tkinter.filedialog',
    'win32gui',
    'win32process',
    'win32com',
    'win32com.client',
]

tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pystray')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    [os.path.join(ROOT, 'screencompanion', '__main__.py')],
    pathex=[ROOT],
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
    name='Screen Companion',
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
    icon=os.path.join(assets_dir, 'icon.ico'),
    onefile=True,
)
