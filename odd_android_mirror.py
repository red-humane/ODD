"""
ODD Android Mirror Engine (Scrcpy 60fps)
Dedicated, ultra-low latency Android screen mirroring and remote control in Windows:
- Pure Scrcpy 60fps mirroring with complete mouse and keyboard interaction
- Automatic ADB device and authorization detection
- One-click Wireless TCP/IP enablement and auto Wi-Fi IP discovery
- Direct activation: 1-click opens mirror if phone is connected, or opens connection guide if disconnected
- 100% vector-drawn minimalist UI without emojis, with equal button sizing
"""

import os
import sys
import json
import time
import shutil
import zipfile
import winreg
import datetime
import subprocess
import threading
import ctypes
from ctypes import wintypes
import urllib.request
import urllib.error
import re
import posixpath
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PySide6.QtCore import QObject, Signal, QTimer, Qt, QSize, QPoint, QRect, QUrl, QMimeData
from PySide6.QtGui import QFont, QColor, QPainter, QPainterPath, QBrush, QPen, QCursor, QDrag
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QProgressBar, QFrame, QSizePolicy, QApplication
)

from odd_icons import get_vector_icon
import odd_theme
from odd_theme import Tokens, Fonts
import odd_ui
from odd_ui import ChipBadge, PrimaryButton

SCRCPY_DIR = Path(os.path.expandvars(r"%APPDATA%\ODD\scrcpy"))
PHONE_CONFIG_FILE = Path(os.path.expandvars(r"%APPDATA%\ODD\phone_device.json"))
SCRCPY_LATEST_ZIP_URL = "https://github.com/Genymobile/scrcpy/releases/download/v3.1/scrcpy-win64-v3.1.zip"

PHONE_BRAND_KEYWORDS = [
    "phone", "galaxy", "pixel", "oneplus", "xiaomi", "redmi", "oppo",
    "vivo", "realme", "motorola", "moto", "nothing", "honor", "sony",
    "xperia", "huawei", "asus", "poco", "nokia", "zte", "tecno",
    "infinix", "iqoo"
]


def get_odd_logo_paths(inverted: bool = True) -> Tuple[str, str]:
    """Returns absolute paths to odd_logo_black.png and odd_logo_black.ico (inverted) or default."""
    base_dir = getattr(sys, '_MEIPASS', None)
    prefix = "odd_logo_black" if inverted else "odd_logo"
    if base_dir:
        png_p = Path(base_dir) / f"{prefix}.png"
        ico_p = Path(base_dir) / f"{prefix}.ico"
        if png_p.exists() and ico_p.exists():
            return str(png_p.resolve()), str(ico_p.resolve())

    script_dir = Path(__file__).resolve().parent
    png_p = script_dir / f"{prefix}.png"
    ico_p = script_dir / f"{prefix}.ico"
    if not (png_p.exists() and ico_p.exists()):
        png_p = script_dir / "odd_logo.png"
        ico_p = script_dir / "odd_logo.ico"
    return str(png_p.resolve()), str(ico_p.resolve())


def get_connected_bluetooth_devices() -> List[str]:
    """
    Returns the friendly names of currently CONNECTED Bluetooth devices only.
    Excludes paired-but-disconnected devices and internal adapter hardware.
    """
    connected: List[str] = []
    seen = set()
    ignore_keywords = (
        'adapter', 'radio', 'transport', 'service', 'enumerator',
        'profile', 'protocol', 'generic attribute', 'rfcomm', 'virtual',
        'microsoft', 'bluetooth device', 'audio endpoint', 'hands-free ag',
        'avrcp', 'a2dp', 'hid device', 'device identification'
    )

    # 1. SetupAPI with DEVPKEY_Device_IsConnected (covers classic & BLE devices)
    try:
        class _GUID(ctypes.Structure):
            _fields_ = [
                ('Data1', wintypes.DWORD),
                ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD),
                ('Data4', wintypes.BYTE * 8)
            ]

        class _SP_DEVINFO_DATA(ctypes.Structure):
            _fields_ = [
                ('cbSize', wintypes.DWORD),
                ('ClassGuid', _GUID),
                ('DevInst', wintypes.DWORD),
                ('Reserved', ctypes.c_void_p)
            ]

        class _DEVPROPKEY(ctypes.Structure):
            _fields_ = [
                ('fmtid_Data1', wintypes.DWORD),
                ('fmtid_Data2', wintypes.WORD),
                ('fmtid_Data3', wintypes.WORD),
                ('fmtid_Data4', wintypes.BYTE * 8),
                ('pid', wintypes.ULONG),
            ]

        key_isConnected = _DEVPROPKEY(
            0xa8b865dd, 0x2e3d, 0x4094,
            (wintypes.BYTE * 8)(0xad, 0x97, 0xe5, 0x93, 0xa7, 0x0c, 0x75, 0xd6),
            26
        )
        key_devName = _DEVPROPKEY(
            0xb725f130, 0x47ef, 0x101a,
            (wintypes.BYTE * 8)(0xa5, 0xf1, 0x02, 0x60, 0x8c, 0x9e, 0xeb, 0xac),
            10
        )

        setupapi = ctypes.WinDLL('setupapi.dll')
        setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
        setupapi.SetupDiEnumDeviceInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(_SP_DEVINFO_DATA)]
        setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
        setupapi.SetupDiGetDevicePropertyW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_SP_DEVINFO_DATA),
            ctypes.POINTER(_DEVPROPKEY), ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.DWORD
        ]
        setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
        setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
        setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

        bth_guid = _GUID(0xe0cbf06c, 0xcd8b, 0x4647, (wintypes.BYTE * 8)(0xbb, 0x8a, 0x26, 0x3b, 0x43, 0xf0, 0xf9, 0x74))
        DIGCF_PRESENT = 0x00000002

        hDevInfo = setupapi.SetupDiGetClassDevsW(ctypes.byref(bth_guid), None, None, DIGCF_PRESENT)
        if hDevInfo and hDevInfo != -1:
            dev_info = _SP_DEVINFO_DATA()
            dev_info.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            index = 0
            while setupapi.SetupDiEnumDeviceInfo(hDevInfo, index, ctypes.byref(dev_info)):
                prop_type = wintypes.DWORD()
                conn_buf = wintypes.BYTE()
                is_conn = False
                if setupapi.SetupDiGetDevicePropertyW(
                    hDevInfo, ctypes.byref(dev_info), ctypes.byref(key_isConnected),
                    ctypes.byref(prop_type), ctypes.cast(ctypes.byref(conn_buf), ctypes.c_void_p),
                    1, None, 0
                ):
                    is_conn = bool(conn_buf.value)

                if is_conn:
                    req_size = wintypes.DWORD()
                    setupapi.SetupDiGetDevicePropertyW(
                        hDevInfo, ctypes.byref(dev_info), ctypes.byref(key_devName),
                        ctypes.byref(prop_type), None, 0, ctypes.byref(req_size), 0
                    )
                    if req_size.value > 0:
                        buf = ctypes.create_unicode_buffer(req_size.value // 2 + 1)
                        if setupapi.SetupDiGetDevicePropertyW(
                            hDevInfo, ctypes.byref(dev_info), ctypes.byref(key_devName),
                            ctypes.byref(prop_type), ctypes.cast(buf, ctypes.c_void_p),
                            req_size.value, None, 0
                        ):
                            d_name = buf.value.strip()
                            d_name_l = d_name.lower()
                            if d_name and len(d_name) >= 2 and d_name_l not in ('bluetooth', 'device', 'unknown device', 'unknown', 'none', 'null') and not any(k in d_name_l for k in ignore_keywords):
                                if d_name not in seen:
                                    seen.add(d_name)
                                    connected.append(d_name)
                index += 1
            setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)
    except Exception:
        pass

    # 2. Classic Bluetooth fallback via BluetoothAPIs.dll
    try:
        class _SYSTEMTIME(ctypes.Structure):
            _fields_ = [
                ('wYear', wintypes.WORD), ('wMonth', wintypes.WORD),
                ('wDayOfWeek', wintypes.WORD), ('wDay', wintypes.WORD),
                ('wHour', wintypes.WORD), ('wMinute', wintypes.WORD),
                ('wSecond', wintypes.WORD), ('wMilliseconds', wintypes.WORD),
            ]

        class _BLUETOOTH_DEVICE_INFO(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('Address', ctypes.c_ulonglong),
                ('ulClassofDevice', wintypes.ULONG),
                ('fConnected', wintypes.BOOL),
                ('fRemembered', wintypes.BOOL),
                ('fAuthenticated', wintypes.BOOL),
                ('stLastSeen', _SYSTEMTIME),
                ('stLastUsed', _SYSTEMTIME),
                ('szName', wintypes.WCHAR * 248),
            ]

        class _BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('fReturnAuthenticated', wintypes.BOOL),
                ('fReturnRemembered', wintypes.BOOL),
                ('fReturnUnknown', wintypes.BOOL),
                ('fReturnConnected', wintypes.BOOL),
                ('fIssueInquiry', wintypes.BOOL),
                ('cTimeoutMultiplier', ctypes.c_ubyte),
                ('hRadio', wintypes.HANDLE),
            ]

        bth = ctypes.WinDLL('BluetoothAPIs.dll')
        bth.BluetoothFindFirstDevice.restype = wintypes.HANDLE
        bth.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(_BLUETOOTH_DEVICE_SEARCH_PARAMS), ctypes.POINTER(_BLUETOOTH_DEVICE_INFO)]
        bth.BluetoothFindNextDevice.restype = wintypes.BOOL
        bth.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BLUETOOTH_DEVICE_INFO)]
        bth.BluetoothFindDeviceClose.restype = wintypes.BOOL
        bth.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]

        search_params = _BLUETOOTH_DEVICE_SEARCH_PARAMS()
        search_params.dwSize = ctypes.sizeof(_BLUETOOTH_DEVICE_SEARCH_PARAMS)
        search_params.fReturnAuthenticated = True
        search_params.fReturnRemembered = True
        search_params.fReturnUnknown = False
        search_params.fReturnConnected = True
        search_params.fIssueInquiry = False

        device_info = _BLUETOOTH_DEVICE_INFO()
        device_info.dwSize = ctypes.sizeof(_BLUETOOTH_DEVICE_INFO)

        hFind = bth.BluetoothFindFirstDevice(ctypes.byref(search_params), ctypes.byref(device_info))
        if hFind:
            while True:
                if device_info.fConnected:
                    d_name = device_info.szName.strip()
                    d_name_l = d_name.lower()
                    if d_name and len(d_name) >= 2 and d_name_l not in ('bluetooth', 'device', 'unknown device', 'unknown', 'none', 'null') and not any(k in d_name_l for k in ignore_keywords):
                        if d_name not in seen:
                            seen.add(d_name)
                            connected.append(d_name)
                device_info.dwSize = ctypes.sizeof(_BLUETOOTH_DEVICE_INFO)
                if not bth.BluetoothFindNextDevice(hFind, ctypes.byref(device_info)):
                    break
            bth.BluetoothFindDeviceClose(hFind)
    except Exception:
        pass

    return connected


