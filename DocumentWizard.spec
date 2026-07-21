# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:\\Users\\ADMIN\\Downloads\\Screen companion\\screen-companion\\.venv\\Lib\\site-packages\\customtkinter', 'customtkinter')]
binaries = []
hiddenimports = ['customtkinter', 'pystray', 'PIL', 'PIL._tkinter_finder', 'pdfplumber', 'pdfminer', 'pdfminer.high_level', 'docx', 'openpyxl', 'pptx', 'anthropic', 'openai', 'google.generativeai', 'google.ai.generativelanguage', 'tkinter', 'tkinter.filedialog', 'win32gui', 'win32process', 'win32com', 'win32com.client', 'psutil']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pystray')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\ADMIN\\Downloads\\Screen companion\\screen-companion\\screencompanion\\__main__.py'],
    pathex=[],
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
    [],
    exclude_binaries=True,
    name='DocumentWizard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\ADMIN\\Downloads\\Screen companion\\screen-companion\\assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DocumentWizard',
)
