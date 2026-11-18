import sys
import os
import ctypes
import ctypes.wintypes
import threading
import time
from pathlib import Path

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

class SafeStream:
    def __init__(self, target):
        self.target = target
    def write(self, s):
        try:
            if self.target:
                self.target.write(s)
        except Exception:
            pass
    def flush(self):
        try:
            if self.target:
                self.target.flush()
        except Exception:
            pass

try:
    if sys.stdout:
        sys.stdout.write("")
        sys.stdout.flush()
    else:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
except Exception:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')

try:
    if sys.stderr:
        sys.stderr.write("")
        sys.stderr.flush()
    else:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
except Exception:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

sys.stdout = SafeStream(sys.stdout)
sys.stderr = SafeStream(sys.stderr)

from odd_crash_capture import install_crash_capture, log_breadcrumb, safe_slot, logger
install_crash_capture()

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QEvent, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QPoint, QRect, QAbstractNativeEventFilter, QCoreApplication
from PySide6.QtGui import QIcon, QAction, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QWidget
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from pynput import keyboard

from odd_settings import load_settings, save_settings, set_startup_enabled, is_rook_installed, is_rook_running
from odd_search import WindowsSearchEngine
from odd_overlay import OddOverlay, EdgeTriggerWindow, get_app_icon, is_mouse_dragging
from odd_settings_dialog import SettingsDialog
from odd_updater import UpdateManager, CURRENT_VERSION, ReleaseInfo
import odd_sound
from fluentapp.windoweffect import WindowBlur

# Transparent blur with acrylic and black tint for overall ODD UI (no draggable)
WindowBlur(radius=50, acrylic=True, draggable=False)

odd_sound.init_sound_engine()

IPC_SERVER_NAME = "ODD_Search_SingleInstance_IPC_Server"
MUTEX_NAME = "Local\\ODD_Search_SingleInstance_Mutex_v1"
_app_mutex = None

def acquire_single_instance_mutex() -> bool:
    """
    Acquires a Win32 Mutex to reliably check if another instance of ODD is running.
    Returns True if this is the primary instance, False if another instance exists.
    """
    global _app_mutex
    ERROR_ALREADY_EXISTS = 183
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = ctypes.c_ulong
        _app_mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not _app_mutex:
            # Do not silently disable single-instance protection when Windows
            # cannot create the mutex. Startup will report this as a failure.
            return False
        last_error = kernel32.GetLastError()
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.CloseHandle(_app_mutex)
            _app_mutex = None
            return False
        return True
    except Exception as e:
        print(f"[STARTUP] Single-instance mutex setup failed: {e}")
        return False

def notify_running_instance():
    """Wakes up the active running instance via local IPC socket"""
    try:
        client = QLocalSocket()
        client.connectToServer(IPC_SERVER_NAME)
        if client.waitForConnected(1000):
            client.write(b"surface\n")
            client.flush()
            delivered = client.waitForBytesWritten(1000)
            client.waitForReadyRead(250)
            client.disconnectFromServer()
            return True
    except Exception:
        pass
    return False

def recover_unresponsive_instance() -> bool:
    """Stop an old ODD process that owns the mutex but cannot receive IPC."""
    try:
        import psutil
        expected = os.path.normcase(os.path.realpath(sys.executable))
        victims = []
        for proc in psutil.process_iter(["pid", "exe"]):
            try:
                if proc.info["pid"] == os.getpid():
                    continue
                executable = proc.info.get("exe")
                if executable and os.path.normcase(os.path.realpath(executable)) == expected:
                    victims.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not victims:
            return False
        for proc in victims:
            try:
                proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        _, alive = psutil.wait_procs(victims, timeout=1.5)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return True
    except Exception as e:
        print(f"[STARTUP] Could not recover the unresponsive ODD instance: {e}")
        return False



