import sys
import os
import math
import shutil
import subprocess
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF, Signal, QObject, QThread
from PySide6.QtGui import (
    QFont, QColor, QPainter, QBrush, QPen, QPixmap, QIcon,
    QPainterPath, QLinearGradient, QRadialGradient
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QProgressBar, QStackedWidget, QLineEdit,
    QFileDialog, QFrame
)
from odd_icons import get_vector_icon, get_vector_pixmap, get_checkbox_check_svg_path
try:
    from fluentapp.windoweffect import WindowBlur
except Exception:
    WindowBlur = None

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
    def isatty(self):
        return False
    def fileno(self):
        return -1
    def readable(self):
        return False
    def writable(self):
        return True
    def seekable(self):
        return False
    def __getattr__(self, name):
        if self.target is not None:
            return getattr(self.target, name)
        raise AttributeError(f"'SafeStream' object has no attribute '{name}'")

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

def get_resource_dir() -> Path:
    """Returns directory of bundled resources (handles PyInstaller onefile temp dir)"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def get_installer_exe_path() -> Path:
    """Returns path to the running installer executable"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable)
    return Path(__file__).resolve().parent / "ODD_Setup.exe"

def get_detected_install_dir(is_uninstaller: bool = False) -> Path:
    """Detects current installation directory if running directly as uninstaller"""
    default_loc = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\ODD"))
    if is_uninstaller and getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / "ODD.exe").exists() and not (exe_dir / "main.py").exists() and not (exe_dir / "installer.py").exists():
            return exe_dir
    return default_loc

def kill_running_odd_instances():
    """Safely terminate running instances of ODD.exe and orphaned python main.py without terminating the installer or uninstaller."""
    my_pid = os.getpid()
    try:
        subprocess.run(
            ["taskkill", "/F", "/FI", f"PID ne {my_pid}", "/IM", "ODD.exe"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )
    except Exception:
        pass

    try:
        ps_cmd = f"Get-Process -Name 'ODD' -ErrorAction SilentlyContinue | Where-Object {{ $_.Id -ne {my_pid} -and $_.ProcessName -eq 'ODD' }} | Stop-Process -Force"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    except Exception:
        pass

    try:
        ps_py_cmd = f"Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {{ $_.ProcessId -ne {my_pid} -and $_.CommandLine -like '*main.py*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_py_cmd], creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    except Exception:
        pass

def safe_copy_file(src: Path, dst: Path, max_attempts: int = 5) -> bool:
    """Safely copy file to dst, handling locks, permissions, and same-file cases."""
    try:
        if src.resolve() == dst.resolve():
            return True
    except Exception:
        pass

    dst.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(max_attempts):
        try:
            if dst.exists():
                try:
                    os.chmod(dst, 0o777)
                except Exception:
                    pass
            shutil.copy2(src, dst)
            return True
        except PermissionError:
            kill_running_odd_instances()
            if attempt >= 2 and dst.exists():
                try:
                    old_path = dst.with_suffix(f".old_{int(time.time())}_{attempt}")
                    dst.rename(old_path)
                    shutil.copy2(src, dst)
                    try:
                        old_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return True
                except Exception:
                    pass
        except shutil.SameFileError:
            return True
        except Exception as e:
            if attempt == max_attempts - 1:
                raise e
            time.sleep(0.3)
    return False

def create_windows_shortcut(target_exe: str, shortcut_path: str, icon_path: str = "", arguments: str = ""):
    """Create a Windows .lnk shortcut using PowerShell with literal strings"""
    try:
        Path(shortcut_path).parent.mkdir(parents=True, exist_ok=True)
        t_exe = str(target_exe).replace("'", "''")
        s_path = str(shortcut_path).replace("'", "''")
        w_dir = str(os.path.dirname(target_exe)).replace("'", "''")
        i_path = str(icon_path).replace("'", "''") if icon_path else ""
        args = str(arguments).replace("'", "''") if arguments else ""

        ps_script = f"""
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{s_path}')
$Shortcut.TargetPath = '{t_exe}'
$Shortcut.WorkingDirectory = '{w_dir}'
if ('{args}' -ne '') {{
    $Shortcut.Arguments = '{args}'
}}
if ('{i_path}' -ne '' -and (Test-Path '{i_path}')) {{
    $Shortcut.IconLocation = '{i_path}'
}}
$Shortcut.Save()
"""
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        print(f"Error creating shortcut: {e}")

def add_startup_registry(app_name: str, exe_path: str):
    """Add application to Windows Startup registry and Startup folder"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Error setting startup registry: {e}")

    try:
        startup_dir = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))
        if startup_dir.exists():
            startup_lnk = startup_dir / f"{app_name}.lnk"
            create_windows_shortcut(exe_path, str(startup_lnk))
    except Exception as e:
        print(f"Error setting startup shortcut: {e}")

def remove_startup_registry(app_name: str):
    """Remove application from Windows Startup registry and Startup folder"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, app_name)
        winreg.CloseKey(key)
    except Exception:
        pass

    try:
        startup_lnk = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")) / f"{app_name}.lnk"
        if startup_lnk.exists():
            startup_lnk.unlink()
    except Exception:
        pass

def register_windows_uninstaller(install_dir: Path, exe_path: Path):
    """Registers ODD in Windows Apps & Features / Programs & Features so it appears in Control Panel & Windows Settings"""
    try:
        import winreg
        uninst_key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ODD"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, uninst_key_path)
        
        uninst_exe = install_dir / "Uninstall ODD.exe"
        if not uninst_exe.exists():
            uninst_exe = install_dir / "ODD_Setup.exe"
            
        if uninst_exe.exists():
            uninst_cmd = f'"{uninst_exe}" --uninstall'
        else:
            uninst_cmd = f'"{install_dir}\\uninstall.bat"'
            
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "ODD Dynamic Island by Humnspace")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "5.1.0")
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Humnspace")
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f'"{install_dir}\\odd_logo.ico"')
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, f'"{install_dir}"')
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninst_cmd)
        winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, uninst_cmd)
        winreg.SetValueEx(key, "HelpLink", 0, winreg.REG_SZ, "https://humn.space/")
        winreg.SetValueEx(key, "URLInfoAbout", 0, winreg.REG_SZ, "https://humn.space/")
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, 54000)
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Error registering Windows uninstaller: {e}")

def unregister_windows_uninstaller():
    """Removes ODD from Windows Apps & Features"""
    try:
        import winreg
        uninst_key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ODD"
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, uninst_key_path)
    except Exception:
        pass

def draw_top_anchored_squircle(painter: QPainter, rect: QRectF, radius: float):
    """Draws a top-anchored continuous squircle path (flush top edge, rounded bottom corners)"""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    r = min(radius, h, w / 2.0)
    path = QPainterPath()
    path.moveTo(x, y)
    path.lineTo(x + w, y)
    path.lineTo(x + w, y + h - r)
    path.quadTo(x + w, y + h, x + w - r, y + h)
    path.lineTo(x + r, y + h)
    path.quadTo(x, y + h, x, y + h - r)
    path.lineTo(x, y)
    path.closeSubpath()
    painter.drawPath(path)
    return path


