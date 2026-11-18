"""
ODD Dedicated COM & Hardware Subsystem (Thread-Safe Single-Apartment Worker)
Owns all Windows COM objects (pycaw, comtypes, WMI, NLM) on a single persistent
worker thread, eliminating cross-thread COM marshalling violations, RPC errors,
and device-invalidation crashes when headphones are unplugged or audio outputs switch.
"""

import sys
import os
import time
import queue
import threading
import subprocess
from typing import Tuple, Dict, Any, Optional
from PySide6.QtCore import QObject, Signal

from odd_crash_capture import log_breadcrumb, logger, safe_slot


class ComWorker(QObject):
    """
    Dedicated background worker thread that exclusively owns COM initialization,
    IAudioEndpointVolume, WMI Brightness, and Windows hardware inspection.
    Never exposes raw COM pointers across thread boundaries.
    """
    # Signals emitted to the GUI thread with pure Python primitive values
    audio_state_changed = Signal(int, bool, str)     # (volume_pct, is_muted, device_name)
    brightness_state_changed = Signal(int, bool)     # (brightness_pct, is_supported)
    hardware_state_changed = Signal(dict)            # hardware status dictionary
    radio_state_changed = Signal(str, bool)          # ("WiFi"|"Bluetooth", is_on)

    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ComWorker":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = ComWorker()
                cls._instance.start()
            return cls._instance

    def __init__(self):
        super().__init__()
        self._cmd_queue = queue.Queue()
        self._thread = None
        self._running = False

        # Volume state cache
        self._last_vol = 70
        self._last_muted = False
        self._last_device_name = "Speakers"
        self._vol_endpoint = None

        # Brightness state cache
        self._cached_brightness = 70
        self._brightness_supported: Optional[bool] = None
        self._wmi_brightness_methods = None

        # Hardware inspection cache
        self._cached_hardware = {}
        self._last_hw_query_ts = 0.0

        # Coalescing pending targets (latest-value-wins)
        self._pending_vol_lock = threading.Lock()
        self._pending_vol_target: Optional[int] = None
        self._pending_bright_lock = threading.Lock()
        self._pending_bright_target: Optional[int] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="ODD_COM_Worker")
        self._thread.start()
        log_breadcrumb("COM worker thread started", category="com")

    def stop(self):
        self._running = False
        self._cmd_queue.put(("STOP", None))

    # --- Public Thread-Safe API (callable from GUI or any thread) ---

    def set_volume(self, vol_pct: int):
        """Coalesced volume update: intermediate slider steps are dropped, latest wins."""
        clamped = max(0, min(100, int(vol_pct)))
        with self._pending_vol_lock:
            self._pending_vol_target = clamped
        self._cmd_queue.put(("SET_VOLUME_COALESCED", None))

    def set_mute(self, muted: bool):
        self._cmd_queue.put(("SET_MUTE", bool(muted)))

    def set_brightness(self, val_pct: int):
        """Coalesced brightness update: intermediate slider steps are dropped, latest wins."""
        clamped = max(0, min(100, int(val_pct)))
        with self._pending_bright_lock:
            self._pending_bright_target = clamped
        self._cmd_queue.put(("SET_BRIGHTNESS_COALESCED", None))

    def request_audio_sync(self):
        self._cmd_queue.put(("QUERY_AUDIO", None))

    def request_brightness_sync(self):
        self._cmd_queue.put(("QUERY_BRIGHTNESS", None))

    def request_hardware_sync(self, force: bool = False):
        self._cmd_queue.put(("QUERY_HARDWARE", force))

    def toggle_radio(self, kind: str, enable: bool):
        self._cmd_queue.put(("TOGGLE_RADIO", (kind, enable)))

    def _on_audio_device_changed(self):
        """Called on Windows audio default device change or headphone unplug."""
        self._vol_endpoint = None
        self._cmd_queue.put(("QUERY_AUDIO", None))

    def get_cached_volume(self) -> Tuple[int, bool]:
        return self._last_vol, self._last_muted

    def get_cached_brightness(self) -> int:
        return self._cached_brightness

    def get_cached_hardware(self) -> dict:
        return dict(self._cached_hardware)

    def get_volume_info(self) -> Tuple[int, bool]:
        return self.get_cached_volume()

    def get_brightness_info(self) -> int:
        return self.get_cached_brightness()

    def get_hardware_state(self) -> dict:
        return self.get_cached_hardware()

    @property
    def last_volume(self) -> int:
        return self._last_vol

    @property
    def last_mute(self) -> bool:
        return self._last_muted

    @property
    def last_brightness(self) -> int:
        return self._cached_brightness

    # --- Worker Thread Loop & COM Lifecycle ---

    def _worker_loop(self):
        import pythoncom
        try:
            pythoncom.CoInitialize()
        except Exception as e:
            logger.error(f"[COM WORKER] CoInitialize failed: {e}")

        try:
            # Initial probe of audio and brightness
            self._acquire_audio_endpoint()
            self._query_audio_internal()
            self._probe_brightness_internal()
            self._query_hardware_internal()

            while self._running:
                try:
                    # Wait up to 500ms for incoming requests
                    cmd, arg = self._cmd_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                if cmd == "STOP":
                    break
                elif cmd == "SET_VOLUME_COALESCED":
                    with self._pending_vol_lock:
                        target = self._pending_vol_target
                        self._pending_vol_target = None
                    if target is not None:
                        self._apply_volume_internal(target)
                elif cmd == "SET_MUTE":
                    self._apply_mute_internal(arg)
                elif cmd == "SET_BRIGHTNESS_COALESCED":
                    with self._pending_bright_lock:
                        target = self._pending_bright_target
                        self._pending_bright_target = None
                    if target is not None:
                        self._apply_brightness_internal(target)
                elif cmd == "QUERY_AUDIO":
                    self._query_audio_internal()
                elif cmd == "QUERY_BRIGHTNESS":
                    self._query_brightness_internal()
                elif cmd == "QUERY_HARDWARE":
                    self._query_hardware_internal(force=arg)
                elif cmd == "TOGGLE_RADIO":
                    kind, enable = arg
                    threading.Thread(target=self._toggle_radio_internal, args=(kind, enable), daemon=True).start()

        except Exception as e:
            logger.error(f"[COM WORKER] Fatal loop exception: {e}")
        finally:
            self._vol_endpoint = None
            self._wmi_brightness_methods = None
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            log_breadcrumb("COM worker thread terminated", category="com")

    # --- Audio Endpoint Management ---

    def _acquire_audio_endpoint(self) -> bool:
        """Acquires default audio playback endpoint cleanly on the COM thread."""
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            device = AudioUtilities.GetSpeakers()
            if device:
                if hasattr(device, "Activate"):
                    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    self._vol_endpoint = interface.QueryInterface(IAudioEndpointVolume)
                elif hasattr(device, "EndpointVolume"):
                    self._vol_endpoint = device.EndpointVolume
                else:
                    self._vol_endpoint = None
                return self._vol_endpoint is not None
        except Exception as e:
            self._vol_endpoint = None
            logger.debug(f"[COM WORKER] _acquire_audio_endpoint failed: {e}")
        return False

    def _query_audio_internal(self):
        """Reads volume, mute, and default device name safely with auto-recovery on device unplug."""
        if not self._vol_endpoint:
            if not self._acquire_audio_endpoint():
                return

        try:
            vol_scalar = self._vol_endpoint.GetMasterVolumeLevelScalar()
            is_muted = bool(self._vol_endpoint.GetMute())
            vol_pct = int(round(vol_scalar * 100))
            device_name = self._get_device_name_internal()

            self._last_vol = vol_pct
            self._last_muted = is_muted
            self._last_device_name = device_name
            self.audio_state_changed.emit(vol_pct, is_muted, device_name)
        except Exception as e:
            # Device may have been unplugged (AUDCLNT_E_DEVICE_INVALIDATED 0x88890004)
            logger.debug(f"[COM WORKER] Audio query failed, retrying endpoint acquisition: {e}")
            self._vol_endpoint = None
            if self._acquire_audio_endpoint():
                try:
                    vol_scalar = self._vol_endpoint.GetMasterVolumeLevelScalar()
                    is_muted = bool(self._vol_endpoint.GetMute())
                    vol_pct = int(round(vol_scalar * 100))
                    device_name = self._get_device_name_internal()
                    self._last_vol = vol_pct
                    self._last_muted = is_muted
                    self._last_device_name = device_name
                    self.audio_state_changed.emit(vol_pct, is_muted, device_name)
                except Exception:
                    pass

    def _apply_volume_internal(self, val_pct: int):
        if not self._vol_endpoint:
            if not self._acquire_audio_endpoint():
                return

        try:
            scalar = max(0.0, min(1.0, val_pct / 100.0))
            self._vol_endpoint.SetMasterVolumeLevelScalar(scalar, None)
            if val_pct <= 0:
                self._vol_endpoint.SetMute(1, None)
                self._last_muted = True
            elif val_pct > 0:
                try:
                    if self._last_muted or bool(self._vol_endpoint.GetMute()):
                        self._vol_endpoint.SetMute(0, None)
                        self._last_muted = False
                except Exception:
                    pass
            self._last_vol = val_pct
            self.audio_state_changed.emit(val_pct, self._last_muted, self._last_device_name)
        except Exception:
            # Device invalidated, re-acquire and retry once
            self._vol_endpoint = None
            if self._acquire_audio_endpoint():
                try:
                    scalar = max(0.0, min(1.0, val_pct / 100.0))
                    self._vol_endpoint.SetMasterVolumeLevelScalar(scalar, None)
                    if val_pct <= 0:
                        self._vol_endpoint.SetMute(1, None)
                        self._last_muted = True
                    elif val_pct > 0:
                        try:
                            if self._last_muted or bool(self._vol_endpoint.GetMute()):
                                self._vol_endpoint.SetMute(0, None)
                                self._last_muted = False
                        except Exception:
                            pass
                    self._last_vol = val_pct
                    self.audio_state_changed.emit(val_pct, self._last_muted, self._last_device_name)
                except Exception:
                    pass

    def _apply_mute_internal(self, muted: bool):
        if not self._vol_endpoint:
            if not self._acquire_audio_endpoint():
                return
        try:
            self._vol_endpoint.SetMute(1 if muted else 0, None)
            self._last_muted = bool(muted)
            self.audio_state_changed.emit(self._last_vol, self._last_muted, self._last_device_name)
        except Exception:
            self._vol_endpoint = None

    def _get_device_name_internal(self) -> str:
        try:
            import ctypes
            from pycaw.pycaw import AudioUtilities, PROPERTYKEY
            from comtypes import _GUID
            device = AudioUtilities.GetSpeakers()
            if device:
                props = device.OpenPropertyStore(0)
                key = PROPERTYKEY()
                key.fmtid = _GUID('{a45c254e-df1c-4efd-8020-67d146a850e0}')
                key.pid = 14
                val = props.GetValue(ctypes.byref(key))
                v = val.GetValue()
                if v:
                    return str(v)
        except Exception:
            pass
        return "Speakers"

    # --- Brightness Management ---

    def _probe_brightness_internal(self):
        """Probes once whether WMI monitor brightness is supported on this machine."""
        if self._brightness_supported is not None:
            return

        try:
            import win32com.client
            wmi = win32com.client.GetObject('winmgmts:\\\\.\\root\\wmi')
            monitors = list(wmi.InstancesOf('WmiMonitorBrightness'))
            if monitors:
                self._cached_brightness = max(0, min(100, int(monitors[0].CurrentBrightness)))
                self._brightness_supported = True
                methods = list(wmi.InstancesOf('WmiMonitorBrightnessMethods'))
                self._wmi_brightness_methods = methods
                self.brightness_state_changed.emit(self._cached_brightness, True)
                return
        except Exception:
            pass

        # If WMI is not supported (standard desktop monitor), NEVER poll or run PowerShell
        self._brightness_supported = False
        self._cached_brightness = 100
        self.brightness_state_changed.emit(100, False)

    def _query_brightness_internal(self):
        if self._brightness_supported is False:
            self.brightness_state_changed.emit(self._cached_brightness, False)
            return

        if self._brightness_supported is None:
            self._probe_brightness_internal()
            return

        try:
            import win32com.client
            wmi = win32com.client.GetObject('winmgmts:\\\\.\\root\\wmi')
            monitors = list(wmi.InstancesOf('WmiMonitorBrightness'))
            if monitors:
                val = max(0, min(100, int(monitors[0].CurrentBrightness)))
                self._cached_brightness = val
                self.brightness_state_changed.emit(val, True)
        except Exception:
            pass

    def _apply_brightness_internal(self, val_pct: int):
        clamped = max(0, min(100, int(val_pct)))
        self._cached_brightness = clamped

        if self._brightness_supported is False:
            self.brightness_state_changed.emit(clamped, False)
            return

        try:
            if not self._wmi_brightness_methods:
                import win32com.client
                wmi = win32com.client.GetObject('winmgmts:\\\\.\\root\\wmi')
                self._wmi_brightness_methods = list(wmi.InstancesOf('WmiMonitorBrightnessMethods'))

            for m in self._wmi_brightness_methods:
                in_params = m.Methods_('WmiSetBrightness').InParameters.SpawnInstance_()
                in_params.Properties_('Brightness').Value = clamped
                in_params.Properties_('Timeout').Value = 1
                m.ExecMethod_('WmiSetBrightness', in_params)
            self.brightness_state_changed.emit(clamped, True)
        except Exception:
            # Re-probe if method reference failed
            self._wmi_brightness_methods = None
            try:
                import win32com.client
                wmi = win32com.client.GetObject('winmgmts:\\\\.\\root\\wmi')
                methods = list(wmi.InstancesOf('WmiMonitorBrightnessMethods'))
                for m in methods:
                    in_params = m.Methods_('WmiSetBrightness').InParameters.SpawnInstance_()
                    in_params.Properties_('Brightness').Value = clamped
                    in_params.Properties_('Timeout').Value = 1
                    m.ExecMethod_('WmiSetBrightness', in_params)
                self._wmi_brightness_methods = methods
                self.brightness_state_changed.emit(clamped, True)
            except Exception as e:
                logger.debug(f"[COM WORKER] WmiSetBrightness failed: {e}")
            except Exception:
                pass

    # --- Hardware Inspection (Wi-Fi, Bluetooth, Night Light, Battery) ---

    def _query_hardware_internal(self, force: bool = False):
        now = time.time()
        if not force and (now - self._last_hw_query_ts < 1.0) and self._cached_hardware:
            self.hardware_state_changed.emit(dict(self._cached_hardware))
            return

        self._last_hw_query_ts = now
        wifi_on = False
        wifi_name = "Wi-Fi"
        bt_on = False
        bt_name = "Bluetooth"
        night_on = False
        batt_pct = -1
        batt_plugged = False

        # 1. Native Wi-Fi Query via wlanapi (with boundary checks)
        try:
            import ctypes
            from ctypes import wintypes
            wlanapi = ctypes.windll.wlanapi
            wlanapi.WlanOpenHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.HANDLE)]
            wlanapi.WlanOpenHandle.restype = wintypes.DWORD
            wlanapi.WlanCloseHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
            wlanapi.WlanCloseHandle.restype = wintypes.DWORD
            wlanapi.WlanFreeMemory.argtypes = [ctypes.c_void_p]
            wlanapi.WlanFreeMemory.restype = None

            cv = wintypes.DWORD()
            h = wintypes.HANDLE()
            if wlanapi.WlanOpenHandle(2, None, ctypes.byref(cv), ctypes.byref(h)) == 0:
                try:
                    class GUID(ctypes.Structure):
                        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD), ('Data4', wintypes.BYTE * 8)]
                    class WLAN_INTERFACE_INFO(ctypes.Structure):
                        _fields_ = [('InterfaceGuid', GUID), ('strInterfaceDescription', wintypes.WCHAR * 256), ('isState', wintypes.DWORD)]
                    class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
                        _fields_ = [('dwNumberOfItems', wintypes.DWORD), ('dwIndex', wintypes.DWORD), ('InterfaceInfo', WLAN_INTERFACE_INFO * 1)]

                    pList = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
                    wlanapi.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST))]
                    wlanapi.WlanEnumInterfaces.restype = wintypes.DWORD

                    if wlanapi.WlanEnumInterfaces(h, None, ctypes.byref(pList)) == 0 and pList:
                        try:
                            if pList.contents and pList.contents.dwNumberOfItems > 0:
                                info = pList.contents.InterfaceInfo[0]
                                wifi_radio_on = (info.isState != 0)
                                wifi_connected = (info.isState == 1)
                                wifi_on = wifi_radio_on
                                if not wifi_radio_on:
                                    wifi_name = "Off"
                                elif not wifi_connected:
                                    wifi_name = "Disconnected"
                                else:
                                    wifi_name = "Connected"
                                    try:
                                        import win32com.client
                                        nlm = win32com.client.Dispatch("{DCB00C01-570F-4A9B-8D69-199FDBA5723B}")
                                        if nlm.IsConnected:
                                            for net in nlm.GetNetworks(1):
                                                n = net.GetName()
                                                if n:
                                                    wifi_name = str(n)
                                                    break
                                    except Exception:
                                        pass
                        finally:
                            wlanapi.WlanFreeMemory(pList)
                finally:
                    wlanapi.WlanCloseHandle(h, None)
        except Exception:
            pass

        # 2. Native zero-latency Bluetooth Radio & Device inspection via bthprops.cpl
        try:
            import ctypes
            from ctypes import wintypes

            class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
                _fields_ = [('dwSize', wintypes.DWORD)]

            bth = ctypes.windll.LoadLibrary('bthprops.cpl')
            bth.BluetoothFindFirstRadio.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.HANDLE)]
            bth.BluetoothFindFirstRadio.restype = wintypes.HANDLE
            bth.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
            bth.BluetoothFindRadioClose.restype = wintypes.BOOL

            params = BLUETOOTH_FIND_RADIO_PARAMS()
            params.dwSize = ctypes.sizeof(params)
            h_radio = wintypes.HANDLE()
            h_find = bth.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(h_radio))
            if h_find:
                try:
                    bth.BluetoothFindRadioClose(h_find)
                except Exception:
                    pass
                if h_radio.value:
                    try:
                        ctypes.windll.kernel32.CloseHandle(h_radio)
                    except Exception:
                        pass

                bt_on = True
                bt_name = "On"
                try:
                    import odd_overlay
                    devs = odd_overlay.get_connected_bluetooth_devices()
                    if devs:
                        bt_name = "  •  ".join(devs)
                except Exception:
                    pass
            else:
                bt_on = False
                bt_name = "OFF"
        except Exception as e:
            logger.debug(f"[COM WORKER] Bluetooth query exception: {e}")
            bt_on = False
            bt_name = "OFF"

        # 3. Night Light via Registry
        try:
            import winreg
            p = r'Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current\default$windows.data.bluelightreduction.bluelightreductionstate\windows.data.bluelightreduction.bluelightreductionstate'
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, p)
            d, _ = winreg.QueryValueEx(k, 'Data')
            if len(d) >= 19:
                night_on = (d[18] == 0x15)
        except Exception:
            pass

        # 4. Battery info via psutil
        try:
            import psutil
            b = psutil.sensors_battery()
            if b:
                batt_pct = int(b.percent)
                batt_plugged = bool(b.power_plugged)
        except Exception:
            pass

        state = {
            "wifi_on": wifi_on,
            "wifi_name": wifi_name,
            "bt_on": bt_on,
            "bt_name": bt_name,
            "night_on": night_on,
            "sound_name": self._last_device_name,
            "batt_pct": batt_pct,
            "batt_plugged": batt_plugged,
        }
        self._cached_hardware = state
        self.hardware_state_changed.emit(state)

    def _toggle_radio_internal(self, kind: str, enable: bool):
        target_state = "On" if enable else "Off"
        ps_cmd = f"""
        [Windows.Devices.Radios.Radio,Windows.System,ContentType=WindowsRuntime] | Out-Null
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }} | Select-Object -First 1
        function AwaitOp($op, $t) {{
            $m = $asTaskGeneric.MakeGenericMethod($t)
            $task = $m.Invoke($null, @($op))
            $task.Wait(2000) | Out-Null
            return $task.Result
        }}
        $radios = AwaitOp ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
        foreach ($r in $radios) {{
            if ($r.Kind.ToString().ToLower() -eq '{kind.lower()}') {{
                $st = if ('{target_state.lower()}' -eq 'on') {{ [Windows.Devices.Radios.RadioState]::On }} else {{ [Windows.Devices.Radios.RadioState]::Off }}
                AwaitOp ($r.SetStateAsync($st)) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
                break
            }}
        }}
        """
        try:
            import base64
            encoded = base64.b64encode(ps_cmd.encode('utf-16le')).decode('ascii')
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                timeout=4,
                check=False
            )
            self.radio_state_changed.emit(kind, enable)
            self._cmd_queue.put(("QUERY_HARDWARE", True))
        except Exception as e:
            logger.debug(f"[COM WORKER] toggle_radio failed: {e}")
