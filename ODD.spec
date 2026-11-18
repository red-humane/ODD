# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs



datas = [

    ('odd_logo.png', '.'),

    ('odd_logo.ico', '.'),

    ('odd_logo_black.png', '.'),

    ('odd_logo_black.ico', '.'),

    ('odd_logo_b64.txt', '.'),

    ('assets/icons', 'assets/icons'),

    ('assets/animations', 'assets/animations'),

    ('assets/sounds', 'assets/sounds')

] + collect_data_files('uiautomation')



binaries = collect_dynamic_libs('uiautomation')



a = Analysis(

    ['main.py'],

    pathex=[],

    binaries=binaries,

    datas=datas,

    hiddenimports=[

        'pynput.keyboard._win32', 

        'pynput.mouse._win32',

        'winrt',

        'winrt.windows.media.control',

        'winrt.windows.storage.streams',

        'winrt.windows.foundation',

        'winrt.windows.foundation.collections',

        'pycaw',

        'comtypes',

        'odd_crash_capture',

        'odd_com',

        'odd_tier',

        'odd_blur',

        'odd_chat',

        'odd_icons',

        'odd_useanimations',

        'odd_animated_buttons',

        'odd_island',

        'odd_media',

        'odd_messaging',

        'odd_overlay',

        'odd_reminder',

        'odd_search',

        'odd_settings',
        'odd_radial_menu',

        'odd_settings_dialog',

        'odd_share',

        'odd_sound',

        'odd_dsp',

        'odd_audio',

        'odd_motion',

        'odd_motion_intelligence',

        'odd_theme',

        'odd_spring',

        'odd_goo',

        'odd_profiler',

        'odd_transform',

        'odd_updater',

        'odd_weather',

        'odd_android_mirror',

        'odd_wellness',

        'odd_system_needs',

        'psutil',

        'rapidfuzz',

        'uiautomation',

        'pygame',

        'pygame.mixer',

        'win32com',

        'win32com.client',

        'win32gui',

        'win32con',

        'pythoncom',

        'pywintypes',

        'cv2',

        'odd_camera',

        'PySide6.QtMultimedia',

        'PySide6.QtMultimediaWidgets',

        'fluentapp',

        'fluentapp.windoweffect'

    ],

    hookspath=[],

    hooksconfig={},

    runtime_hooks=[],

    excludes=[
        'tkinter',
        '_tkinter',
        'Tkinter',
        'tcl',
        'matplotlib',
        'scipy',
        'torch',
        'torchvision',
        'torchaudio',
        'c10',
        'sklearn',
        'scikit_learn',
        'transformers',
        'huggingface_hub',
        'bitsandbytes',
        'numba',
        'llvmlite',
        'nltk',
        'sacremoses',
        'pandas',
        'pyarrow',
    ],

    noarchive=False,

    optimize=0,

)



# Avoid bundling the unrelated ICU DLL picked up from the build environment,

# as well as opengl32sw.dll (unneeded 21MB software rasterizer that causes decompression locks)

UNWANTED_BINARIES = {

    'opengl32sw.dll',

    'icuuc.dll',

}



a.binaries = [
    entry for entry in a.binaries
    if entry[0].replace(chr(92), "/").split("/")[-1].lower() not in UNWANTED_BINARIES
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

    name='ODD',

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