class DynamicIslandInstallerPreview(QWidget):
    """
    Next-generation living Dynamic Island preview widget for ODD Installer.
    Simulates:
    - Top monitor bezel with flush-anchored AMOLED notch.
    - Fluid downward morphing expansion when activated via Win+Alt.
    - Universal Search, Smart Clipboard, and Screen Intelligence preview.
    - Live Activities (Media playback with active equalizer bars).
    - Live installation progress HUD during active installation/uninstallation.
    """
    def __init__(self, mode="install_preview", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setFixedHeight(154)
        self.step = 0
        self.pulse = 0.0

        # Island animated coordinates
        self.island_w = 136.0
        self.island_h = 28.0
        self.state_name = "COMPACT"  # COMPACT, EXPANDED_SEARCH, LIVE_ACTIVITY, ACTIVE_HUD
        self.typed_text = ""
        self.char_idx = 0
        self.cursor_pos = QPoint(100, 120)
        self.show_results = False
        self.active_phase = "DEPLOYING CORE BINARIES"
        self.active_detail = "Writing AMOLED Dynamic Island runtime..."

        # Load logo
        self.logo_pix = None
        logo_path = get_resource_dir() / "odd_logo.png"
        if logo_path.exists():
            self.logo_pix = QPixmap(str(logo_path)).scaled(
                16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._on_tick)
        self.anim_timer.start(33)

    def set_mode(self, mode: str):
        self.mode = mode
        self.step = 0
        self.island_w = 136.0
        self.island_h = 28.0
        self.typed_text = ""
        self.char_idx = 0
        self.show_results = False

    def set_phase_info(self, phase: str, detail: str):
        self.active_phase = phase
        self.active_detail = detail
        self.update()

    def _on_tick(self):
        self.step += 1
        self.pulse += 0.12

        if self.mode == "install_preview":
            # Cycle length: 190 ticks (~6.2 seconds)
            cycle = self.step % 190

            if cycle < 32:
                # 1. Compact resting notch state
                self.state_name = "COMPACT"
                self.show_results = False
                self.island_w += (136.0 - self.island_w) * 0.25
                self.island_h += (28.0 - self.island_h) * 0.25
                self.typed_text = ""
                self.char_idx = 0
                target_cursor = QPoint(self.width() // 2, 22)
                self.cursor_pos.setX(int(self.cursor_pos.x() + (target_cursor.x() - self.cursor_pos.x()) * 0.15))
                self.cursor_pos.setY(int(self.cursor_pos.y() + (target_cursor.y() - self.cursor_pos.y()) * 0.15))

            elif 32 <= cycle < 58:
                # 2. Smooth downward expansion into Universal Search Island
                self.state_name = "EXPANDED_SEARCH"
                self.island_w += (360.0 - self.island_w) * 0.28
                self.island_h += (108.0 - self.island_h) * 0.26
                self.cursor_pos.setY(int(self.cursor_pos.y() + (125 - self.cursor_pos.y()) * 0.15))

            elif 58 <= cycle < 98:
                # 3. Typing query character-by-character
                self.state_name = "EXPANDED_SEARCH"
                self.island_w = 360.0
                self.island_h = 108.0
                target_q = "Win+Alt: notion & notes"
                if cycle % 2 == 0 and self.char_idx < len(target_q):
                    self.char_idx += 1
                    self.typed_text = target_q[:self.char_idx]
                if self.char_idx >= len(target_q) - 4:
                    self.show_results = True

            elif 98 <= cycle < 140:
                # 4. Contextual Live Activity morph (Media player with active equalizers)
                self.state_name = "LIVE_ACTIVITY"
                self.show_results = False
                self.island_w += (280.0 - self.island_w) * 0.28
                self.island_h += (38.0 - self.island_h) * 0.28

            elif 140 <= cycle < 170:
                # 5. Retract cleanly back to top notch
                self.state_name = "COMPACT"
                self.island_w += (136.0 - self.island_w) * 0.26
                self.island_h += (28.0 - self.island_h) * 0.26

            elif cycle >= 170:
                self.cursor_pos = QPoint(80, 128)

        elif self.mode == "uninstall_preview":
            cycle = self.step % 170
            if cycle < 30:
                self.state_name = "COMPACT"
                self.show_results = False
                self.island_w += (136.0 - self.island_w) * 0.25
                self.island_h += (28.0 - self.island_h) * 0.25
                self.typed_text = ""
                self.char_idx = 0
            elif 30 <= cycle < 60:
                self.state_name = "EXPANDED_SEARCH"
                self.island_w += (330.0 - self.island_w) * 0.28
                self.island_h += (98.0 - self.island_h) * 0.26
            elif 60 <= cycle < 100:
                self.state_name = "EXPANDED_SEARCH"
                target_q = "odd: remove & cleanup"
                if cycle % 2 == 0 and self.char_idx < len(target_q):
                    self.char_idx += 1
                    self.typed_text = target_q[:self.char_idx]
                self.show_results = True
            elif 100 <= cycle < 140:
                self.show_results = False
                self.island_w += (136.0 - self.island_w) * 0.26
                self.island_h += (28.0 - self.island_h) * 0.26
            else:
                self.state_name = "COMPACT"

        elif self.mode in ("install_active", "uninstall_active"):
            self.state_name = "ACTIVE_HUD"
            self.island_w += (370.0 - self.island_w) * 0.22
            self.island_h += (80.0 - self.island_h) * 0.22

            phases = [
                ("DEPLOYING CORE RUNTIME", "Writing AMOLED island binaries & native hit-test hooks"),
                ("CONFIGURING HIT-TESTING", "Calibrating WM_NCHITTEST zero-interference geometry"),
                ("BINDING WIN+ALT HOTKEY", "Registering global low-latency desktop shortcut"),
                ("ACTIVATING EDGE SENSORS", "Initializing screen bezel sensors and smart clipboard")
            ] if self.mode == "install_active" else [
                ("TERMINATING PROCESSES", "Releasing native window and background hooks"),
                ("REMOVING SYSTEM HOOKS", "Unregistering Win+Alt and edge trigger sensors"),
                ("CLEANING SHORTCUTS", "Removing desktop icons and Windows registry entries")
            ]
            p_idx = (self.step // 45) % len(phases)
            self.active_phase, self.active_detail = phases[p_idx]

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w = self.width()
        h = self.height()

        # 1. Desktop Screen Simulator Canvas
        canvas_rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
        
        # Subtle dark metallic background gradient
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(14, 16, 22))
        grad.setColorAt(1.0, QColor(9, 10, 14))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(36, 40, 52), 1.0))
        painter.drawRoundedRect(canvas_rect, 10.0, 10.0)

        # 2. Top Screen Bezel bar (physical monitor top edge)
        bezel_rect = QRectF(2.0, 2.0, w - 4.0, 4.0)
        painter.setBrush(QBrush(QColor(22, 24, 30)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bezel_rect, 2.0, 2.0)

        # 3. Screen Edge Touch Sensor Indicator (Subtle white line along center top)
        if self.state_name == "COMPACT":
            sensor_line = QRectF(w / 2.0 - 32.0, 2.0, 64.0, 2.0)
            painter.setBrush(QBrush(QColor(255, 255, 255, 90)))
            painter.drawRoundedRect(sensor_line, 1.0, 1.0)

        # 4. Render Dynamic Island (Top-Anchored Superellipse)
        iw = float(self.island_w)
        ih = float(self.island_h)
        ix = (w - iw) / 2.0
        iy = 3.0  # Anchored flush to the top bezel

        island_rect = QRectF(ix, iy, iw, ih)
        radius = min(17.0, ih / 2.0)

        # Subtle ambient halo under the island
        if self.state_name in ("EXPANDED_SEARCH", "ACTIVE_HUD", "LIVE_ACTIVITY"):
            halo_rect = QRectF(ix - 12.0, iy, iw + 24.0, ih + 16.0)
            halo_grad = QRadialGradient(w / 2.0, iy + ih / 2.0, iw / 1.6)
            if self.mode == "uninstall_active":
                halo_grad.setColorAt(0.0, QColor(239, 68, 68, 30))
            else:
                halo_grad.setColorAt(0.0, QColor(34, 197, 94, 25))
            halo_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(halo_grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(halo_rect, 22.0, 22.0)

        # AMOLED Black Solid Fill (#040507) with crisp perimeter stroke (#2A2E3B)
        painter.setBrush(QBrush(QColor(4, 5, 7)))
        painter.setPen(QPen(QColor(42, 46, 58), 1.0))
        draw_top_anchored_squircle(painter, island_rect, radius)

        # Render Content depending on state
        if self.state_name == "COMPACT":
            # Compact Notch Content: Logo on left, live indicator in center, minimal brand on right
            if self.logo_pix and not self.logo_pix.isNull():
                painter.drawPixmap(int(ix + 12.0), int(iy + (ih - 16.0) / 2.0), self.logo_pix)

            # Center subtle pulsing emerald status dot
            dot_alpha = int(180 + 75 * math.sin(self.pulse))
            dot_color = QColor(34, 197, 94, dot_alpha)
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(int(ix + iw / 2.0), int(iy + ih / 2.0)), 3, 3)

            # Right side: Minimal indicator
            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
            painter.setPen(QColor(185, 185, 192))
            painter.drawText(QRectF(ix + iw - 48.0, iy, 38.0, ih), Qt.AlignmentFlag.AlignCenter, "ODD")

        elif self.state_name == "EXPANDED_SEARCH":
            # Level 2 Expanded Search Island
            top_bar_y = iy + 8.0
            if self.logo_pix and not self.logo_pix.isNull():
                painter.drawPixmap(int(ix + 12.0), int(top_bar_y + 1.0), self.logo_pix)

            # Search text input
            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
            painter.setPen(QColor(255, 255, 255) if self.typed_text else QColor(115, 115, 125))
            disp_text = self.typed_text if self.typed_text else "Win+Alt to search anything..."
            painter.drawText(int(ix + 34.0), int(top_bar_y + 14.0), disp_text)

            # Blinking cursor while typing
            if self.typed_text and (self.step // 12) % 2 == 0:
                text_metrics = painter.fontMetrics()
                cursor_x = int(ix + 35.0 + text_metrics.horizontalAdvance(disp_text))
                painter.setPen(QPen(QColor(34, 197, 94), 1.5))
                painter.drawLine(cursor_x, int(top_bar_y + 2.0), cursor_x, int(top_bar_y + 16.0))

            # Shortcut badge on right
            badge_rect = QRectF(ix + iw - 64.0, top_bar_y, 54.0, 18.0)
            painter.setBrush(QBrush(QColor(20, 22, 28)))
            painter.setPen(QPen(QColor(52, 56, 68), 1.0))
            painter.drawRoundedRect(badge_rect, 4.0, 4.0)
            painter.setFont(QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold))
            painter.setPen(QColor(200, 202, 210))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "Win + Alt")

            # Divider
            painter.setPen(QPen(QColor(32, 34, 42), 1.0))
            painter.drawLine(int(ix + 10.0), int(top_bar_y + 24.0), int(ix + iw - 10.0), int(top_bar_y + 24.0))

            # Result rows if showing
            if self.show_results:
                row_y = top_bar_y + 30.0
                # Row 1: App Result (Notion)
                r1_rect = QRectF(ix + 8.0, row_y, iw - 16.0, 22.0)
                painter.setBrush(QBrush(QColor(26, 28, 36)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(r1_rect, 5.0, 5.0)

                painter.setFont(QFont("Segoe UI Variable Display", 7, QFont.Weight.Bold))
                painter.setPen(QColor(34, 197, 94))
                painter.drawText(int(ix + 16.0), int(row_y + 15.0), "APP")

                painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(int(ix + 48.0), int(row_y + 15.0), "Notion — Workspace & Notes")

                # Row 2: Smart Clipboard Item
                row2_y = row_y + 24.0
                painter.setFont(QFont("Segoe UI Variable Display", 7, QFont.Weight.Bold))
                painter.setPen(QColor(160, 162, 172))
                painter.drawText(int(ix + 16.0), int(row2_y + 15.0), "CLIP")

                painter.setFont(QFont("Segoe UI Variable Text", 8))
                painter.setPen(QColor(210, 212, 220))
                painter.drawText(int(ix + 48.0), int(row2_y + 15.0), "https://humn.space/odd (pinned)")

        elif self.state_name == "LIVE_ACTIVITY":
            # Contextual Media Activity
            act_y = iy + (ih - 18.0) / 2.0
            # Music glyph
            painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
            painter.setPen(QColor(34, 197, 94))
            painter.drawText(int(ix + 12.0), int(act_y + 14.0), "♫")

            # Track title
            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
            painter.setPen(QColor(245, 245, 245))
            painter.drawText(int(ix + 30.0), int(act_y + 14.0), "Nothing OS — Neon Rain")

            # Live 5-bar Equalizer animation
            eq_x = ix + iw - 50.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(34, 197, 94)))
            for b in range(5):
                bh = 4.0 + 9.0 * (0.5 + 0.5 * math.sin(self.pulse * 1.6 + b * 1.1))
                bx = eq_x + b * 6.0
                by = iy + (ih - bh) / 2.0
                painter.drawRoundedRect(QRectF(bx, by, 3.5, bh), 1.5, 1.5)

        elif self.state_name == "ACTIVE_HUD":
            # Live Installer Progress HUD inside Dynamic Island
            top_y = iy + 10.0
            if self.logo_pix and not self.logo_pix.isNull():
                painter.drawPixmap(int(ix + 12.0), int(top_y + 1.0), self.logo_pix)

            painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(int(ix + 34.0), int(top_y + 14.0), "ODD DYNAMIC ISLAND")

            # Step tag
            tag_rect = QRectF(ix + iw - 86.0, top_y, 74.0, 18.0)
            painter.setBrush(QBrush(QColor(20, 22, 30)))
            painter.setPen(QPen(QColor(48, 52, 64), 1.0))
            painter.drawRoundedRect(tag_rect, 4.0, 4.0)
            painter.setFont(QFont("Segoe UI Variable Display", 7, QFont.Weight.Bold))
            painter.setPen(QColor(34, 197, 94) if self.mode == "install_active" else QColor(239, 68, 68))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, "LIVE ACTIVITY")

            # Phase line
            phase_y = top_y + 26.0
            painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
            painter.setPen(QColor(225, 227, 235))
            painter.drawText(int(ix + 14.0), int(phase_y + 13.0), self.active_phase)

            # Detail line
            painter.setFont(QFont("Segoe UI Variable Text", 8))
            painter.setPen(QColor(145, 148, 158))
            painter.drawText(int(ix + 14.0), int(phase_y + 27.0), self.active_detail)

            # Micro progress wave at bottom edge
            wave_y = iy + ih - 3.0
            wave_w = 46.0
            wave_x = ix + ((self.step * 4) % int(iw - wave_w))
            painter.setBrush(QBrush(QColor(34, 197, 94) if self.mode == "install_active" else QColor(239, 68, 68)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(wave_x, wave_y, wave_w, 2.0), 1.0, 1.0)

        # 5. Virtual Cursor for preview simulation
        if "preview" in self.mode and self.state_name == "COMPACT":
            cx = self.cursor_pos.x()
            cy = self.cursor_pos.y()
            painter.setBrush(QBrush(QColor(255, 255, 255, 235)))
            painter.setPen(QPen(QColor(0, 0, 0, 160), 1.0))
            cursor_path = QPainterPath()
            cursor_path.moveTo(cx, cy)
            cursor_path.lineTo(cx + 8, cy + 12)
            cursor_path.lineTo(cx + 4, cy + 12)
            cursor_path.lineTo(cx + 6, cy + 17)
            cursor_path.lineTo(cx + 4, cy + 18)
            cursor_path.lineTo(cx + 2, cy + 13)
            cursor_path.lineTo(cx, cy + 15)
            cursor_path.closeSubpath()
            painter.drawPath(cursor_path)


class InstallWorker(QThread):
    progress_changed = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, install_dir: Path, make_desktop: bool, make_start: bool, make_startup: bool):
        super().__init__()
        self.install_dir = install_dir
        self.make_desktop = make_desktop
        self.make_start = make_start
        self.make_startup = make_startup

    def run(self):
        try:
            self.progress_changed.emit(10, "Closing active instances of ODD...")
            kill_running_odd_instances()

            self.progress_changed.emit(25, "Creating destination directory...")
            self.install_dir.mkdir(parents=True, exist_ok=True)

            self.progress_changed.emit(45, "Deploying ODD Dynamic Island binaries...")
            res_dir = get_resource_dir()
            payload_bin = res_dir / "odd_payload.bin"
            local_bin = Path(__file__).resolve().parent / "odd_payload.bin"
            src_exe = res_dir / "ODD.exe"
            dst_exe = self.install_dir / "ODD.exe"
            local_exe = Path(__file__).resolve().parent / "ODD.exe"

            copied = False
            for bin_cand in [payload_bin, local_bin]:
                if bin_cand.exists() and bin_cand.stat().st_size > 1000000:
                    try:
                        import gzip
                        with gzip.open(str(bin_cand), 'rb') as f_in, open(str(dst_exe), 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out, length=4*1024*1024)
                        if dst_exe.exists() and dst_exe.stat().st_size > 1000000:
                            copied = True
                            break
                    except Exception:
                        try:
                            copied = safe_copy_file(bin_cand, dst_exe)
                            if copied:
                                break
                        except Exception:
                            pass

            if not copied:
                if src_exe.exists():
                    copied = safe_copy_file(src_exe, dst_exe)
                elif local_exe.exists():
                    copied = safe_copy_file(local_exe, dst_exe)

            if not copied:
                raise RuntimeError(
                    f"ODD.exe could not be copied to destination.\n"
                    f"Target: {dst_exe}\n"
                    f"Please verify permissions or close any processes using ODD.exe."
                )

            # Copy setup executable into install directory as Uninstall ODD.exe and ODD_Setup.exe
            inst_exe = get_installer_exe_path()
            for uninst_target in ["Uninstall ODD.exe", "ODD_Setup.exe"]:
                target_path = self.install_dir / uninst_target
                if inst_exe.exists():
                    try:
                        safe_copy_file(inst_exe, target_path)
                    except Exception:
                        pass

            for asset in ["odd_logo.png", "odd_logo.ico", "odd_logo_b64.txt"]:
                for search_base in [res_dir, Path(__file__).resolve().parent]:
                    src_asset = search_base / asset
                    if src_asset.exists():
                        try:
                            safe_copy_file(src_asset, self.install_dir / asset)
                        except Exception:
                            pass
                        break

            # Copy Icons8 assets directory
            for search_base in [res_dir, Path(__file__).resolve().parent]:
                src_icons_dir = search_base / "assets" / "icons"
                if src_icons_dir.exists() and src_icons_dir.is_dir():
                    dst_icons = self.install_dir / "assets" / "icons"
                    dst_icons.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copytree(src_icons_dir, dst_icons, dirs_exist_ok=True)
                    except Exception:
                        pass
                    break

            self.progress_changed.emit(65, "Registering Windows uninstaller and control panel entries...")
            uninst_script = self.install_dir / "uninstall.bat"
            with open(uninst_script, "w", encoding="utf-8") as f:
                f.write(f"""@echo off
if exist "%~dp0Uninstall ODD.exe" (
    start "" "%~dp0Uninstall ODD.exe" --uninstall
    exit /b
)
if exist "%~dp0ODD_Setup.exe" (
    start "" "%~dp0ODD_Setup.exe" --uninstall
    exit /b
)
taskkill /F /IM ODD.exe 2>nul
del /Q "%USERPROFILE%\\Desktop\\ODD.lnk" 2>nul
del /Q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\ODD.lnk" 2>nul
del /Q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Uninstall ODD.lnk" 2>nul
del /Q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\ODD.lnk" 2>nul
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "ODD" /f 2>nul
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\ODD" /f 2>nul
cd %TEMP%
rmdir /S /Q "{self.install_dir}" 2>nul
echo ODD has been uninstalled successfully.
""")

            register_windows_uninstaller(self.install_dir, dst_exe)

            self.progress_changed.emit(85, "Configuring Win+Alt shortcuts and startup hooks...")
            if self.make_desktop:
                desktop_lnk = Path.home() / "Desktop" / "ODD.lnk"
                create_windows_shortcut(str(dst_exe), str(desktop_lnk), str(self.install_dir / "odd_logo.ico"))

            if self.make_start:
                start_dir = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"))
                start_lnk = start_dir / "ODD.lnk"
                create_windows_shortcut(str(dst_exe), str(start_lnk), str(self.install_dir / "odd_logo.ico"))
                
                uninst_lnk = start_dir / "Uninstall ODD.lnk"
                uninst_exe = self.install_dir / "Uninstall ODD.exe"
                if not uninst_exe.exists():
                    uninst_exe = self.install_dir / "ODD_Setup.exe"
                    
                if uninst_exe.exists():
                    create_windows_shortcut(str(uninst_exe), str(uninst_lnk), str(self.install_dir / "odd_logo.ico"), arguments="--uninstall")
                else:
                    create_windows_shortcut(str(uninst_script), str(uninst_lnk), str(self.install_dir / "odd_logo.ico"))

            if self.make_startup:
                add_startup_registry("ODD", str(dst_exe))

            self.progress_changed.emit(100, "ODD Dynamic Island is live!")
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class UninstallWorker(QThread):
    progress_changed = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, install_dir: Path):
        super().__init__()
        self.install_dir = install_dir

    def run(self):
        try:
            self.progress_changed.emit(20, "Stopping active processes and dynamic island hooks...")
            kill_running_odd_instances()

            self.progress_changed.emit(45, "Removing Win+Alt shortcuts, startup entries & registration...")
            desktop_lnk = Path.home() / "Desktop" / "ODD.lnk"
            if desktop_lnk.exists():
                try: desktop_lnk.unlink()
                except Exception: pass

            start_dir = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"))
            for s_name in ["ODD.lnk", "Uninstall ODD.lnk"]:
                s_file = start_dir / s_name
                if s_file.exists():
                    try: s_file.unlink()
                    except Exception: pass

            remove_startup_registry("ODD")
            unregister_windows_uninstaller()
            time.sleep(0.4)

            self.progress_changed.emit(80, "Removing installed files and binaries...")
            is_dev_workspace = (self.install_dir / "main.py").exists() or (self.install_dir / ".git").exists()
            
            if self.install_dir.exists() and not is_dev_workspace:
                kill_running_odd_instances()
                time.sleep(0.4)
                for item in list(self.install_dir.iterdir()):
                    try:
                        if item.is_file() and not item.name.lower().startswith("uninstall"):
                            try:
                                item.unlink()
                            except Exception:
                                kill_running_odd_instances()
                                time.sleep(0.3)
                                item.unlink(missing_ok=True)
                        elif item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass
            time.sleep(0.3)

            self.progress_changed.emit(100, "ODD uninstalled successfully.")
            time.sleep(0.3)
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class OddInstaller(QWidget):
    """
    Next-Generation ODD Installer & Setup Experience.
    Features:
    - AMOLED curved window with subtle ambient lighting.
    - Living interactive Dynamic Island preview with smooth fluid morphing.
    - Feature highlight chips & modern glass cards.
    - Clear installation path selector and modern custom toggles.
    - Multi-stage visual progress tracker.
    - Tactile 3D shortcut keycaps and instant surface launch.
    """
    def __init__(self, is_uninstaller=False, is_update=False):
        super().__init__()
        self.is_uninstaller = is_uninstaller
        self.is_upgrade = is_update
        self.default_install_dir = get_detected_install_dir(is_uninstaller=self.is_uninstaller)
        self.worker = None
        self._drag_pos = None

        self.init_window()
        self.init_ui()
        if not is_update:
            self._update_upgrade_state()

    def init_window(self):
        self.setWindowTitle("ODD Uninstaller" if self.is_uninstaller else "ODD Setup — Dynamic Island")
        self.setFixedSize(540, 660)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        icon_path = get_resource_dir() / "odd_logo.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.pos().y() < 64:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(26, 20, 26, 18)
        main_layout.setSpacing(12)

        # ── TOP HEADER BAR ──
        header = QHBoxLayout()
        header.setSpacing(12)

        logo_frame = QFrame()
        logo_frame.setFixedSize(36, 36)
        logo_frame.setStyleSheet("""
            QFrame {
                background: #10121A;
                border: 1px solid #232736;
                border-radius: 10px;
            }
        """)
        lf_layout = QVBoxLayout(logo_frame)
        lf_layout.setContentsMargins(0, 0, 0, 0)
        lf_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo_lbl = QLabel()
        logo_path = get_resource_dir() / "odd_logo.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaled(
                22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            logo_lbl.setPixmap(pix)
        lf_layout.addWidget(logo_lbl)
        header.addWidget(logo_frame)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self.title_lbl = QLabel("ODD" if not self.is_uninstaller else "ODD UNINSTALLER")
        self.title_lbl.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet("color: #FFFFFF; letter-spacing: 0.8px;")
        title_row.addWidget(self.title_lbl)

        # Version Pill Badge
        self.ver_badge = QLabel("v5.1.0 · DYNAMIC ISLAND" if not self.is_uninstaller else "UNINSTALL")
        self.ver_badge.setStyleSheet("""
            QLabel {
                background: rgba(34, 197, 94, 0.12);
                color: #22C55E;
                border: 1px solid rgba(34, 197, 94, 0.30);
                border-radius: 9px;
                padding: 2px 8px;
                font-family: 'Segoe UI Variable Text';
                font-size: 8px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
        """)
        title_row.addWidget(self.ver_badge)
        title_row.addStretch()
        title_box.addLayout(title_row)

        sub_brand = QLabel("Dynamic Island for Windows · by Humnspace")
        sub_brand.setFont(QFont("Segoe UI Variable Text", 8))
        sub_brand.setStyleSheet("color: #727686;")
        title_box.addWidget(sub_brand)
        header.addLayout(title_box)

        header.addStretch()

        close_btn = QPushButton()
        close_btn.setIcon(get_vector_icon("close", "#8E92A4", 12, active_color="#FFFFFF"))
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #12141C;
                border: 1px solid #232634;
                border-radius: 14px;
                outline: none;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.22);
            }
        """)
        close_btn.clicked.connect(self._on_cancel_close)
        header.addWidget(close_btn)
        main_layout.addLayout(header)

        # ── STACKED PAGES ──
        self.stack = QStackedWidget(self)

        # ── PAGE 1: Welcome & Setup Configuration ──
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 2, 0, 0)
        l1.setSpacing(10)

        self.t1 = QLabel(
            "Next-Generation Desktop Interaction Layer" if not self.is_uninstaller else
            "Remove ODD from your PC"
        )
        self.t1.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        self.t1.setStyleSheet("color: #FFFFFF;")
        l1.addWidget(self.t1)

        self.sub1 = QLabel(
            "Top-anchored AMOLED island with zero-interference hit testing, universal search, smart clipboard, and live desktop activities."
            if not self.is_uninstaller else
            "Are you sure you want to remove ODD Dynamic Island and all registered components?"
        )
        self.sub1.setFont(QFont("Segoe UI Variable Text", 8))
        self.sub1.setStyleSheet("color: #9296A5; line-height: 1.35;")
        self.sub1.setWordWrap(True)
        l1.addWidget(self.sub1)

        if not self.is_uninstaller:
            # Feature Highlights Chips Strip
            chips_layout = QHBoxLayout()
            chips_layout.setSpacing(8)
            feature_chips = [
                ("⚡", "Win + Alt Search"),
                ("🎵", "Living Media Island"),
                ("📋", "Smart Clipboard")
            ]
            for icon_str, label_str in feature_chips:
                chip_frame = QFrame()
                chip_frame.setStyleSheet("""
                    QFrame {
                        background: #0D0F17;
                        border: 1px solid #1C202C;
                        border-radius: 6px;
                        padding: 3px 8px;
                    }
                """)
                chip_row = QHBoxLayout(chip_frame)
                chip_row.setContentsMargins(4, 2, 4, 2)
                chip_row.setSpacing(5)

                ic_lbl = QLabel(icon_str)
                ic_lbl.setFont(QFont("Segoe UI Variable Display", 8))
                chip_row.addWidget(ic_lbl)

                txt_lbl = QLabel(label_str)
                txt_lbl.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium))
                txt_lbl.setStyleSheet("color: #CCCCCC; border: none; background: transparent;")
                chip_row.addWidget(txt_lbl)
                chips_layout.addWidget(chip_frame)

            chips_layout.addStretch()
            l1.addLayout(chips_layout)

        # Living Dynamic Island Interactive Preview
        self.guide = DynamicIslandInstallerPreview(
            mode="install_preview" if not self.is_uninstaller else "uninstall_preview",
            parent=self
        )
        l1.addWidget(self.guide)

        if not self.is_uninstaller:
            # Destination Box Card
            dest_frame = QFrame()
            dest_frame.setStyleSheet("""
                QFrame {
                    background: #0D0F17;
                    border: 1px solid #1F2332;
                    border-radius: 10px;
                    padding: 8px 10px;
                }
            """)
            dest_layout = QVBoxLayout(dest_frame)
            dest_layout.setContentsMargins(6, 6, 6, 6)
            dest_layout.setSpacing(6)

            dest_header_row = QHBoxLayout()
            dest_title = QLabel("INSTALLATION DIRECTORY")
            dest_title.setFont(QFont("Segoe UI Variable Display", 7, QFont.Weight.Bold))
            dest_title.setStyleSheet("color: #727686; letter-spacing: 0.6px; border: none; background: transparent;")
            dest_header_row.addWidget(dest_title)
            dest_header_row.addStretch()
            dest_layout.addLayout(dest_header_row)

            dest_row = QHBoxLayout()
            dest_row.setSpacing(8)

            self.dest_input = QLineEdit(str(self.default_install_dir))
            self.dest_input.setFont(QFont("Segoe UI Variable Text", 8))
            self.dest_input.setStyleSheet("""
                QLineEdit {
                    background: #08090D;
                    color: #FFFFFF;
                    border: 1px solid #272B3B;
                    border-radius: 6px;
                    padding: 6px 10px;
                    outline: none;
                }
                QLineEdit:focus {
                    border: 1px solid #3B82F6;
                    background: #0A0B12;
                }
            """)
            self.dest_input.textChanged.connect(self._update_upgrade_state)
            dest_row.addWidget(self.dest_input)

            browse_btn = QPushButton("Browse...")
            browse_btn.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))
            browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            browse_btn.setStyleSheet("""
                QPushButton {
                    background: #171A24;
                    color: #E2E4EE;
                    border: 1px solid #2B3042;
                    border-radius: 6px;
                    padding: 6px 12px;
                    outline: none;
                }
                QPushButton:hover {
                    background: #232736;
                    color: #FFFFFF;
                    border-color: #3B425A;
                }
            """)
            browse_btn.clicked.connect(self._on_browse_dest)
            dest_row.addWidget(browse_btn)
            dest_layout.addLayout(dest_row)
            l1.addWidget(dest_frame)

            # Integration Options
            opt_layout = QVBoxLayout()
            opt_layout.setSpacing(6)

            self.chk_desktop = QCheckBox("Create Desktop Shortcut (Win + Alt Quick Access)")
            self.chk_desktop.setChecked(True)
            self.chk_start = QCheckBox("Register in Start Menu & Windows Settings")
            self.chk_start.setChecked(True)
            self.chk_boot = QCheckBox("Launch Dynamic Island automatically when Windows starts")
            self.chk_boot.setChecked(True)

            check_svg = get_checkbox_check_svg_path()
            for chk in [self.chk_desktop, self.chk_start, self.chk_boot]:
                chk.setFont(QFont("Segoe UI Variable Text", 8))
                chk.setStyleSheet(f"""
                    QCheckBox {{ color: #D0D2DE; spacing: 9px; outline: none; }}
                    QCheckBox::indicator {{
                        width: 16px;
                        height: 16px;
                        border-radius: 4px;
                        border: 1px solid #2C3042;
                        background: #0D0F16;
                    }}
                    QCheckBox::indicator:hover {{
                        border-color: #444A63;
                        background: #141722;
                    }}
                    QCheckBox::indicator:checked {{
                        background: #22C55E;
                        border: 1px solid #22C55E;
                        image: url({check_svg});
                    }}
                    QCheckBox::indicator:checked:hover {{
                        background: #16A34A;
                        border: 1px solid #16A34A;
                    }}
                """)
                opt_layout.addWidget(chk)

            l1.addLayout(opt_layout)
        else:
            uninst_frame = QFrame()
            uninst_frame.setStyleSheet("background: #0D0F17; border: 1px solid #232736; border-radius: 10px; padding: 10px;")
            uninst_box = QVBoxLayout(uninst_frame)
            uninst_box.setSpacing(4)
            uninst_title = QLabel("DIRECTORY TO REMOVE")
            uninst_title.setFont(QFont("Segoe UI Variable Display", 7, QFont.Weight.Bold))
            uninst_title.setStyleSheet("color: #727686; border: none;")
            uninst_box.addWidget(uninst_title)

            uninst_loc = QLabel(str(self.default_install_dir))
            uninst_loc.setFont(QFont("Segoe UI Variable Text", 8))
            uninst_loc.setStyleSheet("color: #E2E4EE; border: none;")
            uninst_box.addWidget(uninst_loc)
            l1.addWidget(uninst_frame)

        l1.addStretch()

        self.btn_install = QPushButton("Install ODD" if not self.is_uninstaller else "Uninstall ODD")
        self.btn_install.setFixedHeight(42)
        self.btn_install.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.Bold))
        self.btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install.setStyleSheet("""
            QPushButton {
                background: #FFFFFF;
                color: #050505;
                border: 1px solid #FFFFFF;
                border-radius: 10px;
                outline: none;
            }
            QPushButton:hover {
                background: #EDEDED;
                border-color: #EDEDED;
            }
        """)
        self.btn_install.clicked.connect(self.start_installation if not self.is_uninstaller else self.start_uninstallation)
        l1.addWidget(self.btn_install)

        self.stack.addWidget(p1)

        # ── PAGE 2: Modern Multi-Stage Progress Screen ──
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 4, 0, 4)
        l2.setSpacing(12)
        l2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.prog_title = QLabel("Deploying ODD Dynamic Island..." if not self.is_uninstaller else "Uninstalling ODD...")
        self.prog_title.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        self.prog_title.setStyleSheet("color: #FFFFFF;")
        l2.addWidget(self.prog_title, alignment=Qt.AlignmentFlag.AlignCenter)

        # Live Dynamic Island in Active HUD Mode
        self.progress_anim = DynamicIslandInstallerPreview(
            mode="install_active" if not self.is_uninstaller else "uninstall_active",
            parent=self
        )
        l2.addWidget(self.progress_anim)

        # Stage Progress Visual Indicators
        self.stage_box = QHBoxLayout()
        self.stage_box.setSpacing(8)
        self.stage_labels = []
        stages = [
            "1. Unpack Core",
            "2. Island Hooks",
            "3. Shortcuts"
        ] if not self.is_uninstaller else [
            "1. Stop Processes",
            "2. Unlink Hooks",
            "3. Clean Files"
        ]

        for s_text in stages:
            s_lbl = QLabel(s_text)
            s_lbl.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))
            s_lbl.setStyleSheet("""
                QLabel {
                    background: #0E1018;
                    color: #727686;
                    border: 1px solid #1E2232;
                    border-radius: 6px;
                    padding: 4px 10px;
                }
            """)
            s_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stage_labels.append(s_lbl)
            self.stage_box.addWidget(s_lbl)
        l2.addLayout(self.stage_box)

        prog_header = QHBoxLayout()
        self.status_lbl = QLabel("Preparing deployment...")
        self.status_lbl.setFont(QFont("Segoe UI Variable Text", 9))
        self.status_lbl.setStyleSheet("color: #9296A5;")
        prog_header.addWidget(self.status_lbl)
        prog_header.addStretch()

        self.percent_lbl = QLabel("0%")
        self.percent_lbl.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.Bold))
        self.percent_lbl.setStyleSheet("color: #FFFFFF;")
        prog_header.addWidget(self.percent_lbl)
        l2.addLayout(prog_header)

        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(8)
        self.prog_bar.setTextVisible(False)
        self.prog_bar.setStyleSheet("""
            QProgressBar {
                background-color: #12141D;
                border: 1px solid #232736;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #22C55E;
                border-radius: 3px;
            }
        """)
        l2.addWidget(self.prog_bar)

        self.stack.addWidget(p2)

        # ── PAGE 3: Finished / Success Screen ──
        p3 = QWidget()
        l3 = QVBoxLayout(p3)
        l3.setContentsMargins(10, 16, 10, 16)
        l3.setSpacing(14)
        l3.setAlignment(Qt.AlignmentFlag.AlignCenter)

        succ_icon = QLabel()
        succ_icon.setPixmap(get_vector_pixmap("check_circle", "#22C55E", 48))
        succ_icon.setFixedSize(48, 48)
        l3.addWidget(succ_icon, alignment=Qt.AlignmentFlag.AlignCenter)

        self.succ_title = QLabel("ODD Installed Successfully!" if not self.is_uninstaller else "ODD Uninstalled")
        self.succ_title.setFont(QFont("Segoe UI Variable Display", 15, QFont.Weight.Bold))
        self.succ_title.setStyleSheet("color: #FFFFFF;")
        l3.addWidget(self.succ_title, alignment=Qt.AlignmentFlag.AlignCenter)

        # Tactile 3D Keyboard Shortcut Reminder Card
        if not self.is_uninstaller:
            shortcut_card = QFrame()
            shortcut_card.setStyleSheet("""
                QFrame {
                    background: #0D0F17;
                    border: 1px solid #232736;
                    border-radius: 10px;
                    padding: 12px;
                }
            """)
            card_layout = QVBoxLayout(shortcut_card)
            card_layout.setSpacing(8)
            card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            badge_row = QHBoxLayout()
            badge_row.setSpacing(6)
            badge_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

            for key_str in ["Win", "+", "Alt"]:
                lbl = QLabel(key_str)
                if key_str == "+":
                    lbl.setStyleSheet("color: #727686; font-weight: bold; font-size: 12px;")
                else:
                    lbl.setStyleSheet("""
                        background: #181B26;
                        color: #FFFFFF;
                        border: 1px solid #363C52;
                        border-bottom: 2px solid #232736;
                        border-radius: 6px;
                        padding: 5px 12px;
                        font-family: 'Segoe UI Variable Text';
                        font-size: 11px;
                        font-weight: bold;
                    """)
                badge_row.addWidget(lbl)
            card_layout.addLayout(badge_row)

            card_hint = QLabel("Press Win + Alt anytime or shake your cursor to reveal the search & media island.")
            card_hint.setFont(QFont("Segoe UI Variable Text", 8))
            card_hint.setStyleSheet("color: #9296A5; border: none; background: transparent;")
            card_hint.setWordWrap(True)
            card_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(card_hint)
            l3.addWidget(shortcut_card)

        self.succ_desc = QLabel(
            "Universal Search · Smart Clipboard · Screen Intelligence · Live Media"
            if not self.is_uninstaller else
            "All ODD files, registry keys, and shortcuts have been cleanly removed."
        )
        self.succ_desc.setFont(QFont("Segoe UI Variable Text", 8))
        self.succ_desc.setStyleSheet("color: #727686;")
        self.succ_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l3.addWidget(self.succ_desc)

        l3.addSpacing(8)

        self.btn_launch = QPushButton("Launch ODD" if not self.is_uninstaller else "Close")
        self.btn_launch.setFixedHeight(42)
        self.btn_launch.setFixedWidth(210)
        self.btn_launch.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.Bold))
        self.btn_launch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_launch.setStyleSheet("""
            QPushButton {
                background: #FFFFFF;
                color: #050505;
                border: 1px solid #FFFFFF;
                border-radius: 10px;
                outline: none;
            }
            QPushButton:hover {
                background: #EDEDED;
            }
        """)
        self.btn_launch.clicked.connect(self._on_action_clicked)
        l3.addWidget(self.btn_launch, alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(p3)
        main_layout.addWidget(self.stack)

        # ── FOOTER BAR ──
        footer = QLabel("Designed & Engineered by Humnspace · https://humn.space/")
        footer.setFont(QFont("Segoe UI Variable Text", 7))
        footer.setStyleSheet("color: #4C5062;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(footer)

    def _update_upgrade_state(self):
        if self.is_uninstaller:
            return
        target_dir_str = self.dest_input.text().strip() if hasattr(self, 'dest_input') else ""
        target_dir = Path(target_dir_str) if target_dir_str else self.default_install_dir
        self.is_upgrade = ((target_dir / "ODD.exe").exists() and not (target_dir / "main.py").exists()) or \
                          ((self.default_install_dir / "ODD.exe").exists() and not (self.default_install_dir / "main.py").exists())

        if self.is_upgrade:
            self.title_lbl.setText("ODD UPGRADE")
            self.t1.setText("Upgrade to ODD Dynamic Island")
            self.sub1.setText("An existing installation of ODD was detected. Upgrade now to get the new top-anchored Dynamic Island, zero-friction media overlay, and smart clipboard while preserving all preferences.")
            self.btn_install.setText("Upgrade to ODD")
            self.btn_install.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #059669);
                    color: #FFFFFF;
                    border: 1px solid #10B981;
                    border-radius: 10px;
                    outline: none;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #16A34A, stop:1 #047857);
                    border-color: #16A34A;
                }
            """)
        else:
            self.title_lbl.setText("ODD")
            self.t1.setText("Next-Generation Desktop Interaction Layer")
            self.sub1.setText("Top-anchored AMOLED island with zero-interference hit testing, universal search, smart clipboard, and live desktop activities.")
            self.btn_install.setText("Install ODD")
            self.btn_install.setStyleSheet("""
                QPushButton {
                    background: #FFFFFF;
                    color: #050505;
                    border: 1px solid #FFFFFF;
                    border-radius: 10px;
                    outline: none;
                }
                QPushButton:hover {
                    background: #EDEDED;
                    border-color: #EDEDED;
                }
            """)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)

        # AMOLED Black Solid Surface with subtle top ambient glow
        bg_grad = QLinearGradient(0, 0, 0, self.height())
        bg_grad.setColorAt(0.0, QColor(12, 14, 20))
        bg_grad.setColorAt(1.0, QColor(6, 7, 9))

        painter.setBrush(QBrush(bg_grad))
        painter.setPen(QPen(QColor(36, 40, 52), 1.0))
        painter.drawRoundedRect(rect, 16.0, 16.0)

        # Specular light highlight along top rim
        spec_path = QPainterPath()
        spec_path.moveTo(rect.x() + 16.0, rect.y() + 1.0)
        spec_path.lineTo(rect.x() + rect.width() - 16.0, rect.y() + 1.0)
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1.0))
        painter.drawPath(spec_path)

    def _on_browse_dest(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select ODD Installation Directory", self.dest_input.text())
        if chosen:
            p = Path(chosen)
            if p.name.lower() != "odd":
                p = p / "ODD"
            self.dest_input.setText(str(p))

    def _on_cancel_close(self):
        self.close()

    def start_installation(self):
        target_dir_str = self.dest_input.text().strip()
        install_dir = Path(target_dir_str) if target_dir_str else self.default_install_dir
        self.install_dir = install_dir

        if self.is_upgrade:
            self.prog_title.setText("Upgrading to ODD Dynamic Island...")
        else:
            self.prog_title.setText("Deploying ODD Dynamic Island...")

        self.progress_anim.set_mode("install_active")
        self.stack.setCurrentIndex(1)
        self.worker = InstallWorker(
            self.install_dir,
            self.chk_desktop.isChecked(),
            self.chk_start.isChecked(),
            self.chk_boot.isChecked()
        )
        self.worker.progress_changed.connect(self._on_progress_update)
        self.worker.finished.connect(self._on_install_finished)
        self.worker.start()

    def start_uninstallation(self):
        self.prog_title.setText("Uninstalling ODD...")
        self.progress_anim.set_mode("uninstall_active")
        self.stack.setCurrentIndex(1)
        self.worker = UninstallWorker(self.default_install_dir)
        self.worker.progress_changed.connect(self._on_progress_update)
        self.worker.finished.connect(self._on_uninstall_finished)
        self.worker.start()

    def _on_progress_update(self, val: int, msg: str):
        self.prog_bar.setValue(val)
        self.percent_lbl.setText(f"{val}%")
        self.status_lbl.setText(msg)

        # Update stage badges
        if hasattr(self, 'stage_labels') and len(self.stage_labels) == 3:
            active_style = """
                QLabel {
                    background: rgba(34, 197, 94, 0.15);
                    color: #22C55E;
                    border: 1px solid rgba(34, 197, 94, 0.40);
                    border-radius: 6px;
                    padding: 4px 10px;
                }
            """
            done_style = """
                QLabel {
                    background: #10121A;
                    color: #22C55E;
                    border: 1px solid #1E2822;
                    border-radius: 6px;
                    padding: 4px 10px;
                }
            """
            pending_style = """
                QLabel {
                    background: #0E1018;
                    color: #727686;
                    border: 1px solid #1E2232;
                    border-radius: 6px;
                    padding: 4px 10px;
                }
            """

            if val < 35:
                self.stage_labels[0].setStyleSheet(active_style)
                self.stage_labels[1].setStyleSheet(pending_style)
                self.stage_labels[2].setStyleSheet(pending_style)
            elif val < 75:
                self.stage_labels[0].setStyleSheet(done_style)
                self.stage_labels[1].setStyleSheet(active_style)
                self.stage_labels[2].setStyleSheet(pending_style)
            else:
                self.stage_labels[0].setStyleSheet(done_style)
                self.stage_labels[1].setStyleSheet(done_style)
                self.stage_labels[2].setStyleSheet(active_style if val < 100 else done_style)

    def _on_install_finished(self, success: bool, err_msg: str):
        if success:
            if hasattr(self, 'btn_retry'):
                self.btn_retry.hide()
            if self.is_upgrade:
                self.succ_title.setText("ODD Upgraded Successfully!")
                self.btn_launch.setText("Launch ODD")
            else:
                self.succ_title.setText("ODD Installed Successfully!")
                self.btn_launch.setText("Launch ODD")
            self.stack.setCurrentIndex(2)
        else:
            self.status_lbl.setText(f"Error: {err_msg}")
            self.status_lbl.setStyleSheet("color: #EF4444; font-weight: bold;")
            self.prog_title.setText("Installation Failed")
            self.prog_title.setStyleSheet("color: #EF4444;")
            if not hasattr(self, 'btn_retry'):
                self.btn_retry = QPushButton("Retry Installation")
                self.btn_retry.setFixedHeight(36)
                self.btn_retry.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.Bold))
                self.btn_retry.setCursor(Qt.CursorShape.PointingHandCursor)
                self.btn_retry.setStyleSheet("""
                    QPushButton {
                        background: #EF4444;
                        color: #FFFFFF;
                        border-radius: 8px;
                        padding: 6px 16px;
                        outline: none;
                    }
                    QPushButton:hover {
                        background: #DC2626;
                    }
                """)
                self.btn_retry.clicked.connect(self._on_retry_install)
                self.stack.widget(1).layout().addWidget(self.btn_retry)
            else:
                self.btn_retry.show()

    def _on_retry_install(self):
        if hasattr(self, 'btn_retry'):
            self.btn_retry.hide()
        self.prog_title.setText("Deploying ODD Dynamic Island...")
        self.prog_title.setStyleSheet("color: #FFFFFF;")
        self.status_lbl.setStyleSheet("color: #9296A5;")
        self.start_installation()

    def _on_uninstall_finished(self, success: bool, err_msg: str):
        if success:
            self.succ_title.setText("ODD Uninstalled")
            self.stack.setCurrentIndex(2)
        else:
            self.status_lbl.setText(f"Error: {err_msg}")
            self.status_lbl.setStyleSheet("color: #EF4444;")

    def _on_action_clicked(self):
        if not self.is_uninstaller:
            dst_exe = getattr(self, "install_dir", self.default_install_dir) / "ODD.exe"
            if dst_exe.exists():
                subprocess.Popen([str(dst_exe), "--surface"], cwd=str(dst_exe.parent))
            self.close()
        else:
            target_dir = self.default_install_dir
            is_dev = (target_dir / "main.py").exists() or (target_dir / ".git").exists()
            if not is_dev:
                cmd = f'Start-Sleep -Seconds 1; Remove-Item -Path "{target_dir}" -Recurse -Force -ErrorAction SilentlyContinue'
                subprocess.Popen(["powershell", "-NoProfile", "-Command", cmd], creationflags=subprocess.CREATE_NO_WINDOW)
            self.close()

def main():
    app = QApplication(sys.argv)
    exe_stem = Path(sys.argv[0]).stem.lower()
    is_uninst = ("--uninstall" in sys.argv) or ("uninstall" in exe_stem)
    is_update = ("--update" in sys.argv) or ("--upgrade" in sys.argv)
    inst = OddInstaller(is_uninstaller=is_uninst, is_update=is_update)
    inst.show()
    if is_update:
        QTimer.singleShot(150, inst.start_installation)
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
