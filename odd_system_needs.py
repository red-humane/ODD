"""
ODD System & User Needs Intelligence Engine
===========================================
Intelligently observes system hardware states, power transitions, user activity,
fullscreen/gaming focus, and idle presence to dynamically adapt ODD's behaviors:

1. Automatic Charger Connection & Disconnection Identification:
   - Detects AC plug/unplug events in real time.
   - Automatically completes/resolves active or pending battery reminders without requiring manual dismissal.
   - Real-time charge rate velocity (%/min), Time-to-80% / Time-to-100% calculation.
   - Dynamic battery discharge velocity (%/hr) and remaining runtime estimation.
2. User Presence & Ergonomic Needs:
   - Tracks keyboard/mouse idle time via GetLastInputInfo.
   - Automatically pauses intrusive wellness reminders (water, posture, eye rest) when user is away from desk.
   - Resumes cleanly when the user returns.
3. Focus & Fullscreen Need Detection:
   - Detects when the user is in full-screen games, presentations, or video players.
   - Automatically defers non-critical popups to protect deep user immersion.
4. Thermal & Battery Conservation Needs:
   - Detects high resource load (RAM/CPU) during battery operation and suggests smart conservation.
"""

import time
import math
import ctypes
import ctypes.wintypes
from typing import Optional, Dict, Any, List, Tuple
from PySide6.QtCore import QObject, Signal, QTimer


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.wintypes.UINT),
        ('dwTime', ctypes.wintypes.DWORD)
    ]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ('dwLength', ctypes.wintypes.DWORD),
        ('dwMemoryLoad', ctypes.wintypes.DWORD),
        ('ullTotalPhys', ctypes.c_uint64),
        ('ullAvailPhys', ctypes.c_uint64),
        ('ullTotalPageFile', ctypes.c_uint64),
        ('ullAvailPageFile', ctypes.c_uint64),
        ('ullTotalVirtual', ctypes.c_uint64),
        ('ullAvailVirtual', ctypes.c_uint64),
        ('ullAvailExtendedVirtual', ctypes.c_uint64),
    ]


