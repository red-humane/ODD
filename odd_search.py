import os
import sys
import json
import time
import math
import re
import datetime
import calendar
import subprocess
import webbrowser
import urllib.parse
import threading
import socket
import ctypes
import glob
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Callable, Optional, Tuple, Dict, Any

try:
    import odd_messaging
except Exception:
    pass
try:
    import odd_reminder
except Exception:
    pass
try:
    import odd_camera
except Exception:
    pass

def open_system_calendar():
    """Launches the default Windows Calendar or Outlook Calendar, with web fallback"""
    try:
        subprocess.Popen('start outlookcal:', shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        try:
            subprocess.Popen('start ms-calendar:', shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            try:
                webbrowser.open("https://calendar.google.com")
            except Exception:
                pass

def generate_month_calendar_text(year: int, month: int, highlight_day: Optional[int] = None) -> str:
    """Generates clean ASCII/Unicode month calendar grid with weekday headers and highlighted day"""
    cal_sun = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    m_name = calendar.month_name[month]
    header = f"{m_name} {year}"
    lines = [f"{header.center(20)}", "Su Mo Tu We Th Fr Sa"]
    for week in cal_sun:
        row = []
        for d in week:
            if d == 0:
                row.append("  ")
            elif highlight_day and d == highlight_day:
                row.append(f"{d:2d}")
            else:
                row.append(f"{d:2d}")
        lines.append(" ".join(row))
    return "\n".join(lines)

APPS_CACHE_FILE = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\apps_cache.json"))
FILES_CACHE_FILE = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\files_cache.json"))
FOLDERS_CACHE_FILE = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\folders_cache.json"))
CLIPBOARD_CACHE_FILE = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\clipboard_history.json"))
NOTES_FILE = Path(os.path.expandvars(r"%APPDATA%\ODD\notes.json"))

_last_cpu_sample = {"idle": 0, "kernel": 0, "user": 0, "pct": 0.0, "time": 0.0}

def get_system_resource_info() -> Dict[str, Any]:
    """Returns real-time CPU % and RAM % using lightweight Win32 APIs in < 0.05ms without blocking sleeps"""
    global _last_cpu_sample
    ram_pct = 0.0
    ram_used_gb = 0.0
    ram_total_gb = 0.0
    cpu_pct = _last_cpu_sample["pct"]
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            ram_pct = float(stat.dwMemoryLoad)
            total_b = stat.ullTotalPhys
            avail_b = stat.ullAvailPhys
            used_b = total_b - avail_b
            ram_used_gb = used_b / (1024 ** 3)
            ram_total_gb = total_b / (1024 ** 3)
    except Exception:
        pass

    try:
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint), ("dwHighDateTime", ctypes.c_uint)]
        def _to_int(ft):
            return (ft.dwHighDateTime << 32) + ft.dwLowDateTime

        cur_idle, cur_kernel, cur_user = FILETIME(), FILETIME(), FILETIME()
        kernel32 = ctypes.windll.kernel32
        if kernel32.GetSystemTimes(ctypes.byref(cur_idle), ctypes.byref(cur_kernel), ctypes.byref(cur_user)):
            i_val = _to_int(cur_idle)
            k_val = _to_int(cur_kernel)
            u_val = _to_int(cur_user)
            now = time.time()
            if _last_cpu_sample["time"] > 0:
                idle_delta = i_val - _last_cpu_sample["idle"]
                kernel_delta = k_val - _last_cpu_sample["kernel"]
                user_delta = u_val - _last_cpu_sample["user"]
                sys_time = kernel_delta + user_delta
                if sys_time > 0:
                    cpu_pct = max(0.0, min(100.0, ((sys_time - idle_delta) * 100.0) / sys_time))
                    _last_cpu_sample["pct"] = cpu_pct
            _last_cpu_sample["idle"] = i_val
            _last_cpu_sample["kernel"] = k_val
            _last_cpu_sample["user"] = u_val
            _last_cpu_sample["time"] = now
    except Exception:
        pass

    return {
        "cpu_pct": round(cpu_pct, 1),
        "ram_pct": round(ram_pct, 1),
        "ram_used_gb": round(ram_used_gb, 1),
        "ram_total_gb": round(ram_total_gb, 1)
    }

def get_network_info() -> Dict[str, str]:
    """Returns local network IPv4 address and computer hostname"""
    hostname = socket.gethostname()
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            ip = socket.gethostbyname(hostname)
        except Exception:
            pass
    return {"ip": ip, "hostname": hostname}

def trigger_island_timer(label: str, duration_sec: int, is_stopwatch: bool = False):
    """Triggers live Dynamic Island countdown timer or stopwatch ticker"""
    try:
        from odd_island import DynamicIslandMonitor
        mon = DynamicIslandMonitor.get_instance()
        if mon:
            mon.trigger_timer(label, duration_sec, is_stopwatch=is_stopwatch)
    except Exception:
        pass

def start_island_stopwatch(label: str = "Stopwatch"):
    """Starts a count-up stopwatch ticking in Dynamic Island"""
    try:
        from odd_island import DynamicIslandMonitor
        mon = DynamicIslandMonitor.get_instance()
        if mon:
            mon.start_stopwatch(label)
    except Exception:
        pass

def stop_island_timer(timer_id: Optional[str] = None):
    """Stops active stopwatch or countdown timer in Dynamic Island"""
    try:
        from odd_island import DynamicIslandMonitor
        mon = DynamicIslandMonitor.get_instance()
        if mon:
            mon.stop_timer(timer_id)
    except Exception:
        pass

def get_active_island_timers() -> dict:
    """Returns currently active timers and stopwatches"""
    try:
        from odd_island import DynamicIslandMonitor
        mon = DynamicIslandMonitor.get_instance()
        if mon:
            return mon.get_active_timers()
    except Exception:
        pass
    return {}


