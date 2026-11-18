"""

Dynamic Island & Bezel HUD Engine for Windows (ODD)

- Squircle Bezel HUD for Caps Lock ON (tick) / OFF (cross) with smooth IN & OUT animations

- Squircle Bezel HUD for Media Mute / Unmute with smooth IN & OUT animations

- Non-intrusive Gliding Drop-Down Notifications with smooth IN & OUT animations

- Media Track & Real-time Equalizer Waveform Live Activity

- Independent Volume Level HUD Capsule

- Fast Snappy Copy & Paste Animations

- Live Countdown Timer Ticker in Notch

- Battery & Power Status Animations

- Rook Module Shortcut Indication Animations

- 100% Emoji-Free, crisp typography & minimal vector graphics

"""



import os

import sys

import time

import math

import ctypes

import threading

from ctypes import wintypes

from typing import Optional, Dict, Any, Tuple



from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRect, QPoint, QPointF, QSize, QEasingCurve, QPropertyAnimation, QRectF, Property

from PySide6.QtGui import QColor, QFont, QPainter, QBrush, QPen, QPixmap, QIcon, QPainterPath, QLinearGradient, QRadialGradient, QConicalGradient, QCursor, QFontMetrics

from PySide6.QtWidgets import QWidget, QApplication, QLabel, QHBoxLayout, QVBoxLayout, QGraphicsBlurEffect

from odd_spring import SpringValue

from odd_crash_capture import safe_slot





# Structure for Windows Battery & Power Status

class SYSTEM_POWER_STATUS(ctypes.Structure):

    _fields_ = [

        ('ACLineStatus', wintypes.BYTE),

        ('BatteryFlag', wintypes.BYTE),

        ('BatteryLifePercent', wintypes.BYTE),

        ('SystemStatusFlag', wintypes.BYTE),

        ('BatteryLifeTime', wintypes.DWORD),

        ('BatteryFullLifeTime', wintypes.DWORD),

    ]





from pathlib import Path

import json



ACTIVITY_HISTORY_FILE = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\activity_history.json"))





def format_download_filename(filename: str, max_chars: int = 22) -> str:

    """Formats download filename, cleanly eliding with '...' while preserving file extension."""

    if not filename:

        return "Downloading File"

    clean = str(filename).strip()

    if clean.lower().startswith("unconfirmed"):

        return "Downloading File"

    if len(clean) <= max_chars:

        return clean

    name, ext = os.path.splitext(clean)

    if ext and len(ext) <= 6:

        avail = max(4, max_chars - len(ext) - 3)

        return f"{name[:avail]}...{ext}"

    return f"{clean[:max_chars - 3]}..."





class ActivityItem:

    """Represents an active or remembered system activity, installer, or download."""

    def __init__(self, activity_id: str, title: str, progress: float = 0.0, subtitle: str = "",

                 activity_type: str = "download", icon_type: str = "download",

                 speed_str: str = "", total_bytes: int = 0, downloaded_bytes: int = 0,

                 target_path: str = "", status: str = "active", is_demo: bool = False):

        self.id = activity_id

        self.title = title

        self.progress = float(progress)  # 0.0 to 100.0 (or -1 for indeterminate)

        self.subtitle = subtitle

        self.activity_type = activity_type  # 'install', 'download', 'task', 'update'

        self.icon_type = icon_type  # 'blue_sphere', 'install', 'download', 'package', 'check', 'warning'

        self.speed_str = speed_str

        self.total_bytes = total_bytes

        self.downloaded_bytes = downloaded_bytes

        self.target_path = target_path

        self.status = status  # 'active', 'completed', 'paused', 'failed'

        self.is_demo = is_demo

        self.created_at = time.time()

        self.updated_at = time.time()

        self.finished_at = None



    def to_dict(self) -> dict:

        return {

            "id": self.id,

            "title": self.title,

            "progress": self.progress,

            "subtitle": self.subtitle,

            "activity_type": self.activity_type,

            "icon_type": self.icon_type,

            "speed_str": self.speed_str,

            "total_bytes": self.total_bytes,

            "downloaded_bytes": self.downloaded_bytes,

            "target_path": self.target_path,

            "status": self.status,

            "is_demo": self.is_demo,

            "created_at": self.created_at,

            "updated_at": self.updated_at,

            "finished_at": self.finished_at

        }





class ActivityManager(QObject):

    """

    Manages live system downloads, background installations, and activity memory.

    Auto-merges multiple active downloads into unified state for the notch progress ring

    and remembers recent activities with persistence.

    """

    activities_changed = Signal()

    _download_scan_completed = Signal(object)



    _instance = None



    @classmethod

    def get_instance(cls, settings=None):

        if cls._instance is None:

            cls._instance = ActivityManager(settings or {})

        elif settings:

            cls._instance.settings = settings

        return cls._instance



    def __init__(self, settings: dict):

        super().__init__()

        self.settings = settings

        self._activities: Dict[str, ActivityItem] = {}

        self._remembered: List[ActivityItem] = []

        self._dl_history_map: Dict[str, float] = {}

        self._dl_time_map: Dict[str, float] = {}

        self._browser_dl_meta: Dict[str, dict] = {}

        self._last_browser_meta_time = 0.0

        self._dl_scan_in_flight = False

        self._active_demo_timer: Optional[QTimer] = None

        self._load_history()



        self._download_scan_completed.connect(self._apply_download_scan)



        # Windows Downloads folder & Chromium real-time scanner (1.2s interval for minimal disk I/O)

        self._dl_scanner_timer = QTimer(self)

        self._dl_scanner_timer.setInterval(1200)

        self._dl_scanner_timer.timeout.connect(self._scan_downloads)

        self._dl_scanner_timer.start()



    def _load_history(self):

        try:

            if ACTIVITY_HISTORY_FILE.exists():

                with open(ACTIVITY_HISTORY_FILE, "r", encoding="utf-8") as f:

                    data = json.load(f)

                    if isinstance(data, list):

                        for item in data[:30]:

                            act = ActivityItem(

                                activity_id=item.get("id", ""),

                                title=item.get("title", ""),

                                progress=item.get("progress", 100.0),

                                subtitle=item.get("subtitle", "Completed"),

                                activity_type=item.get("activity_type", "download"),

                                icon_type=item.get("icon_type", "check"),

                                speed_str=item.get("speed_str", ""),

                                total_bytes=item.get("total_bytes", 0),

                                downloaded_bytes=item.get("downloaded_bytes", 0),

                                target_path=item.get("target_path", ""),

                                status=item.get("status", "completed")

                            )

                            act.created_at = item.get("created_at", time.time())

                            act.finished_at = item.get("finished_at", time.time())

                            self._remembered.append(act)

        except Exception:

            pass



    def _save_history(self):

        try:

            ACTIVITY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

            with open(ACTIVITY_HISTORY_FILE, "w", encoding="utf-8") as f:

                data = [a.to_dict() for a in self._remembered[:30]]

                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception:

            pass



    def start_activity(self, activity_id: str, title: str, progress: float = 0.0, subtitle: str = "",

                       activity_type: str = "download", icon_type: str = "download",

                       speed_str: str = "", total_bytes: int = 0, downloaded_bytes: int = 0,

                       target_path: str = "", is_demo: bool = False) -> ActivityItem:

        act = ActivityItem(

            activity_id=activity_id,

            title=title,

            progress=progress,

            subtitle=subtitle,

            activity_type=activity_type,

            icon_type=icon_type,

            speed_str=speed_str,

            total_bytes=total_bytes,

            downloaded_bytes=downloaded_bytes,

            target_path=target_path,

            status="active",

            is_demo=is_demo

        )

        self._activities[activity_id] = act

        self.activities_changed.emit()

        return act



    def update_activity(self, activity_id: str, progress: Optional[float] = None, subtitle: Optional[str] = None,

                        speed_str: Optional[str] = None, downloaded_bytes: Optional[int] = None,

                        total_bytes: Optional[int] = None, status: Optional[str] = None):

        act = self._activities.get(activity_id)

        if not act:

            return

        if progress is not None:

            act.progress = float(progress)

        if subtitle is not None:

            act.subtitle = subtitle

        if speed_str is not None:

            act.speed_str = speed_str

        if downloaded_bytes is not None:

            act.downloaded_bytes = downloaded_bytes

        if total_bytes is not None:

            act.total_bytes = total_bytes

        if status is not None:

            act.status = status

        act.updated_at = time.time()

        self.activities_changed.emit()



    def finish_activity(self, activity_id: str, status: str = "completed", message: str = "Finished", target_path: str = ""):

        act = self._activities.pop(activity_id, None)

        if not act:

            return

        act.status = status

        act.progress = 100.0 if status == "completed" else act.progress

        act.subtitle = message

        act.finished_at = time.time()

        if target_path:

            act.target_path = target_path



        # Add to remembered activities (top of history, deduplicated)

        self._remembered = [r for r in self._remembered if r.id != act.id and r.title != act.title]

        self._remembered.insert(0, act)

        self._remembered = self._remembered[:30]

        self._save_history()

        self.activities_changed.emit()



    def remove_activity(self, activity_id: str):

        if activity_id in self._activities:

            del self._activities[activity_id]

        self._remembered = [r for r in self._remembered if r.id != activity_id]

        self._save_history()

        self.activities_changed.emit()



    def clear_history(self):

        self._remembered = []

        self._save_history()

        self.activities_changed.emit()



    def get_merged_state(self) -> Dict[str, Any]:

        active_items = [item for item in self._activities.values() if item.status == "active"]



        if not active_items:

            return {

                "has_active": False,

                "is_completed_pulse": False,

                "merged_progress": 0.0,

                "count": 0,

                "primary_title": "",

                "status_text": "",

                "total_speed_str": "",

                "active_items": [],

                "remembered_items": self._remembered,

                "all_items": self._remembered

            }



        # Calculate merged percentage

        valid_progs = [max(0.0, min(100.0, item.progress)) for item in active_items if item.progress >= 0]

        merged_pct = sum(valid_progs) / max(1, len(valid_progs)) if valid_progs else 0.0



        # Calculate combined speeds

        speeds = [item.speed_str for item in active_items if item.speed_str]

        combined_speed = speeds[0] if len(speeds) == 1 else (f"{len(active_items)} active" if not speeds else speeds[0])



        if len(active_items) == 1:

            top_item = active_items[0]

            prog_int = int(round(top_item.progress))

            primary_title = f"{top_item.title} — {prog_int}%"

            status_text = f"{prog_int}%"

            if top_item.speed_str:

                status_text += f" • {top_item.speed_str}"

        else:

            prog_int = int(round(merged_pct))

            primary_title = f"{len(active_items)} Downloads — {prog_int}%"

            status_text = f"{prog_int}% (Merged)"

            if speeds:

                status_text += f" • {speeds[0]}"



        return {

            "has_active": True,

            "is_completed_pulse": False,

            "merged_progress": merged_pct,

            "count": len(active_items),

            "primary_title": primary_title,

            "status_text": status_text,

            "total_speed_str": combined_speed,

            "active_items": active_items,

            "remembered_items": self._remembered,

            "all_items": active_items + self._remembered

        }



    def _query_browser_downloads(self):

        """Scans active Chromium SQLite databases in read-only mode for real-time download metadata."""

        now = time.time()

        if (now - getattr(self, '_last_browser_meta_time', 0.0)) < 0.6:

            return

        self._last_browser_meta_time = now



        try:

            import glob

            import sqlite3

            local = os.environ.get('LOCALAPPDATA', '')

            patterns = [

                os.path.join(local, r'Google\Chrome\User Data\*\History'),

                os.path.join(local, r'Microsoft\Edge\User Data\*\History'),

                os.path.join(local, r'BraveSoftware\Brave-Browser\User Data\*\History'),

                os.path.join(local, r'Opera Software\Opera Stable\History'),

                os.path.join(local, r'Opera Software\Opera GX Stable\History'),

                os.path.join(local, r'Vivaldi\User Data\*\History'),

            ]

            db_paths = []

            for pat in patterns:

                db_paths.extend(glob.glob(pat))



            meta_map = {}

            active_list = []

            for db_p in db_paths:

                clean_p = db_p.replace('\\', '/')

                conn = None

                for uri_str in (f'file:{clean_p}?mode=ro', f'file:{clean_p}?mode=ro&immutable=1'):

                    try:

                        conn = sqlite3.connect(uri_str, uri=True, timeout=0.15)

                        break

                    except Exception:

                        conn = None

                if not conn:

                    continue



                try:

                    c = conn.cursor()

                    c.execute('SELECT target_path, current_path, received_bytes, total_bytes, state, start_time FROM downloads WHERE state IN (0, 3) ORDER BY start_time DESC LIMIT 15')

                    rows = c.fetchall()

                    if not rows:

                        c.execute('SELECT target_path, current_path, received_bytes, total_bytes, state, start_time FROM downloads ORDER BY start_time DESC LIMIT 10')

                        rows = c.fetchall()



                    for row in rows:

                        target_p, cur_p, rec_b, tot_b, st, s_time = row

                        tot_val = int(tot_b) if tot_b else 0

                        rec_val = int(rec_b) if rec_b else 0

                        meta_data = {

                            "total_bytes": tot_val,

                            "target_path": target_p,

                            "received_bytes": rec_val,

                            "state": st,

                            "start_time": s_time

                        }

                        active_list.append(meta_data)

                        if target_p:

                            meta_map[os.path.basename(target_p).lower()] = meta_data

                        if cur_p:

                            c_base = os.path.basename(cur_p).lower()

                            meta_map[c_base] = meta_data

                            for ext in [".crdownload", ".part", ".opdownload", ".downloading"]:

                                if c_base.endswith(ext):

                                    meta_map[c_base[:-len(ext)]] = meta_data

                    conn.close()

                except Exception:

                    try:

                        conn.close()

                    except Exception:

                        pass



            self._browser_dl_meta = meta_map

            self._browser_dl_active_list = active_list

        except Exception:

            pass



    def _resolve_unconfirmed_file(self, file_path: str, fallback_name: str) -> str:

        """Inspects file header magic bytes so downloads NEVER show ugly 'Unconfirmed 12345'."""

        try:

            if os.path.exists(file_path):

                with open(file_path, "rb") as f:

                    header = f.read(64)

                if header.startswith(b"PK\x03\x04"):

                    return "Archive.zip"

                elif header.startswith(b"MZ"):

                    return "Application.exe"

                elif header.startswith(b"%PDF"):

                    return "Document.pdf"

                elif header.startswith(b"\x89PNG"):

                    return "Image.png"

                elif header.startswith(b"\xff\xd8\xff"):

                    return "Image.jpg"

                elif header.startswith(b"7z\xbc\xaf\x27\x1c"):

                    return "Package.7z"

                elif header.startswith(b"Rar!\x1a\x07"):

                    return "Archive.rar"

                elif b"ftyp" in header[:16]:

                    return "Video.mp4"

                elif header.startswith(b"\x1a\x45\xdf\xa3"):

                    return "Video.mkv"

        except Exception:

            pass

        return "Downloading File"



    def _scan_downloads(self):

        """Schedule disk and browser database scanning away from the GUI thread."""

        if not self.settings.get("auto_detect_downloads", True) or self._dl_scan_in_flight:

            return

        self._dl_scan_in_flight = True

        active_progress = {

            aid: float(getattr(act, "progress", 25.0))

            for aid, act in self._activities.items()

            if aid.startswith("dl_")

        }

        try:

            worker = threading.Thread(

                target=self._scan_downloads_worker,

                args=(active_progress,),

                name="ODD-DownloadScanner",

                daemon=True,

            )

            worker.start()

        except Exception:

            self._dl_scan_in_flight = False



    def _scan_downloads_worker(self, active_progress: Dict[str, float]):

        """Read browser metadata and the Downloads directory without blocking input events."""

        try:

            dl_dir = Path(os.path.expanduser("~/Downloads"))

            if not dl_dir.exists():

                self._download_scan_completed.emit({"ok": False})

                return

            self._query_browser_downloads()

            now = time.time()

            found_dl_keys = set()

            updates = []



            with os.scandir(dl_dir) as it:

                for entry in it:

                    if not entry.is_file():

                        continue

                    low_name = entry.name.lower()

                    is_download_part = (

                        low_name.endswith(".crdownload") or low_name.endswith(".part") or

                        low_name.endswith(".opdownload") or low_name.endswith(".downloading")

                    )

                    if not is_download_part:

                        continue



                    file_path = entry.path

                    act_id = f"dl_{entry.name}"

                    found_dl_keys.add(act_id)



                    base_name = entry.name

                    for ext in [".crdownload", ".part", ".opdownload", ".downloading"]:

                        if base_name.lower().endswith(ext):

                            base_name = base_name[:-len(ext)]

                            break



                    try:

                        stat = entry.stat()

                        curr_size = stat.st_size

                    except Exception:

                        curr_size = 0



                    prev_size = self._dl_history_map.get(file_path, curr_size)

                    prev_time = self._dl_time_map.get(file_path, now - 0.4)

                    dt = max(0.15, now - prev_time)

                    speed_bps = max(0.0, (curr_size - prev_size) / dt)



                    self._dl_history_map[file_path] = curr_size

                    self._dl_time_map[file_path] = now



                    # Check real-time browser download metadata (total size and target filename)

                    meta = self._browser_dl_meta.get(entry.name.lower()) or self._browser_dl_meta.get(base_name.lower())

                    if (not meta or not meta.get("target_path")) and base_name.lower().startswith("unconfirmed"):

                        for cand in getattr(self, "_browser_dl_active_list", []):

                            t_p = cand.get("target_path", "")

                            if t_p and not os.path.basename(t_p).lower().startswith("unconfirmed"):

                                meta = cand

                                break



                    total_bytes = meta.get("total_bytes", 0) if meta else 0



                    if meta and meta.get("target_path") and not os.path.basename(meta["target_path"]).lower().startswith("unconfirmed"):

                        display_title = os.path.basename(meta["target_path"])

                    elif base_name.lower().startswith("unconfirmed"):

                        display_title = self._resolve_unconfirmed_file(file_path, base_name)

                    else:

                        display_title = base_name



                    display_title = format_download_filename(display_title, max_chars=22)



                    # Calculate real-time percentage matching actual downloading progress

                    if total_bytes > 0:

                        real_progress = max(1.0, min(99.0, (curr_size / float(total_bytes)) * 100.0))

                    else:

                        # Fallback smooth progression while receiving bytes

                        old_prog = active_progress.get(act_id, 25.0)

                        real_progress = min(96.0, old_prog + 1.2) if speed_bps > 0 else old_prog



                    if speed_bps >= 1024 * 1024:

                        speed_str = f"{speed_bps / (1024 * 1024):.1f} MB/s"

                    elif speed_bps >= 1024:

                        speed_str = f"{speed_bps / 1024:.0f} KB/s"

                    else:

                        speed_str = ""



                    if curr_size >= 1024 * 1024 * 1024:

                        size_str = f"{curr_size / (1024 * 1024 * 1024):.2f} GB"

                    elif curr_size >= 1024 * 1024:

                        size_str = f"{curr_size / (1024 * 1024):.1f} MB"

                    else:

                        size_str = f"{curr_size / 1024:.0f} KB"



                    if total_bytes >= 1024 * 1024 * 1024:

                        total_str = f"{total_bytes / (1024 * 1024 * 1024):.2f} GB"

                    elif total_bytes >= 1024 * 1024:

                        total_str = f"{total_bytes / (1024 * 1024):.1f} MB"

                    elif total_bytes > 0:

                        total_str = f"{total_bytes / 1024:.0f} KB"

                    else:

                        total_str = ""



                    if total_str:

                        subtitle = f"{size_str} of {total_str}"

                    else:

                        subtitle = f"{size_str} downloaded"

                    if speed_str:

                        subtitle += f" • {speed_str}"



                    final_dest = meta["target_path"] if (meta and meta.get("target_path")) else str(dl_dir / display_title)

                    updates.append({

                        "activity_id": act_id,

                        "title": display_title,

                        "progress": real_progress,

                        "subtitle": subtitle,

                        "speed_str": speed_str,

                        "total_bytes": total_bytes,

                        "downloaded_bytes": curr_size,

                        "target_path": final_dest,

                    })



            self._download_scan_completed.emit({

                "ok": True,

                "found": found_dl_keys,

                "updates": updates,

            })

        except Exception:

            self._download_scan_completed.emit({"ok": False})



    @safe_slot

    def _apply_download_scan(self, result: dict):

        """Apply worker results on the Qt thread so activity state stays thread-safe."""

        self._dl_scan_in_flight = False

        if not result or not result.get("ok"):

            return



        for update in result.get("updates", []):

            act_id = update["activity_id"]

            if act_id not in self._activities:

                self.start_activity(

                    activity_id=act_id,

                    title=update["title"],

                    progress=update["progress"],

                    subtitle=update["subtitle"],

                    activity_type="download",

                    icon_type="download",

                    speed_str=update["speed_str"],

                    total_bytes=update["total_bytes"],

                    downloaded_bytes=update["downloaded_bytes"],

                    target_path=update["target_path"],

                )

            else:

                self.update_activity(

                    activity_id=act_id,

                    progress=update["progress"],

                    subtitle=update["subtitle"],

                    speed_str=update["speed_str"],

                    total_bytes=update["total_bytes"],

                    downloaded_bytes=update["downloaded_bytes"],

                )



        found_dl_keys = result.get("found", set())

        disappeared = [

            aid for aid in list(self._activities.keys())

            if aid.startswith("dl_") and aid not in found_dl_keys

        ]

        for aid in disappeared:

            act = self._activities.get(aid)

            if act is not None:

                self.finish_activity(

                    aid,

                    status="completed",

                    message="Download Completed",

                    target_path=act.target_path,

                )



    def demo_install_blender(self):

        """Simulates: Installing Blender — 72% smoothly transitioning into 100% (Completed)"""

        act_id = "demo_install_blender"

        self.start_activity(

            activity_id=act_id,

            title="Installing Blender",

            progress=35.0,

            subtitle="35% • 1.2 GB • 45s remaining",

            activity_type="install",

            icon_type="blue_sphere",

            speed_str="45 MB/s",

            is_demo=True

        )



        steps = [

            (48.0, "48% • Extracting assets", 400),

            (62.0, "62% • Configuring modules", 900),

            (72.0, "72% • Installing Blender 4.2", 1400),

            (86.0, "86% • Registering extensions", 2000),

            (95.0, "95% • Finishing installation", 2600),

            (100.0, "Installed Blender — Ready", 3200),

        ]



        step_idx = 0

        def _run_next_step():

            nonlocal step_idx

            if step_idx < len(steps):

                prog, sub, _ = steps[step_idx]

                if prog >= 100.0:

                    self.finish_activity(act_id, status="completed", message=sub)

                else:

                    self.update_activity(act_id, progress=prog, subtitle=sub, speed_str="38 MB/s")

                    step_idx += 1

                    if step_idx < len(steps):

                        delay = steps[step_idx][2] - steps[step_idx - 1][2]

                        QTimer.singleShot(delay, _run_next_step)



        QTimer.singleShot(400, _run_next_step)



    def demo_multi_downloads(self):

        """Simulates 2 simultaneous downloads merging into one progress ring"""

        self.start_activity(

            activity_id="demo_dl_1",

            title="Blender-4.2-Setup.exe",

            progress=40.0,

            subtitle="40% • 312 MB • 14.2 MB/s",

            activity_type="download",

            icon_type="blue_sphere",

            speed_str="14.2 MB/s",

            is_demo=True

        )



        self.start_activity(

            activity_id="demo_dl_2",

            title="VSCode-x64-1.92.exe",

            progress=75.0,

            subtitle="75% • 88 MB • 8.6 MB/s",

            activity_type="download",

            icon_type="package",

            speed_str="8.6 MB/s",

            is_demo=True

        )



        steps = [

            (55.0, 85.0, 800),

            (72.0, 95.0, 1600),

            (88.0, 100.0, 2400),

            (100.0, 100.0, 3200),

        ]



        s_idx = 0

        def _step_multi():

            nonlocal s_idx

            if s_idx < len(steps):

                p1, p2, _ = steps[s_idx]

                if p1 >= 100.0:

                    self.finish_activity("demo_dl_1", status="completed", message="Blender-4.2-Setup.exe • Done")

                else:

                    self.update_activity("demo_dl_1", progress=p1, subtitle=f"{int(p1)}% • 14.2 MB/s")



                if p2 >= 100.0:

                    self.finish_activity("demo_dl_2", status="completed", message="VSCode-x64-1.92.exe • Done")

                else:

                    self.update_activity("demo_dl_2", progress=p2, subtitle=f"{int(p2)}% • 8.6 MB/s")



                s_idx += 1

                if s_idx < len(steps):

                    QTimer.singleShot(800, _step_multi)



        QTimer.singleShot(800, _step_multi)





