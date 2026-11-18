import json
import os
import subprocess
from pathlib import Path

SETTINGS_FILE = Path(os.path.expandvars(r"%APPDATA%\ODD\settings.json"))

DEFAULT_SETTINGS = {
    "theme": "dark",
    "ui_theme_style": "classic",  # "classic" (Floating Pill + Standalone ODD) or "container" (Unified Card with Bottom Dock)  # "dark", "light", "oled"
    "side_view": "off", # "off" (center normal view), "left" (top-left side view), "right" (top-right side view)
    "opacity": 0.95,
    "hotkey": "Win+Alt",
    "radial_menu_enabled": True,        # Hold Alt for 400ms to open ODD Radial Menu
    "radial_summon_key": "Alt",         # "Alt", "Ctrl", "Shift", "Win"
    "radial_summon_hold_ms": 400,       # Duration in ms to hold before radial menu opens
    "radial_shake_dismiss_enabled": True,# Deliberately shake cursor to dismiss radial menu
    "radial_magic_cursor": True,        # Specular shine reflection & magic glowing filaments
    "radial_bottom_music_overlay": True,# Minimal media info & play/pause button at bottom of radial menu
    "radial_search_enabled": True,      # Cursor-anchored fast search panel
    "radial_qs_enabled": True,          # Contextual quick settings 4-quadrant squircle overlay
    "radial_phone_enabled": True,       # Phone mirror companion overlay
    "replace_windows_search": False, # Opt-in setting to remap Windows Search shortcut (Win+S) to ODD
    "remind_windows_search_shortcut": True, # Subtle reminder hint when Windows Search opens
    "adapt_to_browser_controls": True, # Respect top-edge exclusion zones & Chrome tab-close buttons
    "edge": "top",
    "edge_trigger_mode": "hotkey_only", # In radial architecture, top hovering is disabled; summon via radial or hotkey
    "animation_style": "fluid",    # "fluid" (liquid gooey droplet - ultra smooth)
    "auto_hide_on_leave": True,
    "auto_hide_delay_ms": 120,
    "enable_music_overlay": True,
    "music_overlay_mode": "auto",  # "auto"/"dynamic" (minimal music + ODD search when playing), "always_minimal", "full_auto", "always", "disabled"
    "paused_media_behavior": "button_only", # "button_only" (media overlay only when playing), "show_minimal"
    "surface_on_startup": False,        # Keep ODD docked at edge upon launch instead of intrusive full popup
    "use_case_preset": "dynamic_island", # "dynamic_island", "minimal_launcher", "productivity", "media_companion"
    "quiet_hours_enabled": False,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "quiet_hours_mute_sound": True,
    "quiet_hours_suppress_popups": True,
    "quiet_hours_allow_priority": True,
    "sound_enabled": True,
    "sound_volume": 0.70,
    "sound_theme": "fluid", # "fluid" (organic liquid drops)
    "run_on_startup": True,
    "integrate_with_rook_tray": True,
    "edge_bar_color_mode": "theme",  # "theme", "preset", "custom"
    "edge_bar_color": "#FFFFFF",     # Default cyan accent for custom/preset
    "edge_bar_width": 140,            # Width in pixels (compact, sleek notch: 40 to 240)
    "edge_bar_thickness": 4,         # Thickness in pixels (2 to 8)
    "edge_bar_glow": False,          # Ambient glow around bar (disabled)
    "edge_notch_style": "simple",    # "simple" (Plain Bar), "worded" (Text / Info-matic), "mica" (Mica Companion)
    "edge_worded_mode": "static",    # "static" (Static Text) or "scroll" (Marquee Scroll)
    "edge_notch_text": "ODD",        # Custom text for static/scrolling notch
    "edge_bar_music_display": True,  # Modern edge bar design with Spotify icon & animated equalizer when music plays
    "edge_bar_infomatic": True,      # Informative edge bar cycling time, date, and running dot animation
    "hide_edge_bar": True,          # Make visual edge bar completely invisible (gestures stay 100% active)
    "ui_show_edge_indicator": True,  # Show visual edge notch pill indicator
    "ui_show_plus_button": True,     # Show '+' Quick Menu button in search pill
    "ui_show_quick_settings_button": True, # Show Quick Settings overlay button in search pill
    "ui_show_music_button": True,    # Show Music Waveform toggle in search pill
    "ui_show_lens_button": True,     # Show Google Lens overlay button in search pill
    "ui_show_settings_button": True, # Show standalone ODD settings logo button
    "ui_show_power_controls": True,  # Show Power controls & Quick Settings buttons below search bar
    "enable_clipboard_history": True,# Enable clipboard tracker & 'clip:'
    "enable_quick_notes": True,      # Enable quick notes & 'note:'
    "enable_unit_converter": True,   # Enable unit & currency conversions
    "enable_system_commands": True,  # Enable system power actions ('sys:', 'lock')
    "enable_world_clock": True,      # Enable world time & timers ('time:', 'timer:')
    "enable_color_inspector": True,  # Enable color inspector ('color:', '#hex')
    "enable_calculator": True,       # Enable calculator ('calc:' & inline math)
    "enable_web_shortcuts": True,    # Enable web omnibox shortcuts ('yt:', 'gh:', etc.)
    "enable_auto_update": True,      # Automatically download and prepare updates in the background
    "enable_web_fallbacks": True,    # Enable Google search fallback suggestions
    "enable_dynamic_island": True,   # Transform top edge notch into interactive Dynamic Island
    "enable_download_mode": True,    # Merge multiple downloads into tiny progress ring in Dynamic Island
    "enable_activity_memory": True,  # The Island remembers temporary activities and installations
    "auto_detect_downloads": True,   # Automatically detect active browser & Windows downloads
    "enable_island_reminders": True, # Natural-language reminders delivered directly inside Dynamic Island
    "enable_water_reminder": True,   # Smart hydration reminders directly in Dynamic Island
    "water_daily_liters": 2.0,       # Daily water intake target in Liters: 1.0, 2.0, 3.0, 4.0+
    "water_bottle_style": "broader_2l", # "small_1l" (1L), "broader_2l" (2L), "big_3l" (3L), "can_3plus" (3+L Can)
    "water_reminder_mode": "work",   # "work" (Whenever you work - active input) | "time" (Within time - clock schedule)
    "water_reminder_interval_min": 60,# Interval in minutes between hydration reminders
    "water_working_hours_only": True,# Active only during desk hours (e.g. 9:00 AM - 5:00 PM)
    "water_start_time": "09:00",     # Working hours start time
    "water_end_time": "17:00",       # Working hours end time
    "water_daily_goal": 8,           # Daily water glasses/sips goal (auto-calculated from liters)
    "dynamic_maximized_delay": True, # Dynamic delay when Chrome or app is maximized to prevent accidental trigger when closing tabs
    "enable_eye_rest_reminder": True,   # Eye Rest (1 hr interval)
    "eye_rest_reminder_mode": "work",  # "work" (Whenever you work - active input) | "time" (Within time - clock schedule)
    "eye_rest_interval_min": 60,       # Eye rest will remind for every 1 hr (60 minutes)
    "enable_posture_reminder": True,    # Posture & desk stretch reminder
    "posture_interval_min": 90,        # Every 90 minutes
    "enable_ventilation_reminder": True,# Fresh air & window ventilation reminder
    "ventilation_interval_min": 180,   # Every 180 minutes (3 hours)
    "enable_battery_health_alert": True,# Charger alerts at 80% and 30%
    "battery_high_limit": 80,          # High charge unplug warning (%)
    "battery_low_limit": 30,           # Low charge plug-in warning (%)
    "battery_auto_detect_plug": True,  # Automatically detect charger connection/disconnection to resolve battery reminders
    "system_needs_intelligence": True, # Context-aware intelligence for power velocity, user presence & system resources
    "smart_game_focus_mode": True,     # Automatically suppress non-critical popups during full-screen games/presentations
    "enable_storage_purge_reminder": True, # Bi-weekly Downloads and Recycle Bin cleanup reminder
    "storage_purge_interval_days": 14, # Every 14 days
    "storage_warn_threshold_pct": 80,  # Warning threshold when C: drive capacity exceeds (%)
    "default_snooze_minutes": 5,     # Default snooze duration (minutes)
    "island_show_media_hud": False,  # No top edge mini pill popup on media playback
    "island_media_style": "vinyl",   # "vinyl" (Rotating Vinyl Disc), "pill" (Modern Pill), "minimal" (Minimal Capsule)
    "island_media_visibility": "auto_hide", # "auto_hide" (Hidable after track change), "persistent" (Non-hidable while playing), "minimized" (Always notch)
    "enable_vinyl_rotation": True,   # Enable realistic rotating vinyl disc physics
    "island_media_auto_width": True, # Auto-hug track title/artist (eliminates all empty spaces)
    "island_show_volume_hud": True,  # Expand island on Windows volume changes
    "island_show_battery_hud": True, # Expand island on power plug/battery transitions
    "island_show_timer_ticker": True,# Show live ticking countdown in island notch
    "island_show_caps_lock_hud": True,# Brief alert when Caps Lock or Num Lock is pressed
    "island_show_clipboard_hud": True,# Fast pulse on copying or pasting text
    "island_show_system_notifications": True, # Display Windows & app notifications in Dynamic Island
    "dnd_enabled": False,                     # Do Not Disturb: silence and suppress all notifications in ODD
    "notification_duration_sec": 5,           # Popup display duration before auto-hiding (seconds)
    "island_hud_duration_ms": 2500,  # Snappy HUD duration (ms)
    "enable_rook_hud": True,         # Show Rook shortcut indication animations in ODD Island
    "search_pill_action_button": "both", # "both" (All Enabled Overlay Buttons), "dynamic", "dynamic_swap", "google_lens", "music", or "none"
    "enable_quick_messaging": True,  # Enable natural-language Quick Text Sending ("Text John I'll be there")
    "enable_weather_widget": True,   # Display weather widget with live temperature on the Island
    "weather_location": "Auto-detect",# Location for weather forecast ("Auto-detect" or city name)
    "weather_unit": "celsius",       # "celsius" (°C) or "fahrenheit" (°F)
    "weather_replace_slot": "music", # Slot to replace on the Island: "music", "lens", "quick_settings", "standalone"
    "enable_android_mirror": True,   # Android Screen Mirroring & Bluetooth Phone Controls (Experimental)
    "android_mirror_replace_slot": "standalone", # Slot in Search Pill: "standalone", "music", "lens", "quick_settings", "none"
    "messaging_provider": "whatsapp_desktop", # "whatsapp_desktop" (WhatsApp Desktop) or "whatsapp_web" (WhatsApp Web)
    "prefixes": {
        "ocr:": "Screen Intelligence: OCR & Text Extraction",
        "snip:": "Screen Intelligence: Region Capture & OCR",
        "mirror:": "Android Phone Mirroring & Controls",
        "phone:": "Android Phone Mirroring & Controls",
        "text:": "Quick Text Message (WhatsApp Desktop / Web)",
        "f:": "Search Files and Folders",
        "pdf:": "Search PDF Documents",
        "doc:": "Search Documents and Notes",
        "folder:": "Search Folders and Directories",
        "open:": "Open Application / File",
        "rem:": "Natural-Language Reminders & Schedule",
        "down:": "Search Downloads and Activity History",
        "act:": "Living System Activities & Tasks",
        "g:": "Search Google",
        "calc:": "Calculator and Math",
        "clip:": "Clipboard History and Paste",
        "note:": "Quick Notes and Tasks",
        "convert:": "Unit and Currency Converter",
        "sys:": "System Power and Controls",
        "yt:": "Search YouTube",
        "gh:": "Search GitHub",
        "wiki:": "Search Wikipedia",
        "map:": "Search Google Maps",
        "r:": "Search Reddit",
        "time:": "World Clock and Timers",
        "color:": "Color Inspector and Picker",
        "cmd:": "Run System Command",
        "url:": "Open Website URL"
    }
}