class SystemNeedsIntelligence(QObject):
    """
    Singleton intelligence engine that evaluates system status and user context,
    automatically orchestrating reminders, battery workflows, and notification delivery.
    """
    power_state_updated = Signal(dict)
    charger_plugged = Signal(dict)
    charger_unplugged = Signal(dict)
    battery_reminder_auto_resolved = Signal(dict)
    user_presence_changed = Signal(bool)       # True if idle (away), False if active
    user_focus_mode_changed = Signal(bool)     # True if in fullscreen/presentation
    system_resource_alert = Signal(dict)

    _instance = None

    @classmethod
    def get_instance(cls, settings: Optional[dict] = None):
        if cls._instance is None:
            cls._instance = SystemNeedsIntelligence(settings or {})
        elif settings:
            cls._instance.settings = settings
        return cls._instance

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings

        # Power tracking state
        self._last_power: Dict[str, Any] = {}
        self._power_history: List[Tuple[float, int, bool]] = []  # [(timestamp, percent, plugged_in)]
        self._charge_velocity: float = 0.65     # % per minute default (~1.5h full charge)
        self._discharge_velocity: float = 16.0  # % per hour default (~6h runtime)
        self._last_plug_state: Optional[bool] = None

        # User Presence / Idle tracking
        self.is_user_idle = False
        self._last_input_time = time.time()
        self._idle_threshold_sec = 240.0  # 4 minutes away

        # Fullscreen / Focus tracking
        self.is_in_fullscreen = False
        self._deferred_notifications: List[dict] = []

        # System Resource tracking
        self._high_mem_samples = 0
        self._last_resource_check = 0.0

        # Background polling timer (runs every 1.5 seconds with negligible CPU overhead)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1500)
        self._poll_timer.timeout.connect(self._poll_context)
        self._poll_timer.start()

    # =========================================================================
    # 1. BATTERY & CHARGING INTELLIGENCE
    # =========================================================================

    def on_power_changed(self, power_dict: dict) -> Dict[str, Any]:
        """
        Receives real-time power updates from DynamicIslandMonitor.
        Identifies plug/unplug events, automatically completes matching reminders,
        and computes charging velocity & runtime estimates.
        """
        now = time.time()
        plugged_in = bool(power_dict.get("plugged_in", False))
        is_charging = bool(power_dict.get("is_charging", False))
        pct = int(power_dict.get("percent", 50))
        has_battery = bool(power_dict.get("has_battery", True))

        # Record sample for rate projection
        self._power_history.append((now, pct, plugged_in))
        # Keep last 30 minutes of telemetry
        cutoff = now - 1800.0
        self._power_history = [s for s in self._power_history if s[0] >= cutoff]

        # Calculate charging or discharging velocity
        charge_eta_str = ""
        runtime_est_str = ""

        if plugged_in:
            # Calculate charge velocity
            plugged_samples = [s for s in self._power_history if s[2]]
            if len(plugged_samples) >= 2:
                dt_min = (plugged_samples[-1][0] - plugged_samples[0][0]) / 60.0
                dpct = plugged_samples[-1][1] - plugged_samples[0][1]
                if dt_min >= 0.5 and dpct > 0:
                    self._charge_velocity = max(0.1, dpct / dt_min)
            if self._charge_velocity <= 0.01:
                self._charge_velocity = 0.65  # Typical laptop 1.5h full charge default

            high_limit = int(self.settings.get("battery_high_limit", 80))
            if pct < high_limit:
                rem_pct = high_limit - pct
                min_to_target = max(1, int(rem_pct / self._charge_velocity))
                charge_eta_str = f"~{min_to_target}m to {high_limit}%"
            elif pct < 100:
                rem_pct = 100 - pct
                min_to_target = max(1, int(rem_pct / self._charge_velocity))
                charge_eta_str = f"~{min_to_target}m to 100%"
            else:
                charge_eta_str = "Fully Charged"
        else:
            # Calculate discharge velocity
            unplugged_samples = [s for s in self._power_history if not s[2]]
            if len(unplugged_samples) >= 2:
                dt_hr = (unplugged_samples[-1][0] - unplugged_samples[0][0]) / 3600.0
                dpct = unplugged_samples[0][1] - unplugged_samples[-1][1]
                if dt_hr >= 0.02 and dpct > 0:
                    self._discharge_velocity = max(2.0, dpct / dt_hr)
            if self._discharge_velocity <= 0.01:
                self._discharge_velocity = 16.0  # Typical 6h laptop runtime default

            hrs_left = pct / self._discharge_velocity
            h = int(hrs_left)
            m = int((hrs_left - h) * 60)
            if h > 0:
                runtime_est_str = f"~{h}h {m}m left"
            else:
                runtime_est_str = f"~{m}m left"

        # Detect transition: PLUGGED IN
        if self._last_plug_state is not None and plugged_in and not self._last_plug_state:
            event_data = {
                "percent": pct,
                "eta": charge_eta_str,
                "velocity": self._charge_velocity,
                "timestamp": now,
            }
            self.charger_plugged.emit(event_data)
            self._handle_auto_resolution_on_plug(pct)

        # Detect transition: UNPLUGGED
        elif self._last_plug_state is not None and not plugged_in and self._last_plug_state:
            event_data = {
                "percent": pct,
                "runtime_estimate": runtime_est_str,
                "velocity": self._discharge_velocity,
                "timestamp": now,
            }
            self.charger_unplugged.emit(event_data)
            self._handle_auto_resolution_on_unplug(pct)

        self._last_plug_state = plugged_in

        summary = {
            "has_battery": has_battery,
            "plugged_in": plugged_in,
            "is_charging": is_charging,
            "percent": pct,
            "charge_eta": charge_eta_str,
            "runtime_estimate": runtime_est_str,
            "charge_velocity": self._charge_velocity,
            "discharge_velocity": self._discharge_velocity,
        }
        self._last_power = summary
        self.power_state_updated.emit(summary)
        return summary

    def _handle_auto_resolution_on_plug(self, pct: int):
        """
        When the charger is plugged in, automatically identify that the power need
        has been satisfied and resolve any active or pending battery reminders.
        """
        # 1. Clear Wellness Manager battery plug_in alert state
        try:
            from odd_wellness import WellnessManager
            wm = WellnessManager.get_instance()
            if hasattr(wm, "on_power_state_changed"):
                wm.on_power_state_changed(plugged_in=True, percent=pct)
            else:
                if getattr(wm, "_last_battery_alert_type", None) == "plug_in":
                    wm._last_battery_alert_type = None
        except Exception:
            pass

        # 2. Automatically complete matching NLP reminders in ReminderManager
        try:
            from odd_reminder import ReminderManager
            rm = ReminderManager.get_instance()
            if hasattr(rm, "on_power_state_changed"):
                rm.on_power_state_changed(plugged_in=True)
            else:
                for rem in list(rm._reminders.values()):
                    if rem.status in ("pending", "triggered", "snoozed"):
                        t_lower = rem.title.lower()
                        if any(kw in t_lower for kw in ("charge", "plug in", "plug-in", "connect charger", "charger")) and "unplug" not in t_lower:
                            rm.complete_reminder(rem.id)
                            self.battery_reminder_auto_resolved.emit({
                                "action": "plugged_in",
                                "title": rem.title,
                                "percent": pct
                            })
        except Exception:
            pass

    def _handle_auto_resolution_on_unplug(self, pct: int):
        """
        When the charger is unplugged, automatically resolve 80% / health limit
        unplug reminders.
        """
        # 1. Clear Wellness Manager battery unplug alert state
        try:
            from odd_wellness import WellnessManager
            wm = WellnessManager.get_instance()
            if hasattr(wm, "on_power_state_changed"):
                wm.on_power_state_changed(plugged_in=False, percent=pct)
            else:
                if getattr(wm, "_last_battery_alert_type", None) == "unplug":
                    wm._last_battery_alert_type = None
        except Exception:
            pass

        # 2. Automatically complete matching NLP reminders in ReminderManager
        try:
            from odd_reminder import ReminderManager
            rm = ReminderManager.get_instance()
            if hasattr(rm, "on_power_state_changed"):
                rm.on_power_state_changed(plugged_in=False)
            else:
                for rem in list(rm._reminders.values()):
                    if rem.status in ("pending", "triggered", "snoozed"):
                        t_lower = rem.title.lower()
                        if any(kw in t_lower for kw in ("unplug", "disconnect charger", "stop charging", "unplug charger")):
                            rm.complete_reminder(rem.id)
                            self.battery_reminder_auto_resolved.emit({
                                "action": "unplugged",
                                "title": rem.title,
                                "percent": pct
                            })
        except Exception:
            pass

    # =========================================================================
    # 2. USER PRESENCE & IDLE TRACKING
    # =========================================================================

    def get_idle_seconds(self) -> float:
        """Returns time in seconds since the last physical mouse or keyboard input."""
        try:
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                tick = ctypes.windll.kernel32.GetTickCount()
                elapsed_ms = max(0, tick - lii.dwTime)
                return elapsed_ms / 1000.0
        except Exception:
            pass
        return 0.0

    def _check_presence(self):
        """Checks if user is idle/away or actively using the machine."""
        idle_sec = self.get_idle_seconds()
        was_idle = self.is_user_idle

        if idle_sec >= self._idle_threshold_sec:
            self.is_user_idle = True
            if not was_idle:
                self.user_presence_changed.emit(True)
                # Inform WellnessManager to pause timers so reminders don't accumulate
                try:
                    from odd_wellness import WellnessManager
                    wm = WellnessManager.get_instance()
                    if hasattr(wm, "set_user_idle"):
                        wm.set_user_idle(True)
                except Exception:
                    pass
        else:
            self.is_user_idle = False
            if was_idle:
                self.user_presence_changed.emit(False)
                # User returned! Resume timers cleanly
                try:
                    from odd_wellness import WellnessManager
                    wm = WellnessManager.get_instance()
                    if hasattr(wm, "set_user_idle"):
                        wm.set_user_idle(False)
                except Exception:
                    pass

    # =========================================================================
    # 3. FULLSCREEN / DEEP FOCUS TRACKING
    # =========================================================================

    def check_fullscreen(self) -> bool:
        """
        Determines whether the currently active window is in true full-screen mode
        (e.g. video player, presentation, or full-screen game).
        """
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False

            # Ignore shell / taskbar / desktop
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            cname = class_buf.value
            if cname in ("Shell_TrayWnd", "Progman", "WorkerW", "EdgeTriggerWindow", "OddBezelHUD"):
                return False

            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

            # Compare with screen bounds
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)

            w = rect.right - rect.left
            h = rect.bottom - rect.top

            # Matches or exceeds screen bounds
            if rect.left <= 0 and rect.top <= 0 and w >= screen_w and h >= screen_h:
                return True
        except Exception:
            pass
        return False

    def should_suppress_notification(self, is_high_priority: bool = False) -> bool:
        """Determines if a notification should be held back during immersion."""
        if is_high_priority:
            return False
        if bool(self.settings.get("dnd_enabled", False)):
            return True
        if bool(self.settings.get("smart_game_focus_mode", True)) and self.is_in_fullscreen:
            return True
        return False

    def queue_deferred_notification(self, notif_data: dict):
        """Holds a non-urgent notification until the user exits full-screen focus."""
        if len(self._deferred_notifications) < 10:
            self._deferred_notifications.append(notif_data)

    def pop_deferred_notifications(self) -> List[dict]:
        """Returns and flushes all deferred notifications upon exiting full-screen."""
        items = list(self._deferred_notifications)
        self._deferred_notifications.clear()
        return items

    # =========================================================================
    # 4. SYSTEM RESOURCE MONITORING (THERMAL & HIGH DRAIN)
    # =========================================================================

    def _check_system_resources(self, now: float):
        """
        Checks RAM and system pressure. If user is running on battery and high memory/CPU
        drain is sustained, warns gently or offers optimization.
        """
        if (now - self._last_resource_check) < 15.0:
            return
        self._last_resource_check = now

        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                mem_load = int(stat.dwMemoryLoad)
                plugged = bool(self._last_power.get("plugged_in", True))

                # If running on battery and memory is extremely high (>92%)
                if not plugged and mem_load >= 92:
                    self._high_mem_samples += 1
                    if self._high_mem_samples == 3:  # 45 seconds of heavy strain
                        self.system_resource_alert.emit({
                            "type": "high_battery_drain",
                            "title": "High Memory Drain",
                            "note": f"RAM usage is at {mem_load}%. Connecting your charger helps prevent throttling.",
                            "mem_load": mem_load
                        })
                else:
                    self._high_mem_samples = 0
        except Exception:
            pass

    # =========================================================================
    # 5. UNIFIED CONTEXT POLLING
    # =========================================================================

    def _poll_context(self):
        """Unified background tick evaluating presence, focus, and resource needs."""
        now = time.time()
        self._check_presence()

        # Check fullscreen focus transitions
        is_fs = self.check_fullscreen()
        if is_fs != self.is_in_fullscreen:
            self.is_in_fullscreen = is_fs
            self.user_focus_mode_changed.emit(is_fs)

        self._check_system_resources(now)
