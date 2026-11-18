"""
ODD Reminder System - Natural Language Reminders for Windows Dynamic Island
Parses human natural language, tracks scheduled and recurring reminders,
and delivers non-intrusive interactive alerts directly inside the Dynamic Island.
"""

import os
import re
import time
import json
import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from PySide6.QtCore import QObject, Signal, QTimer

REMINDERS_FILE = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\reminders.json"))


class ReminderItem:
    """Represents a scheduled, recurring, or triggered reminder."""
    def __init__(self, reminder_id: str, title: str, due_timestamp: float,
                 note: str = "It's time to get this done.",
                 recurrence: Optional[str] = None,
                 context_type: Optional[str] = None,
                 context_target: Optional[str] = None,
                 status: str = "pending",
                 snooze_count: int = 0,
                 created_at: Optional[float] = None):
        self.id = reminder_id
        self.title = title
        self.due_timestamp = float(due_timestamp)
        self.note = note or "It's time to get this done."
        self.recurrence = recurrence  # None, "daily", "weekdays", "weekly"
        self.context_type = context_type  # None, "file", "url", "app"
        self.context_target = context_target  # e.g. path or URL
        self.status = status  # "pending", "triggered", "snoozed", "completed"
        self.snooze_count = snooze_count
        self.created_at = created_at or time.time()
        self.finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "due_timestamp": self.due_timestamp,
            "note": self.note,
            "recurrence": self.recurrence,
            "context_type": self.context_type,
            "context_target": self.context_target,
            "status": self.status,
            "snooze_count": self.snooze_count,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "due_formatted": self.get_due_formatted()
        }

    def get_due_formatted(self) -> str:
        try:
            dt = datetime.datetime.fromtimestamp(self.due_timestamp)
            now = datetime.datetime.now()
            
            # Format time: e.g. "7:00 PM"
            time_part = dt.strftime("%I:%M %p").lstrip("0")
            
            if dt.date() == now.date():
                return f"Today at {time_part}"
            elif dt.date() == (now + datetime.timedelta(days=1)).date():
                return f"Tomorrow at {time_part}"
            elif dt.year == now.year:
                return f"{dt.strftime('%b %d')} at {time_part}"
            else:
                return f"{dt.strftime('%b %d, %Y')} at {time_part}"
        except Exception:
            return "Scheduled"