def is_rook_installed() -> bool:
    """Check if Rook app is installed on the system."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        rook_exe = Path(local_app_data) / "Programs" / "Rook" / "Rook.exe"
        if rook_exe.exists():
            return True
    app_data = os.environ.get("APPDATA", "")
    if app_data:
        rook_dir = Path(app_data) / "Rook"
        if rook_dir.exists():
            return True
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Rook") as _:
                    return True
            except FileNotFoundError:
                pass
    except Exception:
        pass
    return False

def is_rook_running() -> bool:
    """Check if Rook process or mutex/socket is currently active."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.15)
        res = s.connect_ex(('127.0.0.1', 54321))
        s.close()
        if res == 0:
            return True
    except Exception:
        pass
    
    try:
        import ctypes
        # OpenMutexW with SYNCHRONIZE (0x00100000)
        mutex = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, "Local\\RookShortcutManagerSingleInstance")
        if mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)
            return True
    except Exception:
        pass
    return False


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                res = DEFAULT_SETTINGS.copy()
                res.update(data)
                # Remove settings left by the retired AutoPilot feature.
                for retired_key in ("enable_autopilot", "autopilot_cpu_threshold", "autopilot_ram_threshold"):
                    res.pop(retired_key, None)
                if str(res.get("theme", "")).lower() in ("frosted", "frosted_space", "dynamic", "auto", "adaptive", ""):
                    res["theme"] = "dark"
                if "hide_edge_bar" not in data:
                    res["hide_edge_bar"] = True
                if res.get("edge_notch_style") not in ("simple", "worded"):
                    res["edge_notch_style"] = "simple"
                if "ui_show_lens_button" not in data:
                    res["search_pill_action_button"] = "both"
                if "side_view" not in res or res.get("side_view") not in ("off", "left", "right"):
                    res["side_view"] = "off"
                if res.get("hotkey") in ("Alt+Space", "Ctrl+Space"):
                    res["hotkey"] = "Win+Alt"
                return res
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