class DynamicIslandMonitor(QObject):

    """

    High-efficiency Windows event monitor that detects system volume,

    mute toggles, power/battery transitions, keyboard lock keys,

    clipboard copy/paste actions, Rook shortcuts, active countdown timers,

    and background downloads/installations.

    """

    _instance = None



    @classmethod

    def get_instance(cls, settings=None):

        return cls._instance



    volume_changed = Signal(int)              # (volume_pct)

    mute_changed = Signal(bool)               # (is_muted)

    brightness_changed = Signal(int)         # (brightness_pct)

    battery_changed = Signal(dict)            # dict(has_battery, plugged_in, is_charging, percent)

    lock_key_changed = Signal(str, bool)      # ("caps_lock"|"num_lock"|"scroll_lock", is_on)

    clipboard_event = Signal(str, str, int)   # (action: "copied"|"pasted", preview_text, char_count)

    rook_event = Signal(str, str)             # (action_name, shortcut_key)

    timer_tick = Signal(str, int, bool)       # (label, seconds_value, is_stopwatch)

    notification_event = Signal(str, str, object, str)  # (title, message, app_icon_pixmap_or_none, primary_id)

    activities_updated = Signal(dict)         # (merged_activity_state)

    reminder_event = Signal(dict)             # (reminder_dict)

    internet_changed = Signal(bool)           # (is_connected)

    bluetooth_changed = Signal(str, str)      # ("connected"|"disconnected", device_name)



    _APP_ICON_CACHE: Dict[str, Optional[QPixmap]] = {}



    @classmethod

    def _store_app_icon_cache(cls, key: str, pix: Optional[QPixmap]):

        if not key:

            return

        try:

            from odd_tier import TierManager

            limit = TierManager.get_instance().icon_cache_limit

        except Exception:

            limit = 120

        if len(cls._APP_ICON_CACHE) >= limit:

            to_drop = list(cls._APP_ICON_CACHE.keys())[: max(1, limit // 4)]

            for k in to_drop:

                cls._APP_ICON_CACHE.pop(k, None)

        cls._APP_ICON_CACHE[key] = pix



    def __init__(self, settings: dict):

        super().__init__()

        DynamicIslandMonitor._instance = self

        self.settings = settings

        self._last_vol = -1

        self._last_mute = None

        self._last_bright = -1

        self._last_power = {}

        self._last_caps = None

        self._last_num = None

        self._last_scroll = None

        self._last_audio_retry_time = 0

        self._active_timers: Dict[str, Any] = {}



        # Internet & Bluetooth tracking

        self._last_internet_state: Optional[bool] = None

        self._last_net_poll_time = 0.0

        self._last_bluetooth_devices: Optional[set] = None

        self._last_bt_poll_time = 0.0

        self._bt_check_in_progress = False

        self._bt_absence_counts: Dict[str, int] = {}

        self._bt_last_emitted_event: Dict[str, Tuple[str, float]] = {}



        # Initialize lock key baseline states so startup doesn't false-trigger

        try:

            self._last_caps = bool(ctypes.windll.user32.GetKeyState(0x14) & 1)

            self._last_num = bool(ctypes.windll.user32.GetKeyState(0x90) & 1)

            self._last_scroll = bool(ctypes.windll.user32.GetKeyState(0x91) & 1)

        except Exception:

            pass



        # Windows System & App Notification Scanner (wpndatabase.db)

        self._last_notification_id = 0

        self._last_notification_check = 0.0

        self._init_notification_scanner()



        # Activity & Download Manager instance

        self.activity_mgr = ActivityManager.get_instance(self.settings)

        self.activity_mgr.activities_changed.connect(self._on_activities_changed)



        # Reminder & Wellness Manager instances

        from odd_reminder import ReminderManager, WaterReminderManager

        from odd_wellness import WellnessManager

        self.reminder_mgr = ReminderManager.get_instance(self.settings)

        self.reminder_mgr.reminder_triggered.connect(self._on_reminder_triggered)

        self.water_mgr = WaterReminderManager.get_instance(self.settings)

        self.water_mgr.water_triggered.connect(self._on_reminder_triggered)

        self.wellness_mgr = WellnessManager.get_instance(self.settings)

        self.wellness_mgr.wellness_triggered.connect(self._on_reminder_triggered)



        # Dedicated COM worker integration for volume and brightness

        self._vol_endpoint = None

        try:

            from odd_com import ComWorker

            cw = ComWorker.get_instance()

            cw.audio_state_changed.connect(self._on_com_audio_changed)

            cw.brightness_state_changed.connect(self._on_com_brightness_changed)

            self._last_vol = cw.last_volume

            self._last_mute = cw.last_mute

            self._last_bright = cw.last_brightness

        except Exception:

            pass



        # Polling timer (runs at 220ms interval for snappy HUD triggers without CPU overhead)

        self._poll_timer = QTimer(self)

        self._poll_timer.setInterval(220)

        self._poll_timer.timeout.connect(self._poll_system_events)



    def _on_com_audio_changed(self, vol_pct: int, is_muted: bool, *args):

        if self._last_mute is not None and is_muted != self._last_mute:

            self.mute_changed.emit(is_muted)

        if self._last_vol != -1 and vol_pct != self._last_vol:

            self.volume_changed.emit(vol_pct)

        self._last_vol = vol_pct

        self._last_mute = is_muted



    def _on_com_brightness_changed(self, b: int):

        if hasattr(self, '_last_bright') and self._last_bright != -1 and b != self._last_bright:

            self.brightness_changed.emit(b)

        self._last_bright = b



    def _on_activities_changed(self):

        state = self.activity_mgr.get_merged_state()

        self.activities_updated.emit(state)



    def _on_reminder_triggered(self, rem_dict: dict):

        self.reminder_event.emit(rem_dict)



    def start(self):

        self._poll_timer.start()



    def stop(self):

        self._poll_timer.stop()



    def update_settings(self, new_settings: dict):

        self.settings = new_settings

        if hasattr(self, 'water_mgr') and self.water_mgr:

            self.water_mgr.update_settings(new_settings)

        if hasattr(self, 'wellness_mgr') and self.wellness_mgr:

            self.wellness_mgr.update_settings(new_settings)



    def _init_audio_endpoint(self):

        """Deprecated: Audio endpoints and COM interfaces are managed asynchronously by ComWorker."""

        pass



    def _init_notification_scanner(self):

        """Initializes notification tracker with the latest existing notification ID"""

        self._last_notification_id = 0

        try:

            import sqlite3

            from pathlib import Path

            local_app = os.environ.get('LOCALAPPDATA', '')

            db_path = Path(local_app) / 'Microsoft' / 'Windows' / 'Notifications' / 'wpndatabase.db'

            if db_path.exists():

                conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=0.1)

                cursor = conn.cursor()

                cursor.execute("SELECT MAX(Id) FROM Notification WHERE Type='toast'")

                row = cursor.fetchone()

                if row and row[0] is not None:

                    self._last_notification_id = int(row[0])

                conn.close()

        except Exception:

            pass



    @classmethod

    def _format_rounded_icon(cls, pix: QPixmap, size: int = 20) -> Optional[QPixmap]:

        if pix is None or pix.isNull():

            return None

        out = QPixmap(size, size)

        out.fill(Qt.GlobalColor.transparent)

        p = QPainter(out)

        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        clip = QPainterPath()

        clip.addRoundedRect(0.0, 0.0, float(size), float(size), 5.0, 5.0)

        p.setClipPath(clip)

        scaled = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)

        p.drawPixmap(0, 0, scaled)

        p.end()

        return out



    @classmethod

    def resolve_notification_app_icon(

        cls,

        primary_id: str = "",

        handler_image_path: str = "",

        xml_image_srcs: Optional[list] = None,

        title: str = "",

    ) -> Optional[QPixmap]:

        """

        Resolves the notification's actual application icon (WhatsApp, Discord, Spotify,

        Chrome, Edge, Slack, Telegram, Teams, VS Code, etc.) from:

        1. Toast XML <image placement="appLogoOverride" src="..."/> or <image src="..."/>

        2. NotificationHandler.ImagePath from wpndatabase.db

        3. Installed application shortcut / executable matching PrimaryId or notification title

        Returns a 20x20 rounded QPixmap, or None if no application icon is available.

        """

        import urllib.parse

        from pathlib import Path

        from PySide6.QtWidgets import QFileIconProvider

        from PySide6.QtCore import QFileInfo



        cache_key = f"{primary_id}|{handler_image_path}|{(xml_image_srcs or [''])[0]}|{title}".strip().lower()

        if cache_key and cache_key in cls._APP_ICON_CACHE:

            return cls._APP_ICON_CACHE[cache_key]



        candidates = []

        if xml_image_srcs:

            candidates.extend(xml_image_srcs)

        if handler_image_path:

            candidates.append(handler_image_path)



        for raw_src in candidates:

            if not raw_src:

                continue

            s = str(raw_src).strip()

            if s.startswith("file:///"):

                s = urllib.parse.unquote(s[8:].replace("/", "\\"))

            elif s.startswith("file://"):

                s = urllib.parse.unquote(s[7:].replace("/", "\\"))

            s = os.path.expandvars(s)

            if os.path.isfile(s):

                pix = QPixmap(s)

                if not pix.isNull():

                    rounded = cls._format_rounded_icon(pix, 20)

                    if cache_key:

                        cls._store_app_icon_cache(cache_key, rounded)

                    return rounded



        # Match known application identifiers from PrimaryId or notification title

        haystack = f"{primary_id} {title}".lower()

        local_app = os.environ.get("LOCALAPPDATA", "")

        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")

        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        appdata = os.environ.get("APPDATA", "")



        known_app_paths = [

            ("whatsapp", [

                os.path.join(local_app, "WhatsApp", "WhatsApp.exe"),

            ]),

            ("discord", [

                os.path.join(local_app, "Discord", "app.ico"),

                os.path.join(local_app, "Discord", "Update.exe"),

            ]),

            ("spotify", [

                os.path.join(appdata, "Spotify", "Spotify.exe"),

                os.path.join(local_app, "Microsoft", "WindowsApps", "Spotify.exe"),

            ]),

            ("telegram", [

                os.path.join(appdata, "Telegram Desktop", "Telegram.exe"),

            ]),

            ("slack", [

                os.path.join(local_app, "slack", "slack.exe"),

                os.path.join(local_app, "slack", "app.ico"),

            ]),

            ("teams", [

                os.path.join(local_app, "Microsoft", "Teams", "current", "Teams.exe"),

                os.path.join(local_app, "Microsoft", "WindowsApps", "ms-teams.exe"),

            ]),

            ("code", [

                os.path.join(local_app, "Programs", "Microsoft VS Code", "Code.exe"),

                os.path.join(prog_files, "Microsoft VS Code", "Code.exe"),

            ]),

            ("chrome", [

                os.path.join(prog_files, "Google", "Chrome", "Application", "chrome.exe"),

                os.path.join(prog_x86, "Google", "Chrome", "Application", "chrome.exe"),

            ]),

            ("msedge", [

                os.path.join(prog_x86, "Microsoft", "Edge", "Application", "msedge.exe"),

                os.path.join(prog_files, "Microsoft", "Edge", "Application", "msedge.exe"),

            ]),

            ("microsoft edge", [

                os.path.join(prog_x86, "Microsoft", "Edge", "Application", "msedge.exe"),

                os.path.join(prog_files, "Microsoft", "Edge", "Application", "msedge.exe"),

            ]),

            ("brave", [

                os.path.join(prog_files, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),

                os.path.join(local_app, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),

            ]),

            ("firefox", [

                os.path.join(prog_files, "Mozilla Firefox", "firefox.exe"),

            ]),

            ("steam", [

                os.path.join(prog_x86, "Steam", "steam.exe"),

            ]),

            ("outlook", [

                os.path.join(prog_files, "Microsoft Office", "root", "Office16", "OUTLOOK.EXE"),

            ]),

        ]



        import re

        provider = QFileIconProvider()

        for keyword, paths in known_app_paths:

            if re.search(r'\b' + re.escape(keyword) + r'\b', haystack):

                for p in paths:

                    if p and os.path.exists(p):

                        if p.lower().endswith((".png", ".ico", ".jpg", ".jpeg", ".bmp")):

                            pix = QPixmap(p)

                            if not pix.isNull():

                                rounded = cls._format_rounded_icon(pix, 20)

                                if cache_key:

                                    cls._store_app_icon_cache(cache_key, rounded)

                                return rounded

                        icon = provider.icon(QFileInfo(p))

                        if not icon.isNull():

                            pix = icon.pixmap(32, 32)

                            if not pix.isNull():

                                rounded = cls._format_rounded_icon(pix, 20)

                                if cache_key:

                                    cls._store_app_icon_cache(cache_key, rounded)

                                return rounded



        # Also check Start Menu .lnk shortcuts matching PrimaryId or title tokens

        start_dirs = [

            os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"),

            os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Microsoft", "Windows", "Start Menu", "Programs"),

        ]

        search_terms = [t for t in [primary_id.split("!")[-1].split(".")[-1].strip().lower(), title.strip().lower()] if len(t) >= 3]

        if search_terms:

            for sdir in start_dirs:

                if not os.path.isdir(sdir):

                    continue

                try:

                    for root_dir, _, files in os.walk(sdir):

                        for fname in files:

                            if not fname.lower().endswith(".lnk"):

                                continue

                            stem = fname[:-4].lower()

                            if any(term in stem or stem in term for term in search_terms):

                                full_lnk = os.path.join(root_dir, fname)

                                icon = provider.icon(QFileInfo(full_lnk))

                                if not icon.isNull():

                                    pix = icon.pixmap(32, 32)

                                    if not pix.isNull():

                                        rounded = cls._format_rounded_icon(pix, 20)

                                        if cache_key:

                                            cls._store_app_icon_cache(cache_key, rounded)

                                        return rounded

                except Exception:

                    pass



        return None



    def _poll_windows_notifications(self):

        """Polls for newly arrived Windows toast notifications from wpndatabase.db"""

        if not self.settings.get("island_show_system_notifications", True) or self.settings.get("dnd_enabled", False):

            return

        now = time.time()

        if now - getattr(self, '_last_notification_check', 0.0) < 1.2:

            return

        self._last_notification_check = now



        try:

            import sqlite3

            import xml.etree.ElementTree as ET

            from pathlib import Path

            local_app = os.environ.get('LOCALAPPDATA', '')

            db_path = Path(local_app) / 'Microsoft' / 'Windows' / 'Notifications' / 'wpndatabase.db'

            if not db_path.exists():

                return



            conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=0.1)

            cursor = conn.cursor()

            try:

                cursor.execute(

                    'SELECT n.Id, n.Payload, h.PrimaryId '

                    'FROM Notification n LEFT JOIN NotificationHandler h ON n.HandlerId = h.RecordId '

                    'WHERE n.Id > ? AND n.Type = "toast" ORDER BY n.Id ASC LIMIT 5',

                    (self._last_notification_id,)

                )

                rows = cursor.fetchall()

            except Exception:

                cursor.execute(

                    'SELECT Id, Payload, "" FROM Notification WHERE Id > ? AND Type = "toast" ORDER BY Id ASC LIMIT 5',

                    (self._last_notification_id,)

                )

                rows = cursor.fetchall()

            conn.close()



            for row in rows:

                nid = int(row[0])

                if nid > self._last_notification_id:

                    self._last_notification_id = nid

                raw = row[1]

                primary_id = str(row[2] or "") if len(row) > 2 else ""

                handler_img = str(row[3] or "") if len(row) > 3 else ""

                if not raw:

                    continue

                try:

                    payload = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8")

                    root = ET.fromstring(payload)

                    texts = []

                    app_logo_srcs = []

                    other_img_srcs = []

                    for element in root.iter():

                        local_tag = str(element.tag).rsplit('}', 1)[-1].lower()

                        if local_tag == 'text':

                            value = " ".join(part.strip() for part in element.itertext() if part and part.strip())

                            if value:

                                texts.append(value)

                        elif local_tag == 'image':

                            src = (element.attrib.get('src') or '').strip()

                            placement = (element.attrib.get('placement') or '').strip().lower()

                            if src:

                                if 'applogo' in placement or 'icon' in placement:

                                    app_logo_srcs.append(src)

                                else:

                                    other_img_srcs.append(src)

                    if texts:

                        title = texts[0]

                        msg = "\n".join(texts[1:])

                        icon_pix = self.resolve_notification_app_icon(

                            primary_id=primary_id,

                            handler_image_path=handler_img,

                            xml_image_srcs=app_logo_srcs + other_img_srcs,

                            title=title,

                        )

                        self.trigger_notification(title, msg, app_icon=icon_pix, primary_id=primary_id)

                except Exception:

                    pass

        except Exception:

            pass



    def start_stopwatch(self, label: str = "Stopwatch") -> str:

        """Starts a count-up stopwatch ticking in the Dynamic Island"""

        timer_id = f"stopwatch_{int(time.time() * 1000)}"

        self._active_timers[timer_id] = {

            "label": label,

            "start_time": time.time(),

            "type": "stopwatch",

            "is_running": True

        }

        return timer_id



    def trigger_timer(self, label: str, duration_sec: int, is_stopwatch: bool = False) -> str:

        """Register an active countdown timer or stopwatch for the dynamic island ticker"""

        timer_id = f"timer_{int(time.time() * 1000)}"

        if is_stopwatch:

            self._active_timers[timer_id] = {

                "label": label,

                "start_time": time.time(),

                "type": "stopwatch",

                "is_running": True

            }

        else:

            self._active_timers[timer_id] = {

                "label": label,

                "start_time": time.time(),

                "end_time": time.time() + duration_sec,

                "total_sec": duration_sec,

                "type": "timer",

                "is_running": True

            }

        return timer_id



    def stop_timer(self, timer_id: Optional[str] = None):

        """Stops an active stopwatch or countdown timer"""

        if timer_id:

            self._active_timers.pop(timer_id, None)

        else:

            self._active_timers.clear()



    def get_active_timers(self) -> Dict[str, Any]:

        """Returns all currently active timers and stopwatches"""

        return dict(self._active_timers)



    def has_active_timer(self) -> bool:

        return bool(self._active_timers)



    def trigger_clipboard_action(self, action: str, text_preview: str, char_count: int):

        """Trigger instant fast copy/paste animation in the Dynamic Island"""

        self.clipboard_event.emit(action, text_preview, char_count)



    def trigger_rook_shortcut(self, action_name: str, shortcut_key: str):

        """Trigger visual Rook shortcut indication animation in the Dynamic Island"""

        self.rook_event.emit(action_name, shortcut_key)



    def trigger_notification(self, title: str, message: str, app_icon: Any = None, primary_id: str = ""):

        """Trigger non-intrusive drop-down notification in the Bezel HUD"""

        if app_icon is None:

            app_icon = self.resolve_notification_app_icon(title=title, primary_id=primary_id)

        self.notification_event.emit(title, message, app_icon, str(primary_id or ""))



    @safe_slot

    def _poll_system_events(self):

        # 1. Volume & Brightness are event-driven via ComWorker signals (_on_com_audio_changed, _on_com_brightness_changed)



        # 2. Battery & Power Status Detection

        if self.settings.get("island_show_battery_hud", True):

            try:

                status = SYSTEM_POWER_STATUS()

                if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):

                    ac_status = status.ACLineStatus

                    battery_pct = status.BatteryLifePercent

                    is_charging = (status.BatteryFlag & 8) != 0

                    has_battery = (status.BatteryFlag != 128) and (status.BatteryFlag != 255) and (battery_pct <= 100)



                    curr_power = {

                        "has_battery": has_battery,

                        "plugged_in": ac_status == 1,

                        "is_charging": is_charging,

                        "percent": battery_pct if battery_pct <= 100 else 100

                    }



                    if self._last_power:

                        if (
                            curr_power["plugged_in"] != self._last_power.get("plugged_in") or
                            curr_power.get("is_charging") != self._last_power.get("is_charging") or
                            (curr_power["has_battery"] and abs(curr_power["percent"] - self._last_power.get("percent", 0)) >= 10)
                        ):

                            self.battery_changed.emit(curr_power)

                    self._last_power = curr_power

            except Exception:

                pass



        # 3. Lock Keys Detection (Caps Lock / Num Lock / Scroll Lock)

        if self.settings.get("island_show_caps_lock_hud", True):

            try:

                caps_on = bool(ctypes.windll.user32.GetKeyState(0x14) & 1)

                if self._last_caps is not None and caps_on != self._last_caps:

                    self.lock_key_changed.emit("caps_lock", caps_on)

                self._last_caps = caps_on



                num_on = bool(ctypes.windll.user32.GetKeyState(0x90) & 1)

                if self._last_num is not None and num_on != self._last_num:

                    self.lock_key_changed.emit("num_lock", num_on)

                self._last_num = num_on



                scroll_on = bool(ctypes.windll.user32.GetKeyState(0x91) & 1)

                if self._last_scroll is not None and scroll_on != self._last_scroll:

                    self.lock_key_changed.emit("scroll_lock", scroll_on)

                self._last_scroll = scroll_on

            except Exception:

                pass



        # 4. Active Countdown Timers & Count-Up Stopwatch

        if self._active_timers:

            now = time.time()

            to_remove = []

            for tid, tinfo in list(self._active_timers.items()):

                t_type = tinfo.get("type", "timer")

                if t_type == "stopwatch":

                    start_t = tinfo.get("start_time", now)

                    elapsed = max(0, int(now - start_t))

                    hrs = elapsed // 3600

                    mins = (elapsed % 3600) // 60

                    secs = elapsed % 60

                    lbl = f"{hrs}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"

                    if self.settings.get("island_show_timer_ticker", True):

                        self.timer_tick.emit(lbl, elapsed, True)

                else:

                    rem = int(tinfo.get("end_time", now) - now)

                    if rem > 0:

                        hrs = rem // 3600

                        mins = (rem % 3600) // 60

                        secs = rem % 60

                        lbl = f"{hrs}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"

                        if self.settings.get("island_show_timer_ticker", True):

                            self.timer_tick.emit(lbl, rem, False)

                    else:

                        to_remove.append(tid)

                        lbl = tinfo.get("label", "Timer")

                        self.trigger_notification(f"{lbl} Finished!", "Countdown completed")

                        try:

                            import odd_sound

                            odd_sound.play_reminder(self.settings)

                        except Exception:

                            pass

            for tid in to_remove:

                self._active_timers.pop(tid, None)



        # 5. Windows System & App Notifications (wpndatabase.db)

        self._poll_windows_notifications()



        # 6. Internet Connectivity Detection (checked every 2.5s)

        now_t = time.time()

        if now_t - getattr(self, '_last_net_poll_time', 0.0) >= 2.5:

            self._last_net_poll_time = now_t

            try:

                flags = ctypes.c_ulong()

                is_net_connected = bool(ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0))

                if self._last_internet_state is not None:

                    if is_net_connected != self._last_internet_state:

                        self.internet_changed.emit(is_net_connected)

                self._last_internet_state = is_net_connected

            except Exception:

                pass



        # 7. Connected Bluetooth Devices Detection (polled with confirmation hysteresis)

        if now_t - getattr(self, '_last_bt_poll_time', 0.0) >= 5.0 and not getattr(self, '_bt_check_in_progress', False):

            self._last_bt_poll_time = now_t

            self._bt_check_in_progress = True



            def _async_bt_check():

                try:

                    from odd_android_mirror import get_connected_bluetooth_devices

                    current_devices = set(get_connected_bluetooth_devices())

                    now = time.time()



                    # On initial baseline poll, quietly record already-connected devices without emitting alerts

                    if self._last_bluetooth_devices is None:

                        self._last_bluetooth_devices = current_devices

                        self._bt_absence_counts = {}

                        return



                    # 1. Check for genuine new connected devices

                    new_devs = current_devices - self._last_bluetooth_devices

                    for d in list(new_devs):

                        self._bt_absence_counts[d] = 0

                        last_ev, last_t = self._bt_last_emitted_event.get(d, (None, 0.0))

                        # Prevent duplicate alerts or flapping within 30 seconds for the same device

                        if last_ev == "connected" and (now - last_t) < 30.0:

                            continue

                        if last_ev == "disconnected" and (now - last_t) < 12.0:

                            # Reconnected immediately after a transient drop: quietly update state and suppress flapping

                            self._last_bluetooth_devices.add(d)

                            self._bt_last_emitted_event[d] = ("connected", now)

                            continue

                        self._last_bluetooth_devices.add(d)

                        self._bt_last_emitted_event[d] = ("connected", now)

                        self.bluetooth_changed.emit("connected", d)



                    # 2. Check for disconnected devices with hysteresis (must be missing for 3 consecutive polls = ~15s)

                    potentially_lost = self._last_bluetooth_devices - current_devices

                    for d in list(potentially_lost):

                        cnt = self._bt_absence_counts.get(d, 0) + 1

                        self._bt_absence_counts[d] = cnt

                        if cnt >= 3:

                            # Confirmed absent for 3 consecutive polls (>15 seconds)

                            self._last_bluetooth_devices.discard(d)

                            self._bt_absence_counts.pop(d, None)

                            last_ev, last_t = self._bt_last_emitted_event.get(d, (None, 0.0))

                            if last_ev != "disconnected" or (now - last_t) >= 20.0:

                                self._bt_last_emitted_event[d] = ("disconnected", now)

                                self.bluetooth_changed.emit("disconnected", d)



                    # Reset absence counter for any device currently present

                    for d in current_devices:

                        if d in self._bt_absence_counts:

                            self._bt_absence_counts[d] = 0

                except Exception:

                    pass

                finally:

                    self._bt_check_in_progress = False



            threading.Thread(target=_async_bt_check, daemon=True).start()





