# -*- mode: python ; coding: utf-8 -*-
import os
import gzip
import shutil

odd_exe_path = 'dist/ODD.exe'
if not os.path.exists(odd_exe_path):
    if os.path.exists('dist_rebuild/ODD.exe'):
        odd_exe_path = 'dist_rebuild/ODD.exe'
    elif os.path.exists('ODD.exe'):
        odd_exe_path = 'ODD.exe'

payload_path = 'odd_payload.bin'
# Ensure odd_payload.bin exists and matches current ODD.exe
if not os.path.exists(payload_path) or (os.path.exists(odd_exe_path) and os.path.getmtime(odd_exe_path) > os.path.getmtime(payload_path)):
    print(f"Compressing {odd_exe_path} into {payload_path}...")
    with open(odd_exe_path, 'rb') as f_in, gzip.open(payload_path, 'wb', compresslevel=1) as f_out:
        shutil.copyfileobj(f_in, f_out, length=4*1024*1024)
    print(f"Payload created: {os.path.getsize(payload_path)} bytes")

datas = [
    (payload_path, '.'),
    ('odd_logo.png', '.'),
    ('odd_logo.ico', '.'),
    ('odd_logo_black.png', '.'),
    ('odd_logo_black.ico', '.'),
    ('odd_logo_b64.txt', '.'),
    ('assets/icons', 'assets/icons'),
    ('assets/animations', 'assets/animations'),
    ('assets/sounds', 'assets/sounds')
]

a = Analysis(
    ['installer.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['PySide6.QtSvg', 'fluentapp', 'fluentapp.windoweffect', 'odd_icons', 'odd_theme'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter', 'Tkinter', 'tcl', 'pygame', 'cv2', 'scipy', 'matplotlib', 'numpy',
        'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick',
        'PySide6.QtPdf', 'PySide6.QtMultimedia', 'PySide6.QtOpenGL',
        'torch', 'torchvision', 'torchaudio', 'c10', 'sklearn', 'scikit_learn',
        'transformers', 'huggingface_hub', 'bitsandbytes', 'numba', 'llvmlite', 'nltk', 'sacremoses'
    ],
    noarchive=False,
    optimize=0,
)

# Strip out unnecessary heavy dynamic libraries (specifically opengl32sw.dll which causes
# Windows Defender locks and extraction error "decompression resulted in return code -1!")
UNWANTED_BINARIES = {
    'opengl32sw.dll',
    'qt6opengl.dll',
    'qt6pdf.dll',
    'qt6qml.dll',
    'qt6qmlmodels.dll',
    'qt6qmlmeta.dll',
    'qt6qmlworkerscript.dll',
    'qt6quick.dll',
    'qt6virtualkeyboard.dll',
    'icuuc.dll',
}

a.binaries = [
    entry for entry in a.binaries
    if entry[0].replace("\\", "/").split("/")[-1].lower() not in UNWANTED_BINARIES
    and not entry[0].lower().startswith("torch")
    and "torch" not in entry[0].lower()
]

a.datas = [
    entry for entry in a.datas
    if not entry[0].lower().startswith("torch")
    and "torch" not in entry[0].lower()
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ODD_Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='odd_logo.ico',
)
