"""
ODD Crash Forensics & Telemetry System
Provides bulletproof crash capture, faulthandler native crash logging,
Qt message interceptor, exception hooks, thread safety, and breadcrumb auditing.
"""

import sys
import os
import faulthandler
import threading
import traceback
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
import time
import functools
from pathlib import Path
from typing import Callable, Any, Optional

# Determine log directory: %LOCALAPPDATA%\ODD\logs\
_local_appdata = os.environ.get("LOCALAPPDATA")
if not _local_appdata:
    _local_appdata = os.path.expanduser(r"~\AppData\Local")
LOG_DIR = Path(_local_appdata) / "ODD" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

NATIVE_CRASH_LOG = LOG_DIR / "crash_native.log"
PYTHON_CRASH_LOG = LOG_DIR / "crash_python.log"
APP_LOG = LOG_DIR / "odd.log"
BREADCRUMB_LOG = LOG_DIR / "breadcrumbs.log"

# Circular buffer for high-speed in-memory breadcrumbs (last 100 actions)
_breadcrumbs = deque(maxlen=100)
_breadcrumb_lock = threading.Lock()
_native_crash_file = None

# Logger setup
logger = logging.getLogger("ODD")
logger.setLevel(logging.INFO)
logger.propagate = False

# Rotating file handler for app log (max 3 MB, keep 3 backups)
try:
    _rfh = RotatingFileHandler(
        str(APP_LOG),
        maxBytes=3 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
        delay=True
    )
    _rfh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(threadName)s] %(message)s"))
    logger.addHandler(_rfh)
except Exception:
    pass