def format_file_size(size_bytes: Optional[int]) -> str:
    if size_bytes is None or size_bytes < 0:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def get_file_category(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "PDF"
    elif ext in (".doc", ".docx", ".txt", ".rtf", ".odt", ".xlsx", ".xls", ".csv", ".pptx", ".ppt", ".md", ".epub", ".log"):
        return "DOC"
    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".tiff", ".psd"):
        return "IMAGE"
    elif ext in (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus"):
        return "AUDIO"
    elif ext in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v"):
        return "VIDEO"
    elif ext in (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab"):
        return "ARCHIVE"
    elif ext in (".py", ".js", ".ts", ".html", ".css", ".json", ".cpp", ".c", ".h", ".cs", ".java", ".rs", ".go", ".php", ".sql", ".sh", ".bat", ".ps1", ".toml", ".yaml", ".yml", ".xml"):
        return "CODE"
    return "FILE"

def query_windows_search(search_term: str, limit: int = 15, type_filter: Optional[str] = None) -> List[Tuple[str, str, str, str]]:
    """
    Query Windows Desktop Search (WSearch Collator DSO) in real-time.
    Returns: List of (name, path, category, subtitle)
    """
    clean_q = search_term.replace("'", "''").replace("%", "").replace("*", "").strip()
    if not clean_q:
        return []
    
    results = []
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            conn = win32com.client.Dispatch("ADODB.Connection")
            conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
            
            where_clause = f"SCOPE='file:' AND System.ItemNameDisplay LIKE '%{clean_q}%'"
            if type_filter == "pdf":
                where_clause += " AND System.ItemType = '.pdf'"
            elif type_filter == "folder":
                where_clause += " AND System.ItemType = 'Directory'"
            elif type_filter == "doc":
                where_clause += " AND (System.ItemType = '.pdf' OR System.ItemType = '.docx' OR System.ItemType = '.doc' OR System.ItemType = '.txt' OR System.ItemType = '.xlsx' OR System.ItemType = '.xls' OR System.ItemType = '.pptx' OR System.ItemType = '.ppt' OR System.ItemType = '.md' OR System.ItemType = '.csv')"
            elif type_filter == "img":
                where_clause += " AND (System.ItemType = '.png' OR System.ItemType = '.jpg' OR System.ItemType = '.jpeg' OR System.ItemType = '.gif' OR System.ItemType = '.webp' OR System.ItemType = '.svg' OR System.ItemType = '.bmp')"
            elif type_filter == "audio":
                where_clause += " AND (System.ItemType = '.mp3' OR System.ItemType = '.wav' OR System.ItemType = '.flac' OR System.ItemType = '.m4a' OR System.ItemType = '.aac' OR System.ItemType = '.ogg')"
            elif type_filter == "video":
                where_clause += " AND (System.ItemType = '.mp4' OR System.ItemType = '.mkv' OR System.ItemType = '.avi' OR System.ItemType = '.mov' OR System.ItemType = '.wmv' OR System.ItemType = '.webm')"

            sql = f"SELECT TOP {limit} System.ItemNameDisplay, System.ItemPathDisplay, System.ItemType, System.Size FROM SYSTEMINDEX WHERE {where_clause}"
            
            rs = win32com.client.Dispatch("ADODB.Recordset")
            rs.Open(sql, conn)
            while not rs.EOF:
                name = str(rs.Fields("System.ItemNameDisplay").Value or "")
                path = str(rs.Fields("System.ItemPathDisplay").Value or "")
                itype = str(rs.Fields("System.ItemType").Value or "").lower()
                size_val = rs.Fields("System.Size").Value
                size_int = int(size_val) if size_val is not None else None
                
                if path and os.path.exists(path):
                    is_dir = (itype == "directory" or os.path.isdir(path))
                    cat = "FOLDER" if is_dir else get_file_category(name)
                    
                    parent_dir = os.path.dirname(path)
                    size_str = format_file_size(size_int)
                    if is_dir:
                        sub = f"Folder • in {parent_dir}"
                    else:
                        sub = f"{cat} • {size_str} • in {parent_dir}" if size_str else f"{cat} • in {parent_dir}"
                    
                    results.append((name, path, cat, sub))
                rs.MoveNext()
            rs.Close()
            conn.Close()
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        pass
    return results


@dataclass
class SearchItem:
    id: str
    title: str
    subtitle: str
    category: str
    target: str
    action: Optional[Callable] = None
    icon: Optional[str] = None
    score: int = 0
    extra: Optional[Dict[str, Any]] = None

def copy_to_clipboard(text: str):
    """Zero-overhead Win32 / Qt clipboard copy helper"""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            cb = app.clipboard()
            cb.setText(text)
            if hasattr(ClipboardManager, 'instance') and ClipboardManager.instance:
                ClipboardManager.instance.add_clip(text, source="ODD")
            return
    except Exception:
        pass
    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if user32.OpenClipboard(0):
            user32.EmptyClipboard()
            h_cd = kernel32.GlobalAlloc(0x0042, (len(text) + 1) * 2)
            ptr = kernel32.GlobalLock(h_cd)
            ctypes.cdll.msvcrt.wcscpy(ctypes.c_wchar_p(ptr), text)
            kernel32.GlobalUnlock(h_cd)
            user32.SetClipboardData(13, h_cd)
            user32.CloseClipboard()
            if hasattr(ClipboardManager, 'instance') and ClipboardManager.instance:
                ClipboardManager.instance.add_clip(text, source="ODD")
            return
    except Exception:
        pass
    try:
        subprocess.Popen(f'powershell -WindowStyle Hidden -command Set-Clipboard -Value "{text}"', shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def paste_to_active_window(text: str):
    """Copies text to clipboard, hides search capsule, and simulates direct Ctrl+V paste."""
    copy_to_clipboard(text)
    user32 = ctypes.windll.user32
    def do_paste():
        try:
            VK_CONTROL = 0x11
            VK_V = 0x56
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 2, 0)
            user32.keybd_event(VK_CONTROL, 0, 2, 0)
        except Exception:
            pass
    from PySide6.QtCore import QTimer
    QTimer.singleShot(90, do_paste)

class ClipboardManager:
    instance = None

    def __init__(self, max_items: int = 30):
        ClipboardManager.instance = self
        self.max_items = max_items
        self.history: List[dict] = []
        self.on_clip_event: Optional[Callable] = None
        self._load()
        self._last_clip = ""
        self._last_seq = 0
        self._last_watched_sig = ""
        self._start_watcher()

    def _load(self):
        try:
            if CLIPBOARD_CACHE_FILE.exists():
                with open(CLIPBOARD_CACHE_FILE, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
                    if not isinstance(self.history, list):
                        self.history = []
        except Exception:
            self.history = []

    def _save(self):
        try:
            CLIPBOARD_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CLIPBOARD_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history[:self.max_items], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_clip(self, text: str, source: str = "System"):
        if not text or not text.strip():
            return
        text_clean = text.strip()
        if len(text_clean) > 50000:
            return  # Skip huge binary dumps

        is_link = text_clean.startswith(("http://", "https://", "www.")) or (len(text_clean) < 255 and "." in text_clean and " " not in text_clean and ("/" in text_clean or text_clean.endswith((".com", ".org", ".net", ".io", ".dev", ".edu", ".app"))))
        is_files = text_clean.startswith("[Files]") or text_clean.startswith("::files::")
        was_pinned = any(item.get("pinned", False) for item in self.history if item.get("text") == text_clean)

        # Deduplicate recent identical item
        self.history = [item for item in self.history if item.get("text") != text_clean]
        self.history.insert(0, {
            "text": text_clean,
            "timestamp": time.strftime("%H:%M"),
            "chars": len(text_clean),
            "source": source,
            "is_link": is_link,
            "is_files": is_files,
            "pinned": was_pinned
        })
        self.history = self.history[:self.max_items]
        self._last_clip = text_clean
        self._save()

    def toggle_pin(self, text_or_id: str) -> bool:
        clean = str(text_or_id).strip()
        for item in self.history:
            if item.get("text") == clean or clean in (item.get("text", "")[:32], str(self.history.index(item))):
                item["pinned"] = not item.get("pinned", False)
                self._save()
                return item["pinned"]
        return False

    def clear(self):
        self.history = []
        self._save()

    def _start_watcher(self):
        # System clipboard changes are handled by QApplication.clipboard() in
        # main.py. A second native polling thread used raw GlobalLock pointers
        # and could access clipboard memory after another process replaced it,
        # producing intermittent access violations during UI startup.
        # Keep this method as a no-op for compatibility with existing callers.
        return

# Notes & Tasks Manager
class NotesManager:
    @staticmethod
    def load_notes() -> List[dict]:
        try:
            if NOTES_FILE.exists():
                with open(NOTES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
        except Exception:
            pass
        return []

    @staticmethod
    def save_notes(notes: List[dict]):
        try:
            NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(NOTES_FILE, "w", encoding="utf-8") as f:
                json.dump(notes, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def add_note(text: str) -> str:
        notes = NotesManager.load_notes()
        note_id = str(int(time.time() * 1000))
        notes.insert(0, {
            "id": note_id,
            "text": text.strip(),
            "date": time.strftime("%b %d, %H:%M"),
            "done": False
        })
        NotesManager.save_notes(notes[:50])
        return note_id

    @staticmethod
    def delete_note(note_id: str):
        notes = NotesManager.load_notes()
        notes = [n for n in notes if n.get("id") != note_id]
        NotesManager.save_notes(notes)

    @staticmethod
    def clear_notes():
        NotesManager.save_notes([])

    @staticmethod
    def toggle_note(note_id: str):
        notes = NotesManager.load_notes()
        for n in notes:
            if n.get("id") == note_id:
                n["done"] = not n.get("done", False)
        NotesManager.save_notes(notes)

# Initialize clipboard singleton
clipboard_mgr = ClipboardManager()

# Unit & Currency Conversion Engine
CURRENCY_RATES = {
    "usd": 1.0,
    "eur": 0.92,
    "gbp": 0.79,
    "inr": 86.5,
    "jpy": 154.2,
    "cad": 1.38,
    "aud": 1.55,
    "cny": 7.24,
    "chf": 0.89,
    "sgd": 1.35,
    "nzd": 1.68,
    "aed": 3.67,
    "sar": 3.75,
    "brl": 5.75,
    "krw": 1390.0,
    "rub": 96.0,
    "mxn": 20.4,
    "try": 35.2
}

UNIT_FACTORS = {
    # Length (base: meter)
    "m": ("length", 1.0, "Meters"),
    "meter": ("length", 1.0, "Meters"),
    "meters": ("length", 1.0, "Meters"),
    "km": ("length", 1000.0, "Kilometers"),
    "kilometer": ("length", 1000.0, "Kilometers"),
    "kilometers": ("length", 1000.0, "Kilometers"),
    "cm": ("length", 0.01, "Centimeters"),
    "centimeter": ("length", 0.01, "Centimeters"),
    "centimeters": ("length", 0.01, "Centimeters"),
    "mm": ("length", 0.001, "Millimeters"),
    "millimeter": ("length", 0.001, "Millimeters"),
    "millimeters": ("length", 0.001, "Millimeters"),
    "mi": ("length", 1609.344, "Miles"),
    "mile": ("length", 1609.344, "Miles"),
    "miles": ("length", 1609.344, "Miles"),
    "yd": ("length", 0.9144, "Yards"),
    "yard": ("length", 0.9144, "Yards"),
    "yards": ("length", 0.9144, "Yards"),
    "ft": ("length", 0.3048, "Feet"),
    "foot": ("length", 0.3048, "Feet"),
    "feet": ("length", 0.3048, "Feet"),
    "in": ("length", 0.0254, "Inches"),
    "inch": ("length", 0.0254, "Inches"),
    "inches": ("length", 0.0254, "Inches"),

    # Mass / Weight (base: kg)
    "kg": ("mass", 1.0, "Kilograms"),
    "kilogram": ("mass", 1.0, "Kilograms"),
    "kilograms": ("mass", 1.0, "Kilograms"),
    "g": ("mass", 0.001, "Grams"),
    "gram": ("mass", 0.001, "Grams"),
    "grams": ("mass", 0.001, "Grams"),
    "mg": ("mass", 0.000001, "Milligrams"),
    "milligram": ("mass", 0.000001, "Milligrams"),
    "milligrams": ("mass", 0.000001, "Milligrams"),
    "lb": ("mass", 0.45359237, "Pounds"),
    "lbs": ("mass", 0.45359237, "Pounds"),
    "pound": ("mass", 0.45359237, "Pounds"),
    "pounds": ("mass", 0.45359237, "Pounds"),
    "oz": ("mass", 0.028349523, "Ounces"),
    "ounce": ("mass", 0.028349523, "Ounces"),
    "ounces": ("mass", 0.028349523, "Ounces"),
    "ton": ("mass", 1000.0, "Metric Tons"),
    "tons": ("mass", 1000.0, "Metric Tons"),

    # Digital Storage (base: Megabyte)
    "b": ("data", 1 / (1024 * 1024), "Bytes"),
    "byte": ("data", 1 / (1024 * 1024), "Bytes"),
    "bytes": ("data", 1 / (1024 * 1024), "Bytes"),
    "kb": ("data", 1 / 1024, "Kilobytes"),
    "mb": ("data", 1.0, "Megabytes"),
    "gb": ("data", 1024.0, "Gigabytes"),
    "tb": ("data", 1024.0 * 1024.0, "Terabytes"),
    "pb": ("data", 1024.0 * 1024.0 * 1024.0, "Petabytes"),

    # Time (base: seconds)
    "s": ("time", 1.0, "Seconds"),
    "sec": ("time", 1.0, "Seconds"),
    "seconds": ("time", 1.0, "Seconds"),
    "min": ("time", 60.0, "Minutes"),
    "mins": ("time", 60.0, "Minutes"),
    "minute": ("time", 60.0, "Minutes"),
    "minutes": ("time", 60.0, "Minutes"),
    "hr": ("time", 3600.0, "Hours"),
    "hrs": ("time", 3600.0, "Hours"),
    "hour": ("time", 3600.0, "Hours"),
    "hours": ("time", 3600.0, "Hours"),
    "day": ("time", 86400.0, "Days"),
    "days": ("time", 86400.0, "Days"),
    "week": ("time", 604800.0, "Weeks"),
    "weeks": ("time", 604800.0, "Weeks"),
    "month": ("time", 2592000.0, "Months"),
    "months": ("time", 2592000.0, "Months"),
    "year": ("time", 31536000.0, "Years"),
    "years": ("time", 31536000.0, "Years"),

    # Speed (base: km/h)
    "kmh": ("speed", 1.0, "km/h"),
    "km/h": ("speed", 1.0, "km/h"),
    "mph": ("speed", 1.609344, "mph"),
    "mps": ("speed", 3.6, "m/s"),
    "m/s": ("speed", 3.6, "m/s"),
    "knot": ("speed", 1.852, "Knots"),
    "knots": ("speed", 1.852, "Knots"),

    # Area (base: sqm)
    "sqm": ("area", 1.0, "m²"),
    "sqft": ("area", 0.092903, "sq ft"),
    "sqkm": ("area", 1000000.0, "km²"),
    "sqmi": ("area", 2589988.11, "sq mi"),
    "acre": ("area", 4046.86, "Acres"),
    "acres": ("area", 4046.86, "Acres"),
    "ha": ("area", 10000.0, "Hectares"),
    "hectare": ("area", 10000.0, "Hectares")
}

def parse_unit_conversion(query: str) -> Optional[Tuple[str, str]]:
    q = query.strip().lower()
    if q.startswith("convert:"):
        q = q[8:].strip()
    
    # Check temperature conversions (c to f, f to c, c to k, etc.)
    temp_match = re.match(r"^([\-\+]?\d+(?:\.\d+)?)\s*(?:°\s*)?([cfk]|celsius|fahrenheit|kelvin)\s*(?:to|in)\s*(?:°\s*)?([cfk]|celsius|fahrenheit|kelvin)$", q)
    if temp_match:
        val = float(temp_match.group(1))
        u1 = temp_match.group(2)[0]
        u2 = temp_match.group(3)[0]
        # Convert u1 to Celsius first
        if u1 == 'c':
            c_val = val
        elif u1 == 'f':
            c_val = (val - 32) * 5 / 9
        else: # k
            c_val = val - 273.15
        # Convert Celsius to u2
        if u2 == 'c':
            res = c_val
            unit_name = "°C"
        elif u2 == 'f':
            res = c_val * 9 / 5 + 32
            unit_name = "°F"
        else: # k
            res = c_val + 273.15
            unit_name = "K"
        formatted = f"{res:g}" if abs(res - round(res, 2)) < 1e-4 else f"{res:.2f}"
        return f"{formatted} {unit_name}", f"{val} °{u1.upper()} = {formatted} {unit_name}"

    # General number unit1 (to|in) unit2
    m = re.match(r"^([\-\+]?\d+(?:\.\d+)?)\s*([a-zA-Z\/\$€£¥₹]+)\s*(?:to|in|=)\s*([a-zA-Z\/\$€£¥₹]+)$", q)
    if not m:
        m = re.match(r"^([\-\+]?\d+(?:\.\d+)?)\s*([a-zA-Z\/\$€£¥₹]+)\s+([a-zA-Z\/\$€£¥₹]+)$", q)
    if not m:
        return None

    val_str, u1, u2 = m.group(1), m.group(2).lower(), m.group(3).lower()
    try:
        val = float(val_str)
    except ValueError:
        return None

    # Currency symbol mapping
    sym_map = {"$": "usd", "€": "eur", "£": "gbp", "¥": "jpy", "₹": "inr"}
    u1 = sym_map.get(u1, u1)
    u2 = sym_map.get(u2, u2)

    # Check Currency
    if u1 in CURRENCY_RATES and u2 in CURRENCY_RATES:
        usd_val = val / CURRENCY_RATES[u1]
        res = usd_val * CURRENCY_RATES[u2]
        res_str = f"{res:,.2f} {u2.upper()}"
        return res_str, f"{val:,.2f} {u1.upper()} = {res_str} (Rate: 1 {u1.upper()} ~ {CURRENCY_RATES[u2]/CURRENCY_RATES[u1]:.4f} {u2.upper()})"

    # Check Standard Units
    if u1 in UNIT_FACTORS and u2 in UNIT_FACTORS:
        cat1, f1, name1 = UNIT_FACTORS[u1]
        cat2, f2, name2 = UNIT_FACTORS[u2]
        if cat1 == cat2:
            base_val = val * f1
            res = base_val / f2
            res_str = f"{res:g}" if abs(res - round(res, 4)) < 1e-6 else f"{res:.4f}"
            return f"{res_str} {name2}", f"{val:g} {name1} = {res_str} {name2}"

    return None

def trigger_desktop_timer(duration_sec: int, label: str):
    def _timer_worker():
        time.sleep(duration_sec)
        try:
            import odd_sound
            odd_sound.play_preview(0.95)
        except Exception:
            pass
        try:
            # Windows PowerShell notification toast
            msg = f"Timer complete: {label} ({duration_sec}s elapsed)"
            ps_cmd = f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); $textNodes = $template.GetElementsByTagName("text"); $textNodes.Item(0).AppendChild($template.CreateTextNode("ODD Timer Alert")) > $null; $textNodes.Item(1).AppendChild($template.CreateTextNode("{msg}")) > $null; $toast = [Windows.UI.Notifications.ToastNotification]::new($template); [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("ODD").Show($toast)'
            subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    t = threading.Thread(target=_timer_worker, daemon=True)
    t.start()

ALIASES = {
    "wa": ["whatsapp"],
    "whats": ["whatsapp"],
    "wapp": ["whatsapp"],
    "whatsapp": ["whatsapp"],
    "wt": ["terminal", "windows terminal"],
    "term": ["terminal", "windows terminal", "command prompt", "powershell"],
    "terminal": ["windows terminal", "terminal"],
    "calc": ["calculator"],
    "calculator": ["calculator"],
    "vs": ["visual studio", "visual studio code"],
    "vsc": ["visual studio code", "code"],
    "vscode": ["visual studio code", "code"],
    "vs code": ["visual studio code", "code"],
    "visual studio code": ["visual studio code", "code"],
    "ps": ["powershell", "windows powershell"],
    "cmd": ["command prompt"],
    "snip": ["snipping tool"],
    "paint": ["paint", "mspaint"],
    "tg": ["telegram"],
    "tele": ["telegram"],
    "spot": ["spotify"],
    "disc": ["discord"],
    "edge": ["microsoft edge", "msedge"],
    "ms edge": ["microsoft edge", "msedge"],
    "microsoft edge": ["microsoft edge", "msedge"],
    "chrome": ["google chrome", "chrome"],
    "google chrome": ["google chrome", "chrome"],
    "brave": ["brave"],
    "ff": ["firefox", "mozilla firefox"],
    "firefox": ["firefox", "mozilla firefox"],
    "word": ["word", "microsoft word", "winword"],
    "ms word": ["word", "microsoft word", "winword"],
    "microsoft word": ["word", "microsoft word", "winword"],
    "winword": ["word", "microsoft word", "winword"],
    "excel": ["excel", "microsoft excel"],
    "ms excel": ["excel", "microsoft excel"],
    "microsoft excel": ["excel", "microsoft excel"],
    "powerpoint": ["powerpoint", "microsoft powerpoint", "powerpnt"],
    "ppt": ["powerpoint", "microsoft powerpoint", "powerpnt"],
    "ms powerpoint": ["powerpoint", "microsoft powerpoint", "powerpnt"],
    "explorer": ["file explorer", "explorer"],
    "file explorer": ["file explorer", "explorer"],
    "files": ["file explorer", "explorer"],
    "notepad": ["notepad"],
    "store": ["microsoft store"],
    "taskmgr": ["task manager"],
    "task manager": ["task manager"]
}

WEB_APP_TARGETS: Dict[str, Tuple[str, str, str]] = {
    "chatgpt": ("ChatGPT", "https://chatgpt.com", "Open ChatGPT in Default Web Browser"),
    "chat gpt": ("ChatGPT", "https://chatgpt.com", "Open ChatGPT in Default Web Browser"),
    "openai": ("ChatGPT (OpenAI)", "https://chatgpt.com", "Open ChatGPT in Default Web Browser"),
    "claude": ("Claude AI", "https://claude.ai", "Open Claude AI in Default Web Browser"),
    "claude ai": ("Claude AI", "https://claude.ai", "Open Claude AI in Default Web Browser"),
    "gemini": ("Google Gemini", "https://gemini.google.com", "Open Google Gemini in Default Web Browser"),
    "google gemini": ("Google Gemini", "https://gemini.google.com", "Open Google Gemini in Default Web Browser"),
    "perplexity": ("Perplexity AI", "https://www.perplexity.ai", "Open Perplexity in Default Web Browser"),
    "deepseek": ("DeepSeek", "https://chat.deepseek.com", "Open DeepSeek in Default Web Browser"),
    "grok": ("Grok", "https://grok.com", "Open Grok in Default Web Browser"),
    "youtube": ("YouTube", "https://www.youtube.com", "Open YouTube in Default Web Browser"),
    "yt": ("YouTube", "https://www.youtube.com", "Open YouTube in Default Web Browser"),
    "github": ("GitHub", "https://github.com", "Open GitHub in Default Web Browser"),
    "gh": ("GitHub", "https://github.com", "Open GitHub in Default Web Browser"),
    "gmail": ("Gmail", "https://mail.google.com", "Open Gmail in Default Web Browser"),
    "google mail": ("Gmail", "https://mail.google.com", "Open Gmail in Default Web Browser"),
    "google": ("Google", "https://www.google.com", "Open Google in Default Web Browser"),
    "google docs": ("Google Docs", "https://docs.google.com", "Open Google Docs in Default Web Browser"),
    "gdocs": ("Google Docs", "https://docs.google.com", "Open Google Docs in Default Web Browser"),
    "google sheets": ("Google Sheets", "https://sheets.google.com", "Open Google Sheets in Default Web Browser"),
    "gsheets": ("Google Sheets", "https://sheets.google.com", "Open Google Sheets in Default Web Browser"),
    "google drive": ("Google Drive", "https://drive.google.com", "Open Google Drive in Default Web Browser"),
    "gdrive": ("Google Drive", "https://drive.google.com", "Open Google Drive in Default Web Browser"),
    "canva": ("Canva", "https://www.canva.com", "Open Canva in Default Web Browser"),
    "figma": ("Figma", "https://www.figma.com", "Open Figma in Default Web Browser"),
    "notion": ("Notion", "https://www.notion.so", "Open Notion in Default Web Browser"),
    "reddit": ("Reddit", "https://www.reddit.com", "Open Reddit in Default Web Browser"),
    "netflix": ("Netflix", "https://www.netflix.com", "Open Netflix in Default Web Browser"),
    "linkedin": ("LinkedIn", "https://www.linkedin.com", "Open LinkedIn in Default Web Browser"),
    "twitter": ("X (Twitter)", "https://x.com", "Open X in Default Web Browser"),
    "leetcode": ("LeetCode", "https://leetcode.com", "Open LeetCode in Default Web Browser"),
    "stackoverflow": ("Stack Overflow", "https://stackoverflow.com", "Open Stack Overflow in Default Web Browser"),
    "stack overflow": ("Stack Overflow", "https://stackoverflow.com", "Open Stack Overflow in Default Web Browser"),
    "wikipedia": ("Wikipedia", "https://www.wikipedia.org", "Open Wikipedia in Default Web Browser"),
    "google maps": ("Google Maps", "https://maps.google.com", "Open Google Maps in Default Web Browser"),
}

KNOWN_FILE_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt", ".xlsx", ".xls", ".csv",
    ".pptx", ".ppt", ".md", ".epub", ".log", ".png", ".jpg", ".jpeg", ".gif",
    ".svg", ".webp", ".bmp", ".ico", ".tiff", ".psd", ".mp3", ".wav", ".flac",
    ".m4a", ".aac", ".ogg", ".wma", ".opus", ".mp4", ".mkv", ".avi", ".mov",
    ".wmv", ".webm", ".flv", ".m4v", ".zip", ".rar", ".7z", ".tar", ".gz",
    ".py", ".js", ".ts", ".html", ".css", ".json", ".cpp", ".c", ".h", ".cs",
    ".java", ".rs", ".go", ".php", ".sql", ".sh", ".bat", ".ps1", ".toml",
    ".yaml", ".yml", ".xml", ".exe", ".msi", ".lnk", ".msc"
}

KNOWN_WEB_TLDS = {
    ".com", ".org", ".net", ".io", ".ai", ".dev", ".co", ".edu", ".gov", ".app",
    ".me", ".gg", ".tv", ".in", ".uk", ".de", ".fr", ".jp", ".ca", ".au", ".xyz",
    ".space", ".tech", ".info", ".biz", ".online", ".site", ".store", ".cloud", ".sh"
}

def is_likely_web_domain(text: str) -> bool:
    """Returns True if text looks like a domain/URL (e.g. openai.com, humn.space) and NOT a local filename like story.pdf"""
    s = text.strip().lower()
    if s.startswith("http://") or s.startswith("https://"):
        return True
    if " " in s or "." not in s or len(s) < 4:
        return False
    host = s.split("/", 1)[0]
    ext = os.path.splitext(host)[1].lower()
    if ext in KNOWN_FILE_EXTENSIONS:
        return False
    return ext in KNOWN_WEB_TLDS


@dataclass
class ResolvedSplitTarget:
    query_part: str
    title: str
    target: str
    category: str
    subtitle: str
    exe_hints: List[str] = field(default_factory=list)
    title_hints: List[str] = field(default_factory=list)
    class_hints: List[str] = field(default_factory=list)
    prefer_new_window: bool = False
    direct_exe: Optional[str] = None
    is_fallback_web: bool = False
    kind: str = "app"
    exe_Hints: List[str] = field(default_factory=list)
    launch_args: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.exe_Hints and not self.exe_hints:
            self.exe_hints = list(self.exe_Hints)
        if not self.direct_exe and self.kind == "app" and self.target.lower().endswith(".exe"):
            self.direct_exe = self.target
        if self.kind in ("web", "file"):
            self.prefer_new_window = True


class WorkspaceSplitManager:
    """
    Smooth Multi-Window Split & Grid Tiling Engine for ODD v3.5.
    Supports 2, 3, and 4 applications, local files (e.g. story.pdf), folders, and web apps (e.g. ChatGPT).
    Handles DWM invisible shadow borders (DWMWA_EXTENDED_FRAME_BOUNDS), un-maximizing without animation lag,
    and multi-pass reinforcement so windows tile edge-to-edge with zero flicker.
    """

    @staticmethod
    def get_default_browser_exe() -> Optional[str]:
        try:
            import winreg
            import shlex
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
            ) as k:
                prog_id, _ = winreg.QueryValueEx(k, "ProgId")
            if prog_id:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as k2:
                    cmd_str, _ = winreg.QueryValueEx(k2, "")
                if cmd_str:
                    parts = shlex.split(cmd_str, posix=False)
                    if parts:
                        exe_candidate = parts[0].strip('"').strip("'")
                        if os.path.exists(exe_candidate):
                            return exe_candidate
        except Exception:
            pass

        for candidate in (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
        ):
            if os.path.exists(candidate):
                return candidate
        return None

    @staticmethod
    def get_default_pdf_browser_exe() -> Optional[str]:
        """Returns browser executable if default .pdf handler is Edge, Chrome, or Brave, with fallback so PDFs open in independent windows."""
        try:
            import winreg
            import shlex
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice"
            ) as k:
                prog_id, _ = winreg.QueryValueEx(k, "ProgId")
            if prog_id:
                p_low = prog_id.lower()
                if "msedge" in p_low:
                    for p in (
                        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
                    ):
                        if os.path.exists(p):
                            return p
                elif "chrome" in p_low:
                    for p in (
                        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
                    ):
                        if os.path.exists(p):
                            return p
                elif "brave" in p_low:
                    for p in (
                        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
                    ):
                        if os.path.exists(p):
                            return p
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as k2:
                    cmd_str, _ = winreg.QueryValueEx(k2, "")
                if cmd_str:
                    parts = shlex.split(cmd_str, posix=False)
                    if parts:
                        exe_candidate = parts[0].strip('"').strip("'")
                        if os.path.exists(exe_candidate) and any(
                            b in exe_candidate.lower() for b in ("msedge.exe", "chrome.exe", "brave.exe")
                        ):
                            return exe_candidate
        except Exception:
            pass
        for fallback in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ):
            if os.path.exists(fallback):
                return fallback
        return WorkspaceSplitManager.get_default_browser_exe()

    @staticmethod
    def ensure_workspace_file(filename: str) -> str:
        """
        Ensures that if a user types a filename like 'story.pdf' or 'notes.txt' that isn't yet on disk,
        a clean valid file is created in %LOCALAPPDATA%\\ODD\\workspace so it opens smoothly without error.
        """
        ws_dir = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\workspace"))
        ws_dir.mkdir(parents=True, exist_ok=True)
        safe_name = os.path.basename(filename.strip()) or "document.pdf"
        file_path = ws_dir / safe_name
        if file_path.exists() and file_path.stat().st_size > 0:
            return str(file_path)

        ext = file_path.suffix.lower()
        title_text = file_path.stem.replace("_", " ").replace("-", " ").title() or "Document"
        try:
            if ext == ".pdf":
                stream_content = (
                    f"BT /F1 22 Tf 72 720 Td ({safe_name}) Tj "
                    f"/F1 13 Tf 0 -32 Td (Opened via ODD v3.5 Multi-App Split Workspace) Tj "
                    f"0 -24 Td (Document: {title_text}) Tj ET"
                ).encode("latin-1", errors="ignore")
                s_len = len(stream_content)
                pdf_bytes = (
                    b"%PDF-1.4\n"
                    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
                    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
                    b"/MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n"
                    b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
                    + f"5 0 obj\n<< /Length {s_len} >>\nstream\n".encode("ascii")
                    + stream_content
                    + b"\nendstream\nendobj\n"
                    b"xref\n0 6\n"
                    b"0000000000 65535 f \n"
                    b"0000000009 00000 n \n"
                    b"0000000058 00000 n \n"
                    b"0000000115 00000 n \n"
                    b"0000000229 00000 n \n"
                    b"0000000297 00000 n \n"
                    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
                    + f"{350 + s_len}\n%%EOF\n".encode("ascii")
                )
                file_path.write_bytes(pdf_bytes)
            else:
                file_path.write_text(f"# {title_text}\n", encoding="utf-8")
        except Exception:
            pass
        return str(file_path)

    @staticmethod
    def get_work_area() -> Tuple[int, int, int, int]:
        """Returns (left, top, width, height) of the active monitor's work area in Win32 physical pixels."""
        try:
            import ctypes.wintypes as wt
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wt.DWORD),
                    ("rcMonitor", wt.RECT),
                    ("rcWork", wt.RECT),
                    ("dwFlags", wt.DWORD)
                ]
            user32 = ctypes.windll.user32
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            hmon = user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                left = int(mi.rcWork.left)
                top = int(mi.rcWork.top)
                w = int(mi.rcWork.right - mi.rcWork.left)
                h = int(mi.rcWork.bottom - mi.rcWork.top)
                if w > 300 and h > 200:
                    return left, top, w, h
        except Exception:
            pass
        return 0, 0, 1920, 1040

    @classmethod
    def instance(cls):
        return cls

    @classmethod
    def launch_split(cls, items: List[ResolvedSplitTarget], layout_mode: str = "auto", open_target_fn: Optional[Callable] = None):
        return cls.execute_split(items, layout_mode=layout_mode, open_target_fn=open_target_fn)

    @staticmethod
    def compute_slot_rects(count: int, layout_mode: str = "auto") -> List[Tuple[int, int, int, int]]:
        x0, y0, w, h = WorkspaceSplitManager.get_work_area()
        if count <= 1:
            return [(x0, y0, w, h)]
        elif count == 2:
            if layout_mode in ("tb", "top_bottom"):
                h1 = h // 2
                return [(x0, y0, w, h1), (x0, y0 + h1, w, h - h1)]
            elif layout_mode in ("70_30", "focus_left"):
                w1 = int(w * 0.65)
                return [(x0, y0, w1, h), (x0 + w1, y0, w - w1, h)]
            else:
                w1 = w // 2
                return [(x0, y0, w1, h), (x0 + w1, y0, w - w1, h)]
        elif count == 3:
            if layout_mode == "columns_3":
                # 3 Equal Side-by-Side Columns (Left | Center | Right)
                w1 = w // 3
                w2 = (2 * w) // 3 - w1
                w3 = w - w1 - w2
                return [
                    (x0, y0, w1, h),
                    (x0 + w1, y0, w2, h),
                    (x0 + w1 + w2, y0, w3, h)
                ]
            elif layout_mode == "stack_left_main_right":
                w_left = w // 2
                w_right = w - w_left
                h_top = h // 2
                return [
                    (x0, y0, w_left, h_top),
                    (x0, y0 + h_top, w_left, h - h_top),
                    (x0 + w_left, y0, w_right, h)
                ]
            else:
                # Default 3-window layout: Left Half (full height) + Right Stack (Top-Right & Bottom-Right)
                w_left = w // 2
                w_right = w - w_left
                h_top = h // 2
                return [
                    (x0, y0, w_left, h),
                    (x0 + w_left, y0, w_right, h_top),
                    (x0 + w_left, y0 + h_top, w_right, h - h_top)
                ]
        else:
            # 4 items
            if layout_mode in ("cols", "columns_4"):
                w1 = w // 4
                w2 = (2 * w) // 4 - w1
                w3 = (3 * w) // 4 - w1 - w2
                w4 = w - w1 - w2 - w3
                return [
                    (x0, y0, w1, h),
                    (x0 + w1, y0, w2, h),
                    (x0 + w1 + w2, y0, w3, h),
                    (x0 + w1 + w2 + w3, y0, w4, h)
                ]
            else:
                # 2x2 Quadrant Grid (Top-Left, Top-Right, Bottom-Left, Bottom-Right)
                w_left = w // 2
                w_right = w - w_left
                h_top = h // 2
                h_bot = h - h_top
                return [
                    (x0, y0, w_left, h_top),
                    (x0 + w_left, y0, w_right, h_top),
                    (x0, y0 + h_top, w_left, h_bot),
                    (x0 + w_left, y0 + h_top, w_right, h_bot)
                ]

    @staticmethod
    def enumerate_app_windows(include_minimized: bool = False) -> List[Dict[str, Any]]:
        """Enumerates all real top-level application windows on the desktop (64-bit safe)."""
        results = []
        try:
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            dwmapi = ctypes.windll.dwmapi

            try:
                hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
                if hdesk:
                    user32.SetThreadDesktop(hdesk)
            except Exception:
                pass

            WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
            my_pid = os.getpid()
            skip_classes = {
                "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                "NotifyIconOverflowWindow", "Windows.UI.Core.CoreWindow",
                "MsoSplash", "SplashScreen", "SysShadow", "IME", "MSCTFIME UI",
                "DummyDWMListenerWindow", "EdgeUiInputTopWndClass", "EdgeUiInputWndClass",
                "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland",
                "ApplicationFrameTitleBarWindow", "CEF-OSC-WIDGET", "RainmeterMeterWindow"
            }

            seen_hwnds = set()

            def _cb(hwnd, _lparam):
                try:
                    if not hwnd or hwnd in seen_hwnds:
                        return True
                    seen_hwnds.add(hwnd)
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    is_min = bool(user32.IsIconic(hwnd))
                    if is_min and not include_minimized:
                        return True

                    # Skip cloaked background UWP windows
                    cloaked = ctypes.c_int(0)
                    if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0:
                        if cloaked.value != 0:
                            return True

                    pid = wt.DWORD(0)
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value == my_pid:
                        return True

                    c_buf = ctypes.create_unicode_buffer(128)
                    user32.GetClassNameW(hwnd, c_buf, 128)
                    cls_name = c_buf.value
                    if cls_name in skip_classes or cls_name.startswith("Qt6") or cls_name == "#32770":
                        return True

                    # Check window styles (skip child windows, owned popups, and tool windows unless WS_EX_APPWINDOW)
                    GWL_STYLE = -16
                    GWL_EXSTYLE = -20
                    WS_EX_TOOLWINDOW = 0x00000080
                    WS_EX_APPWINDOW = 0x00040000
                    WS_EX_NOACTIVATE = 0x08000000
                    WS_CHILD = 0x40000000
                    GW_OWNER = 4
                    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    if style & WS_CHILD:
                        return True
                    if (ex_style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)) and not (ex_style & WS_EX_APPWINDOW):
                        return True
                    if user32.GetWindow(hwnd, GW_OWNER) and not (ex_style & WS_EX_APPWINDOW):
                        return True

                    t_len = user32.GetWindowTextLengthW(hwnd)
                    if t_len == 0:
                        return True
                    t_buf = ctypes.create_unicode_buffer(t_len + 2)
                    user32.GetWindowTextW(hwnd, t_buf, t_len + 2)
                    title = t_buf.value.strip()
                    if not title or "App Feature Updates" in title:
                        return True

                    rect = wt.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        rw = rect.right - rect.left
                        rh = rect.bottom - rect.top
                        if not is_min and (rw < 250 or rh < 180):
                            return True
                    else:
                        rw, rh = 0, 0

                    exe_name = ""
                    if pid.value:
                        h_proc = kernel32.OpenProcess(0x1000, False, pid.value)
                        if h_proc:
                            try:
                                p_buf = ctypes.create_unicode_buffer(1024)
                                p_sz = wt.DWORD(1024)
                                if kernel32.QueryFullProcessImageNameW(h_proc, 0, p_buf, ctypes.byref(p_sz)):
                                    exe_name = os.path.basename(p_buf.value).lower()
                            finally:
                                kernel32.CloseHandle(h_proc)

                    results.append({
                        "hwnd": int(hwnd),
                        "pid": int(pid.value),
                        "exe": exe_name,
                        "class": cls_name,
                        "title": title,
                        "title_low": title.lower(),
                        "is_min": is_min,
                        "w": rw,
                        "h": rh
                    })
                except Exception:
                    pass
                return True

            enum_fn = WNDENUMPROC(_cb)
            desktops = []
            try:
                hwinsta = user32.GetProcessWindowStation()
                if hwinsta:
                    DESKENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.LPCWSTR, wt.LPARAM)
                    def _desk_cb(dname, _):
                        if dname:
                            desktops.append(str(dname))
                        return True
                    user32.EnumDesktopsW(hwinsta, DESKENUMPROC(_desk_cb), 0)
            except Exception:
                desktops = []

            if desktops:
                for d in desktops:
                    try:
                        hdesk_obj = user32.OpenDesktopW(d, 0, False, 0x01FF)
                        if hdesk_obj:
                            user32.EnumDesktopWindows(hdesk_obj, enum_fn, 0)
                            user32.CloseDesktop(hdesk_obj)
                    except Exception:
                        pass
            else:
                user32.EnumWindows(enum_fn, 0)
        except Exception:
            pass
        return results

    @staticmethod
    def is_window_aligned_to_slot(hwnd: int, slot_rect: Tuple[int, int, int, int], tolerance: int = 8) -> bool:
        """Checks whether a window is still un-maximized, visible, and aligned with its target slot."""
        try:
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            dwmapi = ctypes.windll.dwmapi

            if not hwnd or not user32.IsWindow(hwnd):
                return False
            if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
                return False

            tx, ty, tw, th = slot_rect
            f_rect = wt.RECT()
            if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(f_rect), ctypes.sizeof(wt.RECT)) == 0:
                fw = f_rect.right - f_rect.left
                fh = f_rect.bottom - f_rect.top
                if abs(f_rect.left - tx) > tolerance or abs(f_rect.top - ty) > tolerance:
                    return False
                if abs(fw - tw) > tolerance * 2 and fw < tw:
                    return False
                if abs(fh - th) > tolerance * 2 and fh < th:
                    return False
                return True

            w_rect = wt.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(w_rect)):
                if abs(w_rect.left - tx) > tolerance + 12 or abs(w_rect.top - ty) > tolerance + 12:
                    return False
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def snap_window_to_slot(hwnd: int, slot_rect: Tuple[int, int, int, int], raise_to_top: bool = True) -> bool:
        """
        Positions a window into (x, y, w, h) matching Windows native multi-window arrangement.
        Compensates for DWM invisible shadow margins to achieve true pixel-perfect edge-to-edge alignment.
        """
        try:
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            dwmapi = ctypes.windll.dwmapi

            if not hwnd or not user32.IsWindow(hwnd):
                return False

            tx, ty, tw, th = slot_rect

            # 1. Restore window cleanly if minimized
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.02)

            # 2. If maximized, un-maximize and wait for asynchronous restore
            if user32.IsZoomed(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                for _ in range(12):
                    time.sleep(0.015)
                    if not user32.IsZoomed(hwnd):
                        break

            # 3. Measure actual DWM drop shadow invisible padding
            w_rect = wt.RECT()
            f_rect = wt.RECT()
            pad_l, pad_r, pad_b = 0, 0, 0
            if user32.GetWindowRect(hwnd, ctypes.byref(w_rect)) and \
               dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(f_rect), ctypes.sizeof(wt.RECT)) == 0:
                pad_l = max(0, min(16, f_rect.left - w_rect.left))
                pad_r = max(0, min(16, w_rect.right - f_rect.right))
                pad_b = max(0, min(16, w_rect.bottom - f_rect.bottom))

            # pad_t MUST BE 0! In Windows 10 & 11, standard windows have NO invisible top shadow.
            # Subtracting top padding pushes the title bar and tab strip off-screen!
            adj_x = tx - pad_l
            adj_y = ty
            adj_w = tw + pad_l + pad_r
            adj_h = th + pad_b

            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020
            SWP_SHOWWINDOW = 0x0040
            flags = SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW

            user32.SetWindowPos(hwnd, 0, adj_x, adj_y, adj_w, adj_h, flags)

            # 4. Bring to top / foreground cleanly if requested
            if raise_to_top:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)

            return True
        except Exception:
            return False

    @classmethod
    def batch_snap_windows(
        cls,
        pairs: List[Tuple[int, Tuple[int, int, int, int]]],
        raise_to_top: bool = True,
        animate: bool = False,
        duration_ms: int = 180,
    ) -> None:
        """
        Positions multiple split windows simultaneously using clean Windows DWM-compensated snapping.
        Uses a two-pass reinforcement to prevent Chromium/Electron asynchronous restore jitter.
        """
        if not pairs:
            return

        # Pass 1: Restore and snap all windows into their target slots
        for hwnd, srect in pairs:
            if hwnd:
                cls.snap_window_to_slot(hwnd, srect, raise_to_top=False)

        # Brief settle time for app message pumps
        time.sleep(0.04)

        # Pass 2: Reinforce exact positions and focus
        for hwnd, srect in reversed(pairs):
            if hwnd:
                cls.snap_window_to_slot(hwnd, srect, raise_to_top=raise_to_top)

    @classmethod
    def arrange_active_windows(cls, count: int = 0, layout_mode: str = "auto"):
        """
        Gathers active top-level application windows from desktop and arranges them
        using default Windows multi-window arrangement (2-way, 3-way, or 4-way).
        If count is 0 or 'auto', automatically detects the number of active windows (up to 4).
        """
        def _worker():
            try:
                wins = cls.enumerate_app_windows(include_minimized=False)
                my_pid = os.getpid()
                candidates = [w for w in wins if w["pid"] != my_pid and w["w"] > 250 and w["h"] > 180]
                if not candidates:
                    return

                if count and count >= 2:
                    target_count = min(len(candidates), min(4, count))
                else:
                    target_count = min(len(candidates), 4)
                    if target_count < 2:
                        return

                chosen = candidates[:target_count]
                slot_rects = cls.compute_slot_rects(target_count, layout_mode=layout_mode)
                pairs = [(chosen[i]["hwnd"], slot_rects[i]) for i in range(target_count)]
                cls.batch_snap_windows(pairs, raise_to_top=True)
            except Exception as e:
                print(f"Error arranging active windows: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    @staticmethod
    def _score_window_for_target(win: Dict[str, Any], item: ResolvedSplitTarget, is_new: bool, launched_pid: Optional[int]) -> int:
        score = 0
        w_exe = win["exe"]
        w_cls = win["class"]
        w_title = win["title_low"]

        # Never match non-Explorer shell windows owned by explorer.exe
        if w_exe == "explorer.exe" and w_cls not in ("CabinetWClass", "ExploreWClass"):
            return 0

        # Generic UWP container (ApplicationFrameHost.exe) must match a title hint to avoid matching unrelated UWP apps
        if w_exe == "applicationframehost.exe":
            if any(th and th in w_title for th in item.title_hints):
                score += 950
                if is_new:
                    score += 350
            return score

        if launched_pid and win["pid"] == launched_pid:
            score += 900

        if item.class_hints and w_cls in item.class_hints:
            score += 650

        if item.exe_hints and w_exe in item.exe_hints:
            score += 550

        generic_browser_titles = {"chrome", "google chrome", "edge", "microsoft edge", "microsoft​ edge", "brave", "firefox", "mozilla firefox"}
        best_title_bonus = 0
        for th in item.title_hints:
            if th and th in w_title:
                if th in generic_browser_titles:
                    best_title_bonus = max(best_title_bonus, 120)
                else:
                    best_title_bonus = max(best_title_bonus, 480)
        score += best_title_bonus

        if score > 0 and is_new:
            score += 350

        return score

    @classmethod
    def execute_split(cls, items: List[ResolvedSplitTarget], layout_mode: str = "auto", open_target_fn: Optional[Callable] = None):
        """
        Launches 2, 3, or 4 resolved targets, waits until target windows are ready,
        animates them simultaneously into their exact split/grid slots, and reinforces
        their positions so apps that restore their own window state on startup stay locked in place.
        """
        if not items:
            return

        # Trigger subtle Dynamic Island HUD feedback if available
        try:
            from odd_island import DynamicIslandMonitor
            mon = DynamicIslandMonitor.get_instance()
            if mon:
                summary = " • ".join(it.title for it in items)
                if len(summary) > 34:
                    summary = summary[:31] + "..."
                mon.trigger_rook_shortcut(f"Split {len(items)} Apps", summary)
        except Exception:
            pass

        def _orchestrate():
            try:
                import copy
                work_items = [copy.deepcopy(it) for it in items]
                n = len(work_items)
                slot_rects = cls.compute_slot_rects(n, layout_mode=layout_mode)
                pre_wins = cls.enumerate_app_windows(include_minimized=True)
                pre_hwnds = {w["hwnd"] for w in pre_wins}
                pre_titles = {w["hwnd"]: w["title_low"] for w in pre_wins}

                claimed_hwnds = set()
                slot_hwnds: List[Optional[int]] = [None] * n
                slot_snapped: List[bool] = [False] * n
                slot_matched_at: List[float] = [0.0] * n
                slot_must_be_new: List[bool] = [False] * n
                launched_pids: List[Optional[int]] = [None] * n

                default_browser_exe = cls.get_default_browser_exe()
                pdf_browser_exe = cls.get_default_pdf_browser_exe()

                # Brief 35ms pause so OddOverlay begins sinking smoothly
                time.sleep(0.035)
                spawned_count = 0

                # PHASE 1: Resolve existing windows for APPs or launch new windows when required
                for idx, it in enumerate(work_items):
                    tgt = it.target
                    cat = it.category

                    if tgt.startswith("__auto_file__:"):
                        raw_fname = tgt.split(":", 1)[1].strip()
                        ws_matches = query_windows_search(raw_fname, limit=3)
                        if ws_matches:
                            tgt = ws_matches[0][1]
                        else:
                            tgt = cls.ensure_workspace_file(raw_fname)
                        it.target = tgt

                    # When the user asks for an APPLICATION or WEB target (e.g. "chrome vs code", "chatgpt and code"),
                    # reuse an already-open window if one exists matching the target with high confidence.
                    best_existing = None
                    best_ex_score = 0
                    for w in pre_wins:
                        if w["hwnd"] in claimed_hwnds:
                            continue
                        s = cls._score_window_for_target(w, it, is_new=False, launched_pid=None)
                        if s >= 550:
                            effective_s = s + (50 if not w["is_min"] else 0)
                            if effective_s > best_ex_score:
                                best_ex_score = effective_s
                                best_existing = w
                    if best_existing is not None:
                        hwnd_ex = best_existing["hwnd"]
                        claimed_hwnds.add(hwnd_ex)
                        slot_hwnds[idx] = hwnd_ex
                        slot_matched_at[idx] = time.monotonic()
                        slot_must_be_new[idx] = False
                        continue

                    # No existing window was claimed for this slot -> launch a NEW window
                    slot_must_be_new[idx] = True

                    # Stagger consecutive process spawns by 150ms so Chromium/Explorer IPC never merges simultaneous windows
                    if spawned_count > 0:
                        time.sleep(0.15)
                    spawned_count += 1

                    try:
                        if tgt.lower() in ("explorer.exe", "microsoft.windows.explorer", "file explorer", "explorer"):
                            proc = subprocess.Popen(
                                ["explorer.exe", "/n,", "shell:MyComputerFolder"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
                            launched_pids[idx] = proc.pid
                            continue

                        if cat in ("WEB", "WEB APP", "URL") or it.kind == "web" or tgt.startswith(("http://", "https://")):
                            if default_browser_exe and os.path.exists(default_browser_exe):
                                b_name = os.path.basename(default_browser_exe).lower()
                                if b_name not in it.exe_hints:
                                    it.exe_hints.insert(0, b_name)
                                flag = "-new-window" if "firefox" in b_name else "--new-window"
                                proc = subprocess.Popen(
                                    [default_browser_exe, flag, tgt],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                )
                                launched_pids[idx] = proc.pid
                            else:
                                webbrowser.open_new(tgt)
                            continue

                        if cat == "PDF" or tgt.lower().endswith(".pdf"):
                            browser_for_pdf = pdf_browser_exe or default_browser_exe
                            if browser_for_pdf and os.path.exists(browser_for_pdf) and os.path.exists(tgt):
                                b_name = os.path.basename(browser_for_pdf).lower()
                                if b_name not in it.exe_hints:
                                    it.exe_hints.insert(0, b_name)
                                flag = "-new-window" if "firefox" in b_name else "--new-window"
                                proc = subprocess.Popen(
                                    [browser_for_pdf, flag, tgt],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                )
                                launched_pids[idx] = proc.pid
                                continue

                        if cat == "FOLDER" or (os.path.exists(tgt) and os.path.isdir(tgt)):
                            if "explorer.exe" not in it.exe_hints:
                                it.exe_hints.insert(0, "explorer.exe")
                            if "CabinetWClass" not in it.class_hints:
                                it.class_hints = ["CabinetWClass", "ExploreWClass"]
                            proc = subprocess.Popen(
                                ["explorer.exe", "/n,", tgt],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
                            launched_pids[idx] = proc.pid
                            continue

                        if it.kind == "file" and os.path.exists(tgt):
                            ext_low = os.path.splitext(tgt)[1].lower()
                            if ext_low in (".html", ".htm", ".svg") and default_browser_exe and os.path.exists(default_browser_exe):
                                b_name = os.path.basename(default_browser_exe).lower()
                                if b_name not in it.exe_hints:
                                    it.exe_hints.insert(0, b_name)
                                flag = "-new-window" if "firefox" in b_name else "--new-window"
                                proc = subprocess.Popen(
                                    [default_browser_exe, flag, tgt],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                )
                                launched_pids[idx] = proc.pid
                                continue
                            if ext_low in (".txt", ".md", ".log", ".ini", ".cfg", ".csv"):
                                if "notepad.exe" not in it.exe_hints:
                                    it.exe_hints.insert(0, "notepad.exe")
                                proc = subprocess.Popen(
                                    ["notepad.exe", tgt],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                )
                                launched_pids[idx] = proc.pid
                                continue

                        if it.direct_exe and os.path.exists(it.direct_exe):
                            exe_low = os.path.basename(it.direct_exe).lower()
                            if exe_low in ("msedge.exe", "chrome.exe", "brave.exe", "vivaldi.exe", "opera.exe"):
                                proc = subprocess.Popen(
                                    [it.direct_exe, "--new-window"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                )
                                launched_pids[idx] = proc.pid
                                continue
                            elif exe_low == "firefox.exe":
                                proc = subprocess.Popen(
                                    [it.direct_exe, "-new-window"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                )
                                launched_pids[idx] = proc.pid
                                continue
                            elif exe_low == "code.exe":
                                proc = subprocess.Popen(
                                    [it.direct_exe, "-n"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                )
                                launched_pids[idx] = proc.pid
                                continue
                            else:
                                proc = subprocess.Popen(
                                    [it.direct_exe],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                                )
                                launched_pids[idx] = proc.pid
                                continue

                        if open_target_fn:
                            open_target_fn(tgt)
                        else:
                            os.startfile(tgt)
                    except Exception:
                        try:
                            if open_target_fn:
                                open_target_fn(tgt)
                        except Exception:
                            pass

                # PHASE 2: Wait for newly spawned windows, snap all windows into their slots,
                #          and reinforce slot positions so apps that self-maximize on startup stay tiled.
                start_t = time.monotonic()
                sync_wait = 0.0 if all(h is not None for h in slot_hwnds) else (2.75 if n >= 3 else 2.35)
                max_wait = 7.5
                initial_batch_done = False
                last_reinforce_t = 0.0

                while (time.monotonic() - start_t) < max_wait:
                    now = time.monotonic()
                    elapsed = now - start_t
                    curr_wins = cls.enumerate_app_windows(include_minimized=(elapsed > 0.45))
                    curr_hwnd_map = {w["hwnd"]: w for w in curr_wins}

                    # If a previously matched window was a temporary splash screen that closed, release its slot
                    for i in range(n):
                        h_cur = slot_hwnds[i]
                        if h_cur is not None and h_cur not in curr_hwnd_map:
                            claimed_hwnds.discard(h_cur)
                            slot_hwnds[i] = None
                            slot_snapped[i] = False

                    # Match pending slots
                    for i in range(n):
                        if slot_hwnds[i] is not None:
                            continue
                        it = work_items[i]
                        best_w = None
                        best_s = 0

                        for w in curr_wins:
                            hwnd = w["hwnd"]
                            if hwnd in claimed_hwnds:
                                continue
                            is_new = (hwnd not in pre_hwnds)

                            # When a new window was launched for this slot, only match newly created windows
                            # (or a single-instance viewer/folder window whose title changed to this target).
                            if slot_must_be_new[i] and not is_new:
                                if elapsed > 1.1:
                                    old_title = pre_titles.get(hwnd, "")
                                    if w["title_low"] != old_title and any(
                                        th and len(th) >= 3 and th in w["title_low"] for th in it.title_hints
                                    ):
                                        pass
                                    else:
                                        continue
                                else:
                                    continue

                            s = cls._score_window_for_target(w, it, is_new=is_new, launched_pid=launched_pids[i])

                            # If multiple new windows of the same browser/app were launched, avoid stealing a window
                            # whose title already specifically matches another pending slot's non-generic title_hints
                            if s > 0 and is_new:
                                generic_bt = {"chrome", "google chrome", "edge", "microsoft edge", "microsoft​ edge", "brave", "firefox", "mozilla firefox"}
                                my_specific_hit = any(
                                    th and th not in generic_bt and th in w["title_low"]
                                    for th in it.title_hints
                                )
                                if not my_specific_hit:
                                    other_specific_hit = any(
                                        j != i and slot_hwnds[j] is None and
                                        any(th and th not in generic_bt and th in w["title_low"] for th in work_items[j].title_hints)
                                        for j in range(n)
                                    )
                                    if other_specific_hit and elapsed < 2.0:
                                        continue

                            # Fallback ONLY for unknown file associations where exe_hints is empty
                            if s == 0 and is_new and not it.exe_hints and it.kind == "file" and elapsed > 0.85:
                                matches_other = any(
                                    j != i and
                                    cls._score_window_for_target(w, work_items[j], is_new=True, launched_pid=launched_pids[j]) > 0
                                    for j in range(n)
                                )
                                if not matches_other:
                                    s = 350

                            if s > best_s and (s >= 450 or (is_new and s >= 300)):
                                best_s = s
                                best_w = w

                        if best_w is not None:
                            matched_hwnd = best_w["hwnd"]
                            claimed_hwnds.add(matched_hwnd)
                            slot_hwnds[i] = matched_hwnd
                            slot_matched_at[i] = now

                    # Reconcile slot assignments among newly launched windows if page/document titles loaded out of order
                    swapped_any = False
                    for i in range(n):
                        for j in range(i + 1, n):
                            hi, hj = slot_hwnds[i], slot_hwnds[j]
                            if hi is not None and hj is not None and (slot_must_be_new[i] or slot_must_be_new[j]):
                                wi = curr_hwnd_map.get(hi)
                                wj = curr_hwnd_map.get(hj)
                                if wi and wj and wi["exe"] == wj["exe"]:
                                    cur_pair_score = (
                                        cls._score_window_for_target(wi, work_items[i], is_new=(hi not in pre_hwnds), launched_pid=launched_pids[i]) +
                                        cls._score_window_for_target(wj, work_items[j], is_new=(hj not in pre_hwnds), launched_pid=launched_pids[j])
                                    )
                                    swap_pair_score = (
                                        cls._score_window_for_target(wj, work_items[i], is_new=(hj not in pre_hwnds), launched_pid=launched_pids[i]) +
                                        cls._score_window_for_target(wi, work_items[j], is_new=(hi not in pre_hwnds), launched_pid=launched_pids[j])
                                    )
                                    if swap_pair_score > cur_pair_score + 100:
                                        slot_hwnds[i], slot_hwnds[j] = hj, hi
                                        swapped_any = True

                    all_ready = all(h is not None for h in slot_hwnds)

                    # Execute the synchronized multi-window animation as soon as all windows are ready (or at sync_wait)
                    if not initial_batch_done and (all_ready or elapsed >= sync_wait):
                        ready_pairs = [
                            (slot_hwnds[i], slot_rects[i])
                            for i in range(n)
                            if slot_hwnds[i] is not None
                        ]
                        if ready_pairs:
                            cls.batch_snap_windows(ready_pairs, raise_to_top=True, animate=True, duration_ms=175)
                            for i in range(n):
                                if slot_hwnds[i] is not None:
                                    slot_snapped[i] = True
                            last_reinforce_t = time.monotonic()
                        initial_batch_done = True

                    # If any slow-starting app arrived after the initial batch (or slots swapped), snap all ready windows
                    elif initial_batch_done:
                        newly_arrived = [
                            i for i in range(n)
                            if slot_hwnds[i] is not None and not slot_snapped[i]
                        ]
                        if newly_arrived or swapped_any:
                            ready_pairs = [
                                (slot_hwnds[i], slot_rects[i])
                                for i in range(n)
                                if slot_hwnds[i] is not None
                            ]
                            cls.batch_snap_windows(ready_pairs, raise_to_top=True)
                            for i in newly_arrived:
                                slot_snapped[i] = True
                            last_reinforce_t = time.monotonic()

                    if all_ready and initial_batch_done:
                        break

                    time.sleep(0.04)

                # Final synchronized verification pass
                final_pairs = [
                    (slot_hwnds[i], slot_rects[i])
                    for i in range(n)
                    if slot_hwnds[i] is not None
                ]
                if final_pairs:
                    cls.batch_snap_windows(final_pairs, raise_to_top=True, animate=False)

            except Exception as e:
                print(f"Error in WorkspaceSplitManager: {e}")

        t = threading.Thread(target=_orchestrate, daemon=True)
        t.start()



@dataclass(slots=True)
class IndexedRecord:
    title: str
    target: str
    category: str
    subtitle: str
    t_low: str
    tgt_low: str
    s_low: str
    words: tuple
    acronym: str
    path_boost: int

def create_indexed_record(title: str, target: str, category: str, subtitle: str) -> IndexedRecord:
    t_low = title.strip().lower()
    tgt_low = target.strip().lower()
    s_low = subtitle.strip().lower()
    words = tuple(t_low.replace("-", " ").replace("_", " ").replace(".", " ").split())
    acronym = "".join(w[0] for w in words if w) if len(words) > 1 else ""
    path_boost = 0
    if any(p in tgt_low for p in ("\\downloads\\", "\\documents\\", "\\desktop\\", "\\pictures\\", "\\videos\\", "\\music\\", "\\project\\", "\\projects\\", "\\resumes\\")):
        path_boost += 100
    if any(j in tgt_low for j in ("node_modules", "\\cache\\", "webcache", "\\.obsidian\\", "tagame", "\\temp\\", "\\tmp\\", "appdata\\local\\temp", "\\.vs\\", "\\dist\\", "\\build\\")):
        path_boost -= 350
    return IndexedRecord(title, target, category, subtitle, t_low, tgt_low, s_low, words, acronym, path_boost)

def score_record(q: str, rec: IndexedRecord, is_alias: bool = False, alias_targets: list = None) -> int:
    t = rec.t_low
    if t == q:
        score = 1000
    elif is_alias and alias_targets and t in alias_targets:
        score = 980
    elif is_alias and alias_targets and any(at in t or t.startswith(at) for at in alias_targets):
        score = 950
    elif t.startswith(q):
        score = 800
    elif any(w.startswith(q) for w in rec.words):
        score = 680
    elif rec.acronym and len(q) <= len(rec.words) and rec.acronym.startswith(q):
        score = 500
    elif " " in q and all(any(w.startswith(qp) for w in rec.words) for qp in q.split()):
        score = 640
    elif q in t:
        score = 380
    elif q in rec.s_low:
        score = 180
    elif q in rec.tgt_low:
        score = 120
    else:
        return 0

    return max(10, score + rec.path_boost)

def score_match(query: str, title: str, subtitle: str = "", target: str = "") -> int:
    q = query.strip().lower()
    t = title.strip().lower()
    s = subtitle.strip().lower()
    tgt = target.strip().lower()

    if not q or not t:
        return 0

    score = 0
    words = t.replace("-", " ").replace("_", " ").replace(".", " ").split()

    # Direct exact full match
    if t == q:
        score = 1000
    # Alias / nickname boost (e.g. "wa" -> WhatsApp, "wt" -> Windows Terminal)
    elif q in ALIASES and any(alias_target in t or t.startswith(alias_target) for alias_target in ALIASES[q]):
        score = 950
    # Starts with query
    elif t.startswith(q):
        score = 800
    # Word in title starts with query (e.g. "copilot" in "Microsoft 365 Copilot", "resume" in "Wilfred_Resume")
    elif any(w.startswith(q) for w in words):
        score = 680
    # Acronym matching (e.g. "wt" -> "Windows Terminal", "vs" -> "Visual Studio", "calc" -> "Calculator")
    elif len(words) > 1 and len(q) <= len(words) and "".join(w[0] for w in words if w).startswith(q):
        score = 500
    # Substring in title
    elif q in t:
        score = 380
    # In subtitle or target path
    elif q in s:
        score = 180
    elif q in tgt:
        score = 120

    if score > 0:
        # Boost items in user primary folders
        if any(p in tgt for p in ("\\downloads\\", "\\documents\\", "\\desktop\\", "\\pictures\\", "\\videos\\", "\\music\\", "\\project\\", "\\projects\\", "\\resumes\\")):
            score += 100
        # Penalize build/cache/vendor directories
        if any(j in tgt for j in ("node_modules", "\\cache\\", "webcache", "\\.obsidian\\", "tagame", "\\temp\\", "\\tmp\\", "appdata\\local\\temp", "\\.vs\\", "\\dist\\", "\\build\\")):
            score -= 350
        return max(10, score)

    return 0

def safe_scan_shortcuts(base_path: str, max_depth: int = 3) -> List[Tuple[str, str]]:
    results = []
    if not os.path.exists(base_path):
        return results

    scanned = 0

    def _walk(curr_dir, depth):
        nonlocal scanned
        if depth > max_depth:
            return
        try:
            with os.scandir(curr_dir) as it:
                for entry in it:
                    scanned += 1
                    if scanned % 150 == 0:
                        time.sleep(0.001)
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            if entry.name.lower().endswith(".lnk"):
                                stem = entry.name[:-4]
                                results.append((stem, entry.path))
                        elif entry.is_dir(follow_symlinks=False):
                            name = entry.name.lower()
                            if not name.startswith(".") and not name.startswith("$") and "application data" not in name:
                                _walk(entry.path, depth + 1)
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass

    _walk(base_path, 1)
    return results

def safe_scan_dir(base_path: str, max_depth: int = 4) -> Tuple[List[Tuple[str, str, str]], List[Tuple[str, str, str, str]]]:
    folders = []
    files = []
    if not os.path.exists(base_path):
        return folders, files

    skip_patterns = {
        ".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist",
        "appdata", "$recycle.bin", ".idea", ".vscode", "application data",
        "winsxs", "system volume information", "site-packages", ".cache", ".gradle"
    }

    scanned = 0

    def _walk(curr_dir, depth):
        nonlocal scanned
        if depth > max_depth:
            return
        try:
            with os.scandir(curr_dir) as it:
                for entry in it:
                    scanned += 1
                    if scanned % 150 == 0:
                        time.sleep(0.001)
                    try:
                        if entry.is_symlink():
                            continue
                        name = entry.name
                        low = name.lower()
                        if low in skip_patterns or name.startswith(".") or name.startswith("$"):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            folders.append((name, entry.path, f"Folder • in {curr_dir}"))
                            _walk(entry.path, depth + 1)
                        elif entry.is_file(follow_symlinks=False):
                            if not low.endswith(".tmp") and not low.endswith(".pyc") and not low.endswith(".log.old"):
                                cat = get_file_category(name)
                                try:
                                    sz = entry.stat(follow_symlinks=False).st_size
                                    sz_str = format_file_size(sz)
                                except Exception:
                                    sz_str = ""
                                sub = f"{cat} • {sz_str} • in {curr_dir}" if sz_str else f"{cat} • in {curr_dir}"
                                files.append((name, entry.path, cat, sub))
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass

    _walk(base_path, 1)
    return folders, files

class WindowsSearchEngine:
    def __init__(self, prefixes: dict = None, settings: dict = None):
        self.prefixes = prefixes or {}
        self.settings = settings or {}
        self.apps = []
        self.folders = []
        self.files = []
        self._indexed_apps: List[IndexedRecord] = []
        self._indexed_folders: List[IndexedRecord] = []
        self._indexed_files: List[IndexedRecord] = []
        self._indexing_lock = threading.Lock()

        # Immediate quick sync indexing for zero-delay startup (<2ms)
        self._quick_sync_index()

        # Defer full async reindexing so cold Windows startup never contends with first typing
        delay_sec = 35.0 if (self.apps and self.files) else 15.0
        self._startup_timer = threading.Timer(delay_sec, self.reindex_all)
        self._startup_timer.daemon = True
        self._startup_timer.start()

    def _rebuild_indexed_records(self):
        new_apps = [create_indexed_record(a[0], a[1], "APP", a[2]) for a in self.apps]
        new_folders = [create_indexed_record(f[0], f[1], "FOLDER", f[2]) for f in self.folders]
        new_files = []
        for idx, f in enumerate(self.files):
            if idx > 0 and idx % 400 == 0:
                time.sleep(0.0005)
            new_files.append(create_indexed_record(f[0], f[1], f[2] if len(f) > 2 else "FILE", f[3] if len(f) > 3 else ""))
        self._indexed_apps = new_apps
        self._indexed_folders = new_folders
        self._indexed_files = new_files
        # Exact-token checks are on the hot path for split parsing. Keep them
        # O(1) instead of walking the entire app/folder index per query.
        self._strict_split_tokens = {
            rec.t_low for rec in new_apps if rec.category in ("APP", "FOLDER")
        }
        self._strict_split_tokens.update(rec.t_low for rec in new_folders)

    def set_settings(self, settings: dict):
        self.settings = settings or {}
        if "prefixes" in self.settings:
            self.prefixes = self.settings["prefixes"]

    def set_prefixes(self, prefixes: dict):
        self.prefixes = prefixes

    def _load_apps_cache(self) -> List[Tuple[str, str, str]]:
        """Loads cached apps from disk for instant millisecond search on startup"""
        try:
            if APPS_CACHE_FILE.exists():
                with open(APPS_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        return [(item[0], item[1], item[2]) for item in data if len(item) == 3]
        except Exception:
            pass
        return []

    def _save_apps_cache(self, apps: List[Tuple[str, str, str]]):
        """Atomically saves indexed apps list to disk cache"""
        try:
            APPS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_file = APPS_CACHE_FILE.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(apps, f, ensure_ascii=False)
            if os.path.exists(temp_file):
                os.replace(temp_file, APPS_CACHE_FILE)
        except Exception as e:
            print(f"Error saving apps cache: {e}")

    def _load_files_cache(self) -> List[Tuple[str, str, str, str]]:
        """Loads cached files (PDFs, docs, etc.) from disk for instant startup search"""
        try:
            if FILES_CACHE_FILE.exists():
                with open(FILES_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        return [(item[0], item[1], item[2], item[3]) for item in data if len(item) == 4]
        except Exception:
            pass
        return []

    def _save_files_cache(self, files: List[Tuple[str, str, str, str]]):
        """Atomically saves indexed files list to disk cache"""
        try:
            FILES_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_file = FILES_CACHE_FILE.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(files[:2500], f, ensure_ascii=False)
            if os.path.exists(temp_file):
                os.replace(temp_file, FILES_CACHE_FILE)
        except Exception as e:
            print(f"Error saving files cache: {e}")

    def _load_folders_cache(self) -> List[Tuple[str, str, str]]:
        """Loads cached folders from disk for instant startup search"""
        try:
            if FOLDERS_CACHE_FILE.exists():
                with open(FOLDERS_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        return [(item[0], item[1], item[2]) for item in data if len(item) == 3]
        except Exception:
            pass
        return []

    def _save_folders_cache(self, folders: List[Tuple[str, str, str]]):
        """Atomically saves indexed folders list to disk cache"""
        try:
            FOLDERS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_file = FOLDERS_CACHE_FILE.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(folders[:1200], f, ensure_ascii=False)
            if os.path.exists(temp_file):
                os.replace(temp_file, FOLDERS_CACHE_FILE)
        except Exception as e:
            print(f"Error saving folders cache: {e}")

    def _quick_sync_index(self):
        """Instantly indexes cached apps, files, folders, built-ins, and settings in <2ms"""
        apps = []
        seen = set()

        # 1. Load apps from persistent disk cache if available
        cached = self._load_apps_cache()
        if cached:
            for name, target, sub in cached:
                key = name.lower()
                if key == "file explorer":
                    target = "explorer.exe"
                    sub = "File Manager"
                if key not in seen:
                    seen.add(key)
                    apps.append((name, target, sub))

        # 2. Modern App Fallbacks (Guaranteed instant presence even before cache builds)
        modern_apps = [
            ("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", "Windows App"),
            ("Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "Windows App"),
            ("Telegram", "TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!Telegram", "Windows App"),
            ("Microsoft Store", "Microsoft.WindowsStore_8wekyb3d8bbwe!App", "Windows App"),
            ("Windows Terminal", "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App", "Windows App"),
            ("Visual Studio Code", "code", "Development Editor"),
            ("Google Chrome", "chrome.exe", "Web Browser"),
            ("Microsoft Edge", "msedge.exe", "Web Browser"),
            ("Word", "winword.exe", "Microsoft Word"),
            ("Excel", "excel.exe", "Microsoft Excel"),
            ("PowerPoint", "powerpnt.exe", "Microsoft PowerPoint"),
            ("Discord", "discord", "Communication App")
        ]
        for name, target, sub in modern_apps:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                apps.append((name, target, sub))

        # 3. Built-in Tools & Windows Settings
        settings_items = [
            ("Settings", "ms-settings:", "Windows Settings"),
            ("Windows Update", "ms-settings:windowsupdate", "Check & Install Updates"),
            ("Bluetooth & Devices", "ms-settings:bluetooth", "Manage Bluetooth & Connected Devices"),
            ("Wi-Fi Settings", "ms-settings:network-wifi", "Wireless Network Settings"),
            ("Network & Internet", "ms-settings:network", "Ethernet, VPN & Wi-Fi"),
            ("Display & Brightness", "ms-settings:display", "Resolution, Scaling & Monitors"),
            ("Sound Settings", "ms-settings:sound", "Audio Output & Microphone"),
            ("Installed Apps", "ms-settings:appsfeatures", "Apps & Features / Installed Software"),
            ("Default Apps", "ms-settings:defaultapps", "Change Default Applications"),
            ("Personalization", "ms-settings:personalization", "Themes, Colors & Customization"),
            ("Wallpaper & Background", "ms-settings:personalization-background", "Desktop Background Settings"),
            ("Lock Screen", "ms-settings:lockscreen", "Lock Screen Customization"),
            ("Taskbar Settings", "ms-settings:taskbar", "Taskbar Icons & Behavior"),
            ("Power & Battery", "ms-settings:powersleep", "Sleep, Screen Timeout & Battery"),
            ("Storage Settings", "ms-settings:storagesense", "Storage Space & Cleanup"),
            ("Notifications", "ms-settings:notifications", "Notification & Alert Settings"),
            ("Privacy & Security", "ms-settings:privacy", "Permissions & Privacy"),
            ("Windows Security", "windowsdefender:", "Antivirus & Threat Protection"),
            ("Date & Time", "ms-settings:dateandtime", "Clock & Regional Settings")
        ]
        for name, uri, sub in settings_items:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                apps.append((name, uri, sub))

        built_ins = [
            ("Calculator", "calc.exe", "System Calculator"),
            ("Notepad", "notepad.exe", "Text Editor"),
            ("Command Prompt", "cmd.exe", "Command Line Terminal"),
            ("PowerShell", "powershell.exe", "Windows PowerShell"),
            ("Task Manager", "taskmgr.exe", "System Resource Manager"),
            ("File Explorer", "explorer.exe", "File Manager"),
            ("Control Panel", "control.exe", "System Control Panel"),
            ("Paint", "mspaint.exe", "Drawing & Image Editor"),
            ("Snipping Tool", "snippingtool.exe", "Screen Capture Tool"),
            ("Device Manager", "devmgmt.msc", "Hardware & Device Management"),
            ("Disk Management", "diskmgmt.msc", "Drives & Partition Manager"),
            ("Registry Editor", "regedit.exe", "Windows Registry Editor"),
            ("Services", "services.msc", "Background System Services"),
            ("Event Viewer", "eventvwr.msc", "System Logs & Diagnostic Events"),
            ("Resource Monitor", "resmon.exe", "CPU, RAM & Disk Monitor"),
            ("System Information", "msinfo32.exe", "Hardware & OS Specs"),
            ("Remote Desktop", "mstsc.exe", "Remote Desktop Connection"),
            ("Character Map", "charmap.exe", "Special Characters & Symbols")
        ]
        for name, cmd, sub in built_ins:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                apps.append((name, cmd, sub))

        # 4. Quick shallow shortcuts scan (only on cold initial run if cache is empty)
        if not cached:
            for base_dir in [
                os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
                os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
                str(Path.home() / "Desktop"),
                "C:/Users/Public/Desktop"
            ]:
                for stem, path_str in safe_scan_shortcuts(base_dir, max_depth=1):
                    key = stem.lower()
                    if key not in seen and "uninstall" not in key and "remove" not in key:
                        seen.add(key)
                        apps.append((stem, path_str, "Application"))

        # 5. Quick cached folders and files
        cached_folders = self._load_folders_cache()
        cached_files = self._load_files_cache()

        folders = list(cached_folders)
        seen_f_paths = {f[1].lower() for f in folders}
        for p in [Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads", Path.home() / "Pictures", Path.home() / "Videos", Path.home() / "Music"]:
            if p.exists() and str(p).lower() not in seen_f_paths:
                folders.append((p.name, str(p), f"Folder • in {p.parent}"))

        self.apps = apps
        self.folders = folders
        self.files = cached_files
        self._rebuild_indexed_records()

    def reindex_all(self):
        t = threading.Thread(target=self._background_index, daemon=True)
        t.start()

    def _background_index(self):
        with self._indexing_lock:
            self.reindex_apps()
            self.reindex_folders_and_files()

    def _fetch_start_apps(self) -> List[Tuple[str, str, str]]:
        """Index all Windows Store, UWP, PWA, and registered Start Menu apps via PowerShell Get-StartApps"""
        apps = []
        try:
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-StartApps | ConvertTo-Json -Compress"]
            proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=8, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name = item.get("Name", "").strip()
                    app_id = item.get("AppID", "").strip()
                    if name and app_id and "uninstall" not in name.lower():
                        sub = "Application"
                        if "!" in app_id:
                            sub = "Windows App"
                        elif app_id.endswith(".exe"):
                            sub = "Desktop Application"
                        apps.append((name, app_id, sub))
        except Exception as e:
            print(f"Error indexing Get-StartApps: {e}")
        return apps

    def _fetch_app_paths(self) -> List[Tuple[str, str, str]]:
        """Index registered Windows applications from registry App Paths"""
        apps = []
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths") as key:
                        num_subkeys, _, _ = winreg.QueryInfoKey(key)
                        for i in range(num_subkeys):
                            try:
                                subkey_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, subkey_name) as subkey:
                                    target_path, _ = winreg.QueryValueEx(subkey, "")
                                    name = subkey_name.rsplit(".", 1)[0].replace("_", " ").capitalize()
                                    if target_path and os.path.exists(target_path):
                                        apps.append((name, target_path, "Application"))
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass
        return apps

    def reindex_apps(self):
        apps = []
        seen = set()

        # 1. High priority: Windows Start Apps (Covers WhatsApp, Copilot, Terminal, Store, Spotify, Chrome, etc.)
        for name, app_id, sub in self._fetch_start_apps():
            key = name.lower()
            if key == "file explorer":
                app_id = "explorer.exe"
                sub = "File Manager"
            if key not in seen:
                seen.add(key)
                apps.append((name, app_id, sub))

        # 2. Start Menu Shortcuts & Desktop (Safe Scanner)
        search_dirs = [
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
            str(Path.home() / "Desktop"),
            "C:/Users/Public/Desktop"
        ]

        for base_dir in search_dirs:
            for stem, path_str in safe_scan_shortcuts(base_dir, max_depth=4):
                key = stem.lower()
                if key in seen or "uninstall" in key or "remove" in key:
                    continue
                seen.add(key)
                apps.append((stem, path_str, "Application"))

        # 3. Registry App Paths
        for name, target, sub in self._fetch_app_paths():
            key = name.lower()
            if key not in seen:
                seen.add(key)
                apps.append((name, target, sub))

        # 4. Check WhatsApp desktop locations if not already discovered
        if "whatsapp" not in seen:
            wa_candidates = [
                ("WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", "Windows App"),
                ("WhatsApp", "whatsapp:", "WhatsApp Messenger"),
                ("WhatsApp", os.path.expandvars(r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe"), "Desktop Application"),
                ("WhatsApp", os.path.expandvars(r"%LOCALAPPDATA%\Programs\WhatsApp\WhatsApp.exe"), "Desktop Application"),
            ]
            for wa_name, wa_tgt, wa_sub in wa_candidates:
                if wa_tgt.startswith("5319275A") or wa_tgt == "whatsapp:" or os.path.exists(wa_tgt):
                    apps.append((wa_name, wa_tgt, wa_sub))
                    seen.add("whatsapp")
                    break

        # 5. Windows Settings
        settings_items = [
            ("Settings", "ms-settings:", "Windows Settings"),
            ("Windows Update", "ms-settings:windowsupdate", "Check & Install Updates"),
            ("Bluetooth & Devices", "ms-settings:bluetooth", "Manage Bluetooth & Connected Devices"),
            ("Wi-Fi Settings", "ms-settings:network-wifi", "Wireless Network Settings"),
            ("Network & Internet", "ms-settings:network", "Ethernet, VPN & Wi-Fi"),
            ("Display & Brightness", "ms-settings:display", "Resolution, Scaling & Monitors"),
            ("Sound Settings", "ms-settings:sound", "Audio Output & Microphone"),
            ("Installed Apps", "ms-settings:appsfeatures", "Apps & Features / Installed Software"),
            ("Default Apps", "ms-settings:defaultapps", "Change Default Applications"),
            ("Personalization", "ms-settings:personalization", "Themes, Colors & Customization"),
            ("Wallpaper & Background", "ms-settings:personalization-background", "Desktop Background Settings"),
            ("Lock Screen", "ms-settings:lockscreen", "Lock Screen Customization"),
            ("Taskbar Settings", "ms-settings:taskbar", "Taskbar Icons & Behavior"),
            ("Power & Battery", "ms-settings:powersleep", "Sleep, Screen Timeout & Battery"),
            ("Storage Settings", "ms-settings:storagesense", "Storage Space & Cleanup"),
            ("Notifications", "ms-settings:notifications", "Notification & Alert Settings"),
            ("Privacy & Security", "ms-settings:privacy", "Permissions & Privacy"),
            ("Windows Security", "windowsdefender:", "Antivirus & Threat Protection"),
            ("Date & Time", "ms-settings:dateandtime", "Clock & Regional Settings")
        ]
        for name, uri, sub in settings_items:
            if name.lower() not in seen:
                seen.add(name.lower())
                apps.append((name, uri, sub))

        # 6. Built-in System Tools
        built_ins = [
            ("Calculator", "calc.exe", "System Calculator"),
            ("Notepad", "notepad.exe", "Text Editor"),
            ("Command Prompt", "cmd.exe", "Command Line Terminal"),
            ("PowerShell", "powershell.exe", "Windows PowerShell"),
            ("Task Manager", "taskmgr.exe", "System Resource Manager"),
            ("File Explorer", "explorer.exe", "File Manager"),
            ("Control Panel", "control.exe", "System Control Panel"),
            ("Paint", "mspaint.exe", "Drawing & Image Editor"),
            ("Snipping Tool", "snippingtool.exe", "Screen Capture Tool"),
            ("Device Manager", "devmgmt.msc", "Hardware & Device Management"),
            ("Disk Management", "diskmgmt.msc", "Drives & Partition Manager"),
            ("Registry Editor", "regedit.exe", "Windows Registry Editor"),
            ("Services", "services.msc", "Background System Services"),
            ("Event Viewer", "eventvwr.msc", "System Logs & Diagnostic Events"),
            ("Resource Monitor", "resmon.exe", "CPU, RAM & Disk Monitor"),
            ("System Information", "msinfo32.exe", "Hardware & OS Specs"),
            ("Remote Desktop", "mstsc.exe", "Remote Desktop Connection"),
            ("Character Map", "charmap.exe", "Special Characters & Symbols")
        ]
        for name, cmd, sub in built_ins:
            if name.lower() not in seen:
                seen.add(name.lower())
                apps.append((name, cmd, sub))

        if apps:
            self.apps = apps
            self._save_apps_cache(apps)
            self._rebuild_indexed_records()

    def reindex_folders_and_files(self):
        """Fast indexed deep search of user libraries, project directories, and system drives"""
        folders = []
        files = []
        seen_paths = set()

        # 1. User Home Libraries (Depth 5)
        user_places = [
            str(Path.home() / "Desktop"),
            str(Path.home() / "Documents"),
            str(Path.home() / "Downloads"),
            str(Path.home() / "Pictures"),
            str(Path.home() / "Videos"),
            str(Path.home() / "Music"),
            str(Path.home() / "OneDrive")
        ]

        for base in user_places:
            if os.path.exists(base):
                sub_folders, sub_files = safe_scan_dir(base, max_depth=5)
                for f_name, f_path, f_sub in sub_folders:
                    if f_path.lower() not in seen_paths:
                        seen_paths.add(f_path.lower())
                        folders.append((f_name, f_path, f_sub))
                for file_name, file_path, file_cat, file_sub in sub_files:
                    if file_path.lower() not in seen_paths:
                        seen_paths.add(file_path.lower())
                        files.append((file_name, file_path, file_cat, file_sub))

        # 2. Other Active Fixed Drives (e.g. D:\, E:\)
        try:
            kernel32 = ctypes.windll.kernel32
            for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
                drv = f"{letter}:\\"
                # Check DRIVE_FIXED == 3
                try:
                    if kernel32.GetDriveTypeW(drv) == 3 and os.path.exists(drv):
                        sub_folders, sub_files = safe_scan_dir(drv, max_depth=2)
                        for f_name, f_path, f_sub in sub_folders:
                            if f_path.lower() not in seen_paths:
                                seen_paths.add(f_path.lower())
                                folders.append((f_name, f_path, f_sub))
                        for file_name, file_path, file_cat, file_sub in sub_files:
                            if file_path.lower() not in seen_paths:
                                seen_paths.add(file_path.lower())
                                files.append((file_name, file_path, file_cat, file_sub))
                        time.sleep(0.01)  # cooperative yield so system I/O is never blocked
                except Exception:
                    pass
        except Exception:
            pass

        if folders:
            self.folders = folders
            self._save_folders_cache(folders)
        if files:
            self.files = files
            self._save_files_cache(files)
        self._rebuild_indexed_records()

    def _open_target(self, target: str):
        try:
            if not target:
                return

            low_t = target.strip().lower()
            if low_t in ("explorer.exe", "explorer", "file explorer", "microsoft.windows.explorer", "shell:mycomputerfolder", "this pc"):
                subprocess.Popen(
                    ["explorer.exe", "shell:MyComputerFolder"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return

            # 1. Direct Web URLs & Windows Settings protocols
            if target.startswith("http://") or target.startswith("https://") or \
               target.startswith("ms-settings:") or target.startswith("windowsdefender:") or \
               target.startswith("mailto:") or target.startswith("whatsapp:"):
                webbrowser.open(target)
                return

            # 2. Explicit shell:AppsFolder targets
            if target.startswith("shell:AppsFolder\\"):
                try:
                    os.startfile(target)
                    return
                except Exception:
                    subprocess.Popen(f'explorer.exe "{target}"', shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return

            # 3. Existing Local Files & Folders
            if os.path.exists(target):
                try:
                    os.startfile(target)
                    return
                except Exception:
                    try:
                        subprocess.Popen(f'explorer.exe "{target}"', shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return
                    except Exception:
                        pass

            # 4. Windows StartApps / UWP App IDs
            try:
                os.startfile(f"shell:AppsFolder\\{target}")
                return
            except Exception:
                pass

            # 5. Direct Executables / System Tools (e.g. calc.exe, notepad.exe, cmd.exe)
            try:
                os.startfile(target)
                return
            except Exception:
                pass

            # 6. Explorer shell:AppsFolder launcher fallback
            try:
                subprocess.Popen(f'explorer.exe shell:AppsFolder\\"{target}"', shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass

            # 7. Start command launcher fallback
            try:
                subprocess.Popen(f'start "" "{target}"', shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass

        except Exception as e:
            print(f"Error opening target {target}: {e}")

    def _find_direct_exe(self, exe_name: str, fallback_paths: List[str]) -> Optional[str]:
        """Resolve an executable path quickly via common installation paths or PATH."""
        for p in fallback_paths:
            expanded = os.path.expandvars(p)
            if "*" in expanded:
                matches = glob.glob(expanded)
                if matches:
                    return matches[0]
            elif os.path.exists(expanded):
                return expanded
        found = shutil.which(exe_name)
        if found:
            return found
        return None

    def _resolve_split_part(self, raw_part: str) -> Optional[ResolvedSplitTarget]:
        """
        Resolve a single token from a multi-split query (e.g. 'edge', 'word', 'chatgpt',
        'vs code', 'story.pdf') into a launchable & window-trackable ResolvedSplitTarget.
        """
        part = raw_part.strip().strip('"').strip("'")
        if not part:
            return None
        low = part.lower().strip()
        for prefix in ("open ", "launch ", "start ", "run "):
            if low.startswith(prefix) and len(low) > len(prefix):
                part = part[len(prefix):].strip()
                low = part.lower()

        # 1. Explicit Web Applications ("chatgpt", "claude", "youtube", "github", etc.)
        if low in WEB_APP_TARGETS:
            title, url, sub = WEB_APP_TARGETS[low]
            return ResolvedSplitTarget(
                query_part=raw_part,
                title=title,
                subtitle=sub,
                category="WEB APP",
                target=url,
                kind="web",
                exe_Hints=[],
                title_hints=[
                    title.lower(),
                    low,
                    url.replace("https://", "").replace("http://", "").split("/")[0].lower(),
                ],
            )

        # 2. Web omnibox shortcut (e.g. "yt: rust", "g: python", "gh: torvalds")
        if ":" in low:
            prefix, rest = part.split(":", 1)
            p_low = prefix.strip().lower()
            r_clean = rest.strip()
            web_prefixes = {
                "g": ("Google", "https://www.google.com/search?q="),
                "google": ("Google", "https://www.google.com/search?q="),
                "yt": ("YouTube", "https://www.youtube.com/results?search_query="),
                "youtube": ("YouTube", "https://www.youtube.com/results?search_query="),
                "gh": ("GitHub", "https://github.com/search?q="),
                "github": ("GitHub", "https://github.com/search?q="),
                "so": ("StackOverflow", "https://stackoverflow.com/search?q="),
                "wiki": ("Wikipedia", "https://en.wikipedia.org/wiki/Special:Search?search="),
                "reddit": ("Reddit", "https://www.reddit.com/search/?q="),
                "chatgpt": ("ChatGPT", "https://chatgpt.com/?q="),
                "ai": ("ChatGPT", "https://chatgpt.com/?q="),
                "perplexity": ("Perplexity", "https://www.perplexity.ai/search?q="),
            }
            if p_low in web_prefixes and r_clean:
                name, base_url = web_prefixes[p_low]
                url = f"{base_url}{urllib.parse.quote_plus(r_clean)}"
                return ResolvedSplitTarget(
                    query_part=raw_part,
                    title=f"{name}: {r_clean}",
                    subtitle=f"{name} Web Search (Default Browser)",
                    category="WEB",
                    target=url,
                    kind="web",
                    exe_Hints=[],
                    title_hints=[name.lower(), r_clean.lower()],
                )

        # 3. Direct URL or Domain (e.g. "https://...", "github.com", "openai.com")
        if is_likely_web_domain(low):
            url = part if (low.startswith("http://") or low.startswith("https://")) else f"https://{part}"
            domain_label = url.replace("https://", "").replace("http://", "").split("/")[0]
            return ResolvedSplitTarget(
                query_part=raw_part,
                title=domain_label,
                subtitle=f"Website ({url})",
                category="URL",
                target=url,
                kind="web",
                exe_Hints=[],
                title_hints=[domain_label.lower(), domain_label.split(".")[0].lower()],
            )

        # 4. File with extension (e.g. "story.pdf", "notes.txt", "report.docx", or absolute path)
        if os.path.exists(part):
            abs_p = os.path.abspath(part)
            base_name = os.path.basename(abs_p)
            stem = os.path.splitext(base_name)[0].lower()
            ext = os.path.splitext(base_name)[1].lower()
            cat = "PDF" if ext == ".pdf" else ("FOLDER" if os.path.isdir(abs_p) else "FILE")
            return ResolvedSplitTarget(
                query_part=raw_part,
                title=base_name,
                subtitle=abs_p,
                category=cat,
                target=abs_p,
                kind="folder" if os.path.isdir(abs_p) else "file",
                exe_Hints=["explorer.exe"] if os.path.isdir(abs_p) else [],
                title_hints=[base_name.lower(), stem],
            )

        if "." in low and not low.startswith("."):
            ext = low.rsplit(".", 1)[-1]
            if f".{ext}" in KNOWN_FILE_EXTENSIONS or ext in KNOWN_FILE_EXTENSIONS:
                best_file = None
                best_score = -1
                stem = os.path.splitext(low)[0]
                for rec in self._indexed_files:
                    if rec.t_low == low or os.path.basename(rec.tgt_low) == low:
                        best_file = rec
                        best_score = 1000
                        break
                    elif low in rec.t_low or low in os.path.basename(rec.tgt_low):
                        s = score_record(low, rec)
                        if s > best_score:
                            best_score = s
                            best_file = rec
                    elif rec.t_low == stem and rec.tgt_low.endswith("." + ext):
                        best_file = rec
                        best_score = 960
                        break

                if best_file is None:
                    try:
                        win_hits = self._query_windows_search_index(part, max_items=4)
                        for rec in win_hits:
                            if rec.tgt_low.endswith("." + ext):
                                best_file = rec
                                break
                    except Exception:
                        pass

                if best_file is not None and os.path.exists(best_file.target):
                    base_name = os.path.basename(best_file.target)
                    return ResolvedSplitTarget(
                        query_part=raw_part,
                        title=best_file.title,
                        subtitle=best_file.subtitle,
                        category="PDF" if ext == "pdf" else best_file.category,
                        target=best_file.target,
                        kind="file",
                        exe_Hints=[],
                        title_hints=[base_name.lower(), stem.lower(), best_file.t_low],
                    )
                else:
                    created_path = WorkspaceSplitManager.ensure_workspace_file(part)
                    base_name = os.path.basename(created_path)
                    return ResolvedSplitTarget(
                        query_part=raw_part,
                        title=base_name,
                        subtitle=f"Document ({created_path})",
                        category="PDF" if ext == "pdf" else "FILE",
                        target=created_path,
                        kind="file",
                        exe_Hints=[],
                        title_hints=[base_name.lower(), stem.lower()],
                    )

        # 5. Fast-Path Core Desktop Apps ("edge", "word", "vs code", "chrome", "excel", "powerpoint", etc.)
        if low in ("edge", "ms edge", "microsoft edge", "msedge"):
            exe = self._find_direct_exe("msedge.exe", [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]) or "msedge.exe"
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Microsoft Edge",
                subtitle="Web Browser",
                category="APP",
                target=exe,
                kind="app",
                exe_Hints=["msedge.exe"],
                title_hints=["edge", "microsoft​ edge", "microsoft edge"],
                launch_args=["--new-window"],
            )

        if low in ("chrome", "google chrome"):
            exe = self._find_direct_exe("chrome.exe", [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            ]) or "chrome.exe"
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Google Chrome",
                subtitle="Web Browser",
                category="APP",
                target=exe,
                kind="app",
                exe_Hints=["chrome.exe"],
                title_hints=["chrome", "google chrome", "new tab"],
                launch_args=["--new-window"],
            )

        if low in ("vs code", "vscode", "visual studio code", "code"):
            exe = self._find_direct_exe("Code.exe", [
                r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
                r"C:\Program Files\Microsoft VS Code\Code.exe",
            ]) or "Code.exe"
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Visual Studio Code",
                subtitle="Code Editor",
                category="APP",
                target=exe,
                kind="app",
                exe_Hints=["code.exe"],
                title_hints=["visual studio code", "vs code"],
                launch_args=["-n"],
            )

        if low in ("word", "ms word", "microsoft word", "winword"):
            exe = self._find_direct_exe("WINWORD.EXE", [
                r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
                r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
                r"C:\Program Files\Microsoft Office\Office16\WINWORD.EXE",
            ])
            if not exe:
                for rec in self._indexed_apps:
                    if rec.t_low in ("word", "microsoft word") or "winword" in rec.tgt_low:
                        exe = rec.target
                        break
            if exe:
                return ResolvedSplitTarget(
                    query_part=raw_part,
                    title="Word",
                    subtitle="Microsoft Word",
                    category="APP",
                    target=exe,
                    kind="app",
                    exe_Hints=["winword.exe", "webviewhost.exe", "msedgewebview2.exe"],
                    title_hints=["word", "document"],
                )
            else:
                doc_path = WorkspaceSplitManager.ensure_workspace_file("Document.rtf")
                return ResolvedSplitTarget(
                    query_part=raw_part,
                    title="Word",
                    subtitle="Document Editor",
                    category="APP",
                    target=doc_path,
                    kind="file",
                    exe_Hints=["winword.exe", "wordpad.exe", "write.exe"],
                    title_hints=["word", "document"],
                )

        if low in ("excel", "ms excel", "microsoft excel"):
            exe = self._find_direct_exe("EXCEL.EXE", [
                r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
                r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE",
            ])
            if exe:
                return ResolvedSplitTarget(
                    query_part=raw_part,
                    title="Excel",
                    subtitle="Microsoft Excel",
                    category="APP",
                    target=exe,
                    kind="app",
                    exe_Hints=["excel.exe"],
                    title_hints=["excel", "book"],
                )

        if low in ("powerpoint", "ppt", "ms powerpoint", "microsoft powerpoint", "powerpnt"):
            exe = self._find_direct_exe("POWERPNT.EXE", [
                r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
                r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE",
            ])
            if exe:
                return ResolvedSplitTarget(
                    query_part=raw_part,
                    title="PowerPoint",
                    subtitle="Microsoft PowerPoint",
                    category="APP",
                    target=exe,
                    kind="app",
                    exe_Hints=["powerpnt.exe"],
                    title_hints=["powerpoint", "presentation"],
                )

        if low in ("notepad", "note pad", "editor"):
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Notepad",
                subtitle="Windows Text Editor",
                category="APP",
                target="notepad.exe",
                kind="app",
                exe_Hints=["notepad.exe"],
                title_hints=["notepad", "untitled"],
                class_hints=["Notepad"],
            )

        if low in ("calc", "calculator"):
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Calculator",
                subtitle="Windows Calculator",
                category="APP",
                target="calc.exe",
                kind="app",
                exe_Hints=["calculatorapp.exe", "calc.exe", "applicationframehost.exe"],
                title_hints=["calculator"],
            )

        if low in ("explorer", "files", "file explorer", "windows explorer", "this pc", "my computer"):
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="File Explorer",
                subtitle="Windows File Explorer",
                category="APP",
                target="explorer.exe",
                kind="folder",
                exe_Hints=["explorer.exe"],
                title_hints=["file explorer", "this pc", "home"],
                class_hints=["CabinetWClass", "ExploreWClass"],
                prefer_new_window=False,
            )

        if low in ("brave", "brave browser"):
            exe = self._find_direct_exe("brave.exe", [
                r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            ]) or "brave.exe"
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Brave",
                subtitle="Web Browser",
                category="APP",
                target=exe,
                kind="app",
                exe_Hints=["brave.exe"],
                title_hints=["brave"],
                launch_args=["--new-window"],
            )

        if low in ("firefox", "mozilla firefox"):
            exe = self._find_direct_exe("firefox.exe", [
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            ]) or "firefox.exe"
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Mozilla Firefox",
                subtitle="Web Browser",
                category="APP",
                target=exe,
                kind="app",
                exe_Hints=["firefox.exe"],
                title_hints=["firefox", "mozilla firefox"],
                launch_args=["-new-window"],
            )

        if low in ("terminal", "wt", "windows terminal", "console"):
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Windows Terminal",
                subtitle="Command Line Terminal",
                category="APP",
                target="wt.exe",
                kind="app",
                exe_Hints=["windowsterminal.exe", "wt.exe", "cmd.exe", "powershell.exe"],
                title_hints=["terminal", "powershell", "command prompt"],
            )

        if low in ("cmd", "command prompt"):
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="Command Prompt",
                subtitle="Windows Command Processor",
                category="APP",
                target="cmd.exe",
                kind="app",
                exe_Hints=["cmd.exe", "windowsterminal.exe", "conhost.exe"],
                title_hints=["command prompt", "cmd.exe"],
            )

        if low in ("powershell", "ps", "pwsh"):
            return ResolvedSplitTarget(
                query_part=raw_part,
                title="PowerShell",
                subtitle="Windows PowerShell",
                category="APP",
                target="powershell.exe",
                kind="app",
                exe_Hints=["powershell.exe", "windowsterminal.exe", "pwsh.exe"],
                title_hints=["powershell"],
            )

        # Fast-path User Library Folders (Downloads, Documents, Desktop, Pictures, Videos, Music)
        user_lib_map = {
            "downloads": ("Downloads", Path.home() / "Downloads"),
            "download": ("Downloads", Path.home() / "Downloads"),
            "documents": ("Documents", Path.home() / "Documents"),
            "docs": ("Documents", Path.home() / "Documents"),
            "desktop": ("Desktop", Path.home() / "Desktop"),
            "pictures": ("Pictures", Path.home() / "Pictures"),
            "photos": ("Pictures", Path.home() / "Pictures"),
            "videos": ("Videos", Path.home() / "Videos"),
            "music": ("Music", Path.home() / "Music"),
        }
        if low in user_lib_map:
            lib_title, lib_path = user_lib_map[low]
            if lib_path.exists():
                return ResolvedSplitTarget(
                    query_part=raw_part,
                    title=lib_title,
                    subtitle=f"Folder • {lib_path}",
                    category="FOLDER",
                    target=str(lib_path),
                    kind="folder",
                    exe_Hints=["explorer.exe"],
                    title_hints=[lib_title.lower()],
                    class_hints=["CabinetWClass", "ExploreWClass"],
                    prefer_new_window=True,
                )

        # 6. Indexed Apps, Settings, Folders, and Files
        best_rec: Optional[IndexedRecord] = None
        best_score = 0
        is_alias_q = low in ALIASES
        alias_tgts = ALIASES.get(low)

        for rec in self._indexed_apps:
            s = score_record(low, rec, is_alias=is_alias_q, alias_targets=alias_tgts)
            if s > best_score:
                best_score = s
                best_rec = rec

        if best_score < 600:
            for rec in getattr(self, "_indexed_folders", []):
                s = score_record(low, rec, is_alias=is_alias_q, alias_targets=alias_tgts)
                if s > best_score:
                    best_score = s
                    best_rec = rec

        if best_score < 600:
            for rec in self._indexed_files:
                s = score_record(low, rec, is_alias=is_alias_q, alias_targets=alias_tgts)
                if s > best_score:
                    best_score = s
                    best_rec = rec

        if best_rec is not None and best_score >= 120:
            tgt = best_rec.target
            cat = best_rec.category
            exe_hints: List[str] = []
            if tgt.lower().endswith(".exe"):
                exe_hints.append(os.path.basename(tgt).lower())
            for alias_k, alias_list in ALIASES.items():
                if alias_k == low or alias_k == best_rec.t_low:
                    items = alias_list if isinstance(alias_list, (list, tuple)) else [alias_list]
                    for av in items:
                        av_str = str(av).strip().lower()
                        if av_str.endswith(".exe"):
                            exe_hints.append(av_str)
                        else:
                            exe_hints.append(f"{av_str}.exe")
            if not exe_hints and cat == "APP":
                stem_clean = re.sub(r"[^a-z0-9]", "", best_rec.t_low)
                if stem_clean:
                    exe_hints.append(f"{stem_clean}.exe")
                q_clean = re.sub(r"[^a-z0-9]", "", low)
                if q_clean and f"{q_clean}.exe" not in exe_hints:
                    exe_hints.append(f"{q_clean}.exe")
            kind = "app"
            cls_hints: List[str] = []
            pref_new = False
            if cat == "FOLDER" or os.path.isdir(tgt) or tgt.strip().lower() in ("explorer.exe", "microsoft.windows.explorer"):
                kind = "folder"
                exe_hints.append("explorer.exe")
                cls_hints = ["CabinetWClass", "ExploreWClass"]
                pref_new = (cat == "FOLDER" or os.path.isdir(tgt))
            elif cat in ("FILE", "PDF", "IMAGE", "MEDIA", "CODE") and not tgt.lower().endswith((".exe", ".lnk")):
                kind = "file"
                pref_new = True

            return ResolvedSplitTarget(
                query_part=raw_part,
                title=best_rec.title,
                subtitle=best_rec.subtitle,
                category=cat,
                target=tgt,
                kind=kind,
                exe_Hints=list(dict.fromkeys(exe_hints)),
                title_hints=[best_rec.t_low, low],
                class_hints=cls_hints,
                prefer_new_window=pref_new,
            )

        # 7. Check Windows Search index on-demand for uncached files
        try:
            win_hits = self._query_windows_search_index(part, max_items=3)
            if win_hits:
                rec = win_hits[0]
                return ResolvedSplitTarget(
                    query_part=raw_part,
                    title=rec.title,
                    subtitle=rec.subtitle,
                    category=rec.category,
                    target=rec.target,
                    kind="folder" if rec.category == "FOLDER" else "file",
                    exe_Hints=["explorer.exe"] if rec.category == "FOLDER" else [],
                    title_hints=[rec.t_low, low],
                    class_hints=["CabinetWClass", "ExploreWClass"] if rec.category == "FOLDER" else [],
                    prefer_new_window=True,
                )
        except Exception:
            pass

        return None

    def _is_strict_split_token(self, phrase: str) -> bool:
        """
        Returns True if `phrase` is a recognized standalone application, web app, URL, folder, or file
        suitable for space-separated multi-target splitting (e.g., 'chrome vs code', 'chatgpt youtube').
        """
        low = phrase.strip().lower()
        if not low:
            return False
        if low in WEB_APP_TARGETS:
            return True
        if low in (
            "edge", "ms edge", "microsoft edge", "msedge",
            "chrome", "google chrome",
            "vs code", "vscode", "visual studio code", "code",
            "word", "ms word", "microsoft word", "winword",
            "excel", "ms excel", "microsoft excel",
            "powerpoint", "ppt", "ms powerpoint", "microsoft powerpoint", "powerpnt",
            "notepad", "note pad", "editor",
            "calc", "calculator",
            "explorer", "files", "file explorer", "windows explorer", "this pc", "my computer",
            "downloads", "documents", "desktop", "pictures", "videos", "music",
            "brave", "brave browser",
            "firefox", "mozilla firefox",
            "terminal", "wt", "windows terminal", "console",
            "cmd", "command prompt",
            "powershell", "ps", "pwsh",
        ):
            return True
        if low in ALIASES:
            return True
        if is_likely_web_domain(low):
            return True
        if "." in low and not low.startswith("."):
            ext = low.rsplit(".", 1)[-1]
            if f".{ext}" in KNOWN_FILE_EXTENSIONS or ext in KNOWN_FILE_EXTENSIONS:
                return True
        return low in getattr(self, "_strict_split_tokens", ())

    def _split_space_separated_targets(self, query: str) -> Optional[List[str]]:
        """
        Attempts to segment a space-separated query like 'chrome vs code', 'chatgpt youtube',
        or 'chrome vs code notepad' into 2, 3, or 4 recognized targets using greedy longest-phrase matching.
        Returns None if the whole query is a single known target or if any token cannot be recognized.
        """
        q_clean = query.strip()
        low_q = q_clean.lower()
        words = q_clean.split()
        if len(words) < 2 or len(words) > 10:
            return None
        if self._is_strict_split_token(low_q):
            return None

        segments: List[str] = []
        i = 0
        n = len(words)
        while i < n:
            matched_phrase = None
            matched_len = 0
            for span in (3, 2, 1):
                if i + span <= n:
                    candidate = " ".join(words[i:i + span])
                    if self._is_strict_split_token(candidate):
                        matched_phrase = candidate
                        matched_len = span
                        break
            if matched_phrase is None:
                return None
            segments.append(matched_phrase)
            i += matched_len

        if 2 <= len(segments) <= 4:
            return segments
        return None

    def _search_multi_split(self, query: str, max_results: int = 8) -> Optional[List[SearchItem]]:
        """
        Parse multi-application / multi-file / multi-web queries (2, 3, or 4 items)
        such as:
          - "chrome vs code"
          - "chatgpt youtube"
          - "edge and word"
          - "chatgpt and vs code"
          - "story.pdf, word and vs code"
          - "edge, word, vs code and notepad"
        and return smooth split-screen / tiled workspace launch actions.
        """
        q = query.strip()
        low_q = q.lower()

        if any(low_q.startswith(p) for p in (
            "calc:", "note:", "clip:", "convert:", "color:", "time:", "timer:", "sys:", "exec:",
            "text ", "text:", "message ", "message:", "msg ", "msg:", "whatsapp ", "whatsapp:", "wa ", "wa:", "send "
        )):
            return None

        for split_prefix in ("split ", "tile ", "split: ", "tile: "):
            if low_q.startswith(split_prefix) and len(q) > len(split_prefix):
                q = q[len(split_prefix):].strip()
                low_q = q.lower()
                break

        if any(kw in low_q for kw in (" to ", " in ", " as ")) and any(ch.isdigit() for ch in low_q):
            return None

        has_delim = (
            "," in low_q
            or " and " in low_q
            or " & " in low_q
            or " + " in low_q
            or " | " in low_q
            or " / " in low_q
            or " with " in low_q
            or low_q.endswith(" and")
            or low_q.endswith(",")
            or low_q.endswith(" &")
            or low_q.endswith(" +")
            or low_q.endswith(" |")
            or low_q.endswith(" /")
            or low_q.endswith(" with")
        )

        if not has_delim:
            space_parts = self._split_space_separated_targets(q)
            if not space_parts:
                return None
            parts = space_parts
            trailing_pending = False
        else:
            # Check if user is still typing after a trailing delimiter (e.g. "edge and ")
            trailing_pending = False
            working_q = q
            for suffix in (" and", " with", ",", " &", " +", " |", " /"):
                if low_q.endswith(suffix):
                    trailing_pending = True
                    working_q = q[:-len(suffix)].strip()
                    break

            raw_parts = re.split(
                r'\s*(?:,\s*and\s+|,\s*&\s+|,\s*\+\s+|,|\s+and\s+|\s+with\s+|\s+&\s+|\s+\+\s+|\s+\|\s+|\s+/\s+)\s*',
                working_q,
                flags=re.IGNORECASE
            )
            parts = []
            for rp in raw_parts:
                rp_clean = rp.strip()
                if not rp_clean:
                    continue
                sub_space = self._split_space_separated_targets(rp_clean)
                if sub_space:
                    parts.extend(sub_space)
                else:
                    parts.append(rp_clean)

        if trailing_pending and 1 <= len(parts) <= 3:
            resolved_so_far: List[ResolvedSplitTarget] = []
            for p in parts:
                r = self._resolve_split_part(p)
                if r is None:
                    return None
                resolved_so_far.append(r)
            names = "  |  ".join(t.title for t in resolved_so_far)
            next_slot = len(resolved_so_far) + 1
            return [
                SearchItem(
                    id="split_pending_preview",
                    title=f"Split Screen: {names}  +  [Type App/File/Web #{next_slot}...]",
                    subtitle=f"Keep typing the next app, website, or file name to tile {next_slot} windows side-by-side",
                    category="SPLIT",
                    target=q,
                    action=lambda targets=list(resolved_so_far): WorkspaceSplitManager.instance().launch_split(
                        targets, "left_right" if len(targets) == 2 else "main_left_stack_right", self._open_target
                    ) if len(targets) >= 2 else None,
                    score=1250,
                )
            ]

        if len(parts) < 2 or len(parts) > 4:
            return None

        resolved: List[ResolvedSplitTarget] = []
        for p in parts:
            r = self._resolve_split_part(p)
            if r is None:
                return None
            resolved.append(r)

        count = len(resolved)
        split_items: List[SearchItem] = []

        if count == 2:
            t1, t2 = resolved[0], resolved[1]
            split_items.append(SearchItem(
                id=f"split_2_lr_{t1.title}_{t2.title}",
                title=f"{t1.title}  ◧  Left   |   Right  ◨  {t2.title}",
                subtitle=f"Dual Split Screen (50% / 50%)  •  Left: {t1.title} ({t1.category})  •  Right: {t2.title} ({t2.category})",
                category="SPLIT",
                target=t1.target,
                action=lambda items=list(resolved): WorkspaceSplitManager.instance().launch_split(
                    items, "left_right", self._open_target
                ),
                score=1500,
            ))
            split_items.append(SearchItem(
                id=f"split_2_swap_{t2.title}_{t1.title}",
                title=f"{t2.title}  ◧  Left   |   Right  ◨  {t1.title}  (Swap Sides)",
                subtitle=f"Reversed Dual Split (50% / 50%)  •  Left: {t2.title}  •  Right: {t1.title}",
                category="SPLIT",
                target=t2.target,
                action=lambda items=[resolved[1], resolved[0]]: WorkspaceSplitManager.instance().launch_split(
                    items, "left_right", self._open_target
                ),
                score=1480,
            ))
            split_items.append(SearchItem(
                id=f"split_2_focus_{t1.title}_{t2.title}",
                title=f"{t1.title} (65% Left)  |  {t2.title} (35% Right)",
                subtitle=f"Primary Focus Split (65% / 35%)  •  Wide Left: {t1.title}  •  Sidebar Right: {t2.title}",
                category="SPLIT",
                target=t1.target,
                action=lambda items=list(resolved): WorkspaceSplitManager.instance().launch_split(
                    items, "focus_left", self._open_target
                ),
                score=1460,
            ))
            split_items.append(SearchItem(
                id=f"split_2_tb_{t1.title}_{t2.title}",
                title=f"{t1.title} (Top Half)  /  {t2.title} (Bottom Half)",
                subtitle=f"Vertical Stacked Split (Top / Bottom)  •  Top: {t1.title}  •  Bottom: {t2.title}",
                category="SPLIT",
                target=t1.target,
                action=lambda items=list(resolved): WorkspaceSplitManager.instance().launch_split(
                    items, "top_bottom", self._open_target
                ),
                score=1440,
            ))

        elif count == 3:
            t1, t2, t3 = resolved[0], resolved[1], resolved[2]
            split_items.append(SearchItem(
                id=f"split_3_main_stack_{t1.title}_{t2.title}_{t3.title}",
                title=f"◧ {t1.title} (Left Half)  +  [{t2.title} / {t3.title}] (Right Stack)",
                subtitle=f"Triple Split Layout  •  Left 50%: {t1.title}  •  Top-Right: {t2.title}  •  Bottom-Right: {t3.title}",
                category="TILE 3",
                target=t1.target,
                action=lambda items=list(resolved): WorkspaceSplitManager.instance().launch_split(
                    items, "main_left_stack_right", self._open_target
                ),
                score=1500,
            ))
            split_items.append(SearchItem(
                id=f"split_3_stack_main_{t1.title}_{t2.title}_{t3.title}",
                title=f"[{t1.title} / {t2.title}] (Left Stack)  +  ◨ {t3.title} (Right Half)",
                subtitle=f"Stack + Master Layout  •  Top-Left: {t1.title}  •  Bottom-Left: {t2.title}  •  Right 50%: {t3.title}",
                category="TILE 3",
                target=t3.target,
                action=lambda items=list(resolved): WorkspaceSplitManager.instance().launch_split(
                    items, "stack_left_main_right", self._open_target
                ),
                score=1480,
            ))
            split_items.append(SearchItem(
                id=f"split_3_cols_{t1.title}_{t2.title}_{t3.title}",
                title=f"▯ {t1.title}   |   ▯ {t2.title}   |   ▯ {t3.title}",
                subtitle=f"Triple Columns (3 Equal Columns)  •  Left: {t1.title}  •  Center: {t2.title}  •  Right: {t3.title}",
                category="TILE 3",
                target=t1.target,
                action=lambda items=list(resolved): WorkspaceSplitManager.instance().launch_split(
                    items, "columns_3", self._open_target
                ),
                score=1460,
            ))

        elif count == 4:
            t1, t2, t3, t4 = resolved[0], resolved[1], resolved[2], resolved[3]
            split_items.append(SearchItem(
                id=f"split_4_grid_{t1.title}_{t2.title}_{t3.title}_{t4.title}",
                title=f"⊞ 2×2 Grid:  {t1.title}  |  {t2.title}  |  {t3.title}  |  {t4.title}",
                subtitle=f"Quad Split Grid  •  TL: {t1.title}  •  TR: {t2.title}  •  BL: {t3.title}  •  BR: {t4.title}",
                category="GRID 4",
                target=t1.target,
                action=lambda items=list(resolved): WorkspaceSplitManager.instance().launch_split(
                    items, "grid_2x2", self._open_target
                ),
                score=1500,
            ))
            split_items.append(SearchItem(
                id=f"split_4_cols_{t1.title}_{t2.title}_{t3.title}_{t4.title}",
                title=f"▯▯▯▯ 4 Columns:  {t1.title}  |  {t2.title}  |  {t3.title}  |  {t4.title}",
                subtitle=f"Quad Side-by-Side Columns (25% each)  •  1: {t1.title}  •  2: {t2.title}  •  3: {t3.title}  •  4: {t4.title}",
                category="GRID 4",
                target=t1.target,
                action=lambda items=list(resolved): WorkspaceSplitManager.instance().launch_split(
                    items, "columns_4", self._open_target
                ),
                score=1480,
            ))

        return split_items[:max_results]


    def search(
        self,
        query: str,
        max_results: int = 8,
        include_windows_search: bool = False,
        cancel_event: Optional[threading.Event] = None,
    ) -> List[SearchItem]:
        q = query.strip()
        if not q or (cancel_event is not None and cancel_event.is_set()):
            return []

        results = []
        low_q = q.lower()

        # Check feature module toggles (defaulting to True)
        enable_clip = self.settings.get("enable_clipboard_history", True)
        enable_notes = self.settings.get("enable_quick_notes", True)
        enable_conv = self.settings.get("enable_unit_converter", True)
        enable_color = self.settings.get("enable_color_inspector", True)
        enable_clock = self.settings.get("enable_world_clock", True)
        enable_sys = self.settings.get("enable_system_commands", True)
        enable_web_shortcuts = self.settings.get("enable_web_shortcuts", True)
        enable_calc = self.settings.get("enable_calculator", True)
        enable_fallbacks = self.settings.get("enable_web_fallbacks", True)
        enable_messaging = self.settings.get("enable_quick_messaging", True)

        # ==========================================
        # 0. CHEATCODES & FAST SHORTCUTS
        # ==========================================
        if low_q in ("clp", "clip", "cb", "clipboard"):
            low_q = "clip:"

        if low_q in ("help", "?", "cheat", "cheatcodes", "commands"):
            cheatcodes = [
                ("Text John <msg>", "Quick Text Sending", "Send messages via WhatsApp Desktop or Web (e.g. Text John I'll be there)"),
                ("app1 and app2", "Multi-App Split Screen (2–4)", "Tile 2, 3, or 4 apps, websites, or files (e.g. edge and word)"),
                ("date?", "Current Date & Day Info", "View today's full date, day of year & week number"),
                ("day today", "Current Day of the Week", "Instant weekday status, relative day & calendar info"),
                ("cal", "Monthly Calendar & Grid", "Interactive monthly calendar, navigation & grid copy"),
                ("clp", "Clipboard History & Paste Buffer", "View copied text snippets & press Enter to paste"),
                ("note: <text>", "Quick Notes & Todos", "Store instant scratchpad notes or view saved items"),
                ("calc: <expr>", "Calculator & Math", "Evaluate math equations (e.g. calc: 120*1.18 or 2^10)"),
                ("convert: <val>", "Unit & Currency Converter", "Convert units (e.g. 50 usd to eur, 100 km to mi)"),
                ("time: <city>", "World Clock & Timers", "Check time in London, Tokyo, NYC or 'timer: 5m'"),
                ("color: <hex>", "Color Inspector & Picker", "Inspect #HEX or rgb() with luminance analysis"),
                ("sys: <action>", "System Power Controls", "Lock, sleep, shutdown, empty bin, or view IP"),
                ("rook", "Rook Power Shortcuts", "View and trigger Rook productivity hotkeys"),
                ("media", "Dynamic Island Music Controller", "Instant access to media controls & source switcher"),
                ("sett", "ODD Settings Dialog", "Configure themes, animations, gestures, and hotkeys")
            ]
            for code, title, desc in cheatcodes:
                results.append(SearchItem(
                    id=f"cheat_{code.split()[0]}",
                    title=f"{code:<14} {title}",
                    subtitle=desc,
                    category="CHEATCODE",
                    target=code,
                    action=lambda c=code.split()[0].rstrip(":"): None,
                    score=1000
                ))
            return results

        # ==========================================
        # 0.25 QUICK TEXT SENDING (Natural-Language Messaging: Text/Message/Send <Name> <Message>)
        # ==========================================
        if enable_messaging:
            from odd_messaging import MessageCommandParser, MessagingManager
            msg_mgr = MessagingManager.get_instance(self.settings)

            if low_q in (
                "messaging provider", "message provider", "text provider", "whatsapp provider",
                "use whatsapp desktop", "use whatsapp web", "messaging app", "preferred messaging"
            ):
                active_prov = msg_mgr.get_active_provider()
                for pid, pname in msg_mgr.list_providers():
                    is_active = (pid == active_prov.provider_id)
                    results.append(SearchItem(
                        id=f"msg_prov_{pid}",
                        title=f"Messaging App: {pname}" + (" (Selected)" if is_active else ""),
                        subtitle="Press Enter to set as your preferred messaging provider in ODD",
                        category="MESSAGE",
                        target=pid,
                        action=lambda p=pid: msg_mgr.set_preferred_provider_id(p),
                        score=2000 if is_active else 1950,
                    ))
                return results[:max_results]

            parsed_msg = MessageCommandParser.parse(q)
            if parsed_msg is not None:
                prov = msg_mgr.get_active_provider()
                if parsed_msg.provider_override in ("whatsapp_desktop", "whatsapp_web"):
                    prov = msg_mgr._providers.get(parsed_msg.provider_override, prov)

                results.append(SearchItem(
                    id="msg_send_now",
                    title=f"Send to {parsed_msg.recipient}: \"{parsed_msg.message}\"",
                    subtitle=f"{prov.display_name} • Opens chat, types message & sends automatically",
                    category="MESSAGE",
                    target=parsed_msg.recipient,
                    action=lambda cmd=parsed_msg: msg_mgr.execute_command(cmd),
                    score=2800,
                ))

                # Also allow one-stroke sending via the alternate WhatsApp provider if needed
                alt_id = "whatsapp_web" if prov.provider_id == "whatsapp_desktop" else "whatsapp_desktop"
                alt_prov = msg_mgr._providers.get(alt_id)
                if alt_prov is not None:
                    from odd_messaging import ParsedMessageCommand
                    alt_cmd = ParsedMessageCommand(
                        action="send_message",
                        recipient=parsed_msg.recipient,
                        message=parsed_msg.message,
                        raw_query=parsed_msg.raw_query,
                        provider_override=alt_id,
                    )
                    results.append(SearchItem(
                        id=f"msg_send_alt_{alt_id}",
                        title=f"Send via {alt_prov.display_name} to {parsed_msg.recipient}",
                        subtitle=f"Message: \"{parsed_msg.message}\" • Switch & send with {alt_prov.display_name}",
                        category="MESSAGE",
                        target=parsed_msg.recipient,
                        action=lambda cmd=alt_cmd, p=alt_id: (msg_mgr.set_preferred_provider_id(p), msg_mgr.execute_command(cmd)),
                        score=2400,
                    ))
                return results[:max_results]

            partial_msg = MessageCommandParser.parse_partial(q)
            if partial_msg is not None:
                prov = msg_mgr.get_active_provider()
                rec_hint = partial_msg.get("recipient", "").strip()
                if rec_hint:
                    results.append(SearchItem(
                        id="msg_typing_preview",
                        title=f"Message {rec_hint} — [Keep typing your message...]",
                        subtitle=f"Example: Text {rec_hint} I'll be there in 10 minutes • Provider: {prov.display_name}",
                        category="MESSAGE",
                        target=q,
                        action=None,
                        score=2600,
                    ))
                else:
                    results.append(SearchItem(
                        id="msg_typing_preview",
                        title="Quick Text — Type recipient and message (e.g. Text John I'll be there in 10 minutes)",
                        subtitle=f"Preferred provider: {prov.display_name} • Sends automatically when ready",
                        category="MESSAGE",
                        target=q,
                        action=None,
                        score=2600,
                    ))
                return results[:max_results]

        # ==========================================
        # 0.5 MULTI-APPLICATION / FILE / WEB SPLIT LAUNCHER (2, 3, or 4 targets)
        # ==========================================
        split_matches = self._search_multi_split(q, max_results=max_results)
        if cancel_event is not None and cancel_event.is_set():
            return []
        if split_matches:
            return split_matches

        # ==========================================
        # 0.45 SEE ME / LIVE CAMERA MIRROR OVERLAY
        # ==========================================
        if low_q in ("see me", "seeme", "mirror", "face", "camera mirror", "look at me", "webcam mirror") or low_q.startswith("see me"):
            def _launch_see_me():
                try:
                    import odd_camera
                    odd_camera.SeeMeOverlay.instance().open_overlay()
                except Exception as e:
                    print(f"Error launching See Me overlay: {e}")

            results.append(SearchItem(
                id="cmd_see_me",
                title="See Me (Live Camera Mirror)",
                subtitle="Open landscape live camera mirror to see your face • Press Enter",
                category="CAMERA",
                target="see_me",
                action=_launch_see_me,
                score=3500
            ))
            return results

        # ==========================================
        # 0.46 SPLIT VIEW ARRANGE / MULTI-WINDOW TILING
        # ==========================================
        if low_q in (
            "split", "split view", "splitview", "split screen", "arrange", "arrange windows",
            "split arrange", "split view arrange", "multi window", "tile windows", "tile", "snap", "snap windows"
        ) or low_q.startswith("arrange") or low_q.startswith("split view") or low_q.startswith("split arrange") or low_q.startswith("tile"):
            results.append(SearchItem(
                id="cmd_split_arrange_auto",
                title="Split & Arrange Active Windows (Default Windows Multi-Window)",
                subtitle="Tile 2, 3, or 4 active application windows using native Windows Snap multi-window layout • Press Enter",
                category="SPLIT",
                target="split_arrange_auto",
                action=lambda: WorkspaceSplitManager.arrange_active_windows(0, "auto"),
                score=3500
            ))
            results.append(SearchItem(
                id="cmd_split_arrange_dual",
                title="Split & Arrange 2 Windows (50% / 50%)",
                subtitle="Tile top 2 active windows side-by-side with default Windows multi-window arrangement (Left 50% | Right 50%)",
                category="SPLIT",
                target="split_arrange_2",
                action=lambda: WorkspaceSplitManager.arrange_active_windows(2, "left_right"),
                score=3450
            ))
            results.append(SearchItem(
                id="cmd_split_arrange_triple",
                title="Split & Arrange 3 Windows (Master + Stack)",
                subtitle="Tile top 3 active windows with default Windows 3-way layout (Left 50% + Right Stack Top/Bottom)",
                category="SPLIT",
                target="split_arrange_3",
                action=lambda: WorkspaceSplitManager.arrange_active_windows(3, "main_left_stack_right"),
                score=3400
            ))
            results.append(SearchItem(
                id="cmd_split_arrange_quad",
                title="Split & Arrange 4 Windows (2×2 Grid)",
                subtitle="Tile top 4 active windows with default Windows 2×2 quadrant grid layout (25% each)",
                category="SPLIT",
                target="split_arrange_4",
                action=lambda: WorkspaceSplitManager.arrange_active_windows(4, "grid_2x2"),
                score=3350
            ))
            results.append(SearchItem(
                id="cmd_split_arrange_cols",
                title="Split & Arrange 3 Columns (1/3 Each)",
                subtitle="Tile top 3 active windows into 3 equal vertical columns across your monitor",
                category="SPLIT",
                target="split_arrange_cols",
                action=lambda: WorkspaceSplitManager.arrange_active_windows(3, "columns_3"),
                score=3300
            ))
            results.append(SearchItem(
                id="cmd_split_arrange_tb",
                title="Split & Arrange Vertically (Top / Bottom)",
                subtitle="Tile top 2 active windows into top and bottom halves",
                category="SPLIT",
                target="split_arrange_tb",
                action=lambda: WorkspaceSplitManager.arrange_active_windows(2, "top_bottom"),
                score=3250
            ))
            return results

        if low_q in ("rook", "shortcuts", "hotkeys"):
            rook_shortcuts = [
                ("Win+Alt+R", "Rook Command Hub", "Open centralized shortcut hub and action launcher"),
                ("Win+Alt+S", "Snap Window Layouts", "Tile and arrange active application windows"),
                ("Win+Alt+T", "Always on Top", "Pin active window above all other windows"),
                ("Win+Alt+M", "Global Mic Mute", "Instantly mute/unmute system microphone"),
                ("Win+Alt+C", "Color Dropper", "Sample any screen pixel color to clipboard"),
                ("Win+Alt+E", "Unicode & Symbols", "Insert special symbols and typography characters")
            ]
            for hk, name, desc in rook_shortcuts:
                results.append(SearchItem(
                    id=f"rook_{name.lower().replace(' ', '_')}",
                    title=f"{hk} — {name}",
                    subtitle=desc,
                    category="ROOK",
                    target=hk,
                    action=lambda k=hk: copy_to_clipboard(k),
                    score=1000
                ))
            return results

        # ==========================================
        # 0.5 SYSTEM STATS, TIMER & NETWORK TOOLS
        # ==========================================
        if low_q in ("cpu", "ram", "specs", "memory", "usage", "resource", "resources", "sysinfo", "system info"):
            res_info = get_system_resource_info()
            cpu_val = res_info["cpu_pct"]
            ram_val = res_info["ram_pct"]
            ram_used = res_info["ram_used_gb"]
            ram_tot = res_info["ram_total_gb"]
            res_title = f"CPU: {cpu_val}%  •  RAM: {ram_val}% ({ram_used:.1f} / {ram_tot:.1f} GB)"
            results.append(SearchItem(
                id="cmd_system_stats",
                title=res_title,
                subtitle="Live system performance metrics • Press Enter to open Task Manager",
                category="SYSTEM",
                target="taskmgr.exe",
                action=lambda: subprocess.Popen("taskmgr.exe", shell=True),
                score=1200
            ))
            results.append(SearchItem(
                id="cmd_taskmgr",
                title="Open Windows Task Manager",
                subtitle="View detailed CPU, GPU, memory, and process breakdown",
                category="APP",
                target="taskmgr.exe",
                action=lambda: subprocess.Popen("taskmgr.exe", shell=True),
                score=1100
            ))
            return results

        # ==========================================
        # 0.6 QUICK SETTINGS & SCREENSHOT SHORTCUTS
        # ==========================================
        if low_q in ("qs", "quick", "quick settings", "quicksettings", "control center", "controls", "toggles"):
            def _open_qs():
                try:
                    from PySide6.QtWidgets import QApplication
                    for w in QApplication.topLevelWidgets():
                        if hasattr(w, 'toggle_quick_settings_panel'):
                            w.toggle_quick_settings_panel()
                            break
                except Exception:
                    pass
            results.append(SearchItem(
                id="cmd_quick_settings",
                title="Quick Settings & Controls",
                subtitle="Wi-Fi, Bluetooth, Audio, Brightness, Screenshot • Press Enter",
                category="SETTINGS",
                target="quick_settings",
                action=_open_qs,
                score=1400
            ))
            return results

        if low_q in ("snip", "snipping", "screenshot", "screen shot", "print screen", "printscreen", "prtscr", "capture"):
            def _open_snip():
                try:
                    os.startfile("ms-screenclip:")
                except Exception:
                    try:
                        subprocess.Popen(["snippingtool.exe", "/clip"])
                    except Exception:
                        pass
            results.append(SearchItem(
                id="cmd_screenshot",
                title="Take Screen Snip / Screenshot",
                subtitle="Launch Windows Snipping Tool (Win + Shift + S) • Press Enter",
                category="TOOL",
                target="ms-screenclip:",
                action=_open_snip,
                score=1400
            ))
            return results

        # COUNTDOWN TIMER, STOPWATCH & POMODORO (stopwatch, stopwatch 10m, timer 5m, timer 30s, pomodoro)
        is_timer_q = (
            low_q.startswith("timer") or low_q.startswith("timer:") or low_q.startswith("timer ") or
            low_q.startswith("stopwatch") or low_q.startswith("stopwatch:") or low_q.startswith("stopwatch ") or
            low_q.startswith("pomo") or low_q == "pomodoro"
        )
        if is_timer_q:
            # 1. Check if any stopwatch or timer is currently active (allow one-click stop)
            active_timers = get_active_island_timers()
            if active_timers:
                now_t = time.time()
                for tid, tinfo in active_timers.items():
                    t_type = tinfo.get("type", "timer")
                    lbl = tinfo.get("label", "Timer")
                    if t_type == "stopwatch":
                        elapsed = max(0, int(now_t - tinfo.get("start_time", now_t)))
                        time_str = f"{elapsed // 3600}:{((elapsed % 3600) // 60):02d}:{(elapsed % 60):02d}" if elapsed >= 3600 else f"{(elapsed // 60):02d}:{(elapsed % 60):02d}"
                        results.append(SearchItem(
                            id=f"cmd_stop_{tid}",
                            title=f"Stop Stopwatch (Running: {time_str})",
                            subtitle="Press Enter or Click to Stop and Reset the stopwatch • Clears Dynamic Island",
                            category="STOPWATCH",
                            target="stop",
                            action=lambda t=tid: stop_island_timer(t),
                            score=2600
                        ))
                    else:
                        rem = max(0, int(tinfo.get("end_time", now_t) - now_t))
                        time_str = f"{rem // 3600}:{((rem % 3600) // 60):02d}:{(rem % 60):02d}" if rem >= 3600 else f"{(rem // 60):02d}:{(rem % 60):02d}"
                        results.append(SearchItem(
                            id=f"cmd_stop_{tid}",
                            title=f"Stop Active {lbl} ({time_str} remaining)",
                            subtitle="Press Enter or Click to Stop and Cancel the timer • Clears Dynamic Island",
                            category="TIMER",
                            target="stop",
                            action=lambda t=tid: stop_island_timer(t),
                            score=2600
                        ))

            # Helper to parse complex timing strings like "1h 30m" or "45s"
            def _parse_custom_time(arg_str: str) -> int:
                matches = re.findall(r"(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)?", arg_str)
                if not matches:
                    return 0
                tot = 0
                for v_str, u_str in matches:
                    if not v_str:
                        continue
                    v = int(v_str)
                    u = (u_str or "m").lower()
                    if u.startswith("s"):
                        tot += v
                    elif u.startswith("h"):
                        tot += v * 3600
                    else:
                        tot += v * 60
                return tot

            t_arg = ""
            if " " in low_q:
                t_arg = low_q.split(" ", 1)[1].strip()
            elif ":" in low_q:
                t_arg = low_q.split(":", 1)[1].strip()

            is_sw_query = low_q.startswith("stopwatch")

            # 2. If user provided a specific custom duration (e.g. "stopwatch 15m" or "timer 45s")
            if t_arg:
                dur_sec = _parse_custom_time(t_arg)
                if dur_sec > 0:
                    hrs = dur_sec // 3600
                    mins = (dur_sec % 3600) // 60
                    secs = dur_sec % 60
                    dur_parts = []
                    if hrs: dur_parts.append(f"{hrs}h")
                    if mins: dur_parts.append(f"{mins}m")
                    if secs: dur_parts.append(f"{secs}s")
                    dur_str = " ".join(dur_parts)
                    title_prefix = "Stopwatch Countdown" if is_sw_query else "Timer"
                    results.append(SearchItem(
                        id="cmd_timer_custom_start",
                        title=f"Start {title_prefix} — {dur_str} countdown",
                        subtitle="Ticks live in Dynamic Island with alert when finished • Click to stop anytime",
                        category="STOPWATCH" if is_sw_query else "TIMER",
                        target=str(dur_sec),
                        action=lambda l=f"{title_prefix} ({dur_str})", d=dur_sec: trigger_island_timer(l, d),
                        score=2200
                    ))
                    return results

            # 3. If query is just "stopwatch" without duration
            if is_sw_query and not t_arg:
                # Count-Up Stopwatch (Real stopwatch starting at 00:00)
                results.append(SearchItem(
                    id="cmd_stopwatch_countup",
                    title="Start Stopwatch (Count Up: 00:00)",
                    subtitle="Live ticking count-up stopwatch in Dynamic Island • Click HUD or type stopwatch to stop",
                    category="STOPWATCH",
                    target="countup",
                    action=lambda: start_island_stopwatch("Stopwatch"),
                    score=2400
                ))

                # Custom Timing Presets for Stopwatch
                presets = [
                    (5 * 60, "5 minutes"),
                    (10 * 60, "10 minutes"),
                    (15 * 60, "15 minutes"),
                    (25 * 60, "25 minutes (Pomodoro)"),
                    (30 * 60, "30 minutes"),
                    (60 * 60, "1 hour"),
                ]
                for p_sec, p_label in presets:
                    results.append(SearchItem(
                        id=f"cmd_sw_preset_{p_sec}",
                        title=f"Custom Timing: {p_label}",
                        subtitle=f"Start {p_label} stopwatch countdown • Press Enter to start",
                        category="STOPWATCH",
                        target=str(p_sec),
                        action=lambda sec=p_sec, lab=p_label: trigger_island_timer(f"Stopwatch ({lab})", sec),
                        score=1800 - (p_sec // 60)
                    ))
                return results

            # 4. If query is "pomo" or "pomodoro"
            if low_q in ("pomo", "pomodoro"):
                results.append(SearchItem(
                    id="cmd_pomodoro_start",
                    title="Start Pomodoro Focus Timer — 25 minutes",
                    subtitle="25-minute productivity block in Dynamic Island • Click HUD or type timer to stop",
                    category="TIMER",
                    target="1500",
                    action=lambda: trigger_island_timer("Pomodoro", 25 * 60),
                    score=2400
                ))
                return results

            # 5. Default "timer" query with presets
            results.append(SearchItem(
                id="cmd_timer_default",
                title="Start Timer — 5m countdown",
                subtitle="Ticks live in Dynamic Island • Type custom time like 'timer 12m' or 'timer 30s'",
                category="TIMER",
                target="300",
                action=lambda: trigger_island_timer("Timer (5m)", 5 * 60),
                score=2300
            ))
            for p_sec, p_label in [(60, "1 minute"), (600, "10 minutes"), (900, "15 minutes"), (1500, "25 minutes"), (3600, "1 hour")]:
                results.append(SearchItem(
                    id=f"cmd_timer_preset_{p_sec}",
                    title=f"Start Timer: {p_label}",
                    subtitle=f"Countdown for {p_label} in Dynamic Island • Click HUD or type timer to stop",
                    category="TIMER",
                    target=str(p_sec),
                    action=lambda sec=p_sec, lab=p_label: trigger_island_timer(f"Timer ({lab})", sec),
                    score=1700 - (p_sec // 60)
                ))
            return results

        # NETWORK IP & CONNECTIVITY
        if low_q in ("ip", "my ip", "myip", "ipconfig", "network", "local ip", "ping"):
            net_info = get_network_info()
            local_ip = net_info["ip"]
            hostname = net_info["hostname"]
            results.append(SearchItem(
                id="cmd_network_ip",
                title=f"Local IP: {local_ip}",
                subtitle=f"Host: {hostname} • Press Enter to copy IP address",
                category="NETWORK",
                target=local_ip,
                action=lambda ip=local_ip: copy_to_clipboard(ip),
                score=1200
            ))
            results.append(SearchItem(
                id="cmd_network_status",
                title="Open Network & Internet Settings",
                subtitle="Manage Wi-Fi, Ethernet, VPN and adapter properties",
                category="SETTINGS",
                target="ms-settings:network",
                action=lambda: webbrowser.open("ms-settings:network"),
                score=1000
            ))
            return results


        if low_q in ("sett", "settings", "conf", "config", "preferences"):
            results.append(SearchItem(
                id="cmd_settings",
                title="Open ODD Settings",
                subtitle="Customize themes, notch animations, deliberate hover, and modules",
                category="SETTINGS",
                target="settings",
                action=lambda: None,
                score=1000
            ))
            return results

        if low_q in ("media", "music", "player", "spotify"):
            results.append(SearchItem(
                id="cmd_media",
                title="Music & Media Player Controller",
                subtitle="Expand Dynamic Island media bar with playback & source controls",
                category="MEDIA",
                target="media",
                action=lambda: None,
                score=1000
            ))
            return results

        # ==========================================
        # 1. CLIPBOARD HISTORY (clp, clip:, cb:)
        # ==========================================
        is_clip_query = (
            low_q.startswith("clip:") or low_q.startswith("clip ") or low_q == "clip" or
            low_q.startswith("clp:") or low_q.startswith("clp ") or low_q == "clp" or
            low_q.startswith("cb:") or low_q.startswith("cb ") or low_q == "cb" or
            low_q == "clipboard" or low_q.startswith("clipboard:")
        )

        if enable_clip and is_clip_query:
            if ":" in q:
                term = q.split(":", 1)[1].strip().lower()
            elif " " in q:
                term = q.split(" ", 1)[1].strip().lower()
            else:
                term = ""
            if term == "clear":
                results.append(SearchItem(
                    id="clip_clear",
                    title="Clear Clipboard History",
                    subtitle="Wipe all saved clipboard snippets from disk",
                    category="CLIPBOARD",
                    target="clear",
                    action=lambda: clipboard_mgr.clear(),
                    score=1000
                ))
                return results

            history = clipboard_mgr.history
            if not history:
                results.append(SearchItem(
                    id="clip_empty",
                    title="Clipboard History is Empty",
                    subtitle="Copied text, links and files will automatically appear here",
                    category="CLIPBOARD",
                    target="",
                    score=1000
                ))
                return results

            # Sort pinned items first
            sorted_history = sorted(enumerate(history), key=lambda x: (not x[1].get("pinned", False), x[0]))

            matched = []
            for idx, item in sorted_history:
                txt = item.get("text", "")
                ts = item.get("timestamp", "")
                ch_cnt = item.get("chars", len(txt))
                is_pinned = item.get("pinned", False)
                is_link = item.get("is_link", False)
                is_files = item.get("is_files", False)

                if not term or term in txt.lower():
                    snippet = txt.replace("\n", " ").replace("\r", "")
                    if len(snippet) > 65:
                        snippet = snippet[:62] + "..."
                    
                    badges = []
                    if is_pinned:
                        badges.append("Pinned")
                    if is_link:
                        badges.append("Link")
                    if is_files:
                        badges.append("File")
                    badge_str = f"[{' • '.join(badges)}] " if badges else ""

                    matched.append(SearchItem(
                        id=f"clip_{idx}",
                        title=f"{badge_str}{snippet}",
                        subtitle=f"{'Pinned • ' if is_pinned else ''}Copied at {ts} • {ch_cnt} chars • Enter to Paste directly",
                        category="CLIPBOARD",
                        target=txt,
                        action=lambda t=txt: paste_to_active_window(t),
                        score=1000 - idx + (500 if is_pinned else 0)
                    ))
            if matched:
                return matched[:max_results]
            else:
                results.append(SearchItem(
                    id="clip_none",
                    title=f"No clipboard items matching \"{term}\"",
                    subtitle="Try another search term or type clp: clear",
                    category="CLIPBOARD",
                    target="",
                    score=1000
                ))
                return results

        # ==========================================
        # 1.45. SCREEN INTELLIGENCE & OCR (ocr:, snip:, scan:)
        # ==========================================
        low_q = q.strip().lower()
        if low_q.startswith(("ocr:", "ocr ", "snip:", "snip ", "scan:")) or low_q in ("ocr", "snip", "extract text", "screen intelligence"):
            def _trigger_screen_ocr():
                try:
                    from PySide6.QtWidgets import QApplication
                    for w in QApplication.topLevelWidgets():
                        if hasattr(w, "start_screen_intelligence"):
                            w.start_screen_intelligence()
                            return
                        elif hasattr(w, "start_google_lens_search"):
                            w.start_google_lens_search()
                            return
                except Exception:
                    pass

            results.append(SearchItem(
                id="screen_intel_ocr",
                title="Screen Intelligence: Extract Text (OCR)",
                subtitle="Select an on-screen region to extract text, copy, or translate • Press Enter",
                category="SCREEN INTELLIGENCE",
                target="",
                action=_trigger_screen_ocr,
                score=1000
            ))
            results.append(SearchItem(
                id="screen_intel_lens",
                title="Screen Intelligence: Visual Search (Google Lens)",
                subtitle="Select an on-screen region to reverse-search with Google Lens • Press Enter",
                category="SCREEN INTELLIGENCE",
                target="",
                action=_trigger_screen_ocr,
                score=990
            ))
            return results

        # ==========================================
        # 1.5. NATURAL-LANGUAGE DYNAMIC ISLAND REMINDERS (remind me..., rem:, reminder:)
        # ==========================================
        low_q = q.strip().lower()
        is_rem_query = (
            low_q.startswith("remind") or low_q.startswith("rem:") or low_q.startswith("rem ") or
            low_q.startswith("reminder:") or low_q.startswith("reminder ") or
            (low_q.startswith("r:") and len(low_q) > 2) or
            ("remind" in low_q and (" at " in low_q or " in " in low_q or " tomorrow" in low_q or " to " in low_q or " every " in low_q))
        )
        if is_rem_query:
            from odd_reminder import ReminderParser, ReminderManager
            rem_mgr = ReminderManager.get_instance(self.settings)

            # Handle rem: clear, rem: demo
            if "demo" in low_q:
                results.append(SearchItem(
                    id="rem_demo",
                    title="Demo: Reminder Notification in Dynamic Island",
                    subtitle='Trigger interactive reminder: "Submit assignment" (Press Enter to test)',
                    category="REMINDER",
                    target="demo",
                    action=lambda: rem_mgr.trigger_demo_reminder("Submit assignment", "It's time to get this done."),
                    score=1000
                ))
                return results

            if low_q in ("rem: clear", "remind: clear", "rem clear", "reminder: clear"):
                results.append(SearchItem(
                    id="rem_clear_all",
                    title="Clear All Scheduled Reminders",
                    subtitle="Delete all pending and snoozed reminders from Dynamic Island",
                    category="REMINDER",
                    target="clear",
                    action=lambda: rem_mgr.clear_all(),
                    score=1000
                ))
                return results

            parsed = ReminderParser.parse(q)
            if parsed and parsed.get("title"):
                title = parsed["title"]
                due_ts = parsed["due_timestamp"]
                rec = parsed.get("recurrence")
                ctx_type = parsed.get("context_type")
                ctx_tgt = parsed.get("context_target")

                dt = datetime.datetime.fromtimestamp(due_ts)
                now = datetime.datetime.now()
                time_str = dt.strftime("%I:%M %p").lstrip("0")
                if dt.date() == now.date():
                    due_desc = f"Today at {time_str}"
                elif dt.date() == (now + datetime.timedelta(days=1)).date():
                    due_desc = f"Tomorrow at {time_str}"
                else:
                    due_desc = f"{dt.strftime('%b %d')} at {time_str}"

                sub_desc = f"Due {due_desc}"
                if rec:
                    sub_desc += f" • Repeats {rec.upper()}"
                if ctx_tgt:
                    sub_desc += f" • Context: {Path(ctx_tgt).name if ctx_type == 'file' else ctx_tgt}"
                sub_desc += " • Delivered inside Dynamic Island (Press Enter to Schedule)"

                def _schedule_action(t=title, ts=due_ts, r=rec, ct=ctx_type, cg=ctx_tgt):
                    rem_mgr.add_reminder(t, ts, recurrence=r, context_type=ct, context_target=cg)
                    try:
                        import odd_sound
                        odd_sound.play_preview(0.75)
                    except Exception:
                        pass

                results.append(SearchItem(
                    id="rem_natural_create",
                    title=f'Remind: "{title}"',
                    subtitle=sub_desc,
                    category="REMINDER",
                    target=title,
                    action=_schedule_action,
                    score=1000
                ))

                # Alternative time presets if no explicit time was specified
                if not parsed.get("has_time"):
                    for label, delta_min in [("In 15 minutes", 15), ("In 1 hour", 60), ("Tonight at 8:00 PM", None), ("Tomorrow at 9:00 AM", None)]:
                        if delta_min is not None:
                            alt_ts = (now + datetime.timedelta(minutes=delta_min)).timestamp()
                            alt_sub = f"Due in {delta_min}m"
                        elif "Tonight" in label:
                            tonight_dt = datetime.datetime(now.year, now.month, now.day, 20, 0)
                            if tonight_dt <= now:
                                tonight_dt += datetime.timedelta(days=1)
                            alt_ts = tonight_dt.timestamp()
                            alt_sub = "Due Tonight at 8:00 PM"
                        else:
                            tom_dt = (now + datetime.timedelta(days=1)).replace(hour=9, minute=0, second=0)
                            alt_ts = tom_dt.timestamp()
                            alt_sub = "Due Tomorrow at 9:00 AM"

                        results.append(SearchItem(
                            id=f"rem_alt_{label}",
                            title=f'Remind {label}: "{title}"',
                            subtitle=f"{alt_sub} • Press Enter to schedule",
                            category="REMINDER",
                            target=title,
                            action=lambda t=title, ts=alt_ts, r=rec: rem_mgr.add_reminder(t, ts, recurrence=r),
                            score=950
                        ))

            # List active upcoming reminders
            upcoming = rem_mgr.get_upcoming_reminders()
            for idx, item in enumerate(upcoming[:4]):
                results.append(SearchItem(
                    id=f"rem_item_{item.id}",
                    title=f"{item.title} ({item.get_due_formatted()})",
                    subtitle=f"{item.note} (Enter to mark Done, or type rem: clear to wipe)",
                    category="REMINDER",
                    target=item.title,
                    action=lambda rid=item.id: rem_mgr.complete_reminder(rid),
                    score=900 - idx
                ))

            if results:
                return results[:max_results]

        # ==========================================
        # 2. NOTES & TODOS (note:, notes:, todo:)
        # ==========================================
        is_note_query = (
            low_q.startswith("note:") or low_q.startswith("note ") or low_q == "note" or
            low_q.startswith("notes:") or low_q.startswith("notes ") or low_q == "notes" or
            low_q.startswith("todo:") or low_q.startswith("todo ") or low_q == "todo"
        )
        if enable_notes and is_note_query:
            if ":" in q:
                term = q.split(":", 1)[1].strip()
            elif " " in q:
                term = q.split(" ", 1)[1].strip()
            else:
                term = ""

            low_term = term.lower()

            # Handle note: del, note: clear, note: wipe commands
            if low_term in ("del", "del all", "delete", "delete all", "clear", "wipe"):
                existing_notes = NotesManager.load_notes()
                if not existing_notes:
                    results.append(SearchItem(
                        id="note_empty_del",
                        title="No Notes to Delete",
                        subtitle="Your notes list is already empty",
                        category="NOTE",
                        target="",
                        score=1000
                    ))
                    return results

                results.append(SearchItem(
                    id="note_clear_all",
                    title="Clear All Notes & Tasks",
                    subtitle=f"Permanently delete all {len(existing_notes)} saved notes",
                    category="NOTE",
                    target="clear",
                    action=lambda: NotesManager.clear_notes(),
                    score=1000
                ))
                for idx, n in enumerate(existing_notes):
                    n_txt = n.get("text", "")
                    n_id = n.get("id", "")
                    results.append(SearchItem(
                        id=f"note_del_{n_id}",
                        title=f"Delete: \"{n_txt}\"",
                        subtitle="Press Enter to remove this note",
                        category="NOTE",
                        target=n_id,
                        action=lambda nid=n_id: NotesManager.delete_note(nid),
                        score=900 - idx
                    ))
                return results[:max_results]

            # Handle note: del <keyword>
            if low_term.startswith("del ") or low_term.startswith("delete "):
                del_keyword = term.split(" ", 1)[1].strip().lower()
                existing_notes = NotesManager.load_notes()
                matched_del = []
                for idx, n in enumerate(existing_notes):
                    n_txt = n.get("text", "")
                    n_id = n.get("id", "")
                    if del_keyword in n_txt.lower():
                        matched_del.append(SearchItem(
                            id=f"note_del_{n_id}",
                            title=f"Delete Note: \"{n_txt}\"",
                            subtitle="Press Enter to remove this note",
                            category="NOTE",
                            target=n_id,
                            action=lambda nid=n_id: NotesManager.delete_note(nid),
                            score=1000 - idx
                        ))
                if matched_del:
                    return matched_del[:max_results]
                else:
                    results.append(SearchItem(
                        id="note_del_none",
                        title=f"No notes matching \"{del_keyword}\" to delete",
                        subtitle="Type note: del to view all deletable notes",
                        category="NOTE",
                        target="",
                        score=1000
                    ))
                    return results

            # Add new note option
            if term:
                results.append(SearchItem(
                    id="note_create",
                    title=f"Save Note: \"{term}\"",
                    subtitle="Store quick note / todo in ODD scratchpad (delete with note: del)",
                    category="NOTE",
                    target=term,
                    action=lambda t=term: NotesManager.add_note(t),
                    score=1000
                ))

            # Also show existing matching notes
            existing_notes = NotesManager.load_notes()
            for idx, n in enumerate(existing_notes):
                n_txt = n.get("text", "")
                n_id = n.get("id", "")
                n_date = n.get("date", "")
                if not term or term.lower() in n_txt.lower():
                    results.append(SearchItem(
                        id=f"note_item_{n_id}",
                        title=n_txt,
                        subtitle=f"Created {n_date} (Press Enter to copy, or note: del to delete)",
                        category="NOTE",
                        target=n_txt,
                        action=lambda t=n_txt: copy_to_clipboard(t),
                        score=950 - idx
                    ))
            if results:
                return results[:max_results]
            else:
                results.append(SearchItem(
                    id="note_empty",
                    title="No Notes Saved Yet",
                    subtitle="Type note: <your text> to instantly save a note or task",
                    category="NOTE",
                    target="",
                    score=1000
                ))
                return results

        # ==========================================
        # 2.5. DOWNLOADS & LIVE SYSTEM ACTIVITIES (down:, act:)
        # ==========================================
        is_dl_query = (
            low_q.startswith("down:") or low_q.startswith("down ") or low_q == "down" or
            low_q.startswith("downloads:") or low_q.startswith("act:") or low_q.startswith("act ") or
            low_q == "act" or low_q.startswith("activity:")
        )
        if is_dl_query:
            from odd_island import ActivityManager
            act_mgr = ActivityManager.get_instance(self.settings)
            
            term = ""
            if ":" in q:
                term = q.split(":", 1)[1].strip()
            elif " " in q:
                term = q.split(" ", 1)[1].strip()
            low_term = term.lower()

            # Handle quick simulations / demos
            if "demo blender" in low_term or "demo install" in low_term or ("blender" in low_term and "demo" in low_term):
                results.append(SearchItem(
                    id="act_demo_blender",
                    title="Demo: Installing Blender — 72%",
                    subtitle="Simulate live temporary activity in the Dynamic Island with real-time progression",
                    category="ACTIVITY",
                    target="demo_blender",
                    action=lambda: act_mgr.demo_install_blender(),
                    score=1000
                ))
                return results

            if "demo multi" in low_term or "demo download" in low_term or "demo down" in low_term:
                results.append(SearchItem(
                    id="act_demo_multi",
                    title="Demo: Multiple Downloads Merge into One Progress Ring",
                    subtitle="Simulate 2 active downloads merging on notch and expanding on hover",
                    category="DOWNLOAD",
                    target="demo_multi",
                    action=lambda: act_mgr.demo_multi_downloads(),
                    score=1000
                ))
                return results

            if low_term in ("clear", "wipe", "del", "clean"):
                results.append(SearchItem(
                    id="act_clear_history",
                    title="Clear Activity and Download History",
                    subtitle="Remove all remembered items from the Dynamic Island drawer",
                    category="ACTIVITY",
                    target="clear",
                    action=lambda: act_mgr.clear_history(),
                    score=1000
                ))
                return results

            # List active downloads/activities
            state = act_mgr.get_merged_state()
            active_items = state.get("active_items", [])
            remembered_items = state.get("remembered_items", [])

            # Quick action: Open Downloads folder
            results.append(SearchItem(
                id="act_open_folder",
                title="Open Downloads Folder",
                subtitle=str(Path.home() / "Downloads"),
                category="DOWNLOAD",
                target=str(Path.home() / "Downloads"),
                action=lambda: os.startfile(str(Path.home() / "Downloads")),
                score=1000
            ))

            # Demo triggers
            results.append(SearchItem(
                id="act_demo_blender_opt",
                title="Simulate: Installing Blender — 72%",
                subtitle="Test the Island's temporary activity memory with real-time progression",
                category="ACTIVITY",
                target="demo",
                action=lambda: act_mgr.demo_install_blender(),
                score=990
            ))

            results.append(SearchItem(
                id="act_demo_multi_opt",
                title="Simulate: Merged Downloads Progress Ring",
                subtitle="Test multiple simultaneous downloads merging into one progress ring",
                category="DOWNLOAD",
                target="demo",
                action=lambda: act_mgr.demo_multi_downloads(),
                score=980
            ))

            for idx, item in enumerate(active_items):
                t_path = getattr(item, 'target_path', '')
                act_title = getattr(item, 'title', '')
                act_prog = int(round(getattr(item, 'progress', 0.0)))
                act_sub = getattr(item, 'subtitle', '')
                results.append(SearchItem(
                    id=f"act_live_{idx}",
                    title=f"{act_title} — {act_prog}%",
                    subtitle=f"{act_sub} (Active in Dynamic Island)",
                    category="ACTIVITY",
                    target=t_path or act_title,
                    action=(lambda p=t_path: os.startfile(p)) if t_path and os.path.exists(t_path) else None,
                    score=950 - idx
                ))

            for idx, item in enumerate(remembered_items):
                t_path = getattr(item, 'target_path', '')
                act_title = getattr(item, 'title', '')
                act_sub = getattr(item, 'subtitle', 'Completed')
                results.append(SearchItem(
                    id=f"act_rem_{idx}",
                    title=f"{act_title}",
                    subtitle=f"{act_sub} (Remembered activity • Enter to open file)",
                    category="ACTIVITY",
                    target=t_path or act_title,
                    action=(lambda p=t_path: os.startfile(p)) if t_path and os.path.exists(t_path) else (lambda: os.startfile(str(Path.home() / "Downloads"))),
                    score=850 - idx
                ))

            return results[:max_results]

        # ==========================================
        # 3. UNIT & CURRENCY CONVERTER
        # ==========================================
        if enable_conv:
            conv_res = parse_unit_conversion(q)
            if conv_res:
                res_val, desc = conv_res
                results.append(SearchItem(
                    id="conv_result",
                    title=f"= {res_val}",
                    subtitle=f"{desc} (Press Enter to copy result)",
                    category="CONVERT",
                    target=res_val,
                    action=lambda r=res_val: copy_to_clipboard(r),
                    score=1000
                ))
                return results[:max_results]

        # ==========================================
        # 4. COLOR INSPECTOR & PALETTE (color: or #HEX or rgb)
        # ==========================================
        if enable_color:
            color_match = re.match(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", q.strip())
            rgb_match = re.match(r"^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$", q.strip().lower())
            if low_q.startswith("color:") or color_match or rgb_match:
                hex_val = None
                if color_match:
                    raw_h = color_match.group(1)
                    hex_val = f"#{raw_h}" if len(raw_h) == 6 else f"#{raw_h[0]*2}{raw_h[1]*2}{raw_h[2]*2}"
                elif rgb_match:
                    r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))
                    hex_val = f"#{r:02X}{g:02X}{b:02X}"
                elif low_q.startswith("color:"):
                    c_term = q[6:].strip()
                    m_sub = re.match(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", c_term)
                    if m_sub:
                        raw_h = m_sub.group(1)
                        hex_val = f"#{raw_h}" if len(raw_h) == 6 else f"#{raw_h[0]*2}{raw_h[1]*2}{raw_h[2]*2}"

                if hex_val:
                    try:
                        r = int(hex_val[1:3], 16)
                        g = int(hex_val[3:5], 16)
                        b = int(hex_val[5:7], 16)
                        lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
                        lum_str = "Light" if lum > 0.5 else "Dark"
                        rgb_str = f"rgb({r}, {g}, {b})"
                        results.append(SearchItem(
                            id="color_inspector",
                            title=f"Color {hex_val.upper()} • {rgb_str}",
                            subtitle=f"Luminance: {lum*100:.0f}% ({lum_str}) • Press Enter to copy HEX code",
                            category="COLOR",
                            target=hex_val.upper(),
                            action=lambda h=hex_val.upper(): copy_to_clipboard(h),
                            score=1000
                        ))
                        results.append(SearchItem(
                            id="color_rgb",
                            title=f"Copy RGB: {rgb_str}",
                            subtitle="Copy rgb(r, g, b) format to clipboard",
                            category="COLOR",
                            target=rgb_str,
                            action=lambda s=rgb_str: copy_to_clipboard(s),
                            score=950
                        ))
                        return results
                    except Exception:
                        pass

        # ==========================================
        # 5. CALENDAR, DATE, DAY & WORLD CLOCK
        # ==========================================
        if enable_clock:
            now_dt = datetime.datetime.now()
            today_day_num = now_dt.day
            curr_month = now_dt.month
            curr_year = now_dt.year
            day_name = now_dt.strftime("%A")
            month_name = now_dt.strftime("%B")
            formatted_date_full = now_dt.strftime("%A, %B %d, %Y")
            formatted_date_short = now_dt.strftime("%B %d, %Y")
            day_of_year = now_dt.timetuple().tm_yday
            is_leap = calendar.isleap(curr_year)
            total_days_year = 366 if is_leap else 365
            days_left_year = total_days_year - day_of_year
            iso_week = now_dt.isocalendar()[1]

            # ----------------------------------------------------
            # A. CALENDAR & MONTHLY CALENDAR (cal, calendar, monthly calendar, cal sept, cal 2026, etc.)
            # ----------------------------------------------------
            is_cal_query = (
                low_q in ("cal", "cal?", "calendar", "calendar?", "monthly calendar", "month calendar",
                          "month", "months", "show calendar", "open calendar", "cal today", "calendar today",
                          "calendar month", "month view", "view calendar") or
                low_q.startswith("cal ") or low_q.startswith("cal:") or
                low_q.startswith("calendar ") or low_q.startswith("calendar:") or
                low_q.startswith("month ") or low_q.startswith("month:")
            )

            if is_cal_query:
                # Determine target month and year
                cal_arg = ""
                if ":" in q:
                    cal_arg = q.split(":", 1)[1].strip().lower()
                elif " " in q:
                    cal_arg = q.split(" ", 1)[1].strip().lower()

                target_year = curr_year
                target_month = curr_month
                highlight_d = today_day_num if (target_year == curr_year and target_month == curr_month) else None

                MONTH_MAP = {
                    "jan": 1, "january": 1, "01": 1, "1": 1,
                    "feb": 2, "february": 2, "02": 2, "2": 2,
                    "mar": 3, "march": 3, "03": 3, "3": 3,
                    "apr": 4, "april": 4, "04": 4, "4": 4,
                    "may": 5, "05": 5, "5": 5,
                    "jun": 6, "june": 6, "06": 6, "6": 6,
                    "jul": 7, "july": 7, "07": 7, "7": 7,
                    "aug": 8, "august": 8, "08": 8, "8": 8,
                    "sep": 9, "sept": 9, "september": 9, "09": 9, "9": 9,
                    "oct": 10, "october": 10, "10": 10,
                    "nov": 11, "november": 11, "11": 11,
                    "dec": 12, "december": 12, "12": 12
                }

                if cal_arg in ("next", "next month", "+1", "+1m"):
                    if target_month == 12:
                        target_month = 1
                        target_year += 1
                    else:
                        target_month += 1
                    highlight_d = None
                elif cal_arg in ("prev", "previous", "last", "last month", "prev month", "-1", "-1m"):
                    if target_month == 1:
                        target_month = 12
                        target_year -= 1
                    else:
                        target_month -= 1
                    highlight_d = None
                elif cal_arg:
                    parts = cal_arg.replace(",", " ").replace("-", " ").replace("/", " ").split()
                    for p in parts:
                        if p.isdigit():
                            val = int(p)
                            if 1900 <= val <= 2200:
                                target_year = val
                            elif 1 <= val <= 12:
                                target_month = val
                        elif p in MONTH_MAP:
                            target_month = MONTH_MAP[p]

                highlight_d = today_day_num if (target_year == curr_year and target_month == curr_month) else None
                t_m_name = calendar.month_name[target_month]
                days_in_t_month = calendar.monthrange(target_year, target_month)[1]
                first_weekday_idx = calendar.monthrange(target_year, target_month)[0]
                first_weekday_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][first_weekday_idx]
                grid_str = generate_month_calendar_text(target_year, target_month, highlight_d)

                # Next/Prev month definitions
                next_m = 1 if target_month == 12 else target_month + 1
                next_y = target_year + 1 if target_month == 12 else target_year
                next_m_name = calendar.month_name[next_m]

                prev_m = 12 if target_month == 1 else target_month - 1
                prev_y = target_year - 1 if target_month == 1 else target_year
                prev_m_name = calendar.month_name[prev_m]

                # 1. Primary Monthly Calendar Card
                results.append(SearchItem(
                    id="cal_active_month",
                    title=f"Monthly Calendar — {t_m_name} {target_year}",
                    subtitle=f"{days_in_t_month} Days • Starts on {first_weekday_name} • Press Enter to open Calendar",
                    category="CALENDAR",
                    target=f"{t_m_name} {target_year}",
                    action=lambda: open_system_calendar(),
                    score=1000
                ))

                # 2. Copy Calendar Grid to Clipboard
                results.append(SearchItem(
                    id="cal_copy_grid",
                    title=f"Copy {t_m_name} {target_year} Calendar Grid",
                    subtitle="Copy clean ASCII formatted monthly grid to clipboard",
                    category="CALENDAR",
                    target=grid_str,
                    action=lambda g=grid_str: copy_to_clipboard(g),
                    score=950
                ))

                # 3. Today's Date info (if viewing current month) or Today quick jump
                if target_year == curr_year and target_month == curr_month:
                    results.append(SearchItem(
                        id="cal_today_info",
                        title=f"Today: {formatted_date_full}",
                        subtitle=f"Day {day_of_year} of {total_days_year} (Week {iso_week}) • Press Enter to copy date",
                        category="DATE",
                        target=formatted_date_full,
                        action=lambda d=formatted_date_full: copy_to_clipboard(d),
                        score=920
                    ))
                else:
                    results.append(SearchItem(
                        id="cal_jump_today",
                        title=f"Jump to Today: {formatted_date_full}",
                        subtitle="View current month and date in Calendar",
                        category="CALENDAR",
                        target=formatted_date_full,
                        action=lambda: open_system_calendar(),
                        score=920
                    ))

                # 4. Next Month preview card
                results.append(SearchItem(
                    id="cal_next_month",
                    title=f"Next Month: {next_m_name} {next_y}",
                    subtitle=f"{calendar.monthrange(next_y, next_m)[1]} Days • Type cal {next_m_name.lower()} to view",
                    category="CALENDAR",
                    target=f"{next_m_name} {next_y}",
                    action=lambda: open_system_calendar(),
                    score=890
                ))

                # 5. Previous Month preview card
                results.append(SearchItem(
                    id="cal_prev_month",
                    title=f"Previous Month: {prev_m_name} {prev_y}",
                    subtitle=f"{calendar.monthrange(prev_y, prev_m)[1]} Days • Type cal {prev_m_name.lower()} to view",
                    category="CALENDAR",
                    target=f"{prev_m_name} {prev_y}",
                    action=lambda: open_system_calendar(),
                    score=880
                ))

                return results[:max_results]

            # ----------------------------------------------------
            # B. DATE QUERIES (date?, date, date today, today date, what is the date, etc.)
            # ----------------------------------------------------
            is_date_query = (
                low_q in ("date?", "date", "date:", "today", "today's date", "todays date",
                          "date today", "today date", "what is the date", "what is the date today",
                          "what's the date", "what's today's date", "current date", "what date is today",
                          "what date is it", "today's date?", "todays date?") or
                low_q.startswith("date ") or low_q.startswith("date:")
            )

            if is_date_query:
                # 1. Full formatted date card
                results.append(SearchItem(
                    id="date_full",
                    title=f"Date: {formatted_date_full}",
                    subtitle=f"{formatted_date_short} • Day {day_of_year} of {total_days_year} (Week {iso_week}) • Press Enter to copy",
                    category="DATE",
                    target=formatted_date_full,
                    action=lambda d=formatted_date_full: copy_to_clipboard(d),
                    score=1000
                ))

                # 2. Weekday & Day Status
                results.append(SearchItem(
                    id="date_day_status",
                    title=f"Today is {day_name}",
                    subtitle=f"{month_name} {today_day_num}, {curr_year} • {days_left_year} days remaining in {curr_year}",
                    category="DAY",
                    target=day_name,
                    action=lambda d=day_name: copy_to_clipboard(d),
                    score=950
                ))

                # 3. Monthly Calendar shortcut
                grid_str = generate_month_calendar_text(curr_year, curr_month, today_day_num)
                results.append(SearchItem(
                    id="date_cal_shortcut",
                    title=f"Monthly Calendar — {month_name} {curr_year}",
                    subtitle=f"{calendar.monthrange(curr_year, curr_month)[1]} Days • Press Enter to open Calendar",
                    category="CALENDAR",
                    target=f"{month_name} {curr_year}",
                    action=lambda: open_system_calendar(),
                    score=900
                ))

                # 4. Copy Month Grid
                results.append(SearchItem(
                    id="date_copy_grid",
                    title=f"Copy {month_name} {curr_year} Calendar Grid",
                    subtitle="Copy formatted monthly calendar grid to clipboard",
                    category="CALENDAR",
                    target=grid_str,
                    action=lambda g=grid_str: copy_to_clipboard(g),
                    score=850
                ))

                # 5. Local Time & Timestamp
                time_str = now_dt.strftime("%I:%M:%S %p")
                results.append(SearchItem(
                    id="date_time_local",
                    title=f"Time: {time_str}",
                    subtitle=f"Local system time • Press Enter to copy timestamp",
                    category="TIME",
                    target=f"{formatted_date_full} {time_str}",
                    action=lambda s=f"{formatted_date_full} {time_str}": copy_to_clipboard(s),
                    score=800
                ))

                return results[:max_results]

            # ----------------------------------------------------
            # C. DAY QUERIES (day today, day?, day, today day, what day is today, etc.)
            # ----------------------------------------------------
            is_day_query = (
                low_q in ("day today", "day", "day?", "day:", "today day", "what day is today",
                          "what day is it", "what's the day", "what day is it today", "day of week",
                          "day of the week", "weekday", "current day", "what day", "day today?",
                          "today's day", "todays day") or
                low_q.startswith("day ") or low_q.startswith("day:")
            )

            if is_day_query:
                # 1. Day of the Week Primary Card
                results.append(SearchItem(
                    id="day_primary",
                    title=f"Today is {day_name}",
                    subtitle=f"{formatted_date_full} • Week {iso_week} • Press Enter to copy day",
                    category="DAY",
                    target=day_name,
                    action=lambda d=day_name: copy_to_clipboard(d),
                    score=1000
                ))

                # 2. Formatted Date Card
                results.append(SearchItem(
                    id="day_date_card",
                    title=f"Date: {formatted_date_full}",
                    subtitle=f"Day {day_of_year} of {total_days_year} • {days_left_year} days remaining in {curr_year}",
                    category="DATE",
                    target=formatted_date_full,
                    action=lambda d=formatted_date_full: copy_to_clipboard(d),
                    score=950
                ))

                # 3. Monthly Calendar Card
                results.append(SearchItem(
                    id="day_cal_card",
                    title=f"Monthly Calendar — {month_name} {curr_year}",
                    subtitle=f"{calendar.monthrange(curr_year, curr_month)[1]} Days • Press Enter to open Calendar",
                    category="CALENDAR",
                    target=f"{month_name} {curr_year}",
                    action=lambda: open_system_calendar(),
                    score=900
                ))

                return results[:max_results]

            # ----------------------------------------------------
            # D. TIME & WORLD CLOCK & TIMERS (time:, time in ..., time, now, timestamp, epoch)
            # ----------------------------------------------------
            if low_q.startswith("time:") or low_q.startswith("time in ") or low_q in ("time", "time?", "now", "clock", "timestamp", "epoch"):
                city_term = ""
                if low_q.startswith("time:"):
                    city_term = low_q[5:].strip()
                elif low_q.startswith("time in "):
                    city_term = low_q[8:].strip()

                TIMEZONES = {
                    "utc": (0, "UTC (Universal Time)"),
                    "gmt": (0, "GMT (Greenwich Mean Time)"),
                    "london": (0, "London, UK"),
                    "paris": (1, "Paris, France"),
                    "berlin": (1, "Berlin, Germany"),
                    "rome": (1, "Rome, Italy"),
                    "cairo": (2, "Cairo, Egypt"),
                    "dubai": (4, "Dubai, UAE"),
                    "ist": (5.5, "IST (India Standard Time)"),
                    "india": (5.5, "India (IST)"),
                    "mumbai": (5.5, "Mumbai, India"),
                    "delhi": (5.5, "Delhi, India"),
                    "bangkok": (7, "Bangkok, Thailand"),
                    "singapore": (8, "Singapore"),
                    "hong kong": (8, "Hong Kong"),
                    "beijing": (8, "Beijing, China"),
                    "tokyo": (9, "Tokyo, Japan"),
                    "jst": (9, "JST (Japan Standard Time)"),
                    "sydney": (11, "Sydney, Australia"),
                    "auckland": (13, "Auckland, New Zealand"),
                    "hawaii": (-10, "Honolulu, Hawaii"),
                    "pst": (-8, "PST (Pacific Standard Time)"),
                    "los angeles": (-8, "Los Angeles, USA"),
                    "san francisco": (-8, "San Francisco, USA"),
                    "mst": (-7, "MST (Mountain Standard Time)"),
                    "denver": (-7, "Denver, USA"),
                    "cst": (-6, "CST (Central Standard Time)"),
                    "chicago": (-6, "Chicago, USA"),
                    "est": (-5, "EST (Eastern Standard Time)"),
                    "new york": (-5, "New York, USA"),
                    "toronto": (-5, "Toronto, Canada"),
                    "sao paulo": (-3, "São Paulo, Brazil")
                }

                now_utc = datetime.datetime.now(datetime.timezone.utc)
                if city_term and city_term in TIMEZONES:
                    offset_hrs, city_name = TIMEZONES[city_term]
                    target_dt = now_utc + datetime.timedelta(hours=offset_hrs)
                    time_str = target_dt.strftime("%I:%M %p")
                    date_str = target_dt.strftime("%A, %B %d, %Y")
                    results.append(SearchItem(
                        id="world_time",
                        title=f"{time_str} — {city_name}",
                        subtitle=f"{date_str} (UTC {offset_hrs:+g}) • Enter to copy time",
                        category="TIME",
                        target=time_str,
                        action=lambda t=time_str: copy_to_clipboard(t),
                        score=1000
                    ))
                    return results
                else:
                    # Local Time & Date
                    now_loc = datetime.datetime.now()
                    time_str = now_loc.strftime("%I:%M:%S %p")
                    date_str = now_loc.strftime("%A, %B %d, %Y")
                    epoch_str = str(int(time.time()))
                    results.append(SearchItem(
                        id="local_time",
                        title=f"Local Time: {time_str}",
                        subtitle=f"{date_str} • Press Enter to copy formatted date & time",
                        category="TIME",
                        target=f"{time_str} - {date_str}",
                        action=lambda s=f"{time_str} - {date_str}": copy_to_clipboard(s),
                        score=1000
                    ))
                    results.append(SearchItem(
                        id="local_date",
                        title=f"Date: {date_str}",
                        subtitle=f"Today is {now_loc.strftime('%A')} • Press Enter to copy date",
                        category="DATE",
                        target=date_str,
                        action=lambda s=date_str: copy_to_clipboard(s),
                        score=970
                    ))
                    results.append(SearchItem(
                        id="unix_timestamp",
                        title=f"Unix Timestamp: {epoch_str}",
                        subtitle="Current Unix Epoch timestamp in seconds",
                        category="TIME",
                        target=epoch_str,
                        action=lambda s=epoch_str: copy_to_clipboard(s),
                        score=950
                    ))
                    return results

            # Timer (timer: 5m, timer 10m, timer 30s)
            timer_match = re.match(r"^timer:?\s*(\d+)\s*(s|sec|m|min|mins|h|hr|hours)?$", low_q)
            if timer_match:
                val = int(timer_match.group(1))
                unit = (timer_match.group(2) or "m").lower()
                dur_sec = val if unit in ("s", "sec") else (val * 3600 if unit in ("h", "hr", "hours") else val * 60)
                lbl = f"{val} {unit}"
                results.append(SearchItem(
                    id="timer_start",
                    title=f"Start Timer: {val} {unit}",
                    subtitle=f"Triggers audio & desktop notification after {dur_sec}s",
                    category="TIMER",
                    target=str(dur_sec),
                    action=lambda d=dur_sec, l=lbl: trigger_desktop_timer(d, l),
                    score=1000
                ))
                return results

        # ==========================================
        # 6. SYSTEM ACTIONS & POWER CONTROLS (sys: or lock, sleep, ip)
        # ==========================================
        if enable_sys:
            system_commands = {
                "lock": ("Lock Workstation", "Lock Windows screen and protect session", "rundll32.exe user32.dll,LockWorkStation"),
                "sleep": ("Sleep PC", "Put computer into low-power sleep mode", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"),
                "restart": ("Restart Computer", "Reboot Windows system immediately", "shutdown /r /t 0"),
                "reboot": ("Restart Computer", "Reboot Windows system immediately", "shutdown /r /t 0"),
                "shutdown": ("Shut Down PC", "Power off Windows system completely", "shutdown /s /t 0"),
                "empty bin": ("Empty Recycle Bin", "Permanently delete all items from Recycle Bin", "powershell -Command Clear-RecycleBin -Force -ErrorAction SilentlyContinue"),
                "empty recycle bin": ("Empty Recycle Bin", "Permanently delete all items from Recycle Bin", "powershell -Command Clear-RecycleBin -Force -ErrorAction SilentlyContinue"),
                "trash": ("Empty Recycle Bin", "Permanently delete all items from Recycle Bin", "powershell -Command Clear-RecycleBin -Force -ErrorAction SilentlyContinue"),
                "recycle": ("Empty Recycle Bin", "Permanently delete all items from Recycle Bin", "powershell -Command Clear-RecycleBin -Force -ErrorAction SilentlyContinue"),
                "ip": ("View Local IP Address", "Display and copy local network IPv4 address", "ip_lookup"),
                "my ip": ("View Local IP Address", "Display and copy local network IPv4 address", "ip_lookup")
            }

            if low_q.startswith("sys:") or low_q in system_commands:
                cmd_key = low_q[4:].strip() if low_q.startswith("sys:") else low_q
                if cmd_key in system_commands:
                    title, sub, exec_cmd = system_commands[cmd_key]
                    if exec_cmd == "ip_lookup":
                        import socket
                        try:
                            local_ip = socket.gethostbyname(socket.gethostname())
                        except Exception:
                            local_ip = "127.0.0.1"
                        results.append(SearchItem(
                            id="sys_ip",
                            title=f"IP Address: {local_ip}",
                            subtitle="Local Network IPv4 (Press Enter to copy)",
                            category="SYSTEM",
                            target=local_ip,
                            action=lambda ip=local_ip: copy_to_clipboard(ip),
                            score=1000
                        ))
                    else:
                        results.append(SearchItem(
                            id=f"sys_{cmd_key}",
                            title=title,
                            subtitle=sub,
                            category="SYSTEM",
                            target=exec_cmd,
                            action=lambda c=exec_cmd: subprocess.Popen(c, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                            score=1000
                        ))
                    return results
                elif low_q.startswith("sys:"):
                    # List all system actions
                    for k, (title, sub, exec_cmd) in system_commands.items():
                        if k not in ("reboot", "trash", "recycle", "my ip"):
                            results.append(SearchItem(
                                id=f"sys_{k}",
                                title=title,
                                subtitle=sub,
                                category="SYSTEM",
                                target=exec_cmd,
                                action=lambda c=exec_cmd: subprocess.Popen(c, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                                score=950
                            ))
                    return results[:max_results]

        # ==========================================
        # 6.5. ODD SOFTWARE UPDATES & CHECK
        # ==========================================
        if low_q in ("update", "updates", "odd update", "odd updates", "check update", "check updates", "check for updates", "odd: update", "odd:update"):
            from odd_updater import UpdateManager, CURRENT_VERSION
            upd_mgr = UpdateManager.get_instance()
            if upd_mgr.latest_release and upd_mgr.latest_release.is_newer:
                rel = upd_mgr.latest_release
                def _do_update():
                    if upd_mgr.downloaded_setup_path:
                        upd_mgr.apply_update_and_restart()
                    else:
                        upd_mgr.start_download(rel)

                sub = f"Version {rel.version_display} ready • Press Enter to update" if not upd_mgr.downloaded_setup_path else f"Downloaded • Press Enter to restart & apply {rel.version_display}"
                results.append(SearchItem(
                    id="odd_update_available",
                    title=f"Update ODD ({rel.version_display})",
                    subtitle=sub,
                    category="UPDATE",
                    target="update",
                    action=_do_update,
                    score=1200
                ))
            else:
                def _do_check():
                    upd_mgr.check_for_updates(manual=True)

                results.append(SearchItem(
                    id="odd_check_update",
                    title="Check for ODD Updates",
                    subtitle=f"Current version: v{CURRENT_VERSION} • Press Enter to check for updates",
                    category="UPDATE",
                    target="update",
                    action=_do_check,
                    score=1200
                ))
            return results[:max_results]

        # ==========================================
        # 7. WEB OMNIBOX DIRECT SHORTCUTS
        # ==========================================
        if enable_web_shortcuts:
            web_shortcuts = [
                (("g:", "google:"), "Google Search", "Search the web with Google", "https://www.google.com/search?q="),
                (("yt:", "youtube:"), "YouTube", "Search videos on YouTube", "https://www.youtube.com/results?search_query="),
                (("gh:", "github:"), "GitHub", "Search repositories and code on GitHub", "https://github.com/search?q="),
                (("wiki:", "wikipedia:"), "Wikipedia", "Search encyclopedia articles on Wikipedia", "https://en.wikipedia.org/wiki/Special:Search?search="),
                (("map:", "maps:"), "Google Maps", "Search places and directions on Google Maps", "https://www.google.com/maps/search/"),
                (("r:", "reddit:"), "Reddit", "Search posts and communities on Reddit", "https://www.reddit.com/search/?q="),
                (("d:", "ddg:", "duck:"), "DuckDuckGo", "Search privately with DuckDuckGo", "https://duckduckgo.com/?q="),
                (("x:", "tw:", "twitter:"), "X / Twitter", "Search posts on X", "https://x.com/search?q="),
                (("amz:", "amazon:"), "Amazon", "Search products on Amazon", "https://www.amazon.com/s?k=")
            ]

            for prefixes, service_name, desc, base_url in web_shortcuts:
                for p in prefixes:
                    if low_q.startswith(p):
                        term = q[len(p):].strip()
                        encoded = urllib.parse.quote_plus(term)
                        target_url = f"{base_url}{encoded}"
                        results.append(SearchItem(
                            id=f"web_{service_name.lower()}",
                            title=f"{service_name}: \"{term}\"",
                            subtitle=desc,
                            category="WEB",
                            target=target_url,
                            action=lambda u=target_url: webbrowser.open(u),
                            score=1000
                        ))
                        return results[:max_results]

        # ==========================================
        # 8. CALCULATOR (calc:, percentages, & inline math)
        # ==========================================
        def _calc_smart_math(raw_expr: str) -> Optional[str]:
            raw = raw_expr.strip()
            if not raw:
                return None
            # Percentage: "20% of 850"
            m_of = re.match(r"^([\d.]+)\s*%\s*(?:of)\s*([\d.]+)$", raw, re.IGNORECASE)
            if m_of:
                try:
                    pct = float(m_of.group(1))
                    base = float(m_of.group(2))
                    ans = (pct / 100.0) * base
                    return f"{ans:g}"
                except Exception:
                    pass
            # Addition/subtraction percentage: "100 + 15%" or "500 - 20%"
            m_add_sub = re.match(r"^([\d.]+)\s*([+\-])\s*([\d.]+)\s*%$", raw)
            if m_add_sub:
                try:
                    base = float(m_add_sub.group(1))
                    op = m_add_sub.group(2)
                    pct = float(m_add_sub.group(3))
                    delta = base * (pct / 100.0)
                    ans = base + delta if op == "+" else base - delta
                    return f"{ans:g}"
                except Exception:
                    pass
            # Hex / Binary conversions: "hex 255" or "bin 42"
            if raw.lower().startswith("hex "):
                try:
                    v = int(raw[4:].strip())
                    return hex(v)
                except Exception:
                    pass
            if raw.lower().startswith("bin "):
                try:
                    v = int(raw[4:].strip())
                    return bin(v)
                except Exception:
                    pass

            cleaned = raw.replace("^", "**")
            safe_names = {
                "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "abs": abs, "pow": pow, "pi": math.pi, "e": math.e, "log": math.log,
                "floor": math.floor, "ceil": math.ceil, "round": round
            }
            if re.match(r"^[0-9+\-*/().,%^ \t_a-z]+$", cleaned.lower()):
                words = re.findall(r"[a-z_]+", cleaned.lower())
                if all(w in safe_names for w in words):
                    try:
                        res = eval(cleaned, {"__builtins__": {}}, safe_names)
                        if isinstance(res, (int, float)):
                            return f"{res:g}"
                    except Exception:
                        pass
            return None

        if enable_calc:
            calc_q = None
            if low_q.startswith("calc:"):
                calc_q = q.split(":", 1)[1].strip()
            elif "%" in q or any(func in low_q for func in ("sqrt(", "pow(", "sin(", "cos(", "abs(")) or \
                 (any(op in q for op in "+-*/^") and not any(ch.isalpha() for ch in q)):
                calc_q = q

            if calc_q:
                calc_ans = _calc_smart_math(calc_q)
                if calc_ans is not None:
                    results.append(SearchItem(
                        id="calc_smart_result",
                        title=f"= {calc_ans}",
                        subtitle=f"Calculation result for '{calc_q}' • Press Enter to copy",
                        category="CALC",
                        target=calc_ans,
                        action=lambda r=calc_ans: copy_to_clipboard(r),
                        score=1100
                    ))
                    if low_q.startswith("calc:"):
                        return results[:max_results]

        # Command Prompt (cmd: ...)
        if low_q.startswith("cmd:") or low_q.startswith("exec:"):
            cmd = q.split(":", 1)[1].strip()
            results.append(SearchItem(
                id="cmd_exec",
                title=f"Run command: \"{cmd}\"",
                subtitle="Execute in Windows Command Shell",
                category="COMMAND",
                target=cmd,
                action=lambda c=cmd: subprocess.Popen(f'start cmd /k "{c}"', shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                score=1000
            ))
            return results[:max_results]

        # Direct Web App Shortcuts (e.g. "chatgpt", "claude", "youtube", "github")
        if low_q in WEB_APP_TARGETS:
            w_title, w_url, w_sub = WEB_APP_TARGETS[low_q]
            results.append(SearchItem(
                id=f"web_app_{low_q}",
                title=f"{w_title} (Web Browser)",
                subtitle=f"{w_sub}  •  {w_url}",
                category="WEB APP",
                target=w_url,
                action=lambda u=w_url: webbrowser.open(u),
                score=960
            ))

        # Direct URL Detection (excludes local filenames like story.pdf)
        if is_likely_web_domain(low_q):
            url = q if (low_q.startswith("http://") or low_q.startswith("https://")) else f"https://{q}"
            results.append(SearchItem(
                id="direct_url",
                title=f"Open Website: {url}",
                subtitle="Navigate to web address directly in default browser",
                category="URL",
                target=url,
                action=lambda u=url: webbrowser.open(u),
                score=900
            ))

        # ==========================================
        # 9. DEDICATED FILE & FOLDER PREFIX SEARCHES (Instant In-Memory Filter)
        # ==========================================
        # PDF Search (pdf: <query>, pdfs: <query>)
        if low_q.startswith("pdf:") or low_q.startswith("pdf ") or low_q == "pdf" or low_q.startswith("pdfs:") or low_q.startswith("pdfs "):
            term = q.split(":", 1)[1].strip() if ":" in q else (q.split(" ", 1)[1].strip() if " " in q else "")
            low_term = term.lower()
            for rec in self._indexed_files:
                if rec.category == "PDF" or rec.t_low.endswith(".pdf"):
                    if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                        continue
                    s = score_record(low_term, rec) if low_term else 800
                    if not low_term or s > 0:
                        results.append(SearchItem(
                            id=f"pdf_{rec.target}",
                            title=rec.title,
                            subtitle=rec.subtitle,
                            category="PDF",
                            target=rec.target,
                            action=lambda p=rec.target: self._open_target(p),
                            score=s + 200
                        ))
            if results:
                unique = []
                seen_t = set()
                for it in sorted(results, key=lambda x: x.score, reverse=True):
                    if it.target.lower() not in seen_t:
                        seen_t.add(it.target.lower())
                        unique.append(it)
                return unique[:max_results]
            else:
                results.append(SearchItem(
                    id="pdf_none",
                    title=f"No PDF documents matching \"{term}\"" if term else "No PDF documents found",
                    subtitle="Search another filename or keyword across your computer",
                    category="PDF",
                    target="",
                    score=1000
                ))
                return results

        # Documents Search (doc: <query>, docs: <query>, document: <query>)
        if low_q.startswith("doc:") or low_q.startswith("doc ") or low_q == "doc" or low_q.startswith("docs:") or low_q.startswith("docs ") or low_q.startswith("document:"):
            term = q.split(":", 1)[1].strip() if ":" in q else (q.split(" ", 1)[1].strip() if " " in q else "")
            low_term = term.lower()
            for rec in self._indexed_files:
                if rec.category in ("DOC", "PDF") or any(rec.t_low.endswith(ext) for ext in (".docx", ".doc", ".txt", ".xlsx", ".xls", ".pptx", ".ppt", ".md", ".csv")):
                    if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                        continue
                    s = score_record(low_term, rec) if low_term else 800
                    if not low_term or s > 0:
                        results.append(SearchItem(
                            id=f"doc_{rec.target}",
                            title=rec.title,
                            subtitle=rec.subtitle,
                            category=rec.category,
                            target=rec.target,
                            action=lambda p=rec.target: self._open_target(p),
                            score=s + 200
                        ))
            if results:
                unique = []
                seen_t = set()
                for it in sorted(results, key=lambda x: x.score, reverse=True):
                    if it.target.lower() not in seen_t:
                        seen_t.add(it.target.lower())
                        unique.append(it)
                return unique[:max_results]
            else:
                results.append(SearchItem(
                    id="doc_none",
                    title=f"No documents matching \"{term}\"" if term else "No documents found",
                    subtitle="Search another document name (.pdf, .docx, .txt, .xlsx, etc.)",
                    category="DOC",
                    target="",
                    score=1000
                ))
                return results

        # Folder Search (folder: <query>, folders: <query>, dir: <query>, directory: <query>)
        if low_q.startswith("folder:") or low_q.startswith("folder ") or low_q == "folder" or low_q.startswith("folders:") or low_q.startswith("dir:") or low_q.startswith("directory:"):
            term = q.split(":", 1)[1].strip() if ":" in q else (q.split(" ", 1)[1].strip() if " " in q else "")
            low_term = term.lower()
            for rec in self._indexed_folders:
                if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                    continue
                s = score_record(low_term, rec) if low_term else 800
                if not low_term or s > 0:
                    results.append(SearchItem(
                        id=f"folder_{rec.target}",
                        title=rec.title,
                        subtitle=rec.subtitle,
                        category="FOLDER",
                        target=rec.target,
                        action=lambda p=rec.target: self._open_target(p),
                        score=s + 200
                    ))
            if results:
                unique = []
                seen_t = set()
                for it in sorted(results, key=lambda x: x.score, reverse=True):
                    if it.target.lower() not in seen_t:
                        seen_t.add(it.target.lower())
                        unique.append(it)
                return unique[:max_results]
            else:
                results.append(SearchItem(
                    id="folder_none",
                    title=f"No folders matching \"{term}\"" if term else "No folders found",
                    subtitle="Search another folder name",
                    category="FOLDER",
                    target="",
                    score=1000
                ))
                return results

        # General Files & Folders Search (f: <query>, file: <query>, files: <query>)
        if low_q.startswith("f:") or low_q.startswith("f ") or low_q.startswith("file:") or low_q.startswith("files:"):
            term = q.split(":", 1)[1].strip() if ":" in q else (q.split(" ", 1)[1].strip() if " " in q else "")
            low_term = term.lower()
            for rec in self._indexed_folders:
                if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                    continue
                s = score_record(low_term, rec) if low_term else 700
                if not low_term or s > 0:
                    results.append(SearchItem(
                        id=f"f_fld_{rec.target}",
                        title=rec.title,
                        subtitle=rec.subtitle,
                        category="FOLDER",
                        target=rec.target,
                        action=lambda p=rec.target: self._open_target(p),
                        score=s + 120
                    ))
            for rec in self._indexed_files:
                if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                    continue
                s = score_record(low_term, rec) if low_term else 600
                if not low_term or s > 0:
                    results.append(SearchItem(
                        id=f"f_fil_{rec.target}",
                        title=rec.title,
                        subtitle=rec.subtitle,
                        category=rec.category,
                        target=rec.target,
                        action=lambda p=rec.target: self._open_target(p),
                        score=s + 80
                    ))
            if results:
                unique = []
                seen_t = set()
                for it in sorted(results, key=lambda x: x.score, reverse=True):
                    if it.target.lower() not in seen_t:
                        seen_t.add(it.target.lower())
                        unique.append(it)
                return unique[:max_results]
            else:
                results.append(SearchItem(
                    id="f_none",
                    title=f"No files or folders matching \"{term}\"" if term else "No files or folders found",
                    subtitle="Try another search term across all indexed drives",
                    category="FILE",
                    target="",
                    score=1000
                ))
                return results

        # Image Search (img: <query>, image: <query>, pic: <query>, photo: <query>)
        if low_q.startswith("img:") or low_q.startswith("image:") or low_q.startswith("pic:") or low_q.startswith("photo:"):
            term = q.split(":", 1)[1].strip()
            low_term = term.lower()
            for rec in self._indexed_files:
                if rec.category == "IMAGE" or any(rec.t_low.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico")):
                    if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                        continue
                    s = score_record(low_term, rec) if low_term else 800
                    if not low_term or s > 0:
                        results.append(SearchItem(
                            id=f"img_{rec.target}",
                            title=rec.title,
                            subtitle=rec.subtitle,
                            category="IMAGE",
                            target=rec.target,
                            action=lambda p=rec.target: self._open_target(p),
                            score=s + 200
                        ))
            if results:
                unique = []
                seen_t = set()
                for it in sorted(results, key=lambda x: x.score, reverse=True):
                    if it.target.lower() not in seen_t:
                        seen_t.add(it.target.lower())
                        unique.append(it)
                return unique[:max_results]

        # Audio Search (audio: <query>, song: <query>)
        if low_q.startswith("audio:") or low_q.startswith("song:"):
            term = q.split(":", 1)[1].strip()
            low_term = term.lower()
            for rec in self._indexed_files:
                if rec.category == "AUDIO" or any(rec.t_low.endswith(ext) for ext in (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg")):
                    if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                        continue
                    s = score_record(low_term, rec) if low_term else 800
                    if not low_term or s > 0:
                        results.append(SearchItem(
                            id=f"audio_{rec.target}",
                            title=rec.title,
                            subtitle=rec.subtitle,
                            category="AUDIO",
                            target=rec.target,
                            action=lambda p=rec.target: self._open_target(p),
                            score=s + 200
                        ))
            if results:
                unique = []
                seen_t = set()
                for it in sorted(results, key=lambda x: x.score, reverse=True):
                    if it.target.lower() not in seen_t:
                        seen_t.add(it.target.lower())
                        unique.append(it)
                return unique[:max_results]

        # Video Search (video: <query>, vid: <query>, movie: <query>)
        if low_q.startswith("video:") or low_q.startswith("vid:") or low_q.startswith("movie:"):
            term = q.split(":", 1)[1].strip()
            low_term = term.lower()
            for rec in self._indexed_files:
                if rec.category == "VIDEO" or any(rec.t_low.endswith(ext) for ext in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm")):
                    if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                        continue
                    s = score_record(low_term, rec) if low_term else 800
                    if not low_term or s > 0:
                        results.append(SearchItem(
                            id=f"video_{rec.target}",
                            title=rec.title,
                            subtitle=rec.subtitle,
                            category="VIDEO",
                            target=rec.target,
                            action=lambda p=rec.target: self._open_target(p),
                            score=s + 200
                        ))
            if results:
                unique = []
                seen_t = set()
                for it in sorted(results, key=lambda x: x.score, reverse=True):
                    if it.target.lower() not in seen_t:
                        seen_t.add(it.target.lower())
                        unique.append(it)
                return unique[:max_results]

        # Open Search (open: <query>, open <query>)
        if low_q.startswith("open:") or low_q.startswith("open "):
            term = q.split(":", 1)[1].strip() if ":" in q else q.split(" ", 1)[1].strip()
            low_term = term.lower()
            for rec in self._indexed_apps:
                if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                    continue
                s = score_record(low_term, rec) if low_term else 800
                if not low_term or s > 0:
                    results.append(SearchItem(
                        id=f"open_app_{rec.target}",
                        title=rec.title,
                        subtitle=rec.subtitle,
                        category="APP",
                        target=rec.target,
                        action=lambda p=rec.target: self._open_target(p),
                        score=s + 250
                    ))
            for rec in self._indexed_folders:
                if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                    continue
                s = score_record(low_term, rec) if low_term else 700
                if not low_term or s > 0:
                    results.append(SearchItem(
                        id=f"open_fld_{rec.target}",
                        title=rec.title,
                        subtitle=rec.subtitle,
                        category="FOLDER",
                        target=rec.target,
                        action=lambda p=rec.target: self._open_target(p),
                        score=s + 150
                    ))
            for rec in self._indexed_files:
                if low_term and (low_term not in rec.t_low and low_term not in rec.tgt_low):
                    continue
                s = score_record(low_term, rec) if low_term else 600
                if not low_term or s > 0:
                    results.append(SearchItem(
                        id=f"open_fil_{rec.target}",
                        title=rec.title,
                        subtitle=rec.subtitle,
                        category=rec.category,
                        target=rec.target,
                        action=lambda p=rec.target: self._open_target(p),
                        score=s + 100
                    ))
            if results:
                unique = []
                seen_t = set()
                for it in sorted(results, key=lambda x: x.score, reverse=True):
                    if it.target.lower() not in seen_t:
                        seen_t.add(it.target.lower())
                        unique.append(it)
                return unique[:max_results]

        # ==========================================
        # 10. GENERAL SEARCH (APPS, FOLDERS, FILES, PDFS, WINDOWS SEARCH)
        # ==========================================
        is_alias = low_q in ALIASES
        alias_targets = ALIASES[low_q] if is_alias else None

        # 1. Applications Match
        for idx, rec in enumerate(self._indexed_apps):
            if (idx & 0x1F) == 0:
                if cancel_event is not None and cancel_event.is_set():
                    return []
                time.sleep(0.0002)  # yield the GIL so keyboard input stays responsive
            s = score_record(low_q, rec, is_alias, alias_targets)
            if s > 0:
                results.append(SearchItem(
                    id=f"app_{rec.title}_{rec.target}",
                    title=rec.title,
                    subtitle=rec.subtitle,
                    category="APP",
                    target=rec.target,
                    action=lambda p=rec.target: self._open_target(p),
                    score=s + 100  # Priority boost for applications
                ))

        # 2. Folders Match
        for idx, rec in enumerate(self._indexed_folders):
            if (idx & 0x1F) == 0:
                if cancel_event is not None and cancel_event.is_set():
                    return []
                time.sleep(0.0002)
            if low_q not in rec.t_low and low_q not in rec.tgt_low:
                continue
            s = score_record(low_q, rec, is_alias, alias_targets)
            if s > 0:
                results.append(SearchItem(
                    id=f"folder_{rec.target}",
                    title=rec.title,
                    subtitle=rec.subtitle,
                    category="FOLDER",
                    target=rec.target,
                    action=lambda p=rec.target: self._open_target(p),
                    score=s
                ))

        # 3. Local Files Match (PDFs, Docs, Images, Code, etc.)
        # Skip scanning 20,000 files on short queries (< 3 chars) or when strong app matches exist to ensure instant 0ms keystroke typing
        has_enough_app_matches = sum(1 for r in results if r.score >= 550) >= max_results
        is_explicit_file_query = low_q.startswith((".", "\\", "/")) or low_q.startswith("f:") or low_q.startswith("file:")
        if (len(low_q) >= 3 or is_explicit_file_query) and not has_enough_app_matches:
            file_term = low_q[2:].strip() if low_q.startswith("f:") else (low_q[5:].strip() if low_q.startswith("file:") else low_q)
            for idx, rec in enumerate(self._indexed_files):
                if (idx & 0x1F) == 0:
                    if cancel_event is not None and cancel_event.is_set():
                        return []
                    time.sleep(0.0002)
                if file_term not in rec.t_low and file_term not in rec.tgt_low:
                    continue
                s = score_record(file_term, rec, is_alias, alias_targets)
                if s > 0:
                    # Give PDF and DOC files an extra relevance boost
                    cat_boost = 30 if rec.category in ("PDF", "DOC") else 0
                    results.append(SearchItem(
                        id=f"file_{rec.target}",
                        title=rec.title,
                        subtitle=rec.subtitle,
                        category=rec.category,
                        target=rec.target,
                        action=lambda p=rec.target: self._open_target(p),
                        score=s - 20 + cat_boost
                    ))

        # 4. Windows Desktop Search Collator Real-time Query (WSearch Index - if requested)
        if include_windows_search:
            try:
                ws_matches = query_windows_search(q, limit=8)
                for w_name, w_path, w_cat, w_sub in ws_matches:
                    s = score_match(q, w_name, w_sub, w_path)
                    if s == 0:
                        s = 350
                    cat_boost = 30 if w_cat in ("PDF", "DOC") else 0
                    results.append(SearchItem(
                        id=f"ws_{w_path}",
                        title=w_name,
                        subtitle=w_sub,
                        category=w_cat,
                        target=w_path,
                        action=lambda p=w_path: self._open_target(p),
                        score=s + cat_boost
                    ))
            except Exception:
                pass

        # Deduplicate and sort scored results descending
        unique_results = []
        seen_targets = set()
        for item in results:
            t_key = (item.title.lower(), item.target.lower())
            if t_key not in seen_targets:
                seen_targets.add(t_key)
                unique_results.append(item)

        unique_results.sort(key=lambda x: x.score, reverse=True)

        # ==========================================
        # 11. WEB FALLBACK
        # ==========================================
        if enable_fallbacks:
            encoded_all = urllib.parse.quote_plus(q)
            unique_results.append(SearchItem(
                id="fallback_google",
                title=f"Search Google for \"{q}\"",
                subtitle="Search the web with Google",
                category="WEB",
                target=f"https://www.google.com/search?q={encoded_all}",
                action=lambda: webbrowser.open(f"https://www.google.com/search?q={encoded_all}"),
                score=10
            ))

        return unique_results[:max_results]

    def query_windows_search_items(self, query: str, max_results: int = 8) -> List[SearchItem]:
        """Runs in background thread: queries Windows Search Collator DSO and returns SearchItems"""
        q = query.strip()
        if not q:
            return []
        low_q = q.lower()
        results = []

        type_filter = None
        term = q
        if low_q.startswith("pdf:") or low_q.startswith("pdf ") or low_q.startswith("pdfs:") or low_q.startswith("pdfs "):
            type_filter = "pdf"
            term = q.split(":", 1)[1].strip() if ":" in q else (q.split(" ", 1)[1].strip() if " " in q else "")
        elif low_q.startswith("doc:") or low_q.startswith("doc ") or low_q.startswith("docs:") or low_q.startswith("document:"):
            type_filter = "doc"
            term = q.split(":", 1)[1].strip() if ":" in q else (q.split(" ", 1)[1].strip() if " " in q else "")
        elif low_q.startswith("folder:") or low_q.startswith("folder ") or low_q.startswith("folders:") or low_q.startswith("dir:") or low_q.startswith("directory:"):
            type_filter = "folder"
            term = q.split(":", 1)[1].strip() if ":" in q else (q.split(" ", 1)[1].strip() if " " in q else "")
        elif low_q.startswith("f:") or low_q.startswith("f ") or low_q.startswith("file:") or low_q.startswith("files:"):
            type_filter = None
            term = q.split(":", 1)[1].strip() if ":" in q else (q.split(" ", 1)[1].strip() if " " in q else "")
        elif low_q.startswith("img:") or low_q.startswith("image:") or low_q.startswith("pic:"):
            type_filter = "img"
            term = q.split(":", 1)[1].strip()
        elif low_q.startswith("audio:") or low_q.startswith("song:"):
            type_filter = "audio"
            term = q.split(":", 1)[1].strip()
        elif low_q.startswith("video:") or low_q.startswith("vid:"):
            type_filter = "video"
            term = q.split(":", 1)[1].strip()
        elif low_q.startswith("open:") or low_q.startswith("open "):
            type_filter = None
            term = q.split(":", 1)[1].strip() if ":" in q else q.split(" ", 1)[1].strip()

        if not term:
            return []

        try:
            ws_matches = query_windows_search(term, limit=max_results, type_filter=type_filter)
            for w_name, w_path, w_cat, w_sub in ws_matches:
                s = score_match(term, w_name, w_sub, w_path)
                if s == 0:
                    s = 350
                cat_boost = 30 if w_cat in ("PDF", "DOC") else 0
                results.append(SearchItem(
                    id=f"ws_{w_path}",
                    title=w_name,
                    subtitle=w_sub,
                    category=w_cat,
                    target=w_path,
                    action=lambda p=w_path: self._open_target(p),
                    score=s + cat_boost
                ))
        except Exception:
            pass

        return results[:max_results]

    def execute(self, item: SearchItem):
        """Execute a search item's action or open its target directly"""
        try:
            if item.action and callable(item.action):
                item.action()
            elif item.target:
                self._open_target(item.target)
        except Exception as e:
            print(f"Error executing search item: {e}")
            if item.target:
                self._open_target(item.target)