_SYSTEM_STATUS_TYPES = {"lock_key", "caps_lock", "num_lock", "scroll_lock", "mute"}

_STATUS_PILL_HEIGHT = 40

_STATUS_PILL_SHADOW_PAD = 6

_STATUS_PILL_PAD_X = 15

_STATUS_PILL_SPACING = 8





def _status_pill_font() -> QFont:

    font = QFont("Segoe UI Variable Text")

    font.setPixelSize(14)

    font.setWeight(QFont.Weight.Medium)

    return font





def _status_pill_text_and_icon_w(hud_type: str, data: dict) -> Tuple[str, int]:

    if hud_type in ("lock_key", "caps_lock", "num_lock", "scroll_lock"):

        key_name = data.get("key_name", hud_type)

        is_on = bool(data.get("is_on", False))

        state_txt = "On" if is_on else "Off"

        if key_name == "num_lock":

            return f"Num Lock {state_txt}", 16

        elif key_name == "scroll_lock":

            return f"Scroll Lock {state_txt}", 16

        return f"Caps Lock {state_txt}", 16

    elif hud_type == "mute":

        is_muted = bool(data.get("is_muted", False))

        return ("Audio Mute" if is_muted else "Audio Unmute"), 18

    elif hud_type == "battery":

        pct = max(0, min(100, int(data.get("percent", 100))))

        is_powered = bool(data.get("is_charging", False) or data.get("charging", False) or data.get("plugged_in", False))

        if is_powered:

            status_str = f"Charged ({pct}%) • Safe" if pct >= 80 else f"Charging • {pct}%"

        else:

            if pct <= 15:

                status_str = f"Critical Battery • {pct}%"

            elif pct <= 30:

                status_str = f"Low Battery • {pct}%"

            else:

                status_str = f"Battery • {pct}%"

        return status_str, 22

    return "", 18







def measure_system_status_pill(hud_type: str, data: dict) -> Tuple[int, int]:

    """Calculates dynamic content-fitted (window_width, window_height) for system-status capsules."""

    label, icon_w = _status_pill_text_and_icon_w(hud_type, data)

    metrics = QFontMetrics(_status_pill_font())

    text_w = metrics.horizontalAdvance(label)

    pill_w = _STATUS_PILL_PAD_X + icon_w + _STATUS_PILL_SPACING + text_w + _STATUS_PILL_PAD_X

    win_w = pill_w + _STATUS_PILL_SHADOW_PAD * 2

    win_h = _STATUS_PILL_HEIGHT + _STATUS_PILL_SHADOW_PAD * 2

    return (win_w, win_h)





def paint_system_status_pill_surface(

    painter: QPainter,

    outer_rect: QRect,

    opacity: float = 1.0,

    theme: str = "dark",

    hover_val: float = 0.0,

    press_val: float = 0.0,

) -> QRectF:

    """

    ODD 2.0 Primary Acrylic System-Status Capsule Surface

    - 65-78% dark charcoal acrylic surface opacity (#101012 @ ~70% alpha)

    - Fine translucent white perimeter border (0.75-1.0px)

    - Subtle top specular hairline inner highlight

    - Soft ambient multi-step drop shadow

    - Crisp vector icons and typography

    """

    pad = float(_STATUS_PILL_SHADOW_PAD)

    pill_rect = QRectF(outer_rect).adjusted(pad, pad, -pad, -pad)

    

    pr = max(0.0, min(1.0, float(press_val)))

    if pr > 0.01:

        comp = 0.5 * pr

        pill_rect = pill_rect.adjusted(comp, comp, -comp, -comp)



    radius = pill_rect.height() / 2.0

    op = max(0.0, min(1.0, float(opacity)))

    hv = max(0.0, min(1.0, float(hover_val)))



    painter.save()

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)



    # 1. Soft ambient shadow steps beneath the capsule

    for spread, y_off, alpha in ((6.0, 2.2, 8), (3.8, 1.4, 16), (1.8, 0.8, 26)):

        s_rect = pill_rect.adjusted(-spread, -spread + y_off, spread, spread + y_off)

        s_rad = s_rect.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QColor(0, 0, 0, int(alpha * op)))

        painter.drawRoundedRect(s_rect, s_rad, s_rad)



    # 2. Continuous squircle path

    path = QPainterPath()

    path.addRoundedRect(pill_rect, radius, radius)



    # 3. Primary Dark Acrylic Absorption Body (65-78% surface opacity)

    if theme == "light":

        bg_col = QColor(int(240 + 3 * hv), int(240 + 3 * hv), int(245 + 3 * hv), int(180 * op))

        border_col = QColor(0, 0, 0, int((45 + 15 * hv) * op))

        specular_col = QColor(255, 255, 255, int(30 * op))

    elif theme == "oled":

        bg_col = QColor(0, 0, 0, int(230 * op))

        border_col = QColor(255, 255, 255, int((35 + 15 * hv) * op))

        specular_col = QColor(255, 255, 255, int(20 * op))

    else:

        # Pure solid AMOLED black (#080808) with #292929 border
        v = int(8 + 6 * hv)
        bg_col = QColor(v, v, v + 1, 255)
        border_col = QColor(41, 41, 41, 255)
        specular_col = QColor(0, 0, 0, 0)

    painter.fillPath(path, QBrush(bg_col))



    # 4. Subtle Top Inner Specular Highlight (Upper Edge Hairline)

    spec_h = min(2.5, pill_rect.height() * 0.15)

    specular = QLinearGradient(0, pill_rect.top(), 0, pill_rect.top() + spec_h)

    specular.setColorAt(0.0, specular_col)

    specular.setColorAt(0.40, QColor(specular_col.red(), specular_col.green(), specular_col.blue(), int(specular_col.alpha() * 0.35)))

    specular.setColorAt(1.0, QColor(255, 255, 255, 0))

    painter.fillPath(path, QBrush(specular))



    # 5. Fine 0.75-1.0px Perimeter Border

    painter.strokePath(path, QPen(border_col, 0.85))



    painter.restore()

    return pill_rect