class ReminderParser:
    r"""
    Intelligent natural-language parser for human reminder phrasing.
    Examples:
      - "remind me to submit my assignment at 7 PM"
      - "remind me in 10 minutes to call John"
      - "remind me tomorrow at 9am to check email"
      - "remind me every day at 8:30 am to take vitamins"
      - "rem: buy groceries in 1 hour"
      - "remind to review E:\project\report.pdf at 5pm"
    """

    @staticmethod
    def parse(query: str, default_minutes: int = 15) -> Optional[Dict[str, Any]]:
        q = query.strip()
        if not q:
            return None

        # Clean prefix triggers
        prefixes = [
            r"^remind\s+me\s+to\s+",
            r"^remind\s+me\s+",
            r"^remind\s+to\s+",
            r"^remind:\s*",
            r"^rem:\s*",
            r"^reminder:\s*",
            r"^r:\s*",
            r"^todo:\s*"
        ]
        text = q
        matched_prefix = False
        for p in prefixes:
            m = re.match(p, text, re.IGNORECASE)
            if m:
                text = text[m.end():].strip()
                matched_prefix = True
                break

        if not text and not matched_prefix:
            return None

        # Default values
        now = datetime.datetime.now()
        target_dt = now + datetime.timedelta(minutes=default_minutes)
        recurrence = None
        context_target = None
        context_type = None

        # 1. Detect recurrence (every day, daily, every weekday, every Monday, etc.)
        rec_match = re.search(r"\b(every\s+day|daily|every\s+morning|every\s+evening|every\s+weekday|every\s+week)\b", text, re.IGNORECASE)
        if rec_match:
            rec_str = rec_match.group(1).lower()
            if "day" in rec_str or "daily" in rec_str or "morning" in rec_str or "evening" in rec_str:
                recurrence = "daily"
            elif "weekday" in rec_str:
                recurrence = "weekdays"
            elif "week" in rec_str:
                recurrence = "weekly"
            text = text[:rec_match.start()] + text[rec_match.end():]

        # 2. Detect context attachments (file paths or URLs)
        file_match = re.search(r"([A-Za-z]:\\[^ \t\n\r\f\v\"<>|]+\.[a-zA-Z0-9]+)", text)
        if file_match:
            candidate_path = file_match.group(1)
            if os.path.exists(candidate_path):
                context_type = "file"
                context_target = candidate_path

        url_match = re.search(r"(https?://[^\s]+)", text)
        if url_match and not context_target:
            context_type = "url"
            context_target = url_match.group(1)

        # 3. Detect relative time: "in X minutes/hours/seconds/days"
        rel_match = re.search(r"\bin\s+(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\b", text, re.IGNORECASE)
        has_time = False

        if rel_match:
            val = float(rel_match.group(1))
            unit = rel_match.group(2).lower()
            if unit.startswith("s"):
                target_dt = now + datetime.timedelta(seconds=val)
            elif unit.startswith("m"):
                target_dt = now + datetime.timedelta(minutes=val)
            elif unit.startswith("h"):
                target_dt = now + datetime.timedelta(hours=val)
            elif unit.startswith("d"):
                target_dt = now + datetime.timedelta(days=val)
            text = text[:rel_match.start()] + text[rel_match.end():]
            has_time = True

        # 4. Detect "tomorrow", "tonight", "today"
        day_offset = 0
        if re.search(r"\btomorrow\b", text, re.IGNORECASE):
            day_offset = 1
            text = re.sub(r"\btomorrow\b", "", text, flags=re.IGNORECASE)
            has_time = True
        elif re.search(r"\btonight\b", text, re.IGNORECASE):
            day_offset = 0
            text = re.sub(r"\btonight\b", "", text, flags=re.IGNORECASE)
            has_time = True

        # 5. Detect absolute time: "at 7 PM", "at 7:30 am", "at 19:00", "7pm", "10:30am"
        time_match = re.search(r"(?:at\s+)?(\b\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE)
        if not time_match:
            # Check 24-hour format: "at 19:30"
            time_match_24 = re.search(r"\bat\s+(\d{1,2}):(\d{2})\b", text, re.IGNORECASE)
            if time_match_24:
                hour = int(time_match_24.group(1))
                minute = int(time_match_24.group(2))
                target_date = (now + datetime.timedelta(days=day_offset)).date()
                target_dt = datetime.datetime(target_date.year, target_date.month, target_date.day, hour, minute)
                if target_dt <= now and day_offset == 0:
                    target_dt += datetime.timedelta(days=1)
                text = text[:time_match_24.start()] + text[time_match_24.end():]
                has_time = True
        else:
            raw_h = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            meridiem = time_match.group(3).lower()

            if meridiem == "pm" and raw_h < 12:
                hour = raw_h + 12
            elif meridiem == "am" and raw_h == 12:
                hour = 0
            else:
                hour = raw_h

            target_date = (now + datetime.timedelta(days=day_offset)).date()
            target_dt = datetime.datetime(target_date.year, target_date.month, target_date.day, hour, minute)
            if target_dt <= now and day_offset == 0:
                target_dt += datetime.timedelta(days=1)
            text = text[:time_match.start()] + text[time_match.end():]
            has_time = True

        # Clean remaining prepositions & spaces from title
        clean_title = text.strip()
        clean_title = re.sub(r"^(to\s+|that\s+)", "", clean_title, flags=re.IGNORECASE).strip()
        clean_title = re.sub(r"\s+", " ", clean_title)

        if not clean_title:
            clean_title = "Reminder"

        clean_title = clean_title[0].upper() + clean_title[1:] if len(clean_title) > 1 else clean_title.upper()

        return {
            "title": clean_title,
            "due_timestamp": target_dt.timestamp(),
            "due_dt": target_dt,
            "has_time": has_time,
            "recurrence": recurrence,
            "context_type": context_type,
            "context_target": context_target
        }


class ReminderManager(QObject):
    """
    Singleton manager for live reminders.
    Emits signals when reminders trigger or state changes.
    """
    reminder_triggered = Signal(dict)
    reminders_changed = Signal()
    reminder_auto_resolved = Signal(dict)

    _instance = None

    @classmethod
    def get_instance(cls, settings=None):
        if cls._instance is None:
            cls._instance = ReminderManager(settings or {})
        elif settings:
            cls._instance.settings = settings
        return cls._instance

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self._reminders: Dict[str, ReminderItem] = {}
        self._active_triggered: Optional[ReminderItem] = None
        self._load_reminders()

        # Ticking timer to check for due reminders every 1s
        self._check_timer = QTimer(self)
        self._check_timer.setInterval(1000)
        self._check_timer.timeout.connect(self._check_due_reminders)
        self._check_timer.start()

    def _load_reminders(self):
        try:
            if REMINDERS_FILE.exists():
                with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            r = ReminderItem(
                                reminder_id=item.get("id", ""),
                                title=item.get("title", ""),
                                due_timestamp=item.get("due_timestamp", time.time()),
                                note=item.get("note", "It's time to get this done."),
                                recurrence=item.get("recurrence", None),
                                context_type=item.get("context_type", None),
                                context_target=item.get("context_target", None),
                                status=item.get("status", "pending"),
                                snooze_count=item.get("snooze_count", 0),
                                created_at=item.get("created_at", time.time())
                            )
                            r.finished_at = item.get("finished_at", None)
                            self._reminders[r.id] = r
        except Exception:
            pass

    def _save_reminders(self):
        try:
            REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
                data = [r.to_dict() for r in self._reminders.values()]
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_reminder(self, title: str, due_timestamp: float,
                     note: str = "It's time to get this done.",
                     recurrence: Optional[str] = None,
                     context_type: Optional[str] = None,
                     context_target: Optional[str] = None) -> ReminderItem:
        rid = f"rem_{int(time.time() * 1000)}"
        rem = ReminderItem(
            reminder_id=rid,
            title=title,
            due_timestamp=due_timestamp,
            note=note,
            recurrence=recurrence,
            context_type=context_type,
            context_target=context_target,
            status="pending"
        )
        self._reminders[rid] = rem
        self._save_reminders()
        self.reminders_changed.emit()
        return rem

    def complete_reminder(self, reminder_id: str):
        rem = self._reminders.get(reminder_id)
        if not rem:
            return

        rem.status = "completed"
        rem.finished_at = time.time()

        if self._active_triggered and self._active_triggered.id == reminder_id:
            self._active_triggered = None

        # If recurring, schedule the next iteration automatically!
        if rem.recurrence:
            next_due = rem.due_timestamp
            if rem.recurrence == "daily":
                next_due += 86400.0
            elif rem.recurrence == "weekdays":
                dt = datetime.datetime.fromtimestamp(rem.due_timestamp)
                while True:
                    dt += datetime.timedelta(days=1)
                    if dt.weekday() < 5:  # Monday through Friday
                        break
                next_due = dt.timestamp()
            elif rem.recurrence == "weekly":
                next_due += 7 * 86400.0

            # Create next instance
            self.add_reminder(
                title=rem.title,
                due_timestamp=next_due,
                note=rem.note,
                recurrence=rem.recurrence,
                context_type=rem.context_type,
                context_target=rem.context_target
            )

        self._save_reminders()
        self.reminders_changed.emit()

    def snooze_reminder(self, reminder_id: str, minutes: int = 5):
        rem = self._reminders.get(reminder_id)
        if not rem:
            return

        rem.status = "snoozed"
        rem.due_timestamp = time.time() + (minutes * 60.0)
        rem.snooze_count += 1

        if self._active_triggered and self._active_triggered.id == reminder_id:
            self._active_triggered = None

        self._save_reminders()
        self.reminders_changed.emit()

    def reschedule_reminder(self, reminder_id: str, new_due_timestamp: float):
        rem = self._reminders.get(reminder_id)
        if not rem:
            return

        rem.status = "pending"
        rem.due_timestamp = float(new_due_timestamp)

        if self._active_triggered and self._active_triggered.id == reminder_id:
            self._active_triggered = None

        self._save_reminders()
        self.reminders_changed.emit()

    def delete_reminder(self, reminder_id: str):
        if reminder_id in self._reminders:
            del self._reminders[reminder_id]
        if self._active_triggered and self._active_triggered.id == reminder_id:
            self._active_triggered = None
        self._save_reminders()
        self.reminders_changed.emit()

    def clear_all(self):
        self._reminders.clear()
        self._active_triggered = None
        self._save_reminders()
        self.reminders_changed.emit()

    def on_power_state_changed(self, plugged_in: bool):
        """
        Automatically identifies charger plug/unplug events and resolves corresponding
        custom natural language reminders (e.g. 'charge laptop', 'unplug charger').
        """
        resolved_any = False
        for rem in list(self._reminders.values()):
            if rem.status in ("pending", "triggered", "snoozed"):
                t = (rem.title + " " + rem.note).lower()
                if plugged_in:
                    if any(w in t for w in ("charge", "plug in", "plug-in", "connect charger", "charger")) and "unplug" not in t:
                        self.complete_reminder(rem.id)
                        self.reminder_auto_resolved.emit({"action": "plugged_in", "id": rem.id, "title": rem.title})
                        resolved_any = True
                else:
                    if any(w in t for w in ("unplug", "disconnect charger", "stop charging")):
                        self.complete_reminder(rem.id)
                        self.reminder_auto_resolved.emit({"action": "unplugged", "id": rem.id, "title": rem.title})
                        resolved_any = True
        if resolved_any:
            self._save_reminders()
            self.reminders_changed.emit()

    def get_upcoming_reminders(self) -> List[ReminderItem]:
        pending = [r for r in self._reminders.values() if r.status in ("pending", "snoozed")]
        pending.sort(key=lambda r: r.due_timestamp)
        return pending

    def get_active_triggered(self) -> Optional[ReminderItem]:
        return self._active_triggered

    def _check_due_reminders(self):
        if not self.settings.get("enable_dynamic_island", True):
            return

        now = time.time()
        for rem in list(self._reminders.values()):
            if rem.status in ("pending", "snoozed") and now >= rem.due_timestamp:
                rem.status = "triggered"
                self._active_triggered = rem
                self._save_reminders()
                self.reminder_triggered.emit(rem.to_dict())
                self.reminders_changed.emit()
                break

    def trigger_demo_reminder(self, title: str = "Submit assignment", note: str = "It's time to get this done."):
        """Triggers an immediate demo reminder directly inside the Dynamic Island for testing"""
        demo_id = f"demo_rem_{int(time.time())}"
        rem = ReminderItem(
            reminder_id=demo_id,
            title=title,
            due_timestamp=time.time(),
            note=note,
            status="triggered"
        )
        self._reminders[demo_id] = rem
        self._active_triggered = rem
        self.reminder_triggered.emit(rem.to_dict())
        self.reminders_changed.emit()


class WaterReminderManager(QObject):
    """
    Intelligent Water & Hydration Reminder Engine for ODD Dynamic Island:
    - Customizable intervals: 30 mins, 45 mins, 60 mins.
    - Working hours filtering: e.g. 9:00 AM – 5:00 PM (active only during desk hours).
    - Daily intake tracking (glasses drank today vs daily goal).
    - Non-intrusive interactive alerts directly inside the Dynamic Island.
    """
    water_triggered = Signal(dict)
    hydration_updated = Signal(dict)

    _instance = None

    @classmethod
    def get_instance(cls, settings: dict = None):
        if cls._instance is None:
            cls._instance = cls(settings or {})
        elif settings:
            cls._instance.update_settings(settings)
        return cls._instance

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings or {}
        self._next_due_time = 0.0
        self._today_date_str = datetime.date.today().isoformat()
        self._glasses_today = 0
        self._liters_today = 0.0
        self._daily_liters = float(self.settings.get("water_daily_liters", 2.0))
        self._daily_goal = max(1, int(round(self._daily_liters / 0.25)))
        self._active_work_seconds = 0.0
        self._load_hydration_state()

        self._schedule_next_water(initial=True)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(20000)  # Check every 20s
        self.poll_timer.timeout.connect(self._check_water_due)
        self.poll_timer.start()

    def update_settings(self, new_settings: dict):
        old_interval = int(self.settings.get("water_reminder_interval_min", 60))
        self.settings = new_settings
        self._daily_liters = float(self.settings.get("water_daily_liters", 2.0))
        self._daily_goal = max(1, int(round(self._daily_liters / 0.25)))
        new_interval = int(self.settings.get("water_reminder_interval_min", 60))
        if old_interval != new_interval:
            self._schedule_next_water()

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

    def is_within_working_hours(self) -> bool:
        """Checks if current time falls within configured working hours (e.g. 9:00 AM - 5:00 PM)"""
        if not self.settings.get("water_working_hours_only", True):
            return True

        now = datetime.datetime.now().time()
        start_str = str(self.settings.get("water_start_time", "09:00")).strip()
        end_str = str(self.settings.get("water_end_time", "17:00")).strip()

        try:
            start_parts = [int(p) for p in start_str.split(":")]
            end_parts = [int(p) for p in end_str.split(":")]
            t_start = datetime.time(start_parts[0], start_parts[1])
            t_end = datetime.time(end_parts[0], end_parts[1])

            if t_start <= t_end:
                return t_start <= now <= t_end
            else:
                return now >= t_start or now <= t_end
        except Exception:
            return datetime.time(9, 0) <= now <= datetime.time(17, 0)

    def _schedule_next_water(self, initial: bool = False, delay_minutes: Optional[int] = None):
        interval = delay_minutes if delay_minutes is not None else int(self.settings.get("water_reminder_interval_min", 60))
        if interval <= 0:
            interval = 60
        self._next_due_time = time.time() + (interval * 60.0)
        self._active_work_seconds = 0.0

    def _check_water_due(self):
        if not bool(self.settings.get("enable_water_reminder", True)):
            return

        today = datetime.date.today().isoformat()
        if today != self._today_date_str:
            self._today_date_str = today
            self._glasses_today = 0
            self._liters_today = 0.0
            self._active_work_seconds = 0.0
            self._save_hydration_state()

        mode = str(self.settings.get("water_reminder_mode", "work")).lower()
        interval_min = int(self.settings.get("water_reminder_interval_min", 60))
        if interval_min <= 0:
            interval_min = 60
        interval_sec = interval_min * 60.0

        if mode == "work":
            # "Whenever you work" mode: Only accumulate time when user is actively inputting
            idle_sec = self.get_idle_seconds()
            if idle_sec < 180.0:  # Active input within 3 minutes
                self._active_work_seconds += 20.0  # 20s tick
            if self._active_work_seconds >= interval_sec:
                if self.is_within_working_hours():
                    self._trigger_water_alert()
                    self._active_work_seconds = 0.0
                else:
                    self._active_work_seconds = interval_sec - 120.0
        else:
            # "Within time" mode: Fixed clock schedule
            now = time.time()
            if now >= self._next_due_time:
                if self.is_within_working_hours():
                    self._trigger_water_alert()
                else:
                    self._schedule_next_water(delay_minutes=60)

    def _trigger_water_alert(self):
        interval_min = int(self.settings.get("water_reminder_interval_min", 60))
        progress_pct = min(100.0, round((self._liters_today / max(0.1, self._daily_liters)) * 100.0, 1))
        is_completed = (self._liters_today >= self._daily_liters)

        if is_completed:
            note = f"Daily goal achieved! ({self._liters_today:.2f}L / {self._daily_liters:.1f}L completed). Sip to stay hydrated."
        else:
            note = f"Take a sip to stay focused ({self._liters_today:.2f}L / {self._daily_liters:.1f}L • {progress_pct:.0f}% completed)."

        bottle_style = str(self.settings.get("water_bottle_style", "broader_2l"))
        data = {
            "id": f"water_rem_{int(time.time())}",
            "type": "water",
            "title": "Time to Hydrate",
            "note": note,
            "glasses_today": self._glasses_today,
            "liters_today": self._liters_today,
            "daily_liters": self._daily_liters,
            "daily_goal": self._daily_goal,
            "progress_pct": progress_pct,
            "is_completed": is_completed,
            "bottle_style": bottle_style,
            "interval_min": interval_min,
        }
        self.water_triggered.emit(data)
        self._schedule_next_water()

    def log_drink(self, amount_liters: float = 0.25) -> dict:
        """User drank water (+250ml by default): increments intake and schedules next reminder."""
        self._glasses_today += 1
        self._liters_today = round(self._liters_today + amount_liters, 2)
        progress_pct = min(100.0, round((self._liters_today / max(0.1, self._daily_liters)) * 100.0, 1))
        is_completed = (self._liters_today >= self._daily_liters)
        self._save_hydration_state()
        self._schedule_next_water()

        state = {
            "glasses_today": self._glasses_today,
            "liters_today": self._liters_today,
            "daily_liters": self._daily_liters,
            "daily_goal": self._daily_goal,
            "progress_pct": progress_pct,
            "is_completed": is_completed
        }
        self.hydration_updated.emit(state)
        return state

    def snooze(self, minutes: int = 10):
        """Snoozes water reminder for X minutes"""
        self._schedule_next_water(delay_minutes=minutes)

    def dismiss(self):
        """Dismisses current alert and resets interval"""
        self._schedule_next_water()

    def trigger_test_alert(self):
        """Immediately triggers a preview water reminder in Dynamic Island"""
        self._trigger_water_alert()

    def get_glasses_today(self) -> int:
        return self._glasses_today

    def get_liters_today(self) -> float:
        return self._liters_today

    def get_daily_liters(self) -> float:
        return self._daily_liters

    def get_daily_goal(self) -> int:
        return self._daily_goal

    def _load_hydration_state(self):
        try:
            p = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\hydration.json"))
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    if d.get("date") == self._today_date_str:
                        self._glasses_today = int(d.get("glasses_today", 0))
                        self._liters_today = float(d.get("liters_today", round(self._glasses_today * 0.25, 2)))
        except Exception:
            pass

    def _save_hydration_state(self):
        try:
            p = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\hydration.json"))
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({
                    "date": self._today_date_str,
                    "glasses_today": self._glasses_today,
                    "liters_today": self._liters_today,
                    "daily_liters": self._daily_liters,
                    "bottle_style": self.settings.get("water_bottle_style", "broader_2l")
                }, f)
        except Exception:
            pass