def parse_hotkey(hotkey_str: str) -> tuple[int, int]:
    """Parses a shortcut string (e.g. 'Alt+Space', 'Ctrl+Space', 'F12') into Win32 (modifiers, vk_code)."""
    tokens = [t.strip().lower() for t in hotkey_str.replace('+', ' ').split()]
    mods = 0
    vk = 0
    key_token = None

    for t in tokens:
        if t in ('alt', 'menu'):
            mods |= 0x0001
        elif t in ('ctrl', 'control'):
            mods |= 0x0002
        elif t in ('shift',):
            mods |= 0x0004
        elif t in ('win', 'windows', 'meta', 'super', 'cmd'):
            mods |= 0x0008
        else:
            key_token = t

    VK_MAP = {
        'space': 0x20,
        'return': 0x0D,
        'enter': 0x0D,
        'tab': 0x09,
        'esc': 0x1B,
        'escape': 0x1B,
        'backspace': 0x08,
        'delete': 0x2E,
        'del': 0x2E,
        'insert': 0x2D,
        'ins': 0x2D,
        'home': 0x24,
        'end': 0x23,
        'pageup': 0x21,
        'pgup': 0x21,
        'pagedown': 0x22,
        'pgdown': 0x22,
        'left': 0x25,
        'up': 0x26,
        'right': 0x27,
        'down': 0x28,
        '`': 0xC0,
        '~': 0xC0,
        '-': 0xBD,
        '=': 0xBB,
        '[': 0xDB,
        ']': 0xDD,
        '\\': 0xDC,
        ';': 0xBA,
        "'": 0xDE,
        ',': 0xBC,
        '.': 0xBE,
        '/': 0xBF,
    }
    for i in range(1, 25):
        VK_MAP[f'f{i}'] = 0x70 + (i - 1)

    if key_token:
        if key_token in VK_MAP:
            vk = VK_MAP[key_token]
        elif len(key_token) == 1:
            c = key_token.upper()
            if ('A' <= c <= 'Z') or ('0' <= c <= '9'):
                vk = ord(c)

    return mods, vk

def parse_pynput_keys(hotkey_str: str):
    try:
        from pynput import keyboard
    except ImportError:
        return []
    tokens = [t.strip().lower() for t in hotkey_str.replace('+', ' ').split()]
    keys = []
    KEY_MAP = {
        'alt': keyboard.Key.alt,
        'menu': keyboard.Key.alt,
        'ctrl': keyboard.Key.ctrl,
        'control': keyboard.Key.ctrl,
        'shift': keyboard.Key.shift,
        'win': keyboard.Key.cmd,
        'windows': keyboard.Key.cmd,
        'meta': keyboard.Key.cmd,
        'super': keyboard.Key.cmd,
        'cmd': keyboard.Key.cmd,
        'space': keyboard.Key.space,
        'enter': keyboard.Key.enter,
        'return': keyboard.Key.enter,
        'tab': keyboard.Key.tab,
        'esc': keyboard.Key.esc,
        'escape': keyboard.Key.esc,
        'backspace': keyboard.Key.backspace,
        'delete': keyboard.Key.delete,
        'del': keyboard.Key.delete,
        'home': keyboard.Key.home,
        'end': keyboard.Key.end,
        'pageup': keyboard.Key.page_up,
        'pgup': keyboard.Key.page_up,
        'pagedown': keyboard.Key.page_down,
        'pgdown': keyboard.Key.page_down,
        'left': keyboard.Key.left,
        'right': keyboard.Key.right,
        'up': keyboard.Key.up,
        'down': keyboard.Key.down,
    }
    for i in range(1, 25):
        if hasattr(keyboard.Key, f'f{i}'):
            KEY_MAP[f'f{i}'] = getattr(keyboard.Key, f'f{i}')

    for t in tokens:
        if t in KEY_MAP:
            keys.append(KEY_MAP[t])
        elif len(t) == 1:
            keys.append(keyboard.KeyCode.from_char(t.lower()))
    return keys

class HotkeyNativeFilter(QAbstractNativeEventFilter):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType in ("windows_generic_MSG", "windows_dispatcher_MSG"):
                msg = ctypes.wintypes.MSG.from_address(message.__int__())
                if msg.message == 0x0312:  # WM_HOTKEY
                    if msg.wParam == self.manager.hotkey_id:
                        self.manager._trigger_hotkey()
                        return True, 0
        except Exception:
            pass
        return False, 0