_last_saved_startup = None

def save_settings(settings: dict, sync_startup: bool = False):
    global _last_saved_startup
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)
    if "run_on_startup" in settings:
        cur_startup = bool(settings["run_on_startup"])
        if sync_startup or (_last_saved_startup is not None and _last_saved_startup != cur_startup):
            _last_saved_startup = cur_startup
            import threading
            threading.Thread(target=set_startup_enabled, args=(cur_startup,), daemon=True).start()
        elif _last_saved_startup is None:
            _last_saved_startup = cur_startup

def set_startup_enabled(enable: bool):
    try:
        import winreg
        import sys
        app_name = "ODD"
        exe_path = sys.executable if getattr(sys, 'frozen', False) else str(Path(__file__).resolve().parent / "ODD.exe")
        
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        if enable:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Error setting startup registry: {e}")

    try:
        startup_dir = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))
        startup_lnk = startup_dir / "ODD.lnk"
        if enable:
            if not startup_lnk.exists():
                ps_script = f"""
                $WshShell = New-Object -comObject WScript.Shell
                $Shortcut = $WshShell.CreateShortcut("{startup_lnk}")
                $Shortcut.TargetPath = "{exe_path}"
                $Shortcut.WorkingDirectory = "{os.path.dirname(exe_path)}"
                $Shortcut.Save()
                """
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=False, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            if startup_lnk.exists():
                startup_lnk.unlink()
    except Exception as e:
        print(f"Error setting startup shortcut: {e}")