class BluetoothPhoneInfo:
    def __init__(self, mac: str, name: str, is_phone: bool = True,
                 is_connected: bool = False, last_connected_str: str = "",
                 last_connected_ft: int = 0):
        self.mac = mac
        self.name = name
        self.is_phone = is_phone
        self.is_connected = is_connected
        self.last_connected_str = last_connected_str
        self.last_connected_ft = last_connected_ft


class AndroidMirrorManager(QObject):
    """
    Singleton Manager for Scrcpy Android Phone Mirroring.
    """
    adb_status_updated = Signal(str, str, str)  # (state, serial, model)
    devices_updated = Signal(list)
    scrcpy_ready_updated = Signal(bool)
    download_progress = Signal(int)
    download_finished = Signal(bool, str)
    operation_finished = Signal(str, str)
    wireless_ip_discovered = Signal(str)

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = AndroidMirrorManager()
            return cls._instance

    def __init__(self):
        super().__init__()
        self._cached_devices: List[BluetoothPhoneInfo] = []
        self._primary_phone_name: str = ""
        self._is_scanning = False
        self._is_downloading = False
        self._scrcpy_process = None
        self._adb_path = self._find_adb()
        self._scrcpy_path = self._find_scrcpy()
        self._saved_ip: str = ""
        self._saved_model: str = ""
        self._load_saved_device()

    def _load_saved_device(self):
        try:
            if PHONE_CONFIG_FILE.exists():
                with open(PHONE_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._saved_ip = data.get("saved_ip", "").strip()
                    self._saved_model = data.get("saved_model", "").strip()
        except Exception as e:
            print(f"[ODD Android Mirror] Load saved device error: {e}")

    def save_device_info(self, ip_or_serial: str, model: str = ""):
        try:
            clean = ip_or_serial.strip()
            if not clean:
                return
            self._saved_ip = clean
            if model:
                self._saved_model = model.strip()
            PHONE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PHONE_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "saved_ip": self._saved_ip,
                    "saved_model": self._saved_model,
                    "last_connected": time.time()
                }, f, indent=2)
        except Exception as e:
            print(f"[ODD Android Mirror] Save device info error: {e}")

    def get_saved_device_ip(self) -> str:
        return getattr(self, '_saved_ip', '')

    def get_saved_device_model(self) -> str:
        return getattr(self, '_saved_model', '')

    def has_saved_device(self) -> bool:
        return bool(getattr(self, '_saved_ip', ''))

    def try_reconnect_saved(self, timeout_sec: float = 1.5) -> Tuple[str, str, str]:
        """Synchronously attempts to reconnect to saved phone device, returning (state, serial, model)."""
        if not self.has_saved_device():
            return self.check_adb_devices()
        adb_exe = self._find_adb()
        if not adb_exe:
            return "not_found", "", ""
        try:
            subprocess.run(
                [adb_exe, "connect", self._saved_ip],
                capture_output=True, text=True, errors="replace", timeout=timeout_sec, creationflags=0x08000000
            )
        except Exception:
            pass
        return self.check_adb_devices()

    def toggle_phone_rotation(self):
        """Toggles phone orientation between Portrait and Landscape."""
        adb_exe = self._find_adb()
        if not adb_exe:
            return
        def _worker():
            try:
                state, serial, _ = self.check_adb_devices()
                target_serial = serial
                if not target_serial and self.has_saved_device():
                    target_serial = self._saved_ip
                if not target_serial:
                    return
                res = subprocess.run(
                    [adb_exe, "-s", target_serial, "shell", "settings get system user_rotation"],
                    capture_output=True, text=True, errors="replace", timeout=2.0, creationflags=0x08000000
                )
                cur_rot = res.stdout.strip()
                # 0 = Portrait (0 deg), 1 = Landscape (90 deg)
                new_rot = "1" if cur_rot == "0" else "0"
                # Disable lock, apply orientation, then re-enable auto-rotation
                subprocess.run(
                    [adb_exe, "-s", target_serial, "shell", "settings put system accelerometer_rotation 0"],
                    capture_output=True, timeout=2.0, creationflags=0x08000000
                )
                subprocess.run(
                    [adb_exe, "-s", target_serial, "shell", f"settings put system user_rotation {new_rot}"],
                    capture_output=True, timeout=2.0, creationflags=0x08000000
                )
                if new_rot == "0":
                    # Re-enable auto-rotation for games when set back
                    subprocess.run(
                        [adb_exe, "-s", target_serial, "shell", "settings put system accelerometer_rotation 1"],
                        capture_output=True, timeout=2.0, creationflags=0x08000000
                    )
                self.operation_finished.emit("rotation", f"Orientation: {'Landscape' if new_rot == '1' else 'Portrait'}")
            except Exception as e:
                print(f"[ODD Android Mirror] Rotation error: {e}")
        threading.Thread(target=_worker, daemon=True).start()

    def _find_adb(self) -> Optional[str]:
        # 1. Bundled or downloaded scrcpy directory
        scrcpy_adb = SCRCPY_DIR / "adb.exe"
        if scrcpy_adb.exists():
            return str(scrcpy_adb)

        for sub in SCRCPY_DIR.glob("**/adb.exe"):
            return str(sub)

        # 2. Local Android SDK platform-tools
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        sdk_adb = Path(local_appdata) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
        if sdk_adb.exists():
            return str(sdk_adb)

        # 3. PATH
        which_adb = shutil.which("adb")
        if which_adb:
            return which_adb

        return None

    def _find_scrcpy(self) -> Optional[str]:
        target = SCRCPY_DIR / "scrcpy.exe"
        if target.exists():
            return str(target)

        for sub in SCRCPY_DIR.glob("**/scrcpy.exe"):
            return str(sub)

        which_scrcpy = shutil.which("scrcpy")
        if which_scrcpy:
            return which_scrcpy

        common_paths = [
            Path(r"C:\Program Files\scrcpy\scrcpy.exe"),
            Path(r"C:\tools\scrcpy\scrcpy.exe"),
            Path(r"C:\ProgramData\chocolatey\bin\scrcpy.exe"),
        ]
        for p in common_paths:
            if p.exists():
                return str(p)

        return None

    def is_scrcpy_available(self) -> bool:
        self._scrcpy_path = self._find_scrcpy()
        return bool(self._scrcpy_path and Path(self._scrcpy_path).exists())

    def check_adb_devices(self) -> Tuple[str, str, str]:
        """
        Returns (state, serial, model_name)
        where state is 'device', 'unauthorized', 'offline', or 'none'.
        Intelligently prioritizes standard port 5555 and USB devices over ephemeral pairing ports.
        """
        adb_exe = self._find_adb()
        if not adb_exe:
            return "not_found", "", ""
        try:
            res = subprocess.run(
                [adb_exe, "devices", "-l"],
                capture_output=True, text=True, errors="replace", timeout=2, creationflags=0x08000000
            )
            lines = [l.strip() for l in res.stdout.strip().splitlines() if l.strip() and not l.startswith("*")]
            candidates = []
            for line in lines[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    serial = parts[0]
                    state = parts[1]
                    model = ""
                    for p in parts:
                        if p.startswith("model:"):
                            model = p.split("model:")[1].replace("_", " ")
                    candidates.append((state, serial, model or serial))

            if not candidates:
                return "none", "", ""

            # Prioritization order:
            # 1. USB device with state == 'device' (serial without ':')
            # 2. Port 5555 device with state == 'device'
            # 3. Any device with state == 'device'
            # 4. Any unauthorized device
            # 5. First candidate
            for c in candidates:
                if c[0] == "device" and ":" not in c[1]:
                    return c
            for c in candidates:
                if c[0] == "device" and c[1].endswith(":5555"):
                    return c
            for c in candidates:
                if c[0] == "device":
                    return c
            for c in candidates:
                if c[0] == "unauthorized":
                    return c
            return candidates[0]
        except Exception as e:
            return "error", str(e), ""

    def scan_devices_async(self):
        if self._is_scanning:
            return
        self._is_scanning = True
        threading.Thread(target=self._scan_devices_worker, daemon=True).start()

    def _scan_devices_worker(self):
        # 1. Check ADB connection
        state, serial, model = self.check_adb_devices()

        # If no device connected, auto-try reconnecting to saved phone (e.g. after PC restart)
        if state == "none" and self.has_saved_device():
            adb_exe = self._find_adb()
            if adb_exe:
                try:
                    subprocess.run(
                        [adb_exe, "connect", self._saved_ip],
                        capture_output=True, text=True, errors="replace", timeout=1.5, creationflags=0x08000000
                    )
                    state, serial, model = self.check_adb_devices()
                except Exception:
                    pass

        # If connected to device, persist it so it never gets lost!
        if state == "device" and serial:
            self.save_device_info(serial, model)
            if ":" not in serial:
                # USB device: keep port 5555 active in background so wireless is always available
                adb_exe = self._find_adb()
                if adb_exe:
                    try:
                        subprocess.run([adb_exe, "-s", serial, "tcpip", "5555"],
                                       capture_output=True, timeout=2.0, creationflags=0x08000000)
                    except Exception:
                        pass

        # 2. Check Bluetooth registry for friendly name fallback (connected phones only)
        devices: List[BluetoothPhoneInfo] = []
        try:
            connected_bt_names = get_connected_bluetooth_devices()
            connected_bt_set = {d.strip().lower() for d in connected_bt_names}

            path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                        i += 1
                        with winreg.OpenKey(key, sub) as dev_key:
                            try:
                                name_bytes, _ = winreg.QueryValueEx(dev_key, "Name")
                                name = name_bytes.decode("utf-8", errors="ignore").rstrip("\x00")
                            except Exception:
                                name = sub

                            is_phone = False
                            try:
                                cod, _ = winreg.QueryValueEx(dev_key, "COD")
                                if ((cod >> 8) & 0x1F) == 0x02:
                                    is_phone = True
                            except Exception:
                                pass

                            if any(k in name.lower() for k in PHONE_BRAND_KEYWORDS):
                                is_phone = True

                            # Crucial: only consider connected if actively reported by Windows Bluetooth system
                            is_connected = False
                            name_clean = name.strip().lower()
                            if name_clean in connected_bt_set or any(name_clean in cb or cb in name_clean for cb in connected_bt_set):
                                is_connected = True

                            last_conn_str = ""
                            last_conn_ft = 0
                            try:
                                ft, _ = winreg.QueryValueEx(dev_key, "LastConnected")
                                if ft > 0:
                                    last_conn_ft = int(ft)
                                    dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
                                    now = datetime.datetime.utcnow()
                                    diff = now - dt
                                    if diff.total_seconds() < 3600 * 24:
                                        last_conn_str = "Recently active"
                                    else:
                                        days = int(diff.total_seconds() // (3600 * 24))
                                        last_conn_str = f"Active {days}d ago"
                            except Exception:
                                pass

                            if is_phone:
                                devices.append(BluetoothPhoneInfo(
                                    mac=sub,
                                    name=name,
                                    is_phone=is_phone,
                                    is_connected=is_connected,
                                    last_connected_str=last_conn_str,
                                    last_connected_ft=last_conn_ft
                                ))
                    except OSError:
                        break
        except Exception:
            pass

        devices.sort(key=lambda d: (d.is_connected, d.last_connected_ft), reverse=True)
        # ONLY cache and expose devices that are currently connected! Paired offline devices should never be shown as active phone.
        connected_phones = [d for d in devices if d.is_connected]
        self._cached_devices = connected_phones

        if state == "device":
            self._primary_phone_name = model or serial
        elif connected_phones:
            self._primary_phone_name = connected_phones[0].name
        else:
            self._primary_phone_name = ""

        self._is_scanning = False
        self.devices_updated.emit(self._cached_devices)
        self.adb_status_updated.emit(state, serial, model)
        self.scrcpy_ready_updated.emit(self.is_scrcpy_available())

    def launch_scrcpy(self, serial: Optional[str] = None, ip: Optional[str] = None,
                      stay_on_top: bool = True, max_fps: int = 60, turn_screen_off: bool = False):
        """
        Launches Scrcpy screen mirror window.
        """
        scrcpy_exe = self._find_scrcpy()
        if not scrcpy_exe:
            self.operation_finished.emit("error", "Scrcpy engine not installed. Downloading portable engine...")
            self.download_portable_scrcpy()
            return

        adb_exe = self._find_adb()
        env = os.environ.copy()
        if adb_exe:
            env["ADB"] = adb_exe

        def _run():
            try:
                state, cur_serial, model = self.check_adb_devices()
                target_serial = serial or cur_serial

                # If no active serial, but saved device exists, try auto-connecting
                if not target_serial and self.has_saved_device():
                    state, cur_serial, model = self.try_reconnect_saved(timeout_sec=1.8)
                    target_serial = cur_serial or self.get_saved_device_ip()

                # If explicit IP provided, check if already in devices first (zero latency)
                if ip and ip.strip():
                    target_ip = ip.strip()
                    if ":" not in target_ip:
                        target_ip += ":5555"
                    if target_serial != target_ip and adb_exe:
                        subprocess.run(
                            [adb_exe, "connect", target_ip],
                            capture_output=True, text=True, errors="replace", timeout=2.0, creationflags=0x08000000
                        )
                        state, cur_serial, model = self.check_adb_devices()
                        target_serial = cur_serial or target_ip
                    else:
                        target_serial = target_ip

                if state == "unauthorized":
                    self.operation_finished.emit(
                        "error",
                        "Phone unauthorized! Unlock your phone and tap 'Allow' on the USB debugging prompt."
                    )
                    return
                elif state == "none" and not target_serial:
                    self.operation_finished.emit(
                        "guide",
                        "No phone detected via USB or Wi-Fi. Please plug in your phone with USB debugging enabled."
                    )
                    return

                if target_serial:
                    self.save_device_info(target_serial, model)

                # Inverted Black ODD Logo for Phone Mirror Window!
                png_path, _ = get_odd_logo_paths(inverted=True)
                if os.path.exists(png_path):
                    env["SCRCPY_ICON_PATH"] = png_path

                cmd = [
                    scrcpy_exe,
                    "--window-title=ODD Phone Mirror",
                    "--stay-awake",
                    "--push-target=/sdcard/Download/"
                ]
                if stay_on_top:
                    cmd.append("--always-on-top")
                if max_fps > 0:
                    cmd.append(f"--max-fps={max_fps}")
                if turn_screen_off:
                    cmd.append("--turn-screen-off")

                # Fast direct connection (100ms startup)
                if target_serial:
                    cmd.extend(["-s", target_serial])

                # Use DEVNULL so stdout/stderr buffer never fills up and freezes scrcpy!
                self._scrcpy_process = subprocess.Popen(
                    cmd, env=env, creationflags=0x08000000,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                threading.Thread(
                    target=self._apply_scrcpy_window_icon,
                    args=("ODD Phone Mirror",),
                    daemon=True
                ).start()
                self.operation_finished.emit("scrcpy", f"Mirror active: {model or target_serial or 'Connected'}")
            except Exception as e:
                self.operation_finished.emit("error", f"Scrcpy launch error: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _apply_scrcpy_window_icon(self, window_title: str):
        """Monitors for Scrcpy window creation and sets native Win32 window icon to inverted black ODD logo."""
        try:
            _, ico_path = get_odd_logo_paths(inverted=True)
            if not os.path.exists(ico_path):
                return

            import win32gui, win32con
            hicon_big = win32gui.LoadImage(0, ico_path, win32con.IMAGE_ICON, 32, 32, win32con.LR_LOADFROMFILE)
            hicon_small = win32gui.LoadImage(0, ico_path, win32con.IMAGE_ICON, 16, 16, win32con.LR_LOADFROMFILE)

            for _ in range(50):
                hwnd = win32gui.FindWindow(None, window_title)
                if hwnd and win32gui.IsWindow(hwnd):
                    if hicon_big:
                        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, hicon_big)
                    if hicon_small:
                        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, hicon_small)
                    break
                time.sleep(0.2)
        except Exception as e:
            print(f"[ODD Android Mirror] Window icon apply error: {e}")

    def enable_wireless_mode(self):
        """
        Enables Wireless TCP/IP mode on USB-connected phone, auto-discovers its Wi-Fi IP,
        and connects wirelessly in ~1 second so the user can unplug the USB cable!
        """
        adb_exe = self._find_adb()
        if not adb_exe:
            self.operation_finished.emit("error", "ADB engine not found")
            return

        def _worker():
            try:
                state, serial, _ = self.check_adb_devices()
                if state != "device":
                    self.operation_finished.emit(
                        "error",
                        "Please plug phone into USB first to enable wireless mode."
                    )
                    return

                # Fast port 5555 enablement
                subprocess.run(
                    [adb_exe, "-s", serial, "tcpip", "5555"],
                    capture_output=True, text=True, errors="replace", timeout=2.5, creationflags=0x08000000
                )

                # Combined fast IP query (single shell call)
                q_res = subprocess.run(
                    [adb_exe, "-s", serial, "shell", "ip -4 route show table wlan0 dev wlan0 proto static 2>/dev/null; ip -4 addr show wlan0 2>/dev/null; ip route 2>/dev/null"],
                    capture_output=True, text=True, errors="replace", timeout=2.0, creationflags=0x08000000
                )
                ip_match = re.findall(r'\b(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b', q_res.stdout)
                ip = ip_match[0] if ip_match else ""

                if ip:
                    target = f"{ip}:5555"
                    subprocess.run(
                        [adb_exe, "connect", target],
                        capture_output=True, text=True, errors="replace", timeout=2.0, creationflags=0x08000000
                    )
                    self.wireless_ip_discovered.emit(target)
                    self.operation_finished.emit(
                        "wireless",
                        f"Wireless enabled on {target}! You can now unplug the USB cable."
                    )
                    self.scan_devices_async()
                else:
                    self.operation_finished.emit(
                        "wireless",
                        "Port 5555 enabled. Enter phone Wi-Fi IP to connect."
                    )
            except Exception as e:
                self.operation_finished.emit("error", f"Wireless setup error: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def connect_wireless_adb(self, ip_port: str, pair_code: str = "", auto_launch: bool = True):
        """
        Connects ADB to phone wirelessly via IP:PORT.
        Supports Android 11+ pairing if pair_code is provided.
        Upon successful connection, automatically launches Scrcpy so mirror opens immediately!
        """
        adb_exe = self._find_adb()
        if not adb_exe:
            self.operation_finished.emit("error", "ADB not found")
            return

        def _worker():
            try:
                target = ip_port.strip()
                if not target:
                    self.operation_finished.emit("error", "Please enter IP address and port")
                    return

                if ":" not in target:
                    target += ":5555"

                host = target.split(":")[0]

                # 1. Android 11+ Pairing
                if pair_code and pair_code.strip():
                    p_code = pair_code.strip().replace(" ", "").replace("-", "")
                    pair_res = subprocess.run(
                        [adb_exe, "pair", target, p_code],
                        capture_output=True, text=True, errors="replace", timeout=8, creationflags=0x08000000
                    )
                    p_out = (pair_res.stdout + " " + pair_res.stderr).strip()
                    if pair_res.returncode != 0 or "failed" in p_out.lower() or "error" in p_out.lower():
                        err_detail = p_out if p_out else "Check pairing port and 6-digit code on phone."
                        self.operation_finished.emit("error", f"Pairing failed: {err_detail}")
                        return
                    # Once paired, disconnect any old stale sessions so the new TLS authentication takes effect!
                    subprocess.run([adb_exe, "disconnect"], capture_output=True, timeout=2, creationflags=0x08000000)
                    time.sleep(0.4)

                # 2. Connect (first try stable 5555, then target)
                connected_target = ""
                # Try port 5555 first if paired or default
                if host:
                    alt_target = f"{host}:5555"
                    res = subprocess.run(
                        [adb_exe, "connect", alt_target],
                        capture_output=True, text=True, errors="replace", timeout=3, creationflags=0x08000000
                    )
                    out = (res.stdout + " " + res.stderr).strip()
                    if "connected to" in out.lower() or "already connected" in out.lower():
                        connected_target = alt_target

                if not connected_target:
                    res = subprocess.run(
                        [adb_exe, "connect", target],
                        capture_output=True, text=True, errors="replace", timeout=4, creationflags=0x08000000
                    )
                    out = (res.stdout + " " + res.stderr).strip()
                    if "connected to" in out.lower() or "already connected" in out.lower():
                        connected_target = target

                # If connected but reported as unauthorized, cycle disconnect/connect once to refresh TLS key validation
                if connected_target:
                    state, _, _ = self.check_adb_devices()
                    if state == "unauthorized":
                        subprocess.run([adb_exe, "disconnect", connected_target],
                                       capture_output=True, timeout=2, creationflags=0x08000000)
                        time.sleep(0.3)
                        subprocess.run([adb_exe, "connect", connected_target],
                                       capture_output=True, timeout=3, creationflags=0x08000000)

                if connected_target:
                    # Switch to stable port 5555 if dynamic port was used, so it persists forever
                    if not connected_target.endswith(":5555"):
                        try:
                            subprocess.run([adb_exe, "-s", connected_target, "tcpip", "5555"],
                                           capture_output=True, timeout=2.0, creationflags=0x08000000)
                            subprocess.run([adb_exe, "connect", f"{host}:5555"],
                                           capture_output=True, timeout=2.0, creationflags=0x08000000)
                            connected_target = f"{host}:5555"
                        except Exception:
                            pass

                    # Save device info for restart survival!
                    self.save_device_info(connected_target)

                    self.operation_finished.emit("wireless_connected", f"Connected to {connected_target}")
                    self.scan_devices_async()
                    if auto_launch:
                        self.launch_scrcpy(serial=connected_target)
                else:
                    self.operation_finished.emit("error", f"Connection failed: {out}")
            except Exception as e:
                self.operation_finished.emit("error", f"Wireless error: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def get_recent_phone_files(self, limit: int = 4) -> List[Dict[str, str]]:
        """Returns recent files from phone /sdcard/Download or Screenshots."""
        adb_exe = self._find_adb()
        if not adb_exe:
            return []
        state, serial, _ = self.check_adb_devices()
        if state != "device" or not serial:
            return []

        files = []
        try:
            cmd = [adb_exe, "-s", serial, "shell", f"ls -t /sdcard/Download 2>/dev/null | head -n {limit}"]
            res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=2, creationflags=0x08000000)
            for line in res.stdout.splitlines():
                fname = line.strip()
                if fname and not fname.startswith(".") and "." in fname:
                    files.append({
                        "name": fname,
                        "path": f"/sdcard/Download/{fname}",
                        "folder": "Download"
                    })
        except Exception:
            pass

        if len(files) < limit:
            try:
                cmd = [adb_exe, "-s", serial, "shell", f"ls -t /sdcard/Pictures/Screenshots 2>/dev/null | head -n {limit - len(files)}"]
                res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=2, creationflags=0x08000000)
                for line in res.stdout.splitlines():
                    fname = line.strip()
                    if fname and not fname.startswith(".") and "." in fname:
                        files.append({
                            "name": fname,
                            "path": f"/sdcard/Pictures/Screenshots/{fname}",
                            "folder": "Screenshots"
                        })
            except Exception:
                pass

        return files[:limit]

    def pull_file_to_desktop(self, phone_path: str, dest_dir: Optional[str] = None) -> Optional[str]:
        """Pulls a file from phone to Windows Desktop or temp cache, returning local file path."""
        adb_exe = self._find_adb()
        if not adb_exe:
            return None
        state, serial, _ = self.check_adb_devices()
        if state != "device" or not serial:
            return None

        if not dest_dir:
            dest_dir = str(Path.home() / "Desktop")

        os.makedirs(dest_dir, exist_ok=True)
        filename = posixpath.basename(phone_path)
        local_target = os.path.join(dest_dir, filename)

        try:
            res = subprocess.run(
                [adb_exe, "-s", serial, "pull", phone_path, local_target],
                capture_output=True, text=True, errors="replace", timeout=15, creationflags=0x08000000
            )
            if res.returncode == 0 and os.path.exists(local_target):
                return local_target
        except Exception as e:
            print(f"[ODD Android Mirror] Pull error: {e}")
        return None

    def pull_latest_file_to_desktop(self) -> Tuple[bool, str]:
        """Pulls the most recent file from phone to Windows Desktop and selects it."""
        recent = self.get_recent_phone_files(limit=1)
        if not recent:
            return False, "No recent files found on phone."

        target_file = recent[0]
        local_path = self.pull_file_to_desktop(target_file["path"])
        if local_path and os.path.exists(local_path):
            try:
                subprocess.Popen(f'explorer /select,"{local_path}"', shell=True)
            except Exception:
                pass
            return True, f"Saved to Desktop: {os.path.basename(local_path)}"
        return False, "Failed to transfer file to Desktop."

    def push_files_to_phone(self, local_paths: List[str], dest_folder: str = "/sdcard/Download/") -> Tuple[bool, str]:
        """Pushes files from PC to phone's Download folder."""
        adb_exe = self._find_adb()
        if not adb_exe:
            return False, "ADB not found"
        state, serial, _ = self.check_adb_devices()
        if state != "device" or not serial:
            return False, "Phone not connected"

        success_count = 0
        last_name = ""
        for lp in local_paths:
            if os.path.exists(lp):
                try:
                    res = subprocess.run(
                        [adb_exe, "-s", serial, "push", lp, dest_folder],
                        capture_output=True, text=True, errors="replace", timeout=15, creationflags=0x08000000
                    )
                    if res.returncode == 0:
                        success_count += 1
                        last_name = os.path.basename(lp)
                except Exception:
                    pass

        if success_count == 1:
            return True, f"Copied {last_name} to Phone Download"
        elif success_count > 1:
            return True, f"Copied {success_count} files to Phone Download"
        return False, "File push failed"


    def send_phone_key(self, key_name: str):
        """
        Sends simulated hardware keys to phone: power, volume_up, volume_down, home, back.
        """
        key_map = {
            "power": "26",
            "volume_up": "24",
            "volume_down": "25",
            "home": "3",
            "back": "4",
            "menu": "82",
            "mute": "164"
        }
        code = key_map.get(key_name.lower())
        if not code:
            return

        adb_exe = self._find_adb()
        if not adb_exe:
            return

        def _worker():
            try:
                subprocess.run(
                    [adb_exe, "shell", "input", "keyevent", code],
                    capture_output=True, timeout=3, creationflags=0x08000000
                )
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def sync_clipboard_to_phone(self, text: str):
        """
        Pushes text to Android clipboard.
        """
        adb_exe = self._find_adb()
        if not adb_exe or not text:
            return

        def _worker():
            try:
                clean = text.replace('"', '\\"').replace("'", "\\'")
                subprocess.run(
                    [adb_exe, "shell", "input", "text", f'"{clean}"'],
                    capture_output=True, timeout=4, creationflags=0x08000000
                )
                self.operation_finished.emit("clipboard", "Clipboard sent to phone")
            except Exception as e:
                self.operation_finished.emit("error", f"Clipboard error: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def download_portable_scrcpy(self):
        """
        Downloads lightweight portable scrcpy into %APPDATA%\\ODD\\scrcpy.
        """
        if self._is_downloading:
            return
        self._is_downloading = True

        def _download_worker():
            try:
                SCRCPY_DIR.mkdir(parents=True, exist_ok=True)
                zip_path = SCRCPY_DIR.parent / "scrcpy_temp.zip"

                req = urllib.request.Request(
                    SCRCPY_LATEST_ZIP_URL,
                    headers={"User-Agent": "ODD-Android-Mirror/1.0"}
                )

                with urllib.request.urlopen(req, timeout=30) as response:
                    total_size = int(response.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 65536

                    with open(zip_path, "wb") as f:
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int(downloaded * 100 / total_size)
                                self.download_progress.emit(pct)

                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extractall(SCRCPY_DIR.parent)

                # Move extracted folder to scrcpy dir
                extracted_dirs = list(SCRCPY_DIR.parent.glob("scrcpy-win64*"))
                if extracted_dirs:
                    ed = extracted_dirs[0]
                    if SCRCPY_DIR.exists():
                        shutil.rmtree(SCRCPY_DIR)
                    ed.rename(SCRCPY_DIR)

                if zip_path.exists():
                    zip_path.unlink()

                self._is_downloading = False
                self._scrcpy_path = self._find_scrcpy()
                self.scrcpy_ready_updated.emit(self.is_scrcpy_available())
                self.download_finished.emit(True, "Scrcpy engine installed successfully!")
            except Exception as e:
                self._is_downloading = False
                self.download_finished.emit(False, f"Download failed: {e}")

        threading.Thread(target=_download_worker, daemon=True).start()


class DraggablePhoneFileBadge(QFrame):
    """
    Interactive chip for a phone file.
    - Drag & Drop: Dragging this badge directly onto Windows Desktop (or any folder) copies the file!
    - Click: Instantly downloads the file to Windows Desktop.
    """
    def __init__(self, mgr: AndroidMirrorManager, file_info: Dict[str, str], theme: str = "dark", parent=None):
        super().__init__(parent)
        self.mgr = mgr
        self.file_info = file_info
        self.theme = theme
        self._drag_start_pos = None

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Drag to Desktop or Click to save: {file_info['name']}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(5)

        self.lbl_icon = QLabel(self)
        self.lbl_icon.setFixedSize(12, 12)
        layout.addWidget(self.lbl_icon)

        name = file_info["name"]
        display_name = name if len(name) <= 15 else (name[:8] + "..." + name[-4:])
        self.lbl_name = QLabel(display_name, self)
        self.lbl_name.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Medium))
        layout.addWidget(self.lbl_name)

        self.apply_theme(self.theme)

    def apply_theme(self, theme: str):
        self.theme = theme
        if theme == "light":
            self.setStyleSheet("""
                QFrame {
                    background: rgba(226, 232, 240, 0.9);
                    border: 1px solid rgba(203, 213, 225, 0.9);
                    border-radius: 5px;
                }
                QFrame:hover {
                    background: rgba(203, 213, 225, 0.95);
                    border-color: #475569;
                }
            """)
            self.lbl_name.setStyleSheet("color: #0F172A;")
            self.lbl_icon.setPixmap(get_vector_icon("download", "#0F172A", 12).pixmap(12, 12))
        else:
            self.setStyleSheet("""
                QFrame {
                    background: rgba(255, 255, 255, 0.08);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 5px;
                }
                QFrame:hover {
                    background: rgba(255, 255, 255, 0.16);
                    border-color: rgba(255, 255, 255, 0.35);
                }
            """)
            self.lbl_name.setStyleSheet("color: #E2E8F0;")
            self.lbl_icon.setPixmap(get_vector_icon("download", "#FFFFFF", 12).pixmap(12, 12))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or not self._drag_start_pos:
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        # Prepare file for dragging to Windows Desktop!
        temp_dir = os.path.join(tempfile.gettempdir(), "ODD_Desktop_Drag")
        local_path = self.mgr.pull_file_to_desktop(self.file_info["path"], dest_dir=temp_dir)
        if local_path and os.path.exists(local_path):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(local_path)])
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start_pos:
            if (event.pos() - self._drag_start_pos).manhattanLength() < 5:
                # Clicked: pull directly to Desktop!
                local_path = self.mgr.pull_file_to_desktop(self.file_info["path"])
                if local_path:
                    try:
                        subprocess.Popen(f'explorer /select,"{local_path}"', shell=True)
                    except Exception:
                        pass
        super().mouseReleaseEvent(event)