class GlobalHotkeyManager(QObject):
    toggle_signal = Signal()

    def __init__(self, initial_hotkey: str = 'Alt+Space'):
        super().__init__()
        self.hotkey_str = (initial_hotkey or 'Alt+Space').strip()
        self.hotkey_id = 9999
        self.registered_hwnd = None
        self.pynput_listener = None
        self._active_hotkey = None
        self._receiver_widget = None
        self._last_trigger_time = 0.0
        self._native_filter = HotkeyNativeFilter(self)
        try:
            app_inst = QCoreApplication.instance()
            if app_inst:
                app_inst.installNativeEventFilter(self._native_filter)
        except Exception:
            pass
        self._init_receiver()
        self.update_hotkey(self.hotkey_str)

    def _is_hotkey_physically_pressed(self) -> bool:
        """Verifies using Win32 GetAsyncKeyState that the actual target keys are physically down,
        strictly preventing ghost triggers from Alt alone, Alt+Tab, Alt+F4, or missed key releases."""
        user32 = ctypes.windll.user32
        mods, vk = parse_hotkey(self.hotkey_str)

        # Tab check: If user is doing Alt+Tab (and Tab is NOT part of the shortcut), NEVER trigger!
        if vk != 0x09 and bool(user32.GetAsyncKeyState(0x09) & 0x8000):
            return False

        # Modifier-only shortcuts like Win+Alt
        if not vk and (mods & 0x0008) and (mods & 0x0001):
            is_alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
            is_win = bool((user32.GetAsyncKeyState(0x5B) | user32.GetAsyncKeyState(0x5C)) & 0x8000)
            return is_alt and is_win

        # Check required primary key
        if vk and not bool(user32.GetAsyncKeyState(vk) & 0x8000):
            return False

        # Check modifiers
        if (mods & 0x0001) and not bool(user32.GetAsyncKeyState(0x12) & 0x8000):  # Alt
            return False
        if (mods & 0x0002) and not bool(user32.GetAsyncKeyState(0x11) & 0x8000):  # Ctrl
            return False
        if (mods & 0x0004) and not bool(user32.GetAsyncKeyState(0x10) & 0x8000):  # Shift
            return False
        if (mods & 0x0008) and not bool((user32.GetAsyncKeyState(0x5B) | user32.GetAsyncKeyState(0x5C)) & 0x8000):  # Win
            return False

        return True

    def _trigger_hotkey(self):
        import time
        now = time.time()
        if now - self._last_trigger_time < 0.12:
            return
        # Avoid firing if user is actively in Alt+Tab
        try:
            if bool(ctypes.windll.user32.GetAsyncKeyState(0x09) & 0x8000):
                return
        except Exception:
            pass
        self._last_trigger_time = now
        self.toggle_signal.emit()

    def _init_receiver(self):
        manager = self
        class HotkeyReceiverWidget(QWidget):
            def __init__(self):
                super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
                self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            def nativeEvent(self, eventType, message):
                try:
                    msg = ctypes.wintypes.MSG.from_address(message.__int__())
                    if msg.message == 0x0312:  # WM_HOTKEY
                        if msg.wParam == manager.hotkey_id:
                            manager._trigger_hotkey()
                            return True, 0
                except Exception:
                    pass
                return super().nativeEvent(eventType, message)

        self._receiver_widget = HotkeyReceiverWidget()
        self.registered_hwnd = int(self._receiver_widget.winId())

    def update_hotkey(self, hotkey_str: str, settings: dict = None):
        self.unregister_hotkey()
        self.settings = settings or getattr(self, 'settings', {})
        self.hotkey_str = (hotkey_str or self.settings.get('hotkey', 'Win+Alt')).strip()
        mods, vk = parse_hotkey(self.hotkey_str)
        MOD_NOREPEAT = 0x4000
        user32 = ctypes.windll.user32

        # 1. Register Win32 OS-level HotKey on widget HWND and thread
        if vk:
            try:
                if self.registered_hwnd:
                    if not user32.RegisterHotKey(self.registered_hwnd, self.hotkey_id, mods | MOD_NOREPEAT, vk):
                        user32.RegisterHotKey(self.registered_hwnd, self.hotkey_id, mods, vk)
                user32.RegisterHotKey(0, self.hotkey_id, mods | MOD_NOREPEAT, vk)
            except Exception:
                pass

        # 2. Concurrently run low-level keyboard hook (pynput)
        # This guarantees 100% trigger reliability across all apps, games, and elevated windows
        try:
            from pynput import keyboard
            pyn_keys = parse_pynput_keys(self.hotkey_str)
            if pyn_keys:
                self.pynput_listener = keyboard.Listener(
                    on_press=self._pynput_on_press,
                    on_release=self._pynput_on_release
                )
                canonical_keys = [self.pynput_listener.canonical(k) for k in pyn_keys]
                self._active_hotkey = keyboard.HotKey(canonical_keys, self._trigger_hotkey)
                self.pynput_listener.daemon = True
                self.pynput_listener.start()
        except Exception as e:
            print(f"Error starting pynput listener: {e}")

        # Ensure low-level listener is active for ODD hold summon detection
        if self.pynput_listener is None:
            try:
                from pynput import keyboard
                self.pynput_listener = keyboard.Listener(
                    on_press=self._pynput_on_press,
                    on_release=self._pynput_on_release
                )
                self.pynput_listener.daemon = True
                self.pynput_listener.start()
            except Exception as e:
                print(f"Error starting fallback pynput listener: {e}")

    def _pynput_on_press(self, key):
        # Forward key press to Radial Summon Controller (Hold ALT / summon key)
        if getattr(self, 'radial_controller', None):
            try:
                k_name = getattr(key, 'name', None) or getattr(key, 'char', None) or str(key)
                self.radial_controller.on_global_key_down(k_name)
            except Exception:
                pass

        try:
            from pynput import keyboard
            user32 = ctypes.windll.user32

            # Direct hardware check for Win + Alt combination (zero reliance on state machine dictionary)
            is_win = bool((user32.GetAsyncKeyState(0x5B) | user32.GetAsyncKeyState(0x5C)) & 0x8000)
            is_alt = bool((user32.GetAsyncKeyState(0x12) | user32.GetAsyncKeyState(0xA4) | user32.GetAsyncKeyState(0xA5)) & 0x8000)
            is_ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
            is_shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
            is_tab = bool(user32.GetAsyncKeyState(0x09) & 0x8000)

            if is_win and is_alt and not is_ctrl and not is_shift and not is_tab:
                self._trigger_hotkey()
                return

            # Optional Windows Search replacement (Win+S)
            if getattr(self, "settings", {}).get("replace_windows_search", False):
                if key == keyboard.KeyCode.from_char('s') or key == keyboard.KeyCode.from_char('S'):
                    user32 = ctypes.windll.user32
                    is_win = bool((user32.GetAsyncKeyState(0x5B) | user32.GetAsyncKeyState(0x5C)) & 0x8000)
                    is_ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
                    is_alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
                    if is_win and not is_ctrl and not is_alt:
                        self._trigger_hotkey()
                        return
            # Reset state if user is pressing Tab (Alt+Tab task switcher)
            if key == keyboard.Key.tab and getattr(self, '_active_hotkey', None):
                self._active_hotkey._state.clear()
                return
        except Exception:
            pass

        if getattr(self, '_active_hotkey', None) and self.pynput_listener is not None:
            try:
                self._active_hotkey.press(self.pynput_listener.canonical(key))
            except Exception:
                pass

    def _pynput_on_release(self, key):
        # Forward key release to Radial Summon Controller
        if getattr(self, 'radial_controller', None):
            try:
                k_name = getattr(key, 'name', None) or getattr(key, 'char', None) or str(key)
                self.radial_controller.on_global_key_up(k_name)
            except Exception:
                pass

        if getattr(self, '_active_hotkey', None) and self.pynput_listener is not None:
            try:
                self._active_hotkey.release(self.pynput_listener.canonical(key))
            except Exception:
                pass

    def unregister_hotkey(self):
        if self.registered_hwnd:
            try:
                ctypes.windll.user32.UnregisterHotKey(self.registered_hwnd, self.hotkey_id)
            except Exception:
                pass
        try:
            ctypes.windll.user32.UnregisterHotKey(0, self.hotkey_id)
        except Exception:
            pass
        if self.pynput_listener is not None:
            try:
                self.pynput_listener.stop()
            except Exception:
                pass
            self.pynput_listener = None
        self._active_hotkey = None


