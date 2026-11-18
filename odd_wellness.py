"""
ODD Wellness & Ergonomic Reminders Engine
Provides intelligent, scheduled ergonomic health and maintenance prompts:
1. Eye Rest (The 20-20-20 Rule): Every 20 mins, look 20 feet away for 20 seconds.
2. Posture & Desk Stretch: Every 60 mins, roll shoulders and reset posture.
3. Ventilation / Air Freshness: Every 2 to 3 hours, crack open window / step outside.
4. Battery Health & Charger Alerts: Unplug at 80%, plug in at 30% to extend Li-ion lifespan.
5. Storage Purge & Clean: Every 2 weeks, empty Recycle Bin and review Downloads.
"""

import os
import sys
import time
import json
import ctypes
import shutil
import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from PySide6.QtCore import QObject, Signal, QTimer


class WellnessManager(QObject):
    """
    Central manager for ergonomic wellness, battery health, and storage hygiene.
    Schedules non-intrusive alerts through ODD's Dynamic Island.
    """
    _instance: Optional['WellnessManager'] = None

    # Signals for Dynamic Island / Overlay presentation
    wellness_triggered = Signal(dict)
    storage_cleaned = Signal(dict)
    battery_resolved = Signal(dict)

    @classmethod
    def get_instance(cls, settings: dict = None) -> 'WellnessManager':
        if cls._instance is None:
            cls._instance = cls(settings or {})
        elif settings:
            cls._instance.update_settings(settings)
        return cls._instance

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings or {}

        # Next due timestamps (epoch seconds) - spaced out and calm
        now = time.time()
        self._last_any_wellness_time = now - 900.0  # Allow initial grace period
        self._next_eye_due = now + self._get_interval_sec("eye_rest_interval_min", 60)
        self._active_eye_work_seconds = 0.0
        self._next_posture_due = now + self._get_interval_sec("posture_interval_min", 90)
        self._next_vent_due = now + self._get_interval_sec("ventilation_interval_min", 180)

        # Battery tracking state
        self._last_battery_alert_type = None  # "unplug" or "plug_in"
        self._last_battery_alert_time = 0.0
        self._is_idle = False

        # Storage purge state tracking
        self._state_file = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\wellness_state.json"))
        self._last_storage_check_time = 0.0
        self._load_state()

        # Polling timer (runs every 15 seconds)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(15000)
        self.poll_timer.timeout.connect(self._check_wellness_events)
        self.poll_timer.start()

    def update_settings(self, new_settings: dict):
        self.settings = new_settings

    @staticmethod
    def get_idle_seconds() -> float:
        """Returns seconds since last user keyboard or mouse input on Windows."""
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
                return max(0.0, millis / 1000.0)
        except Exception:
            pass
        return 0.0

    def _get_interval_sec(self, key: str, default_min: int) -> float:
        val = int(self.settings.get(key, default_min))
        if val <= 0:
            val = default_min
        return val * 60.0

    def is_within_working_hours(self) -> bool:
        """Checks if current time falls within configured working hours if enabled."""
        if not self.settings.get("water_working_hours_only", True):
            return True
        now = datetime.datetime.now().time()
        start_str = str(self.settings.get("water_start_time", "09:00")).strip()
        end_str = str(self.settings.get("water_end_time", "17:00")).strip()
        try:
            sp = [int(p) for p in start_str.split(":")]
            ep = [int(p) for p in end_str.split(":")]
            t_start = datetime.time(sp[0], sp[1])
            t_end = datetime.time(ep[0], ep[1])
            if t_start <= t_end:
                return t_start <= now <= t_end
            return now >= t_start or now <= t_end
        except Exception:
            return datetime.time(9, 0) <= now <= datetime.time(17, 0)

    def set_user_idle(self, is_idle: bool):
        """Called by SystemNeedsIntelligence when user is away from keyboard."""
        self._is_idle = bool(is_idle)

    def _check_wellness_events(self):
        now = time.time()

        # Only prompt wellness desk reminders during active working hours
        if not self.is_within_working_hours():
            return

        # 4. Battery Health & Charger Check (every 15s)
        if bool(self.settings.get("enable_battery_health_alert", True)):
            self._check_battery_health(now)

        # 5. Storage Purge (checked once per hour)
        if bool(self.settings.get("enable_storage_purge_reminder", True)):
            if now - self._last_storage_check_time >= 3600.0:
                self._last_storage_check_time = now
                self._check_storage_purge(now)

        # If user is away from desk (idle), suppress ergonomic fatigue reminders until they return
        if self._is_idle:
            return

        # 1. Eye Rest (Every 1 hr - user configured interval)
        if bool(self.settings.get("enable_eye_rest_reminder", True)):
            mode = str(self.settings.get("eye_rest_reminder_mode", "work")).lower()
            interval_sec = self._get_interval_sec("eye_rest_interval_min", 60)
            if mode == "work":
                # "Whenever you work" mode: Only accumulates when user is actively inputting
                idle_sec = self.get_idle_seconds()
                if idle_sec < 180.0:  # Active input within 3 minutes
                    self._active_eye_work_seconds += 15.0  # 15s poll interval
                if self._active_eye_work_seconds >= interval_sec:
                    self._trigger_eye_rest_alert()
                    self._active_eye_work_seconds = 0.0
                    return
            else:
                # "Within time" mode: Fixed clock schedule
                if now >= self._next_eye_due:
                    self._trigger_eye_rest_alert()
                    return

        # Global pacing: Ensure at least 30 minutes between other secondary posture/ventilation reminders
        if (now - getattr(self, "_last_any_wellness_time", 0.0)) < 1800.0:
            return

        # 2. Posture & Stretch
        if bool(self.settings.get("enable_posture_reminder", True)):
            if now >= self._next_posture_due:
                self._trigger_posture_alert()
                return

        # 3. Ventilation / Air Freshness
        if bool(self.settings.get("enable_ventilation_reminder", True)):
            if now >= self._next_vent_due:
                self._trigger_ventilation_alert()
                return

    # ---------------- 1. EYE REST (1 HR INTERVAL) ----------------
    def _trigger_eye_rest_alert(self):
        data = {
            "id": f"wellness_eye_{int(time.time())}",
            "type": "eye_rest",
            "title": "Eye Rest (1 hr)",
            "note": "You've been working for 1 hour. Look 20 feet away for 20 seconds to relax your optic nerves.",
            "duration_sec": 20,
        }
        self._last_any_wellness_time = time.time()
        self.wellness_triggered.emit(data)
        self._next_eye_due = time.time() + self._get_interval_sec("eye_rest_interval_min", 60)
        self._active_eye_work_seconds = 0.0

    def snooze_eye_rest(self, minutes: int = 15):
        self._next_eye_due = time.time() + (minutes * 60.0)

    # ---------------- 2. POSTURE & STRETCH ----------------
    def _trigger_posture_alert(self):
        data = {
            "id": f"wellness_posture_{int(time.time())}",
            "type": "posture",
            "title": "Posture & Desk Stretch",
            "note": "Roll your shoulders back, decompress your spine, and do a quick 2-minute stretch.",
        }
        self._last_any_wellness_time = time.time()
        self.wellness_triggered.emit(data)
        self._next_posture_due = time.time() + self._get_interval_sec("posture_interval_min", 90)

    def snooze_posture(self, minutes: int = 20):
        self._next_posture_due = time.time() + (minutes * 60.0)

    # ---------------- 3. VENTILATION / FRESH AIR ----------------
    def _trigger_ventilation_alert(self):
        data = {
            "id": f"wellness_vent_{int(time.time())}",
            "type": "ventilation",
            "title": "Fresh Air & Ventilation",
            "note": "Crack open a window or take a breath outside to flush CO₂ and recharge your focus.",
        }
        self._last_any_wellness_time = time.time()
        self.wellness_triggered.emit(data)
        self._next_vent_due = time.time() + self._get_interval_sec("ventilation_interval_min", 180)

    def snooze_ventilation(self, minutes: int = 30):
        self._next_vent_due = time.time() + (minutes * 60.0)

    # ---------------- 4. BATTERY HEALTH (80% / 30% RULE) ----------------
    def _check_battery_health(self, now: float):
        # Throttle battery alerts to at least 2 hours (7200s) between alerts
        if (now - self._last_battery_alert_time) < 7200.0:
            return

        try:
            class SYSTEM_POWER_STATUS(ctypes.Structure):
                _fields_ = [
                    ('ACLineStatus', ctypes.c_byte),
                    ('BatteryFlag', ctypes.c_byte),
                    ('BatteryLifePercent', ctypes.c_byte),
                    ('SystemStatusFlag', ctypes.c_byte),
                    ('BatteryLifeTime', ctypes.c_ulong),
                    ('BatteryFullLifeTime', ctypes.c_ulong),
                ]
            sps = SYSTEM_POWER_STATUS()
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
                return

            has_battery = (sps.BatteryFlag != 128) and (sps.BatteryFlag != 255) and (sps.BatteryLifePercent <= 100)
            if not has_battery:
                return

            pct = int(sps.BatteryLifePercent)
            plugged_in = (sps.ACLineStatus == 1)

            high_limit = int(self.settings.get("battery_high_limit", 80))
            low_limit = int(self.settings.get("battery_low_limit", 30))

            # Case A: Plugged in & reached upper target limit
            if plugged_in and pct >= high_limit:
                if self._last_battery_alert_type != "unplug":
                    self._last_battery_alert_type = "unplug"
                    self._last_battery_alert_time = now
                    data = {
                        "id": f"wellness_batt_unplug_{int(now)}",
                        "type": "battery_health",
                        "sub_type": "unplug",
                        "title": f"Unplug Charger ({pct}%)",
                        "note": f"Battery reached {pct}%. Unplugging near {high_limit}% significantly extends your laptop's battery lifespan.",
                        "percent": pct
                    }
                    self.wellness_triggered.emit(data)

            # Case B: On battery & dropped below lower target limit
            elif not plugged_in and pct <= low_limit:
                if self._last_battery_alert_type != "plug_in":
                    self._last_battery_alert_type = "plug_in"
                    self._last_battery_alert_time = now
                    data = {
                        "id": f"wellness_batt_plugin_{int(now)}",
                        "type": "battery_health",
                        "sub_type": "plug_in",
                        "title": f"Connect Charger ({pct}%)",
                        "note": f"Battery dropped to {pct}%. Connect your charger to prevent deep discharge degradation.",
                        "percent": pct
                    }
                    self.wellness_triggered.emit(data)

            # Reset alert state when in safe zone (35% - 75%)
            elif 35 < pct < (high_limit - 5):
                self._last_battery_alert_type = None

        except Exception:
            pass

    def on_power_state_changed(self, plugged_in: bool, percent: int):
        """
        Called in real-time when the physical power cable is plugged or unplugged.
        Automatically resolves the corresponding battery alert without waiting for timer or user click.
        """
        now = time.time()
        high_limit = int(self.settings.get("battery_high_limit", 80))
        low_limit = int(self.settings.get("battery_low_limit", 30))

        if plugged_in:
            # Charger is now connected: resolve any pending or active 'plug_in' alerts immediately!
            if self._last_battery_alert_type == "plug_in":
                self._last_battery_alert_type = None
                self._last_battery_alert_time = 0.0
                self.battery_resolved.emit({"action": "plugged_in", "percent": percent})

            # Check if battery is already at or above high limit
            if percent >= high_limit and self._last_battery_alert_type != "unplug":
                if (now - self._last_battery_alert_time) >= 1800.0:
                    self._last_battery_alert_type = "unplug"
                    self._last_battery_alert_time = now
                    data = {
                        "id": f"wellness_batt_unplug_{int(now)}",
                        "type": "battery_health",
                        "sub_type": "unplug",
                        "title": f"Unplug Charger ({percent}%)",
                        "note": f"Battery reached {percent}%. Unplugging near {high_limit}% significantly extends your laptop's battery lifespan.",
                        "percent": percent
                    }
                    self.wellness_triggered.emit(data)
        else:
            # Charger is now disconnected: resolve any pending or active 'unplug' alerts immediately!
            if self._last_battery_alert_type == "unplug":
                self._last_battery_alert_type = None
                self._last_battery_alert_time = 0.0
                self.battery_resolved.emit({"action": "unplugged", "percent": percent})

            # Check if battery is at or below low limit
            if percent <= low_limit and self._last_battery_alert_type != "plug_in":
                if (now - self._last_battery_alert_time) >= 1800.0:
                    self._last_battery_alert_type = "plug_in"
                    self._last_battery_alert_time = now
                    data = {
                        "id": f"wellness_batt_plugin_{int(now)}",
                        "type": "battery_health",
                        "sub_type": "plug_in",
                        "title": f"Connect Charger ({percent}%)",
                        "note": f"Battery dropped to {percent}%. Connect your charger to prevent deep discharge degradation.",
                        "percent": percent
                    }
                    self.wellness_triggered.emit(data)

    def snooze_battery(self, minutes: int = 15):
        # Allow re-triggering after exactly `minutes` by setting last time to (now - 7200 + minutes*60)
        self._last_battery_alert_time = time.time() - max(0.0, 7200.0 - (minutes * 60.0))

    # ---------------- 5. STORAGE PURGE (DOWNLOADS & RECYCLE BIN) ----------------
    def _check_storage_purge(self, now: float):
        interval_days = int(self.settings.get("storage_purge_interval_days", 14))
        interval_sec = interval_days * 86400.0
        warn_pct_thresh = int(self.settings.get("storage_warn_threshold_pct", 80))

        # Check drive consumption
        try:
            c_usage = shutil.disk_usage("C:\\")
            c_used_pct = int((c_usage.used / c_usage.total) * 100)
        except Exception:
            c_used_pct = 0

        last_purged = float(self._state_data.get("last_storage_purge_time", 0.0))
        is_interval_due = (now - last_purged) >= interval_sec
        is_storage_critical = (c_used_pct >= warn_pct_thresh) and ((now - last_purged) >= 86400.0 * 3)

        if is_interval_due or is_storage_critical:
            reason = f"Drive C: is at {c_used_pct}% capacity" if is_storage_critical else "Bi-weekly storage hygiene schedule"
            data = {
                "id": f"wellness_storage_{int(now)}",
                "type": "storage_purge",
                "title": "Storage Purge Time",
                "note": f"Empty Recycle Bin & clean Downloads to preserve SSD performance ({reason}).",
                "c_used_pct": c_used_pct
            }
            self.wellness_triggered.emit(data)

    def execute_storage_cleanup(self) -> dict:
        """
        Safely empties the Windows Recycle Bin via Win32 API and opens the Downloads folder.
        Returns details of cleanup.
        """
        # 1. Empty Recycle Bin (SHERB_NOCONFIRMATION=1 | SHERB_NOPROGRESSUI=2 | SHERB_NOSOUND=4 -> 7)
        try:
            ctypes.windll.shell32.SHEmptyRecycleBinW(0, None, 7)
            bin_emptied = True
        except Exception:
            bin_emptied = False

        # 2. Open Downloads folder for user to review large stale files
        downloads_path = Path.home() / "Downloads"
        try:
            if downloads_path.exists():
                os.startfile(str(downloads_path))
        except Exception:
            pass

        # Update state
        self._state_data["last_storage_purge_time"] = time.time()
        self._save_state()

        result = {
            "bin_emptied": bin_emptied,
            "downloads_opened": downloads_path.exists(),
            "time": time.time()
        }
        self.storage_cleaned.emit(result)
        return result

    def snooze_storage(self, days: int = 1):
        self._state_data["last_storage_purge_time"] = time.time() - (self._get_interval_sec("storage_purge_interval_days", 14) - (days * 86400.0))
        self._save_state()

    # ---------------- TEST PREVIEW TRIGGERS ----------------
    def trigger_test_alert(self, alert_type: str = "eye_rest"):
        if alert_type == "eye_rest":
            self._trigger_eye_rest_alert()
        elif alert_type == "posture":
            self._trigger_posture_alert()
        elif alert_type == "ventilation":
            self._trigger_ventilation_alert()
        elif alert_type == "battery_health":
            cur_mode = getattr(self, "_test_battery_mode", "plug_in")
            next_mode = "unplug" if cur_mode == "plug_in" else "plug_in"
            self._test_battery_mode = next_mode
            if next_mode == "unplug":
                data = {
                    "id": f"wellness_batt_test_{int(time.time())}",
                    "type": "battery_health",
                    "sub_type": "unplug",
                    "title": "Unplug Charger (80%)",
                    "note": "Battery reached 80%. Unplugging near 80% significantly extends battery lifespan.",
                    "percent": 80
                }
            else:
                data = {
                    "id": f"wellness_batt_test_{int(time.time())}",
                    "type": "battery_health",
                    "sub_type": "plug_in",
                    "title": "Connect Charger (18%)",
                    "note": "Battery dropped to 18%. Connect charger now to prevent sudden shutdown.",
                    "percent": 18
                }
            self.wellness_triggered.emit(data)
        elif alert_type == "storage_purge":
            data = {
                "id": f"wellness_storage_test_{int(time.time())}",
                "type": "storage_purge",
                "title": "Storage Purge Time",
                "note": "Empty Recycle Bin & clean Downloads to preserve SSD performance (Bi-weekly schedule).",
                "c_used_pct": 78
            }
            self.wellness_triggered.emit(data)

    def trigger_test_eye_rest(self):
        self.trigger_test_alert("eye_rest")

    def trigger_test_posture(self):
        self.trigger_test_alert("posture")

    def trigger_test_ventilation(self):
        self.trigger_test_alert("ventilation")

    def trigger_test_battery(self, sub_type: Optional[str] = None):
        if sub_type:
            self._test_battery_mode = "plug_in" if sub_type == "unplug" else "unplug"
        self.trigger_test_alert("battery_health")

    def trigger_test_storage(self):
        self.trigger_test_alert("storage_purge")

    # ---------------- STATE PERSISTENCE ----------------
    def _load_state(self):
        self._state_data = {}
        try:
            if self._state_file.exists():
                with open(self._state_file, "r", encoding="utf-8") as f:
                    self._state_data = json.load(f)
        except Exception:
            self._state_data = {}

    def _save_state(self):
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(self._state_data, f)
        except Exception:
            pass