def paint_system_status_pill_content(

    painter: QPainter,

    pill_rect: QRectF,

    hud_type: str,

    data: dict,

    anim_dy: float = 0.0,

    mute_t: Optional[float] = None,

):

    """Paints normalized [ ICON ] [ EXISTING STATUS TEXT ] inside `pill_rect`."""

    label, icon_w = _status_pill_text_and_icon_w(hud_type, data)

    pad_x = float(_STATUS_PILL_PAD_X)

    spacing = float(_STATUS_PILL_SPACING)

    cy = pill_rect.center().y()

    text_col = QColor(245, 245, 247)



    # 1. Caps Lock / Num Lock / Scroll Lock

    if hud_type in ("lock_key", "caps_lock", "num_lock", "scroll_lock"):

        is_on = bool(data.get("is_on", False))

        cx = pill_rect.left() + pad_x + icon_w / 2.0

        cy_icon = cy + anim_dy

        icon_col = QColor(245, 245, 247) if is_on else QColor(156, 163, 175)



        painter.setPen(QPen(icon_col, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        painter.setBrush(Qt.BrushStyle.NoBrush)

        arrow_path = QPainterPath()

        if is_on:

            arrow_path.moveTo(cx - 4.2, cy_icon - 0.8)

            arrow_path.lineTo(cx, cy_icon - 5.0)

            arrow_path.lineTo(cx + 4.2, cy_icon - 0.8)

            arrow_path.moveTo(cx, cy_icon - 4.6)

            arrow_path.lineTo(cx, cy_icon + 5.0)

        else:

            arrow_path.moveTo(cx - 4.2, cy_icon + 0.8)

            arrow_path.lineTo(cx, cy_icon + 5.0)

            arrow_path.lineTo(cx + 4.2, cy_icon + 0.8)

            arrow_path.moveTo(cx, cy_icon - 5.0)

            arrow_path.lineTo(cx, cy_icon + 4.6)

        painter.strokePath(arrow_path, painter.pen())



    # 2. Audio Mute / Unmute

    elif hud_type == "mute":

        is_muted = bool(data.get("is_muted", False))

        m_t = (1.0 if is_muted else 0.0) if mute_t is None else max(0.0, min(1.0, float(mute_t)))

        u_t = 1.0 - m_t



        spk_cx = pill_rect.left() + pad_x + 6.5

        spk_cy = cy

        c_val = int(245 * u_t + 165 * m_t)

        spk_color = QColor(c_val, c_val, min(255, c_val + 4))



        spk_horn = QPainterPath()

        spk_horn.moveTo(spk_cx - 5.2, spk_cy - 2.2)

        spk_horn.lineTo(spk_cx - 2.4, spk_cy - 2.2)

        spk_horn.lineTo(spk_cx + 1.6, spk_cy - 5.0)

        spk_horn.lineTo(spk_cx + 1.6, spk_cy + 5.0)

        spk_horn.lineTo(spk_cx - 2.4, spk_cy + 2.2)

        spk_horn.lineTo(spk_cx - 5.2, spk_cy + 2.2)

        spk_horn.closeSubpath()



        painter.setBrush(QBrush(spk_color))

        painter.setPen(QPen(spk_color, 0.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        painter.fillPath(spk_horn, painter.brush())

        painter.strokePath(spk_horn, painter.pen())



        if u_t > 0.05:

            w1_prog = max(0.0, min(1.0, u_t * 1.2))

            w2_prog = max(0.0, min(1.0, (u_t - 0.15) / 0.85))

            painter.setBrush(Qt.BrushStyle.NoBrush)

            if w1_prog > 0.02:

                painter.setPen(QPen(QColor(245, 245, 247, int(235 * w1_prog)), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

                painter.drawArc(QRectF(spk_cx + 2.4, spk_cy - 3.1 * w1_prog, 3.4 * w1_prog, 6.2 * w1_prog), -55 * 16, 110 * 16)

            if w2_prog > 0.02:

                painter.setPen(QPen(QColor(245, 245, 247, int(195 * w2_prog)), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

                painter.drawArc(QRectF(spk_cx + 3.9, spk_cy - 5.2 * w2_prog, 5.4 * w2_prog, 10.4 * w2_prog), -55 * 16, 110 * 16)



        if m_t > 0.05:

            slash_col = QColor(175, 175, 185, int(240 * m_t))

            painter.setPen(QPen(slash_col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

            b1 = max(0.0, min(1.0, m_t * 1.3))

            b2 = max(0.0, min(1.0, (m_t - 0.18) / 0.82))

            x0, y0 = spk_cx + 4.0, spk_cy - 2.6

            x1, y1 = spk_cx + 8.8, spk_cy + 2.6

            if b1 > 0.02:

                painter.drawLine(QPointF(x0, y0), QPointF(x0 + (x1 - x0) * b1, y0 + (y1 - y0) * b1))

            if b2 > 0.02:

                painter.drawLine(QPointF(x1, y0), QPointF(x1 - (x1 - x0) * b2, y0 + (y1 - y0) * b2))



    # 3. Battery & Power Status

    elif hud_type == "battery":

        pct = max(0, min(100, int(data.get("percent", 100))))

        charging = bool(data.get("is_charging", False) or data.get("charging", False))

        plugged = bool(data.get("plugged_in", False))

        is_powered = (charging or plugged)



        bw, bh = 19.5, 11.0

        bx = pill_rect.left() + pad_x

        by = cy - bh / 2.0



        if is_powered:

            outline_col = QColor(16, 185, 129, 220)

            fill_col = QColor(16, 185, 129, 240)

        elif pct <= 15:

            outline_col = QColor(239, 68, 68, 220)

            fill_col = QColor(239, 68, 68, 240)

        elif pct <= 30:

            outline_col = QColor(245, 158, 11, 220)

            fill_col = QColor(245, 158, 11, 240)

        else:

            outline_col = QColor(212, 212, 218, 190)

            fill_col = QColor(245, 245, 247, 235)



        painter.setPen(QPen(outline_col, 1.2))

        painter.setBrush(QBrush(QColor(outline_col.red(), outline_col.green(), outline_col.blue(), 18)))

        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 3.2, 3.2)



        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QBrush(outline_col))

        painter.drawRoundedRect(QRectF(bx + bw + 0.6, by + 3.0, 1.8, bh - 6.0), 0.9, 0.9)



        fill_max_w = bw - 4.0

        cur_fill_w = max(2.5, (pct / 100.0) * fill_max_w)

        painter.setBrush(QBrush(fill_col))

        painter.drawRoundedRect(QRectF(bx + 2.0, by + 2.0, cur_fill_w, bh - 4.0), 1.8, 1.8)



        if is_powered:

            bcx = bx + bw / 2.0

            bolt = QPainterPath()

            bolt.moveTo(bcx + 0.6, cy - 4.2)

            bolt.lineTo(bcx - 2.2, cy + 0.3)

            bolt.lineTo(bcx - 0.2, cy + 0.3)

            bolt.lineTo(bcx - 0.8, cy + 4.2)

            bolt.lineTo(bcx + 2.2, cy - 0.3)

            bolt.lineTo(bcx + 0.2, cy - 0.3)

            bolt.closeSubpath()

            painter.setBrush(QBrush(QColor(12, 14, 18, 240)))

            painter.setPen(QPen(QColor(245, 245, 247), 0.75))

            painter.drawPath(bolt)



    # Status Text

    painter.setFont(_status_pill_font())

    painter.setPen(text_col)

    text_left = int(round(pill_rect.left() + pad_x + icon_w + spacing))

    text_rect = QRect(

        text_left,

        int(round(pill_rect.top())),

        int(round(pill_rect.right() - text_left - pad_x + 4)),

        int(round(pill_rect.height())),

    )

    text_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    # A tiny low-alpha text halo gives compact lock pills a soft blurred entry/exit

    # without a per-widget blur effect or the extra render cost of a filter pass.

    painter.save()

    painter.setOpacity(0.30)

    halo_col = QColor(text_col)

    halo_col.setAlpha(max(1, int(halo_col.alpha() * 0.22)))

    painter.setPen(halo_col)

    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):

        painter.drawText(text_rect.translated(int(dx), int(dy)), text_align, label)

    painter.restore()

    painter.setPen(text_col)

    painter.drawText(text_rect, text_align, label)





def format_elided_notification_message(message: str, font: QFont, max_width: int, max_lines: int = 2) -> str:

    """

    Formats notification message text, wrapping up to max_lines.

    If the text exceeds max_lines, the last line terminates with clean '...' elision.

    """

    if not message:

        return ""

    metrics = QFontMetrics(font)

    raw_lines = [l.strip() for l in message.splitlines() if l.strip()]

    if not raw_lines:

        return ""

    words = " ".join(raw_lines).split()

    if not words:

        return ""



    lines = []

    curr_line = ""

    for idx, w in enumerate(words):

        test_line = f"{curr_line} {w}".strip()

        if metrics.horizontalAdvance(test_line) <= max_width:

            curr_line = test_line

        else:

            if curr_line:

                lines.append(curr_line)

                if len(lines) == max_lines - 1:

                    # Final line: elide remaining text with trailing '...'

                    rem_text = " ".join(words[idx:])

                    elided = metrics.elidedText(rem_text, Qt.TextElideMode.ElideRight, max_width)

                    if elided.endswith("…"):

                        elided = elided[:-1].rstrip() + "..."

                    elif not elided.endswith("..."):

                        elided = elided.rstrip(".") + "..."

                    lines.append(elided)

                    return "\n".join(lines)

                curr_line = w

            else:

                elided = metrics.elidedText(w, Qt.TextElideMode.ElideRight, max_width)

                if elided.endswith("…"):

                    elided = elided[:-1].rstrip() + "..."

                elif not elided.endswith("..."):

                    elided = elided.rstrip(".") + "..."

                lines.append(elided)

                if len(lines) >= max_lines:

                    return "\n".join(lines)

                curr_line = ""



    if curr_line:

        lines.append(curr_line)

    return "\n".join(lines[:max_lines])





class OddBezelHUD(QWidget):

    """

    Dedicated ODD Bezel HUD & Notification Drop-Down Surface.

    Shares the unified ODDOverlaySurface liquid glass material with zero rectangular

    backing, restrained soft-settle spring motion (Entry: 280ms, Content reveal: 180ms,

    Exit: 240ms), real application icons for notifications, and compact keyboard lock pills.

    """

    def __init__(self, settings: dict, parent=None, trigger_window=None):

        super().__init__(parent)

        self.settings = settings

        self.trigger_window = trigger_window

        self.hud_type: Optional[str] = None

        self.hud_data: Dict[str, Any] = {}

        self.is_animating_out = False

        self._hud_opacity: float = 0.0

        self._content_reveal: float = 0.0

        self._hud_morph: float = 0.0



        self.setWindowFlags(

            Qt.WindowType.FramelessWindowHint |

            Qt.WindowType.WindowStaysOnTopHint |

            Qt.WindowType.Tool

        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.setCursor(Qt.CursorShape.ArrowCursor)



        # Timers

        self.dismiss_timer = QTimer(self)

        self.dismiss_timer.setSingleShot(True)

        self.dismiss_timer.timeout.connect(self.start_out_animation)



        # Physics-based spring animation system for slide-down drop & settle

        self._spring_timer = QTimer(self)
        self._spring_timer.setInterval(16)
        self._spring_timer.timeout.connect(self._on_spring_tick)
        self._spring_start_time = 0.0
        self._spring_y_start = 0.0
        self._spring_y_target = 0.0
        self._spring_center_x = 0

        # Living notification countdown progress bar timer (~45 FPS)
        self._notif_start_time = 0.0
        self._notif_total_duration_ms = 5000.0
        self._notif_is_paused = False
        self._notif_saved_ratio = 1.0

        self._notif_progress_timer = QTimer(self)
        self._notif_progress_timer.setInterval(22)
        self._notif_progress_timer.timeout.connect(self._on_notif_progress_tick)



        # Restrained soft-settle animations (never animate windowOpacity on WA_TranslucentBackground)

        self.pos_anim = QPropertyAnimation(self, b"geometry")

        self.opacity_anim = QPropertyAnimation(self, b"hud_opacity")

        self.reveal_anim = QPropertyAnimation(self, b"content_reveal")

        self.morph_anim = QPropertyAnimation(self, b"hud_morph")

        self._out_finished_connected = False



        self.target_y = 8

        self.hud_width = 128

        self.hud_height = 52

        self.is_expanded = False

    def nativeEvent(self, event_type, message):
        """
        Shape-aware Windows hit testing for Bezel HUD (WM_NCHITTEST = 0x0084):
        Only interactive notification dropdowns intercept clicks inside their squircle.
        Passive lock key pills, mute, battery, and volume HUDs return HTTRANSPARENT (-1)
        so mouse clicks pass through completely to underlying applications.
        """
        try:
            if event_type in ("windows_generic_MSG", "windows_dispatcher_MSG"):
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    if not self.isVisible() or self.is_animating_out:
                        return True, -1  # HTTRANSPARENT

                    if self.hud_type in ("notification", "reminder", "wellness", "activity", "timer", "chat", "nearby_share"):
                        local_pt = self.mapFromGlobal(QCursor.pos())
                        if self.rect().contains(local_pt):
                            return False, 0  # HTCLIENT: 100% Clickable!

                    return True, -1  # HTTRANSPARENT: Passive HUDs pass clicks through!
        except Exception:
            pass
        return super().nativeEvent(event_type, message)



    @staticmethod

    def _evaluate_spring(t: float, y_start: float, y_target: float, zeta: float = 0.58, omega_n: float = 22.0) -> float:

        """

        Physics-based damped harmonic oscillator spring solver.

        Underdamped (zeta ~0.58, omega_n ~22 rad/s) produces a vibrant, bouncier,

        fluid drop with expressive overshoot and settling.

        """

        if t <= 0.0:

            return y_start

        omega_d = omega_n * math.sqrt(max(0.001, 1.0 - zeta * zeta))

        decay = math.exp(-zeta * omega_n * t)

        delta = y_target - y_start

        coeff = zeta / math.sqrt(max(0.001, 1.0 - zeta * zeta))

        return y_target - delta * decay * (math.cos(omega_d * t) + coeff * math.sin(omega_d * t))



    def _on_spring_tick(self):

        now = time.perf_counter()

        t = now - getattr(self, "_spring_start_time", now)

        if t < 0.56:

            cur_y = self._evaluate_spring(t, self._spring_y_start, self._spring_y_target)

            self.move(self._spring_center_x, int(round(cur_y)))

        else:

            self.move(self._spring_center_x, int(round(self._spring_y_target)))

            self._spring_timer.stop()



    def get_hud_morph(self) -> float:

        return getattr(self, "_hud_morph", 0.0)



    def set_hud_morph(self, val: float):

        self._hud_morph = max(0.0, min(1.0, float(val)))

        self.update()



    hud_morph = Property(float, get_hud_morph, set_hud_morph)



    def get_hud_opacity(self) -> float:

        return getattr(self, "_hud_opacity", 0.0)



    def set_hud_opacity(self, val: float):

        self._hud_opacity = max(0.0, min(1.0, float(val)))

        self.update()



    hud_opacity = Property(float, get_hud_opacity, set_hud_opacity)



    def get_content_reveal(self) -> float:

        return getattr(self, "_content_reveal", 0.0)



    def set_content_reveal(self, val: float):

        self._content_reveal = max(0.0, min(1.0, float(val)))

        self.update()



    content_reveal = Property(float, get_content_reveal, set_content_reveal)



    @staticmethod

    def _soft_settle_curve() -> QEasingCurve:

        curve = QEasingCurve(QEasingCurve.Type.BezierSpline)

        curve.addCubicBezierSegment(QPointF(0.22, 1.0), QPointF(0.36, 1.0), QPointF(1.0, 1.0))

        return curve



    @staticmethod

    def _soft_exit_curve() -> QEasingCurve:

        curve = QEasingCurve(QEasingCurve.Type.BezierSpline)

        curve.addCubicBezierSegment(QPointF(0.32, 0.0), QPointF(0.67, 0.0), QPointF(1.0, 1.0))

        return curve



    @staticmethod

    def _spring_expand_curve() -> QEasingCurve:

        """cubic-bezier(0.34, 1.56, 0.64, 1) spring overshoot expansion curve"""

        curve = QEasingCurve(QEasingCurve.Type.BezierSpline)

        curve.addCubicBezierSegment(QPointF(0.34, 1.56), QPointF(0.64, 1.0), QPointF(1.0, 1.0))

        return curve



    def _auto_expand_notification(self):

        """Auto-expands compact app-name intro into the full notification message using cubic-bezier(0.34, 1.56, 0.64, 1)"""

        if not self.isVisible() or self.is_animating_out or self.hud_type != "notification":

            return

        full_h = getattr(self, "_notif_full_height", self.height())

        if self.height() >= full_h:

            return

        screen = self._active_screen_geometry()

        center_x = screen.x() + (screen.width() - self.width()) // 2

        start_rect = self.geometry()

        end_rect = QRect(center_x, self.target_y, self.width(), full_h)



        self.pos_anim.stop()

        self.pos_anim.setDuration(500)

        self.pos_anim.setEasingCurve(self._spring_expand_curve())

        self.pos_anim.setStartValue(start_rect)

        self.pos_anim.setEndValue(end_rect)

        self.pos_anim.start()



        self._expand_start_time = time.perf_counter()

        if hasattr(self, '_expand_anim_timer') and self._expand_anim_timer:

            self._expand_anim_timer.stop()

        self._expand_anim_timer = QTimer(self)

        self._expand_anim_timer.setInterval(16)

        def _on_expand_tick():

            now = time.perf_counter()

            t = min(1.0, (now - getattr(self, '_expand_start_time', now)) / 0.50)

            self._message_reveal = t

            self.update()

            if t >= 1.0 and hasattr(self, '_expand_anim_timer') and self._expand_anim_timer:

                self._expand_anim_timer.stop()

        self._expand_anim_timer.timeout.connect(_on_expand_tick)

        self._expand_anim_timer.start()



    def _on_notif_progress_tick(self):
        if self.hud_type == "notification" and self.isVisible() and not self.is_animating_out:
            self.update()
        else:
            self._notif_progress_timer.stop()

    def on_power_changed(self, power_dict: dict):
        if self.hud_type in ("notification", "battery") and self.isVisible():
            title = str(self.hud_data.get("title", "")).lower()
            if "battery" in title or "charger" in title:
                plugged = bool(power_dict.get("plugged_in", False))
                pct = int(power_dict.get("percent", 50))
                if plugged and ("connect" in title or "low" in title or "plug in" in title):
                    self.show_notification_hud(
                        "Charger Connected",
                        f"Battery charging at {pct}% • Health mode active",
                        duration_ms=2200,
                        force=True
                    )
                elif not plugged and ("unplug" in title or "80%" in title):
                    self.show_notification_hud(
                        "Charger Disconnected",
                        f"Running on battery ({pct}%) • 80% limit saved",
                        duration_ms=2200,
                        force=True
                    )

    def enterEvent(self, event):
        if self.hud_type == "notification" and not self.is_animating_out and self.isVisible():
            self._notif_is_paused = True
            self.dismiss_timer.stop()
            self.dismiss_timer.start(8000)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._close_hover = False
        if self.hud_type == "notification" and not self.is_animating_out and self.isVisible():
            self._notif_is_paused = False
            self.dismiss_timer.stop()
            self.dismiss_timer.start(2200)
        super().leaveEvent(event)

    def _get_notification_close_rect(self) -> QRectF:
        close_size = 22.0
        close_x = float(self.width() - 32)
        has_msg = bool(self.hud_data.get("message", ""))
        close_y = 12.0 if has_msg else float((self.height() - close_size) / 2.0)
        return QRectF(close_x - 3.0, close_y - 3.0, close_size + 6.0, close_size + 6.0)

    def mouseMoveEvent(self, event):
        if self.hud_type == "notification":
            pt = event.position() if hasattr(event, 'position') else event.pos()
            close_rect = getattr(self, '_close_btn_rect', None) or self._get_notification_close_rect()
            is_hover = close_rect.contains(pt)
            if is_hover != getattr(self, '_close_hover', False):
                self._close_hover = is_hover
                self.setCursor(Qt.CursorShape.PointingHandCursor if is_hover else Qt.CursorShape.ArrowCursor)
                self.update()

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if self.hud_type == "notification":
            pt = event.position() if hasattr(event, 'position') else event.pos()
            close_rect = getattr(self, '_close_btn_rect', None) or self._get_notification_close_rect()
            if close_rect.contains(pt):
                self.cancel_notification()
            else:
                self._open_notification_app()
                self.cancel_notification()
            event.accept()
            return

        super().mousePressEvent(event)



    def _open_notification_app(self):

        """Opens or foregrounds the application that issued the notification"""

        try:

            data = getattr(self, "hud_data", {}) or {}

            primary_id = str(data.get("primary_id", "") or "").strip()

            title = str(data.get("title", "") or "").strip()



            import ctypes

            user32 = ctypes.windll.user32



            targets = []

            if primary_id:

                clean_id = primary_id.split("!")[-1].split("_")[0].replace(".exe", "").lower()

                targets.append(clean_id)

            if title:

                targets.append(title.split("—")[0].split("-")[0].strip().lower())



            found_hwnd = None

            if targets:

                def enum_proc(hwnd, lparam):

                    nonlocal found_hwnd

                    if not user32.IsWindowVisible(hwnd):

                        return True

                    length = user32.GetWindowTextLengthW(hwnd)

                    if length == 0:

                        return True

                    buf = ctypes.create_unicode_buffer(length + 1)

                    user32.GetWindowTextW(hwnd, buf, length + 1)

                    w_title = buf.value.lower()

                    for t in targets:

                        if t and len(t) >= 3 and (t in w_title):

                            found_hwnd = hwnd

                            return False

                    return True



                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

                user32.EnumWindows(WNDENUMPROC(enum_proc), 0)



            if found_hwnd:

                SW_RESTORE = 9

                user32.ShowWindow(found_hwnd, SW_RESTORE)

                user32.SetForegroundWindow(found_hwnd)

                return



            if primary_id:

                import os

                try:

                    os.startfile(f"shell:AppsFolder\\{primary_id}")

                    return

                except Exception:

                    pass



            if hasattr(self, "trigger_window") and self.trigger_window and hasattr(self.trigger_window, "overlay"):

                overlay = self.trigger_window.overlay

                if hasattr(overlay, "search_engine"):

                    app_name = targets[0] if targets else title

                    items = overlay.search_engine.search(app_name, max_results=1)

                    if items and hasattr(overlay.search_engine, "execute"):

                        overlay.search_engine.execute(items[0])

                        return

        except Exception as e:

            print(f"[ODD] Error opening notification app: {e}")



    def cancel_notification(self):

        """Immediately cancels and dismisses any active notification HUD with zero linger"""

        if self.hud_type == "notification" and self.isVisible():

            self.dismiss_timer.stop()

            self.start_out_animation()



    def update_settings(self, new_settings: dict):

        self.settings = new_settings



    def show_caps_lock_hud(self, is_on: bool, duration_ms: int = 1800):

        if not self.settings.get("island_show_caps_lock_hud", True):

            return

        data = {"is_on": is_on}

        w, h = measure_system_status_pill("caps_lock", data)

        self._trigger_hud("caps_lock", data, width=w, height=h, duration_ms=duration_ms)



    def show_num_lock_hud(self, is_on: bool, duration_ms: int = 1800):

        if not self.settings.get("island_show_caps_lock_hud", True):

            return

        data = {"is_on": is_on}

        w, h = measure_system_status_pill("num_lock", data)

        self._trigger_hud("num_lock", data, width=w, height=h, duration_ms=duration_ms)



    def show_scroll_lock_hud(self, is_on: bool, duration_ms: int = 1800):

        if not self.settings.get("island_show_caps_lock_hud", True):

            return

        data = {"is_on": is_on}

        w, h = measure_system_status_pill("scroll_lock", data)

        self._trigger_hud("scroll_lock", data, width=w, height=h, duration_ms=duration_ms)



    def show_mute_hud(self, is_muted: bool, duration_ms: int = 1800):

        if not self.settings.get("island_show_volume_hud", True):

            return

        data = {"is_muted": is_muted}

        w, h = measure_system_status_pill("mute", data)

        self._trigger_hud("mute", data, width=w, height=h, duration_ms=duration_ms)



    def show_battery_hud(self, power_dict: dict, duration_ms: int = 3500):

        if not self.settings.get("island_show_battery_hud", True):

            return

        w, h = 340, 136

        self._trigger_hud("battery", power_dict, width=w, height=h, duration_ms=duration_ms)



    def show_clipboard_hud(self, action: str, preview: str, chars: int, duration_ms: int = 1800):

        # Disabled: All clipboard confirmations are rendered exclusively in the resting Info-matic bar without secondary overlays

        return



    def show_rook_hud(self, action_name: str, key_binding: str, duration_ms: int = 1800):

        if not self.settings.get("enable_rook_hud", True):

            return

        self._trigger_hud("rook", {"action": action_name, "key": key_binding}, width=102, height=88, duration_ms=duration_ms)



    def show_notification_hud(self, title: str, message: str, duration_ms: Optional[int] = None, app_icon: Any = None, primary_id: str = "", force: bool = False):
        if not force and (not self.settings.get("island_show_system_notifications", True) or self.settings.get("dnd_enabled", False)):
            return

        if duration_ms is None or duration_ms <= 0:
            dur_sec = float(self.settings.get("notification_duration_sec", 5))
            duration_ms = int(dur_sec * 1000)

        if app_icon is False:
            app_icon = None
        elif app_icon is None:
            app_icon = DynamicIslandMonitor.resolve_notification_app_icon(title=title, primary_id=primary_id)

        # Category and app source detection for redesigned top pill tag
        primary_id_str = str(primary_id or "").strip()
        t_lower = (title + " " + message).lower()
        if "battery" in t_lower or "charger" in t_lower or "unplug" in t_lower or "plug in" in t_lower:
            source_tag = "BATTERY"
            icon_type = "battery"
        elif "water" in t_lower or "hydration" in t_lower or "+250ml" in t_lower:
            source_tag = "HYDRATION"
            icon_type = "water"
        elif any(k in t_lower for k in ("completed", "goal", "acknowledged", "daily goal", "done")):
            source_tag = "ODD"
            icon_type = "done"
        elif any(k in t_lower for k in ("snooze", "postponed", "timer", "stopwatch")):
            source_tag = "TIME"
            icon_type = "snooze"
        elif "whatsapp" in primary_id_str.lower() or "whatsapp" in t_lower:
            source_tag = "WHATSAPP"
            icon_type = "app"
        elif "discord" in primary_id_str.lower() or "discord" in t_lower:
            source_tag = "DISCORD"
            icon_type = "app"
        elif "spotify" in primary_id_str.lower() or "spotify" in t_lower:
            source_tag = "SPOTIFY"
            icon_type = "app"
        elif primary_id_str:
            parts = [p for p in re.split(r'[._\-\\]', primary_id_str) if len(p) >= 3 and not p.isdigit()]
            source_tag = parts[0].upper() if parts else "SYSTEM"
            icon_type = "app" if app_icon else "system"
        else:
            source_tag = "SYSTEM"
            icon_type = "system"

        title_font = QFont("Segoe UI Variable Display", 9.0, QFont.Weight.DemiBold)
        msg_font = QFont("Segoe UI Variable Text", 8.2)
        title_metrics = QFontMetrics(title_font)
        message_metrics = QFontMetrics(msg_font)

        title_single_w = title_metrics.horizontalAdvance(title)
        msg_single_w = 0
        if message:
            msg_single_w = max(
                (message_metrics.horizontalAdvance(line) for line in message.splitlines() if line.strip()),
                default=0,
            )

        avatar_pad = 78
        desired_content_w = max(title_single_w, min(msg_single_w, 270))
        width = max(330, min(415, desired_content_w + avatar_pad + 28))
        content_width = width - (avatar_pad + 32)

        # Long title elision
        if title_metrics.horizontalAdvance(title) > content_width:
            title = title_metrics.elidedText(title, Qt.TextElideMode.ElideRight, content_width)

        title_height = max(16, title_metrics.boundingRect(
            QRect(0, 0, content_width, 120), int(Qt.TextFlag.TextWordWrap), title
        ).height())

        # For more text notification, elide so it cleanly stops with "..."
        if message:
            message = format_elided_notification_message(message, msg_font, content_width, max_lines=2)
            message_height = max(15, message_metrics.boundingRect(
                QRect(0, 0, content_width, 80), int(Qt.TextFlag.TextWordWrap), message
            ).height())
            height = min(88, max(68, 12 + 14 + title_height + 4 + message_height + 14))
            intro_height = min(54, max(46, 12 + title_height + 12))
        else:
            message_height = 0
            height = 54
            intro_height = height

        self._notif_start_time = time.time()
        self._notif_total_duration_ms = float(duration_ms)
        self._notif_is_paused = False
        self._notif_saved_ratio = 1.0
        self._notif_progress_timer.start()

        self._trigger_hud(
            "notification",
            {
                "title": title,
                "message": message,
                "title_height": title_height,
                "app_icon": app_icon,
                "primary_id": primary_id,
                "source_tag": source_tag,
                "icon_type": icon_type,
                "start_time": time.time(),
                "total_duration_ms": float(duration_ms),
                "intro_height": intro_height,
                "full_height": height,
            },
            width=width,
            height=height,
            duration_ms=duration_ms,
        )



    def show_nearby_share_hud(self, sender: str, message: str, duration_ms: int = 4500):

        title_str = f"Nearby Share — from {sender}"

        display_msg = message if len(message) <= 34 else message[:32] + "…"

        sub_str = f"{display_msg} (Copied to OS Clipboard)"

        m_title = QFontMetrics(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.Bold)).horizontalAdvance(title_str)

        m_sub = QFontMetrics(QFont("Segoe UI Variable Text", 8.0)).horizontalAdvance(sub_str)

        width = max(210, min(320, max(m_title, m_sub) + 56))

        self._trigger_hud("nearby_share", {"sender": sender, "message": message}, width=width, height=46, duration_ms=duration_ms)



    def show_chat_hud(self, sender: str, message: str, duration_ms: int = 4000):

        self.show_nearby_share_hud(sender, message, duration_ms=duration_ms)



    def _safe_disconnect_out_finished(self):

        if getattr(self, "_out_finished_connected", False):

            try:

                self.opacity_anim.finished.disconnect(self._on_out_finished)

            except Exception:

                pass

            try:

                self.pos_anim.finished.disconnect(self._on_out_finished)

            except Exception:

                pass

            self._out_finished_connected = False



    def _active_screen_geometry(self) -> QRect:

        screen_obj = QApplication.screenAt(QCursor.pos()) or self.screen() or QApplication.primaryScreen()

        return screen_obj.geometry()



    def _trigger_hud(self, hud_type: str, data: dict, width: int, height: int, duration_ms: int):

        self._safe_disconnect_out_finished()



        is_status_pill = hud_type in _SYSTEM_STATUS_TYPES

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, is_status_pill)



        self._entrance_start_time = time.perf_counter()

        try:

            import odd_sound

            if hud_type in ("caps_lock", "num_lock", "scroll_lock"):

                odd_sound.play_lock_sound(data.get("is_on", False), self.settings)

            elif hud_type == "mute":

                odd_sound.play_mute_sound(data.get("is_muted", False), self.settings)

            elif hud_type == "notification":

                odd_sound.play_notification(self.settings)

            elif hud_type == "reminder":

                odd_sound.play_reminder(self.settings)

        except Exception:

            pass



        screen = self._active_screen_geometry()

        side_view = str(self.settings.get("side_view", "off")).lower()

        if side_view == "left":

            center_x = screen.x() + 20

            self.target_y = screen.y() + 85

        elif side_view == "right":

            center_x = screen.x() + screen.width() - width - 20

            self.target_y = screen.y() + 85

        else:

            center_x = screen.x() + (screen.width() - width) // 2

            self.target_y = screen.y() + (8 if is_status_pill else 6)



        # If an overlay is already visible, fade + morph directly into the new overlay without collision or snapping!

        if self.isVisible() and not self.is_animating_out:

            if hasattr(self, '_spring_timer') and self._spring_timer.isActive():

                self._spring_timer.stop()

            end_rect = QRect(center_x, self.target_y, width, height)

            current_rect = self.geometry()



            self.hud_type = hud_type

            self.hud_data = data

            self.hud_width = width

            self.hud_height = height

            self.is_expanded = (hud_type == "notification")



            self.dismiss_timer.stop()

            self.pos_anim.stop()

            self.opacity_anim.stop()

            self.reveal_anim.stop()

            self.morph_anim.stop()



            # Smoothly morph bounds directly from current geometry to target geometry

            if current_rect != end_rect:

                self.pos_anim.setDuration(190)

                self.pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

                self.pos_anim.setStartValue(current_rect)

                self.pos_anim.setEndValue(end_rect)

                self.pos_anim.start()



            # Fade + morph content reveal smoothly

            self._hud_opacity = 1.0

            self._hud_morph = 1.0

            self._content_reveal = 0.20

            self.reveal_anim.setDuration(160)

            self.reveal_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            self.reveal_anim.setStartValue(0.20)

            self.reveal_anim.setEndValue(1.0)

            self.reveal_anim.start()



            self.dismiss_timer.start(duration_ms)

            self.update()

            return



        self.hud_type = hud_type

        self.hud_data = data

        self.hud_width = width

        self.hud_height = height

        self.is_animating_out = False

        self.is_expanded = hud_type == "notification"



        self.dismiss_timer.stop()

        self.dismiss_timer.setInterval(duration_ms)



        # Hide the resting edge bar while overlay is expanded

        if self.trigger_window and hasattr(self.trigger_window, "set_edge_bar_hidden"):

            self.trigger_window.set_edge_bar_hidden(True)



        self.pos_anim.stop()

        self.opacity_anim.stop()

        self.reveal_anim.stop()

        self.morph_anim.stop()

        if hasattr(self, '_spring_timer') and self._spring_timer.isActive():

            self._spring_timer.stop()



        # Intro app-name state with auto-expand spring animation into full message

        has_intro_expand = (hud_type == "notification" and bool(data.get("message")) and data.get("intro_height", height) < height)

        init_h = int(data.get("intro_height", 42)) if has_intro_expand else height

        if has_intro_expand:

            self._notif_compact_height = init_h

            self._notif_full_height = height

            self._message_reveal = 0.0

            if hasattr(self, '_notif_expand_timer') and self._notif_expand_timer:

                self._notif_expand_timer.stop()

            self._notif_expand_timer = QTimer(self)

            self._notif_expand_timer.setSingleShot(True)

            self._notif_expand_timer.timeout.connect(self._auto_expand_notification)

            self._notif_expand_timer.start(280)

        else:

            self._message_reveal = 1.0



        # Physics-based spring drop: starts above the top screen bezel

        start_y = screen.y() - init_h - 16

        self.setGeometry(center_x, start_y, width, init_h)

        self._spring_start_time = time.perf_counter()

        self._spring_y_start = float(start_y)

        self._spring_y_target = float(self.target_y)

        self._spring_center_x = center_x

        self._spring_timer.start()



        self._hud_opacity = 0.0

        self._hud_morph = 0.0

        self._content_reveal = 0.0

        self.show()
        self.raise_()



        try:

            import odd_blur

            odd_blur.ensure_transparent_hwnd(int(self.winId()))

        except Exception:

            pass



        self.morph_anim.setDuration(180)

        self.morph_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.morph_anim.setStartValue(0.0)

        self.morph_anim.setEndValue(1.0)



        self.opacity_anim.setDuration(160)

        self.opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.opacity_anim.setStartValue(0.0)

        self.opacity_anim.setEndValue(1.0)



        self.reveal_anim.setDuration(160)

        self.reveal_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.reveal_anim.setStartValue(0.0)

        self.reveal_anim.setEndValue(1.0)



        self.morph_anim.start()

        self.opacity_anim.start()

        self.reveal_anim.start()

        self.dismiss_timer.start()

        self.update()



    def start_out_animation(self):

        """Exit: Slide up into the top screen bezel with InCubic velocity and fading opacity"""

        if self.is_animating_out or not self.isVisible():

            return

        self.is_animating_out = True

        self._out_start_time = time.perf_counter()

        self.dismiss_timer.stop()

        if hasattr(self, '_spring_timer') and self._spring_timer.isActive():

            self._spring_timer.stop()



        self.pos_anim.stop()

        self.opacity_anim.stop()

        self.reveal_anim.stop()

        self.morph_anim.stop()



        # Slide Up Exit into the top bezel

        screen = self._active_screen_geometry()

        target_up_y = screen.y() - self.height() - 20

        curr_rect = self.geometry()

        exit_rect = QRect(curr_rect.x(), target_up_y, curr_rect.width(), curr_rect.height())



        duration = 240

        self.pos_anim.setDuration(duration)

        self.pos_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        self.pos_anim.setStartValue(curr_rect)

        self.pos_anim.setEndValue(exit_rect)



        self.opacity_anim.setDuration(duration)

        self.opacity_anim.setEasingCurve(QEasingCurve.Type.InQuad)

        self.opacity_anim.setStartValue(self._hud_opacity)

        self.opacity_anim.setEndValue(0.0)



        self.morph_anim.setDuration(duration)

        self.morph_anim.setEasingCurve(QEasingCurve.Type.InQuad)

        self.morph_anim.setStartValue(self._hud_morph)

        self.morph_anim.setEndValue(0.0)



        self.reveal_anim.setDuration(int(duration * 0.70))

        self.reveal_anim.setEasingCurve(QEasingCurve.Type.InQuad)

        self.reveal_anim.setStartValue(self._content_reveal)

        self.reveal_anim.setEndValue(0.0)



        if not self._out_finished_connected:

            self.pos_anim.finished.connect(self._on_out_finished)

            self._out_finished_connected = True



        self.pos_anim.start()

        self.opacity_anim.start()

        self.morph_anim.start()

        self.reveal_anim.start()



    def _on_out_finished(self):

        self._safe_disconnect_out_finished()

        self.hide()

        self.is_animating_out = False

        self.hud_type = None

        self.hud_data = {}

        if self.trigger_window and hasattr(self.trigger_window, "set_edge_bar_hidden"):

            self.trigger_window.set_edge_bar_hidden(False)



    def hideEvent(self, event):

        super().hideEvent(event)

        if self.trigger_window and hasattr(self.trigger_window, "set_edge_bar_hidden"):

            overlay = getattr(self.trigger_window, "overlay", None)

            if not (overlay and (overlay.is_open or overlay.isVisible())):

                self.trigger_window.set_edge_bar_hidden(False)



    def paintEvent(self, event):

        try:

            self._do_paint_event(event)

        except Exception:

            pass



    def _do_paint_event(self, event):

        if not self.hud_type or self._hud_opacity <= 0.004:

            return



        painter = QPainter(self)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)



        if self.is_animating_out:

            painter.setOpacity(self._hud_opacity)

        # Animate.css animate__headShake entrance for wellness & alert reminders / notifications

        elif self.hud_type in ("reminder", "notification"):

            import odd_animated_buttons

            now = time.perf_counter()

            elapsed = now - getattr(self, "_entrance_start_time", now)

            t = elapsed / 0.75

            if t < 0.50:

                headshake_dx = odd_animated_buttons.get_headshake_offset(t)

                if abs(headshake_dx) > 0.01:

                    painter.translate(headshake_dx, 0.0)

                QTimer.singleShot(16, self.update)



        theme = str(self.settings.get("theme", "dark")).lower()



        # ---------------- SYSTEM-STATUS CAPSULE PILL (Caps / Num / Scroll / Mute / Battery) ----------------

        if self.hud_type in _SYSTEM_STATUS_TYPES:

            painter.save()

            y_shift = -5.0 * (1.0 - self._hud_morph)

            scale_fac = 0.94 + 0.06 * self._hud_morph

            cx = self.width() / 2.0

            cy = self.height() / 2.0

            painter.translate(cx, cy + y_shift)

            painter.scale(scale_fac, scale_fac)

            painter.translate(-cx, -cy)



            pill_rect = paint_system_status_pill_surface(painter, self.rect(), opacity=self._hud_opacity, theme=theme)

            content_op = max(0.0, min(1.0, self._hud_opacity * self._content_reveal))

            painter.setOpacity(content_op)

            paint_system_status_pill_content(painter, pill_rect, self.hud_type, self.hud_data)

            painter.restore()

            return



        rect = self.rect().adjusted(1, 1, -1, -1)

        r = min(float(rect.height()) / 2.0, 22.0)



        # 1. Shared ODDOverlaySurface Liquid Glass Material (zero rectangular backing)

        try:

            import odd_blur

            odd_blur.ODDOverlaySurface.paint_glass_surface(

                painter,

                rect,

                r,

                theme=theme,

                opacity=self._hud_opacity,

                hwnd=int(self.winId()),

            )

        except Exception:

            pass



        if theme == "light":

            text_col = QColor(20, 20, 24)

            sub_col = QColor(95, 98, 108)

        elif theme == "oled":

            text_col = QColor(255, 255, 255)

            sub_col = QColor(162, 166, 176)

        else:

            text_col = QColor(248, 250, 252)

            sub_col = QColor(164, 168, 178)



        content_op = max(0.0, min(1.0, self._hud_opacity * (0.25 + 0.75 * self._content_reveal)))

        painter.save()

        painter.setOpacity(content_op)

        if not self.is_animating_out:

            painter.translate(0.0, -3.5 * (1.0 - self._content_reveal))



        if False:

            pass



        # ---------------- D. COPY / PASTE BADGE HUD ----------------

        # ---------------- D. COPY BADGE HUD (Monochrome, Copied only) ----------------

        elif self.hud_type == "clip":

            painter.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.DemiBold))

            painter.setPen(sub_col)

            painter.drawText(QRect(0, 12, self.width(), 16), Qt.AlignmentFlag.AlignCenter, "Copied")



            cx = self.width() / 2.0

            cy = self.height() / 2.0 + 1.0



            accent = fg_col

            painter.setBrush(QBrush(QColor(255, 255, 255, 22)))

            painter.setPen(QPen(QColor(255, 255, 255, 110), 1.0))

            painter.drawEllipse(QPoint(int(cx), int(cy)), 15, 15)



            painter.setPen(QPen(accent, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

            tick_path = QPainterPath()

            tick_path.moveTo(cx - 5.5, cy + 0.5)

            tick_path.lineTo(cx - 1.5, cy + 4.5)

            tick_path.lineTo(cx + 6.0, cy - 4.5)

            painter.strokePath(tick_path, painter.pen())



            painter.setFont(QFont("Segoe UI Variable Text", 8.2, QFont.Weight.Medium))

            painter.setPen(sub_col)

            painter.drawText(QRect(0, self.height() - 25, self.width(), 16), Qt.AlignmentFlag.AlignCenter, "Clipboard")



        # ---------------- E. ROOK SHORTCUT HUD ----------------

        elif self.hud_type == "rook":

            action_name = self.hud_data.get("action", "Rook")



            painter.setFont(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.DemiBold))

            painter.setPen(sub_col)

            painter.drawText(QRect(0, 12, self.width(), 16), Qt.AlignmentFlag.AlignCenter, "Rook Shortcut")



            cx = self.width() / 2.0

            cy = self.height() / 2.0 + 1.0



            accent = QColor(168, 85, 247)

            painter.setBrush(QBrush(QColor(accent.red(), accent.green(), accent.blue(), 35)))

            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 150), 1.0))

            painter.drawEllipse(QPoint(int(cx), int(cy)), 15, 15)



            painter.setPen(QPen(accent, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

            painter.drawLine(int(cx - 4.0), int(cy), int(cx + 4.0), int(cy))

            painter.drawLine(int(cx), int(cy - 4.0), int(cx), int(cy + 4.0))



            painter.setFont(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.Bold))

            painter.setPen(accent)

            disp_act = action_name if len(action_name) <= 12 else action_name[:10] + "…"

            painter.drawText(QRect(0, self.height() - 25, self.width(), 16), Qt.AlignmentFlag.AlignCenter, disp_act)



        # ---------------- G. RICH CHARGING / BATTERY OVERLAY (Image 3 Style) ----------------
        elif self.hud_type == "battery":
            pct = max(0, min(100, int(self.hud_data.get("percent", 59))))
            is_charging = bool(self.hud_data.get("is_charging", False) or self.hud_data.get("charging", False) or self.hud_data.get("plugged_in", False))
            secsleft = self.hud_data.get("secsleft", -1)

            card_w = float(self.width())
            card_h = float(self.height())
            grad = QRadialGradient(card_w * 0.35, card_h * 0.45, card_w * 0.8)
            grad.setColorAt(0.0, QColor(10, 28, 14, int(255 * self._hud_opacity)))
            grad.setColorAt(1.0, QColor(3, 8, 4, int(255 * self._hud_opacity)))

            p_path = QPainterPath()
            p_path.addRoundedRect(QRectF(1.0, 1.0, card_w - 2.0, card_h - 2.0), 22.0, 22.0)
            painter.fillPath(p_path, QBrush(grad))
            painter.strokePath(p_path, QPen(QColor(255, 255, 255, int(28 * self._hud_opacity)), 1.0))

            neon_green = QColor(0, 230, 118, int(255 * self._hud_opacity))
            text_white = QColor(255, 255, 255, int(255 * self._hud_opacity))
            text_dim = QColor(255, 255, 255, int(150 * self._hud_opacity))

            bolt_x = 22.0
            bolt_y = 20.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(neon_green if is_charging else text_dim))
            bolt = QPainterPath()
            bolt.moveTo(bolt_x + 5.0, bolt_y)
            bolt.lineTo(bolt_x, bolt_y + 9.0)
            bolt.lineTo(bolt_x + 4.5, bolt_y + 9.0)
            bolt.lineTo(bolt_x + 3.0, bolt_y + 16.0)
            bolt.lineTo(bolt_x + 9.5, bolt_y + 6.0)
            bolt.lineTo(bolt_x + 5.5, bolt_y + 6.0)
            bolt.closeSubpath()
            painter.drawPath(bolt)

            header_text = "Charging" if is_charging else "Battery"
            painter.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.DemiBold))
            painter.setPen(text_white)
            painter.drawText(QRectF(bolt_x + 16.0, bolt_y - 3.0, 200.0, 22.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, header_text)

            if is_charging:
                if pct >= 100:
                    time_label = "Fully Charged"
                elif 0 < secsleft < 86400:
                    m = int(secsleft // 60)
                    time_label = f"{m // 60}h {m % 60}m left" if m >= 60 else f"{m} min left"
                else:
                    est_m = max(5, int((100 - pct) * 0.9))
                    time_label = f"{est_m} min left"
            else:
                if 0 < secsleft < 86400:
                    m = int(secsleft // 60)
                    time_label = f"{m // 60}h {m % 60}m left" if m >= 60 else f"{m} min left"
                else:
                    time_label = "On battery"

            painter.setFont(QFont("Segoe UI Variable Display", 18, QFont.Weight.Bold))
            pct_str = f"{pct}%"
            fm_pct = QFontMetrics(painter.font())
            pct_w = fm_pct.horizontalAdvance(pct_str)
            painter.setPen(neon_green)
            painter.drawText(QRectF(22.0, 46.0, pct_w + 4.0, 28.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, pct_str)

            dot_x = 22.0 + pct_w + 8.0
            painter.setFont(QFont("Segoe UI Variable Text", 15, QFont.Weight.Normal))
            painter.setPen(text_dim)
            painter.drawText(QRectF(dot_x, 46.0, 14.0, 28.0), Qt.AlignmentFlag.AlignCenter, "•")

            time_x = dot_x + 16.0
            painter.setFont(QFont("Segoe UI Variable Display", 17, QFont.Weight.Normal))
            painter.setPen(text_white)
            painter.drawText(QRectF(time_x, 46.0, card_w - time_x - 14.0, 28.0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, time_label)

            gauge_x = 22.0
            gauge_y = 82.0
            gauge_w = card_w - 44.0
            gauge_h = 36.0
            gauge_rect = QRectF(gauge_x, gauge_y, gauge_w, gauge_h)

            painter.setPen(QPen(QColor(255, 255, 255, int(60 * self._hud_opacity)), 1.2))
            painter.setBrush(QBrush(QColor(0, 0, 0, int(80 * self._hud_opacity))))
            painter.drawRoundedRect(gauge_rect, 18.0, 18.0)

            fill_max = gauge_w - 6.0
            fill_w = max(16.0, (pct / 100.0) * fill_max)
            fill_rect = QRectF(gauge_x + 3.0, gauge_y + 3.0, fill_w, gauge_h - 6.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(neon_green))
            painter.drawRoundedRect(fill_rect, 15.0, 15.0)

        # ---------------- F. REDESIGNED NOTIFICATION OVERLAY (Squircle Badge + Living Gradient Pill) ----------------
        elif self.hud_type == "notification":
            title = str(self.hud_data.get("title", "Notification")).strip()
            message = str(self.hud_data.get("message", "")).strip()
            app_icon = self.hud_data.get("app_icon", None)
            source_tag = str(self.hud_data.get("source_tag", "SYSTEM")).upper()
            icon_type = str(self.hud_data.get("icon_type", "system")).lower()

            # Dynamic Category / Brand Accent Color
            if icon_type == "battery":
                accent_col = QColor(16, 185, 129)   # Emerald
            elif icon_type == "water":
                accent_col = QColor(56, 189, 248)   # Sky Blue
            elif icon_type == "done":
                accent_col = QColor(16, 185, 129)   # Emerald
            elif icon_type == "snooze":
                accent_col = QColor(6, 182, 212)    # Cyan
            elif "spotify" in source_tag.lower():
                accent_col = QColor(30, 215, 96)    # Spotify green
            elif "discord" in source_tag.lower():
                accent_col = QColor(88, 101, 242)   # Discord blurple
            elif "whatsapp" in source_tag.lower():
                accent_col = QColor(37, 211, 102)   # WhatsApp green
            else:
                accent_col = QColor(99, 102, 241)   # Fluent Indigo

            # Subtle left ambient halo glow behind avatar
            halo = QRadialGradient(QPointF(30.0, float(self.height() / 2.0)), 46.0)
            halo.setColorAt(0.0, QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 34 if theme != "light" else 18))
            halo.setColorAt(1.0, QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(QPointF(30.0, float(self.height() / 2.0)), 46.0, 46.0)

            # 1. Left Squircle Avatar Badge (32x32)
            badge_size = 32.0
            badge_x = 14.0
            badge_y = float((self.height() - badge_size) / 2.0)
            badge_rect = QRectF(badge_x, badge_y, badge_size, badge_size)

            # Squircle background with category tint & luminous border
            badge_bg = QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 30 if theme != "light" else 20)
            badge_border = QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 80 if theme != "light" else 50)
            painter.setPen(QPen(badge_border, 1.0))
            painter.setBrush(QBrush(badge_bg))
            painter.drawRoundedRect(badge_rect, 8.5, 8.5)

            # Badge Icon Content
            if app_icon is not None and isinstance(app_icon, QPixmap) and not app_icon.isNull():
                ix = int(badge_x + (badge_size - 22) / 2)
                iy = int(badge_y + (badge_size - 22) / 2)
                painter.drawPixmap(ix, iy, 22, 22, app_icon)
            else:
                bcx = badge_x + badge_size / 2.0
                bcy = badge_y + badge_size / 2.0
                if icon_type == "battery":
                    bw, bh = 15.0, 9.5
                    bx = bcx - bw / 2.0 - 0.5
                    by = bcy - bh / 2.0
                    painter.setPen(QPen(accent_col, 1.25))
                    painter.setBrush(QBrush(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 35)))
                    painter.drawRoundedRect(QRectF(bx, by, bw, bh), 2.0, 2.0)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(accent_col))
                    painter.drawRoundedRect(QRectF(bx + bw + 0.5, bcy - 2.0, 1.4, 4.0), 0.5, 0.5)
                    # Interior charge bolt
                    bolt = QPainterPath()
                    bolt.moveTo(bcx + 0.5, bcy - 3.4)
                    bolt.lineTo(bcx - 2.0, bcy + 0.2)
                    bolt.lineTo(bcx - 0.2, bcy + 0.2)
                    bolt.lineTo(bcx - 0.9, bcy + 3.4)
                    bolt.lineTo(bcx + 2.0, bcy - 0.2)
                    bolt.lineTo(bcx + 0.2, bcy - 0.2)
                    bolt.closeSubpath()
                    painter.drawPath(bolt)
                elif icon_type == "done":
                    painter.setPen(QPen(accent_col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    chk = QPainterPath()
                    chk.moveTo(bcx - 5.0, bcy + 0.2)
                    chk.lineTo(bcx - 1.2, bcy + 4.0)
                    chk.lineTo(bcx + 5.5, bcy - 3.5)
                    painter.strokePath(chk, painter.pen())
                elif icon_type == "snooze":
                    painter.setPen(QPen(accent_col, 1.3))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPointF(bcx, bcy), 6.0, 6.0)
                    painter.drawLine(QPointF(bcx, bcy), QPointF(bcx, bcy - 3.5))
                    painter.drawLine(QPointF(bcx, bcy), QPointF(bcx + 2.8, bcy))
                elif icon_type == "water":
                    painter.setPen(QPen(accent_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    painter.setBrush(QBrush(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 35)))
                    drp = QPainterPath()
                    drp.moveTo(bcx, bcy - 5.5)
                    drp.cubicTo(bcx + 4.5, bcy - 0.5, bcx + 5.0, bcy + 4.0, bcx, bcy + 5.5)
                    drp.cubicTo(bcx - 5.0, bcy + 4.0, bcx - 4.5, bcy - 0.5, bcx, bcy - 5.5)
                    painter.drawPath(drp)
                else:
                    painter.setPen(QPen(accent_col if theme != "light" else text_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    bell = QPainterPath()
                    bell.moveTo(bcx - 4.5, bcy + 2.8)
                    bell.lineTo(bcx + 4.5, bcy + 2.8)
                    bell.quadTo(bcx + 3.6, bcy - 1.0, bcx + 2.2, bcy - 4.2)
                    bell.quadTo(bcx, bcy - 5.6, bcx - 2.2, bcy - 4.2)
                    bell.quadTo(bcx - 3.6, bcy - 1.0, bcx - 4.5, bcy + 2.8)
                    bell.closeSubpath()
                    painter.strokePath(bell, painter.pen())
                    painter.drawPoint(QPointF(bcx, bcy + 5.0))

            # 2. Right Circular Glass Dismiss '✕' Button
            close_size = 22.0
            close_x = float(self.width() - 32)
            close_y = 12.0 if message else float((self.height() - close_size) / 2.0)
            self._close_btn_rect = QRectF(close_x - 3.0, close_y - 3.0, close_size + 6.0, close_size + 6.0)

            is_close_hover = getattr(self, '_close_hover', False)
            if is_close_hover:
                painter.setBrush(QBrush(QColor(255, 255, 255, 45) if theme != "light" else QColor(0, 0, 0, 26)))
                painter.setPen(QPen(QColor(255, 255, 255, 75) if theme != "light" else QColor(0, 0, 0, 45), 0.9))
                painter.drawEllipse(QRectF(close_x, close_y, close_size, close_size))
            else:
                painter.setBrush(QBrush(QColor(255, 255, 255, 14) if theme != "light" else QColor(0, 0, 0, 10)))
                painter.setPen(QPen(QColor(255, 255, 255, 24) if theme != "light" else QColor(0, 0, 0, 16), 0.7))
                painter.drawEllipse(QRectF(close_x, close_y, close_size, close_size))

            painter.setPen(QPen(text_col if is_close_hover else sub_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            ccx = close_x + close_size / 2.0
            ccy = close_y + close_size / 2.0
            cd = 3.2
            painter.drawLine(QPointF(ccx - cd, ccy - cd), QPointF(ccx + cd, ccy + cd))
            painter.drawLine(QPointF(ccx + cd, ccy - cd), QPointF(ccx - cd, ccy + cd))

            # 3. Typography: Category Tag Chip + Title + Message
            text_left = int(badge_x + badge_size + 12)
            right_boundary = int(close_x - 10)
            text_avail_w = max(40, right_boundary - text_left)

            if message:
                # A. Category Tag Chip Pill & Timestamp
                tag_font = QFont("Segoe UI Variable Text", 6.6, QFont.Weight.Bold)
                tag_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
                painter.setFont(tag_font)
                tag_metrics = QFontMetrics(tag_font)
                tag_w = tag_metrics.horizontalAdvance(source_tag)

                # Small pill chip around source tag
                chip_h = 13.0
                chip_rect = QRectF(text_left, 10.0, tag_w + 10.0, chip_h)
                painter.setPen(QPen(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 60 if theme != "light" else 40), 0.7))
                painter.setBrush(QBrush(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 32 if theme != "light" else 20)))
                painter.drawRoundedRect(chip_rect, 6.5, 6.5)

                painter.setPen(accent_col if theme != "light" else QColor(accent_col.darker(115)))
                painter.drawText(QRect(text_left + 5, 10, tag_w, int(chip_h)), Qt.AlignmentFlag.AlignCenter, source_tag)

                bullet_x = text_left + tag_w + 15
                painter.setPen(QColor(135, 140, 155))
                painter.drawText(QRect(bullet_x, 10, 8, 13), Qt.AlignmentFlag.AlignCenter, "•")

                time_x = bullet_x + 9
                time_font = QFont("Segoe UI Variable Text", 6.4, QFont.Weight.Normal)
                painter.setFont(time_font)
                painter.setPen(QColor(145, 152, 168) if theme != "light" else QColor(115, 120, 135))
                painter.drawText(QRect(time_x, 10, 50, 13), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Just now")

                # B. Headline
                painter.setFont(QFont("Segoe UI Variable Display", 9.0, QFont.Weight.DemiBold))
                painter.setPen(text_col)
                title_metrics = QFontMetrics(painter.font())
                elided_title = title_metrics.elidedText(title, Qt.TextElideMode.ElideRight, text_avail_w)
                painter.drawText(QRect(text_left, 26, text_avail_w, 17), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

                # C. Message
                painter.setFont(QFont("Segoe UI Variable Text", 8.2, QFont.Weight.Normal))
                painter.setPen(sub_col)
                msg_metrics = QFontMetrics(painter.font())
                elided_msg = msg_metrics.elidedText(message, Qt.TextElideMode.ElideRight, text_avail_w)
                painter.drawText(QRect(text_left, 45, text_avail_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_msg)
            else:
                # Single-line banner title
                painter.setFont(QFont("Segoe UI Variable Display", 9.2, QFont.Weight.DemiBold))
                painter.setPen(text_col)
                title_metrics = QFontMetrics(painter.font())
                elided_title = title_metrics.elidedText(title, Qt.TextElideMode.ElideRight, text_avail_w)
                painter.drawText(QRect(text_left, 0, text_avail_w, self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

            # 4. Living Rounded Capsule Progress Bar with glowing leading bead
            start_t = float(self.hud_data.get("start_time", 0.0))
            tot_dur = float(self.hud_data.get("total_duration_ms", 5000.0))
            now = time.time()
            if start_t > 0 and tot_dur > 0:
                elapsed_ms = (now - start_t) * 1000.0
                remain_ratio = max(0.0, min(1.0, 1.0 - (elapsed_ms / tot_dur)))
                if getattr(self, '_notif_is_paused', False):
                    remain_ratio = getattr(self, '_notif_saved_ratio', remain_ratio)
                else:
                    self._notif_saved_ratio = remain_ratio

                bar_total_w = float(self.width() - 32)
                bar_fill_w = max(0.0, bar_total_w * remain_ratio)
                bar_x = 16.0
                bar_y = float(self.height() - 4.5)
                bar_h = 2.2

                # Groove
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(255, 255, 255, 14) if theme != "light" else QColor(0, 0, 0, 12)))
                painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_total_w, bar_h), 1.1, 1.1)

                # Gradient fill
                if bar_fill_w > 1.0:
                    prog_grad = QLinearGradient(bar_x, bar_y, bar_x + bar_fill_w, bar_y)
                    prog_grad.setColorAt(0.0, QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 190))
                    prog_grad.setColorAt(1.0, QColor(accent_col.lighter(125).red(), accent_col.lighter(125).green(), accent_col.lighter(125).blue(), 250))
                    painter.setBrush(QBrush(prog_grad))
                    painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_fill_w, bar_h), 1.1, 1.1)

                    # Subtle glowing tip bead
                    tip_x = bar_x + bar_fill_w
                    painter.setBrush(QBrush(QColor(255, 255, 255, 230)))
                    painter.drawEllipse(QPointF(tip_x, bar_y + bar_h / 2.0), 1.4, 1.4)



        # ---------------- G. NEARBY SHARE / DEVICE DROP HUD CARD ----------------

        elif self.hud_type in ("chat", "nearby_share"):

            sender = self.hud_data.get("sender", "Nearby Device")

            message = self.hud_data.get("message", "")



            dot_x = 12

            dot_y = (self.height() - 20) // 2

            accent_col = QColor(16, 185, 129) if theme != "light" else QColor(5, 150, 105)

            painter.setBrush(QBrush(QColor(accent_col.red(), accent.green() if hasattr(accent_col, 'green') else 185, accent_col.blue(), 35)))

            painter.setPen(QPen(accent_col, 1.0))

            painter.drawRoundedRect(dot_x, dot_y, 20, 20, 5, 5)



            painter.setPen(QPen(accent_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

            painter.setBrush(Qt.BrushStyle.NoBrush)

            painter.drawEllipse(QPoint(dot_x + 7, dot_y + 8), 2, 2)

            painter.drawEllipse(QPoint(dot_x + 13, dot_y + 12), 2, 2)

            painter.drawLine(dot_x + 8, dot_y + 9, dot_x + 12, dot_y + 11)



            painter.setFont(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.Bold))

            painter.setPen(accent_col)

            painter.drawText(dot_x + 28, (self.height() // 2) - 1, f"Nearby Share — from {sender}")



            painter.setFont(QFont("Segoe UI Variable Text", 8.0))

            painter.setPen(text_col)

            display_msg = message if len(message) <= 34 else message[:32] + "…"

            painter.drawText(dot_x + 28, (self.height() // 2) + 12, f"{display_msg} (Copied to OS Clipboard)")



        painter.restore()







class DynamicIslandHUD(QWidget):

    """

    The Living Dynamic Island visual surface in the top notch for Windows.

    Smoothly expands and morphs for Media tracks, Volume levels, Timers, and Fast Copy/Paste pills.

    Zero emojis, clean typography, minimalist vector indicators.

    """

    def __init__(self, parent_trigger, settings: dict):

        super().__init__(parent_trigger)

        self.trigger = parent_trigger

        self.settings = settings



        self.current_hud_type: Optional[str] = None  # 'media', 'volume', 'battery', 'clip', 'rook', 'timer', 'reminder', 'activity', 'downloads'

        self.hud_data: Dict[str, Any] = {}

        self.eq_phase = 0.0

        self.vinyl_angle = 0.0

        self._hovered_btn: Optional[str] = None

        self._btn_hover_progress: Dict[str, float] = {"cancel": 0.0, "done": 0.0}

        self._reminder_buttons: Dict[str, Any] = {}

        self._activity_rects: list = []



        # Auto-dismiss timer for HUD activity

        self.dismiss_timer = QTimer(self)

        self.dismiss_timer.setSingleShot(True)

        self.dismiss_timer.timeout.connect(self.dismiss_hud)



        # Equalizer / ticker / vinyl / icon animation timer (~60 FPS)

        self.anim_timer = QTimer(self)

        self.anim_timer.setInterval(16)

        self.anim_timer.timeout.connect(self._on_anim_tick)



        # Micro-interaction spring physics for smooth volume, lock arrow, and audio mute animations

        self.vol_spring = SpringValue(initial_value=50.0, response=0.12, damping_ratio=0.82)

        self.lock_spring = SpringValue(initial_value=1.0, response=0.14, damping_ratio=0.70)

        self.mute_spring = SpringValue(initial_value=0.0, response=0.16, damping_ratio=0.74)

        self.content_reveal = SpringValue(initial_value=0.0, response=0.14, damping_ratio=0.78)

        self._last_tick_time = time.perf_counter()



        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)



    def get_dynamic_media_width(self, data: dict = None) -> int:

        """Calculates dynamic content-hugging width for media pill to eliminate empty space"""

        data = data or self.hud_data

        if not data:

            return 180

        title = data.get("title", "Media Playing") or "Media Playing"

        artist = data.get("artist", "") or ""

        style = self.settings.get("island_media_style", "vinyl")



        if style == "minimal":

            return 134



        metrics_title = QFontMetrics(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))

        w_title = metrics_title.horizontalAdvance(title)

        w_artist = 0

        if artist:

            metrics_artist = QFontMetrics(QFont("Segoe UI Variable Text", 6.5))

            w_artist = metrics_artist.horizontalAdvance(artist)



        text_w = max(w_title, w_artist)

        text_w = max(40, min(130, text_w))



        icon_w = 20 if style == "vinyl" else 18

        eq_w = 22

        total_w = 8 + icon_w + 8 + text_w + 8 + eq_w + 8

        return max(156, min(248, total_w))



    def get_dynamic_activity_size(self, data: dict = None) -> Tuple[int, int]:

        """Calculates minimal expanded dimensions for activities & downloads"""

        data = data or self.hud_data

        items = data.get("all_items", []) or data.get("active_items", [])

        count = len(items) if items else 1

        max_title_w = 90

        metrics = QFontMetrics(QFont("Segoe UI Variable Text", 8.2, QFont.Weight.DemiBold))

        for item in (items[:3] if items else []):

            t = getattr(item, "title", "") if hasattr(item, "title") else (item.get("title", "") if isinstance(item, dict) else "Download")

            max_title_w = max(max_title_w, metrics.horizontalAdvance(str(t)))

        width = max(210, min(296, 32 + max_title_w + 58))

        if count <= 1:

            height = 38

        elif count == 2:

            height = 66

        else:

            height = 94

        return (width, height)



    def get_dynamic_reminder_size(self, data: dict = None) -> Tuple[int, int]:

        """Calculates expanded dimensions for the redesigned Dynamic Island reminder card"""

        data = data or self.hud_data

        rem_type = str(data.get("type", "reminder")).lower()

        title = str(data.get("title", "")).lower()

        is_battery = "battery" in rem_type or "charger" in title or "battery" in title

        if is_battery:

            # Modern high-fidelity battery alert card with battery capsule, status tag & monochrome action buttons

            return (340, 56)

        elif rem_type in ("water", "eye_rest", "posture", "take_rest", "ventilation"):

            # Redesigned spacious horizontal wellness notification pill with Cancel & Done buttons

            return (320, 52)

        else:

            # Compact sleek horizontal system alert pill with Cancel & Action buttons

            return (320, 52)



    def get_dynamic_hud_size(self, hud_type: str = None, data: dict = None) -> Tuple[int, int]:

        """Calculates snug, content-fitted (width, height) for any Dynamic Island HUD type"""

        htype = hud_type or self.current_hud_type

        d = data if data is not None else self.hud_data



        if htype == "reminder":

            return self.get_dynamic_reminder_size(d)

        elif htype in ("activity", "downloads"):

            return self.get_dynamic_activity_size(d)

        elif htype == "media":

            return (self.get_dynamic_media_width(d), 36)

        elif htype in _SYSTEM_STATUS_TYPES:

            return measure_system_status_pill(htype, d)

        elif htype == "volume":

            return (186, 34)

        elif htype == "timer":

            lbl = d.get("label", "00:00")

            is_stopwatch = d.get("is_stopwatch", False)

            title_text = "STOPWATCH" if is_stopwatch or "stopwatch" in lbl.lower() else "TIMER"

            m_title = QFontMetrics(QFont("Segoe UI Variable Text", 7.2, QFont.Weight.Bold)).horizontalAdvance(title_text)

            m_lbl = QFontMetrics(QFont("Segoe UI Variable Text", 9.0, QFont.Weight.Bold)).horizontalAdvance(lbl)

            w = max(152, min(206, 12 + 8 + 10 + max(m_title, m_lbl) + 12 + 48 + 10))

            return (w, 36)

        elif htype == "chat":

            sender = d.get("sender", "Friend")

            msg_text = d.get("text", "")

            m_s = QFontMetrics(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold)).horizontalAdvance(sender)

            m_m = QFontMetrics(QFont("Segoe UI Variable Text", 7.8, QFont.Weight.Medium)).horizontalAdvance(msg_text)

            w = max(176, min(276, 10 + 20 + 8 + max(m_s, m_m) + 56))

            return (w, 36)

        return (168, 34)



    def on_power_changed(self, power_dict: dict) -> bool:
        """
        Receives real-time power updates. If a battery reminder is currently showing,
        automatically identify whether the charger is plugged in or unplugged,
        instantly morph the reminder into a confirmed state, play audio chime,
        and schedule auto-dismissal without forcing the user to click buttons.
        """
        if self.current_hud_type != "reminder":
            return False

        data = getattr(self, "hud_data", {}) or {}
        rem_type = str(data.get("type", "")).lower()
        title = str(data.get("title", "")).lower()
        sub_type = str(data.get("sub_type", "")).lower()
        is_battery = "battery" in rem_type or "charger" in title or "battery" in title or sub_type in ("plug_in", "unplug", "auto_plugged", "auto_unplugged")

        if not is_battery:
            return False

        plugged_in = bool(power_dict.get("plugged_in", False))
        pct = int(power_dict.get("percent", data.get("percent", 50)))

        # Case 1: Charger was just plugged in while a 'Connect Charger' reminder was showing!
        if plugged_in and ("plug_in" in sub_type or "connect" in title or "low" in title or sub_type == ""):
            data["title"] = f"Charger Connected ({pct}%)"
            data["note"] = "Battery charging safely • Health active"
            data["sub_type"] = "auto_plugged"
            data["is_auto_resolved"] = True
            data["percent"] = pct
            self.hud_data = data
            self.update()
            if hasattr(self.trigger, 'update'):
                self.trigger.update()

            try:
                import odd_sound
                odd_sound.play_charge_sound(True, self.settings)
            except Exception:
                pass

            try:
                from odd_wellness import WellnessManager
                WellnessManager.get_instance().on_power_state_changed(True, pct)
            except Exception:
                pass
            try:
                from odd_reminder import ReminderManager
                ReminderManager.get_instance().on_power_state_changed(True)
            except Exception:
                pass

            self.dismiss_timer.stop()
            self.dismiss_timer.start(2000)
            return True

        # Case 2: Charger was unplugged while an 'Unplug Charger (80%)' reminder was showing!
        elif not plugged_in and ("unplug" in sub_type or "unplug" in title or "80" in title):
            data["title"] = f"Charger Disconnected ({pct}%)"
            data["note"] = "Running on Battery • Longevity cycle saved"
            data["sub_type"] = "auto_unplugged"
            data["is_auto_resolved"] = True
            data["percent"] = pct
            self.hud_data = data
            self.update()
            if hasattr(self.trigger, 'update'):
                self.trigger.update()

            try:
                import odd_sound
                odd_sound.play_charge_sound(False, self.settings)
            except Exception:
                pass

            try:
                from odd_wellness import WellnessManager
                WellnessManager.get_instance().on_power_state_changed(False, pct)
            except Exception:
                pass
            try:
                from odd_reminder import ReminderManager
                ReminderManager.get_instance().on_power_state_changed(False)
            except Exception:
                pass

            self.dismiss_timer.stop()
            self.dismiss_timer.start(2000)
            return True

        return False

    def handle_mouse_move(self, pos: QPoint) -> bool:

        """Tracks hover state over interactive buttons in the Dynamic Island HUD"""

        old_hover = self._hovered_btn

        new_hover = None



        if self.current_hud_type == "reminder" and hasattr(self, '_reminder_buttons'):

            for btn_name in ("done", "cancel", "snooze", "reschedule", "dismiss", "context", "stop_action"):

                r = self._reminder_buttons.get(btn_name)

                if r and r.contains(pos):

                    new_hover = btn_name

                    break

        elif self.current_hud_type in ("activity", "downloads") and hasattr(self, '_activity_rects'):

            for rect, _ in self._activity_rects:

                if rect.contains(pos):

                    new_hover = "activity_item"

                    break



        if new_hover != old_hover:

            self._hovered_btn = new_hover

            self.update()

            if hasattr(self.trigger, 'update'):

                self.trigger.update()



        return new_hover is not None



    def handle_mouse_leave(self):

        """Resets hover state when cursor leaves the edge trigger window"""

        if self._hovered_btn is not None:

            self._hovered_btn = None

            self.update()

            if hasattr(self.trigger, 'update'):

                self.trigger.update()



    def handle_mouse_press(self, pos: QPoint) -> bool:

        """Handles clicks on interactive Dynamic Island HUD buttons (Stop timer, Done, Snooze, etc.)"""

        # 0. Active Stopwatch / Timer: click anywhere on HUD or Stop button to stop and reset

        if self.current_hud_type == "timer":

            try:

                import odd_sound

                odd_sound.play_preview(0.70)

            except Exception:

                pass

            mon = DynamicIslandMonitor.get_instance()

            if mon:

                mon.stop_timer()

            if hasattr(self.trigger, 'bezel_hud') and self.trigger.bezel_hud:

                self.trigger.bezel_hud.show_notification_hud("Stopped", "Stopwatch / Timer stopped", duration_ms=1500)

            self.dismiss_hud()

            return True



        # 1. Reminder interactive action buttons: Done, Cancel, Snooze, Reschedule, Attachment, Dismiss

        if self.current_hud_type == "reminder" and hasattr(self, '_reminder_buttons'):

            rem_id = self._reminder_buttons.get("id")

            title = self.hud_data.get("title", "Reminder")

            rem_type = self.hud_data.get("type", "reminder")



            # Check Cancel / Dismiss button

            r_cancel = self._reminder_buttons.get("cancel") or self._reminder_buttons.get("dismiss")

            if r_cancel and r_cancel.contains(pos):

                try:

                    import odd_sound

                    odd_sound.play_preview(0.60)

                except Exception:

                    pass

                if rem_type == "water":

                    try:

                        from odd_reminder import WaterReminderManager

                        WaterReminderManager.get_instance().dismiss()

                    except Exception:

                        pass

                elif rem_type == "eye_rest":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_eye_rest(15)

                    except Exception:

                        pass

                elif rem_type == "posture":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_posture(20)

                    except Exception:

                        pass

                elif rem_type == "ventilation":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_ventilation(30)

                    except Exception:

                        pass

                elif rem_type == "battery_health":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_battery(30)

                    except Exception:

                        pass

                self.dismiss_hud(immediate=True)

                return True



            # Check Stop / Direct Action button (Orange square from Image 3)

            r_stop = self._reminder_buttons.get("stop_action")

            if r_stop and r_stop.contains(pos):

                try:

                    import odd_sound

                    odd_sound.play_preview(0.85)

                except Exception:

                    pass

                self.dismiss_hud()

                return True



            # Check Done button

            r_done = self._reminder_buttons.get("done")

            if r_done and r_done.contains(pos):

                try:

                    import odd_sound

                    odd_sound.play_preview(0.85)

                except Exception:

                    pass

                if rem_type == "water":

                    try:

                        from odd_reminder import WaterReminderManager

                        st = WaterReminderManager.get_instance().log_drink()

                        if hasattr(self.trigger, 'bezel_hud') and self.trigger.bezel_hud:

                            l_td = st.get("liters_today", 0.0)

                            d_lt = st.get("daily_liters", 2.0)

                            pct = st.get("progress_pct", 0)

                            if st.get("is_completed"):

                                self.trigger.bezel_hud.show_notification_hud("Daily Goal Reached!", f"Completed: {l_td:.2f}L of {d_lt:.1f}L target", duration_ms=2200, app_icon=False)

                            else:

                                self.trigger.bezel_hud.show_notification_hud("Logged +250ml", f"Today: {l_td:.2f}L / {d_lt:.1f}L ({pct:.0f}%)", duration_ms=2000, app_icon=False)

                    except Exception:

                        pass

                elif rem_type == "storage_purge":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().execute_storage_cleanup()

                    except Exception:

                        pass

                elif rem_type == "battery_health":

                    if hasattr(self.trigger, 'bezel_hud'):

                        self.trigger.bezel_hud.show_notification_hud("Battery Acknowledged", "Charger status updated", duration_ms=1600, app_icon=False)

                elif rem_type in ("eye_rest", "posture", "take_rest", "ventilation"):

                    pass

                else:

                    from odd_reminder import ReminderManager

                    ReminderManager.get_instance().complete_reminder(rem_id)

                    if hasattr(self.trigger, 'bezel_hud'):

                        self.trigger.bezel_hud.show_notification_hud("Completed", f'Completed "{title}"', duration_ms=1800)

                self.dismiss_hud()

                return True



            # Check Snooze button

            r_snooze = self._reminder_buttons.get("snooze")

            if r_snooze and r_snooze.contains(pos):

                try:

                    import odd_sound

                    odd_sound.play_preview(0.70)

                except Exception:

                    pass

                if rem_type == "water":

                    try:

                        from odd_reminder import WaterReminderManager

                        WaterReminderManager.get_instance().snooze(10)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Snoozed", "Water reminder snoozed for 10 minutes", duration_ms=1800, app_icon=False)

                    except Exception:

                        pass

                elif rem_type == "eye_rest":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_eye_rest(5)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Snoozed", "Eye rest snoozed for 5 minutes", duration_ms=1800, app_icon=False)

                    except Exception:

                        pass

                elif rem_type == "posture":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_posture(10)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Snoozed", "Posture alert snoozed for 10 minutes", duration_ms=1800, app_icon=False)

                    except Exception:

                        pass

                elif rem_type == "ventilation":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_ventilation(15)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Snoozed", "Ventilation alert snoozed for 15 minutes", duration_ms=1800, app_icon=False)

                    except Exception:

                        pass

                elif rem_type == "battery_health":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_battery(15)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Snoozed", "Battery reminder snoozed for 15 minutes", duration_ms=1800, app_icon=False)

                    except Exception:

                        pass

                elif rem_type == "storage_purge":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_storage(days=1)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Snoozed", "Storage purge snoozed for 1 day", duration_ms=1800, app_icon=False)

                    except Exception:

                        pass

                else:

                    from odd_reminder import ReminderManager

                    snooze_min = int(self.settings.get("default_snooze_minutes", 5))

                    ReminderManager.get_instance().snooze_reminder(rem_id, minutes=snooze_min)

                    if hasattr(self.trigger, 'bezel_hud'):

                        self.trigger.bezel_hud.show_notification_hud("Snoozed", f'Snoozed for {snooze_min} minutes', duration_ms=1800)

                self.dismiss_hud()

                return True



            # Check Reschedule button (+1 Hour / +30m / +20m)

            r_reschedule = self._reminder_buttons.get("reschedule")

            if r_reschedule and r_reschedule.contains(pos):

                try:

                    import odd_sound

                    odd_sound.play_preview(0.70)

                except Exception:

                    pass

                if rem_type == "water":

                    try:

                        from odd_reminder import WaterReminderManager

                        WaterReminderManager.get_instance().snooze(30)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Postponed", "Water reminder postponed by 30 minutes", duration_ms=1800)

                    except Exception:

                        pass

                elif rem_type == "eye_rest":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_eye_rest(20)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Postponed", "Eye rest postponed by 20 minutes", duration_ms=1800)

                    except Exception:

                        pass

                elif rem_type == "posture":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_posture(60)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Postponed", "Posture alert postponed by 1 hour", duration_ms=1800)

                    except Exception:

                        pass

                elif rem_type == "ventilation":

                    try:

                        from odd_wellness import WellnessManager

                        WellnessManager.get_instance().snooze_ventilation(120)

                        if hasattr(self.trigger, 'bezel_hud'):

                            self.trigger.bezel_hud.show_notification_hud("Postponed", "Ventilation alert postponed by 2 hours", duration_ms=1800)

                    except Exception:

                        pass

                else:

                    from odd_reminder import ReminderManager

                    new_due = time.time() + 3600.0

                    ReminderManager.get_instance().reschedule_reminder(rem_id, new_due)

                    if hasattr(self.trigger, 'bezel_hud'):

                        self.trigger.bezel_hud.show_notification_hud("Rescheduled", "Rescheduled for +1 hour", duration_ms=1800)

                self.dismiss_hud()

                return True



            # Check Context attachment chip

            r_ctx = self._reminder_buttons.get("context")

            ctx_tgt = self._reminder_buttons.get("context_target")

            if r_ctx and r_ctx.contains(pos) and ctx_tgt:

                try:

                    if os.path.exists(ctx_tgt):

                        os.startfile(ctx_tgt)

                    elif ctx_tgt.startswith("http"):

                        import webbrowser

                        webbrowser.open(ctx_tgt)

                except Exception:

                    pass

                return True



            # Click was on the body of the reminder card

            return True



        # 2. Activity / Download item row click

        if getattr(self, '_activity_rects', None):

            for rect, target_path in self._activity_rects:

                if rect.contains(pos) and target_path:

                    try:

                        if os.path.exists(target_path):

                            os.startfile(target_path)

                        else:

                            dl_dir = os.path.expanduser("~/Downloads")

                            if os.path.exists(dl_dir):

                                os.startfile(dl_dir)

                    except Exception:

                        pass

                    return True

        return False



    def draw_blue_sphere(self, painter: QPainter, cx: float, cy: float, radius: float):

        """Paints high-end 3D glossy blue sphere with inner light and specular reflection"""

        grad = QRadialGradient(cx - radius * 0.35, cy - radius * 0.35, radius * 1.4)

        grad.setColorAt(0.0, QColor(147, 197, 253))  # #93C5FD

        grad.setColorAt(0.25, QColor(59, 130, 246))  # #3B82F6

        grad.setColorAt(0.75, QColor(29, 78, 216))   # #1D4ED8

        grad.setColorAt(1.0, QColor(30, 58, 138))    # #1E3A8A



        painter.setBrush(QBrush(grad))

        painter.setPen(Qt.PenStyle.NoPen)

        painter.drawEllipse(QPointF(cx, cy), radius, radius)



        # Specular glint highlight

        painter.setBrush(QBrush(QColor(255, 255, 255, 220)))

        painter.drawEllipse(QPointF(cx - radius * 0.35, cy - radius * 0.35), max(1.2, radius * 0.28), max(1.2, radius * 0.28))



    def draw_progress_ring(self, painter: QPainter, cx: float, cy: float, radius: float, progress: float,

                           stroke_width: float = 2.5, color: Optional[QColor] = None, bg_track: bool = True):

        """Paints smooth, anti-aliased circular progress ring"""

        rect_f = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)



        if bg_track:

            track_pen = QPen(QColor(255, 255, 255, 30), stroke_width)

            track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

            painter.setPen(track_pen)

            painter.setBrush(Qt.BrushStyle.NoBrush)

            painter.drawEllipse(rect_f)



        pct = max(0.0, min(100.0, float(progress)))

        if pct > 0:

            arc_col = color if color is not None else QColor(self.settings.get("edge_bar_color", "#FFFFFF"))

            arc_pen = QPen(arc_col, stroke_width)

            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

            painter.setPen(arc_pen)

            painter.setBrush(Qt.BrushStyle.NoBrush)

            # Start at 12 o'clock (90 * 16) and sweep clockwise (-pct * 360 * 16 / 100)

            start_angle = 90 * 16

            span_angle = int(-pct * 360.0 * 16.0 / 100.0)

            painter.drawArc(rect_f, start_angle, span_angle)



    def draw_download_indicator(self, painter: QPainter, cx: float, cy: float, radius: float, progress: float,

                                stroke_width: float = 2.0, color: Optional[QColor] = None, is_active: bool = True):

        """

        Paints high-tech dynamic circular download progress ring with streaming vector arrow

        and glowing leading bead.

        """

        pct = max(0.0, min(100.0, float(progress)))

        theme = self.settings.get("theme", "dark")

        accent = color if color is not None else (QColor(0, 229, 255) if theme != "light" else QColor(0, 150, 220))

        track_col = QColor(255, 255, 255, 32) if theme != "light" else QColor(0, 0, 0, 24)



        rect_f = QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)



        painter.save()

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)



        # 1. Background circular track

        painter.setPen(QPen(track_col, stroke_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.drawEllipse(rect_f)



        # 2. Dynamic Progress Arc with vibrant gradient & glow

        if pct > 0:

            arc_grad = QConicalGradient(cx, cy, 90.0)

            arc_grad.setColorAt(0.0, QColor(59, 130, 246))   # Blue

            arc_grad.setColorAt(0.7, accent)                 # Cyan

            arc_grad.setColorAt(1.0, QColor(147, 197, 253))  # Light blue



            arc_pen = QPen(QBrush(arc_grad), stroke_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)

            painter.setPen(arc_pen)

            start_angle = 90 * 16

            span_angle = int(-pct * 360.0 * 16.0 / 100.0)

            painter.drawArc(rect_f, start_angle, span_angle)



            # Leading Head Glow Bead at tip of arc

            if pct < 100.0:

                rad_angle = math.radians(90.0 - pct * 3.6)

                bead_x = cx + radius * math.cos(rad_angle)

                bead_y = cy - radius * math.sin(rad_angle)

                painter.setPen(Qt.PenStyle.NoPen)

                painter.setBrush(QBrush(QColor(255, 255, 255, 230)))

                painter.drawEllipse(QPointF(bead_x, bead_y), stroke_width * 0.75, stroke_width * 0.75)



        # 3. Dynamic Animated Center Indicator

        if pct >= 100.0:

            # Completed Emerald Checkmark

            chk_col = QColor(16, 185, 129)

            painter.setPen(QPen(chk_col, max(1.4, stroke_width * 0.8), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

            chk = QPainterPath()

            chk.moveTo(cx - radius * 0.40, cy + radius * 0.05)

            chk.lineTo(cx - radius * 0.10, cy + radius * 0.38)

            chk.lineTo(cx + radius * 0.46, cy - radius * 0.30)

            painter.strokePath(chk, painter.pen())

        else:

            # High-Tech Streaming Down-Arrow with Fluid Motion

            now_t = time.time()

            flow_t = (now_t * 2.2) % 1.0 if is_active else 0.5

            stream_dy = (flow_t - 0.5) * (radius * 0.45)

            alpha_pulse = int(210 + 45 * math.sin(flow_t * math.pi))



            arrow_col = QColor(255, 255, 255, alpha_pulse) if theme != "light" else QColor(20, 24, 30, alpha_pulse)

            painter.setPen(QPen(arrow_col, max(1.3, stroke_width * 0.75), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))



            tip_y = cy + radius * 0.32 + stream_dy

            top_y = cy - radius * 0.36 + stream_dy

            head_w = radius * 0.34



            # Vertical shaft

            painter.drawLine(QPointF(cx, top_y), QPointF(cx, tip_y))

            # Arrowhead

            arrow_path = QPainterPath()

            arrow_path.moveTo(cx - head_w, tip_y - head_w * 0.9)

            arrow_path.lineTo(cx, tip_y)

            arrow_path.lineTo(cx + head_w, tip_y - head_w * 0.9)

            painter.strokePath(arrow_path, painter.pen())



            # Subtle trailing pulse dot above arrow shaft

            if is_active and flow_t > 0.3:

                dot_y = top_y - radius * 0.22

                dot_alpha = int(180 * (1.0 - flow_t))

                painter.setPen(Qt.PenStyle.NoPen)

                painter.setBrush(QBrush(QColor(accent.red(), accent.green(), accent.blue(), dot_alpha)))

                painter.drawEllipse(QPointF(cx, dot_y), stroke_width * 0.5, stroke_width * 0.5)



        painter.restore()



    def mousePressEvent(self, event):

        if self.handle_mouse_press(event.pos()):

            event.accept()

            return

        super().mousePressEvent(event)



    def _get_btn_hover_progress(self, name: str) -> float:

        if not hasattr(self, "_btn_hover_progress"):

            self._btn_hover_progress = {}

        return max(0.0, min(1.0, float(self._btn_hover_progress.get(name, 0.0))))



    def show_hud(self, hud_type: str, data: dict, duration_ms: int = 2500, persistent: bool = False):

        if not self.settings.get("enable_dynamic_island", True):

            return



        if hasattr(self.trigger, "is_island_collapsing"):

            self.trigger.is_island_collapsing = False



        lock_huds = {"lock_key", "caps_lock", "num_lock", "scroll_lock"}

        if hud_type in lock_huds:

            is_on = bool(data.get("is_on", False))

            self.lock_spring.snap_to(0.0 if is_on else 1.0)

            self.lock_spring.set_target(1.0 if is_on else 0.0, preserve_velocity=False)

        elif hud_type == "mute":

            is_muted = bool(data.get("is_muted", False))

            self.mute_spring.snap_to(0.0 if is_muted else 1.0)

            self.mute_spring.set_target(1.0 if is_muted else 0.0, preserve_velocity=False)



        # Smoothly morph and transition between consecutive overlays without collapsing or colliding

        if self.trigger.is_island_expanded and not getattr(self.trigger, "is_island_collapsing", False):

            self.current_hud_type = hud_type

            self.hud_data = data

            self._hud_show_time = time.perf_counter()

            self._last_tick_time = time.perf_counter()

            self.dismiss_timer.stop()

            if not persistent and duration_ms > 0:

                self.dismiss_timer.start(duration_ms)

            self.content_reveal.snap_to(0.0 if hud_type == "reminder" else 0.35)

            self.content_reveal.set_target(1.0, preserve_velocity=True)

            if hud_type == "volume":

                v = float(data.get("volume", 50))

                self.vol_spring.set_target(v, preserve_velocity=True)

            if not self.anim_timer.isActive():

                self.anim_timer.start()

            self.trigger.morph_island(expanded=True, hud_type=hud_type)

            self.update()

            if hasattr(self.trigger, "update"):

                self.trigger.update()

            return



        self.current_hud_type = hud_type

        self.hud_data = data

        self._hud_show_time = time.perf_counter()

        if hud_type == "reminder":

            self._entrance_start_time = self._hud_show_time

        self._last_tick_time = time.perf_counter()

        self.content_reveal.snap_to(0.0 if hud_type == "reminder" else 0.30)

        self.content_reveal.set_target(1.0, preserve_velocity=True)

        if hud_type == "volume":

            v = float(data.get("volume", 50))

            self.vol_spring.set_target(v, preserve_velocity=True)



        self.dismiss_timer.stop()

        if not persistent and duration_ms > 0:

            self.dismiss_timer.start(duration_ms)



        if not self.anim_timer.isActive():

            self.anim_timer.start()



        self.trigger.morph_island(expanded=True, hud_type=hud_type)

        self.update()

        if hasattr(self.trigger, "update"):

            self.trigger.update()



    def show_chat_message(self, sender: str, text: str, ttl_sec: float = 6.0):

        """Display an ephemeral chat message in the Dynamic Island"""

        if not self.settings.get("enable_experimental_chat", True):

            return

        duration_ms = int(ttl_sec * 1000)

        self.show_hud("chat", {"sender": sender, "text": text, "ttl": ttl_sec}, duration_ms=duration_ms)



    def dismiss_hud(self, immediate: bool = False):

        if immediate:

            if hasattr(self.trigger, "is_island_collapsing"):

                self.trigger.is_island_collapsing = False

            self.current_hud_type = None

            self.hud_data = {}

            self.content_reveal.snap_to(0.0)

            if self.anim_timer.isActive() and not self.trigger.has_active_media_playing():

                self.anim_timer.stop()

            self.trigger.morph_island(expanded=False)

            self.update()

            if hasattr(self.trigger, "update"):

                self.trigger.update()

            return



        if not self.current_hud_type and not getattr(self.trigger, 'is_island_collapsing', False):

            return

        if getattr(self.trigger, 'is_island_collapsing', False):

            return

        self._collapse_start_time = time.perf_counter()

        self.content_reveal.set_target(0.0, preserve_velocity=True)

        self.trigger.morph_island(expanded=False)



    def _on_anim_tick(self):

        now = time.perf_counter()

        dt = min(0.04, max(0.001, now - getattr(self, '_last_tick_time', now)))

        self._last_tick_time = now

        self.vol_spring.update(dt)

        self.lock_spring.update(dt)

        self.mute_spring.update(dt)

        self.content_reveal.update(dt)



        if not hasattr(self, "_btn_hover_progress"):

            self._btn_hover_progress = {"cancel": 0.0, "done": 0.0}

        target_cancel = 1.0 if self._hovered_btn == "cancel" else 0.0

        self._btn_hover_progress["cancel"] += (target_cancel - self._btn_hover_progress.get("cancel", 0.0)) * 0.25

        target_done = 1.0 if self._hovered_btn == "done" else 0.0

        self._btn_hover_progress["done"] += (target_done - self._btn_hover_progress.get("done", 0.0)) * 0.25



        self.eq_phase += 0.14

        if self.eq_phase > 1000.0:

            self.eq_phase = 0.0



        if self.settings.get("enable_vinyl_rotation", True):

            is_playing = self.hud_data.get("is_playing", True) if self.current_hud_type == "media" else False

            if is_playing:

                self.vinyl_angle = (self.vinyl_angle + 1.5) % 360.0



        self.update()

        if hasattr(self.trigger, "update"):

            self.trigger.update()



    def paint_island_content(self, painter: QPainter, rect: QRect):

        try:

            self._do_paint_island_content(painter, rect)

        except Exception:

            pass



    def _do_paint_island_content(self, painter: QPainter, rect: QRect):

        """Paints clean, modern Dynamic Island HUD content with zero emojis"""

        if not self.current_hud_type:

            return



        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)



        # Animate.css animate__bounceOutUp exit kinematics

        if getattr(self.trigger, "is_island_collapsing", False):

            import odd_animated_buttons

            now = time.perf_counter()

            elapsed = now - getattr(self, "_collapse_start_time", now)

            out_t = min(1.0, elapsed / 0.40)

            sx, sy, dy, out_op = odd_animated_buttons.get_bounceoutup_transform(out_t, float(rect.height()))

            cx = rect.center().x()

            cy = rect.center().y()

            painter.translate(cx, cy + dy)

            painter.scale(sx, sy)

            painter.translate(-cx, -cy)



        theme = str(self.settings.get("theme", "dark")).lower()

        text_col = QColor(255, 255, 255, 240) if theme != "light" else QColor(20, 20, 20, 240)

        sub_col = QColor(255, 255, 255, 140) if theme != "light" else QColor(90, 90, 90, 180)

        accent_col = QColor(self.settings.get("edge_bar_color", "#FFFFFF"))

        media_style = self.settings.get("island_media_style", "vinyl")



        # ---------------- 1. MEDIA TRACK & EQUALIZER HUD ----------------

        if self.current_hud_type == "media":

            title = self.hud_data.get("title", "Media Playing") or "Media Playing"

            artist = self.hud_data.get("artist", "") or ""

            thumb_bytes = self.hud_data.get("thumbnail_bytes", None)



            # Left Art / Rotating Vinyl Disc

            if media_style == "vinyl":

                disc_r = 10.0

                disc_cx = float(rect.left() + 8 + disc_r)

                disc_cy = float(rect.top() + rect.height() / 2.0)



                painter.save()

                painter.translate(disc_cx, disc_cy)

                painter.rotate(self.vinyl_angle)



                # Outer Vinyl Record Body

                painter.setBrush(QBrush(QColor(18, 18, 20)))

                painter.setPen(QPen(QColor(55, 55, 60), 0.8))

                painter.drawEllipse(QPointF(0, 0), disc_r, disc_r)



                # Concentric Vinyl Grooves

                painter.setBrush(Qt.BrushStyle.NoBrush)

                painter.setPen(QPen(QColor(255, 255, 255, 22), 0.6))

                painter.drawEllipse(QPointF(0, 0), disc_r - 2.5, disc_r - 2.5)

                painter.drawEllipse(QPointF(0, 0), disc_r - 5.0, disc_r - 5.0)



                # Center Label (Rotating Album Art)

                label_r = 4.5

                drawn_label = False

                if thumb_bytes:

                    pix = QPixmap()

                    if pix.loadFromData(thumb_bytes):

                        scaled = pix.scaled(int(label_r * 2), int(label_r * 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)

                        label_path = QPainterPath()

                        label_path.addEllipse(QPointF(0, 0), label_r, label_r)

                        painter.save()

                        painter.setClipPath(label_path)

                        painter.drawPixmap(int(-label_r), int(-label_r), scaled)

                        painter.restore()

                        drawn_label = True



                if not drawn_label:

                    painter.setBrush(QBrush(accent_col))

                    painter.setPen(Qt.PenStyle.NoPen)

                    painter.drawEllipse(QPointF(0, 0), label_r, label_r)



                # Center Spindle Hole

                painter.setBrush(QBrush(QColor(12, 12, 14)))

                painter.setPen(QPen(QColor(255, 255, 255, 80), 0.5))

                painter.drawEllipse(QPointF(0, 0), 1.2, 1.2)



                painter.restore()



                icon_w = int(disc_r * 2)

                icon_x = rect.left() + 8

            else:

                # Modern Pill: Sleek squircle thumbnail

                icon_w = 18

                icon_x = rect.left() + 8

                icon_y = rect.top() + (rect.height() - icon_w) // 2



                drawn_thumb = False

                if thumb_bytes:

                    pix = QPixmap()

                    if pix.loadFromData(thumb_bytes):

                        scaled = pix.scaled(icon_w, icon_w, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)

                        thumb_path = QPainterPath()

                        thumb_path.addRoundedRect(icon_x, icon_y, icon_w, icon_w, 4, 4)

                        painter.save()

                        painter.setClipPath(thumb_path)

                        painter.drawPixmap(icon_x, icon_y, scaled)

                        painter.restore()

                        drawn_thumb = True



                if not drawn_thumb:

                    painter.setBrush(QBrush(accent_col))

                    painter.setPen(Qt.PenStyle.NoPen)

                    painter.drawRoundedRect(icon_x, icon_y, icon_w, icon_w, 4, 4)



                    tri = QPainterPath()

                    tri.moveTo(icon_x + 6, icon_y + 4.5)

                    tri.lineTo(icon_x + 13, icon_y + 9)

                    tri.lineTo(icon_x + 6, icon_y + 13.5)

                    tri.closeSubpath()

                    painter.fillPath(tri, QBrush(QColor(0, 0, 0) if theme != "light" else QColor(255, 255, 255)))



            # Right: Dynamic 4-bar equalizer (snug right border, 0 empty void)

            eq_w = 22

            eq_x = rect.right() - eq_w - 8

            eq_y = rect.top() + (rect.height() - 14) // 2

            for i in range(4):

                bar_h = max(3, int(3 + 8 * (math.sin(self.eq_phase + i * 1.3) ** 2)))

                bx = eq_x + i * 5.5

                by = eq_y + (14 - bar_h) // 2

                painter.setBrush(QBrush(accent_col))

                painter.setPen(Qt.PenStyle.NoPen)

                painter.drawRoundedRect(int(bx), int(by), 3, bar_h, 1.5, 1.5)



            # Center: Title & Artist clean stacked typography

            text_x = icon_x + icon_w + 8

            avail_w = max(30, eq_x - text_x - 6)



            metrics_title = QFontMetrics(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))

            elided_title = metrics_title.elidedText(title, Qt.TextElideMode.ElideRight, avail_w)



            if artist and media_style != "minimal":

                metrics_artist = QFontMetrics(QFont("Segoe UI Variable Text", 6.5))

                elided_artist = metrics_artist.elidedText(artist, Qt.TextElideMode.ElideRight, avail_w)



                painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))

                painter.setPen(text_col)

                painter.drawText(text_x, rect.top() + 12, elided_title)



                painter.setFont(QFont("Segoe UI Variable Text", 6.5))

                painter.setPen(sub_col)

                painter.drawText(text_x, rect.top() + 23, elided_artist)

            else:

                painter.setFont(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.DemiBold))

                painter.setPen(text_col)

                painter.drawText(QRect(text_x, rect.top(), avail_w, rect.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)



        # ---------------- 2. VOLUME LEVEL SLIDER HUD ----------------

        elif self.current_hud_type == "volume":

            # Vector Speaker Icon on the left

            spk_cx = rect.left() + 18

            spk_cy = rect.top() + rect.height() / 2.0

            spk_horn = QPainterPath()

            spk_horn.moveTo(spk_cx - 4.5, spk_cy - 2.0)

            spk_horn.lineTo(spk_cx - 2.0, spk_cy - 2.0)

            spk_horn.lineTo(spk_cx + 1.5, spk_cy - 4.2)

            spk_horn.lineTo(spk_cx + 1.5, spk_cy + 4.2)

            spk_horn.lineTo(spk_cx - 2.0, spk_cy + 2.0)

            spk_horn.lineTo(spk_cx - 4.5, spk_cy + 2.0)

            spk_horn.closeSubpath()

            painter.setBrush(QBrush(accent_col))

            painter.setPen(Qt.PenStyle.NoPen)

            painter.fillPath(spk_horn, painter.brush())



            painter.setBrush(Qt.BrushStyle.NoBrush)

            painter.setPen(QPen(accent_col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

            painter.drawArc(QRectF(spk_cx + 2.5, spk_cy - 3.5, 4.0, 7.0), -50 * 16, 100 * 16)



            # Progress Bar Slider (Smooth Spring-driven Liquid Gliding)

            bar_x = rect.left() + 34

            bar_w = max(10, rect.width() - 80)

            bar_h = 6.0

            bar_y = rect.top() + (rect.height() - bar_h) / 2.0

            r_bar = bar_h / 2.0



            painter.setBrush(QBrush(QColor(255, 255, 255, 25) if theme != "light" else QColor(0, 0, 0, 25)))

            painter.setPen(Qt.PenStyle.NoPen)

            painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), r_bar, r_bar)



            vol_val = self.vol_spring.value

            if vol_val > 0:

                fill_w = max(bar_h, bar_w * (vol_val / 100.0))

                painter.setBrush(QBrush(accent_col))

                painter.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), r_bar, r_bar)



            # Percentage Text

            painter.setFont(QFont("Segoe UI Variable Text", 8.2, QFont.Weight.DemiBold))

            painter.setPen(text_col)

            disp_pct = int(round(vol_val))

            painter.drawText(

                QRect(int(bar_x + bar_w + 6), rect.top(), 40, rect.height()),

                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,

                f"{disp_pct}%",

            )



        # ---------------- 3. FAST SNAPPY COPY / PASTE HUD ----------------

        elif self.current_hud_type == "clip":

            action = self.hud_data.get("action", "COPIED").upper()

            chars = self.hud_data.get("chars", 0)

            preview = self.hud_data.get("preview", "")



            # Action Pill Tag (Full Rounded Pill)

            badge_w = 54.0

            badge_h = 16.0

            badge_x = rect.left() + 14.0

            badge_y = rect.top() + (rect.height() - badge_h) / 2.0

            r_badge = badge_h / 2.0

            

            painter.setBrush(QBrush(accent_col))

            painter.setPen(Qt.PenStyle.NoPen)

            painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), r_badge, r_badge)



            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))

            painter.setPen(QColor(0, 0, 0) if theme != "light" else QColor(255, 255, 255))

            painter.drawText(QRect(int(badge_x), int(badge_y), int(badge_w), int(badge_h)), Qt.AlignmentFlag.AlignCenter, action)



            # Preview / Character counter

            painter.setFont(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.Medium))

            painter.setPen(text_col)

            p_str = f'"{preview if len(preview) <= 22 else preview[:20] + "…"}"' if preview else f"{chars} characters"

            painter.drawText(

                QRect(int(badge_x + badge_w + 10), rect.top(), rect.width() - int(badge_x + badge_w + 20), rect.height()),

                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,

                p_str,

            )



        # ---------------- 4. ROOK SHORTCUT INDICATION HUD ----------------

        elif self.current_hud_type == "rook":

            action_name = self.hud_data.get("action", "Rook Action")

            shortcut_key = self.hud_data.get("key", "")



            # ROOK Mini Badge (Full Rounded Pill)

            badge_w = 44.0

            badge_h = 16.0

            badge_x = rect.left() + 14.0

            badge_y = rect.top() + (rect.height() - badge_h) / 2.0

            r_badge = badge_h / 2.0



            painter.setBrush(QBrush(QColor(168, 85, 247, 45))) # Purple accent

            painter.setPen(QPen(QColor(168, 85, 247, 180), 1.0))

            painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), r_badge, r_badge)



            painter.setFont(QFont("Segoe UI Variable Text", 7.5, QFont.Weight.Bold))

            painter.setPen(QColor(168, 85, 247))

            painter.drawText(QRect(int(badge_x), int(badge_y), int(badge_w), int(badge_h)), Qt.AlignmentFlag.AlignCenter, "ROOK")



            # Action Label

            painter.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.DemiBold))

            painter.setPen(text_col)

            painter.drawText(

                QRect(int(badge_x + badge_w + 10), rect.top(), rect.width() - int(badge_x + badge_w + 20), rect.height()),

                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,

                action_name,

            )



            # Shortcut Key Chip (Right side, Full Rounded Pill)

            if shortcut_key:

                chip_w = 54.0

                chip_h = 16.0

                chip_x = rect.right() - chip_w - 14.0

                chip_y = rect.top() + (rect.height() - chip_h) / 2.0

                r_chip = chip_h / 2.0



                painter.setBrush(QBrush(QColor(0, 0, 0, 15) if theme == "light" else QColor(255, 255, 255, 12)))

                painter.setPen(QPen(QColor(0, 0, 0, 30) if theme == "light" else QColor(255, 255, 255, 25), 1.0))

                painter.drawRoundedRect(QRectF(chip_x, chip_y, chip_w, chip_h), r_chip, r_chip)



                painter.setFont(QFont("Segoe UI Variable Text", 7.5, QFont.Weight.Medium))

                painter.setPen(sub_col)

                painter.drawText(QRect(int(chip_x), int(chip_y), int(chip_w), int(chip_h)), Qt.AlignmentFlag.AlignCenter, shortcut_key)



        # ---------------- 5. SYSTEM STATUS PILL (CAPS / NUM LOCK / AUDIO MUTE / BATTERY) ----------------

        elif self.current_hud_type in _SYSTEM_STATUS_TYPES:

            now_t = time.perf_counter()

            elapsed_t = now_t - getattr(self, "_hud_show_time", now_t)

            is_on = bool(self.hud_data.get("is_on", False))

            if elapsed_t < 0.45:

                anim_dy = (-2.6 if is_on else 2.4) * math.exp(-7.5 * elapsed_t) * math.sin(elapsed_t * 16.0)

            else:

                anim_dy = 0.0

            mute_t = max(0.0, min(1.0, self.mute_spring.value))

            paint_system_status_pill_content(

                painter,

                QRectF(rect),

                self.current_hud_type,

                self.hud_data,

                anim_dy=anim_dy,

                mute_t=mute_t,

            )



        # ---------------- 6. TIMER & STOPWATCH TICKER HUD ----------------

        elif self.current_hud_type == "timer":

            lbl = self.hud_data.get("label", "00:00")

            is_stopwatch = self.hud_data.get("is_stopwatch", False)

            title_text = "STOPWATCH" if is_stopwatch or "stopwatch" in lbl.lower() else "TIMER"



            # Left: Orange/cyan timer indicator dot

            dot_x = rect.left() + 12

            dot_y = rect.top() + (rect.height() - 7) // 2

            dot_col = QColor(245, 158, 11) if is_stopwatch else accent_col

            painter.setBrush(QBrush(dot_col))

            painter.setPen(Qt.PenStyle.NoPen)

            painter.drawEllipse(dot_x, dot_y, 7, 7)



            painter.setFont(QFont("Segoe UI Variable Text", 7.0, QFont.Weight.Bold))

            painter.setPen(sub_col)

            painter.drawText(dot_x + 12, rect.top() + 13, title_text)



            painter.setFont(QFont("Segoe UI Variable Text", 9.0, QFont.Weight.Bold))

            painter.setPen(accent_col if not is_stopwatch else QColor(255, 255, 255))

            painter.drawText(dot_x + 12, rect.top() + 25, lbl)



            # Interactive Stop button on the right (Full Rounded Pill)

            stop_w, stop_h = 46.0, 19.0

            stop_x = rect.right() - stop_w - 8.0

            stop_y = rect.top() + (rect.height() - stop_h) / 2.0

            stop_rect = QRectF(stop_x, stop_y, stop_w, stop_h)



            # Subtle translucent stop badge

            painter.setBrush(QBrush(QColor(239, 68, 68, 45)))

            painter.setPen(QPen(QColor(239, 68, 68, 140), 0.8))

            painter.drawRoundedRect(stop_rect, stop_h / 2.0, stop_h / 2.0)



            # Stop icon and text: "Stop"

            painter.setFont(QFont("Segoe UI Variable Text", 7.5, QFont.Weight.DemiBold))

            painter.setPen(QColor(248, 113, 113))

            painter.drawText(stop_rect, Qt.AlignmentFlag.AlignCenter, "Stop")



        # ---------------- 7. LIVE ACTIVITIES & DOWNLOAD MODE (ULTRA-MINIMAL) ----------------

        elif self.current_hud_type in ("activity", "downloads"):

            self._activity_rects = []

            active_items = self.hud_data.get("active_items", [])

            all_items = self.hud_data.get("all_items", [])

            items_to_render = (active_items if active_items else all_items)[:3]

            count = len(items_to_render)



            if count <= 1:

                # SINGLE DOWNLOAD / TASK — Sleek, compact Apple Dynamic Island capsule

                item = items_to_render[0] if items_to_render else {}

                raw_t = getattr(item, 'title', '') if hasattr(item, 'title') else (item.get('title', '') if isinstance(item, dict) else 'Download')

                title = format_download_filename(raw_t, 24)

                subtitle = getattr(item, 'subtitle', '') if hasattr(item, 'subtitle') else (item.get('subtitle', '') if isinstance(item, dict) else '')

                prog = getattr(item, 'progress', 0.0) if hasattr(item, 'progress') else (item.get('progress', 0.0) if isinstance(item, dict) else 0.0)

                status = getattr(item, 'status', 'active') if hasattr(item, 'status') else (item.get('status', 'active') if isinstance(item, dict) else 'active')

                icon_type = getattr(item, 'icon_type', 'download') if hasattr(item, 'icon_type') else (item.get('icon_type', 'download') if isinstance(item, dict) else 'download')



                center_y = rect.center().y()



                # Left: Minimal Progress Ring or 3D Blue Sphere

                icon_cx = rect.left() + 18

                if status == "completed":

                    painter.setBrush(QBrush(QColor(16, 185, 129)))

                    painter.setPen(Qt.PenStyle.NoPen)

                    painter.drawEllipse(icon_cx - 5.5, center_y - 5.5, 11, 11)

                    painter.setPen(QPen(QColor(255, 255, 255), 1.4))

                    painter.drawLine(icon_cx - 2.5, center_y, icon_cx - 0.8, center_y + 1.8)

                    painter.drawLine(icon_cx - 0.8, center_y + 1.8, icon_cx + 2.5, center_y - 1.8)

                elif icon_type == "blue_sphere" or "install" in title.lower():

                    self.draw_blue_sphere(painter, icon_cx, center_y, 5.5)

                else:

                    self.draw_download_indicator(painter, icon_cx, center_y, radius=7.0, progress=prog, stroke_width=1.9, color=accent_col, is_active=(status == "active"))



                # Right: Pure text percentage or "Done" (No buttons, no chips)

                if status == "completed":

                    pct_str = "Done"

                    painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))

                    painter.setPen(QColor(16, 185, 129))

                else:

                    pct_str = f"{int(round(prog))}%"

                    painter.setFont(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.Bold))

                    painter.setPen(accent_col)



                metrics_pct = QFontMetrics(painter.font())

                pct_w = metrics_pct.horizontalAdvance(pct_str)

                pct_x = rect.right() - pct_w - 16

                painter.drawText(pct_x, center_y + 3, pct_str)



                # Middle: Title + Speed/Subtitle (Compact typography)

                text_left = rect.left() + 32

                avail_title_w = pct_x - text_left - 10

                painter.setFont(QFont("Segoe UI Variable Text", 8.2, QFont.Weight.DemiBold))

                painter.setPen(text_col)

                metrics_title = QFontMetrics(painter.font())



                if subtitle and "•" in subtitle:

                    elided_title = metrics_title.elidedText(title, Qt.TextElideMode.ElideRight, avail_title_w)

                    painter.drawText(text_left, rect.top() + 15, elided_title)



                    painter.setFont(QFont("Segoe UI Variable Text", 6.8))

                    painter.setPen(sub_col)

                    speed_only = subtitle.split("•")[-1].strip() if "•" in subtitle else subtitle

                    painter.drawText(text_left, rect.top() + 26, speed_only)

                else:

                    elided_title = metrics_title.elidedText(title, Qt.TextElideMode.ElideRight, avail_title_w)

                    painter.drawText(text_left, center_y + 3, elided_title)



                # Bottom: Hairline 2.0px progress track

                bar_x = rect.left() + 16

                bar_y = rect.bottom() - 4

                bar_w = rect.width() - 32

                bar_h = 2.0



                painter.setBrush(QBrush(QColor(255, 255, 255, 15) if theme != "light" else QColor(0, 0, 0, 15)))

                painter.setPen(Qt.PenStyle.NoPen)

                painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 1.0, 1.0)



                if prog > 0:

                    fill_w = max(3.0, bar_w * (min(100.0, float(prog)) / 100.0))

                    bar_grad = QLinearGradient(bar_x, bar_y, bar_x + fill_w, bar_y)

                    if status == "completed":

                        bar_grad.setColorAt(0.0, QColor(16, 185, 129))

                        bar_grad.setColorAt(1.0, QColor(52, 211, 153))

                    else:

                        bar_grad.setColorAt(0.0, QColor(59, 130, 246))

                        bar_grad.setColorAt(1.0, accent_col)

                    painter.setBrush(QBrush(bar_grad))

                    painter.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 1.0, 1.0)



            else:

                # MULTIPLE DOWNLOADS — Clean minimalist list

                row_h = (rect.height() - 8) // count

                for idx, item in enumerate(items_to_render):

                    curr_y = rect.top() + 4 + idx * row_h

                    center_row_y = curr_y + row_h // 2



                    raw_t = getattr(item, 'title', '') if hasattr(item, 'title') else (item.get('title', '') if isinstance(item, dict) else 'Download')

                    title = format_download_filename(raw_t, 22)

                    subtitle = getattr(item, 'subtitle', '') if hasattr(item, 'subtitle') else (item.get('subtitle', '') if isinstance(item, dict) else '')

                    prog = getattr(item, 'progress', 0.0) if hasattr(item, 'progress') else (item.get('progress', 0.0) if isinstance(item, dict) else 0.0)

                    status = getattr(item, 'status', 'active') if hasattr(item, 'status') else (item.get('status', 'active') if isinstance(item, dict) else 'active')

                    icon_type = getattr(item, 'icon_type', 'download') if hasattr(item, 'icon_type') else (item.get('icon_type', 'download') if isinstance(item, dict) else 'download')



                    # Left Icon

                    icon_cx = rect.left() + 16

                    if status == "completed":

                        painter.setBrush(QBrush(QColor(16, 185, 129)))

                        painter.setPen(Qt.PenStyle.NoPen)

                        painter.drawEllipse(icon_cx - 4.5, center_row_y - 4.5, 9, 9)

                        painter.setPen(QPen(QColor(255, 255, 255), 1.2))

                        painter.drawLine(icon_cx - 2, center_row_y, icon_cx - 0.6, center_row_y + 1.4)

                        painter.drawLine(icon_cx - 0.6, center_row_y + 1.4, icon_cx + 2, center_row_y - 1.4)

                    elif icon_type == "blue_sphere" or "install" in title.lower():

                        self.draw_blue_sphere(painter, icon_cx, center_row_y, 4.5)

                    else:

                        self.draw_download_indicator(painter, icon_cx, center_row_y, radius=5.6, progress=prog, stroke_width=1.5, color=accent_col, is_active=(status == "active"))



                    # Right percentage / status text

                    if status == "completed":

                        pct_str = "Done"

                        painter.setFont(QFont("Segoe UI Variable Text", 7.2, QFont.Weight.DemiBold))

                        painter.setPen(QColor(16, 185, 129))

                    else:

                        pct_str = f"{int(round(prog))}%"

                        painter.setFont(QFont("Segoe UI Variable Text", 7.8, QFont.Weight.Bold))

                        painter.setPen(accent_col)



                    metrics_pct = QFontMetrics(painter.font())

                    pct_w = metrics_pct.horizontalAdvance(pct_str)

                    pct_x = rect.right() - pct_w - 14

                    painter.drawText(pct_x, center_row_y + 3, pct_str)



                    # Middle: Title

                    text_left = rect.left() + 28

                    avail_title_w = pct_x - text_left - 8

                    painter.setFont(QFont("Segoe UI Variable Text", 7.5, QFont.Weight.Medium))

                    painter.setPen(text_col)

                    metrics_title = QFontMetrics(painter.font())

                    elided_title = metrics_title.elidedText(title, Qt.TextElideMode.ElideRight, avail_title_w)

                    painter.drawText(text_left, center_row_y + 3, elided_title)



                    # Thin hairline under each item

                    if idx < count - 1:

                        bar_x = text_left

                        bar_y = curr_y + row_h - 1

                        bar_w = rect.width() - 44

                        painter.setBrush(QBrush(QColor(255, 255, 255, 12) if theme != "light" else QColor(0, 0, 0, 12)))

                        painter.setPen(Qt.PenStyle.NoPen)

                        painter.drawRect(QRectF(bar_x, bar_y, bar_w, 1.0))



        # ---------------- 8. BUILT-IN DYNAMIC ISLAND REMINDER NOTIFICATION ----------------

        elif self.current_hud_type == "reminder":

            self._reminder_buttons = {}

            import odd_animated_buttons

            now = time.perf_counter()

            elapsed = now - getattr(self, "_entrance_start_time", getattr(self, "_hud_show_time", now))

            t = elapsed / 0.75

            if t < 0.50:

                headshake_dx = odd_animated_buttons.get_headshake_offset(t)

                if abs(headshake_dx) > 0.01:

                    painter.translate(headshake_dx, 0.0)

            data = getattr(self, "hud_data", {}) or {}

            rem_id = data.get("id", "")

            title = str(self.hud_data.get("title", "Reminder")).strip()

            note = str(self.hud_data.get("note", "")).strip()

            rem_type = str(self.hud_data.get("type", "reminder")).lower()



            # Clean any emojis out of title and note to maintain strict minimalism

            import re

            title = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27bf\ud83c-\ud83e]', '', title).strip()

            note = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27bf\ud83c-\ud83e]', '', note).strip()



            is_wellness = rem_type in ("water", "eye_rest", "posture", "take_rest", "ventilation")

            hover_pos = getattr(self.trigger, "_mouse_local_pos", None)



            # =========================================================================

            # COMPACT SLEEK WELLNESS NOTIFICATION PILL (Height 42px)

            # =========================================================================

            # =========================================================================

            # REDESIGNED MONOCHROME WELLNESS NOTIFICATION PILL (Height 52px, Width 320px)

            # =========================================================================

            if is_wellness:

                # Pure Monochrome Palette (Zero orange, zero blur, crisp Nothing / Apple aesthetic)

                fg_col = QColor(250, 250, 250) if theme != "light" else QColor(15, 17, 21)

                sub_col = QColor(165, 165, 175) if theme != "light" else QColor(115, 118, 128)

                icon_cx = rect.left() + 24

                icon_cy = rect.center().y()



                # Left Monochrome Vector Icon

                if rem_type == "water":

                    # Minimalist water drop outline with clean ripple line

                    painter.setPen(QPen(fg_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

                    painter.setBrush(Qt.BrushStyle.NoBrush)

                    drp = QPainterPath()

                    drp.moveTo(icon_cx, icon_cy - 7.0)

                    drp.cubicTo(icon_cx + 5.5, icon_cy - 0.5, icon_cx + 6.0, icon_cy + 4.5, icon_cx, icon_cy + 7.0)

                    drp.cubicTo(icon_cx - 6.0, icon_cy + 4.5, icon_cx - 5.5, icon_cy - 0.5, icon_cx, icon_cy - 7.0)

                    painter.strokePath(drp, painter.pen())

                    painter.drawEllipse(QPointF(icon_cx, icon_cy + 2.0), 2.2, 1.2)

                    label_txt = "Hydration Check"

                    try:

                        l_today = float(data.get("liters_today") or 0.0)

                    except (ValueError, TypeError):

                        l_today = 0.0

                    try:

                        d_liters = float(data.get("daily_liters") or 2.0)

                    except (ValueError, TypeError):

                        d_liters = 2.0

                    if data.get("is_completed", False):

                        hint_txt = f"{l_today:.2f}L / {d_liters:.1f}L  •  Goal Met!"

                    else:

                        hint_txt = f"{l_today:.2f}L / {d_liters:.1f}L  •  Take a sip"



                elif rem_type == "eye_rest":

                    # Minimalist optical nerve / eye vector

                    painter.setPen(QPen(fg_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

                    painter.setBrush(Qt.BrushStyle.NoBrush)

                    eye_path = QPainterPath()

                    eye_path.moveTo(icon_cx - 7.0, icon_cy)

                    eye_path.quadTo(icon_cx, icon_cy - 5.5, icon_cx + 7.0, icon_cy)

                    eye_path.quadTo(icon_cx, icon_cy + 5.5, icon_cx - 7.0, icon_cy)

                    painter.strokePath(eye_path, painter.pen())

                    painter.setPen(Qt.PenStyle.NoPen)

                    painter.setBrush(QBrush(fg_col))

                    painter.drawEllipse(QPointF(icon_cx, icon_cy), 2.4, 2.4)

                    label_txt = "Eye Rest (1 hr)"

                    hint_txt = "Look 20 ft away for 20s"



                elif rem_type in ("posture", "take_rest"):

                    # Minimalist upright spine & shoulder alignment vector

                    painter.setPen(QPen(fg_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

                    painter.setBrush(Qt.BrushStyle.NoBrush)

                    # Head

                    painter.drawEllipse(QPointF(icon_cx, icon_cy - 5.5), 1.8, 1.8)

                    # Spine and shoulders

                    painter.drawLine(QPointF(icon_cx, icon_cy - 3.2), QPointF(icon_cx, icon_cy + 6.0))

                    painter.drawLine(QPointF(icon_cx - 5.0, icon_cy - 1.0), QPointF(icon_cx + 5.0, icon_cy - 1.0))

                    painter.drawPoint(QPointF(icon_cx - 4.5, icon_cy + 3.0))

                    painter.drawPoint(QPointF(icon_cx + 4.5, icon_cy + 3.0))

                    label_txt = "Posture & Stretch"

                    hint_txt = "Roll shoulders back & stretch"



                else: # ventilation / fresh air

                    # Minimalist fresh air window / breeze vector

                    painter.setPen(QPen(fg_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

                    painter.setBrush(Qt.BrushStyle.NoBrush)

                    ww = 13.0

                    wh = 13.0

                    wx = icon_cx - ww / 2.0

                    wy = icon_cy - wh / 2.0

                    painter.drawRoundedRect(QRectF(wx, wy, ww, wh), 2.0, 2.0)

                    painter.drawLine(QPointF(icon_cx, wy), QPointF(icon_cx, wy + wh))

                    painter.drawLine(QPointF(wx, icon_cy), QPointF(wx + ww, icon_cy))

                    label_txt = "Fresh Air Reset"

                    hint_txt = "Crack a window & breathe"



                # Right Action Buttons: [ Cancel ] [ Done ]

                btn_h = 24

                btn_y = icon_cy - btn_h // 2

                btn_cancel_w = 60

                btn_done_w = 56

                btn_done_x = rect.right() - btn_done_w - 10

                btn_cancel_x = btn_done_x - btn_cancel_w - 6



                rect_done = QRect(btn_done_x, btn_y, btn_done_w, btn_h)

                rect_cancel = QRect(btn_cancel_x, btn_y, btn_cancel_w, btn_h)



                is_hover_done = (self._hovered_btn == "done")

                is_hover_cancel = (self._hovered_btn == "cancel")



                # 1. Uiverse.io KhaledMatalkah Dual Split-Curtain Wipe Cancel Button

                p_cancel = self._get_btn_hover_progress("cancel")

                odd_animated_buttons.paint_split_wipe_cancel_button(

                    painter, QRectF(rect_cancel), "Cancel", hover_progress=p_cancel, theme=theme, font_size=7.4

                )

                self._reminder_buttons["cancel"] = rect_cancel



                # 2. Uiverse.io iZOXVL .boton-elegante Action / Done Button with radial bloom

                p_done = self._get_btn_hover_progress("done")

                done_text = "Done" if rem_type != "water" else "Log"

                odd_animated_buttons.paint_boton_elegante(

                    painter, QRectF(rect_done), done_text, hover_progress=p_done, theme=theme, font_size=7.4

                )

                self._reminder_buttons["done"] = rect_done

                self._reminder_buttons["id"] = rem_id



                # Center Typography: Title + Subtitle

                text_left = icon_cx + 20

                text_avail_w = max(20, btn_cancel_x - text_left - 8)



                painter.setFont(QFont("Segoe UI Variable Display", 8.4, QFont.Weight.DemiBold))

                painter.setPen(fg_col)

                metrics_t = QFontMetrics(painter.font())

                elided_t = metrics_t.elidedText(label_txt, Qt.TextElideMode.ElideRight, text_avail_w)

                painter.drawText(QRect(text_left, rect.top() + 10, text_avail_w, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_t)



                painter.setFont(QFont("Segoe UI Variable Text", 7.0, QFont.Weight.Normal))

                painter.setPen(sub_col)

                metrics_h = QFontMetrics(painter.font())

                elided_h = metrics_h.elidedText(hint_txt, Qt.TextElideMode.ElideRight, text_avail_w)

                painter.drawText(QRect(text_left, rect.top() + 27, text_avail_w, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_h)



            # =========================================================================

            # REDESIGNED MONOCHROME BATTERY ALERT HUD (Height 56px, Width 340px)

            # =========================================================================

            elif "battery" in rem_type or "charger" in title.lower() or "battery" in title.lower():
                sub_type = str(self.hud_data.get("sub_type", "")).lower()
                is_auto_resolved = bool(self.hud_data.get("is_auto_resolved", False))
                is_unplug = ("unplug" in sub_type or "unplug" in title.lower() or "80" in title)
                is_charging = (sub_type in ("auto_plugged", "charging") or ("charge" in title.lower() and "unplug" not in title.lower()))
                pct = int(self.hud_data.get("percent", 80 if is_unplug else 20))

                fg_col = QColor(250, 250, 250) if theme != "light" else QColor(15, 17, 21)
                sub_col = QColor(165, 165, 175) if theme != "light" else QColor(115, 118, 128)

                if is_charging:
                    tag_text = "CHARGING" if is_auto_resolved else "HEALTH CHARGE"
                    display_title = self.hud_data.get("title", f"Charger Connected ({pct}%)")
                    display_desc = self.hud_data.get("note", "Battery charging safely • Health active")
                    btn_done_text = "Charging"
                    accent_col = QColor(16, 185, 129)
                elif is_auto_resolved and sub_type == "auto_unplugged":
                    tag_text = "HEALTH PROTECTED"
                    display_title = self.hud_data.get("title", f"Charger Disconnected ({pct}%)")
                    display_desc = self.hud_data.get("note", "Running on Battery • Longevity cycle saved")
                    btn_done_text = "Unplugged"
                    accent_col = QColor(16, 185, 129)
                elif is_unplug:
                    tag_text = "HEALTH 80%"
                    display_title = f"Unplug Charger ({pct}%)"
                    display_desc = "Optimal charge reached • Health protection"
                    btn_done_text = "Unplugged"
                    accent_col = QColor(16, 185, 129)
                else:
                    tag_text = "LOW BATTERY"
                    display_title = f"Connect Charger ({pct}%)"
                    display_desc = "Plug in charger • Low battery reserve"
                    btn_done_text = "Plugged In"
                    accent_col = QColor(245, 158, 11) if pct > 15 else QColor(239, 68, 68)

                # 1. Left Battery Capsule Indicator (with dynamic glow & bolt)
                icon_cx = rect.left() + 24
                icon_cy = rect.center().y()
                bw = 26.0
                bh = 15.0
                bx = icon_cx - bw / 2.0 - 1.0
                by = icon_cy - bh / 2.0

                # Outer Battery Shell
                shell_col = accent_col if (is_charging or pct <= 20) else fg_col
                painter.setPen(QPen(shell_col, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.setBrush(QBrush(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 20) if (is_charging or pct <= 20) else (QColor(255, 255, 255, 12) if theme != "light" else QColor(0, 0, 0, 8))))
                painter.drawRoundedRect(QRectF(bx, by, bw, bh), 3.0, 3.0)

                # Positive Terminal Nipple
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(shell_col))
                painter.drawRoundedRect(QRectF(bx + bw + 0.8, icon_cy - 3.0, 1.6, 6.0), 0.8, 0.8)

                # Interior Fill Level
                fill_max_w = bw - 4.4
                fill_w = max(3.0, min(fill_max_w, fill_max_w * (pct / 100.0)))
                painter.setBrush(QBrush(shell_col))
                painter.drawRoundedRect(QRectF(bx + 2.2, by + 2.2, fill_w, bh - 4.4), 1.8, 1.8)

                # Charging lightning bolt
                if is_charging:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor(255, 255, 255) if theme != "light" else QColor(20, 20, 20)))
                    bolt = QPainterPath()
                    bolt.moveTo(bx + bw / 2.0 + 0.5, icon_cy - 3.0)
                    bolt.lineTo(bx + bw / 2.0 - 1.6, icon_cy + 0.2)
                    bolt.lineTo(bx + bw / 2.0 - 0.2, icon_cy + 0.2)
                    bolt.lineTo(bx + bw / 2.0 - 0.7, icon_cy + 3.0)
                    bolt.lineTo(bx + bw / 2.0 + 1.6, icon_cy - 0.2)
                    bolt.lineTo(bx + bw / 2.0 + 0.2, icon_cy - 0.2)
                    bolt.closeSubpath()
                    painter.drawPath(bolt)

                # 2. Right Action Buttons: [ Cancel ] [ Unplugged / Plugged In / Charging ]
                btn_done_w = 74
                btn_cancel_w = 56
                btn_h = 24
                btn_y = icon_cy - btn_h // 2

                btn_done_x = rect.right() - btn_done_w - 10
                btn_cancel_x = btn_done_x - btn_cancel_w - 6

                rect_done = QRect(btn_done_x, btn_y, btn_done_w, btn_h)
                rect_cancel = QRect(btn_cancel_x, btn_y, btn_cancel_w, btn_h)

                is_hover_done = (self._hovered_btn == "done")
                is_hover_cancel = (self._hovered_btn == "cancel")

                p_cancel = self._get_btn_hover_progress("cancel")
                odd_animated_buttons.paint_split_wipe_cancel_button(
                    painter, QRectF(rect_cancel), "Cancel", hover_progress=p_cancel, theme=theme, font_size=7.4
                )
                self._reminder_buttons["cancel"] = rect_cancel

                p_done = self._get_btn_hover_progress("done")
                odd_animated_buttons.paint_boton_elegante(
                    painter, QRectF(rect_done), btn_done_text, hover_progress=p_done, theme=theme, font_size=7.4
                )
                self._reminder_buttons["done"] = rect_done
                self._reminder_buttons["id"] = rem_id

                # 3. Center Typography: Tag + Headline + Subtitle
                text_left = icon_cx + 22
                text_avail_w = max(40, btn_cancel_x - text_left - 8)

                # Category Tag Pill
                tag_font = QFont("Segoe UI Variable Text", 6.0, QFont.Weight.Bold)
                painter.setFont(tag_font)
                metrics_tag = QFontMetrics(tag_font)
                tag_w = metrics_tag.horizontalAdvance(tag_text) + 8
                tag_rect = QRectF(text_left, rect.top() + 9, tag_w, 13)

                painter.setPen(QPen(accent_col, 0.75))
                painter.setBrush(QBrush(QColor(accent_col.red(), accent_col.green(), accent_col.blue(), 25)))
                painter.drawRoundedRect(tag_rect, 3.5, 3.5)

                painter.setPen(accent_col)
                painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)



                # Headline

                title_x = int(tag_rect.right() + 6)

                title_w = max(20, btn_cancel_x - title_x - 6)

                painter.setFont(QFont("Segoe UI Variable Display", 8.4, QFont.Weight.DemiBold))

                painter.setPen(fg_col)

                metrics_t = QFontMetrics(painter.font())

                elided_t = metrics_t.elidedText(display_title, Qt.TextElideMode.ElideRight, title_w)

                painter.drawText(QRect(title_x, rect.top() + 7, title_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_t)



                # Subtitle

                painter.setFont(QFont("Segoe UI Variable Text", 6.8, QFont.Weight.Normal))

                painter.setPen(sub_col)

                metrics_d = QFontMetrics(painter.font())

                elided_d = metrics_d.elidedText(display_desc, Qt.TextElideMode.ElideRight, text_avail_w)

                painter.drawText(QRect(text_left, rect.top() + 27, text_avail_w, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_d)



            # =========================================================================

            # REDESIGNED MONOCHROME AUTOPILOT & SYSTEM ALERT NOTIFICATION PILL

            # =========================================================================

            else:

                fg_col = QColor(250, 250, 250) if theme != "light" else QColor(15, 17, 21)

                sub_col = QColor(165, 165, 175) if theme != "light" else QColor(115, 118, 128)



                icon_cx = rect.left() + 24

                icon_cy = rect.center().y()



                painter.setPen(QPen(fg_col, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

                painter.setBrush(Qt.BrushStyle.NoBrush)

                bell = QPainterPath()

                bell.moveTo(icon_cx - 4.5, icon_cy + 3.0)

                bell.lineTo(icon_cx + 4.5, icon_cy + 3.0)

                bell.quadTo(icon_cx + 3.8, icon_cy - 1.0, icon_cx + 2.5, icon_cy - 4.2)

                bell.quadTo(icon_cx, icon_cy - 6.0, icon_cx - 2.5, icon_cy - 4.2)

                bell.quadTo(icon_cx - 3.8, icon_cy - 1.0, icon_cx - 4.5, icon_cy + 3.0)

                bell.closeSubpath()

                painter.strokePath(bell, painter.pen())

                painter.drawPoint(QPointF(icon_cx, icon_cy + 5.0))



                # Buttons: [ Cancel ] [ Action ]

                btn_done_w = 56

                btn_cancel_w = 56

                btn_h = 24

                btn_y = icon_cy - btn_h // 2



                btn_done_x = rect.right() - btn_done_w - 10

                btn_cancel_x = btn_done_x - btn_cancel_w - 6



                rect_done = QRect(btn_done_x, btn_y, btn_done_w, btn_h)

                rect_cancel = QRect(btn_cancel_x, btn_y, btn_cancel_w, btn_h)



                is_hover_done = (self._hovered_btn == "done")

                is_hover_cancel = (self._hovered_btn == "cancel")



                # 1. Uiverse.io KhaledMatalkah Dual Split-Curtain Wipe Cancel Button

                p_cancel = self._get_btn_hover_progress("cancel")

                odd_animated_buttons.paint_split_wipe_cancel_button(

                    painter, QRectF(rect_cancel), "Cancel", hover_progress=p_cancel, theme=theme, font_size=7.4

                )

                self._reminder_buttons["cancel"] = rect_cancel



                # 2. Action Button (or Recycle Bin Clear Expand Button for storage purge)

                p_done = self._get_btn_hover_progress("done")

                is_storage_purge = ("storage" in rem_type or "recycle" in title.lower() or "purge" in title.lower())

                if is_storage_purge:

                    # Uiverse.io vinodjangid07 Recycle Bin Clear Expand Button

                    odd_animated_buttons.paint_recycle_bin_clear_button(

                        painter, QRectF(rect_done), hover_progress=p_done, text="Delete"

                    )

                else:

                    # Uiverse.io iZOXVL .boton-elegante Action Button with radial bloom

                    odd_animated_buttons.paint_boton_elegante(

                        painter, QRectF(rect_done), "Got it", hover_progress=p_done, theme=theme, font_size=7.4

                    )

                self._reminder_buttons["done"] = rect_done

                self._reminder_buttons["id"] = rem_id



                # Typography: Title + Subtitle

                text_left = icon_cx + 20

                text_avail_w = max(20, btn_cancel_x - text_left - 8)

                display_title = title if title else "Notice"

                display_desc = note if note else display_title



                painter.setFont(QFont("Segoe UI Variable Display", 8.4, QFont.Weight.DemiBold))

                painter.setPen(fg_col)

                metrics_t = QFontMetrics(painter.font())

                elided_t = metrics_t.elidedText(display_title, Qt.TextElideMode.ElideRight, text_avail_w)

                painter.drawText(QRect(text_left, rect.top() + 10, text_avail_w, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_t)



                painter.setFont(QFont("Segoe UI Variable Text", 6.9, QFont.Weight.Normal))

                painter.setPen(sub_col)

                metrics_d = QFontMetrics(painter.font())

                elided_d = metrics_d.elidedText(display_desc, Qt.TextElideMode.ElideRight, text_avail_w)

                painter.drawText(QRect(text_left, rect.top() + 27, text_avail_w, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_d)



        # ---------------- 9. EPHEMERAL CHAT MESSAGE HUD ----------------

        elif self.current_hud_type == "chat":

            sender = self.hud_data.get("sender", "Friend")

            msg_text = self.hud_data.get("text", "")



            # Left: Vector Chat Bubble Icon with ambient glow

            icon_w = 20

            icon_x = rect.left() + 10

            icon_y = rect.top() + (rect.height() - icon_w) // 2



            painter.setBrush(QBrush(QColor(0, 229, 255, 35)))

            painter.setPen(QPen(QColor(0, 229, 255, 180), 1.0))

            painter.drawRoundedRect(icon_x, icon_y, icon_w, icon_w, 6, 6)



            # Draw tiny chat bubble vector

            painter.setPen(QPen(QColor(0, 229, 255), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

            painter.setBrush(Qt.BrushStyle.NoBrush)

            cx = icon_x + icon_w / 2.0

            cy = icon_y + icon_w / 2.0 - 0.5

            painter.drawRoundedRect(QRectF(cx - 5.0, cy - 4.0, 10.0, 7.5), 2.0, 2.0)

            painter.drawLine(int(cx - 2.5), int(cy + 3.5), int(cx - 4.5), int(cy + 6.0))

            painter.drawLine(int(cx - 4.5), int(cy + 6.0), int(cx - 0.5), int(cy + 3.5))



            # Right: Ephemeral vanishing indicator badge (e.g. "VANISH")

            vanish_x = rect.right() - 56

            painter.setFont(QFont("Segoe UI Variable Text", 6.8, QFont.Weight.Bold))

            painter.setPen(QColor(16, 185, 129))

            painter.drawText(QRect(vanish_x, rect.top(), 46, rect.height()), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "EPHEMERAL")



            # Center Typography

            text_x = icon_x + icon_w + 10

            avail_w = max(40, vanish_x - text_x - 8)



            # Sender tag

            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))

            painter.setPen(accent_col)

            metrics_sender = QFontMetrics(painter.font())

            painter.drawText(text_x, rect.top() + 12, metrics_sender.elidedText(sender, Qt.TextElideMode.ElideRight, avail_w))



            # Message text (Vanishing)

            painter.setFont(QFont("Segoe UI Variable Text", 7.8, QFont.Weight.Medium))

            painter.setPen(text_col)

            metrics_msg = QFontMetrics(painter.font())

            painter.drawText(text_x, rect.top() + 23, metrics_msg.elidedText(msg_text, Qt.TextElideMode.ElideRight, avail_w))