def create_tray_icon(app, overlay, search_engine, on_open_settings, on_open_feedback, on_open_updates):
    tray = QSystemTrayIcon(get_app_icon(), app)
    tray.setToolTip("ODD — Living Desktop Search (by Humnspace)")

    menu = QMenu()

    act_toggle = QAction(f"Toggle ODD ({overlay.settings.get('hotkey', 'Alt+Space')})", menu)
    tray.act_toggle = act_toggle
    def update_hotkey_text(hk):
        act_toggle.setText(f"Toggle ODD ({hk})")
    tray.update_hotkey_text = update_hotkey_text
    def do_toggle():
        if overlay.is_open:
            overlay.sink()
        else:
            overlay.surface()
    act_toggle.triggered.connect(do_toggle)
    menu.addAction(act_toggle)

    act_reindex = QAction("Reindex Search Cache", menu)
    act_reindex.triggered.connect(search_engine.reindex_all)
    menu.addAction(act_reindex)

    menu.addSeparator()

    act_update = QAction("Check for Updates...", menu)
    act_update.triggered.connect(on_open_updates)
    menu.addAction(act_update)

    act_settings = QAction("ODD Settings...", menu)
    act_settings.triggered.connect(on_open_settings)
    menu.addAction(act_settings)

    act_feedback = QAction("Send Feedback (me.humnspace@gmail.com)...", menu)
    act_feedback.triggered.connect(on_open_feedback)
    menu.addAction(act_feedback)

    menu.addSeparator()

    act_quit = QAction("Quit ODD", menu)
    act_quit.triggered.connect(app.quit)
    menu.addAction(act_quit)

    tray.setContextMenu(menu)
    tray.act_update = act_update
    return tray