def log_breadcrumb(action: str, category: str = "action", details: str = ""):
    """
    Records a high-fidelity breadcrumb before major actions so the last log line
    before an unhandled crash precisely identifies the trigger.
    """
    ts = time.strftime("%H:%M:%S") + f".{int((time.time() % 1) * 1000):03d}"
    thread_name = threading.current_thread().name
    entry = f"[{ts}] [{thread_name}] [{category.upper()}] {action}"
    if details:
        entry += f" | {details}"

    with _breadcrumb_lock:
        _breadcrumbs.append(entry)

    # Append to breadcrumb log
    try:
        with open(BREADCRUMB_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def get_recent_breadcrumbs(count: int = 25) -> list[str]:
    """Returns the most recent breadcrumbs for crash reporting."""
    with _breadcrumb_lock:
        return list(_breadcrumbs)[-count:]


def dump_crash_report(exctype, value, tb, source: str = "PYTHON_EXCEPTION"):
    """Dumps full traceback and recent breadcrumbs to crash_python.log."""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        breadcrumbs = get_recent_breadcrumbs(30)
        report_lines = [
            "\n" + "=" * 80,
            f"ODD FATAL CRASH REPORT - {ts}",
            f"Source: {source}",
            f"Thread: {threading.current_thread().name} (id={threading.get_ident()})",
            f"Python: {sys.version}",
            "=" * 80,
            "\n--- RECENT BREADCRUMBS (LAST 30 ACTIONS) ---",
        ]
        report_lines.extend(breadcrumbs)
        report_lines.append("\n--- FULL TRACEBACK ---")
        report_lines.extend(traceback.format_exception(exctype, value, tb))
        report_lines.append("=" * 80 + "\n")

        crash_text = "\n".join(report_lines)

        with open(PYTHON_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(crash_text)

        logger.critical(crash_text)
        sys.stderr.write(crash_text)
    except Exception as e:
        try:
            sys.stderr.write(f"Failed to write crash report: {e}\n")
        except Exception:
            pass


def global_excepthook(exctype, value, tb):
    """Global sys.excepthook that records full diagnostics."""
    dump_crash_report(exctype, value, tb, source="sys.excepthook")
    # Call original excepthook if present
    try:
        if sys.__excepthook__ and sys.__excepthook__ is not global_excepthook:
            sys.__excepthook__(exctype, value, tb)
    except Exception:
        pass


def global_thread_excepthook(args):
    """Global threading.excepthook for unhandled exceptions in background worker threads."""
    dump_crash_report(args.exc_type, args.exc_value, args.exc_traceback, source=f"threading.excepthook [{args.thread.name}]")


def qt_message_handler(mode, context, message):
    """
    Intercepts and logs Qt runtime warnings, errors, and thread-crossing violations:
    - "QObject: Cannot create children for a parent in a different thread"
    - "QBasicTimer::start: Timers cannot be started from another thread"
    - "QPainter not active"
    - "Cannot queue arguments of type ..."
    """
    from PySide6.QtCore import QtMsgType

    type_name = "DEBUG"
    if mode == QtMsgType.QtWarningMsg:
        type_name = "WARNING"
    elif mode == QtMsgType.QtCriticalMsg:
        type_name = "CRITICAL"
    elif mode == QtMsgType.QtFatalMsg:
        type_name = "FATAL"
    elif mode == QtMsgType.QtInfoMsg:
        type_name = "INFO"

    file_info = f" ({context.file}:{context.line})" if context.file else ""
    log_line = f"[Qt {type_name}]{file_info} {message}"

    log_breadcrumb(message, category=f"qt_{type_name.lower()}")
    if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        logger.warning(log_line)
    else:
        logger.debug(log_line)


def safe_slot(func: Callable) -> Callable:
    """
    Essential decorator for PyQt6/PySide6 slots, callbacks, QTimer handlers, and event overrides.
    PySide6 immediately aborts (std::terminate) the whole process when an unhandled Python exception
    escapes a slot. @safe_slot intercepts the exception, logs full diagnostics, and prevents
    the process from crashing.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            fn_name = getattr(func, "__qualname__", getattr(func, "__name__", str(func)))
            logger.error(f"[SAFE_SLOT CAUGHT] Exception in {fn_name}: {e}\n{tb}")
            log_breadcrumb(f"Exception in {fn_name}: {e}", category="slot_error")
            return None
    return wrapper


def install_crash_capture():
    """
    Initializes faulthandler, exception hooks, and Qt message logging.
    Must be called at the very earliest entry point in main.py.
    """
    global _native_crash_file

    # 1. Native crash capture (catches C-level segfaults / access violations)
    try:
        # Rotate native crash log if it exceeds 2MB
        if NATIVE_CRASH_LOG.exists() and NATIVE_CRASH_LOG.stat().st_size > 2 * 1024 * 1024:
            try:
                bak = NATIVE_CRASH_LOG.with_suffix(".log.old")
                if bak.exists():
                    bak.unlink()
                NATIVE_CRASH_LOG.rename(bak)
            except Exception:
                pass

        _native_crash_file = open(str(NATIVE_CRASH_LOG), "a+", buffering=1, encoding="utf-8")
        _native_crash_file.write(f"\n=== ODD FAULTHANDLER INITIALIZED: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        _native_crash_file.flush()
        faulthandler.enable(file=_native_crash_file, all_threads=True)
    except Exception as e:
        sys.stderr.write(f"Faulthandler init failed: {e}\n")

    # 2. Python exception hooks
    sys.excepthook = global_excepthook
    threading.excepthook = global_thread_excepthook

    # 3. Qt runtime message handler
    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(qt_message_handler)
    except Exception as e:
        sys.stderr.write(f"Qt message handler installation failed: {e}\n")

    log_breadcrumb("Crash capture initialized", category="startup")
    logger.info("ODD Crash Forensics initialized successfully.")


class StallWatchdog:
    """
    Lightweight GUI stall watchdog.
    Pings the Qt event loop; if the GUI thread is blocked for > threshold_ms
    (default: 24ms), captures the GUI thread's current stack frame and logs the
    offending function. Can be enabled via ODD_STALL_WATCHDOG=1 or setting.
    """
    _instance = None

    def __init__(self, threshold_ms: float = 24.0, check_interval_ms: float = 12.0):
        self.threshold = threshold_ms / 1000.0
        self.interval = check_interval_ms / 1000.0
        self.main_thread_id = threading.main_thread().ident
        self._last_heartbeat = time.perf_counter()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._timer = None
        self._enabled = os.environ.get("ODD_STALL_WATCHDOG", "0").lower() in ("1", "true")

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = StallWatchdog()
        return cls._instance

    def start(self):
        if not self._enabled or self._running:
            return
        self._running = True
        self._last_heartbeat = time.perf_counter()

        try:
            from PySide6.QtCore import QTimer
            self._timer = QTimer()
            self._timer.setInterval(max(4, int(self.interval * 1000)))
            self._timer.timeout.connect(self._on_heartbeat)
            self._timer.start()

            self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="StallWatchdog")
            self._thread.start()
            logger.info(f"StallWatchdog active (threshold={self.threshold*1000:.0f}ms)")
        except Exception as e:
            logger.warning(f"Could not start StallWatchdog: {e}")

    def _on_heartbeat(self):
        self._last_heartbeat = time.perf_counter()

    def _monitor_loop(self):
        last_logged = 0.0
        while self._running:
            time.sleep(self.interval)
            now = time.perf_counter()
            elapsed = now - self._last_heartbeat
            if elapsed > self.threshold:
                if now - last_logged > 1.0:
                    last_logged = now
                    frame = sys._current_frames().get(self.main_thread_id)
                    if frame:
                        stack = "".join(traceback.format_stack(frame))
                        logger.warning(f"[GUI THREAD STALL] Blocked for {elapsed*1000:.1f}ms:\n{stack}")
                        log_breadcrumb(f"GUI stall {elapsed*1000:.1f}ms", category="stall_watchdog")

    def stop(self):
        self._running = False
        if self._timer:
            try:
                self._timer.stop()
            except Exception:
                pass