class AndroidMirrorCard(QWidget):
    """
    Sleek Frosted Dropdown Card for Scrcpy Android Phone Mirroring:
    - Pure Scrcpy 60fps Experience
    - Minimal, simple step-by-step Connection Guide (Wired USB & Wireless Wi-Fi)
    - Required (non-optional) Wi-Fi pairing code for Android 11+
    - Zero blue colors: clean modern monochrome / emerald / warm amber accents
    - Dynamic fluid height with zero cropped / cut-off UI elements
    """
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme() if hasattr(overlay, "get_current_theme") else "dark"
        self.mgr = AndroidMirrorManager.get_instance()
        self.adb_state = "none"
        self.adb_serial = ""
        self.adb_model = ""

        self.mgr.adb_status_updated.connect(self._on_adb_status_updated)
        self.mgr.devices_updated.connect(self._on_devices_updated)
        self.mgr.scrcpy_ready_updated.connect(self._on_scrcpy_ready_updated)
        self.mgr.download_progress.connect(self._on_download_progress)
        self.mgr.download_finished.connect(self._on_download_finished)
        self.mgr.operation_finished.connect(self._on_operation_finished)
        self.mgr.wireless_ip_discovered.connect(self._on_wireless_ip_discovered)

        self.setAcceptDrops(True)
        self.guide_mode = "wireless"

        self._init_ui()
        self.refresh_status()

    def mousePressEvent(self, event):
        if hasattr(self, 'overlay') and self.overlay:
            self.overlay.last_typing_time = time.time()
            if hasattr(self.overlay, 'leave_sink_timer') and self.overlay.leave_sink_timer.isActive():
                self.overlay.leave_sink_timer.stop()
        super().mousePressEvent(event)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        # 1. Sleek Minimal Header Row
        hdr_layout = QHBoxLayout()
        hdr_layout.setContentsMargins(2, 0, 2, 0)
        hdr_layout.setSpacing(8)

        self.lbl_title_icon = QLabel(self)
        self.lbl_title_icon.setFixedSize(16, 16)
        hdr_layout.addWidget(self.lbl_title_icon)

        self.lbl_title = QLabel("Phone Mirror", self)
        self.lbl_title.setFont(QFont("Segoe UI Variable Display", 10.5, QFont.Weight.Bold))
        hdr_layout.addWidget(self.lbl_title)

        # Status badge
        self.lbl_badge = ChipBadge("DISCONNECTED", state="disconnected", parent=self)
        hdr_layout.addWidget(self.lbl_badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        hdr_layout.addStretch()

        # Guide Toggle Button
        self.btn_guide = QPushButton("Guide", self)
        self.btn_guide.setFixedHeight(22)
        self.btn_guide.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guide.setToolTip("Show / Hide Connection Guide")
        self.btn_guide.clicked.connect(self._toggle_guide)
        hdr_layout.addWidget(self.btn_guide, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Re-scan Button
        self.btn_refresh = QPushButton(self)
        self.btn_refresh.setFixedSize(22, 22)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setToolTip("Re-scan USB & Wi-Fi devices")
        self.btn_refresh.clicked.connect(self.refresh_status)
        hdr_layout.addWidget(self.btn_refresh, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Settings Gear
        self.btn_settings = QPushButton(self)
        self.btn_settings.setFixedSize(22, 22)
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.setToolTip("Open Phone Mirror Settings")
        self.btn_settings.clicked.connect(self._open_settings)
        hdr_layout.addWidget(self.btn_settings, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Close label / Esc
        self.lbl_esc = QLabel("Esc", self)
        self.lbl_esc.setFont(QFont("Segoe UI Variable Text", 8))
        hdr_layout.addWidget(self.lbl_esc, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(hdr_layout)

        # 2. Elevated Phone Status Hero Card
        self.banner_frame = QFrame(self)
        self.banner_frame.setObjectName("phoneBanner")
        banner_layout = QHBoxLayout(self.banner_frame)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        banner_layout.setSpacing(10)

        self.lbl_banner_icon = QLabel(self.banner_frame)
        self.lbl_banner_icon.setFixedSize(22, 22)
        banner_layout.addWidget(self.lbl_banner_icon)

        v_info = QVBoxLayout()
        v_info.setSpacing(1)
        self.lbl_phone_name = QLabel("No Phone Connected", self.banner_frame)
        self.lbl_phone_name.setFont(QFont("Segoe UI Variable Display", 10.5, QFont.Weight.DemiBold))
        v_info.addWidget(self.lbl_phone_name)

        self.lbl_phone_status = QLabel("Connect via USB cable or Wi-Fi below", self.banner_frame)
        self.lbl_phone_status.setFont(QFont("Segoe UI Variable Text", 8))
        self.lbl_phone_status.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        v_info.addWidget(self.lbl_phone_status)
        banner_layout.addLayout(v_info, stretch=1)

        # Primary Action Button in Hero Banner (Monochrome high-contrast, zero blue)
        self.btn_main_action = PrimaryButton("Launch Mirror", parent=self.banner_frame)
        self.btn_main_action.setFixedHeight(30)
        self.btn_main_action.setMinimumWidth(110)
        self.btn_main_action.clicked.connect(self._main_action_clicked)
        banner_layout.addWidget(self.btn_main_action)

        layout.addWidget(self.banner_frame)

        # 3. Download progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # 4. Minimal Connection Guide Card (Simple, intuitive, easy to understand)
        self.guide_card = QFrame(self)
        self.guide_card.setObjectName("guideFrame")
        guide_layout = QVBoxLayout(self.guide_card)
        guide_layout.setContentsMargins(10, 8, 10, 8)
        guide_layout.setSpacing(6)

        guide_tab_layout = QHBoxLayout()
        guide_tab_layout.setContentsMargins(0, 0, 0, 2)
        guide_tab_layout.setSpacing(6)

        self.lbl_g_title = QLabel("WI-FI WIRELESS GUIDE", self.guide_card)
        self.lbl_g_title.setFont(QFont("Segoe UI Variable Display", 7.5, QFont.Weight.Bold))
        guide_tab_layout.addWidget(self.lbl_g_title, alignment=Qt.AlignmentFlag.AlignVCenter)

        guide_tab_layout.addStretch()

        self.btn_guide_mode_usb = QPushButton("USB Wired", self.guide_card)
        self.btn_guide_mode_usb.setFixedHeight(22)
        self.btn_guide_mode_usb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guide_mode_usb.clicked.connect(lambda: self._set_guide_mode("usb"))
        guide_tab_layout.addWidget(self.btn_guide_mode_usb, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.btn_guide_mode_wireless = QPushButton("Wi-Fi Wireless", self.guide_card)
        self.btn_guide_mode_wireless.setFixedHeight(22)
        self.btn_guide_mode_wireless.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guide_mode_wireless.clicked.connect(lambda: self._set_guide_mode("wireless"))
        guide_tab_layout.addWidget(self.btn_guide_mode_wireless, alignment=Qt.AlignmentFlag.AlignVCenter)

        guide_layout.addLayout(guide_tab_layout)

        self.step_labels = []
        self.step_badges = []

        # 4a. Static USB steps container
        self.guide_usb_widget = QWidget(self.guide_card)
        usb_layout = QVBoxLayout(self.guide_usb_widget)
        usb_layout.setContentsMargins(0, 2, 0, 2)
        usb_layout.setSpacing(4)
        usb_steps = [
            ("1", "Developer Options", "Phone Settings > About phone > Tap 'Build number' 7 times"),
            ("2", "USB Debugging", "Settings > Developer options > Turn ON 'USB debugging'"),
            ("3", "Connect Cable", "Plug phone into PC with USB cable & tap 'Allow' on phone prompt")
        ]
        self._build_steps_rows(self.guide_usb_widget, usb_layout, usb_steps)
        self.guide_usb_widget.hide()
        guide_layout.addWidget(self.guide_usb_widget)

        # 4b. Static Wireless steps container
        self.guide_wireless_widget = QWidget(self.guide_card)
        wireless_layout = QVBoxLayout(self.guide_wireless_widget)
        wireless_layout.setContentsMargins(0, 2, 0, 2)
        wireless_layout.setSpacing(4)
        wireless_steps = [
            ("1", "Same Wi-Fi", "Ensure phone and PC are connected to the same Wi-Fi network"),
            ("2", "Wireless Debugging", "In Developer options > Turn ON 'Wireless debugging'"),
            ("3", "Pairing Code", "Tap 'Pair device with pairing code' to view IP:Port & 6-digit Code"),
            ("4", "Pair & Connect", "Enter IP:Port and Code below, then click Pair & Connect")
        ]
        self._build_steps_rows(self.guide_wireless_widget, wireless_layout, wireless_steps)
        guide_layout.addWidget(self.guide_wireless_widget)

        layout.addWidget(self.guide_card)

        # 5. Connection Actions Container
        self.scrcpy_container = QFrame(self)
        self.scrcpy_container.setObjectName("scrcpyFrame")
        scrcpy_vlayout = QVBoxLayout(self.scrcpy_container)
        scrcpy_vlayout.setContentsMargins(8, 6, 8, 6)
        scrcpy_vlayout.setSpacing(6)

        # 5a. Wireless Inputs (IP:Port + required Pairing Code)
        self.wireless_widget = QWidget(self.scrcpy_container)
        w_vbox = QVBoxLayout(self.wireless_widget)
        w_vbox.setContentsMargins(0, 0, 0, 0)
        w_vbox.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)

        self.txt_ip = QLineEdit(self.wireless_widget)
        self.txt_ip.setPlaceholderText("Phone IP:Port (e.g. 192.168.1.50:37123)")
        saved_ip = self.mgr.get_saved_device_ip() if self.mgr.has_saved_device() else ""
        if saved_ip and not ("_adb" in saved_ip):
            self.txt_ip.setText(saved_ip)
        self.txt_ip.setFixedHeight(28)
        self.txt_ip.setFont(QFont("Segoe UI Variable Text", 8))
        self.txt_ip.returnPressed.connect(self._connect_wireless_clicked)
        row1.addWidget(self.txt_ip, stretch=1)

        self.txt_pair_code = QLineEdit(self.wireless_widget)
        self.txt_pair_code.setPlaceholderText("Pair Code *")
        self.txt_pair_code.setToolTip("6-digit Wi-Fi Pairing Code from phone (Required)")
        self.txt_pair_code.setFixedHeight(28)
        self.txt_pair_code.setFixedWidth(115)
        self.txt_pair_code.setMaxLength(8)
        self.txt_pair_code.setFont(QFont("Segoe UI Variable Text", 8))
        self.txt_pair_code.returnPressed.connect(self._connect_wireless_clicked)
        row1.addWidget(self.txt_pair_code)
        w_vbox.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)

        self.btn_connect_wireless = QPushButton("Pair && Connect", self.wireless_widget)
        self.btn_connect_wireless.setFixedHeight(28)
        self.btn_connect_wireless.setMinimumWidth(120)
        self.btn_connect_wireless.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_connect_wireless.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
        self.btn_connect_wireless.clicked.connect(self._connect_wireless_clicked)
        row2.addWidget(self.btn_connect_wireless)

        self.btn_enable_wireless = QPushButton("USB to Wi-Fi", self.wireless_widget)
        self.btn_enable_wireless.setFixedHeight(28)
        self.btn_enable_wireless.setMinimumWidth(115)
        self.btn_enable_wireless.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_enable_wireless.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
        self.btn_enable_wireless.setToolTip("Plug phone via USB once to enable wireless mirroring without pairing code")
        self.btn_enable_wireless.clicked.connect(self._enable_wireless_clicked)
        row2.addWidget(self.btn_enable_wireless)
        row2.addStretch()
        w_vbox.addLayout(row2)

        scrcpy_vlayout.addWidget(self.wireless_widget)

        # 5b. USB Action Row
        self.usb_widget = QWidget(self.scrcpy_container)
        u_hbox = QHBoxLayout(self.usb_widget)
        u_hbox.setContentsMargins(0, 0, 0, 0)
        u_hbox.setSpacing(8)

        self.btn_scan_usb = QPushButton("Scan USB Phone", self.usb_widget)
        self.btn_scan_usb.setFixedHeight(28)
        self.btn_scan_usb.setMinimumWidth(125)
        self.btn_scan_usb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan_usb.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
        self.btn_scan_usb.clicked.connect(self.refresh_status)
        u_hbox.addWidget(self.btn_scan_usb)

        self.lbl_usb_hint = QLabel("Plug in USB cable — ODD will detect your phone automatically", self.usb_widget)
        self.lbl_usb_hint.setFont(QFont("Segoe UI Variable Text", 7.5))
        self.lbl_usb_hint.setStyleSheet("color: #94A3B8;")
        u_hbox.addWidget(self.lbl_usb_hint, stretch=1)

        scrcpy_vlayout.addWidget(self.usb_widget)
        layout.addWidget(self.scrcpy_container)

        # 6. Remote hardware controls row (Shown when connected)
        self.remote_container = QFrame(self)
        self.remote_container.setObjectName("remoteFrame")
        remote_layout = QHBoxLayout(self.remote_container)
        remote_layout.setContentsMargins(0, 0, 0, 0)
        remote_layout.setSpacing(6)

        self.btn_remote_power = self._create_remote_btn("power", "Power", "power")
        remote_layout.addWidget(self.btn_remote_power, stretch=1)

        self.btn_remote_voldn = self._create_remote_btn("volume", "Vol -", "volume_down")
        remote_layout.addWidget(self.btn_remote_voldn, stretch=1)

        self.btn_remote_volup = self._create_remote_btn("volume", "Vol +", "volume_up")
        remote_layout.addWidget(self.btn_remote_volup, stretch=1)

        self.btn_remote_clip = QPushButton("Clip", self.remote_container)
        self.btn_remote_clip.setFixedHeight(26)
        self.btn_remote_clip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remote_clip.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
        self.btn_remote_clip.setToolTip("Send PC clipboard text to phone")
        self.btn_remote_clip.clicked.connect(self._sync_clipboard_clicked)
        remote_layout.addWidget(self.btn_remote_clip, stretch=1)

        self.btn_remote_disconnect = QPushButton("Disconnect", self.remote_container)
        self.btn_remote_disconnect.setFixedHeight(26)
        self.btn_remote_disconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remote_disconnect.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
        self.btn_remote_disconnect.setToolTip("Disconnect phone session")
        self.btn_remote_disconnect.clicked.connect(self._disconnect_clicked)
        remote_layout.addWidget(self.btn_remote_disconnect, stretch=1)

        self.remote_container.hide()
        layout.addWidget(self.remote_container)

        # 7. File transfer container (drag & drop)
        self.transfer_container = QFrame(self)
        self.transfer_container.setObjectName("transferFrame")
        transfer_layout = QHBoxLayout(self.transfer_container)
        transfer_layout.setContentsMargins(8, 3, 8, 3)
        transfer_layout.setSpacing(6)

        self.lbl_transfer_icon = QLabel(self.transfer_container)
        self.lbl_transfer_icon.setFixedSize(14, 14)
        transfer_layout.addWidget(self.lbl_transfer_icon)

        self.files_layout = QHBoxLayout()
        self.files_layout.setContentsMargins(0, 0, 0, 0)
        self.files_layout.setSpacing(4)
        transfer_layout.addLayout(self.files_layout)

        self.lbl_no_files = QLabel("Drop PC files here to send to phone", self.transfer_container)
        self.lbl_no_files.setFont(QFont("Segoe UI Variable Text", 7.5))
        transfer_layout.addWidget(self.lbl_no_files)
        transfer_layout.addStretch()

        self.btn_pull_desktop = QPushButton("Save to Desktop", self.transfer_container)
        self.btn_pull_desktop.setFixedHeight(22)
        self.btn_pull_desktop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pull_desktop.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Medium))
        self.btn_pull_desktop.clicked.connect(self._pull_latest_clicked)
        transfer_layout.addWidget(self.btn_pull_desktop)

        self.transfer_container.hide()
        layout.addWidget(self.transfer_container)

        # Status message
        self.lbl_status_msg = QLabel("", self)
        self.lbl_status_msg.setFont(QFont("Segoe UI Variable Text", 8))
        self.lbl_status_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status_msg.hide()
        layout.addWidget(self.lbl_status_msg)

        # Compatibility stubs
        self.step_labels = []
        self.step_badges = []
        self.btn_remote_rotate = self._create_remote_btn("rotate", "Rotate", "rotate")
        self.btn_remote_rotate.hide()
        self.btn_remote_home = self._create_remote_btn("home", "Home", "home")
        self.btn_remote_home.hide()
        self.btn_remote_back = self._create_remote_btn("arrow_left", "Back", "back")
        self.btn_remote_back.hide()
        self.lbl_hint = QLabel(self)
        self.lbl_hint.hide()

        self._set_guide_mode(self.guide_mode)
        self.set_theme(self.theme)

    def _create_remote_btn(self, icon_name: str, text: str, key_name: str) -> QPushButton:
        btn = QPushButton(f" {text}", self)
        btn.setFixedHeight(26)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
        if key_name == "rotate":
            btn.clicked.connect(self.mgr.toggle_phone_rotation)
        else:
            btn.clicked.connect(lambda: self.mgr.send_phone_key(key_name))
        btn.setProperty("icon_name", icon_name)
        return btn

    def _disconnect_clicked(self):
        self._show_status_msg("Disconnecting...", 2000)
        def _disc():
            adb_exe = self.mgr._find_adb()
            if adb_exe:
                subprocess.run([adb_exe, "disconnect"], capture_output=True, timeout=2, creationflags=0x08000000)
            self.refresh_status()
        threading.Thread(target=_disc, daemon=True).start()

    def get_desired_height(self) -> int:
        self.layout().activate()
        hint = self.layout().sizeHint().height()
        return max(hint, 150)

    def sizeHint(self) -> QSize:
        return QSize(490, self.get_desired_height())

    def _update_overlay_geometry(self):
        if hasattr(self, 'overlay') and self.overlay and self.isVisible():
            QTimer.singleShot(10, self._apply_overlay_geometry)

    def _apply_overlay_geometry(self):
        if hasattr(self, 'overlay') and self.overlay and self.isVisible():
            if hasattr(self.overlay, 'quick_settings_card') and self.overlay.quick_settings_card.isVisible():
                return
            card_h = self.get_desired_height()
            target_h = 56 + card_h + 8
            if abs(self.overlay.spring_h.target - target_h) > 6:
                self.overlay.animate_to_geometry(self.overlay.capsule_width_expanded, target_h)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if urls:
                event.acceptProposedAction()
                self._push_dropped_files(urls)
                return
        super().dropEvent(event)

    def _push_dropped_files(self, paths: List[str]):
        if self.adb_state != "device":
            self._show_status_msg("Connect phone to transfer files", 3000)
            return

        self._show_status_msg(f"Transferring {len(paths)} file(s) to phone...", 3000)
        def _worker():
            ok, msg = self.mgr.push_files_to_phone(paths)
            QTimer.singleShot(0, lambda: self._show_status_msg(msg, 3500))
            if ok:
                QTimer.singleShot(500, self.refresh_recent_files)
        threading.Thread(target=_worker, daemon=True).start()

    def refresh_recent_files(self):
        if self.adb_state != "device":
            return
        def _worker():
            files = self.mgr.get_recent_phone_files(limit=3)
            QTimer.singleShot(0, lambda: self._update_recent_files_ui(files))
        threading.Thread(target=_worker, daemon=True).start()

    def _update_recent_files_ui(self, files: List[Dict[str, str]]):
        if not hasattr(self, 'files_layout'):
            return
        while self.files_layout.count() > 0:
            item = self.files_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if files:
            self.lbl_no_files.hide()
            for f in files:
                badge = DraggablePhoneFileBadge(self.mgr, f, theme=self.theme, parent=self.transfer_container)
                self.files_layout.addWidget(badge)
            self.btn_pull_desktop.setEnabled(True)
        else:
            self.lbl_no_files.show()
            self.btn_pull_desktop.setEnabled(False)

    def _pull_latest_clicked(self):
        if self.adb_state != "device":
            self._show_status_msg("Phone not connected", 2500)
            return
        self._show_status_msg("Pulling latest file to Desktop...", 3000)
        def _worker():
            ok, msg = self.mgr.pull_latest_file_to_desktop()
            QTimer.singleShot(0, lambda: self._show_status_msg(msg, 3500))
        threading.Thread(target=_worker, daemon=True).start()

    def _toggle_guide(self):
        self.guide_card.setVisible(not self.guide_card.isVisible())
        self._update_overlay_geometry()

    def refresh_status(self, force_guide=False):
        self.lbl_phone_name.setText("Scanning USB & Wi-Fi...")
        self.lbl_phone_status.setText("● Looking for connected Android devices...")
        self.lbl_phone_status.setStyleSheet("color: #94A3B8;")
        if force_guide:
            self.guide_card.show()
        self._update_overlay_geometry()
        self.mgr.scan_devices_async()

    def _main_action_clicked(self):
        if not self.mgr.is_scrcpy_available():
            self._show_status_msg("Downloading portable Scrcpy engine...", 3000)
            self.mgr.download_portable_scrcpy()
            return

        if self.adb_state == "device":
            self.mgr.launch_scrcpy(serial=self.adb_serial)
            if hasattr(self, 'overlay') and self.overlay:
                self.overlay.sink()
        elif self.adb_state == "unauthorized":
            self._show_status_msg("Refreshing authorization...", 2500)
            def _reauth():
                adb_exe = self.mgr._find_adb()
                if adb_exe:
                    target = self.adb_serial or (self.txt_ip.text().strip() if hasattr(self, 'txt_ip') else "")
                    if target:
                        subprocess.run([adb_exe, "disconnect", target],
                                       capture_output=True, timeout=2.0, creationflags=0x08000000)
                        subprocess.run([adb_exe, "connect", target],
                                       capture_output=True, timeout=2.0, creationflags=0x08000000)
                    else:
                        subprocess.run([adb_exe, "disconnect"],
                                       capture_output=True, timeout=2.0, creationflags=0x08000000)
                self.refresh_status()
                state, serial, _ = self.mgr.check_adb_devices()
                if state == "device" and serial:
                    self.mgr.launch_scrcpy(serial=serial)
                    if hasattr(self, 'overlay') and self.overlay:
                        self.overlay.sink()
            threading.Thread(target=_reauth, daemon=True).start()
        else:
            # Check if saved device can be reconnected directly
            if self.mgr.has_saved_device():
                saved_target = self.mgr.get_saved_device_ip()
                self._show_status_msg(f"Reconnecting to {saved_target}...", 3000)
                def _recon():
                    adb_exe = self.mgr._find_adb()
                    if adb_exe:
                        subprocess.run([adb_exe, "connect", saved_target],
                                       capture_output=True, timeout=2.5, creationflags=0x08000000)
                    self.refresh_status()
                    state, serial, _ = self.mgr.check_adb_devices()
                    if state == "device" and serial:
                        self.mgr.launch_scrcpy(serial=serial)
                        if hasattr(self, 'overlay') and self.overlay:
                            self.overlay.sink()
                    else:
                        QTimer.singleShot(0, lambda: self._show_status_msg("Device offline. Check Wi-Fi or USB cable", 3500))
                threading.Thread(target=_recon, daemon=True).start()
            else:
                self.guide_card.show()
                self.refresh_status()

    def _on_devices_updated(self, devices: list):
        connected_devs = [d for d in devices if getattr(d, 'is_connected', False)]
        if self.adb_state != "device":
            if connected_devs:
                self.lbl_phone_name.setText(connected_devs[0].name)
            elif not self.mgr.has_saved_device():
                self.lbl_phone_name.setText("No Phone Connected")

    def _on_adb_status_updated(self, state: str, serial: str, model: str):
        self.adb_state = state
        self.adb_serial = serial
        self.adb_model = model

        if state == "device":
            device_display = model or serial or "Android Device"
            self.lbl_phone_name.setText(device_display)
            self.lbl_phone_status.setText("● Connected via USB / Wi-Fi (60fps ready)")
            self.lbl_phone_status.setStyleSheet(f"color: {Tokens.TEXT_PRIMARY.name()}; font-weight: 500;")
            self.lbl_badge.set_status("CONNECTED", "connected")
            self.lbl_badge.setStyleSheet("""
                QLabel {
                    background: rgba(16, 185, 129, 0.18);
                    color: #10B981;
                    border: 1px solid rgba(16, 185, 129, 0.35);
                    border-radius: 8px;
                    padding: 1px 7px;
                }
            """)
            self.btn_main_action.setText("Launch Mirror")
            self.btn_main_action.setEnabled(True)
            self.guide_card.hide()
            self.scrcpy_container.hide()
            self.remote_container.show()
            self.transfer_container.show()
            self.refresh_recent_files()
        elif state == "unauthorized":
            device_display = model or serial or "Android Device"
            self.lbl_phone_name.setText(device_display)
            self.lbl_phone_status.setText("● Unauthorized (Unlock phone & tap Allow)")
            self.lbl_phone_status.setStyleSheet(f"color: {Tokens.TEXT_SECONDARY_HEX}; font-weight: 500;")
            self.lbl_badge.set_status("UNAUTHORIZED", "busy")
            self.lbl_badge.setStyleSheet("""
                QLabel {
                    background: rgba(245, 158, 11, 0.18);
                    color: #F59E0B;
                    border: 1px solid rgba(245, 158, 11, 0.35);
                    border-radius: 8px;
                    padding: 1px 7px;
                }
            """)
            self.btn_main_action.setText("Check Again")
            self.btn_main_action.setEnabled(True)
            self.guide_card.show()
            self.scrcpy_container.show()
            self.remote_container.hide()
            self.transfer_container.hide()
        else: # none / disconnected
            self.lbl_badge.setText("DISCONNECTED")
            self.lbl_badge.setStyleSheet("""
                QLabel {
                    background: rgba(148, 163, 184, 0.15);
                    color: #94A3B8;
                    border: 1px solid rgba(148, 163, 184, 0.25);
                    border-radius: 8px;
                    padding: 1px 7px;
                }
            """)
            if self.mgr.has_saved_device():
                saved_name = self.mgr.get_saved_device_model() or "Saved Phone"
                saved_ip = self.mgr.get_saved_device_ip()
                if "_adb" in saved_ip or len(saved_ip) > 22:
                    ip_display = "Wi-Fi Device"
                else:
                    ip_display = saved_ip
                self.lbl_phone_name.setText(saved_name)
                self.lbl_phone_status.setText(f"● Saved Device ({ip_display})")
                status_col = "#334155" if self.theme == "light" else "#E2E8F0"
                self.lbl_phone_status.setStyleSheet(f"color: {status_col}; font-weight: 500;")
                self.btn_main_action.setText("Reconnect")
                if hasattr(self, 'txt_ip') and not self.txt_ip.text().strip():
                    if not ("_adb" in saved_ip):
                        self.txt_ip.setText(saved_ip)
            else:
                self.lbl_phone_name.setText("No Phone Connected")
                self.lbl_phone_status.setText("● Connect via USB or Wi-Fi below")
                self.lbl_phone_status.setStyleSheet("color: #94A3B8;")
                self.btn_main_action.setText("Scan USB")

            self.btn_main_action.setEnabled(True)
            self.guide_card.show()
            self.scrcpy_container.show()
            self.remote_container.hide()
            self.transfer_container.hide()

        self._update_overlay_geometry()

    def _on_scrcpy_ready_updated(self, ready: bool):
        if not ready:
            self.btn_main_action.setText("Setup Scrcpy")

    def _enable_wireless_clicked(self):
        self._show_status_msg("Switching plugged USB phone to wireless mode...", 3000)
        self.mgr.enable_wireless_mode()

    def _on_wireless_ip_discovered(self, target: str):
        if not ("_adb" in target):
            self.txt_ip.setText(target)

    def _on_download_progress(self, pct: int):
        self.progress_bar.show()
        self.progress_bar.setValue(pct)
        self.btn_main_action.setText(f"Installing {pct}%")

    def _on_download_finished(self, success: bool, msg: str):
        self.progress_bar.hide()
        if success:
            self.btn_main_action.setText("Launch Mirror")
            self._show_status_msg("Scrcpy installed! Ready to mirror.", 3000)
            self.refresh_status()
            state, serial, _ = self.mgr.check_adb_devices()
            if state == "device" and serial:
                self.mgr.launch_scrcpy(serial=serial)
                if hasattr(self, 'overlay') and self.overlay:
                    self.overlay.sink()
        else:
            self.btn_main_action.setText("Retry Setup")
            self._show_status_msg(f"Setup error: {msg}", 4000)

    def _build_steps_rows(self, parent_widget, parent_layout, steps):
        is_light = getattr(self, 'theme', 'dark') == "light"
        step_text_color = "#1E293B" if is_light else "#E2E8F0"
        badge_bg = "rgba(0, 0, 0, 0.08)" if is_light else "rgba(255, 255, 255, 0.12)"
        badge_color = "#0F172A" if is_light else "#FFFFFF"
        for num, title, detail in steps:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)

            badge = QLabel(num, parent_widget)
            badge.setFixedSize(16, 16)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFont(QFont("Segoe UI Variable Text", 6.5, QFont.Weight.Bold))
            badge.setStyleSheet(f"background: {badge_bg}; color: {badge_color}; border-radius: 8px;")
            row.addWidget(badge)
            self.step_badges.append(badge)

            lbl = QLabel(parent_widget)
            lbl.setFont(QFont("Segoe UI Variable Text", 7.8))
            lbl.setText(f"<span style='color: {step_text_color};'><b>{title}:</b> {detail}</span>")
            lbl.setProperty("step_info", (title, detail))
            lbl.setWordWrap(False)
            row.addWidget(lbl, stretch=1)
            self.step_labels.append(lbl)

            parent_layout.addLayout(row)

    def _set_guide_mode(self, mode: str):
        self.guide_mode = mode
        if mode == "usb":
            self.lbl_g_title.setText("USB WIRED GUIDE")
            if hasattr(self, 'guide_usb_widget'):
                self.guide_usb_widget.show()
            if hasattr(self, 'guide_wireless_widget'):
                self.guide_wireless_widget.hide()
            if hasattr(self, 'usb_widget'):
                self.usb_widget.show()
            if hasattr(self, 'wireless_widget'):
                self.wireless_widget.hide()
        else:
            self.lbl_g_title.setText("WI-FI WIRELESS GUIDE")
            if hasattr(self, 'guide_usb_widget'):
                self.guide_usb_widget.hide()
            if hasattr(self, 'guide_wireless_widget'):
                self.guide_wireless_widget.show()
            if hasattr(self, 'usb_widget'):
                self.usb_widget.hide()
            if hasattr(self, 'wireless_widget'):
                self.wireless_widget.show()

        self._update_guide_mode_button_styles()
        self._update_overlay_geometry()

    def _update_guide_mode_button_styles(self):
        if not hasattr(self, 'btn_guide_mode_usb') or not hasattr(self, 'btn_guide_mode_wireless'):
            return
        theme = getattr(self, 'theme', 'dark')
        active_mode = getattr(self, 'guide_mode', 'wireless')

        if theme == "light":
            active_style = """
                QPushButton {
                    background: #0F172A;
                    color: #FFFFFF;
                    border: 1px solid #0F172A;
                    border-radius: 4px;
                    padding: 1px 7px;
                    font-weight: 600;
                    font-size: 7.5pt;
                }
            """
            inactive_style = """
                QPushButton {
                    background: rgba(0, 0, 0, 0.05);
                    color: #475569;
                    border: 1px solid rgba(0, 0, 0, 0.1);
                    border-radius: 4px;
                    padding: 1px 7px;
                    font-size: 7.5pt;
                }
                QPushButton:hover {
                    background: rgba(0, 0, 0, 0.09);
                    color: #0F172A;
                }
            """
        else: # Dark / OLED
            active_style = """
                QPushButton {
                    background: rgba(255, 255, 255, 0.18);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.3);
                    border-radius: 4px;
                    padding: 1px 7px;
                    font-weight: 600;
                    font-size: 7.5pt;
                }
            """
            inactive_style = """
                QPushButton {
                    background: rgba(255, 255, 255, 0.05);
                    color: #94A3B8;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 4px;
                    padding: 1px 7px;
                    font-size: 7.5pt;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.12);
                    color: #E2E8F0;
                }
            """

        if active_mode == "usb":
            self.btn_guide_mode_usb.setStyleSheet(active_style)
            self.btn_guide_mode_wireless.setStyleSheet(inactive_style)
        else:
            self.btn_guide_mode_usb.setStyleSheet(inactive_style)
            self.btn_guide_mode_wireless.setStyleSheet(active_style)

    def _connect_wireless_clicked(self):
        ip = self.txt_ip.text().strip()
        code = self.txt_pair_code.text().strip()
        if not ip:
            self._show_status_msg("Enter phone IP:Port (e.g. 192.168.1.50:37123)", 3000)
            self.txt_ip.setFocus()
            return
        if not code:
            self._show_status_msg("Wi-Fi pairing code is required. Check phone screen.", 3500)
            self.txt_pair_code.setFocus()
            return

        cleaned_code = code.replace(" ", "").replace("-", "")
        self._show_status_msg(f"Pairing & connecting to {ip}...", 3500)
        self.mgr.connect_wireless_adb(ip, pair_code=cleaned_code, auto_launch=True)

    def _sync_clipboard_clicked(self):
        clip = QApplication.clipboard().text()
        if not clip:
            self._show_status_msg("PC clipboard is empty", 2000)
            return
        self.mgr.sync_clipboard_to_phone(clip)
        self._show_status_msg("Clipboard text sent to phone", 2500)

    def _on_operation_finished(self, op: str, msg: str):
        if op == "wireless_connected":
            self._show_status_msg("Connected! Opening mirror...", 2500)
            if hasattr(self, 'overlay') and self.overlay:
                QTimer.singleShot(350, self.overlay.sink)
            return
        elif op == "scrcpy":
            if hasattr(self, 'overlay') and self.overlay:
                self.overlay.sink()
            return
        elif op == "guide":
            self.guide_card.show()
            self._update_overlay_geometry()
        self._show_status_msg(msg, 3500)

    def _show_status_msg(self, text: str, timeout_ms: int = 3500):
        self.lbl_status_msg.setText(text)
        self.lbl_status_msg.show()
        self._update_overlay_geometry()
        QTimer.singleShot(timeout_ms, self._hide_status_msg)

    def _hide_status_msg(self):
        self.lbl_status_msg.hide()
        self._update_overlay_geometry()

    def _open_settings(self):
        try:
            if hasattr(self, 'overlay') and self.overlay:
                if hasattr(self.overlay, 'on_open_settings') and callable(self.overlay.on_open_settings):
                    origin = QRect(self.btn_settings.mapToGlobal(QPoint(0, 0)), QSize(22, 22))
                    self.overlay.on_open_settings(origin, target_setting="Android Mirroring")
                if self.overlay.is_open:
                    self.overlay.sink()
        except Exception as e:
            print(f"[ODD Android Mirror] Open settings error: {e}")

    def set_theme(self, theme: str):
        self.theme = theme
        is_light = theme == "light"
        icon_color = "#0F172A" if is_light else "#FFFFFF"
        sub_icon_color = "#64748B" if is_light else "#A1A1AA"

        self.lbl_title_icon.setPixmap(get_vector_icon("phone", icon_color, 16).pixmap(16, 16))
        self.lbl_banner_icon.setPixmap(get_vector_icon("phone", icon_color, 24).pixmap(24, 24))

        self.btn_guide.setIcon(get_vector_icon("info", sub_icon_color, 13, active_color=icon_color))
        self.btn_guide.setIconSize(QSize(13, 13))

        self.btn_refresh.setIcon(get_vector_icon("refresh", sub_icon_color, 14, active_color=icon_color))
        self.btn_refresh.setIconSize(QSize(14, 14))

        self.btn_settings.setIcon(get_vector_icon("settings", sub_icon_color, 14, active_color=icon_color))
        self.btn_settings.setIconSize(QSize(14, 14))

        main_btn_icon_color = "#FFFFFF" if is_light else "#000000"
        self.btn_main_action.setIcon(get_vector_icon("mirror", main_btn_icon_color, 16))
        self.btn_main_action.setIconSize(QSize(16, 16))

        self.btn_connect_wireless.setIcon(get_vector_icon("wifi", icon_color, 13))
        self.btn_connect_wireless.setIconSize(QSize(13, 13))

        self.btn_enable_wireless.setIcon(get_vector_icon("refresh", icon_color, 13))
        self.btn_enable_wireless.setIconSize(QSize(13, 13))

        if hasattr(self, 'btn_scan_usb'):
            self.btn_scan_usb.setIcon(get_vector_icon("refresh", icon_color, 13))
            self.btn_scan_usb.setIconSize(QSize(13, 13))

        self.btn_remote_power.setIcon(get_vector_icon("power", icon_color, 13))
        self.btn_remote_power.setIconSize(QSize(13, 13))

        self.btn_remote_volup.setIcon(get_vector_icon("volume", icon_color, 13))
        self.btn_remote_volup.setIconSize(QSize(13, 13))

        self.btn_remote_voldn.setIcon(get_vector_icon("volume", icon_color, 13))
        self.btn_remote_voldn.setIconSize(QSize(13, 13))

        self.btn_remote_clip.setIcon(get_vector_icon("copy", icon_color, 13))
        self.btn_remote_clip.setIconSize(QSize(13, 13))

        self.btn_remote_home.setIcon(get_vector_icon("home", icon_color, 13))
        self.btn_remote_home.setIconSize(QSize(13, 13))

        self.btn_remote_back.setIcon(get_vector_icon("arrow_left", icon_color, 13))
        self.btn_remote_back.setIconSize(QSize(13, 13))

        if hasattr(self, 'lbl_transfer_icon') and self.lbl_transfer_icon:
            self.lbl_transfer_icon.setPixmap(get_vector_icon("folder", icon_color, 14).pixmap(14, 14))
        if hasattr(self, 'btn_pull_desktop') and self.btn_pull_desktop:
            self.btn_pull_desktop.setIcon(get_vector_icon("desktop", icon_color, 12))
            self.btn_pull_desktop.setIconSize(QSize(12, 12))

        header_btn_style = """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 2px;
            }
            QPushButton:hover {
                background: rgba(0, 0, 0, 0.08);
            }
        """ if is_light else """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 2px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.14);
            }
        """
        self.btn_refresh.setStyleSheet(header_btn_style)
        self.btn_settings.setStyleSheet(header_btn_style)

        guide_toggle_style = """
            QPushButton {
                background: rgba(0, 0, 0, 0.05);
                color: #475569;
                border: 1px solid rgba(0, 0, 0, 0.1);
                border-radius: 5px;
                padding: 1px 7px;
                font-size: 7.5pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(0, 0, 0, 0.09);
                color: #0F172A;
            }
        """ if is_light else """
            QPushButton {
                background: rgba(255, 255, 255, 0.07);
                color: #94A3B8;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 5px;
                padding: 1px 7px;
                font-size: 7.5pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.14);
                color: #FFFFFF;
            }
        """
        self.btn_guide.setStyleSheet(guide_toggle_style)

        if is_light:
            self.lbl_title.setStyleSheet("color: #0F172A;")
            self.lbl_esc.setStyleSheet("color: rgba(100, 116, 139, 0.7);")
            self.lbl_phone_name.setStyleSheet("color: #0F172A;")
            self.lbl_status_msg.setStyleSheet("color: #059669; font-weight: 600;")
            self.lbl_g_title.setStyleSheet("color: #64748B;")

            self.banner_frame.setStyleSheet("""
                #phoneBanner {
                    background: rgba(241, 245, 249, 0.9);
                    border: 1px solid rgba(203, 213, 225, 0.85);
                    border-radius: 10px;
                }
            """)
            self.guide_card.setStyleSheet("""
                #guideFrame {
                    background: rgba(248, 250, 252, 0.95);
                    border: 1px solid rgba(226, 232, 240, 0.95);
                    border-radius: 8px;
                }
            """)
            self.scrcpy_container.setStyleSheet("""
                #scrcpyFrame {
                    background: rgba(248, 250, 252, 0.9);
                    border: 1px solid rgba(226, 232, 240, 0.95);
                    border-radius: 8px;
                }
            """)
            self.transfer_container.setStyleSheet("""
                #transferFrame {
                    background: rgba(248, 250, 252, 0.85);
                    border: 1px dashed rgba(203, 213, 225, 0.9);
                    border-radius: 8px;
                }
            """)
            self.lbl_no_files.setStyleSheet("color: #64748B;")
            self.btn_pull_desktop.setStyleSheet("""
                QPushButton {
                    background: rgba(15, 23, 42, 0.06);
                    color: #0F172A;
                    border: 1px solid rgba(15, 23, 42, 0.15);
                    border-radius: 5px;
                    padding: 2px 7px;
                }
                QPushButton:hover {
                    background: rgba(15, 23, 42, 0.12);
                }
            """)
            self.btn_main_action.setStyleSheet("""
                QPushButton {
                    background: #0F172A;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 7px;
                    padding: 4px 12px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #1E293B;
                }
                QPushButton:pressed {
                    background: #334155;
                }
            """)
            input_style = """
                QLineEdit {
                    background: #FFFFFF;
                    border: 1px solid #CBD5E1;
                    border-radius: 6px;
                    color: #0F172A;
                    padding: 3px 8px;
                }
                QLineEdit:focus {
                    border-color: #475569;
                }
            """
            btn_pill_style = """
                QPushButton {
                    background: rgba(0, 0, 0, 0.05);
                    color: #1E293B;
                    border: 1px solid rgba(0, 0, 0, 0.12);
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-weight: 500;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(0, 0, 0, 0.09);
                    border-color: rgba(0, 0, 0, 0.2);
                    color: #0F172A;
                }
                QPushButton:pressed {
                    background: rgba(0, 0, 0, 0.14);
                }
            """
        else: # Dark / OLED
            is_oled = theme == "oled"
            bg_base = "#000000" if is_oled else "rgba(255, 255, 255, 0.04)"
            banner_bg = "#000000" if is_oled else "rgba(255, 255, 255, 0.07)"
            border_base = "rgba(255, 255, 255, 0.16)" if is_oled else "rgba(255, 255, 255, 0.08)"

            self.lbl_title.setStyleSheet("color: #FFFFFF;")
            self.lbl_esc.setStyleSheet("color: rgba(255, 255, 255, 0.45);")
            self.lbl_phone_name.setStyleSheet("color: #FFFFFF;")
            self.lbl_status_msg.setStyleSheet("color: rgba(255, 255, 255, 0.95); font-weight: 600;")
            self.lbl_g_title.setStyleSheet("color: #94A3B8;")

            self.banner_frame.setStyleSheet(f"""
                #phoneBanner {{
                    background: {banner_bg};
                    border: 1px solid {border_base};
                    border-radius: 10px;
                }}
            """)
            self.guide_card.setStyleSheet(f"""
                #guideFrame {{
                    background: {bg_base};
                    border: 1px solid {border_base};
                    border-radius: 8px;
                }}
            """)
            self.scrcpy_container.setStyleSheet(f"""
                #scrcpyFrame {{
                    background: {bg_base};
                    border: 1px solid {border_base};
                    border-radius: 8px;
                }}
            """)
            self.transfer_container.setStyleSheet(f"""
                #transferFrame {{
                    background: {bg_base};
                    border: 1px dashed {border_base};
                    border-radius: 8px;
                }}
            """)
            self.lbl_no_files.setStyleSheet("color: #94A3B8;")
            self.btn_pull_desktop.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08);
                    color: #E2E8F0;
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    border-radius: 5px;
                    padding: 2px 7px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.16);
                }
            """)
            self.btn_main_action.setStyleSheet("""
                QPushButton {
                    background: #FFFFFF;
                    color: #000000;
                    border: none;
                    border-radius: 7px;
                    padding: 4px 12px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #E2E8F0;
                }
                QPushButton:pressed {
                    background: #CBD5E1;
                }
            """)
            input_style = """
                QLineEdit {
                    background: rgba(0, 0, 0, 0.35);
                    border: 1px solid rgba(255, 255, 255, 0.14);
                    border-radius: 6px;
                    color: #FFFFFF;
                    padding: 3px 8px;
                }
                QLineEdit:focus {
                    border-color: rgba(255, 255, 255, 0.45);
                }
            """
            btn_pill_style = """
                QPushButton {
                    background: rgba(255, 255, 255, 0.08);
                    color: #E2E8F0;
                    border: 1px solid rgba(255, 255, 255, 0.14);
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-weight: 500;
                    text-align: center;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.15);
                    border-color: rgba(255, 255, 255, 0.25);
                    color: #FFFFFF;
                }
                QPushButton:pressed {
                    background: rgba(255, 255, 255, 0.2);
                }
            """

        self.txt_ip.setStyleSheet(input_style)
        self.txt_pair_code.setStyleSheet(input_style)

        self.btn_connect_wireless.setStyleSheet(btn_pill_style)
        self.btn_enable_wireless.setStyleSheet(btn_pill_style)
        if hasattr(self, 'btn_scan_usb'):
            self.btn_scan_usb.setStyleSheet(btn_pill_style)
        self.btn_remote_power.setStyleSheet(btn_pill_style)
        self.btn_remote_volup.setStyleSheet(btn_pill_style)
        self.btn_remote_voldn.setStyleSheet(btn_pill_style)
        self.btn_remote_clip.setStyleSheet(btn_pill_style)
        self.btn_remote_home.setStyleSheet(btn_pill_style)
        self.btn_remote_back.setStyleSheet(btn_pill_style)
        if hasattr(self, 'btn_remote_disconnect'):
            self.btn_remote_disconnect.setStyleSheet(btn_pill_style)

        self._update_guide_mode_button_styles()

        step_text_color = "#1E293B" if is_light else "#E2E8F0"
        badge_bg = "rgba(0, 0, 0, 0.08)" if is_light else "rgba(255, 255, 255, 0.12)"
        badge_color = "#0F172A" if is_light else "#FFFFFF"
        for lbl in getattr(self, 'step_labels', []):
            info = lbl.property("step_info")
            if info:
                t, d = info
                lbl.setText(f"<span style='color: {step_text_color};'><b>{t}:</b> {d}</span>")
            else:
                lbl.setStyleSheet(f"color: {step_text_color};")
        for b in getattr(self, 'step_badges', []):
            b.setStyleSheet(f"background: {badge_bg}; color: {badge_color}; border-radius: 8px;")

        if hasattr(self, 'files_layout'):
            for i in range(self.files_layout.count()):
                item = self.files_layout.itemAt(i)
                if item and item.widget() and isinstance(item.widget(), DraggablePhoneFileBadge):
                    item.widget().apply_theme(theme)