class AltF4EventFilter(QObject):
    """
    Application-wide event filter to intercept Alt+F4 and close requests.
    Prevents closing the app when Alt+F4 is pressed and hides the search capsule instead.
    """
    def __init__(self, overlay: OddOverlay, get_settings_dialog_fn):
        super().__init__()
        self.overlay = overlay
        self.get_settings_dialog = get_settings_dialog_fn

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_F4 and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
                settings_dlg = self.get_settings_dialog()
                if settings_dlg and settings_dlg.isVisible() and watched == settings_dlg:
                    settings_dlg.close()
                    return True
                if self.overlay.is_open:
                    self.overlay.sink()
                return True
        elif event.type() == QEvent.Type.Close:
            if watched == self.overlay:
                event.ignore()
                self.overlay.sink()
                return True
        return super().eventFilter(watched, event)

def cleanup_stale_mei_directories():
    """No-op: PyInstaller automatically manages its own temporary _MEIPASS extraction folders.
    Manual directory purging while installers or child processes are launching corrupts DLL loading."""
    pass

def main():
    cleanup_stale_mei_directories()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(get_app_icon())
    overlay = None

    # Single-instance enforcement: prevent duplicate processes/windows
    if not acquire_single_instance_mutex():
        print("ODD is already running in the background. Waking up active instance.")
        if notify_running_instance():
            sys.exit(0)
        # A previous build could leave a crashed, non-responsive process
        # holding the mutex. Recover that exact installed executable, then
        # take over instead of silently exiting without showing the UI.
        if recover_unresponsive_instance():
            time.sleep(0.25)
        if not acquire_single_instance_mutex():
            print("[STARTUP] ODD is already active, but its UI could not be reached.")
            sys.exit(1)

    # Listen before costly service initialization so a second launch can queue
    # a surface request even while the primary app is still starting up.
    QLocalServer.removeServer(IPC_SERVER_NAME)
    ipc_server = QLocalServer(app)
    def on_new_connection():
        client = ipc_server.nextPendingConnection()
        if client:
            def read_cmd():
                try:
                    cmd = bytes(client.readAll()).decode("utf-8").strip()
                    if cmd == "surface" and overlay is not None:
                        try:
                            client.write(b"ok\n")
                            client.flush()
                        except Exception:
                            pass
                        if not overlay.is_open and not overlay.is_animating:
                            overlay.surface(from_key=True)
                except Exception:
                    pass
            client.readyRead.connect(read_cmd)
            if client.bytesAvailable() > 0:
                read_cmd()
    ipc_server.newConnection.connect(on_new_connection)
    ipc_server.listen(IPC_SERVER_NAME)

    # The profiler wakes both the GUI and a worker thread every 4 ms. Keep it
    # available for diagnostics, but do not spend CPU on it in normal use.
    # Set ODD_PERF_WATCHDOG=1 when investigating event-loop stalls.
    if os.environ.get("ODD_PERF_WATCHDOG", "0").strip().lower() in ("1", "true", "yes"):
        try:
            import odd_profiler
            watchdog = odd_profiler.get_watchdog()
            watchdog.start()
            watchdog_timer = QTimer(app)
            watchdog_timer.setInterval(4)
            watchdog_timer.timeout.connect(watchdog.ping)
            watchdog_timer.start()
        except Exception as e:
            print(f"[PROFILER] Failed to init watchdog: {e}")

    settings = load_settings()
    
    # Ensure startup registration matches setting
    if settings.get("run_on_startup", True):
        set_startup_enabled(True)

    search_engine = WindowsSearchEngine(prefixes=settings.get("prefixes", {}))

    # Global Hotkey Manager (customizable & resilient Win32/pynput fallback)
    hotkey_manager = GlobalHotkeyManager(settings.get("hotkey", "Win+Alt"))
    hotkey_manager.settings = settings
    @safe_slot
    def on_hotkey_toggle():
        rc = getattr(hotkey_manager, "radial_controller", None)
        if rc is not None and settings.get("radial_menu_enabled", True):
            pos = QCursor.pos()
            if rc.search_panel.isVisible():
                rc.search_panel.dismiss(immediate=True)
            elif rc.radial_menu.isVisible():
                rc.radial_menu.dismiss(immediate=True)
            elif rc.qs_panel.isVisible():
                rc.qs_panel.dismiss(immediate=True)
            elif hasattr(rc, "phone_panel") and rc.phone_panel.isVisible():
                rc.phone_panel.dismiss(immediate=True)
            else:
                rc.radial_menu.open_at_cursor(pos)
            return

        if overlay is not None:
            if overlay.is_open:
                overlay.sink()
            else:
                overlay.surface(from_key=True)
    hotkey_manager.toggle_signal.connect(on_hotkey_toggle)

    settings_dialog = None
    trigger = None
    tray = None

    def get_settings_dialog():
        nonlocal settings_dialog
        return settings_dialog

    def apply_settings(new_s):
        nonlocal settings
        settings = new_s
        new_hk = settings.get("hotkey", "Win+Alt")
        if hotkey_manager is not None:
            try:
                hotkey_manager.update_hotkey(new_hk, settings=new_s)
            except Exception as e:
                print(f"Error updating hotkey: {e}")
        if tray is not None and hasattr(tray, 'update_hotkey_text'):
            tray.update_hotkey_text(new_hk)
        search_engine.set_prefixes(settings.get("prefixes", {}))
        if overlay is not None:
            overlay.update_settings(settings)
            if hasattr(overlay, 'radial_controller') and overlay.radial_controller:
                overlay.radial_controller.update_settings(settings)
        if trigger is not None:
            trigger.update_settings(settings)
        update_tray_visibility()

    def open_settings(origin: QRect = None, target_setting: str = None):
        nonlocal settings, settings_dialog
        # QAction.triggered can supply a boolean; only the overlay supplies a QRect.
        if not isinstance(origin, QRect):
            origin = None
        try:
            settings = load_settings()
            if settings_dialog is not None:
                try:
                    settings_dialog.close()
                    settings_dialog.deleteLater()
                except Exception:
                    pass
            settings_dialog = SettingsDialog(settings)
            settings_dialog.settings_changed.connect(apply_settings)
            settings_dialog.setWindowIcon(get_app_icon())
            if target_setting:
                matches = settings_dialog.search_settings_nlp(target_setting)
                if matches:
                    settings_dialog.navigate_to_setting(matches[0])
                else:
                    settings_dialog.nav_list.setCurrentRow(0)
            else:
                settings_dialog.nav_list.setCurrentRow(0)
            if origin is not None:
                # A never-shown dialog reports a placeholder geometry near the
                # desktop corner. Resolve the final center before starting the
                # circle-to-window morph.
                settings_dialog.adjustSize()
                target_size = settings_dialog.size()
                screen = QGuiApplication.screenAt(origin.center()) or QApplication.primaryScreen()
                available = screen.availableGeometry()
                target_rect = QRect(
                    QPoint(
                        available.center().x() - target_size.width() // 2,
                        available.center().y() - target_size.height() // 2,
                    ),
                    target_size,
                )
                settings_dialog.setWindowOpacity(0.0)
                settings_dialog.setGeometry(origin)
                settings_dialog.show()
                entry = QPropertyAnimation(settings_dialog, b"geometry", settings_dialog)
                entry.setDuration(175)
                entry.setEasingCurve(QEasingCurve.Type.OutCubic)
                entry.setStartValue(origin)
                entry.setEndValue(target_rect)
                fade = QPropertyAnimation(settings_dialog, b"windowOpacity", settings_dialog)
                fade.setDuration(145)
                fade.setEasingCurve(QEasingCurve.Type.OutCubic)
                fade.setStartValue(0.18)
                fade.setEndValue(1.0)
                entry_group = QParallelAnimationGroup(settings_dialog)
                entry_group.addAnimation(entry)
                entry_group.addAnimation(fade)
                settings_dialog._entry_animation = entry_group
                entry_group.start()
            else:
                settings_dialog.show()
            settings_dialog.raise_()
            settings_dialog.activateWindow()
            try:
                from odd_overlay import force_foreground_focus
                force_foreground_focus(settings_dialog.winId())
            except Exception:
                pass
        except Exception:
            import traceback, os
            try:
                err_path = os.path.join(os.environ.get("APPDATA", ""), "ODD", "error.log")
                os.makedirs(os.path.dirname(err_path), exist_ok=True)
                with open(err_path, "a") as f:
                    f.write(f"\n--- open_settings Error ---\n{traceback.format_exc()}\n")
            except Exception:
                pass

    def open_feedback():
        nonlocal settings, settings_dialog
        settings = load_settings()
        if settings_dialog is not None:
            try:
                settings_dialog.close()
                settings_dialog.deleteLater()
            except Exception:
                pass
        settings_dialog = SettingsDialog(settings)
        settings_dialog.settings_changed.connect(apply_settings)
        settings_dialog.setWindowIcon(get_app_icon())
        settings_dialog.show_feedback_tab()
        try:
            from odd_overlay import force_foreground_focus
            force_foreground_focus(settings_dialog.winId())
        except Exception:
            pass

    def open_updates():
        nonlocal settings, settings_dialog
        settings = load_settings()
        if settings_dialog is not None:
            try:
                settings_dialog.close()
                settings_dialog.deleteLater()
            except Exception:
                pass
        settings_dialog = SettingsDialog(settings)
        settings_dialog.settings_changed.connect(apply_settings)
        settings_dialog.setWindowIcon(get_app_icon())
        settings_dialog.show_updates_tab()
        try:
            from odd_overlay import force_foreground_focus
            force_foreground_focus(settings_dialog.winId())
        except Exception:
            pass

    overlay = OddOverlay(search_engine, settings, on_open_settings=open_settings)

    # Initialize ODD Radial Menu Controller (Hold ALT summon & cursor arc)
    try:
        from odd_radial_menu import RadialSummonController
        radial_controller = RadialSummonController(overlay, settings)
        overlay.radial_controller = radial_controller
        hotkey_manager.radial_controller = radial_controller
    except Exception as e:
        print(f"[RADIAL] Error initializing radial menu controller: {e}")

    trigger = EdgeTriggerWindow(overlay, settings)
    overlay.trigger_window = trigger
    trigger.show()
    QTimer.singleShot(80, overlay.prewarm_overlay_surface)

    # Subtle Windows Search reminder watcher (respects 4-hour cooldown, non-intrusive notch hint)
    _last_win_search_hint_time = [0.0]
    def _check_windows_search_active():
        try:
            if not settings.get("remind_windows_search_shortcut", True):
                return
            now = time.time()
            if now - _last_win_search_hint_time[0] < 14400.0:  # 4-hour cooldown
                return
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value.lower()
            if "search" in title or "cortana" in title:
                _last_win_search_hint_time[0] = now
                if trigger:
                    trigger.show_infomatic_alert("search_hint", "Tip: Win + Alt opens ODD Search", duration_sec=2.8)
        except Exception:
            pass

    win_search_hint_timer = QTimer(app)
    win_search_hint_timer.setInterval(1200)
    win_search_hint_timer.timeout.connect(_check_windows_search_active)
    win_search_hint_timer.start()

    # Wire fast direct clipboard copy alerts to Info-matic bar with strict deduplication
    _last_clip_data = [None, 0.0]
    def _on_app_clipboard_changed():
        try:
            now = time.time()
            if now - _last_clip_data[1] < 1.5:
                return
            cb = QApplication.clipboard()
            md = cb.mimeData()
            if md is None:
                return
            sig = None
            if md.hasUrls():
                urls = md.urls()
                if urls:
                    local_files = [u.toLocalFile() for u in urls if u.isLocalFile()]
                    if local_files:
                        sig = "::files::" + ";".join(local_files)
            if sig is None and md.hasText():
                txt = md.text().strip()
                if txt:
                    sig = txt

            if not sig or sig == _last_clip_data[0]:
                return

            _last_clip_data[0] = sig
            _last_clip_data[1] = now

            if odd_search and hasattr(odd_search, 'clipboard_mgr'):
                odd_search.clipboard_mgr.add_clip(sig if not sig.startswith("::files::") else f"[Files] {os.path.basename(sig)}", source="System")

            trigger.show_infomatic_alert("copied", "Copied", duration_sec=2.2)
        except Exception:
            pass

    try:
        QApplication.clipboard().dataChanged.connect(_on_app_clipboard_changed)
    except Exception:
        pass

    # System tray
    tray = create_tray_icon(app, overlay, search_engine, on_open_settings=open_settings, on_open_feedback=open_feedback, on_open_updates=open_updates)

    # Update Manager notifications & listeners
    upd_mgr = UpdateManager.get_instance()
    def on_update_discovered(rel: ReleaseInfo):
        # Strict validation: Only notify if an update is really available and newer than current version
        if not rel or not getattr(rel, 'is_newer', False):
            return

        if tray and hasattr(tray, 'act_update') and tray.act_update:
            tray.act_update.setText(f"Update Available ({rel.version_display})...")
            tray.setToolTip(f"ODD — Update {rel.version_display} Available")

        # 1. Bezel HUD notification on notch / island
        bezel = getattr(trigger, 'bezel_hud', None) or getattr(overlay, 'bezel_hud', None) or (getattr(overlay, 'trigger_window', None) and getattr(overlay.trigger_window, 'bezel_hud', None))
        if bezel:
            bezel.show_notification_hud(
                f"Update Available: {rel.version_display}",
                "A new version of ODD is available to install",
                duration_ms=5000
            )

        # 2. Windows System Tray notification balloon
        try:
            if tray and tray.isVisible():
                tray.showMessage(
                    "ODD Update Available",
                    f"Version {rel.version_display} is now available.\nClick to review and update.",
                    QSystemTrayIcon.MessageIcon.Information,
                    5000
                )
                try:
                    tray.messageClicked.disconnect()
                except Exception:
                    pass
                tray.messageClicked.connect(lambda: upd_mgr.ask_update_confirmation(rel))
        except Exception:
            pass

    def on_update_downloaded(setup_path: str, rel: ReleaseInfo):
        if tray and hasattr(tray, 'act_update') and tray.act_update:
            tray.act_update.setText(f"Restart & Install Update ({rel.version_display})")
            tray.setToolTip(f"ODD — Update {rel.version_display} Ready to Install")
            try:
                tray.act_update.triggered.disconnect()
            except Exception:
                pass
            tray.act_update.triggered.connect(lambda: upd_mgr.apply_update_and_restart(setup_path))

        bezel = getattr(trigger, 'bezel_hud', None) or getattr(overlay, 'bezel_hud', None) or (getattr(overlay, 'trigger_window', None) and getattr(overlay.trigger_window, 'bezel_hud', None))
        if bezel:
            bezel.show_notification_hud(
                f"Update Ready: ODD {rel.version_display}",
                "Downloaded silently • Click or press to restart & update",
                duration_ms=6000
            )
        try:
            if tray and tray.isVisible():
                tray.showMessage(
                    "ODD Auto-Update Ready",
                    f"ODD {rel.version_display} is downloaded and ready.\nClick here or tray menu to restart and apply.",
                    QSystemTrayIcon.MessageIcon.Information,
                    5500
                )
                try:
                    tray.messageClicked.disconnect()
                except Exception:
                    pass
                tray.messageClicked.connect(lambda: upd_mgr.apply_update_and_restart(setup_path))
        except Exception:
            pass

    upd_mgr.update_available.connect(on_update_discovered)
    upd_mgr.download_finished.connect(on_update_downloaded)

    # Install Global Event Filter to intercept Alt+F4
    alt_f4_filter = AltF4EventFilter(overlay, get_settings_dialog)
    app.installEventFilter(alt_f4_filter)

    def update_tray_visibility():
        integrate_rook = settings.get("integrate_with_rook_tray", True)
        rook_active = is_rook_running() or is_rook_installed()
        if integrate_rook and rook_active:
            tray.hide()
        else:
            tray.show()

    update_tray_visibility()

    # Periodic background check for Rook ecosystem status (e.g. if Rook launches or quits)
    rook_sync_timer = QTimer()
    rook_sync_timer.timeout.connect(update_tray_visibility)
    rook_sync_timer.start(10000)

    # Do not auto-surface the heavy search overlay on normal startup (avoids intrusive popup)
    # The living edge trigger / Dynamic Island is already active and ready at the top edge.
    surface_on_startup = bool(settings.get("surface_on_startup", False))
    if "--surface" in sys.argv or surface_on_startup:
        QTimer.singleShot(150, lambda: overlay.surface(from_key=True))
    elif "--startup" not in sys.argv and "--silent" not in sys.argv and "--minimized" not in sys.argv:
        # Subtle non-intrusive readiness pulse in Dynamic Island notch
        if trigger is not None:
            QTimer.singleShot(350, lambda: trigger.show_infomatic_alert("ready", "ODD Ready • Press Win+Alt to search", duration_sec=2.2))

    print(f"ODD by Humnspace is running at the {settings.get('edge', 'top')} edge.")
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
