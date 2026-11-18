import re
import difflib
try:
    import rapidfuzz
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except Exception:
    _HAS_RAPIDFUZZ = False

import sys
import webbrowser
import urllib.parse
import subprocess
import threading
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize, QRect, QRectF, QPoint, QPointF, QPropertyAnimation, QEasingCurve, Property, QEvent, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QIcon, QPixmap, QPainterPath, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QWidget, QSlider, QCheckBox, QComboBox, QListView, QAbstractItemView,
    QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFrame, QListWidget,
    QListWidgetItem, QStackedWidget, QColorDialog, QScrollArea,
    QProgressBar, QSizePolicy, QKeySequenceEdit, QSpinBox
)
from odd_settings import save_settings, set_startup_enabled, is_rook_installed, is_rook_running, DEFAULT_SETTINGS
from odd_icons import get_vector_icon, get_vector_pixmap, get_checkbox_check_svg_path, get_combo_arrow_svg_path
from odd_updater import UpdateManager, CURRENT_VERSION, WEBSITE_URL, ReleaseInfo
import odd_sound
from fluentapp.windoweffect import WindowBlur


def get_resource_path(filename: str) -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / filename
    return Path(__file__).resolve().parent / filename


def get_odd_logo_pixmap(size=(32, 32), theme="dark") -> QPixmap:
    """Returns official ODD logo pixmap, automatically using odd_logo_black.png for light theme or odd_logo.png for dark/oled theme."""
    is_light = (str(theme).lower() == "light")
    target_name = "odd_logo_black.png" if is_light else "odd_logo.png"
    png_path = get_resource_path(target_name)
    if not png_path.exists():
        png_path = Path(__file__).resolve().parent / target_name
    if not png_path.exists():
        png_path = get_resource_path("odd_logo.png")
        if not png_path.exists():
            png_path = Path(__file__).resolve().parent / "odd_logo.png"

    if not png_path.exists():
        return QPixmap()

    src = QPixmap(str(png_path)).scaled(
        size[0], size[1],
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )
    return src


class ToggleSwitch(QCheckBox):
    """
    Skeuomorphic pill toggle switch based on Uiverse/Nicolas Jesenberger (friendly-otter-40).
    Aspect ratio 292 / 142.
    Smooth animated slide transition (.4s-.6s) between OFF and ON states.
    - Background: inactive color (#d3d3d6 in light, #333438 in dark) -> active color (#1868e3)
    - ON icon (I) on the left (x=65, y=39, w=12, h=64, rx=6)
    - OFF icon (O) on the right (cx=221, cy=71, r=26, stroke=12)
    - Sliding white knob (cx=71 -> 221, r=57) with soft tactile depth
    """
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setFixedSize(45, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme = "dark"
        self._progress = 1.0 if self.isChecked() else 0.0
        self._target_progress = self._progress

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self.toggled.connect(self._on_toggled)

    def set_theme_mode(self, theme: str):
        self._theme = str(theme).lower()
        self.update()

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._target_progress = 1.0 if checked else 0.0
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _on_toggled(self, checked: bool):
        self._target_progress = 1.0 if checked else 0.0
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _on_anim_tick(self):
        diff = self._target_progress - self._progress
        if abs(diff) < 0.02:
            self._progress = self._target_progress
            self._anim_timer.stop()
        else:
            self._progress += diff * 0.26
        self.update()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if not self.isEnabled():
            painter.setOpacity(0.48)

        w = float(self.width())
        h = float(self.height())

        # Scale 292x142 viewBox to widget geometry
        painter.save()
        sx = w / 292.0
        sy = h / 142.0
        painter.scale(sx, sy)

        p = max(0.0, min(1.0, float(self._progress)))
        is_dark = (self._theme != "light")

        # Active & Inactive Colors from spec
        active_color = QColor("#1868e3")
        inactive_color = QColor("#333438") if is_dark else QColor("#d3d3d6")

        # Interpolate background color
        r_bg = int(inactive_color.red() + (active_color.red() - inactive_color.red()) * p)
        g_bg = int(inactive_color.green() + (active_color.green() - inactive_color.green()) * p)
        b_bg = int(inactive_color.blue() + (active_color.blue() - inactive_color.blue()) * p)
        bg_col = QColor(r_bg, g_bg, b_bg)

        # 1. Background Pill: viewBox (0, 0, 292, 142), rx = 71
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(0, 0, 292, 142), 71, 71)
        painter.fillPath(bg_path, QBrush(bg_col))

        # 2. Left "I" icon (.toggle-icon.on): x=65, y=39, w=12, h=64, rx=6
        # When off: inactive color (hidden). When on: white
        on_alpha = int(255 * p)
        if on_alpha > 5:
            icon_on_path = QPainterPath()
            icon_on_path.addRoundedRect(QRectF(65, 39, 12, 64), 6, 6)
            painter.fillPath(icon_on_path, QBrush(QColor(255, 255, 255, on_alpha)))

        # 3. Right "O" icon (.toggle-icon.off): ring at (221, 71), outer r=26, stroke=12
        # When off: #eaeaec / #50525a. When on: active color
        off_idle_col = QColor("#50525a") if is_dark else QColor("#eaeaec")
        r_off = int(off_idle_col.red() + (active_color.red() - off_idle_col.red()) * p)
        g_off = int(off_idle_col.green() + (active_color.green() - off_idle_col.green()) * p)
        b_off = int(off_idle_col.blue() + (active_color.blue() - off_idle_col.blue()) * p)
        off_icon_col = QColor(r_off, g_off, b_off)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(off_icon_col, 12.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(QPointF(221, 71), 26, 26)

        # 4. Sliding Knob (.toggle-circle-center): moves 150px (from x=71 to x=221)
        knob_cx = 71.0 + 150.0 * p
        knob_cy = 71.0
        knob_r = 57.0

        # Knob soft depth shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 42)))
        painter.drawEllipse(QPointF(knob_cx, knob_cy + 3.0), knob_r, knob_r)

        # Knob body (pure white)
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(QPointF(knob_cx, knob_cy), knob_r, knob_r)

        painter.restore()


def create_setting_card(parent=None) -> QFrame:
    """Helper creating a modern OS Settings style grouped card container."""
    card = QFrame(parent)
    card.setObjectName("SettingCard")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return card


def create_row_divider(parent=None) -> QFrame:
    """1px horizontal divider between aligned rows inside a SettingCard."""
    line = QFrame(parent)
    line.setObjectName("SettingDivider")
    line.setFixedHeight(1)
    line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return line


def create_styled_combobox(parent=None, width: int = 230) -> QComboBox:
    """Creates a QComboBox equipped with a custom QListView popup view for consistent styling."""
    combo = QComboBox(parent)
    list_view = QListView(combo)
    list_view.setObjectName("ComboPopup")
    combo.setView(list_view)
    combo.setFixedWidth(width)
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    return combo


class HomeCategoryCard(QFrame):
    """Clickable Settings Homepage card representing a major configuration category."""
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, icon_name: str, badge_text: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("HomeCategoryCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_name = icon_name
        self.setMinimumHeight(76)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        self.icon_box = QLabel()
        self.icon_box.setObjectName("HomeCardIconBox")
        self.icon_box.setFixedSize(40, 40)
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        text_col.setContentsMargins(0, 0, 0, 0)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("HomeCardTitle")
        self.lbl_title.setFont(QFont("Segoe UI Variable Text", 10.5, QFont.Weight.DemiBold))
        top_row.addWidget(self.lbl_title)

        if badge_text:
            self.lbl_badge = QLabel(badge_text)
            self.lbl_badge.setObjectName("HomeCardBadge")
            top_row.addWidget(self.lbl_badge)
        else:
            self.lbl_badge = None
        top_row.addStretch()
        text_col.addLayout(top_row)

        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setObjectName("HomeCardSub")
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setFont(QFont("Segoe UI Variable Text", 9))
        text_col.addWidget(self.lbl_sub)

        layout.addLayout(text_col, stretch=1)

        self.lbl_arrow = QLabel("›")
        self.lbl_arrow.setObjectName("HomeCardArrow")
        self.lbl_arrow.setFont(QFont("Segoe UI Variable Display", 16, QFont.Weight.DemiBold))
        self.lbl_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_arrow)

    def update_icon_theme(self, icon_color: str):
        pix = get_vector_pixmap(self.icon_name, icon_color, 20)
        self.icon_box.setPixmap(pix)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class GlobalShortcutSelector(QWidget):
    """Interactive custom shortcut selector with popular presets and key recorder."""
    hotkey_changed = Signal(str)

    def __init__(self, initial_hotkey: str = "Alt+Space", parent=None):
        super().__init__(parent)
        self.theme = "dark"
        self._block = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.combo = create_styled_combobox(width=165)
        self.presets = [
            ("Alt + Space (Default)", "Alt+Space"),
            ("Ctrl + Space", "Ctrl+Space"),
            ("Shift + Space", "Shift+Space"),
            ("Win + Space", "Win+Space"),
            ("Alt + O", "Alt+O"),
            ("Ctrl + Alt + Space", "Ctrl+Alt+Space"),
            ("Ctrl + Shift + Space", "Ctrl+Shift+Space"),
            ("F12", "F12"),
            ("Custom Shortcut...", "custom")
        ]
        for label, val in self.presets:
            self.combo.addItem(label, val)

        self.key_edit = QKeySequenceEdit()
        self.key_edit.setFixedWidth(135)
        self.key_edit.setFixedHeight(30)
        self.key_edit.setToolTip("Click and press your desired shortcut key combination")

        self.btn_reset = QPushButton("Default")
        self.btn_reset.setFixedHeight(30)
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.setToolTip("Reset shortcut to Alt + Space")
        self.btn_reset.clicked.connect(lambda: self.set_hotkey("Alt+Space"))

        layout.addWidget(self.combo)
        layout.addWidget(self.key_edit)
        layout.addWidget(self.btn_reset)

        self.set_hotkey(initial_hotkey)

        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.key_edit.keySequenceChanged.connect(self._on_key_edit_changed)

    def set_hotkey(self, hk_str: str):
        self._block = True
        try:
            hk_clean = (hk_str or "Alt+Space").strip()
            parts = [p.strip() for p in hk_clean.split('+') if p.strip()]
            norm = "+".join(parts) if parts else "Alt+Space"
            self.key_edit.setKeySequence(QKeySequence(norm))
            clean_cmp = norm.replace(" ", "").lower()
            matched = False
            for idx, (_, val) in enumerate(self.presets):
                if val.replace(" ", "").lower() == clean_cmp:
                    self.combo.setCurrentIndex(idx)
                    matched = True
                    break
            if not matched:
                self.combo.setCurrentIndex(len(self.presets) - 1)
        finally:
            self._block = False
        self.hotkey_changed.emit(self.get_hotkey_string())

    def _on_combo_changed(self, idx):
        if getattr(self, '_block', False):
            return
        val = self.combo.currentData()
        if val and val != "custom":
            self._block = True
            try:
                self.key_edit.setKeySequence(QKeySequence(val))
            finally:
                self._block = False
            self.hotkey_changed.emit(val)
        else:
            self.key_edit.setFocus()

    def _on_key_edit_changed(self, seq):
        if getattr(self, '_block', False):
            return
        hk_str = seq.toString().strip()
        if not hk_str:
            return
        self._block = True
        try:
            clean_cmp = hk_str.replace(" ", "").lower()
            matched = False
            for idx, (_, val) in enumerate(self.presets):
                if val.replace(" ", "").lower() == clean_cmp:
                    self.combo.setCurrentIndex(idx)
                    matched = True
                    break
            if not matched:
                self.combo.setCurrentIndex(len(self.presets) - 1)
        finally:
            self._block = False
        self.hotkey_changed.emit(hk_str)

    def get_hotkey_string(self) -> str:
        s = self.key_edit.keySequence().toString().strip()
        if not s:
            val = self.combo.currentData()
            if val and val != "custom":
                return val
            return "Alt+Space"
        return s

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = (theme == "light")
        bg = "rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.07)"
        border = "rgba(0, 0, 0, 0.14)" if is_light else "rgba(255, 255, 255, 0.16)"
        color = "#1E293B" if is_light else "#FFFFFF"
        self.key_edit.setStyleSheet(f"""
            QKeySequenceEdit {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                color: {color};
                font-size: 12px;
                font-weight: 500;
                padding: 2px 8px;
            }}
            QKeySequenceEdit:focus {{
                border: 1px solid {'#18181B' if is_light else '#D4D4D8'};
                background: {'#FFFFFF' if is_light else 'rgba(255, 255, 255, 0.12)'};
            }}
        """)
        btn_bg = "rgba(0, 0, 0, 0.04)" if is_light else "rgba(255, 255, 255, 0.06)"
        btn_border = "rgba(0, 0, 0, 0.12)" if is_light else "rgba(255, 255, 255, 0.14)"
        self.btn_reset.setStyleSheet(f"""
            QPushButton {{
                background: {btn_bg};
                border: 1px solid {btn_border};
                border-radius: 6px;
                color: {color};
                font-size: 11px;
                font-weight: 600;
                padding: 2px 10px;
            }}
            QPushButton:hover {{
                border: 1px solid {'#18181B' if is_light else '#D4D4D8'};
                color: {'#18181B' if is_light else '#FFFFFF'};
            }}
        """)


class EdgeBarPreviewWidget(QWidget):
    """Live interactive preview of the customized edge bar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        self.bar_color_hex = "#D4D4D8"
        self.bar_width = 140
        self.bar_thickness = 4
        self.bar_glow = False
        self.notch_style = "bar"
        self.notch_text = "ODD"
        self.color_mode = "theme"
        self.theme = "dark"

    def update_preview(self, color_mode, color_hex, width, thickness, glow, theme, notch_style="bar", notch_text="ODD"):
        self.color_mode = color_mode
        self.bar_color_hex = color_hex
        self.bar_width = width
        self.bar_thickness = thickness
        self.bar_glow = glow
        self.theme = theme
        self.notch_style = notch_style or "bar"
        self.notch_text = notch_text or "ODD"
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        bg = QColor("#181818") if self.theme != "light" else QColor(242, 244, 248)
        border_col = QColor(255, 255, 255, 28) if self.theme != "light" else QColor(0, 0, 0, 24)

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border_col, 1.0))
        painter.drawRoundedRect(rect, 8, 8)

        if self.color_mode in ("preset", "custom") and self.bar_color_hex:
            base_col = QColor(self.bar_color_hex)
            if not base_col.isValid():
                base_col = QColor("#D4D4D8")
            col = QColor(base_col.red(), base_col.green(), base_col.blue(), 240)
        else:
            col = QColor(255, 255, 255, 235) if self.theme != "light" else QColor(24, 24, 27, 235)

        pw = max(40, min(int(self.bar_width * 0.65), self.width() - 40))
        ph = max(4, min(int(self.bar_thickness * 1.0), 12))
        n_st = str(self.notch_style).lower()
        if n_st in ("worded", "text_static", "text_scroll"):
            ph = max(ph, 18)
            pw = max(pw, 92)

        px = (self.width() - pw) // 2
        py = 5
        pill_rect = QRect(px, py, pw, ph)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        painter.drawRoundedRect(pill_rect, max(2, ph // 2), max(2, ph // 2))

        cx = pill_rect.center().x()
        cy = pill_rect.center().y()
        fg_col = QColor(255, 255, 255, 240) if self.theme != "light" else QColor(30, 30, 30, 240)

        if n_st in ("worded", "text_static", "text_scroll"):
            painter.setFont(QFont("Segoe UI Variable Display", 6.5, QFont.Weight.Bold))
            painter.setPen(fg_col)
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, self.notch_text)

        painter.setPen(QColor(160, 168, 184) if self.theme != "light" else QColor(100, 108, 122))
        painter.setFont(QFont("Segoe UI Variable Text", 8.2))
        style_disp = "Worded Text" if n_st in ("worded", "text_static", "text_scroll") else "Simple Bar"
        painter.drawText(
            QRect(0, 24, self.width(), 26),
            Qt.AlignmentFlag.AlignCenter,
            f"Screen Notch: {style_disp} • {self.bar_width}px width • {self.bar_thickness}px height"
        )


NLP_INTENTS_MAP = {
    "Start ODD with Windows": ["startup", "boot", "start on login", "autostart", "open when pc turns on", "windows start", "background boot", "run at startup", "disable startup", "enable startup"],
    "Enable Sound Effects": ["sound", "mute", "unmute", "audio effects", "clicks", "beeps", "quiet", "silence", "fx", "audio feedback", "turn off sound", "turn on sound", "sound volume"],
    "Sound Profile": ["sound pack", "audio style", "droplet", "modern audio", "sound preset"],
    "Effect Volume": ["volume", "loudness", "sound slider", "volume level", "audio volume", "louder", "quieter", "softer", "sound percent"],
    "Music & Media Player Integration": ["music", "music player", "song", "media controls", "playback", "spotify", "apple music", "youtube music", "audio player", "album art", "track controls"],
    "Hover Overlay Mode": ["hover island", "mouse over music", "show media on hover"],
    "When Media is Paused": ["paused media", "minimal music", "media pill", "button only", "hide when paused"],
    "Rotating Vinyl Disc Animation": ["vinyl", "spinning record", "record animation", "disc", "music style"],
    "Active Visual Theme": ["dark mode", "light mode", "oled", "black", "color", "appearance", "dark theme", "light theme", "visual", "look", "night mode", "day mode"],
    "Overlay Opacity": ["transparency", "opacity", "transparent", "acrylic", "blur", "see through", "glass", "clear", "opaque"],
    "Animation Style": ["fluid spring", "instant", "snappy", "bounce", "animation speed", "easing"],
    "Screen Edge Placement": ["top", "bottom", "left", "right", "screen position", "dock position", "where island appears", "display edge"],
    "Screen Edge Trigger": ["trigger mode", "edge touch", "hover trigger", "click trigger", "how to open", "open odd", "hover top", "click notch"],
    "Edge Trigger Mode": ["trigger mode", "edge touch", "hover trigger", "click trigger", "how to open", "open odd", "hover top", "click notch"],
    "Activation Shortcut": ["shortcut", "hotkey", "alt+space", "keyboard shortcut", "change shortcut", "change alt space", "key combination", "activation key", "press key", "toggle key", "trigger key", "custom shortcut"],
    "Notch Color Mode": ["notch color", "accent color", "colored bar", "custom color", "preset color", "indicator color"],
    "Accent Swatches": ["swatches", "theme color", "accent picker"],
    "Notch Width": ["notch width", "bar length", "wide notch", "island width", "notch dimension", "bar size", "make notch smaller", "make notch bigger"],
    "Notch Thickness": ["notch thickness", "bar height", "notch size", "thickness", "how thick"],
    "Invisible Edge Notch": ["invisible notch", "hide notch", "remove top bar", "stealth notch", "ghost notch", "hide trigger"],
    "Enable Quick Text Sending": ["quick texting", "send text", "message", "whatsapp"],
    "Preferred Messaging App": ["whatsapp", "text", "message", "send message", "chat", "messaging provider", "texting", "whatsapp web", "whatsapp desktop"],
    "Enable Island Weather Widget": ["weather", "forecast", "temperature", "temp", "celsius", "fahrenheit", "degrees", "rain", "sunny", "cloudy", "island weather", "replace music with weather", "city", "location", "climate"],
    "Weather Location": ["city name", "weather city", "my location", "auto detect location", "weather town", "gps", "coordinates"],
    "Island Slot to Replace": ["replace music button", "replace lens", "replace quick settings", "weather slot", "put weather in island", "standalone weather"],
    "Temperature Unit": ["celsius", "fahrenheit", "c or f", "degrees c", "degrees f", "metric weather", "imperial weather"],
    "Overlay Button Display Mode": ["action buttons", "overlay buttons", "pill icons", "search buttons"],
    "Quick Settings Button": ["sliders button", "action center button", "quick toggle button", "volume brightness sliders"],
    "Music Player Button": ["waveform button", "music toggle button", "music icon in island"],
    "Google Lens Visual Search Button": ["google lens", "lens", "visual search", "search image", "image search", "reverse image search", "ocr", "extract text from screen", "scan", "take a screenshot", "screenshot", "screen snip"],
    "'+' Quick Commands Button": ["plus button", "help button", "commands guide button"],
    "Circular ODD Button": ["odd button", "satellite button", "settings button", "circular button", "logo button"],
    "Screen-Edge Notch Indicator": ["notch pill", "edge indicator", "island notch"],
    "Power & Quick Controls Strip": ["power strip", "quick controls", "power buttons"],
    "Calculator & Inline Math": ["calculator", "math", "calculate", "equations", "convert numbers"],
    "Unit & Currency Converter": ["currency", "units", "conversion", "usd", "eur", "convert km to miles"],
    "Clipboard History": ["clipboard", "history", "copy paste", "clips", "snippets"],
    "Quick Notes & Scratchpad": ["notes", "scratchpad", "notepad", "write note", "quick note"],
    "World Clock & Countdown Timers": ["clock", "timer", "stopwatch", "alarm", "countdown", "world clock", "time"],
    "Color Inspector & Palette Tool": ["color picker", "hex", "rgb", "color tool", "palette", "inspect color"],
    "System Power Commands": ["shutdown", "restart", "sleep", "lock pc", "hibernate", "power controls"],
    "Web Omnibox Shortcuts": ["web search", "browser omnibox", "search engine", "google", "bing", "duckduckgo"],
    "Web Search Fallbacks": ["search fallback", "web fallback", "browser fallback"],
    "Media Track & Live Waveform HUD": ["media hud", "track banner", "song notification", "waveform hud"],
    "Live Countdown Timer Ticker": ["timer ticker", "stopwatch ticker", "countdown hud"],
    "Natural-Language Island Reminders": ["reminders", "task alert", "remind me", "reminder banner"],
    "System Volume & Mute HUD": ["volume popup", "audio level banner", "island volume", "volume slider indicator"],
    "Battery & Power Charging HUD": ["battery level", "charging indicator", "battery popup", "power banner", "charger alert"],
    "Caps Lock Indicator HUD": ["caps lock", "num lock", "scroll lock", "key lock indicator", "caps alert", "lock banner"],
    "Copy & Paste Feedback Badges": ["copy badge", "paste badge", "clipboard feedback"],
    "Download Progress Ring": ["download", "download ring", "file progress", "download progress"],
    "Background Activity Memory": ["background activity", "activity monitor"],
    "Display System & App Notifications": ["notifications", "system alerts", "popups", "toast alerts", "notification banners", "windows notifications", "dnd", "do not disturb", "mute notifications", "silent mode", "stop alerts", "quiet hours", "suppress popups"],
    "Notification Auto-Hide Duration": ["how long notification stays", "notification time", "dismiss timer", "toast duration", "seconds notification"],
    "Custom Command Prefixes": ["hotkeys", "prefixes", "shortcuts", "bangs", "custom search command", "quick commands"],
    "Global Keyboard Shortcut": ["shortcut", "hotkey", "alt+space", "keyboard shortcut", "change shortcut", "change alt space", "key combination", "activation key", "press key", "toggle key", "trigger key", "custom shortcut"],
    "Check for Updates": ["update", "version", "upgrade", "new version", "check for updates", "changelog", "release notes", "install update"],
    "Send Feedback": ["feedback", "bug report", "feature request", "contact developer", "ideas", "suggestions"],
    "Maximized App Dwell Delay": ["chrome delay", "maximized delay", "closing tab", "tab delay", "full window delay", "avoid top trigger", "delay when maximized", "accidental hover"],
    "Enable Water Reminders": ["water", "hydration", "drink water", "water reminder", "hydrate", "drink reminder", "water overlay"],
    "Reminder Frequency": ["water frequency", "water interval", "how often water", "30 minutes", "45 minutes", "60 minutes"],
    "Working Hours Only": ["working hours", "office hours", "desk hours", "water schedule", "do not disturb after work"],
    "Active Hours Schedule": ["start time", "end time", "9 to 5", "water hours", "schedule water"],
    "Preview Water Alert": ["test water", "test hydration", "water preview", "sample water alert"],
    "Notch Indicator Style": ["notch style", "arrow notch", "hand notch", "head notch", "dot notch", "pulse notch", "text notch", "marquee", "scrolling text", "customize hover bar"],
    "Custom Notch Text": ["notch text", "edge text", "custom bar text", "marquee text", "odd text"],
    "Eye Rest (20-20-20 Rule)": ["eye rest", "20-20-20", "eyes", "vision", "eye strain", "headache", "look away", "screen break"],
    "Posture & Desk Stretch Alerts": ["posture", "stretch", "roll shoulders", "stand up", "desk stretch", "ergonomics", "back pain"],
    "Ventilation & Fresh Air Reminders": ["fresh air", "ventilation", "crack window", "carbon dioxide", "drowsiness", "step outside", "air freshness"],
    "Laptop Battery Longevity Alerts": ["battery health", "unplug charger", "plug in charger", "80% battery", "30% battery", "battery alert", "charger reminder", "extend battery life"],
    "Storage Purge & Cleanliness": ["storage purge", "empty trash", "recycle bin", "clean downloads", "free disk space", "ssd speed", "80% full disk"],
}

_STOP_WORDS = {
    'how', 'to', 'can', 'i', 'where', 'do', 'the', 'a', 'an', 'please', 'want', 'find', 'open',
    'go', 'show', 'me', 'setting', 'settings', 'for', 'about', 'is', 'there', 'you', 'my', 'in',
    'of', 'on', 'with', 'from', 'at', 'turn', 'set', 'make', 'change', 'switch', 'adjust'
}


class SettingHighlightOverlay(QWidget):
    """
    Non-intrusive 2-second glowing accent overlay that covers the target setting row.
    Smoothly pulses/fades after exactly 2 seconds.
    """
    def __init__(self, target_widget: QWidget, theme: str = "dark", duration: float = 2.0):
        super().__init__(target_widget)
        import time
        self.target = target_widget
        self.theme = theme
        self.duration = duration
        self.start_ts = time.perf_counter()
        self.alpha = 1.0

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setGeometry(0, 0, target_widget.width(), target_widget.height())

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._on_tick)
        self.target.installEventFilter(self)

    def start(self):
        self.show()
        self.raise_()
        self.timer.start()

    def eventFilter(self, watched, event):
        if watched == self.target and event.type() == QEvent.Type.Resize:
            self.setGeometry(0, 0, self.target.width(), self.target.height())
        return super().eventFilter(watched, event)

    def _on_tick(self):
        import time
        elapsed = time.perf_counter() - self.start_ts
        if elapsed >= self.duration:
            self.timer.stop()
            try:
                self.target.removeEventFilter(self)
            except Exception:
                pass
            self.hide()
            self.deleteLater()
            return

        # Hold bright for 1.4 seconds, then smoothly fade out over final 0.6s
        if elapsed <= 1.4:
            self.alpha = 1.0
        else:
            self.alpha = max(0.0, 1.0 - (elapsed - 1.4) / 0.6)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.theme == "light":
            accent = QColor("#FFFFFF")  # Clean Sky Blue
        else:
            accent = QColor("#FFFFFF")  # Bright Cyan Neon

        border_col = QColor(accent.red(), accent.green(), accent.blue(), int(255 * self.alpha))
        fill_col = QColor(accent.red(), accent.green(), accent.blue(), int(38 * self.alpha))

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border_col, 2.5))
        painter.setBrush(QBrush(fill_col))
        painter.drawRoundedRect(rect, 8, 8)


class SettingsSearchBar(QFrame):
    """
    Search bar with clean non-blocking typing, instant debounce query execution,
    and automatic full-page search results navigation in ODD Settings.
    """
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.setObjectName("SettingsSearchBarContainer")
        self.setFixedHeight(34)
        self.setMinimumWidth(260)
        self.setMaximumWidth(360)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(6)

        # Search vector icon
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(16, 16)
        layout.addWidget(self.icon_lbl)

        # Text input (no popup stealing focus!)
        self.input = QLineEdit()
        self.input.setObjectName("SettingsSearchInput")
        self.input.setPlaceholderText("Search here...")
        self.input.setFont(QFont("Segoe UI Variable Text", 9.2))
        self.input.textChanged.connect(self._on_text_changed)
        self.input.returnPressed.connect(self._on_return_pressed)
        layout.addWidget(self.input, stretch=1)

        # Clear '✕' button
        self.btn_clear = QPushButton("✕")
        self.btn_clear.setFixedSize(18, 18)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self.clear_search)
        self.btn_clear.hide()
        layout.addWidget(self.btn_clear)

        # Debounce timer: user types first, and after a brief natural pause (380ms),
        # it opens the results in the dedicated blank search results page
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(380)
        self._debounce_timer.timeout.connect(self._execute_search)

        self.input.installEventFilter(self)

    def set_theme_mode(self, theme: str):
        if theme == "light":
            self.setStyleSheet("""
                QFrame#SettingsSearchBarContainer {
                    background-color: #FFFFFF;
                    border: 1px solid #D4D4D8;
                    border-radius: 8px;
                }
                QLineEdit#SettingsSearchInput {
                    background: transparent;
                    border: none;
                    color: #18181B;
                }
            """)
            self.icon_lbl.setPixmap(get_vector_pixmap("lens", "#52525B", 14))
            self.btn_clear.setStyleSheet("""
                QPushButton { background: transparent; border: none; color: #71717A; font-size: 11px; font-weight: bold; }
                QPushButton:hover { color: #18181B; }
            """)
        else:
            self.setStyleSheet("""
                QFrame#SettingsSearchBarContainer {
                    background-color: #181818;
                    border: 1px solid #333333;
                    border-radius: 8px;
                }
                QLineEdit#SettingsSearchInput {
                    background: transparent;
                    border: none;
                    color: #FAFAFA;
                }
            """)
            self.icon_lbl.setPixmap(get_vector_pixmap("lens", "#A1A1AA", 14))
            self.btn_clear.setStyleSheet("""
                QPushButton { background: transparent; border: none; color: #A1A1AA; font-size: 11px; font-weight: bold; }
                QPushButton:hover { color: #FFFFFF; }
            """)

    def eventFilter(self, watched, event):
        if watched == self.input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.clear_search()
                return True
        return super().eventFilter(watched, event)

    def _on_text_changed(self, text: str):
        has_text = bool(text.strip())
        self.btn_clear.setVisible(has_text)
        if not has_text:
            if self._debounce_timer.isActive():
                self._debounce_timer.stop()
            self.dialog.close_search_view()
            return

        # Restart debounce timer on keystroke so typing is 100% smooth without interruptions
        self._debounce_timer.start(380)

    def _on_return_pressed(self):
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
        self._execute_search()

    def _execute_search(self):
        text = self.input.text().strip()
        if text:
            self.dialog.show_search_results(text)
        else:
            self.dialog.close_search_view()

    def clear_search(self):
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
        self.input.clear()
        self.dialog.close_search_view()
        self.input.setFocus()


class BottleOptionCard(QFrame):
    """
    Interactive visual bottle selector card for daily hydration target:
    - 1L: Small slim water bottle
    - 2L: Broader sports water bottle
    - 3L: Big broader hydro flask
    - 3+L: Water can / dispenser jug
    """
    clicked = Signal(str, float)

    def __init__(self, style_id: str, liters: float, title: str, subtitle: str, is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.style_id = style_id
        self.liters = liters
        self.title_text = title
        self.subtitle_text = subtitle
        self.is_selected = is_selected
        self.is_hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(114)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(120, 114)

    def set_selected(self, selected: bool):
        if self.is_selected != selected:
            self.is_selected = selected
            self.update()

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.style_id, self.liters)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            w = float(self.width())
            h = float(self.height())
            card_rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)

            # Background & border styling (pure monochrome)
            if self.is_selected:
                bg_col = QColor(255, 255, 255, 34)
                border_pen = QPen(QColor(255, 255, 255, 230), 1.8)
                fg_col = QColor(255, 255, 255, 255)
                sub_col = QColor(225, 230, 240)
            elif self.is_hovered:
                bg_col = QColor(255, 255, 255, 18)
                border_pen = QPen(QColor(255, 255, 255, 110), 1.2)
                fg_col = QColor(245, 245, 245)
                sub_col = QColor(170, 175, 185)
            else:
                bg_col = QColor(255, 255, 255, 10)
                border_pen = QPen(QColor(255, 255, 255, 38), 1.0)
                fg_col = QColor(220, 220, 220)
                sub_col = QColor(140, 145, 155)

            painter.setBrush(QBrush(bg_col))
            painter.setPen(border_pen)
            painter.drawRoundedRect(card_rect, 10.0, 10.0)

            # Draw Vector Bottle Art in upper region (cx = w / 2, cy = 28)
            cx = w / 2.0
            cy = 28.0
            painter.setBrush(Qt.BrushStyle.NoBrush)
            icon_pen = QPen(fg_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(icon_pen)

            if self.style_id == "small_1l":
                # 1L: Sleek, narrow slender bottle (width 12, height 28)
                painter.drawRoundedRect(QRectF(cx - 3.0, cy - 14.0, 6.0, 4.0), 1.0, 1.0)
                path = QPainterPath()
                path.moveTo(cx - 2.5, cy - 10.0)
                path.lineTo(cx - 2.5, cy - 7.0)
                path.lineTo(cx - 5.5, cy - 3.0)
                path.lineTo(cx - 5.5, cy + 12.0)
                path.quadTo(cx - 5.5, cy + 14.0, cx - 3.5, cy + 14.0)
                path.lineTo(cx + 3.5, cy + 14.0)
                path.quadTo(cx + 5.5, cy + 14.0, cx + 5.5, cy + 12.0)
                path.lineTo(cx + 5.5, cy - 3.0)
                path.lineTo(cx + 2.5, cy - 7.0)
                path.lineTo(cx + 2.5, cy - 10.0)
                path.closeSubpath()
                painter.drawPath(path)
                painter.drawLine(QPointF(cx - 4.0, cy + 6.0), QPointF(cx + 4.0, cy + 6.0))

            elif self.style_id == "broader_2l":
                # 2L: Broader sports / gym bottle (width 18, height 28)
                painter.drawRoundedRect(QRectF(cx - 4.0, cy - 14.0, 8.0, 4.0), 1.2, 1.2)
                path = QPainterPath()
                path.moveTo(cx - 3.5, cy - 10.0)
                path.lineTo(cx - 3.5, cy - 7.0)
                path.quadTo(cx - 9.0, cy - 3.0, cx - 9.0, cy + 1.0)
                path.lineTo(cx - 9.0, cy + 12.0)
                path.quadTo(cx - 9.0, cy + 14.0, cx - 7.0, cy + 14.0)
                path.lineTo(cx + 7.0, cy + 14.0)
                path.quadTo(cx + 9.0, cy + 14.0, cx + 9.0, cy + 12.0)
                path.lineTo(cx + 9.0, cy + 1.0)
                path.quadTo(cx + 9.0, cy - 3.0, cx + 3.5, cy - 7.0)
                path.lineTo(cx + 3.5, cy - 10.0)
                path.closeSubpath()
                painter.drawPath(path)
                painter.drawLine(QPointF(cx - 7.5, cy + 2.0), QPointF(cx + 7.5, cy + 2.0))
                painter.drawLine(QPointF(cx - 7.5, cy + 6.0), QPointF(cx + 7.5, cy + 6.0))

            elif self.style_id == "big_3l":
                # 3L: Big broader wide-mouth hydro flask (width 22, height 28)
                painter.drawRoundedRect(QRectF(cx - 6.0, cy - 13.0, 12.0, 4.0), 1.5, 1.5)
                painter.drawArc(QRectF(cx + 2.5, cy - 17.0, 6.0, 7.0), 0, 180 * 16)
                path = QPainterPath()
                path.moveTo(cx - 5.5, cy - 9.0)
                path.lineTo(cx - 11.0, cy - 4.0)
                path.lineTo(cx - 11.0, cy + 12.0)
                path.quadTo(cx - 11.0, cy + 14.0, cx - 9.0, cy + 14.0)
                path.lineTo(cx + 9.0, cy + 14.0)
                path.quadTo(cx + 11.0, cy + 14.0, cx + 11.0, cy + 12.0)
                path.lineTo(cx + 11.0, cy - 4.0)
                path.lineTo(cx + 5.5, cy - 9.0)
                path.closeSubpath()
                painter.drawPath(path)
                painter.drawLine(QPointF(cx - 8.0, cy - 1.0), QPointF(cx - 3.0, cy - 1.0))
                painter.drawLine(QPointF(cx - 8.0, cy + 4.0), QPointF(cx - 3.0, cy + 4.0))
                painter.drawLine(QPointF(cx - 8.0, cy + 9.0), QPointF(cx - 3.0, cy + 9.0))

            else: # "can_3plus"
                # 3+L: Office dispenser water can / jug (width 24, height 28)
                painter.drawRoundedRect(QRectF(cx - 4.0, cy - 14.0, 8.0, 3.5), 1.0, 1.0)
                path = QPainterPath()
                path.moveTo(cx - 3.5, cy - 10.5)
                path.lineTo(cx - 12.0, cy - 5.0)
                path.lineTo(cx - 12.0, cy + 12.0)
                path.quadTo(cx - 12.0, cy + 14.0, cx - 10.0, cy + 14.0)
                path.lineTo(cx + 10.0, cy + 14.0)
                path.quadTo(cx + 12.0, cy + 14.0, cx + 12.0, cy + 12.0)
                path.lineTo(cx + 12.0, cy - 5.0)
                path.lineTo(cx + 3.5, cy - 10.5)
                path.closeSubpath()
                painter.drawPath(path)
                handle = QPainterPath()
                handle.moveTo(cx + 12.0, cy - 2.0)
                handle.cubicTo(cx + 16.5, cy - 2.0, cx + 16.5, cy + 8.0, cx + 12.0, cy + 8.0)
                painter.strokePath(handle, icon_pen)
                painter.drawLine(QPointF(cx - 10.0, cy - 1.0), QPointF(cx + 10.0, cy - 1.0))
                painter.drawLine(QPointF(cx - 10.0, cy + 4.0), QPointF(cx + 10.0, cy + 4.0))
                painter.drawLine(QPointF(cx - 10.0, cy + 9.0), QPointF(cx + 10.0, cy + 9.0))

            # Typography
            font_title = QFont("Segoe UI Variable Display", 9.2, QFont.Weight.Bold)
            painter.setFont(font_title)
            painter.setPen(fg_col)
            painter.drawText(QRectF(4.0, 48.0, w - 8.0, 18.0), Qt.AlignmentFlag.AlignCenter, self.title_text)

            font_sub = QFont("Segoe UI Variable Display", 7.6, QFont.Weight.Normal)
            painter.setFont(font_sub)
            painter.setPen(sub_col)
            painter.drawText(QRectF(4.0, 68.0, w - 8.0, 16.0), Qt.AlignmentFlag.AlignCenter, self.subtitle_text)

            sips_text = f"~{int(round(self.liters / 0.25))} sips / day" if self.style_id != "can_3plus" else "16+ sips / day"
            font_hint = QFont("Segoe UI Variable Display", 6.8, QFont.Weight.DemiBold)
            painter.setFont(font_hint)
            painter.setPen(QColor(sub_col.red(), sub_col.green(), sub_col.blue(), 180))
            painter.drawText(QRectF(4.0, 87.0, w - 8.0, 16.0), Qt.AlignmentFlag.AlignCenter, sips_text)

            # Selected badge indicator (check mark in top right corner)
            if self.is_selected:
                painter.setBrush(QBrush(fg_col))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(w - 12.0, 12.0), 5.0, 5.0)
                painter.setPen(QPen(QColor(20, 20, 20), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawLine(QPointF(w - 14.2, 12.0), QPointF(w - 12.5, 13.8))
                painter.drawLine(QPointF(w - 12.5, 13.8), QPointF(w - 9.8, 10.2))
        finally:
            painter.end()


class BottleSelectorWidget(QWidget):
    """Horizontal container holding the 4 visual bottle option cards."""
    bottle_selected = Signal(str, float)

    def __init__(self, current_style="broader_2l", parent=None):
        super().__init__(parent)
        self.selected_style = current_style
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(122)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(10)

        self.cards = {}
        options = [
            ("small_1l", 1.0, "1 Liter", "Small Bottle"),
            ("broader_2l", 2.0, "2 Liters", "Broader Bottle"),
            ("big_3l", 3.0, "3 Liters", "Big Bottle"),
            ("can_3plus", 4.0, "3+ Liters", "Water Can"),
        ]
        for style_id, liters, title, sub in options:
            card = BottleOptionCard(style_id, liters, title, sub, is_selected=(style_id == current_style), parent=self)
            card.clicked.connect(self._on_card_clicked)
            layout.addWidget(card, 1)
            self.cards[style_id] = card

    def _on_card_clicked(self, style_id: str, liters: float):
        self.selected_style = style_id
        for sid, card in self.cards.items():
            card.set_selected(sid == style_id)
        self.bottle_selected.emit(style_id, liters)

    def set_current_style(self, style_id: str):
        self.selected_style = style_id
        for sid, card in self.cards.items():
            card.set_selected(sid == style_id)

    def set_style(self, style_id: str):
        self.set_current_style(style_id)

    def get_daily_liters(self) -> float:
        mapping = {"small_1l": 1.0, "broader_2l": 2.0, "big_3l": 3.0, "can_3plus": 4.0}
        return mapping.get(self.selected_style, 2.0)


class ModeSegmentedSelector(QWidget):
    """Pill-style segmented mode selector for 'Whenever you work' vs 'Within time'."""
    mode_changed = Signal(str)

    def __init__(self, current_mode="work", parent=None):
        super().__init__(parent)
        self.current_mode = current_mode
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_work = QPushButton("Whenever you work")
        self.btn_time = QPushButton("Within time")
        for b in (self.btn_work, self.btn_time):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(30)
            layout.addWidget(b)

        self.btn_work.clicked.connect(lambda: self._set_mode("work"))
        self.btn_time.clicked.connect(lambda: self._set_mode("time"))
        self._update_styles()

    def _set_mode(self, mode: str):
        if self.current_mode != mode:
            self.current_mode = mode
            self._update_styles()
            self.mode_changed.emit(mode)

    def _update_styles(self):
        sel_style = """
            QPushButton {
                background: rgba(255, 255, 255, 0.22);
                color: #FFFFFF;
                border: 1.5px solid rgba(255, 255, 255, 0.85);
                border-radius: 8px;
                padding: 4px 14px;
                font-size: 11px;
                font-weight: 600;
            }
        """
        unsel_style = """
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                color: #AAAAAA;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 4px 14px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.12);
                color: #EEEEEE;
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
        """
        self.btn_work.setStyleSheet(sel_style if self.current_mode == "work" else unsel_style)
        self.btn_time.setStyleSheet(sel_style if self.current_mode == "time" else unsel_style)

    def set_mode(self, mode: str):
        self.current_mode = mode
        self._update_styles()


# =========================================================================
# REACT BITS PRO APP-UI DESIGN BLOCKS
# 1. Onboarding 4: Use Case Picker with Option Tiles
# 2. Forms 11: Clean Card-Based Form Layout with Badges and Hairline Dividers
# 3. File Manager 2: Asset Grid with Type Filters and Instant Search
# 4. Notifications 3: Delivery Preferences with Quiet Hours Schedule
# 5. Integrations 1: Integration Marketplace Grid with Live Status Indicators
# =========================================================================

class UseCaseOptionTile(QFrame):
    """
    Onboarding 4 (React Bits Pro): Option tile with icon badge, title, 2-line description,
    and a radio/check selection indicator.
    """
    clicked = Signal(str)

    def __init__(self, key: str, title: str, subtitle: str, icon_name: str, badge_text: str = "", is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.key = key
        self.title_text = title
        self.subtitle_text = subtitle
        self.icon_name = icon_name
        self.badge_text = badge_text
        self.is_selected = is_selected
        self.setObjectName("UseCaseTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(86)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        # Icon box
        self.icon_box = QLabel()
        self.icon_box.setObjectName("UseCaseIconBox")
        self.icon_box.setFixedSize(38, 38)
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_box)

        # Text column
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("UseCaseTitle")
        self.lbl_title.setFont(QFont("Segoe UI Variable Text", 10.2, QFont.Weight.DemiBold))
        top_row.addWidget(self.lbl_title)

        if badge_text:
            self.lbl_badge = QLabel(badge_text)
            self.lbl_badge.setObjectName("UseCaseBadge")
            top_row.addWidget(self.lbl_badge)
        top_row.addStretch()
        text_col.addLayout(top_row)

        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setObjectName("UseCaseSub")
        self.lbl_sub.setFont(QFont("Segoe UI Variable Text", 8.8))
        self.lbl_sub.setWordWrap(True)
        text_col.addWidget(self.lbl_sub)

        layout.addLayout(text_col, stretch=1)

        # Radio selection indicator
        self.indicator = QLabel()
        self.indicator.setObjectName("UseCaseIndicator")
        self.indicator.setFixedSize(22, 22)
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.indicator)

        self.update_state(self.is_selected)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update_state(selected)

    def update_state(self, selected: bool):
        self.is_selected = selected
        theme = getattr(self.window(), "_current_applied_theme", "dark")
        is_light = (theme == "light")
        accent = "#18181B" if is_light else "#FFFFFF"
        active_border = "#27272A" if is_light else "#D4D4D8"
        bg_active = "rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.08)"
        bg_inactive = "#FFFFFF" if is_light else "#1C1C1F"
        border_inactive = "#E4E4E7" if is_light else "rgba(255, 255, 255, 0.08)"
        hover_border = "#71717A" if is_light else "#A1A1AA"

        if selected:
            self.setStyleSheet(f"""
                QFrame#UseCaseTile {{
                    background: {bg_active};
                    border: 1.5px solid {active_border};
                    border-radius: 10px;
                }}
            """)
            self.indicator.setText("●")
            self.indicator.setStyleSheet(f"color: {accent}; font-size: 14px; font-weight: bold;")
        else:
            self.setStyleSheet(f"""
                QFrame#UseCaseTile {{
                    background: {bg_inactive};
                    border: 1px solid {border_inactive};
                    border-radius: 10px;
                }}
                QFrame#UseCaseTile:hover {{
                    border: 1px solid {hover_border};
                }}
            """)
            self.indicator.setText("○")
            self.indicator.setStyleSheet(f"color: {'#A1A1AA' if not is_light else '#71717A'}; font-size: 14px;")

        col = accent if selected else ("#18181B" if is_light else "#FAFAFA")
        pix = get_vector_pixmap(self.icon_name, col, 20)
        self.icon_box.setPixmap(pix)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)


class UseCasePickerWidget(QWidget):
    """Onboarding 4: Grid of use-case presets"""
    preset_selected = Signal(str)

    def __init__(self, current_preset: str = "dynamic_island", parent=None):
        super().__init__(parent)
        self.current_preset = current_preset
        self.tiles = {}

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        definitions = [
            ("dynamic_island", "Dynamic Island & Notch", "Top-edge fluid morphing pill with live media vinyl, volume HUD, and quick settings.", "bell", "RECOMMENDED"),
            ("minimal_launcher", "Minimal Search Capsule", "Compact floating launcher, instant app and file search, keyboard-first workflow.", "desktop", "FAST"),
            ("productivity", "Productivity Hub", "All tools active: clipboard history, quick notes, calculations, and web prefixes.", "modules", "POWER"),
            ("media_companion", "Media Companion", "Expanded music overlay, audio spectrum equalizer, Spotify and media controls.", "music", "AUDIO"),
        ]

        for i, (k, title, desc, icon, badge) in enumerate(definitions):
            tile = UseCaseOptionTile(k, title, desc, icon, badge_text=badge, is_selected=(k == self.current_preset), parent=self)
            tile.clicked.connect(self._on_tile_clicked)
            self.tiles[k] = tile
            grid.addWidget(tile, i // 2, i % 2)

    def _on_tile_clicked(self, key: str):
        if self.current_preset != key:
            self.current_preset = key
            for k, tile in self.tiles.items():
                tile.set_selected(k == key)
            self.preset_selected.emit(key)

    def set_preset(self, key: str):
        self.current_preset = key
        for k, tile in self.tiles.items():
            tile.set_selected(k == key)


class Forms11Card(QFrame):
    """
    Forms 11 (React Bits Pro): Clean card container with header title,
    descriptive subtitle, category badge tag, structured form rows, and hairline dividers.
    """
    def __init__(self, title: str, subtitle: str = "", badge_text: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Forms11Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Header area
        self.header_frame = QFrame()
        self.header_frame.setObjectName("Forms11Header")
        h_layout = QHBoxLayout(self.header_frame)
        h_layout.setContentsMargins(16, 14, 16, 12)
        h_layout.setSpacing(10)

        t_col = QVBoxLayout()
        t_col.setContentsMargins(0, 0, 0, 0)
        t_col.setSpacing(2)

        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("Forms11Title")
        self.lbl_title.setFont(QFont("Segoe UI Variable Text", 10.5, QFont.Weight.DemiBold))
        t_col.addWidget(self.lbl_title)

        if subtitle:
            self.lbl_sub = QLabel(subtitle)
            self.lbl_sub.setObjectName("Forms11Sub")
            self.lbl_sub.setFont(QFont("Segoe UI Variable Text", 9))
            self.lbl_sub.setWordWrap(True)
            t_col.addWidget(self.lbl_sub)
        h_layout.addLayout(t_col, stretch=1)

        if badge_text:
            self.badge_lbl = QLabel(badge_text)
            self.badge_lbl.setObjectName("Forms11Badge")
            h_layout.addWidget(self.badge_lbl)

        self.main_layout.addWidget(self.header_frame)
        self.main_layout.addWidget(create_row_divider())

        # Body area for rows
        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.main_layout.addLayout(self.body_layout)

    def add_row(self, title: str, subtitle: str = "", control: QWidget = None, add_divider: bool = True):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 12, 16, 12)
        row_layout.setSpacing(14)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        t_lbl = QLabel(title)
        t_lbl.setObjectName("RowTitle")
        t_lbl.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.DemiBold))
        text_col.addWidget(t_lbl)

        if subtitle:
            s_lbl = QLabel(subtitle)
            s_lbl.setObjectName("RowSubtitle")
            s_lbl.setFont(QFont("Segoe UI Variable Text", 8.8))
            s_lbl.setWordWrap(True)
            text_col.addWidget(s_lbl)

        row_layout.addLayout(text_col, stretch=1)
        if control:
            row_layout.addWidget(control)

        self.body_layout.addWidget(row)
        if add_divider:
            self.body_layout.addWidget(create_row_divider())


class FileManagerAssetCard(QFrame):
    """Asset Card for File Manager 2 block with icon preview, category badge, and action toggle."""
    def __init__(self, key: str, title: str, category: str, subtitle: str, metadata_tag: str, icon_name: str, toggle_switch: ToggleSwitch, parent=None):
        super().__init__(parent)
        self.key = key
        self.category = category
        self.title_text = title
        self.subtitle_text = subtitle
        self.setObjectName("AssetCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(96)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Top row: Icon + Title + Category + Toggle
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        self.icon_box = QLabel()
        self.icon_box.setObjectName("AssetIconBox")
        self.icon_box.setFixedSize(34, 34)
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = get_vector_pixmap(icon_name, "#A1A1AA", 18)
        self.icon_box.setPixmap(pix)
        top_row.addWidget(self.icon_box)

        t_col = QVBoxLayout()
        t_col.setContentsMargins(0, 0, 0, 0)
        t_col.setSpacing(2)

        h_title = QHBoxLayout()
        h_title.setContentsMargins(0, 0, 0, 0)
        h_title.setSpacing(6)

        lbl_t = QLabel(title)
        lbl_t.setObjectName("AssetTitle")
        lbl_t.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.DemiBold))
        h_title.addWidget(lbl_t)

        cat_badge = QLabel(category.upper())
        cat_badge.setObjectName("AssetCategoryBadge")
        h_title.addWidget(cat_badge)
        h_title.addStretch()
        t_col.addLayout(h_title)

        lbl_sub = QLabel(subtitle)
        lbl_sub.setObjectName("AssetSub")
        lbl_sub.setFont(QFont("Segoe UI Variable Text", 8.8))
        lbl_sub.setWordWrap(True)
        t_col.addWidget(lbl_sub)

        top_row.addLayout(t_col, stretch=1)
        top_row.addWidget(toggle_switch)
        layout.addLayout(top_row)

        # Bottom row: Metadata tag / chip
        bot_row = QHBoxLayout()
        bot_row.setContentsMargins(0, 0, 0, 0)
        bot_row.setSpacing(6)

        lbl_meta = QLabel(metadata_tag)
        lbl_meta.setObjectName("AssetMetaChip")
        bot_row.addWidget(lbl_meta)
        bot_row.addStretch()
        layout.addLayout(bot_row)


class FileManagerAssetGrid(QWidget):
    """
    File Manager 2 (React Bits Pro): Asset grid with type filter pills and search bar.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.asset_cards = []
        self.current_filter = "all"

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(12)

        # 1. Filter Bar + Search Header
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setContentsMargins(0, 0, 0, 0)
        ctrl_bar.setSpacing(8)

        # Filter Pills
        self.pill_all = QPushButton("All")
        self.pill_search = QPushButton("Search Providers")
        self.pill_tools = QPushButton("Productivity Tools")
        self.pill_sys = QPushButton("System & Hardware")

        self.filter_buttons = {
            "all": self.pill_all,
            "search": self.pill_search,
            "tools": self.pill_tools,
            "sys": self.pill_sys,
        }

        for k, btn in self.filter_buttons.items():
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, key=k: self.set_filter(key))
            ctrl_bar.addWidget(btn)

        ctrl_bar.addStretch()

        # Search filter box
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText("Filter modules...")
        self.search_filter.setClearButtonEnabled(True)
        self.search_filter.setFixedWidth(180)
        self.search_filter.setFixedHeight(28)
        self.search_filter.textChanged.connect(self._apply_filter)
        ctrl_bar.addWidget(self.search_filter)

        vbox.addLayout(ctrl_bar)

        # 2. Asset Grid (2 columns)
        self.grid_container = QWidget()
        self.grid = QGridLayout(self.grid_container)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

        vbox.addWidget(self.grid_container)
        self._update_pill_styles()

    def add_asset_card(self, card: FileManagerAssetCard):
        idx = len(self.asset_cards)
        self.asset_cards.append(card)
        self.grid.addWidget(card, idx // 2, idx % 2)

    def set_filter(self, key: str):
        self.current_filter = key
        self._update_pill_styles()
        self._apply_filter()

    def _update_pill_styles(self):
        theme = getattr(self.window(), "_current_applied_theme", "dark")
        is_light = (theme == "light")
        accent = "#09090B" if is_light else "#FFFFFF"
        active_bg = "#E4E4E7" if is_light else "#27272A"
        active_border = "#71717A" if is_light else "#52525B"
        inactive_bg = "#FFFFFF" if is_light else "rgba(255, 255, 255, 0.04)"
        border_inact = "#E4E4E7" if is_light else "rgba(255, 255, 255, 0.08)"
        hover_border = "#71717A" if is_light else "#71717A"

        for k, btn in self.filter_buttons.items():
            if k == self.current_filter:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {active_bg};
                        color: {accent};
                        border: 1.5px solid {active_border};
                        border-radius: 14px;
                        padding: 3px 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {inactive_bg};
                        color: {'#71717A' if is_light else '#A1A1AA'};
                        border: 1px solid {border_inact};
                        border-radius: 14px;
                        padding: 3px 12px;
                        font-size: 11px;
                        font-weight: 500;
                    }}
                    QPushButton:hover {{
                        color: {'#18181B' if is_light else '#FAFAFA'};
                        border: 1px solid {hover_border};
                    }}
                """)

    def _apply_filter(self):
        query = self.search_filter.text().strip().lower()
        visible_idx = 0

        for card in self.asset_cards:
            self.grid.removeWidget(card)
            card.hide()

        for card in self.asset_cards:
            matches_cat = (self.current_filter == "all") or (card.category.lower() == self.current_filter.lower())
            matches_q = (not query) or (query in card.title_text.lower() or query in card.subtitle_text.lower())
            if matches_cat and matches_q:
                card.show()
                self.grid.addWidget(card, visible_idx // 2, visible_idx % 2)
                visible_idx += 1


class QuietHoursWidget(QFrame):
    """
    Notifications 3 (React Bits Pro): Delivery preferences with quiet hours schedule.
    """
    def __init__(self, settings: dict, make_toggle_fn, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setObjectName("QuietHoursCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Header with Moon Icon and Master Switch
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        icon_box = QLabel()
        icon_box.setObjectName("QuietHoursIconBox")
        icon_box.setFixedSize(36, 36)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme = getattr(self.window(), "_current_applied_theme", "dark")
        is_light = (theme == "light")
        icon_box.setPixmap(get_vector_pixmap("moon", "#18181B" if is_light else "#FFFFFF", 20))
        top_row.addWidget(icon_box)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        lbl_t = QLabel("Quiet Hours & Do Not Disturb")
        lbl_t.setObjectName("RowTitle")
        lbl_t.setFont(QFont("Segoe UI Variable Text", 10.5, QFont.Weight.DemiBold))
        text_col.addWidget(lbl_t)

        lbl_sub = QLabel("Mute non-urgent sound effects and suppress expanding popups during your focus or sleep hours.")
        lbl_sub.setObjectName("RowSubtitle")
        lbl_sub.setFont(QFont("Segoe UI Variable Text", 8.8))
        lbl_sub.setWordWrap(True)
        text_col.addWidget(lbl_sub)
        top_row.addLayout(text_col, stretch=1)

        self.chk_quiet_master = make_toggle_fn(self.settings.get("quiet_hours_enabled", False))
        top_row.addWidget(self.chk_quiet_master)
        layout.addLayout(top_row)

        layout.addWidget(create_row_divider())

        # Time Schedule Controls
        schedule_row = QHBoxLayout()
        schedule_row.setContentsMargins(0, 0, 0, 0)
        schedule_row.setSpacing(12)

        lbl_sched = QLabel("Active Schedule:")
        lbl_sched.setFont(QFont("Segoe UI Variable Text", 9.2, QFont.Weight.Medium))
        schedule_row.addWidget(lbl_sched)

        lbl_from = QLabel("From")
        lbl_from.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        schedule_row.addWidget(lbl_from)

        self.combo_quiet_start = create_styled_combobox(width=110)
        for h in range(24):
            time_str = f"{h:02d}:00"
            disp = f"{h % 12 or 12}:00 {'AM' if h < 12 else 'PM'}"
            self.combo_quiet_start.addItem(disp, time_str)
        curr_s = self.settings.get("quiet_hours_start", "22:00")
        idx_s = self.combo_quiet_start.findData(curr_s)
        self.combo_quiet_start.setCurrentIndex(idx_s if idx_s >= 0 else 22)
        schedule_row.addWidget(self.combo_quiet_start)

        lbl_to = QLabel("to")
        lbl_to.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        schedule_row.addWidget(lbl_to)

        self.combo_quiet_end = create_styled_combobox(width=110)
        for h in range(24):
            time_str = f"{h:02d}:00"
            disp = f"{h % 12 or 12}:00 {'AM' if h < 12 else 'PM'}"
            self.combo_quiet_end.addItem(disp, time_str)
        curr_e = self.settings.get("quiet_hours_end", "07:00")
        idx_e = self.combo_quiet_end.findData(curr_e)
        self.combo_quiet_end.setCurrentIndex(idx_e if idx_e >= 0 else 7)
        schedule_row.addWidget(self.combo_quiet_end)

        schedule_row.addStretch()
        layout.addLayout(schedule_row)

        # Exception Rules Checkboxes
        rules_box = QVBoxLayout()
        rules_box.setContentsMargins(0, 0, 0, 0)
        rules_box.setSpacing(6)

        self.chk_quiet_mute = QCheckBox("Mute all procedural audio chimes during Quiet Hours")
        self.chk_quiet_mute.setChecked(self.settings.get("quiet_hours_mute_sound", True))
        rules_box.addWidget(self.chk_quiet_mute)

        self.chk_quiet_suppress = QCheckBox("Suppress Island drop-down animations during fullscreen games and videos")
        self.chk_quiet_suppress.setChecked(self.settings.get("quiet_hours_suppress_popups", True))
        rules_box.addWidget(self.chk_quiet_suppress)

        self.chk_quiet_priority = QCheckBox("Allow high-priority alarms, countdown timers, and battery alerts")
        self.chk_quiet_priority.setChecked(self.settings.get("quiet_hours_allow_priority", True))
        rules_box.addWidget(self.chk_quiet_priority)

        layout.addLayout(rules_box)

        # Connect enable state
        def _on_toggle(checked):
            self.combo_quiet_start.setEnabled(checked)
            self.combo_quiet_end.setEnabled(checked)
            self.chk_quiet_mute.setEnabled(checked)
            self.chk_quiet_suppress.setEnabled(checked)
            self.chk_quiet_priority.setEnabled(checked)

        self.chk_quiet_master.toggled.connect(_on_toggle)
        _on_toggle(self.chk_quiet_master.isChecked())


class IntegrationMarketplaceCard(QFrame):
    """Integration card in Integrations 1 block with status badge and quick action."""
    def __init__(self, key: str, title: str, category: str, subtitle: str, status_text: str, is_active: bool, icon_name: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.title_text = title
        self.category = category
        self.subtitle_text = subtitle
        self.setObjectName("IntegrationCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(115)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Top row: Icon + Title + Category + Status Badge
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        self.icon_box = QLabel()
        self.icon_box.setObjectName("IntegrationIconBox")
        self.icon_box.setFixedSize(36, 36)
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.icon_box)

        t_col = QVBoxLayout()
        t_col.setContentsMargins(0, 0, 0, 0)
        t_col.setSpacing(2)

        h_title = QHBoxLayout()
        h_title.setContentsMargins(0, 0, 0, 0)
        h_title.setSpacing(6)

        lbl_t = QLabel(title)
        lbl_t.setObjectName("IntegrationTitle")
        lbl_t.setFont(QFont("Segoe UI Variable Text", 10.2, QFont.Weight.DemiBold))
        h_title.addWidget(lbl_t)

        cat_badge = QLabel(category.upper())
        cat_badge.setObjectName("IntegrationCategoryBadge")
        h_title.addWidget(cat_badge)
        h_title.addStretch()
        t_col.addLayout(h_title)

        lbl_sub = QLabel(subtitle)
        lbl_sub.setObjectName("IntegrationSub")
        lbl_sub.setFont(QFont("Segoe UI Variable Text", 8.8))
        lbl_sub.setWordWrap(True)
        t_col.addWidget(lbl_sub)

        top_row.addLayout(t_col, stretch=1)
        layout.addLayout(top_row)

        # Bottom row: Connection status pill + Action button
        bot_row = QHBoxLayout()
        bot_row.setContentsMargins(0, 0, 0, 0)
        bot_row.setSpacing(8)

        self.lbl_status = QLabel(f"●  {status_text}")
        self.lbl_status.setObjectName("IntegrationStatusPill")
        bot_row.addWidget(self.lbl_status)
        bot_row.addStretch()

        self.btn_action = QPushButton("Connected" if is_active else "Configure")
        self.btn_action.setObjectName("IntegrationActionBtn")
        self.btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_action.setFixedHeight(26)
        bot_row.addWidget(self.btn_action)

        layout.addLayout(bot_row)

        theme = getattr(self.window(), "_current_applied_theme", "dark")
        is_light = (theme == "light")
        col = "#18181B" if is_light else "#FAFAFA"
        pix = get_vector_pixmap(icon_name, col, 20)
        self.icon_box.setPixmap(pix)


class IntegrationsMarketplaceWidget(QWidget):
    """
    Integrations 1 (React Bits Pro): Integration marketplace grid with search and category filtering.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.integration_cards = []
        self.current_filter = "all"

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(12)

        # 1. Filter Bar
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setContentsMargins(0, 0, 0, 0)
        ctrl_bar.setSpacing(8)

        self.pill_all = QPushButton("All Services (8)")
        self.pill_media = QPushButton("Media & Audio")
        self.pill_hw = QPushButton("Hardware & System")
        self.pill_cloud = QPushButton("Mobile & Cloud")

        self.filter_buttons = {
            "all": self.pill_all,
            "media": self.pill_media,
            "hw": self.pill_hw,
            "cloud": self.pill_cloud,
        }

        for k, btn in self.filter_buttons.items():
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, key=k: self.set_filter(key))
            ctrl_bar.addWidget(btn)

        ctrl_bar.addStretch()

        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText("Filter integrations...")
        self.search_filter.setClearButtonEnabled(True)
        self.search_filter.setFixedWidth(180)
        self.search_filter.setFixedHeight(28)
        self.search_filter.textChanged.connect(self._apply_filter)
        ctrl_bar.addWidget(self.search_filter)

        vbox.addLayout(ctrl_bar)

        # 2. Marketplace Grid (2 columns)
        self.grid_container = QWidget()
        self.grid = QGridLayout(self.grid_container)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

        vbox.addWidget(self.grid_container)
        self._populate_integrations()
        self._update_pill_styles()

    def _populate_integrations(self):
        definitions = [
            ("spotify", "Spotify & Windows Media", "media", "GSMTC real-time playback session tracking, track seek, and album artwork.", "Connected (Active)", True, "music"),
            ("core_audio", "Windows Core Audio (pycaw)", "media", "Direct hardware endpoint audio mixer with per-application volume sliders.", "Connected", True, "volume"),
            ("power_wmi", "Windows Power & Battery (WMI)", "hw", "Hardware ACLineStatus, discharge rate telemetry, and health preservation.", "Connected", True, "power"),
            ("android_link", "Android Phone Link (ADB)", "cloud", "Wireless and USB Android screen mirroring, clipboard sync, and notification hub.", "Ready (Standby)", False, "phone"),
            ("everything_api", "Windows Search & Everything", "hw", "Instant local PC file, folder, and settings indexing engine.", "Connected", True, "desktop"),
            ("open_meteo", "Open-Meteo Weather API", "cloud", "Geocoded real-time local temperature, condition icons, and hourly precipitation.", "Online", True, "globe"),
            ("rook_tray", "Rook Companion System Tray", "hw", "Persistent background taskbar companion with quick launch shortcuts.", "Integrated", True, "rook"),
            ("lens_vision", "Google Lens Visual Search", "cloud", "Screen region snip and visual reverse-image search.", "Ready", True, "sparkles"),
        ]

        for i, (k, title, cat, desc, status, is_act, icon) in enumerate(definitions):
            card = IntegrationMarketplaceCard(k, title, cat, desc, status, is_act, icon, parent=self)
            self.integration_cards.append(card)
            self.grid.addWidget(card, i // 2, i % 2)

    def set_filter(self, key: str):
        self.current_filter = key
        self._update_pill_styles()
        self._apply_filter()

    def _update_pill_styles(self):
        theme = getattr(self.window(), "_current_applied_theme", "dark")
        is_light = (theme == "light")
        accent = "#09090B" if is_light else "#FFFFFF"
        active_bg = "#E4E4E7" if is_light else "#27272A"
        active_border = "#71717A" if is_light else "#52525B"
        inactive_bg = "#FFFFFF" if is_light else "rgba(255, 255, 255, 0.04)"
        border_inact = "#E4E4E7" if is_light else "rgba(255, 255, 255, 0.08)"
        hover_border = "#71717A" if is_light else "#71717A"

        for k, btn in self.filter_buttons.items():
            if k == self.current_filter:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {active_bg};
                        color: {accent};
                        border: 1.5px solid {active_border};
                        border-radius: 14px;
                        padding: 3px 12px;
                        font-size: 11px;
                        font-weight: 600;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {inactive_bg};
                        color: {'#71717A' if is_light else '#A1A1AA'};
                        border: 1px solid {border_inact};
                        border-radius: 14px;
                        padding: 3px 12px;
                        font-size: 11px;
                        font-weight: 500;
                    }}
                    QPushButton:hover {{
                        color: {'#18181B' if is_light else '#FAFAFA'};
                        border: 1px solid {hover_border};
                    }}
                """)

    def _apply_filter(self):
        query = self.search_filter.text().strip().lower()
        visible_idx = 0

        for card in self.integration_cards:
            self.grid.removeWidget(card)
            card.hide()

        for card in self.integration_cards:
            matches_cat = (self.current_filter == "all") or (card.category.lower() == self.current_filter.lower())
            matches_q = (not query) or (query in card.title_text.lower() or query in card.subtitle_text.lower())
            if matches_cat and matches_q:
                card.show()
                self.grid.addWidget(card, visible_idx // 2, visible_idx % 2)
                visible_idx += 1


class SettingsDialog(QDialog):
    settings_changed = Signal(dict)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings.copy()
        self._syncing_quick_controls = False
        self._toggle_switches = []
        self._group_headers = []
        self._row_titles = []
        self._row_subtitles = []
        self._home_cards = []
        self._searchable_settings = []
        self._page_scroll_areas = []
        self._current_applied_theme = str(self.settings.get("theme", "dark")).lower()
        self._last_synced_startup = bool(self.settings.get("run_on_startup", True))
        self._save_debounce_timer = QTimer(self)
        self._save_debounce_timer.setSingleShot(True)
        self._save_debounce_timer.setInterval(250)
        self._save_debounce_timer.timeout.connect(self._flush_save_settings)

        self.setWindowTitle("ODD Settings — by Humnspace")
        self.resize(860, 620)
        self.setMinimumSize(780, 540)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        self.init_ui()

    # ------------------- Structured Row Builder -------------------
    def _make_toggle(self, checked: bool) -> ToggleSwitch:
        sw = ToggleSwitch()
        sw.setChecked(bool(checked))
        self._toggle_switches.append(sw)
        return sw

    def _add_group_title(self, parent_layout: QVBoxLayout, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("GroupSectionTitle")
        lbl.setFont(QFont("Segoe UI Variable Text", 9.5, QFont.Weight.Bold))
        lbl.setContentsMargins(4, 6, 0, 2)
        parent_layout.addWidget(lbl)
        self._group_headers.append(lbl)
        return lbl

    def _add_setting_row(
        self,
        card_layout: QVBoxLayout,
        title: str,
        subtitle: str = "",
        control: QWidget = None,
        add_divider: bool = True
    ) -> QWidget:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(16, 12, 16, 12)
        row_layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setObjectName("RowTitle")
        lbl_t.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.DemiBold))
        lbl_t.setWordWrap(True)
        text_col.addWidget(lbl_t)
        self._row_titles.append(lbl_t)

        if subtitle:
            lbl_s = QLabel(subtitle)
            lbl_s.setObjectName("RowSubtitle")
            lbl_s.setFont(QFont("Segoe UI Variable Text", 8.8))
            lbl_s.setWordWrap(True)
            text_col.addWidget(lbl_s)
            self._row_subtitles.append(lbl_s)

        row_layout.addLayout(text_col, stretch=1)

        if control is not None:
            row_layout.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        card_layout.addWidget(row_widget)
        if add_divider:
            card_layout.addWidget(create_row_divider())
            
        self._register_setting(
            title=title,
            subtitle=subtitle,
            widget=row_widget,
            tab_index=getattr(self, '_current_tab_index', 0),
            tab_name=getattr(self, '_current_tab_title', "General"),
            scroll_area=getattr(self, '_current_scroll_area', None)
        )
        return row_widget

    def _create_page_scroll(self, page_title: str, page_subtitle: str) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        self._current_tab_title = page_title
        self._current_scroll_area = scroll
        self._current_tab_index = len(self._page_scroll_areas)
        self._page_scroll_areas.append(scroll)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 2, 10, 14)
        layout.setSpacing(10)

        # Category Page Title Header
        hdr_box = QVBoxLayout()
        hdr_box.setContentsMargins(2, 0, 0, 6)
        hdr_box.setSpacing(2)

        lbl_pt = QLabel(page_title)
        lbl_pt.setFont(QFont("Segoe UI Variable Display", 14, QFont.Weight.Bold))
        hdr_box.addWidget(lbl_pt)
        self._row_titles.append(lbl_pt)

        lbl_ps = QLabel(page_subtitle)
        lbl_ps.setFont(QFont("Segoe UI Variable Text", 9.2))
        lbl_ps.setWordWrap(True)
        hdr_box.addWidget(lbl_ps)
        self._row_subtitles.append(lbl_ps)

        layout.addLayout(hdr_box)
        scroll.setWidget(container)
        return scroll, layout

    def get_current_theme(self) -> str:
        return str(self.settings.get("theme", "dark")).lower()

    def _register_setting(
        self,
        title: str,
        subtitle: str,
        widget: QWidget,
        tab_index: int,
        tab_name: str,
        scroll_area: QScrollArea,
        extra_keywords: list = None
    ):
        clean_title = (title or "").strip()
        if not clean_title or not widget:
            return
        # Avoid duplicate registration of the exact same title & widget
        for item in self._searchable_settings:
            if item.get("title") == clean_title and item.get("widget") == widget:
                return

        intents = list(NLP_INTENTS_MAP.get(clean_title, []))
        if extra_keywords:
            intents.extend(extra_keywords)

        self._searchable_settings.append({
            "title": clean_title,
            "subtitle": (subtitle or "").strip(),
            "widget": widget,
            "tab_index": tab_index,
            "tab_name": tab_name,
            "scroll_area": scroll_area,
            "intents": intents,
        })

    def search_settings_nlp(self, query: str) -> list:
        """
        High-precision NLP search for ODD Settings:
        - Normalizes and strips conversational stop-words.
        - Evaluates exact matches, partial matches, token sets, and intent concepts.
        - Enforces strict precision threshold (65.0) to eliminate random results.
        """
        q_raw = (query or "").strip().lower()
        if not q_raw:
            return []

        words = [w for w in re.split(r'\s+|[.,?!/\-_]', q_raw) if w and w not in _STOP_WORDS]
        filtered_q = " ".join(words) if words else q_raw

        scored_matches = []

        for item in self._searchable_settings:
            title = item["title"]
            subtitle = item.get("subtitle", "")
            intents = item.get("intents", [])

            t_lower = title.lower()
            s_lower = subtitle.lower()

            # 1. Direct Exact / Substring Match (Highest confidence)
            if q_raw == t_lower or filtered_q == t_lower:
                scored_matches.append((100.0, item))
                continue
            if filtered_q and filtered_q in t_lower:
                scored_matches.append((97.0, item))
                continue
            if t_lower in filtered_q:
                scored_matches.append((96.0, item))
                continue

            scores = []

            # 2. Match against NLP Intent Keywords
            for intent in intents:
                i_lower = intent.lower()
                if q_raw == i_lower or filtered_q == i_lower:
                    scores.append(95.0)
                elif filtered_q and (filtered_q in i_lower or i_lower in filtered_q):
                    scores.append(91.0)
                elif _HAS_RAPIDFUZZ:
                    scores.append(fuzz.token_set_ratio(filtered_q, i_lower))
                else:
                    scores.append(difflib.SequenceMatcher(None, filtered_q, i_lower).ratio() * 100.0)

            # 3. Match against Title & Subtitle via Token Set / Partial Ratio
            if _HAS_RAPIDFUZZ:
                scores.append(fuzz.token_set_ratio(filtered_q, t_lower))
                scores.append(fuzz.partial_ratio(filtered_q, t_lower))
                if s_lower:
                    scores.append(fuzz.token_set_ratio(filtered_q, s_lower) * 0.88)
            else:
                scores.append(difflib.SequenceMatcher(None, filtered_q, t_lower).ratio() * 100.0)
                if s_lower:
                    scores.append(difflib.SequenceMatcher(None, filtered_q, s_lower).ratio() * 85.0)

            best_score = max(scores) if scores else 0.0

            # Strict Precision Threshold (No random results)
            if best_score >= 65.0:
                scored_matches.append((best_score, item))

        # Sort descending by relevance score
        scored_matches.sort(key=lambda x: x[0], reverse=True)
        return [match[1] for match in scored_matches]

    def navigate_to_setting(self, setting_item: dict):
        """
        Directly opens the setting category, centers the widget in the scroll viewport,
        and applies an animated glowing highlight overlay for exactly 2 seconds.
        """
        if not setting_item:
            return

        tab_idx = setting_item.get("tab_index", 0)
        target_widget = setting_item.get("widget")
        scroll_area = setting_item.get("scroll_area")

        # 1. Switch to the category detail view
        self.open_category(tab_idx)

        # 2. Smoothly center and highlight the target setting widget
        def _execute_center_and_glow():
            if target_widget and scroll_area:
                try:
                    # Calculate relative vertical coordinate inside scroll container
                    target_rect = target_widget.geometry()
                    parent = target_widget.parentWidget()
                    container = scroll_area.widget()
                    while parent and parent != container:
                        target_rect.moveTop(target_rect.top() + parent.y())
                        parent = parent.parentWidget()

                    viewport_h = scroll_area.viewport().height()
                    target_y = max(0, target_rect.top() - (viewport_h - target_rect.height()) // 2)
                    scroll_area.verticalScrollBar().setValue(target_y)

                    # Highlight setting for 2 seconds
                    overlay = SettingHighlightOverlay(target_widget, theme=self.get_current_theme(), duration=2.0)
                    overlay.start()
                except Exception as e:
                    print(f"[ODD Settings] Navigation highlight error: {e}")

        QTimer.singleShot(45, _execute_center_and_glow)


    # ------------------- Main Dialog Initialization -------------------
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(22, 16, 22, 16)
        main_layout.setSpacing(14)

        # 1. Top Navigation & Brand Bar
        header = QHBoxLayout()
        header.setSpacing(12)

        self.btn_back_home = QPushButton("←  All Settings")
        self.btn_back_home.setObjectName("BackHomeButton")
        self.btn_back_home.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back_home.setFixedHeight(32)
        self.btn_back_home.clicked.connect(self.show_home_view)
        self.btn_back_home.hide()
        header.addWidget(self.btn_back_home)

        self.logo_lbl = QLabel()
        curr_theme = str(self.settings.get("theme", "dark")).lower()
        self.logo_lbl.setPixmap(get_odd_logo_pixmap((30, 30), curr_theme))
        header.addWidget(self.logo_lbl)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(1)

        self.title_lbl = QLabel("ODD Settings")
        self.title_lbl.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        title_vbox.addWidget(self.title_lbl)

        self.sub_lbl = QLabel("Living Desktop Search & Workspace Control Center")
        self.sub_lbl.setFont(QFont("Segoe UI Variable Text", 8.8))
        title_vbox.addWidget(self.sub_lbl)
        header.addLayout(title_vbox)

        header.addStretch()

        # Modern NLP Settings Search Bar
        self.search_bar = SettingsSearchBar(self, parent=self)
        header.addWidget(self.search_bar)

        self.ver_badge = QLabel(f"v{CURRENT_VERSION}")
        self.ver_badge.setFont(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.DemiBold))
        header.addWidget(self.ver_badge)

        self.btn_header_close = QPushButton("✕", self)
        self.btn_header_close.setFixedSize(28, 28)
        self.btn_header_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_header_close.setToolTip("Close Settings (Esc)")
        self.btn_header_close.clicked.connect(self.close)
        header.addWidget(self.btn_header_close)

        main_layout.addLayout(header)

        # 2. Root Stack: Index 0 = Settings Homepage (no sidebar), Index 1 = Category Detail View (with sidebar)
        self.root_stack = QStackedWidget()

        # Build detail pages first so all self.chk_* and self.combo_* controls exist
        self.detail_container = QWidget()
        detail_layout = QHBoxLayout(self.detail_container)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(18)

        # Left Sidebar (Only visible when inside a selected category)
        sidebar_panel = QFrame()
        sidebar_panel.setObjectName("SidebarPanel")
        sidebar_panel.setFixedWidth(205)
        sb_layout = QVBoxLayout(sidebar_panel)
        sb_layout.setContentsMargins(8, 8, 8, 8)
        sb_layout.setSpacing(6)

        self.btn_sidebar_home = QPushButton("⌂   Settings Home")
        self.btn_sidebar_home.setObjectName("SidebarHomeBtn")
        self.btn_sidebar_home.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sidebar_home.setFixedHeight(34)
        self.btn_sidebar_home.clicked.connect(self.show_home_view)
        sb_layout.addWidget(self.btn_sidebar_home)

        sb_layout.addWidget(create_row_divider())

        self.nav_list = QListWidget()
        self.nav_list.setIconSize(QSize(16, 16))
        self.nav_defs = [
            ("Radial Arc & Cursor", "sparkles", "Orbital squircle menu, hold summon key, cursor search & contextual overlays"),
            ("Appearance & Animations", "appearance", "Themes, liquid spring physics, screen edge placement & notch styling"),
            ("Libraries", "modules", "Productivity engines, search providers, custom command prefixes & commands guide"),
            ("General", "general", "Startup preferences, global hotkey, sound effects & wellness reminders"),
            ("ODD Island", "bell", "Dynamic Island HUD, live media vinyl, quiet hours & hardware telemetry"),
            ("Updates & Feedback", "update", f"Version v{CURRENT_VERSION}, diagnostic logs, bug reports & feedback"),
        ]
        for title, icon_name, _desc in self.nav_defs:
            item = QListWidgetItem(get_vector_icon(icon_name, "#A1A1AA", 16, active_color="#FFFFFF"), f"  {title}")
            self.nav_list.addItem(item)

        sb_layout.addWidget(self.nav_list, stretch=1)
        detail_layout.addWidget(sidebar_panel)

        self.pages = QStackedWidget()
        self.pages.setStyleSheet("background: transparent; border: none;")
        self.pages.addWidget(self.create_radial_tab())        # Index 0: Radial Arc & Cursor
        self.pages.addWidget(self.create_appearance_tab())    # Index 1: Appearance & Animations
        self.pages.addWidget(self.create_libraries_tab())     # Index 2: Libraries
        self.pages.addWidget(self.create_general_tab())       # Index 3: General
        self.pages.addWidget(self.create_island_tab())        # Index 4: ODD Island
        self.pages.addWidget(self.create_updates_tab())       # Index 5: Updates & Feedback

        detail_layout.addWidget(self.pages, stretch=1)

        # Build Homepage View (Index 0)
        self.home_view = self.create_home_view()

        # Build Search Results Page (Index 2)
        self.search_view = self.create_search_view()

        self.root_stack.addWidget(self.home_view)         # 0 = Home View (No sidebar)
        self.root_stack.addWidget(self.detail_container)  # 1 = Detail View (Sidebar + Category Page)
        self.root_stack.addWidget(self.search_view)       # 2 = Dedicated Search Results Page
        main_layout.addWidget(self.root_stack, stretch=1)

        self.nav_list.currentRowChanged.connect(self._on_sidebar_row_changed)

        # 3. Footer Actions
        footer = QHBoxLayout()
        footer.setSpacing(10)

        self.btn_reset = QPushButton("Reset Defaults")
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.clicked.connect(self.reset_defaults)
        footer.addWidget(self.btn_reset)
        footer.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        footer.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Save & Apply")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setFont(QFont("Segoe UI Variable Text", 9.5, QFont.Weight.Bold))
        self.btn_save.clicked.connect(self.save_and_apply)
        footer.addWidget(self.btn_save)

        main_layout.addLayout(footer)

        # Start on the clean Settings Homepage
        self.show_home_view()
        self.apply_global_theme()

        # Live Settings Connections
        self.chk_startup.toggled.connect(self._on_setting_live_changed)
        self.chk_sound.toggled.connect(self._on_setting_live_changed)
        self.slider_volume.valueChanged.connect(self._on_setting_live_changed)
        self.chk_music.toggled.connect(self._on_setting_live_changed)
        self.combo_music_mode.currentIndexChanged.connect(self._on_setting_live_changed)
        if hasattr(self, 'combo_paused_media'):
            self.combo_paused_media.currentIndexChanged.connect(self._on_setting_live_changed)
        if hasattr(self, 'combo_media_style'):
            self.combo_media_style.currentIndexChanged.connect(self._on_setting_live_changed)
        if hasattr(self, 'combo_media_visibility'):
            self.combo_media_visibility.currentIndexChanged.connect(self._on_setting_live_changed)
        self.combo_theme.currentIndexChanged.connect(self._on_setting_live_changed)
        if hasattr(self, 'combo_layout_style'):
            self.combo_layout_style.currentIndexChanged.connect(self._on_setting_live_changed)
        self.combo_edge.currentIndexChanged.connect(self._on_setting_live_changed)
        self.combo_mode.currentIndexChanged.connect(self._on_setting_live_changed)
        self.combo_anim.currentIndexChanged.connect(self._on_setting_live_changed)
        self.slider_opacity.valueChanged.connect(self._on_setting_live_changed)
        if hasattr(self, 'combo_edge_color_mode'):
            self.combo_edge_color_mode.currentIndexChanged.connect(self._on_setting_live_changed)
        if hasattr(self, 'slider_edge_width'):
            self.slider_edge_width.valueChanged.connect(self._on_setting_live_changed)
        if hasattr(self, 'slider_edge_thickness'):
            self.slider_edge_thickness.valueChanged.connect(self._on_setting_live_changed)
        for rad_chk in (
            'chk_radial_menu', 'chk_radial_shake', 'chk_radial_magic',
            'chk_radial_bottom_music', 'chk_radial_search', 'chk_radial_qs', 'chk_radial_phone'
        ):
            if hasattr(self, rad_chk):
                getattr(self, rad_chk).toggled.connect(self._on_setting_live_changed)
        if hasattr(self, 'combo_radial_key'):
            self.combo_radial_key.currentIndexChanged.connect(self._on_setting_live_changed)
        if hasattr(self, 'chk_hide_edge_bar'):
            self.chk_hide_edge_bar.toggled.connect(self._on_setting_live_changed)

        for chk_name in (
            'chk_ui_plus', 'chk_ui_quick_settings', 'chk_ui_music', 'chk_ui_lens',
            'chk_ui_settings', 'chk_ui_edge_bar', 'chk_ui_power_controls',
            'chk_mod_clip', 'chk_mod_notes', 'chk_mod_conv', 'chk_mod_sys', 'chk_mod_clock',
            'chk_mod_color', 'chk_mod_calc', 'chk_mod_web', 'chk_mod_fallbacks', 'chk_mod_messaging',
            'chk_island_media', 'chk_island_volume', 'chk_island_battery',
            'chk_island_timer', 'chk_island_caps', 'chk_island_clip',
            'chk_island_downloads', 'chk_island_activity_mem', 'chk_island_reminders',
            'chk_island_notifications', 'chk_vinyl_rot',
            'chk_dynamic_max_delay', 'chk_edge_music', 'chk_edge_infomatic', 'chk_water_reminder', 'chk_water_working_hours'
        ):
            if hasattr(self, chk_name):
                getattr(self, chk_name).toggled.connect(self._on_setting_live_changed)

        if hasattr(self, 'combo_messaging_provider'):
            self.combo_messaging_provider.currentIndexChanged.connect(self._on_setting_live_changed)

    # ------------------- Navigation: Homepage <-> Category Detail -------------------
    def show_home_view(self):
        self._sync_home_quick_controls_from_main()
        self.root_stack.setCurrentIndex(0)
        self.btn_back_home.hide()
        self.sub_lbl.setText("Select a category below or adjust quick preferences")

    def open_category(self, index: int):
        if 0 <= index < self.pages.count():
            self.nav_list.blockSignals(True)
            self.nav_list.setCurrentRow(index)
            self.nav_list.blockSignals(False)
            self.pages.setCurrentIndex(index)
            self.root_stack.setCurrentIndex(1)
            self.btn_back_home.show()
            cat_title, _, cat_desc = self.nav_defs[index]
            self.sub_lbl.setText(f"{cat_title}  •  {cat_desc}")

    def _on_sidebar_row_changed(self, index: int):
        if 0 <= index < self.pages.count():
            self.pages.setCurrentIndex(index)
            cat_title, _, cat_desc = self.nav_defs[index]
            self.sub_lbl.setText(f"{cat_title}  •  {cat_desc}")

    # ------------------- Search Results Full Page (Index 2) -------------------
    def create_search_view(self) -> QWidget:
        """
        Creates the dedicated full-page search results view for ODD Settings.
        Allows the user to type freely without interruptions or popups, and presents
        results cleanly formatted with category badges, descriptions, and direct jump buttons.
        """
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(12)

        # Header area: Back button + Query summary
        hdr_box = QHBoxLayout()
        hdr_box.setSpacing(10)

        self.btn_search_back = QPushButton("←  Back")
        self.btn_search_back.setObjectName("SearchBackBtn")
        self.btn_search_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search_back.setFixedHeight(30)
        self.btn_search_back.clicked.connect(self.close_search_view)
        hdr_box.addWidget(self.btn_search_back)

        self.lbl_search_header = QLabel("Search Results")
        self.lbl_search_header.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        self.lbl_search_header.setObjectName("SearchHeaderTitle")
        hdr_box.addWidget(self.lbl_search_header)

        self.lbl_search_count = QLabel("")
        self.lbl_search_count.setFont(QFont("Segoe UI Variable Text", 9))
        self.lbl_search_count.setObjectName("SearchHeaderCount")
        hdr_box.addWidget(self.lbl_search_count)

        hdr_box.addStretch()
        vbox.addLayout(hdr_box)

        # Scroll area for result cards
        self.search_scroll = QScrollArea()
        self.search_scroll.setWidgetResizable(True)
        self.search_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.search_scroll.setStyleSheet("background: transparent; border: none;")

        self.search_results_container = QWidget()
        self.search_results_layout = QVBoxLayout(self.search_results_container)
        self.search_results_layout.setContentsMargins(2, 4, 8, 16)
        self.search_results_layout.setSpacing(10)

        self.search_scroll.setWidget(self.search_results_container)
        vbox.addWidget(self.search_scroll, stretch=1)

        return container

    def show_search_results(self, query: str):
        """Executes the high-precision NLP search and populates the dedicated search view."""
        q = (query or "").strip()
        if not q:
            self.close_search_view()
            return

        # Record current stack index before switching to search results (so back returns properly)
        curr_idx = self.root_stack.currentIndex()
        if curr_idx != 2:
            self._previous_stack_index = curr_idx

        matches = self.search_settings_nlp(q)

        # Clear previous result widgets
        while self.search_results_layout.count() > 0:
            item = self.search_results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        is_light = self.get_current_theme() == "light"

        if not matches:
            self.lbl_search_header.setText(f"No results for \"{q}\"")
            self.lbl_search_count.setText("0 settings found")
            empty_box = QFrame()
            empty_box.setObjectName("SettingCard")
            empty_layout = QVBoxLayout(empty_box)
            empty_layout.setContentsMargins(24, 32, 24, 32)
            empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.setSpacing(8)

            lbl_hint1 = QLabel(f"No settings closely matched '{q}'.")
            lbl_hint1.setFont(QFont("Segoe UI Variable Text", 10.5, QFont.Weight.DemiBold))
            lbl_hint1.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_hint1.setStyleSheet("color: #FFFFFF;" if not is_light else "color: #18181B;")
            empty_layout.addWidget(lbl_hint1)

            lbl_hint2 = QLabel("Try searching with terms like 'dark mode', 'sound', 'weather', 'startup', or 'volume'.")
            lbl_hint2.setFont(QFont("Segoe UI Variable Text", 9.2))
            lbl_hint2.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_hint2.setStyleSheet("color: #A1A1AA;" if not is_light else "color: #71717A;")
            empty_layout.addWidget(lbl_hint2)

            self.search_results_layout.addWidget(empty_box)
        else:
            count_str = f"{len(matches)} setting{'s' if len(matches) != 1 else ''} found"
            self.lbl_search_header.setText(f"Results for \"{q}\"")
            self.lbl_search_count.setText(f"•  {count_str}")

            for match in matches:
                card = self._create_search_result_card(match, is_light)
                self.search_results_layout.addWidget(card)

        self.search_results_layout.addStretch()

        self.root_stack.setCurrentIndex(2)
        self.btn_back_home.hide()
        self.sub_lbl.setText(f"Search results for \"{q}\"")

    def close_search_view(self):
        """Restores the previous view (home or detail) and resets search query."""
        if hasattr(self, 'search_bar') and self.search_bar.input.text():
            self.search_bar.input.blockSignals(True)
            self.search_bar.input.clear()
            self.search_bar.btn_clear.hide()
            self.search_bar.input.blockSignals(False)

        prev_idx = getattr(self, '_previous_stack_index', 0)
        if prev_idx == 1:
            self.root_stack.setCurrentIndex(1)
            self.btn_back_home.show()
            curr_row = self.nav_list.currentRow()
            if 0 <= curr_row < len(self.nav_defs):
                cat_title, _, cat_desc = self.nav_defs[curr_row]
                self.sub_lbl.setText(f"{cat_title}  •  {cat_desc}")
        else:
            self.show_home_view()

    def _create_search_result_card(self, match: dict, is_light: bool) -> QFrame:
        card = QFrame()
        card.setObjectName("SearchResultCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # Icon or category badge
        badge_box = QVBoxLayout()
        badge_box.setSpacing(4)
        badge_box.setContentsMargins(0, 0, 0, 0)

        badge_lbl = QLabel(match.get("tab_name", "Settings").upper())
        badge_lbl.setFont(QFont("Segoe UI Variable Text", 7.8, QFont.Weight.Bold))
        badge_lbl.setStyleSheet(
            "color: #52525B; letter-spacing: 0.5px;" if is_light else "color: #D4D4D8; letter-spacing: 0.5px;"
        )
        badge_box.addWidget(badge_lbl)

        title_lbl = QLabel(match.get("title", ""))
        title_lbl.setFont(QFont("Segoe UI Variable Text", 10.5, QFont.Weight.DemiBold))
        title_lbl.setStyleSheet("color: #18181B;" if is_light else "color: #FFFFFF;")
        badge_box.addWidget(title_lbl)

        sub_text = match.get("subtitle", "")
        if sub_text:
            sub_lbl = QLabel(sub_text)
            sub_lbl.setFont(QFont("Segoe UI Variable Text", 9))
            sub_lbl.setWordWrap(True)
            sub_lbl.setStyleSheet("color: #71717A;" if is_light else "color: #A1A1AA;")
            badge_box.addWidget(sub_lbl)

        layout.addLayout(badge_box, stretch=1)

        btn_open = QPushButton("Open  →")
        btn_open.setObjectName("SearchResultOpenBtn")
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.setFixedHeight(28)
        layout.addWidget(btn_open)

        def _on_card_clicked():
            self.navigate_to_setting(match)

        btn_open.clicked.connect(_on_card_clicked)
        card.mouseReleaseEvent = lambda e: _on_card_clicked() if e.button() == Qt.MouseButton.LeftButton else None

        return card

    def create_home_view(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 2, 8, 14)
        layout.setSpacing(16)

        # 1. Primary Settings Tabs Grid (The 5 major sections prominently showcased first!)
        self._add_group_title(layout, "Settings Tabs & Categories")
        tabs_grid = QGridLayout()
        tabs_grid.setContentsMargins(0, 4, 0, 4)
        tabs_grid.setHorizontalSpacing(12)
        tabs_grid.setVerticalSpacing(12)
        tabs_grid.setColumnStretch(0, 1)
        tabs_grid.setColumnStretch(1, 1)

        self._home_cards = []
        for idx, (cat_title, icon_name, cat_desc) in enumerate(self.nav_defs):
            badge = f"v{CURRENT_VERSION}" if "Update" in cat_title else ""
            card = HomeCategoryCard(cat_title, cat_desc, icon_name, badge_text=badge, parent=container)
            card.clicked.connect(lambda checked=False, i=idx: self.open_category(i))
            self._home_cards.append(card)
            tabs_grid.addWidget(card, idx // 2, idx % 2)

        layout.addLayout(tabs_grid)

        # 2. Helpful Quick Information Container Card
        info_card = create_setting_card(container)
        ic_layout = QVBoxLayout(info_card)
        ic_layout.setContentsMargins(18, 16, 18, 16)
        ic_layout.setSpacing(6)

        info_header = QLabel("ODD Desktop Companion", info_card)
        info_header.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.DemiBold))
        ic_layout.addWidget(info_header)

        info_sub = QLabel(
            "Select any category above to customize appearance, search engines, global hotkeys, "
            "Dynamic Island HUDs, and system tools. All preferences take effect immediately.",
            info_card
        )
        info_sub.setWordWrap(True)
        info_sub.setFont(QFont("Segoe UI Variable Text", 9))
        info_sub.setStyleSheet("color: #A1A1AA; line-height: 1.4;")
        ic_layout.addWidget(info_sub)

        layout.addWidget(info_card)
        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _sync_home_quick_controls_from_main(self):
        if not hasattr(self, 'home_chk_startup'):
            return
        self._syncing_quick_controls = True
        try:
            if hasattr(self, 'home_shortcut_selector') and hasattr(self, 'shortcut_selector'):
                self.home_shortcut_selector.set_hotkey(self.shortcut_selector.get_hotkey_string())
            if hasattr(self, 'home_combo_mode') and hasattr(self, 'combo_mode'):
                idx_m = self.home_combo_mode.findData(self.combo_mode.currentData())
                if idx_m >= 0:
                    self.home_combo_mode.setCurrentIndex(idx_m)
            if hasattr(self, 'home_chk_startup') and hasattr(self, 'chk_startup'):
                self.home_chk_startup.setChecked(self.chk_startup.isChecked())
        finally:
            self._syncing_quick_controls = False

    def _on_home_quick_control_changed(self):
        if self._syncing_quick_controls:
            return
        self._syncing_quick_controls = True
        try:
            if hasattr(self, 'home_shortcut_selector') and hasattr(self, 'shortcut_selector'):
                new_hk = self.home_shortcut_selector.get_hotkey_string()
                self.shortcut_selector.set_hotkey(new_hk)
                self.settings["hotkey"] = new_hk
                if hasattr(self, 'combo_mode') and self.combo_mode.count() >= 4:
                    self.combo_mode.setItemText(3, f"Keyboard shortcut only ({new_hk})")
                if hasattr(self, 'home_combo_mode') and self.home_combo_mode.count() >= 4:
                    self.home_combo_mode.setItemText(3, f"Keyboard shortcut only ({new_hk})")
            if hasattr(self, 'home_combo_mode') and hasattr(self, 'combo_mode'):
                idx_m = self.combo_mode.findData(self.home_combo_mode.currentData())
                if idx_m >= 0 and self.combo_mode.currentIndex() != idx_m:
                    self.combo_mode.setCurrentIndex(idx_m)
            if hasattr(self, 'home_chk_startup') and hasattr(self, 'chk_startup'):
                if self.chk_startup.isChecked() != self.home_chk_startup.isChecked():
                    self.chk_startup.setChecked(self.home_chk_startup.isChecked())
        finally:
            self._syncing_quick_controls = False
        self._on_setting_live_changed()

    def _on_use_case_preset_selected(self, preset_key: str):
        self.settings["use_case_preset"] = preset_key
        if preset_key == "dynamic_island":
            self.settings["enable_music_overlay"] = True
            self.settings["ui_show_edge_indicator"] = True
            self.settings["island_show_media_hud"] = True
            self.settings["island_show_volume_hud"] = True
            self.settings["hide_edge_bar"] = False
            self.settings["sound_enabled"] = True
            if hasattr(self, 'chk_music'): self.chk_music.setChecked(True)
            if hasattr(self, 'chk_ui_edge_bar'): self.chk_ui_edge_bar.setChecked(True)
            if hasattr(self, 'chk_sound'): self.chk_sound.setChecked(True)
        elif preset_key == "minimal_launcher":
            self.settings["enable_music_overlay"] = False
            self.settings["ui_show_edge_indicator"] = False
            self.settings["hide_edge_bar"] = True
            self.settings["edge_trigger_mode"] = "hotkey_only"
            if hasattr(self, 'chk_music'): self.chk_music.setChecked(False)
            if hasattr(self, 'chk_ui_edge_bar'): self.chk_ui_edge_bar.setChecked(False)
            if hasattr(self, 'combo_mode'):
                idx = self.combo_mode.findData("hotkey_only")
                if idx >= 0: self.combo_mode.setCurrentIndex(idx)
        elif preset_key == "productivity":
            self.settings["enable_clipboard_history"] = True
            self.settings["enable_quick_notes"] = True
            self.settings["enable_calculator"] = True
            self.settings["enable_unit_converter"] = True
            self.settings["ui_show_plus_button"] = True
            self.settings["ui_show_quick_settings_button"] = True
            if hasattr(self, 'chk_mod_clip'): self.chk_mod_clip.setChecked(True)
            if hasattr(self, 'chk_mod_notes'): self.chk_mod_notes.setChecked(True)
            if hasattr(self, 'chk_mod_calc'): self.chk_mod_calc.setChecked(True)
            if hasattr(self, 'chk_mod_conv'): self.chk_mod_conv.setChecked(True)
            if hasattr(self, 'chk_ui_plus'): self.chk_ui_plus.setChecked(True)
            if hasattr(self, 'chk_ui_quick_settings'): self.chk_ui_quick_settings.setChecked(True)
        elif preset_key == "media_companion":
            self.settings["enable_music_overlay"] = True
            self.settings["music_overlay_mode"] = "always"
            self.settings["ui_show_music_button"] = True
            self.settings["sound_enabled"] = True
            if hasattr(self, 'chk_music'): self.chk_music.setChecked(True)
            if hasattr(self, 'combo_music_mode'):
                idx = self.combo_music_mode.findData("always")
                if idx >= 0: self.combo_music_mode.setCurrentIndex(idx)
            if hasattr(self, 'chk_ui_music'): self.chk_ui_music.setChecked(True)
            if hasattr(self, 'chk_sound'): self.chk_sound.setChecked(True)

        self._on_setting_live_changed()

    # ------------------- Live Settings Sync -------------------
    def _on_setting_live_changed(self):
        if not hasattr(self, 'chk_startup') or not hasattr(self, 'combo_theme'):
            return
        self.settings["run_on_startup"] = self.chk_startup.isChecked()
        self.settings["sound_enabled"] = self.chk_sound.isChecked()
        self.settings["sound_volume"] = self.slider_volume.value() / 100.0
        if hasattr(self, 'combo_sound_theme'):
            self.settings["sound_theme"] = self.combo_sound_theme.currentData() or "fluid"
        else:
            self.settings["sound_theme"] = "fluid"
        self.settings["enable_music_overlay"] = self.chk_music.isChecked()
        self.settings["music_overlay_mode"] = self.combo_music_mode.currentData() or "auto"
        if hasattr(self, 'combo_paused_media'):
            self.settings["paused_media_behavior"] = self.combo_paused_media.currentData() or "show_minimal"
        if hasattr(self, 'combo_media_style'):
            self.settings["island_media_style"] = self.combo_media_style.currentData() or "vinyl"
        if hasattr(self, 'combo_media_visibility'):
            self.settings["island_media_visibility"] = self.combo_media_visibility.currentData() or "auto_hide"
        if hasattr(self, 'chk_vinyl_rot'):
            self.settings["enable_vinyl_rotation"] = self.chk_vinyl_rot.isChecked()
        theme_val = self.combo_theme.currentData() or "dark"
        self.settings["theme"] = theme_val
        if hasattr(self, 'combo_layout_style'):
            self.settings["ui_theme_style"] = self.combo_layout_style.currentData() or "classic" 
        if hasattr(self, 'combo_side_view') and self.combo_side_view.currentData() is not None:
            self.settings["side_view"] = self.combo_side_view.currentData()
        self.settings["edge"] = self.combo_edge.currentText()
        self.settings["edge_trigger_mode"] = self.combo_mode.currentData() or "hover"
        if hasattr(self, 'shortcut_selector'):
            self.settings["hotkey"] = self.shortcut_selector.get_hotkey_string()
        if hasattr(self, 'chk_auto_update'):
            self.settings["enable_auto_update"] = self.chk_auto_update.isChecked()
        self.settings["animation_style"] = self.combo_anim.currentData() or "fluid"

        self.settings["opacity"] = self.slider_opacity.value() / 100.0

        if hasattr(self, 'combo_edge_color_mode'):
            self.settings["edge_bar_color_mode"] = self.combo_edge_color_mode.currentData() or "theme"
        if hasattr(self, 'slider_edge_width'):
            self.settings["edge_bar_width"] = self.slider_edge_width.value()
        if hasattr(self, 'slider_edge_thickness'):
            self.settings["edge_bar_thickness"] = self.slider_edge_thickness.value()
        if hasattr(self, 'chk_radial_menu'):
            self.settings["radial_menu_enabled"] = self.chk_radial_menu.isChecked()
        if hasattr(self, 'combo_radial_key'):
            self.settings["radial_summon_key"] = self.combo_radial_key.currentData() or "Alt"
        if hasattr(self, 'slider_radial_hold'):
            self.settings["radial_summon_hold_ms"] = self.slider_radial_hold.value()
        if hasattr(self, 'chk_radial_shake'):
            self.settings["radial_shake_dismiss_enabled"] = self.chk_radial_shake.isChecked()
        if hasattr(self, 'chk_radial_magic'):
            self.settings["radial_magic_cursor"] = self.chk_radial_magic.isChecked()
        if hasattr(self, 'chk_radial_bottom_music'):
            self.settings["radial_bottom_music_overlay"] = self.chk_radial_bottom_music.isChecked()
        if hasattr(self, 'chk_radial_search'):
            self.settings["radial_search_enabled"] = self.chk_radial_search.isChecked()
        if hasattr(self, 'chk_radial_qs'):
            self.settings["radial_qs_enabled"] = self.chk_radial_qs.isChecked()
        if hasattr(self, 'chk_radial_phone'):
            self.settings["radial_phone_enabled"] = self.chk_radial_phone.isChecked()
        if hasattr(self, 'chk_hide_edge_bar'):
            self.settings["hide_edge_bar"] = self.chk_hide_edge_bar.isChecked()
        if hasattr(self, 'chk_edge_music'):
            self.settings["edge_bar_music_display"] = self.chk_edge_music.isChecked()
        if hasattr(self, 'chk_edge_infomatic'):
            self.settings["edge_bar_infomatic"] = self.chk_edge_infomatic.isChecked()
        if hasattr(self, 'chk_dynamic_max_delay'):
            self.settings["dynamic_maximized_delay"] = self.chk_dynamic_max_delay.isChecked()
        if hasattr(self, 'combo_notch_style') and self.combo_notch_style.currentData():
            self.settings["edge_notch_style"] = self.combo_notch_style.currentData()
        if hasattr(self, 'combo_worded_mode') and self.combo_worded_mode.currentData():
            self.settings["edge_worded_mode"] = self.combo_worded_mode.currentData()
        if hasattr(self, 'edit_notch_text'):
            self.settings["edge_notch_text"] = self.edit_notch_text.text().strip() or "ODD"

        # UI Element Visibility Settings
        if hasattr(self, 'chk_ui_plus'):
            self.settings["ui_show_plus_button"] = self.chk_ui_plus.isChecked()
        if hasattr(self, 'chk_ui_quick_settings'):
            self.settings["ui_show_quick_settings_button"] = self.chk_ui_quick_settings.isChecked()
        if hasattr(self, 'chk_ui_music'):
            self.settings["ui_show_music_button"] = self.chk_ui_music.isChecked()
        if hasattr(self, 'chk_ui_lens'):
            self.settings["ui_show_lens_button"] = self.chk_ui_lens.isChecked()
        if hasattr(self, 'chk_ui_settings'):
            self.settings["ui_show_settings_button"] = self.chk_ui_settings.isChecked()
        if hasattr(self, 'chk_ui_edge_bar'):
            self.settings["ui_show_edge_indicator"] = self.chk_ui_edge_bar.isChecked()
        if hasattr(self, 'chk_ui_power_controls'):
            self.settings["ui_show_power_controls"] = self.chk_ui_power_controls.isChecked()
        if hasattr(self, 'combo_action_btn'):
            self.settings["search_pill_action_button"] = self.combo_action_btn.currentData() or "both"

        # Productivity Module Toggles
        if hasattr(self, 'chk_mod_clip'):
            self.settings["enable_clipboard_history"] = self.chk_mod_clip.isChecked()
        if hasattr(self, 'chk_mod_notes'):
            self.settings["enable_quick_notes"] = self.chk_mod_notes.isChecked()
        if hasattr(self, 'chk_mod_conv'):
            self.settings["enable_unit_converter"] = self.chk_mod_conv.isChecked()
        if hasattr(self, 'chk_mod_sys'):
            self.settings["enable_system_commands"] = self.chk_mod_sys.isChecked()
        if hasattr(self, 'chk_mod_clock'):
            self.settings["enable_world_clock"] = self.chk_mod_clock.isChecked()
        if hasattr(self, 'chk_mod_color'):
            self.settings["enable_color_inspector"] = self.chk_mod_color.isChecked()
        if hasattr(self, 'chk_mod_calc'):
            self.settings["enable_calculator"] = self.chk_mod_calc.isChecked()
        if hasattr(self, 'chk_mod_web'):
            self.settings["enable_web_shortcuts"] = self.chk_mod_web.isChecked()
        if hasattr(self, 'chk_mod_fallbacks'):
            self.settings["enable_web_fallbacks"] = self.chk_mod_fallbacks.isChecked()
        if hasattr(self, 'chk_mod_messaging'):
            self.settings["enable_quick_messaging"] = self.chk_mod_messaging.isChecked()
        if hasattr(self, 'combo_messaging_provider') and self.combo_messaging_provider.currentData():
            self.settings["messaging_provider"] = self.combo_messaging_provider.currentData()

        # Weather Settings
        if hasattr(self, 'chk_enable_weather'):
            self.settings["enable_weather_widget"] = self.chk_enable_weather.isChecked()
        if hasattr(self, 'edit_weather_location'):
            self.settings["weather_location"] = self.edit_weather_location.text().strip() or "Auto-detect"
        if hasattr(self, 'combo_weather_slot') and self.combo_weather_slot.currentData():
            self.settings["weather_replace_slot"] = self.combo_weather_slot.currentData()
        if hasattr(self, 'combo_weather_unit') and self.combo_weather_unit.currentData():
            self.settings["weather_unit"] = self.combo_weather_unit.currentData()

        # Android Phone Mirroring Settings
        if hasattr(self, 'chk_enable_android_mirror'):
            self.settings["enable_android_mirror"] = self.chk_enable_android_mirror.isChecked()
        if hasattr(self, 'combo_android_mirror_slot') and self.combo_android_mirror_slot.currentData():
            self.settings["android_mirror_replace_slot"] = self.combo_android_mirror_slot.currentData()

        # Dynamic Island Settings (Always enabled)
        self.settings["enable_dynamic_island"] = True
        if hasattr(self, 'chk_island_media'):
            self.settings["island_show_media_hud"] = self.chk_island_media.isChecked()
        if hasattr(self, 'chk_island_volume'):
            self.settings["island_show_volume_hud"] = self.chk_island_volume.isChecked()
        if hasattr(self, 'chk_island_battery'):
            self.settings["island_show_battery_hud"] = self.chk_island_battery.isChecked()
        if hasattr(self, 'chk_island_timer'):
            self.settings["island_show_timer_ticker"] = self.chk_island_timer.isChecked()
        if hasattr(self, 'chk_island_caps'):
            self.settings["island_show_caps_lock_hud"] = self.chk_island_caps.isChecked()
        if hasattr(self, 'chk_island_clip'):
            self.settings["island_show_clipboard_hud"] = self.chk_island_clip.isChecked()
        if hasattr(self, 'chk_island_downloads'):
            self.settings["enable_download_mode"] = self.chk_island_downloads.isChecked()
        if hasattr(self, 'chk_island_activity_mem'):
            self.settings["enable_activity_memory"] = self.chk_island_activity_mem.isChecked()
        if hasattr(self, 'chk_island_reminders'):
            self.settings["enable_island_reminders"] = self.chk_island_reminders.isChecked()
        if hasattr(self, 'chk_island_notifications'):
            self.settings["island_show_system_notifications"] = self.chk_island_notifications.isChecked()
        if hasattr(self, 'combo_notification_duration') and self.combo_notification_duration.currentData() is not None:
            self.settings["notification_duration_sec"] = self.combo_notification_duration.currentData()

        # Water / Hydration Reminder Settings
        if hasattr(self, 'bottle_selector'):
            self.settings["water_bottle_style"] = self.bottle_selector.selected_style
            self.settings["water_daily_liters"] = self.bottle_selector.get_daily_liters()
            self.settings["water_daily_goal"] = max(1, int(round(self.settings["water_daily_liters"] / 0.25)))
        if hasattr(self, 'chk_water_reminder'):
            self.settings["enable_water_reminder"] = self.chk_water_reminder.isChecked()
        if hasattr(self, 'mode_water'):
            self.settings["water_reminder_mode"] = self.mode_water.current_mode
        if hasattr(self, 'combo_water_interval') and self.combo_water_interval.currentData() is not None:
            self.settings["water_reminder_interval_min"] = int(self.combo_water_interval.currentData())
        if hasattr(self, 'chk_water_working_hours'):
            self.settings["water_working_hours_only"] = self.chk_water_working_hours.isChecked()
        if hasattr(self, 'edit_water_start'):
            self.settings["water_start_time"] = self.edit_water_start.text().strip() or "09:00"
        if hasattr(self, 'edit_water_end'):
            self.settings["water_end_time"] = self.edit_water_end.text().strip() or "17:00"

        # Wellness Reminders (Eye Rest, Posture, Ventilation)
        if hasattr(self, 'chk_eye_rest'):
            self.settings["enable_eye_rest_reminder"] = self.chk_eye_rest.isChecked()
        if hasattr(self, 'mode_eye_rest'):
            self.settings["eye_rest_reminder_mode"] = self.mode_eye_rest.current_mode
        if hasattr(self, 'combo_eye_interval') and self.combo_eye_interval.currentData() is not None:
            self.settings["eye_rest_interval_min"] = int(self.combo_eye_interval.currentData())

        if hasattr(self, 'chk_posture'):
            self.settings["enable_posture_reminder"] = self.chk_posture.isChecked()
        if hasattr(self, 'combo_posture_interval') and self.combo_posture_interval.currentData() is not None:
            self.settings["posture_interval_min"] = int(self.combo_posture_interval.currentData())

        if hasattr(self, 'chk_ventilation'):
            self.settings["enable_ventilation_reminder"] = self.chk_ventilation.isChecked()
        if hasattr(self, 'combo_vent_interval') and self.combo_vent_interval.currentData() is not None:
            self.settings["ventilation_interval_min"] = int(self.combo_vent_interval.currentData())

        # Laptop Battery Preservation & Storage Purge
        if hasattr(self, 'chk_battery_health'):
            self.settings["enable_battery_health_alert"] = self.chk_battery_health.isChecked()
        if hasattr(self, 'chk_battery_auto_detect'):
            self.settings["battery_auto_detect_plug"] = self.chk_battery_auto_detect.isChecked()
        if hasattr(self, 'chk_system_needs'):
            self.settings["system_needs_intelligence"] = self.chk_system_needs.isChecked()
        if hasattr(self, 'spin_battery_high'):
            self.settings["battery_high_limit"] = int(self.spin_battery_high.value())
        if hasattr(self, 'spin_battery_low'):
            self.settings["battery_low_limit"] = int(self.spin_battery_low.value())

        if hasattr(self, 'chk_storage_purge'):
            self.settings["enable_storage_purge_reminder"] = self.chk_storage_purge.isChecked()
        if hasattr(self, 'combo_purge_interval') and self.combo_purge_interval.currentData() is not None:
            self.settings["storage_purge_interval_days"] = int(self.combo_purge_interval.currentData())

        action_val = None
        if hasattr(self, 'combo_action_btn') and self.combo_action_btn.currentData():
            action_val = self.combo_action_btn.currentData()
        if action_val:
            self.settings["search_pill_action_button"] = action_val

        self._sync_home_quick_controls_from_main()

        # Only reapply global stylesheets if the theme actually changed (massive performance boost!)
        new_theme = str(self.settings.get("theme", "dark")).lower()
        if getattr(self, "_current_applied_theme", None) != new_theme:
            self._current_applied_theme = new_theme
            self.apply_global_theme()

        self._update_edge_preview()

        # Debounce disk persistence so rapid slider scrubbing and clicks do not block the UI thread
        if hasattr(self, '_save_debounce_timer'):
            self._save_debounce_timer.start()
        else:
            self._flush_save_settings()

        # Only update startup registry if the value actually toggled
        new_startup = bool(self.settings.get("run_on_startup", True))
        if getattr(self, "_last_synced_startup", None) != new_startup:
            self._last_synced_startup = new_startup
            try:
                set_startup_enabled(new_startup)
            except Exception:
                pass

        self.settings_changed.emit(self.settings)

    def _flush_save_settings(self):
        try:
            save_settings(self.settings)
        except Exception:
            pass

    def _on_bottle_selected(self, key: str, liters: float):
        self.settings["water_bottle_style"] = key
        self.settings["water_daily_liters"] = liters
        self.settings["water_daily_goal"] = max(1, int(round(liters / 0.25)))
        try:
            from odd_reminder import WaterReminderManager
            WaterReminderManager.get_instance(self.settings).update_settings(self.settings)
        except Exception as e:
            print(f"[ODD Settings] Error notifying water manager of bottle selection: {e}")
        self._on_setting_live_changed()

    def _on_water_mode_changed(self, mode: str):
        self.settings["water_reminder_mode"] = mode
        try:
            from odd_reminder import WaterReminderManager
            WaterReminderManager.get_instance(self.settings).update_settings(self.settings)
        except Exception as e:
            print(f"[ODD Settings] Error notifying water manager of mode change: {e}")
        self._on_setting_live_changed()

    def _on_eye_mode_changed(self, mode: str):
        self.settings["eye_rest_reminder_mode"] = mode
        try:
            from odd_wellness import WellnessManager
            WellnessManager.get_instance(self.settings).update_settings(self.settings)
        except Exception as e:
            print(f"[ODD Settings] Error notifying wellness manager of eye mode change: {e}")
        self._on_setting_live_changed()

    def _select_preset_color(self, hex_code: str):
        self.settings["edge_bar_color"] = hex_code
        if hasattr(self, 'combo_edge_color_mode'):
            idx = self.combo_edge_color_mode.findData("preset")
            if idx >= 0:
                self.combo_edge_color_mode.setCurrentIndex(idx)
        self._on_setting_live_changed()

    def _open_custom_color_picker(self):
        curr_hex = self.settings.get("edge_bar_color", "#D4D4D8")
        col = QColorDialog.getColor(QColor(curr_hex), self, "Select Edge Bar Color")
        if col.isValid():
            self.settings["edge_bar_color"] = col.name()
            if hasattr(self, 'combo_edge_color_mode'):
                idx = self.combo_edge_color_mode.findData("custom")
                if idx >= 0:
                    self.combo_edge_color_mode.setCurrentIndex(idx)
            self._on_setting_live_changed()

    def _on_weather_location_edited(self):
        typed = self.edit_weather_location.text().strip()
        if not typed:
            typed = "Auto-detect"
        self.settings["weather_location"] = typed
        self._on_setting_live_changed()

        def _resolve_and_update():
            try:
                import odd_weather
                loc_text = self.settings.get("weather_location", "Auto-detect")
                if loc_text.lower() not in ("", "auto", "auto-detect", "current", "my location", "local"):
                    try:
                        lat, lon, friendly_city, country = odd_weather.resolve_location_coordinates(loc_text)
                        disp_name = friendly_city
                    except Exception:
                        disp_name = loc_text
                else:
                    disp_name = "Auto-detect"

                def _apply_in_gui():
                    if hasattr(self, 'edit_weather_location') and self.edit_weather_location:
                        self.edit_weather_location.blockSignals(True)
                        self.edit_weather_location.setText(disp_name)
                        self.edit_weather_location.blockSignals(False)
                    self.settings["weather_location"] = disp_name
                    self._on_setting_live_changed()
                    import odd_weather
                    odd_weather.WeatherManager.get_instance().refresh(force=True, settings=self.settings)

                QTimer.singleShot(0, _apply_in_gui)
            except Exception as e:
                print(f"[ODD Settings] Weather location error: {e}")

        threading.Thread(target=_resolve_and_update, daemon=True, name="ODD_Weather_Resolve").start()

    def _update_edge_preview(self):
        if not hasattr(self, 'edge_bar_preview') or not hasattr(self, 'combo_edge_color_mode'):
            return
        cm = self.combo_edge_color_mode.currentData() or "theme"
        hex_c = self.settings.get("edge_bar_color", "#D4D4D8")
        w = self.slider_edge_width.value() if hasattr(self, 'slider_edge_width') else 140
        t = self.slider_edge_thickness.value() if hasattr(self, 'slider_edge_thickness') else 4
        glow = False
        thm = self.combo_theme.currentData() or "dark"
        n_style = self.combo_notch_style.currentData() if hasattr(self, 'combo_notch_style') else self.settings.get("edge_notch_style", "bar")
        n_text = self.edit_notch_text.text().strip() if hasattr(self, 'edit_notch_text') else self.settings.get("edge_notch_text", "ODD")
        self.edge_bar_preview.update_preview(cm, hex_c, w, t, glow, thm, notch_style=n_style, notch_text=n_text)

    def _trigger_test_water_reminder(self):
        try:
            from odd_reminder import WaterReminderManager
            WaterReminderManager.get_instance().trigger_test_alert()
        except Exception as e:
            print(f"[ODD Settings] Error triggering test water reminder: {e}")

    def _trigger_test_eye_rest(self):
        try:
            from odd_wellness import WellnessManager
            WellnessManager.get_instance().trigger_test_eye_rest()
        except Exception as e:
            print(f"[ODD Settings] Error triggering test eye rest: {e}")

    def _trigger_test_posture(self):
        try:
            from odd_wellness import WellnessManager
            WellnessManager.get_instance().trigger_test_posture()
        except Exception as e:
            print(f"[ODD Settings] Error triggering test posture: {e}")

    def _trigger_test_ventilation(self):
        try:
            from odd_wellness import WellnessManager
            WellnessManager.get_instance().trigger_test_ventilation()
        except Exception as e:
            print(f"[ODD Settings] Error triggering test ventilation: {e}")

    def _trigger_test_battery(self):
        try:
            from odd_wellness import WellnessManager
            WellnessManager.get_instance().trigger_test_battery()
        except Exception as e:
            print(f"[ODD Settings] Error triggering test battery: {e}")

    def _trigger_test_storage(self):
        try:
            from odd_wellness import WellnessManager
            WellnessManager.get_instance().trigger_test_storage()
        except Exception as e:
            print(f"[ODD Settings] Error triggering test storage: {e}")

    def _trigger_execute_storage_clean(self):
        try:
            from odd_wellness import WellnessManager
            res = WellnessManager.get_instance().execute_storage_cleanup()
            msg = "Recycle Bin has been emptied, and the Downloads folder was opened for you to review large stale files."
            QMessageBox.information(self, "Storage Cleaned", msg)
        except Exception as e:
            QMessageBox.warning(self, "Storage Cleanup", f"Failed: {e}")

    # ------------------- PAGE 0: Radial Arc & Cursor HUD -------------------
    def create_radial_tab(self) -> QWidget:
        scroll, layout = self._create_page_scroll(
            "Radial Arc & Cursor HUD",
            "Configure the orbital squircle arc menu, hold summon key, fast cursor search panel, and contextual companion overlays."
        )

        # Hero Banner
        hero_card = create_setting_card()
        h_layout = QVBoxLayout(hero_card)
        h_layout.setContentsMargins(18, 16, 18, 16)
        h_layout.setSpacing(6)
        hero_title = QLabel("Cursor-Centric Desktop Experience", hero_card)
        hero_title.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.DemiBold))
        h_layout.addWidget(hero_title)
        hero_desc = QLabel(
            "ODD's radial interface centers all launching, contextual searching, media control, and quick system switches "
            "directly around your mouse cursor. Hold your activation key anywhere on screen to summon the squircle arc.",
            hero_card
        )
        hero_desc.setWordWrap(True)
        hero_desc.setFont(QFont("Segoe UI Variable Text", 9))
        hero_desc.setStyleSheet("color: #A1A1AA; line-height: 1.4;")
        h_layout.addWidget(hero_desc)
        layout.addWidget(hero_card)

        # Group 1: Orbital Arc Menu & Summon Key
        self._add_group_title(layout, "Orbital Arc Menu & Hold Summon")
        card_summon = create_setting_card()
        cs_layout = QVBoxLayout(card_summon)
        cs_layout.setContentsMargins(0, 2, 0, 2)
        cs_layout.setSpacing(0)

        self.chk_radial_menu = self._make_toggle(self.settings.get("radial_menu_enabled", True))
        self.chk_radial_menu.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cs_layout,
            "Enable Radial Arc Menu",
            "Hold activation key to summon ODD's semi-circular arc menu around your cursor",
            self.chk_radial_menu,
            add_divider=True
        )

        self.combo_radial_key = create_styled_combobox(width=220)
        self.combo_radial_key.addItem("Alt (Default)", "Alt")
        self.combo_radial_key.addItem("Ctrl", "Ctrl")
        self.combo_radial_key.addItem("Shift", "Shift")
        self.combo_radial_key.addItem("Windows Key", "Win")
        curr_rad_key = self.settings.get("radial_summon_key", "Alt")
        idx_rk = self.combo_radial_key.findData(curr_rad_key)
        if idx_rk >= 0:
            self.combo_radial_key.setCurrentIndex(idx_rk)
        self.combo_radial_key.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cs_layout,
            "Summon Activation Key",
            "Hold this key to summon the radial menu (a quick tap triggers default Windows behavior)",
            self.combo_radial_key,
            add_divider=True
        )

        hold_ctrl = QWidget()
        hold_row = QHBoxLayout(hold_ctrl)
        hold_row.setContentsMargins(0, 0, 0, 0)
        hold_row.setSpacing(10)
        self.slider_radial_hold = QSlider(Qt.Orientation.Horizontal)
        self.slider_radial_hold.setRange(250, 1200)
        self.slider_radial_hold.setSingleStep(50)
        self.slider_radial_hold.setFixedWidth(135)
        curr_hold = int(self.settings.get("radial_summon_hold_ms", 400))
        self.slider_radial_hold.setValue(curr_hold)
        self.lbl_radial_hold = QLabel(f"{curr_hold} ms")
        self.lbl_radial_hold.setFixedWidth(55)
        self.lbl_radial_hold.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        def _on_hold_changed(val):
            self.lbl_radial_hold.setText(f"{val} ms")
            self._on_setting_live_changed()
        self.slider_radial_hold.valueChanged.connect(_on_hold_changed)
        hold_row.addWidget(self.slider_radial_hold)
        hold_row.addWidget(self.lbl_radial_hold)
        self._add_setting_row(
            cs_layout,
            "Hold Duration",
            "How long the activation key must be held to open the radial menu (Default: 400 ms)",
            hold_ctrl,
            add_divider=True
        )

        self.chk_radial_magic = self._make_toggle(self.settings.get("radial_magic_cursor", True))
        self.chk_radial_magic.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cs_layout,
            "Magic Cursor & Shine Reflection",
            "Animated specular light reflections and glowing filaments connecting the cursor to radial items",
            self.chk_radial_magic,
            add_divider=True
        )

        self.chk_radial_shake = self._make_toggle(self.settings.get("radial_shake_dismiss_enabled", True))
        self.chk_radial_shake.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cs_layout,
            "Shake Cursor to Dismiss",
            "Deliberately shake the cursor back and forth to dismiss the radial menu instantly",
            self.chk_radial_shake,
            add_divider=False
        )
        layout.addWidget(card_summon)

        # Group 2: Contextual Overlays & Integrated Tools
        self._add_group_title(layout, "Contextual Overlays & Integrated Tools")
        card_overlays = create_setting_card()
        co_layout = QVBoxLayout(card_overlays)
        co_layout.setContentsMargins(0, 2, 0, 2)
        co_layout.setSpacing(0)

        self.chk_radial_search = self._make_toggle(self.settings.get("radial_search_enabled", True))
        self.chk_radial_search.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            co_layout,
            "Fast Cursor Search Panel",
            "Fast, non-blocking search panel opening at cursor with instant category filters (Apps, Folders, Files, Settings)",
            self.chk_radial_search,
            add_divider=True
        )

        self.chk_radial_qs = self._make_toggle(self.settings.get("radial_qs_enabled", True))
        self.chk_radial_qs.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            co_layout,
            "Contextual Quick Settings",
            "Modern 4-quadrant squircle toggles with edge-aware volume & brightness popups and direct settings access",
            self.chk_radial_qs,
            add_divider=True
        )

        self.chk_radial_phone = self._make_toggle(self.settings.get("radial_phone_enabled", True))
        self.chk_radial_phone.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            co_layout,
            "Phone Mirror Companion",
            "Dedicated cursor overlay for Android scrcpy wireless mirroring, screen orientation, and clipboard sync",
            self.chk_radial_phone,
            add_divider=True
        )

        self.chk_radial_bottom_music = self._make_toggle(self.settings.get("radial_bottom_music_overlay", True))
        self.chk_radial_bottom_music.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            co_layout,
            "Bottom Music Mini-Overlay",
            "Minimal media strip docked at the bottom of the radial menu showing track name, artist, and Play/Pause button",
            self.chk_radial_bottom_music,
            add_divider=False
        )
        layout.addWidget(card_overlays)

        layout.addStretch()
        return scroll

    # ------------------- PAGE 3: General & Shortcuts -------------------
    def create_general_tab(self) -> QWidget:
        scroll, layout = self._create_page_scroll(
            "General Preferences",
            "Configure your activation shortcut, mouse edge trigger, Windows startup, audio feedback, and wellness reminders."
        )

        # Group 1: Quick Setup & System Preferences
        self._add_group_title(layout, "Quick Setup & System Preferences")
        card_quick = create_setting_card()
        cq_layout = QVBoxLayout(card_quick)
        cq_layout.setContentsMargins(0, 2, 0, 2)
        cq_layout.setSpacing(0)

        curr_hk = self.settings.get("hotkey", "Alt+Space")
        self.shortcut_selector = GlobalShortcutSelector(curr_hk)
        def _on_hk_changed(new_hk):
            self.settings["hotkey"] = new_hk
            if hasattr(self, 'combo_mode') and self.combo_mode.count() >= 4:
                self.combo_mode.setItemText(3, f"Keyboard shortcut only ({new_hk})")
            self._on_setting_live_changed()
        self.shortcut_selector.hotkey_changed.connect(_on_hk_changed)
        self._add_setting_row(
            cq_layout,
            "Activation Shortcut",
            "Press this key combination anywhere on your PC to open or hide ODD (Default: Alt + Space)",
            self.shortcut_selector,
            add_divider=True
        )

        self.combo_mode = create_styled_combobox(width=250)
        self.combo_mode.addItem(f"Keyboard shortcut only ({curr_hk})", "hotkey_only")
        self.combo_mode.addItem("Move mouse to top screen edge (Fast)", "hover")
        self.combo_mode.addItem("Move mouse to top edge with slight delay", "deliberate")
        self.combo_mode.addItem("Click top notch indicator", "click")
        curr_mode = self.settings.get("edge_trigger_mode", "hotkey_only")
        idx_m = self.combo_mode.findData(curr_mode)
        if idx_m >= 0:
            self.combo_mode.setCurrentIndex(idx_m)
        self.combo_mode.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cq_layout,
            "Screen Edge Trigger",
            "Choose how ODD appears when using your mouse or keyboard",
            self.combo_mode,
            add_divider=True
        )

        self.chk_startup = self._make_toggle(self.settings.get("run_on_startup", True))
        self.chk_startup.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cq_layout,
            "Start with Windows",
            "Automatically launch ODD in the background when your computer turns on",
            self.chk_startup,
            add_divider=False
        )
        layout.addWidget(card_quick)

        # Group 2: Audio Feedback
        self._add_group_title(layout, "Sound & Audio Feedback")
        card_sound = create_setting_card()
        c2_layout = QVBoxLayout(card_sound)
        c2_layout.setContentsMargins(0, 2, 0, 2)
        c2_layout.setSpacing(0)
        c2_layout.setSpacing(0)

        self.chk_sound = self._make_toggle(self.settings.get("sound_enabled", True))
        self._add_setting_row(
            c2_layout,
            "Enable Sound Effects",
            "Play subtle organic audio feedback when surfacing the search bar and selecting items",
            self.chk_sound,
            add_divider=True
        )

        self.combo_sound_theme = create_styled_combobox(width=235)
        self.combo_sound_theme.addItem("Fluid (Organic Liquid Drops)", "fluid")
        self.combo_sound_theme.setCurrentIndex(0)
        self._add_setting_row(
            c2_layout,
            "Sound Profile",
            "Select the acoustic character for UI interactions",
            self.combo_sound_theme,
            add_divider=True
        )

        vol_ctrl = QWidget()
        vol_row = QHBoxLayout(vol_ctrl)
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(10)

        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setFixedWidth(135)
        curr_vol = int(self.settings.get("sound_volume", 0.70) * 100)
        self.slider_volume.setValue(curr_vol)
        vol_row.addWidget(self.slider_volume)

        self.vol_val_lbl = QLabel(f"{curr_vol}%")
        self.vol_val_lbl.setFixedWidth(36)
        self.vol_val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vol_row.addWidget(self.vol_val_lbl)

        self.btn_test_sound = QPushButton("Test")
        self.btn_test_sound.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_sound.clicked.connect(lambda: odd_sound.play_preview(self.slider_volume.value() / 100.0, style="fluid"))
        vol_row.addWidget(self.btn_test_sound)

        def _on_vol_changed(v):
            self.vol_val_lbl.setText(f"{v}%")
            if self.chk_sound.isChecked():
                odd_sound.play_preview(v / 100.0, style="fluid")

        self.slider_volume.valueChanged.connect(_on_vol_changed)
        self.chk_sound.toggled.connect(self.slider_volume.setEnabled)
        self.chk_sound.toggled.connect(self.combo_sound_theme.setEnabled)
        self.chk_sound.toggled.connect(self.btn_test_sound.setEnabled)
        self.slider_volume.setEnabled(self.chk_sound.isChecked())
        self.combo_sound_theme.setEnabled(self.chk_sound.isChecked())
        self.btn_test_sound.setEnabled(self.chk_sound.isChecked())

        self._add_setting_row(
            c2_layout,
            "Effect Volume",
            "Adjust the playback level of UI sound effects",
            vol_ctrl,
            add_divider=False
        )
        layout.addWidget(card_sound)

        # Group 4: Ergonomic & Vision Health
        self._add_group_title(layout, "Ergonomic & Vision Health")
        card_ergo = create_setting_card()
        ce_layout = QVBoxLayout(card_ergo)
        ce_layout.setContentsMargins(0, 2, 0, 2)
        ce_layout.setSpacing(0)

        self.chk_eye_rest = self._make_toggle(self.settings.get("enable_eye_rest_reminder", True))
        self.chk_eye_rest.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Eye Rest (Hourly Vision Care)",
            "Every 1 hour, prompts you to look at something 20 feet away for 20 seconds to prevent digital eye strain & headaches",
            self.chk_eye_rest,
            add_divider=True
        )

        cur_eye_mode = str(self.settings.get("eye_rest_reminder_mode", "work")).lower()
        self.mode_eye_rest = ModeSegmentedSelector(cur_eye_mode)
        self.mode_eye_rest.mode_changed.connect(self._on_eye_mode_changed)
        self._add_setting_row(
            ce_layout,
            "Eye Rest Trigger Mode",
            "Choose whether to count active keyboard/mouse work hours or standard clock time",
            self.mode_eye_rest,
            add_divider=True
        )

        self.combo_eye_interval = create_styled_combobox(width=230)
        self.combo_eye_interval.addItem("Every 1 hour (Default)", 60)
        self.combo_eye_interval.addItem("Every 45 minutes", 45)
        self.combo_eye_interval.addItem("Every 30 minutes", 30)
        idx_ei = self.combo_eye_interval.findData(int(self.settings.get("eye_rest_interval_min", 60)))
        if idx_ei >= 0:
            self.combo_eye_interval.setCurrentIndex(idx_ei)
        self.combo_eye_interval.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Eye Rest Frequency",
            "Interval between vision rest alerts",
            self.combo_eye_interval,
            add_divider=True
        )

        self.chk_posture = self._make_toggle(self.settings.get("enable_posture_reminder", True))
        self.chk_posture.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Posture & Desk Stretch Alerts",
            "Prompts you to roll your shoulders, reset spinal posture, stand up, or do a quick 2-minute desk stretch",
            self.chk_posture,
            add_divider=True
        )

        self.combo_posture_interval = create_styled_combobox(width=230)
        self.combo_posture_interval.addItem("Every 45 minutes", 45)
        self.combo_posture_interval.addItem("Every 60 minutes (Recommended)", 60)
        self.combo_posture_interval.addItem("Every 90 minutes", 90)
        idx_pi = self.combo_posture_interval.findData(int(self.settings.get("posture_interval_min", 60)))
        if idx_pi >= 0:
            self.combo_posture_interval.setCurrentIndex(idx_pi)
        self.combo_posture_interval.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Posture Alert Frequency",
            "Interval between posture and desk stretch reminders",
            self.combo_posture_interval,
            add_divider=True
        )

        self.chk_ventilation = self._make_toggle(self.settings.get("enable_ventilation_reminder", True))
        self.chk_ventilation.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Ventilation & Fresh Air Reminders",
            "Prompts you to crack open a window or step outside for fresh air, preventing CO2 buildup that causes afternoon drowsiness",
            self.chk_ventilation,
            add_divider=True
        )

        self.combo_vent_interval = create_styled_combobox(width=230)
        self.combo_vent_interval.addItem("Every 2 hours", 120)
        self.combo_vent_interval.addItem("Every 2.5 hours", 150)
        self.combo_vent_interval.addItem("Every 3 hours (Recommended)", 180)
        idx_vi = self.combo_vent_interval.findData(int(self.settings.get("ventilation_interval_min", 120)))
        if idx_vi >= 0:
            self.combo_vent_interval.setCurrentIndex(idx_vi)
        self.combo_vent_interval.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Ventilation Alert Frequency",
            "Interval between fresh air reminders",
            self.combo_vent_interval,
            add_divider=True
        )

        self.chk_water_reminder = self._make_toggle(self.settings.get("enable_water_reminder", True))
        self.chk_water_reminder.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Enable Water Reminders",
            "Smart periodic hydration alerts delivered directly through the Dynamic Island",
            self.chk_water_reminder,
            add_divider=True
        )

        cur_bottle_style = str(self.settings.get("water_bottle_style", "broader_2l"))
        self.bottle_selector = BottleSelectorWidget(cur_bottle_style)
        self.bottle_selector.bottle_selected.connect(self._on_bottle_selected)

        bottle_box = QWidget()
        bb_layout = QVBoxLayout(bottle_box)
        bb_layout.setContentsMargins(16, 12, 16, 14)
        bb_layout.setSpacing(8)

        lbl_target_title = QLabel("Daily Hydration Target")
        lbl_target_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        lbl_target_desc = QLabel("Choose how much water you need daily. Click a bottle to configure your goal:")
        lbl_target_desc.setStyleSheet("font-size: 11px; color: #A1A1AA;")
        lbl_target_desc.setWordWrap(True)
        bb_layout.addWidget(lbl_target_title)
        bb_layout.addWidget(lbl_target_desc)
        bb_layout.addWidget(self.bottle_selector)

        ce_layout.addWidget(bottle_box)
        ce_layout.addWidget(create_row_divider())

        cur_water_mode = str(self.settings.get("water_reminder_mode", "work")).lower()
        self.mode_water = ModeSegmentedSelector(cur_water_mode)
        self.mode_water.mode_changed.connect(self._on_water_mode_changed)
        self._add_setting_row(
            ce_layout,
            "Water Reminder Mode",
            "Remind whenever you work (active screen time) or within time (clock interval)",
            self.mode_water,
            add_divider=True
        )

        self.combo_water_interval = create_styled_combobox(width=230)
        self.combo_water_interval.addItem("Every 30 minutes (High frequency)", 30)
        self.combo_water_interval.addItem("Every 40 minutes (Intensive hydration)", 40)
        self.combo_water_interval.addItem("Every 60 minutes (Hourly baseline)", 60)
        self.combo_water_interval.addItem("Every 90 minutes (Relaxed interval)", 90)
        self.combo_water_interval.addItem("Every 120 minutes (2 hours)", 120)
        cur_interval = int(self.settings.get("water_reminder_interval_min", 60))
        w_idx = self.combo_water_interval.findData(cur_interval)
        self.combo_water_interval.setCurrentIndex(w_idx if w_idx >= 0 else 2)
        self.combo_water_interval.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Reminder Frequency",
            "Select how often ODD reminds you to drink water",
            self.combo_water_interval,
            add_divider=True
        )

        self.chk_water_working_hours = self._make_toggle(self.settings.get("water_working_hours_only", True))
        self.chk_water_working_hours.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Working Hours Only",
            "Only alert during active desk hours so you are not disturbed off-hours",
            self.chk_water_working_hours,
            add_divider=True
        )

        time_container = QWidget()
        time_layout = QHBoxLayout(time_container)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(8)

        lbl_from = QLabel("From:")
        lbl_from.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        time_layout.addWidget(lbl_from)

        self.edit_water_start = QLineEdit(str(self.settings.get("water_start_time", "09:00")))
        self.edit_water_start.setFixedWidth(56)
        self.edit_water_start.setPlaceholderText("09:00")
        self.edit_water_start.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_water_start.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(255, 255, 255, 0.45);
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        self.edit_water_start.textChanged.connect(self._on_setting_live_changed)
        time_layout.addWidget(self.edit_water_start)

        lbl_to = QLabel("To:")
        lbl_to.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        time_layout.addWidget(lbl_to)

        self.edit_water_end = QLineEdit(str(self.settings.get("water_end_time", "17:00")))
        self.edit_water_end.setFixedWidth(56)
        self.edit_water_end.setPlaceholderText("17:00")
        self.edit_water_end.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_water_end.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(255, 255, 255, 0.45);
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        self.edit_water_end.textChanged.connect(self._on_setting_live_changed)
        time_layout.addWidget(self.edit_water_end)

        self._add_setting_row(
            ce_layout,
            "Active Hours Schedule",
            "Set your desk hours (e.g. 09:00 to 17:00 in 24-hour format)",
            time_container,
            add_divider=True
        )

        preview_btns_box = QWidget()
        pbb_layout = QHBoxLayout(preview_btns_box)
        pbb_layout.setContentsMargins(0, 0, 0, 0)
        pbb_layout.setSpacing(8)

        btn_test_eye = QPushButton("Test Eye Rest")
        btn_test_eye.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test_eye.setFixedHeight(28)
        btn_test_eye.clicked.connect(self._trigger_test_eye_rest)
        pbb_layout.addWidget(btn_test_eye)

        btn_test_post = QPushButton("Test Posture")
        btn_test_post.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test_post.setFixedHeight(28)
        btn_test_post.clicked.connect(self._trigger_test_posture)
        pbb_layout.addWidget(btn_test_post)

        btn_test_vent = QPushButton("Test Fresh Air")
        btn_test_vent.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test_vent.setFixedHeight(28)
        btn_test_vent.clicked.connect(self._trigger_test_ventilation)
        pbb_layout.addWidget(btn_test_vent)

        self.btn_test_water = QPushButton("Test Water")
        self.btn_test_water.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_water.setFixedHeight(28)
        self.btn_test_water.clicked.connect(self._trigger_test_water_reminder)
        pbb_layout.addWidget(self.btn_test_water)

        for b in (btn_test_eye, btn_test_post, btn_test_vent, self.btn_test_water):
            b.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08);
                    color: #FAFAFA;
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.16);
                    border-color: rgba(255, 255, 255, 0.35);
                }
            """)

        self._add_setting_row(
            ce_layout,
            "Preview Health Alerts",
            "Trigger a live test notification in the Dynamic Island right now",
            preview_btns_box,
            add_divider=False
        )
        layout.addWidget(card_ergo)

        # Group 5: Battery Longevity & Storage Hygiene
        self._add_group_title(layout, "Battery Care & Storage Hygiene")
        card_bat_stor = create_setting_card()
        cbs_layout = QVBoxLayout(card_bat_stor)
        cbs_layout.setContentsMargins(0, 2, 0, 2)
        cbs_layout.setSpacing(0)

        self.chk_battery_health = self._make_toggle(self.settings.get("enable_battery_health_alert", True))
        self.chk_battery_health.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cbs_layout,
            "Laptop Battery Longevity Alerts",
            "Prompts you to unplug when battery reaches 80% and plug in when it drops to 30%, extending battery cycle life",
            self.chk_battery_health,
            add_divider=True
        )

        bat_limits_box = QWidget()
        bl_layout = QHBoxLayout(bat_limits_box)
        bl_layout.setContentsMargins(0, 0, 0, 0)
        bl_layout.setSpacing(10)

        lbl_high = QLabel("Unplug at:")
        lbl_high.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        bl_layout.addWidget(lbl_high)

        self.spin_battery_high = QSpinBox()
        self.spin_battery_high.setRange(50, 100)
        self.spin_battery_high.setSuffix("%")
        self.spin_battery_high.setValue(int(self.settings.get("battery_high_limit", 80)))
        self.spin_battery_high.valueChanged.connect(self._on_setting_live_changed)
        bl_layout.addWidget(self.spin_battery_high)

        lbl_low = QLabel("Plug in at:")
        lbl_low.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        bl_layout.addWidget(lbl_low)

        self.spin_battery_low = QSpinBox()
        self.spin_battery_low.setRange(10, 50)
        self.spin_battery_low.setSuffix("%")
        self.spin_battery_low.setValue(int(self.settings.get("battery_low_limit", 30)))
        self.spin_battery_low.valueChanged.connect(self._on_setting_live_changed)
        bl_layout.addWidget(self.spin_battery_low)

        btn_test_bat = QPushButton("Test Alert")
        btn_test_bat.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test_bat.setFixedHeight(26)
        btn_test_bat.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #FAFAFA;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.16);
            }
        """)
        btn_test_bat.clicked.connect(self._trigger_test_battery)
        bl_layout.addWidget(btn_test_bat)

        self._add_setting_row(
            cbs_layout,
            "Battery Health Thresholds",
            "Target charge window for laptop battery preservation (Default: 30% - 80%)",
            bat_limits_box,
            add_divider=True
        )

        self.chk_battery_auto_detect = self._make_toggle(self.settings.get("battery_auto_detect_plug", True))
        self.chk_battery_auto_detect.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cbs_layout,
            "Automatic Charger Detection & Auto-Resolution",
            "Automatically identifies when charger is connected or disconnected, smoothly resolving and dismissing battery reminders without manual button clicks",
            self.chk_battery_auto_detect,
            add_divider=True
        )

        self.chk_system_needs = self._make_toggle(self.settings.get("system_needs_intelligence", True))
        self.chk_system_needs.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cbs_layout,
            "System Needs & Focus Intelligence",
            "Dynamically computes charging ETA, remaining battery runtime, user presence (away detection), and suppresses non-critical popups during full-screen games/video",
            self.chk_system_needs,
            add_divider=True
        )

        self.chk_storage_purge = self._make_toggle(self.settings.get("enable_storage_purge_reminder", True))
        self.chk_storage_purge.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cbs_layout,
            "Storage Purge & Cleanliness Reminders",
            "Periodically prompts to empty the Recycle Bin and clear out Downloads folder; warns when drive is over 80% full",
            self.chk_storage_purge,
            add_divider=True
        )

        self.combo_purge_interval = create_styled_combobox(width=230)
        self.combo_purge_interval.addItem("Every 7 days", 7)
        self.combo_purge_interval.addItem("Every 14 days (2 weeks — Recommended)", 14)
        self.combo_purge_interval.addItem("Every 30 days (Monthly)", 30)
        idx_pi = self.combo_purge_interval.findData(int(self.settings.get("storage_purge_interval_days", 14)))
        if idx_pi >= 0:
            self.combo_purge_interval.setCurrentIndex(idx_pi)
        self.combo_purge_interval.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cbs_layout,
            "Purge Frequency",
            "Cycle interval between storage purge reminders",
            self.combo_purge_interval,
            add_divider=True
        )

        storage_acts_box = QWidget()
        sa_layout = QHBoxLayout(storage_acts_box)
        sa_layout.setContentsMargins(0, 0, 0, 0)
        sa_layout.setSpacing(8)

        btn_clean_now = QPushButton("Empty Recycle Bin & Open Downloads")
        btn_clean_now.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clean_now.setFixedHeight(28)
        btn_clean_now.setStyleSheet("""
            QPushButton {
                background: rgba(16, 185, 129, 0.18);
                color: #34D399;
                border: 1px solid rgba(52, 211, 153, 0.40);
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11.5px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(16, 185, 129, 0.32);
                border-color: rgba(52, 211, 153, 0.70);
                color: #FFFFFF;
            }
        """)
        btn_clean_now.clicked.connect(self._trigger_execute_storage_clean)
        sa_layout.addWidget(btn_clean_now)

        btn_test_storage = QPushButton("Test Alert")
        btn_test_storage.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_test_storage.setFixedHeight(28)
        btn_test_storage.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #FAFAFA;
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(255, 255, 255, 0.16); }
        """)
        btn_test_storage.clicked.connect(self._trigger_test_storage)
        sa_layout.addWidget(btn_test_storage)

        self._add_setting_row(
            cbs_layout,
            "Storage Maintenance Actions",
            "Perform instant cleanup or trigger a preview alert in the Dynamic Island",
            storage_acts_box,
            add_divider=False
        )
        layout.addWidget(card_bat_stor)

        layout.addStretch()
        return scroll

    # ------------------- PAGE 1: Appearance & Animations -------------------
    def create_appearance_tab(self) -> QWidget:
        scroll, layout = self._create_page_scroll(
            "Appearance & Animations",
            "Customize visual themes, liquid spring physics, surface opacity, screen edge placement, and notch styling."
        )

        # Group 1: Theme & Transparency
        self._add_group_title(layout, "Theme & Surface")
        card_theme = create_setting_card()
        ct_layout = QVBoxLayout(card_theme)
        ct_layout.setContentsMargins(0, 2, 0, 2)
        ct_layout.setSpacing(0)

        self.combo_theme = create_styled_combobox(width=220)
        self.combo_theme.addItem("Dark Theme", "dark")
        self.combo_theme.addItem("Light Theme", "light")
        self.combo_theme.addItem("OLED Deep Black", "oled")
        curr_theme = str(self.settings.get("theme", "dark")).lower()
        idx = self.combo_theme.findData(curr_theme)
        self.combo_theme.setCurrentIndex(idx if idx >= 0 else 0)
        self._add_setting_row(
            ct_layout,
            "Active Visual Theme",
            "Select the color palette for ODD overlays and settings",
            self.combo_theme,
            add_divider=True
        )

        self.combo_layout_style = create_styled_combobox(width=220)
        self.combo_layout_style.addItem("Classic (Floating Pill + Standalone Button)", "classic")
        self.combo_layout_style.addItem("Container (Unified Card with Bottom Dock)", "container")
        curr_layout = str(self.settings.get("ui_theme_style", "classic")).lower()
        idx_l = self.combo_layout_style.findData(curr_layout)
        self.combo_layout_style.setCurrentIndex(idx_l if idx_l >= 0 else 0)
        self._add_setting_row(
            ct_layout,
            "UI Layout Style",
            "Select Classic (separate pill & button) or Container (unified card with bottom dock)",
            self.combo_layout_style,
            add_divider=True
        )

        op_ctrl = QWidget()
        op_row = QHBoxLayout(op_ctrl)
        op_row.setContentsMargins(0, 0, 0, 0)
        op_row.setSpacing(10)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(40, 100)
        self.slider_opacity.setFixedWidth(150)
        curr_op = int(self.settings.get("opacity", 0.90) * 100)
        self.slider_opacity.setValue(curr_op)
        op_row.addWidget(self.slider_opacity)
        self.op_val_lbl = QLabel(f"{curr_op}%")
        self.op_val_lbl.setFixedWidth(38)
        self.op_val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider_opacity.valueChanged.connect(lambda v: self.op_val_lbl.setText(f"{v}%"))
        op_row.addWidget(self.op_val_lbl)

        self._add_setting_row(
            ct_layout,
            "Overlay Opacity",
            "Adjust the translucency of the floating search bar surface",
            op_ctrl,
            add_divider=False
        )
        layout.addWidget(card_theme)

        # Group 2: Motion & Spring Physics
        self._add_group_title(layout, "Motion & Spring Physics")
        card_anim = create_setting_card()
        ca_layout = QVBoxLayout(card_anim)
        ca_layout.setContentsMargins(0, 2, 0, 2)
        ca_layout.setSpacing(0)

        self.combo_anim = create_styled_combobox(width=240)
        self.combo_anim.addItem("Fluid Spring (Liquid 60 FPS)", "fluid")
        self.combo_anim.addItem("Snappy Fast (Instant Overshoot)", "snappy")
        self.combo_anim.addItem("Soft Settle (Damped Spring)", "soft")
        self.combo_anim.addItem("Gentle Float (Smooth Drift)", "gentle")

        self.combo_anim.addItem("Instant (No Motion)", "instant")
        curr_anim = str(self.settings.get("animation_style", "fluid")).lower()
        idx_anim = self.combo_anim.findData(curr_anim)
        if idx_anim >= 0:
            self.combo_anim.setCurrentIndex(idx_anim)
        self.combo_anim.currentIndexChanged.connect(self._on_setting_live_changed)

        self._add_setting_row(
            ca_layout,
            "Physics Motion Engine",
            "Centered drop-in, liquid morphing, and surface-tension expansion profile",
            self.combo_anim,
            add_divider=False
        )
        layout.addWidget(card_anim)

        # Group 2: Screen Edge Placement
        self._add_group_title(layout, "Screen Edge Placement")
        card_edge = create_setting_card()
        ce_layout = QVBoxLayout(card_edge)
        ce_layout.setContentsMargins(0, 2, 0, 2)
        ce_layout.setSpacing(0)

        self.combo_side_view = create_styled_combobox(width=220)
        self.combo_side_view.addItem("Off (Normal Top View)", "off")
        self.combo_side_view.addItem("Top-Left Side View", "left")
        self.combo_side_view.addItem("Top-Right Side View", "right")
        curr_side = str(self.settings.get("side_view", "off")).lower()
        idx_side = self.combo_side_view.findData(curr_side)
        self.combo_side_view.setCurrentIndex(idx_side if idx_side >= 0 else 0)
        self.combo_side_view.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            ce_layout,
            "Side View Mode",
            "Dock ODD to top-left or top-right with sleek side-sliding UI",
            self.combo_side_view,
            add_divider=True
        )

        self.combo_edge = create_styled_combobox(width=220)
        self.combo_edge.addItems(["top", "bottom", "left", "right"])
        if hasattr(self, 'combo_side_view'):
            idx_s = self.combo_side_view.findData(self.settings.get("side_view", "off"))
            if idx_s >= 0:
                self.combo_side_view.setCurrentIndex(idx_s)
        self.combo_edge.setCurrentText(self.settings.get("edge", "top"))
        self._add_setting_row(
            ce_layout,
            "Screen Edge Placement",
            "Choose which monitor edge anchors the ODD notch",
            self.combo_edge,
            add_divider=False
        )
        layout.addWidget(card_edge)

        # Group 3: Edge Bar Customization
        self._add_group_title(layout, "Edge Notch Styling")
        card_eb = create_setting_card()
        eb_layout = QVBoxLayout(card_eb)
        eb_layout.setContentsMargins(0, 6, 0, 4)
        eb_layout.setSpacing(0)

        preview_wrap = QWidget()
        pw_lay = QVBoxLayout(preview_wrap)
        pw_lay.setContentsMargins(16, 8, 16, 10)
        self.edge_bar_preview = EdgeBarPreviewWidget()
        pw_lay.addWidget(self.edge_bar_preview)
        eb_layout.addWidget(preview_wrap)
        eb_layout.addWidget(create_row_divider())

        # 1. Notch Style Selector (Simple, Worded)
        self.combo_notch_style = create_styled_combobox(width=250)
        self.combo_notch_style.addItem("Simple Bar (Plain Minimal)", "simple")
        self.combo_notch_style.addItem("Worded (Text & Info-matic)", "worded")
        raw_ns = str(self.settings.get("edge_notch_style", "simple")).strip().lower()
        if raw_ns in ("worded", "text_static", "text_scroll"):
            curr_ns = "worded"
        else:
            curr_ns = "simple"
        idx_ns = self.combo_notch_style.findData(curr_ns)
        if idx_ns >= 0:
            self.combo_notch_style.setCurrentIndex(idx_ns)

        self._add_setting_row(
            eb_layout,
            "Edge Bar Style",
            "Choose indicator style: Simple (plain minimal bar) or Worded (custom/info-matic text)",
            self.combo_notch_style,
            add_divider=True
        )

        # ---------------- SECTION A: SIMPLE BAR OPTIONS ----------------
        self.container_simple = QWidget()
        lay_simple = QVBoxLayout(self.container_simple)
        lay_simple.setContentsMargins(0, 0, 0, 0)
        lay_simple.setSpacing(0)

        # Invisible Edge Bar
        self.chk_hide_edge_bar = self._make_toggle(self.settings.get("hide_edge_bar", False))
        self._add_setting_row(
            lay_simple,
            "Invisible Edge Notch",
            "Make edge bar completely invisible while keeping hover and click gestures active",
            self.chk_hide_edge_bar,
            add_divider=True
        )

        # Color Mode
        self.combo_edge_color_mode = create_styled_combobox(width=220)
        self.combo_edge_color_mode.addItem("Match Active Theme", "theme")
        self.combo_edge_color_mode.addItem("Vibrant Preset Colors", "preset")
        self.combo_edge_color_mode.addItem("Custom Hex Color", "custom")
        curr_cm = self.settings.get("edge_bar_color_mode", "theme")
        idx_cm = self.combo_edge_color_mode.findData(curr_cm)
        if idx_cm >= 0:
            self.combo_edge_color_mode.setCurrentIndex(idx_cm)
        self._add_setting_row(
            lay_simple,
            "Notch Color Mode",
            "Use automatic theme coloring or pick custom selectable colors",
            self.combo_edge_color_mode,
            add_divider=True
        )

        # Swatches & Custom Color Picker
        self.swatch_container = QWidget()
        swatch_layout = QHBoxLayout(self.swatch_container)
        swatch_layout.setContentsMargins(0, 0, 0, 0)
        swatch_layout.setSpacing(7)
        PRESET_COLORS = [
            ("#000000", "Black"),
            ("#00E5FF", "Cyan"),
            ("#A855F7", "Purple"),
            ("#10B981", "Emerald"),
            ("#F59E0B", "Amber"),
            ("#F43F5E", "Rose"),
            ("#FFFFFF", "Frost"),
            ("#64748B", "Slate")
        ]
        for hex_col, name in PRESET_COLORS:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"{name} ({hex_col})")
            border_style = "2px solid rgba(255, 255, 255, 0.40)" if hex_col == "#000000" else "2px solid rgba(255, 255, 255, 0.22)"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {hex_col};
                    border: {border_style};
                    border-radius: 11px;
                }}
                QPushButton:hover {{ border: 2px solid #A1A1AA; }}
            """)
            btn.clicked.connect(lambda _, h=hex_col: self._select_preset_color(h))
            swatch_layout.addWidget(btn)

        self.btn_pick_custom = QPushButton("Custom...")
        self.btn_pick_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pick_custom.clicked.connect(self._open_custom_color_picker)
        swatch_layout.addWidget(self.btn_pick_custom)

        self._add_setting_row(
            lay_simple,
            "Custom Selectable Colors",
            "Choose a preset swatch or pick any custom hex accent color",
            self.swatch_container,
            add_divider=True
        )

        # Width slider
        w_ctrl = QWidget()
        w_row = QHBoxLayout(w_ctrl)
        w_row.setContentsMargins(0, 0, 0, 0)
        w_row.setSpacing(10)
        self.slider_edge_width = QSlider(Qt.Orientation.Horizontal)
        self.slider_edge_width.setRange(40, 240)
        self.slider_edge_width.setFixedWidth(150)
        self.slider_edge_width.setValue(int(self.settings.get("edge_bar_width", 75)))
        w_row.addWidget(self.slider_edge_width)
        self.lbl_ew_val = QLabel(f"{self.slider_edge_width.value()}px")
        self.lbl_ew_val.setFixedWidth(40)
        self.lbl_ew_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        def _on_width_changed(v):
            self.lbl_ew_val.setText(f"{v}px")
            self._update_edge_preview()
            self._on_setting_live_changed()
        self.slider_edge_width.valueChanged.connect(_on_width_changed)
        w_row.addWidget(self.lbl_ew_val)
        self._add_setting_row(
            lay_simple,
            "Bar Width",
            "Horizontal length of the simple edge bar",
            w_ctrl,
            add_divider=True
        )

        # Thickness slider
        t_ctrl = QWidget()
        t_row = QHBoxLayout(t_ctrl)
        t_row.setContentsMargins(0, 0, 0, 0)
        t_row.setSpacing(10)
        self.slider_edge_thickness = QSlider(Qt.Orientation.Horizontal)
        self.slider_edge_thickness.setRange(2, 8)
        self.slider_edge_thickness.setFixedWidth(150)
        self.slider_edge_thickness.setValue(int(self.settings.get("edge_bar_thickness", 4)))
        t_row.addWidget(self.slider_edge_thickness)
        self.lbl_et_val = QLabel(f"{self.slider_edge_thickness.value()}px")
        self.lbl_et_val.setFixedWidth(40)
        self.lbl_et_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        def _on_thickness_changed(v):
            self.lbl_et_val.setText(f"{v}px")
            self._update_edge_preview()
            self._on_setting_live_changed()
        self.slider_edge_thickness.valueChanged.connect(_on_thickness_changed)
        t_row.addWidget(self.lbl_et_val)
        self._add_setting_row(
            lay_simple,
            "Bar Thickness",
            "Vertical height of the simple edge bar",
            t_ctrl,
            add_divider=True
        )
        eb_layout.addWidget(self.container_simple)

        # ---------------- SECTION B: WORDED OPTIONS ----------------
        self.container_worded = QWidget()
        lay_worded = QVBoxLayout(self.container_worded)
        lay_worded.setContentsMargins(0, 0, 0, 0)
        lay_worded.setSpacing(0)

        # Custom text
        self.edit_notch_text = QLineEdit(str(self.settings.get("edge_notch_text", "ODD")))
        self.edit_notch_text.setFixedWidth(140)
        self.edit_notch_text.setPlaceholderText("e.g. ODD")
        self.edit_notch_text.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QLineEdit:focus {
                border: 1px solid rgba(255, 255, 255, 0.45);
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        def _on_notch_text_changed(txt):
            self._update_edge_preview()
            self._on_setting_live_changed()
        self.edit_notch_text.textChanged.connect(_on_notch_text_changed)
        self._add_setting_row(
            lay_worded,
            "Custom Worded Text",
            "Word or brand badge displayed in the edge bar",
            self.edit_notch_text,
            add_divider=True
        )

        # Text Motion Mode (Static vs Scrolling)
        self.combo_worded_mode = create_styled_combobox(width=220)
        self.combo_worded_mode.addItem("Static Text Badge", "static")
        self.combo_worded_mode.addItem("Scrolling Marquee Text", "scroll")
        raw_wm = str(self.settings.get("edge_worded_mode", "static")).strip().lower()
        if raw_wm in ("scroll", "text_scroll"):
            curr_wm = "scroll"
        else:
            curr_wm = "static"
        idx_wm = self.combo_worded_mode.findData(curr_wm)
        if idx_wm >= 0:
            self.combo_worded_mode.setCurrentIndex(idx_wm)
        def _on_worded_mode_changed(idx):
            self._update_edge_preview()
            self._on_setting_live_changed()
        self.combo_worded_mode.currentIndexChanged.connect(_on_worded_mode_changed)
        self._add_setting_row(
            lay_worded,
            "Text Motion Mode",
            "Choose between static centered badge or continuous scrolling marquee text",
            self.combo_worded_mode,
            add_divider=True
        )

        # Info-matic option
        self.chk_edge_infomatic = self._make_toggle(self.settings.get("edge_bar_infomatic", True))
        self._add_setting_row(
            lay_worded,
            "Info-matic Cycling",
            "Dynamically cycle time, date, and running dot animations alongside text",
            self.chk_edge_infomatic,
            add_divider=True
        )
        eb_layout.addWidget(self.container_worded)

        # Visibility controller based on notch style
        def _on_notch_style_changed(idx=None):
            mode = str(self.combo_notch_style.currentData() or "simple").lower()
            if mode not in ("simple", "worded"):
                mode = "simple"
            self.container_simple.setVisible(mode == "simple")
            self.container_worded.setVisible(mode == "worded")
            self._update_edge_preview()
            self._on_setting_live_changed()

        self.combo_notch_style.currentIndexChanged.connect(_on_notch_style_changed)
        _on_notch_style_changed()

        # ---------------- COMMON EDGE BAR OPTIONS ----------------
        self.chk_edge_music = self._make_toggle(self.settings.get("edge_bar_music_display", True))
        self._add_setting_row(
            eb_layout,
            "Edge Bar Music Indicator",
            "Morph edge bar into an interactive media capsule with animated equalizer soundwave bars while music plays",
            self.chk_edge_music,
            add_divider=True
        )

        self.chk_dynamic_max_delay = self._make_toggle(self.settings.get("dynamic_maximized_delay", True))
        self._add_setting_row(
            eb_layout,
            "Maximized App Dwell Delay",
            "Adds a gentle hover delay when apps (e.g. Chrome) are maximized to avoid triggering while clicking tabs or buttons",
            self.chk_dynamic_max_delay,
            add_divider=False
        )

        layout.addWidget(card_eb)
        layout.addStretch()
        self._update_edge_preview()
        return scroll

    # ------------------- PAGE 3: Search Bar & Modules -------------------
    def create_libraries_tab(self) -> QWidget:
        scroll, layout = self._create_page_scroll(
            "Libraries & Tools",
            "Configure search engines, built-in productivity modules, action buttons, and custom command prefixes."
        )

        # Group 1: Built-in Productivity Engines (File Manager 2 Asset Grid)
        self._add_group_title(layout, "Productivity Engines & Search Modules")
        self.modules_asset_grid = FileManagerAssetGrid(parent=self)

        self.chk_mod_calc = self._make_toggle(self.settings.get("enable_calculator", True))
        card_calc = FileManagerAssetCard(
            "calc", "Calculator & Math", "search",
            "Evaluate expressions and trigonometric functions directly in search.",
            "Prefix: calc: (or inline math)", "modules", self.chk_mod_calc, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_calc)

        self.chk_mod_conv = self._make_toggle(self.settings.get("enable_unit_converter", True))
        card_conv = FileManagerAssetCard(
            "conv", "Unit & Currency Converter", "search",
            "Convert values naturally across currencies, lengths, and weights.",
            "Example: 100 usd in eur", "refresh", self.chk_mod_conv, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_conv)

        self.chk_mod_clip = self._make_toggle(self.settings.get("enable_clipboard_history", True))
        card_clip = FileManagerAssetCard(
            "clip", "Clipboard History", "tools",
            "Search and paste recent clipboard items with persistent local cache.",
            "Prefix: clip: or cb:", "copy", self.chk_mod_clip, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_clip)

        self.chk_mod_notes = self._make_toggle(self.settings.get("enable_quick_notes", True))
        card_notes = FileManagerAssetCard(
            "notes", "Quick Notes & Scratchpad", "tools",
            "Jot down persistent notes, reminders, and tasks from the capsule.",
            "Prefix: note: or todo:", "file", self.chk_mod_notes, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_notes)

        self.chk_mod_clock = self._make_toggle(self.settings.get("enable_world_clock", True))
        card_clock = FileManagerAssetCard(
            "clock", "World Clock & Timers", "tools",
            "Check international timezones or start live timers in the Island.",
            "Prefix: time: or timer: 5m", "calendar", self.chk_mod_clock, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_clock)

        self.chk_mod_color = self._make_toggle(self.settings.get("enable_color_inspector", True))
        card_color = FileManagerAssetCard(
            "color", "Color Inspector & Palette", "tools",
            "Preview hex/RGB colors, test palettes, and copy CSS formats.",
            "Format: #D4D4D8 or color:", "lightbulb", self.chk_mod_color, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_color)

        self.chk_mod_sys = self._make_toggle(self.settings.get("enable_system_commands", True))
        card_sys = FileManagerAssetCard(
            "sys", "System Power Commands", "sys",
            "Execute quick system actions: lock, sleep, restart, empty recycle bin.",
            "Prefix: sys:lock or sys:sleep", "power", self.chk_mod_sys, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_sys)

        self.chk_mod_web = self._make_toggle(self.settings.get("enable_web_shortcuts", True))
        card_web = FileManagerAssetCard(
            "web", "Web Omnibox Shortcuts", "search",
            "Search web services directly with custom prefixes.",
            "Prefix: yt:, gh:, wiki:", "globe", self.chk_mod_web, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_web)

        self.chk_mod_fallbacks = self._make_toggle(self.settings.get("enable_web_fallbacks", True))
        card_fallbacks = FileManagerAssetCard(
            "fallbacks", "Web Search Fallbacks", "search",
            "Offer live Google search suggestions when no local file matches.",
            "Trigger: Unmatched queries", "globe", self.chk_mod_fallbacks, parent=self
        )
        self.modules_asset_grid.add_asset_card(card_fallbacks)

        layout.addWidget(self.modules_asset_grid)

        # Group 2: Quick Text Sending (Messaging)
        self._add_group_title(layout, "Quick Text Sending")
        card_msg = create_setting_card()
        cm_layout = QVBoxLayout(card_msg)
        cm_layout.setContentsMargins(0, 2, 0, 2)
        cm_layout.setSpacing(0)

        self.chk_mod_messaging = self._make_toggle(self.settings.get("enable_quick_messaging", True))
        self._add_setting_row(
            cm_layout,
            "Enable Quick Text Sending",
            "Send messages directly from ODD (e.g. 'Text John I'll be there in 10 minutes')",
            self.chk_mod_messaging,
            add_divider=True
        )

        self.combo_messaging_provider = create_styled_combobox(width=220)
        self.combo_messaging_provider.addItem("WhatsApp Desktop", "whatsapp_desktop")
        self.combo_messaging_provider.addItem("WhatsApp Web", "whatsapp_web")
        curr_mp = str(self.settings.get("messaging_provider", "whatsapp_desktop")).strip().lower()
        idx_mp = self.combo_messaging_provider.findData(curr_mp)
        if idx_mp >= 0:
            self.combo_messaging_provider.setCurrentIndex(idx_mp)
        self.chk_mod_messaging.toggled.connect(self.combo_messaging_provider.setEnabled)
        self.combo_messaging_provider.setEnabled(self.chk_mod_messaging.isChecked())

        self._add_setting_row(
            cm_layout,
            "Preferred Messaging App",
            "Choose which platform opens and sends your message automatically",
            self.combo_messaging_provider,
            add_divider=False
        )
        layout.addWidget(card_msg)

        # Group 3: Search Bar Buttons
        self._add_group_title(layout, "Search Bar Action Buttons")
        card_ui = create_setting_card()
        c_ui_layout = QVBoxLayout(card_ui)
        c_ui_layout.setContentsMargins(0, 2, 0, 2)
        c_ui_layout.setSpacing(0)

        self.combo_action_btn = create_styled_combobox(width=255)
        self.combo_action_btn.addItem("Show All Checked Buttons (Recommended)", "both")
        self.combo_action_btn.addItem("Dynamic (Music when Media Active)", "dynamic")
        self.combo_action_btn.addItem("Dynamic Swap (Music or Google Lens)", "dynamic_swap")
        self.combo_action_btn.addItem("Google Lens Only", "google_lens")
        self.combo_action_btn.addItem("Music Button Only", "music")
        self.combo_action_btn.addItem("None", "none")
        curr_ab = self.settings.get("search_pill_action_button", "both")
        if curr_ab in ("lens", "similar_image", "bing_visual"):
            curr_ab = "google_lens"
        idx_ab = self.combo_action_btn.findData(curr_ab)
        if idx_ab >= 0:
            self.combo_action_btn.setCurrentIndex(idx_ab)
        self.combo_action_btn.currentIndexChanged.connect(self._on_setting_live_changed)

        self._add_setting_row(
            c_ui_layout,
            "Overlay Button Display Mode",
            "Control how action buttons appear inside the search pill",
            self.combo_action_btn,
            add_divider=True
        )

        self.chk_ui_quick_settings = self._make_toggle(self.settings.get("ui_show_quick_settings_button", True))
        self._add_setting_row(
            c_ui_layout,
            "Quick Settings Button",
            "Access Wi-Fi, Volume, Brightness, and Screen Snip from the search bar",
            self.chk_ui_quick_settings,
            add_divider=True
        )

        self.chk_ui_music = self._make_toggle(self.settings.get("ui_show_music_button", True))
        self._add_setting_row(
            c_ui_layout,
            "Music Player Button",
            "Toggle the media player overlay from the search bar",
            self.chk_ui_music,
            add_divider=True
        )

        self.chk_ui_lens = self._make_toggle(self.settings.get("ui_show_lens_button", True))
        self._add_setting_row(
            c_ui_layout,
            "Google Lens Visual Search Button",
            "Capture any region of your screen to search with Google Lens",
            self.chk_ui_lens,
            add_divider=True
        )

        self.chk_ui_plus = self._make_toggle(self.settings.get("ui_show_plus_button", True))
        self._add_setting_row(
            c_ui_layout,
            "'+' Quick Commands Button",
            "Show the quick prefix & command menu button on the left of the search bar",
            self.chk_ui_plus,
            add_divider=True
        )

        self.chk_ui_settings = self._make_toggle(self.settings.get("ui_show_settings_button", True))
        self._add_setting_row(
            c_ui_layout,
            "Circular ODD Button",
            "Show the connected circular ODD logo button beside the search bar",
            self.chk_ui_settings,
            add_divider=True
        )

        self.chk_ui_edge_bar = self._make_toggle(self.settings.get("ui_show_edge_indicator", True))
        self._add_setting_row(
            c_ui_layout,
            "Screen-Edge Notch Indicator",
            "Show the visual notch bar along the active screen edge",
            self.chk_ui_edge_bar,
            add_divider=True
        )

        self.chk_ui_power_controls = self._make_toggle(self.settings.get("ui_show_power_controls", True))
        self._add_setting_row(
            c_ui_layout,
            "Power & Quick Controls Strip",
            "Show Lock, Sleep, Restart, and Shutdown controls when Quick Settings is open",
            self.chk_ui_power_controls,
            add_divider=False
        )
        layout.addWidget(card_ui)

        # Group 4: Interactive Commands & Learning Guide
        self._add_group_title(layout, "Interactive Commands & Learning Guide")
        card_guide = create_setting_card()
        cg_layout = QVBoxLayout(card_guide)
        cg_layout.setContentsMargins(12, 12, 12, 12)
        cg_layout.setSpacing(8)

        lbl_guide_sub = QLabel("Explore and learn all built-in instant tools, calculation triggers, and commands:")
        lbl_guide_sub.setStyleSheet("color: #A1A1AA; font-size: 11.5px;")
        lbl_guide_sub.setWordWrap(True)
        cg_layout.addWidget(lbl_guide_sub)

        self.edit_guide_search = QLineEdit()
        self.edit_guide_search.setPlaceholderText("Search commands (e.g. 'calc', 'weather', 'media', 'notes', 'clp')...")
        self.edit_guide_search.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 6px 12px;
                color: #FFFFFF;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: rgba(255, 255, 255, 0.35);
                background: rgba(255, 255, 255, 0.08);
            }
        """)
        cg_layout.addWidget(self.edit_guide_search)

        self.table_guide = QTableWidget(0, 4)
        self.table_guide.setMinimumHeight(280)
        self.table_guide.setShowGrid(False)
        self.table_guide.setHorizontalHeaderLabels(["Tool / Feature", "Prefix", "Example Usage & Tip", "Action"])
        self.table_guide.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_guide.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_guide.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_guide.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_guide.verticalHeader().setVisible(False)
        self.table_guide.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table_guide.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._populate_commands_guide_table()
        self.edit_guide_search.textChanged.connect(self._filter_commands_guide_table)
        cg_layout.addWidget(self.table_guide)
        layout.addWidget(card_guide)

        # Group 5: Custom Command Prefixes Section
        self._add_group_title(layout, "Custom Command Prefixes")
        card_table = create_setting_card()
        t_layout = QVBoxLayout(card_table)
        t_layout.setContentsMargins(10, 10, 10, 10)

        self.table_prefixes = QTableWidget(0, 2)
        self.table_prefixes.setMinimumHeight(240)
        self.table_prefixes.setShowGrid(False)
        self.table_prefixes.setHorizontalHeaderLabels(["Prefix", "Description"])
        self.table_prefixes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_prefixes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_prefixes.verticalHeader().setVisible(False)

        self.populate_prefixes_table()
        t_layout.addWidget(self.table_prefixes)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add Prefix")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(self._add_prefix_row)
        btn_row.addWidget(btn_add)

        btn_del = QPushButton("- Remove Selected")
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.clicked.connect(self._delete_prefix_row)
        btn_row.addWidget(btn_del)

        btn_rst = QPushButton("Reset Defaults")
        btn_rst.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rst.clicked.connect(self._restore_default_prefixes)
        btn_row.addWidget(btn_rst)
        btn_row.addStretch()
        t_layout.addLayout(btn_row)

        layout.addWidget(card_table)

        layout.addStretch()
        return scroll

    def create_modules_tab(self) -> QWidget:
        return self.create_libraries_tab()

    def create_prefixes_tab(self) -> QWidget:
        return self.create_libraries_tab()
    # ------------------- PAGE 4: Dynamic Island & Bezel HUDs -------------------
    def create_island_tab(self) -> QWidget:
        scroll, layout = self._create_page_scroll(
            "ODD Island & HUD Alerts",
            "Control the living top-edge Dynamic Island, media player, hardware telemetry, and quiet hours."
        )

        # Group 1: Core Dynamic Island
        self._add_group_title(layout, "Dynamic Island Core & Overlays")
        card_core = create_setting_card()
        cc_layout = QVBoxLayout(card_core)
        cc_layout.setContentsMargins(0, 2, 0, 2)
        cc_layout.setSpacing(0)

        self.chk_island_media = self._make_toggle(self.settings.get("island_show_media_hud", True))
        self._add_setting_row(
            cc_layout,
            "Media Track & Live Waveform HUD",
            "Show compact album art and real-time audio spectrum in the Island",
            self.chk_island_media,
            add_divider=True
        )

        self.chk_island_timer = self._make_toggle(self.settings.get("island_show_timer_ticker", True))
        self._add_setting_row(
            cc_layout,
            "Live Countdown Timer Ticker",
            "Pin active timers inside the Dynamic Island with real-time countdown",
            self.chk_island_timer,
            add_divider=True
        )

        self.chk_island_reminders = self._make_toggle(self.settings.get("enable_island_reminders", True))
        self._add_setting_row(
            cc_layout,
            "Natural-Language Island Reminders",
            "Deliver scheduled reminders directly through the Dynamic Island",
            self.chk_island_reminders,
            add_divider=False
        )
        layout.addWidget(card_core)

        # Group 2: Hardware & System HUDs
        self._add_group_title(layout, "Hardware & Activity HUDs")
        card_hud = create_setting_card()
        ch_layout = QVBoxLayout(card_hud)
        ch_layout.setContentsMargins(0, 2, 0, 2)
        ch_layout.setSpacing(0)

        self.chk_island_volume = self._make_toggle(self.settings.get("island_show_volume_hud", True))
        self._add_setting_row(
            ch_layout,
            "System Volume & Mute HUD",
            "Display a sleek bezel pill when adjusting system volume or muting audio",
            self.chk_island_volume,
            add_divider=True
        )

        self.chk_island_battery = self._make_toggle(self.settings.get("island_show_battery_hud", True))
        self._add_setting_row(
            ch_layout,
            "Battery & Power Charging HUD",
            "Show charger connection and low-battery alerts in the Island",
            self.chk_island_battery,
            add_divider=True
        )

        self.chk_island_caps = self._make_toggle(self.settings.get("island_show_caps_lock_hud", True))
        self._add_setting_row(
            ch_layout,
            "Caps Lock Indicator HUD",
            "Show a clean compact badge when toggling Caps Lock",
            self.chk_island_caps,
            add_divider=True
        )

        self.chk_island_clip = self._make_toggle(self.settings.get("island_show_clipboard_hud", True))
        self._add_setting_row(
            ch_layout,
            "Copy & Paste Feedback Badges",
            "Show a brief confirmation pill when copying items to the clipboard",
            self.chk_island_clip,
            add_divider=True
        )

        self.chk_island_downloads = self._make_toggle(self.settings.get("enable_download_mode", True))
        self._add_setting_row(
            ch_layout,
            "Download Progress Ring",
            "Track active file downloads as a compact progress ring on the notch",
            self.chk_island_downloads,
            add_divider=True
        )

        self.chk_island_activity_mem = self._make_toggle(self.settings.get("enable_activity_memory", True))
        self._add_setting_row(
            ch_layout,
            "Background Activity Memory",
            "Remember ongoing installers and background tasks in the Island",
            self.chk_island_activity_mem,
            add_divider=False
        )
        layout.addWidget(card_hud)

        # Group 3: Music & Media Player Integration
        self._add_group_title(layout, "Music & Media Player Integration")
        card_music = create_setting_card()
        c3_layout = QVBoxLayout(card_music)
        c3_layout.setContentsMargins(0, 2, 0, 2)
        c3_layout.setSpacing(0)

        self.chk_music = self._make_toggle(self.settings.get("enable_music_overlay", True))
        self._add_setting_row(
            c3_layout,
            "Music & Media Player Integration",
            "Display live album artwork, interactive seekbar, and playback controls",
            self.chk_music,
            add_divider=True
        )

        self.combo_music_mode = create_styled_combobox(width=260)
        self.combo_music_mode.addItem("Dynamic (Minimal Music + Search)", "auto")
        self.combo_music_mode.addItem("Always Minimal Music + ODD Search", "always_minimal")
        self.combo_music_mode.addItem("Full Music Player when playing", "full_auto")
        self.combo_music_mode.addItem("Always Full Music First", "always")
        self.combo_music_mode.addItem("Disabled", "disabled")
        curr_m_mode = self.settings.get("music_overlay_mode", "auto")
        if curr_m_mode == "dynamic":
            curr_m_mode = "auto"
        idx = self.combo_music_mode.findData(curr_m_mode)
        if idx >= 0:
            self.combo_music_mode.setCurrentIndex(idx)
        self._add_setting_row(
            c3_layout,
            "Hover Overlay Mode",
            "Choose how media controls appear when surfacing ODD",
            self.combo_music_mode,
            add_divider=True
        )

        self.combo_paused_media = create_styled_combobox(width=260)
        self.combo_paused_media.addItem("Show Minimal Overlay at Bottom", "show_minimal")
        self.combo_paused_media.addItem("Hide Overlay (Use Music Button)", "button_only")
        curr_p_mode = self.settings.get("paused_media_behavior", "show_minimal")
        idx_pm = self.combo_paused_media.findData(curr_p_mode)
        if idx_pm >= 0:
            self.combo_paused_media.setCurrentIndex(idx_pm)
        self._add_setting_row(
            c3_layout,
            "When Media is Paused",
            "Control whether paused sessions stay visible below the search bar",
            self.combo_paused_media,
            add_divider=True
        )

        self.chk_vinyl_rot = self._make_toggle(self.settings.get("enable_vinyl_rotation", True))
        self._add_setting_row(
            c3_layout,
            "Rotating Vinyl Disc Animation",
            "Smooth 60fps spinning vinyl artwork animation while audio is playing",
            self.chk_vinyl_rot,
            add_divider=False
        )
        layout.addWidget(card_music)

        # Group 4: Weather Forecast & Island Widget
        self._add_group_title(layout, "Weather Forecast & Island Widget")
        card_weather = create_setting_card()
        cw_layout = QVBoxLayout(card_weather)
        cw_layout.setContentsMargins(0, 2, 0, 2)
        cw_layout.setSpacing(0)

        self.chk_enable_weather = self._make_toggle(self.settings.get("enable_weather_widget", True))
        self.chk_enable_weather.toggled.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cw_layout,
            "Enable Island Weather Widget",
            "Display clean live weather icon and exact temperature in the island",
            self.chk_enable_weather,
            add_divider=True
        )

        self.edit_weather_location = QLineEdit(self)
        self.edit_weather_location.setText(str(self.settings.get("weather_location", "Auto-detect")))
        self.edit_weather_location.setPlaceholderText("Auto-detect or City name (e.g. London, New York, Tokyo)")
        self.edit_weather_location.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                min-width: 210px;
            }
            QLineEdit:focus {
                border: 1px solid rgba(255, 255, 255, 0.45);
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        self.edit_weather_location.editingFinished.connect(self._on_weather_location_edited)
        self.edit_weather_location.returnPressed.connect(self._on_weather_location_edited)
        self.edit_weather_location.textChanged.connect(lambda txt: self.settings.update({"weather_location": txt.strip() or "Auto-detect"}))
        self._add_setting_row(
            cw_layout,
            "Weather Location",
            "Choose your city for exact local weather, or use Auto-detect",
            self.edit_weather_location,
            add_divider=True
        )

        self.combo_weather_slot = create_styled_combobox(width=220)
        self.combo_weather_slot.addItem("Replace Music Overlay Button (Default)", "music")
        self.combo_weather_slot.addItem("Replace Google Lens Button", "lens")
        self.combo_weather_slot.addItem("Replace Quick Settings Button", "quick_settings")
        self.combo_weather_slot.addItem("Add as Standalone Button", "standalone")
        curr_slot = str(self.settings.get("weather_replace_slot", "music")).strip().lower()
        idx_slot = self.combo_weather_slot.findData(curr_slot)
        if idx_slot >= 0:
            self.combo_weather_slot.setCurrentIndex(idx_slot)
        self.combo_weather_slot.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cw_layout,
            "Island Slot to Replace",
            "Choose which button in the island is replaced by the weather widget",
            self.combo_weather_slot,
            add_divider=True
        )

        self.combo_weather_unit = create_styled_combobox(width=220)
        self.combo_weather_unit.addItem("Celsius (°C)", "celsius")
        self.combo_weather_unit.addItem("Fahrenheit (°F)", "fahrenheit")
        curr_unit = str(self.settings.get("weather_unit", "celsius")).strip().lower()
        idx_unit = self.combo_weather_unit.findData(curr_unit)
        if idx_unit >= 0:
            self.combo_weather_unit.setCurrentIndex(idx_unit)
        self.combo_weather_unit.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cw_layout,
            "Temperature Unit",
            "Select Celsius (°C) or Fahrenheit (°F)",
            self.combo_weather_unit,
            add_divider=False
        )
        layout.addWidget(card_weather)

        # Group 5: Android Phone Mirroring (Experimental)
        self._add_group_title(layout, "Android Phone Mirroring (Experimental)")
        card_mirror = create_setting_card()
        cmir_layout = QVBoxLayout(card_mirror)
        cmir_layout.setContentsMargins(0, 2, 0, 2)
        cmir_layout.setSpacing(0)

        self.chk_enable_android_mirror = self._make_toggle(self.settings.get("enable_android_mirror", True))
        self._add_setting_row(
            cmir_layout,
            "Enable Android Mirror in Search Bar",
            "Show a phone button in the search bar to mirror screen and control Android via Bluetooth",
            self.chk_enable_android_mirror,
            add_divider=True
        )

        self.combo_android_mirror_slot = create_styled_combobox(width=250)
        self.combo_android_mirror_slot.addItem("Add as Standalone Button (Default)", "standalone")
        self.combo_android_mirror_slot.addItem("Replace Music Overlay Button", "music")
        self.combo_android_mirror_slot.addItem("Replace Google Lens Button", "lens")
        self.combo_android_mirror_slot.addItem("Replace Quick Settings Button", "quick_settings")
        self.combo_android_mirror_slot.addItem("Replace Weather Widget", "weather")
        curr_mslot = str(self.settings.get("android_mirror_replace_slot", "standalone")).strip().lower()
        idx_mslot = self.combo_android_mirror_slot.findData(curr_mslot)
        if idx_mslot >= 0:
            self.combo_android_mirror_slot.setCurrentIndex(idx_mslot)
        self.combo_android_mirror_slot.currentIndexChanged.connect(self._on_setting_live_changed)
        self._add_setting_row(
            cmir_layout,
            "Search Bar Button Slot",
            "Choose which search pill slot the phone mirror button occupies or replaces",
            self.combo_android_mirror_slot,
            add_divider=False
        )
        layout.addWidget(card_mirror)

        # Group 6: Notifications Delivery & Quiet Hours
        self._add_group_title(layout, "Notification Delivery & Quiet Hours")
        card_notif = create_setting_card()
        cn_layout = QVBoxLayout(card_notif)
        cn_layout.setContentsMargins(0, 2, 0, 2)
        cn_layout.setSpacing(0)

        self.chk_island_notifications = self._make_toggle(self.settings.get("island_show_system_notifications", True))
        self._add_setting_row(
            cn_layout,
            "Display System & App Notifications",
            "Surface incoming desktop notifications cleanly inside the Dynamic Island",
            self.chk_island_notifications,
            add_divider=True
        )

        self.combo_notification_duration = create_styled_combobox(width=190)
        self.combo_notification_duration.addItem("3 seconds", 3)
        self.combo_notification_duration.addItem("5 seconds (Default)", 5)
        self.combo_notification_duration.addItem("7 seconds", 7)
        self.combo_notification_duration.addItem("10 seconds", 10)
        cur_dur = int(self.settings.get("notification_duration_sec", 5))
        dur_idx = self.combo_notification_duration.findData(cur_dur)
        self.combo_notification_duration.setCurrentIndex(dur_idx if dur_idx >= 0 else 1)
        self.combo_notification_duration.currentIndexChanged.connect(self._on_setting_live_changed)

        self._add_setting_row(
            cn_layout,
            "Notification Auto-Hide Duration",
            "How long notification popups remain visible before collapsing",
            self.combo_notification_duration,
            add_divider=False
        )
        layout.addWidget(card_notif)

        # Quiet Hours Schedule Card (Notifications 3)
        self.quiet_hours_widget = QuietHoursWidget(self.settings, self._make_toggle, parent=self)
        self.quiet_hours_widget.combo_quiet_start.currentIndexChanged.connect(self._on_quiet_hours_changed)
        self.quiet_hours_widget.combo_quiet_end.currentIndexChanged.connect(self._on_quiet_hours_changed)
        self.quiet_hours_widget.chk_quiet_mute.toggled.connect(self._on_quiet_hours_changed)
        self.quiet_hours_widget.chk_quiet_suppress.toggled.connect(self._on_quiet_hours_changed)
        self.quiet_hours_widget.chk_quiet_priority.toggled.connect(self._on_quiet_hours_changed)
        layout.addWidget(self.quiet_hours_widget)

        # Group 7: Hardware & Service Integrations (Integrations 1)
        self._add_group_title(layout, "Connected Services & Hardware Telemetry")
        self.integrations_widget = IntegrationsMarketplaceWidget(parent=self)
        layout.addWidget(self.integrations_widget)

        layout.addStretch()
        return scroll

    def create_integrations_tab(self) -> QWidget:
        return self.create_island_tab()

    def create_wellness_tab(self) -> QWidget:
        return self.create_general_tab()
    def _on_quiet_hours_changed(self):
        if hasattr(self, 'quiet_hours_widget'):
            self.settings["quiet_hours_enabled"] = self.quiet_hours_widget.chk_quiet_master.isChecked()
            self.settings["quiet_hours_start"] = self.quiet_hours_widget.combo_quiet_start.currentData() or "22:00"
            self.settings["quiet_hours_end"] = self.quiet_hours_widget.combo_quiet_end.currentData() or "07:00"
            self.settings["quiet_hours_mute_sound"] = self.quiet_hours_widget.chk_quiet_mute.isChecked()
            self.settings["quiet_hours_suppress_popups"] = self.quiet_hours_widget.chk_quiet_suppress.isChecked()
            self.settings["quiet_hours_allow_priority"] = self.quiet_hours_widget.chk_quiet_priority.isChecked()
        self._on_setting_live_changed()

    def _populate_commands_guide_table(self, filter_text: str = ""):
        self.table_guide.setRowCount(0)
        from odd_overlay import COMMANDS_GUIDE_DATA
        filter_lower = filter_text.strip().lower()

        for item in COMMANDS_GUIDE_DATA:
            pfx = item.get("prefix", "")
            title = item.get("title", "")
            icon = item.get("icon", "")
            ex = item.get("example", "")
            tip = item.get("tip", "")

            searchable = f"{pfx} {title} {ex} {tip}".lower()
            if filter_lower and filter_lower not in searchable:
                continue

            row = self.table_guide.rowCount()
            self.table_guide.insertRow(row)

            # Col 0: Icon + Title
            item_title = QTableWidgetItem(f"{icon}  {title}")
            item_title.setToolTip(tip)
            self.table_guide.setItem(row, 0, item_title)

            # Col 1: Prefix badge
            item_pfx = QTableWidgetItem(pfx)
            item_pfx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_guide.setItem(row, 1, item_pfx)

            # Col 2: Example + Tip
            item_ex = QTableWidgetItem(f"{ex} — {tip}")
            self.table_guide.setItem(row, 2, item_ex)

            # Col 3: Copy Prefix Button
            btn_copy = QPushButton("Copy")
            btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_copy.setFixedSize(54, 24)
            btn_copy.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.16);
                    border-radius: 4px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.18);
                    border-color: rgba(255, 255, 255, 0.32);
                }
            """)
            btn_copy.clicked.connect(lambda _, p=pfx, b=btn_copy: self._copy_command_prefix(p, b))
            self.table_guide.setCellWidget(row, 3, btn_copy)

    def _filter_commands_guide_table(self, txt: str):
        self._populate_commands_guide_table(txt)

    def _copy_command_prefix(self, prefix: str, button: QPushButton):
        try:
            from PySide6.QtWidgets import QApplication
            cb = QApplication.clipboard()
            cb.setText(prefix)
            button.setText("Copied!")
            button.setStyleSheet("""
                QPushButton {
                    background: rgba(16, 185, 129, 0.25);
                    color: #34D399;
                    border: 1px solid rgba(16, 185, 129, 0.45);
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            QTimer.singleShot(1400, lambda: self._reset_copy_btn(button))
        except Exception:
            pass

    def _reset_copy_btn(self, button: QPushButton):
        try:
            button.setText("Copy")
            button.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.16);
                    border-radius: 4px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.18);
                    border-color: rgba(255, 255, 255, 0.32);
                }
            """)
        except Exception:
            pass

    def populate_prefixes_table(self):
        self.table_prefixes.setRowCount(0)
        prefixes = self.settings.get("prefixes", {})
        for prefix, act in prefixes.items():
            row = self.table_prefixes.rowCount()
            self.table_prefixes.insertRow(row)
            item_p = QTableWidgetItem(prefix)
            item_a = QTableWidgetItem(act)
            item_p.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_prefixes.setItem(row, 0, item_p)
            self.table_prefixes.setItem(row, 1, item_a)

    def _add_prefix_row(self):
        row = self.table_prefixes.rowCount()
        self.table_prefixes.insertRow(row)
        item_p = QTableWidgetItem("new:")
        item_a = QTableWidgetItem("Custom Search Description")
        item_p.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table_prefixes.setItem(row, 0, item_p)
        self.table_prefixes.setItem(row, 1, item_a)
        self.table_prefixes.editItem(item_p)

    def _delete_prefix_row(self):
        selected = self.table_prefixes.currentRow()
        if selected >= 0:
            self.table_prefixes.removeRow(selected)

    def _restore_default_prefixes(self):
        self.settings["prefixes"] = DEFAULT_SETTINGS["prefixes"].copy()
        self.populate_prefixes_table()

    # ------------------- PAGE 6: Software Updates -------------------
    def create_updates_tab(self) -> QWidget:
        scroll, layout = self._create_page_scroll(
            "Updates & Feedback",
            f"ODD Desktop v{CURRENT_VERSION} — update channels, diagnostic logs, and community feedback."
        )

        # Group 1: Software Updates
        self._add_group_title(layout, "Software Updates")
        card_u = create_setting_card()
        u_layout = QVBoxLayout(card_u)
        u_layout.setContentsMargins(18, 18, 18, 18)
        u_layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        self.logo_lbl_u = QLabel()
        self.logo_lbl_u.setPixmap(get_odd_logo_pixmap((44, 44), self.settings.get("theme", "dark")))
        top_row.addWidget(self.logo_lbl_u)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(3)
        self.title_u = QLabel("ODD Desktop")
        self.title_u.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        info_vbox.addWidget(self.title_u)

        ver_row = QHBoxLayout()
        ver_row.setSpacing(8)
        self.lbl_upd_cur_ver = QLabel(f"Current Version: v{CURRENT_VERSION}")
        self.lbl_upd_cur_ver.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.DemiBold))
        ver_row.addWidget(self.lbl_upd_cur_ver)

        self.lbl_platform = QLabel("Windows 64-bit")
        ver_row.addWidget(self.lbl_platform)
        ver_row.addStretch()

        info_vbox.addLayout(ver_row)
        top_row.addLayout(info_vbox)
        top_row.addStretch()

        self.btn_check_update = QPushButton("Check for Updates")
        self.btn_check_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check_update.clicked.connect(self._on_check_update_clicked)
        top_row.addWidget(self.btn_check_update)
        u_layout.addLayout(top_row)

        self.chk_auto_update = QCheckBox("Automatically check for updates (asks before downloading)")
        self.chk_auto_update.setChecked(bool(self.settings.get("enable_auto_update", True)))
        self.chk_auto_update.toggled.connect(self._on_setting_live_changed)
        u_layout.addWidget(self.chk_auto_update)

        self.lbl_upd_status = QLabel(f"ODD is up to date (v{CURRENT_VERSION}).")
        self.lbl_upd_status.setStyleSheet("color: #A1A1AA; font-size: 11.5px;")
        self.lbl_upd_status.setWordWrap(True)
        u_layout.addWidget(self.lbl_upd_status)

        self.txt_release_notes = QTextEdit()
        self.txt_release_notes.setReadOnly(True)
        self.txt_release_notes.setMinimumHeight(110)
        self.txt_release_notes.hide()
        u_layout.addWidget(self.txt_release_notes)

        self.prog_update = QProgressBar()
        self.prog_update.setFixedHeight(6)
        self.prog_update.setTextVisible(False)
        self.prog_update.setStyleSheet("""
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.08);
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #71717A;
                border-radius: 3px;
            }
        """)
        self.prog_update.hide()
        u_layout.addWidget(self.prog_update)

        self.btn_install_update = QPushButton("Install Update")
        self.btn_install_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install_update.clicked.connect(self._on_install_update_clicked)
        self.btn_install_update.hide()
        u_layout.addWidget(self.btn_install_update)
        layout.addWidget(card_u)

        # Group 2: Diagnostics & Crash Logs
        self._add_group_title(layout, "Diagnostics & Crash Logs")
        card_diag = create_setting_card()
        cd_layout = QVBoxLayout(card_diag)
        cd_layout.setContentsMargins(0, 2, 0, 2)
        cd_layout.setSpacing(0)

        chip_box = QWidget()
        ch_lay = QHBoxLayout(chip_box)
        ch_lay.setContentsMargins(0, 0, 0, 0)
        lbl_status_chip = QLabel("ACTIVE & LOGGING")
        lbl_status_chip.setStyleSheet("background: rgba(255, 255, 255, 0.08); color: #FAFAFA; border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 6px; padding: 2px 8px; font-size: 10px; font-weight: bold;")
        ch_lay.addWidget(lbl_status_chip)

        self._add_setting_row(
            cd_layout,
            "Native Crash Forensics (faulthandler)",
            "Automatic fault capture enabled. All unhandled exceptions, thread errors, and breadcrumbs are preserved to disk.",
            chip_box,
            add_divider=True
        )

        btn_open_logs = QPushButton("Open Logs Folder")
        btn_open_logs.setCursor(Qt.CursorShape.PointingHandCursor)
        def _open_logs_dir():
            import os
            log_dir = os.path.expandvars(r"%LOCALAPPDATA%\ODD\logs")
            os.makedirs(log_dir, exist_ok=True)
            subprocess.Popen(f'explorer "{log_dir}"')
        btn_open_logs.clicked.connect(_open_logs_dir)
        self._add_setting_row(
            cd_layout,
            "Application Diagnostics Logs",
            "Open the local log directory containing crash reports, runtime breadcrumbs, and debug traces",
            btn_open_logs,
            add_divider=False
        )
        layout.addWidget(card_diag)

        # Group 3: Send Feedback & Community Support
        self._add_group_title(layout, "Send Feedback & Community Support")
        card_f = create_setting_card()
        f_layout = QVBoxLayout(card_f)
        f_layout.setContentsMargins(0, 2, 0, 14)
        f_layout.setSpacing(10)

        self.combo_topic = create_styled_combobox(width=220)
        self.combo_topic.addItems(["Feature Suggestion", "Bug Report", "UI Feedback", "Question"])
        self._add_setting_row(
            f_layout,
            "Feedback Topic",
            "Select the category that best describes your message",
            self.combo_topic,
            add_divider=True
        )

        form_wrap = QWidget()
        fw_layout = QVBoxLayout(form_wrap)
        fw_layout.setContentsMargins(16, 6, 16, 0)
        fw_layout.setSpacing(10)

        self.feed_subject = QLineEdit("Feedback on ODD Desktop Search")
        self.feed_subject.setPlaceholderText("Subject...")
        fw_layout.addWidget(self.feed_subject)

        self.feed_body = QTextEdit()
        self.feed_body.setPlaceholderText("Describe your suggestions, ideas, or feedback...")
        self.feed_body.setMinimumHeight(120)
        fw_layout.addWidget(self.feed_body)

        f_btn_row = QHBoxLayout()
        f_btn_row.setSpacing(10)

        self.btn_mail = QPushButton("Send Email")
        self.btn_mail.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mail.clicked.connect(self._on_send_email)
        f_btn_row.addWidget(self.btn_mail)

        self.btn_copy = QPushButton("Copy Feedback")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.clicked.connect(self._on_copy_feedback)
        f_btn_row.addWidget(self.btn_copy)

        f_btn_row.addStretch()

        self.lbl_email_link = QLabel("me.humnspace@gmail.com")
        f_btn_row.addWidget(self.lbl_email_link)

        fw_layout.addLayout(f_btn_row)
        f_layout.addWidget(form_wrap)
        layout.addWidget(card_f)

        layout.addStretch()
        return scroll

    def create_feedback_tab(self) -> QWidget:
        return self.create_updates_tab()

    def _on_send_email(self):
        topic = self.combo_topic.currentText()
        subj = f"[{topic}] {self.feed_subject.text().strip()}"
        body = self.feed_body.toPlainText().strip()
        mailto = f"mailto:me.humnspace@gmail.com?subject={urllib.parse.quote(subj)}&body={urllib.parse.quote(body)}"
        webbrowser.open(mailto)
        QMessageBox.information(self, "Feedback", "Your default email client has been opened with the feedback template pre-filled.")

    def _on_copy_feedback(self):
        topic = self.combo_topic.currentText()
        subj = f"[{topic}] {self.feed_subject.text().strip()}"
        body = self.feed_body.toPlainText().strip()
        full_text = f"To: me.humnspace@gmail.com\nSubject: {subj}\n\n{body}"
        subprocess.run(f"powershell -command Set-Clipboard -Value @'\n{full_text}\n'@", shell=True)
        QMessageBox.information(self, "Feedback", "Feedback message copied to clipboard!")

    def _on_check_update_clicked(self):
        self.btn_check_update.setEnabled(False)
        self.lbl_upd_status.setText("Checking for updates...")
        self.lbl_upd_status.setStyleSheet("color: #A1A1AA; font-size: 11.5px;")

        upd = UpdateManager.get_instance()
        try:
            upd.update_available.disconnect()
            upd.update_not_available.disconnect()
            upd.check_failed.disconnect()
            upd.download_progress.disconnect()
            upd.download_finished.disconnect()
            upd.download_failed.disconnect()
        except Exception:
            pass
        upd.update_available.connect(self._on_update_available)
        upd.update_not_available.connect(self._on_update_not_available)
        upd.check_failed.connect(self._on_update_check_failed)
        upd.download_progress.connect(self._on_update_download_progress)
        upd.download_finished.connect(self._on_update_download_finished)
        upd.download_failed.connect(self._on_update_download_failed)
        upd.check_for_updates(manual=True)

    def _on_install_update_clicked(self):
        upd = UpdateManager.get_instance()
        if hasattr(upd, '_downloaded_setup_path') and upd._downloaded_setup_path:
            upd.install_update_and_restart(upd._downloaded_setup_path)

    def _on_update_available(self, rel: ReleaseInfo):
        self.btn_check_update.setEnabled(True)
        self.lbl_upd_status.setText(f"New update v{rel.version} is available!")
        self.lbl_upd_status.setStyleSheet("color: #4ADE80; font-size: 12px; font-weight: bold;")
        if rel.release_notes:
            self.txt_release_notes.setPlainText(rel.release_notes)
            self.txt_release_notes.show()
        self.btn_install_update.show()

    def _on_update_not_available(self, manual: bool):
        self.btn_check_update.setEnabled(True)
        self.lbl_upd_status.setText(f"ODD is up to date (v{CURRENT_VERSION}).")
        self.lbl_upd_status.setStyleSheet("color: #4ADE80; font-size: 11.5px;")
        self.txt_release_notes.hide()
        self.btn_install_update.hide()
        self.prog_update.hide()

    def _on_update_check_failed(self, error_msg: str, manual: bool):
        self.btn_check_update.setEnabled(True)
        if manual:
            self.lbl_upd_status.setText(f"Could not check for updates ({error_msg}).")
            self.lbl_upd_status.setStyleSheet("color: #F87171; font-size: 11.5px;")

    def _on_update_download_progress(self, downloaded: int, total: int, pct: float, speed_str: str):
        if pct >= 0:
            self.prog_update.show()
            self.prog_update.setValue(int(pct))
            mb_cur = downloaded / (1024 * 1024)
            mb_tot = total / (1024 * 1024) if total > 0 else mb_cur
            self.lbl_upd_status.setText(f"Downloading update: {int(pct)}% ({mb_cur:.1f}/{mb_tot:.1f} MB • {speed_str})")
        else:
            self.lbl_upd_status.setText(f"Downloading update... ({speed_str})")

    def _on_update_download_finished(self, setup_path: str, rel: ReleaseInfo):
        self.prog_update.setValue(100)
        self.lbl_upd_status.setText("Update downloaded and ready to install.")
        self.lbl_upd_status.setStyleSheet("color: #4ADE80; font-size: 12px; font-weight: bold;")
        self.btn_install_update.setText("Restart & Apply Update")
        self.btn_install_update.setEnabled(True)
        self.btn_install_update.show()

    def _on_update_download_failed(self, error_msg: str):
        self.prog_update.hide()
        self.lbl_upd_status.setText(f"Download failed: {error_msg}")
        self.lbl_upd_status.setStyleSheet("color: #F87171; font-size: 11.5px;")
        self.btn_install_update.setEnabled(True)
        self.btn_install_update.setText("Retry Download")

    def reset_defaults(self):
        reply = QMessageBox.question(
            self,
            "Reset Settings",
            "Are you sure you want to reset all settings to default?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.settings = DEFAULT_SETTINGS.copy()
            self.chk_startup.setChecked(self.settings.get("run_on_startup", True))
            if hasattr(self, 'chk_radial_menu'):
                self.chk_radial_menu.setChecked(self.settings.get("radial_menu_enabled", True))
            if hasattr(self, 'combo_radial_key'):
                idx_rk = self.combo_radial_key.findData(self.settings.get("radial_summon_key", "Alt"))
                if idx_rk >= 0:
                    self.combo_radial_key.setCurrentIndex(idx_rk)
            if hasattr(self, 'slider_radial_hold'):
                curr_hold = int(self.settings.get("radial_summon_hold_ms", 400))
                self.slider_radial_hold.setValue(curr_hold)
                if hasattr(self, 'lbl_radial_hold'):
                    self.lbl_radial_hold.setText(f"{curr_hold} ms")
            if hasattr(self, 'chk_radial_shake'):
                self.chk_radial_shake.setChecked(self.settings.get("radial_shake_dismiss_enabled", True))
            if hasattr(self, 'chk_radial_magic'):
                self.chk_radial_magic.setChecked(self.settings.get("radial_magic_cursor", True))
            if hasattr(self, 'chk_radial_bottom_music'):
                self.chk_radial_bottom_music.setChecked(self.settings.get("radial_bottom_music_overlay", True))
            if hasattr(self, 'chk_radial_search'):
                self.chk_radial_search.setChecked(self.settings.get("radial_search_enabled", True))
            if hasattr(self, 'chk_radial_qs'):
                self.chk_radial_qs.setChecked(self.settings.get("radial_qs_enabled", True))
            if hasattr(self, 'chk_radial_phone'):
                self.chk_radial_phone.setChecked(self.settings.get("radial_phone_enabled", True))
            self.chk_sound.setChecked(self.settings.get("sound_enabled", True))
            self.slider_volume.setValue(int(self.settings.get("sound_volume", 0.70) * 100))
            curr_t = str(self.settings.get("theme", "dark")).lower()
            idx_t = self.combo_theme.findData(curr_t)
            if idx_t >= 0:
                self.combo_theme.setCurrentIndex(idx_t)
            else:
                self.combo_theme.setCurrentText(curr_t)
            self.combo_edge.setCurrentText(self.settings.get("edge", "top"))
            idx = self.combo_mode.findData(self.settings.get("edge_trigger_mode", "hover"))
            if idx >= 0:
                self.combo_mode.setCurrentIndex(idx)
            self.slider_opacity.setValue(int(self.settings.get("opacity", 0.90) * 100))
            self.chk_music.setChecked(self.settings.get("enable_music_overlay", True))
            idx_m = self.combo_music_mode.findData(self.settings.get("music_overlay_mode", "auto"))
            if idx_m >= 0:
                self.combo_music_mode.setCurrentIndex(idx_m)
            if hasattr(self, 'combo_paused_media'):
                idx_pm = self.combo_paused_media.findData(self.settings.get("paused_media_behavior", "show_minimal"))
                if idx_pm >= 0:
                    self.combo_paused_media.setCurrentIndex(idx_pm)
            if hasattr(self, 'combo_media_style'):
                idx_ms = self.combo_media_style.findData(self.settings.get("island_media_style", "vinyl"))
                if idx_ms >= 0:
                    self.combo_media_style.setCurrentIndex(idx_ms)
            if hasattr(self, 'combo_media_visibility'):
                idx_mv = self.combo_media_visibility.findData(self.settings.get("island_media_visibility", "auto_hide"))
                if idx_mv >= 0:
                    self.combo_media_visibility.setCurrentIndex(idx_mv)
            if hasattr(self, 'chk_vinyl_rot'):
                self.chk_vinyl_rot.setChecked(self.settings.get("enable_vinyl_rotation", True))
            idx_a = self.combo_anim.findData(self.settings.get("animation_style", "fluid"))
            if idx_a >= 0:
                self.combo_anim.setCurrentIndex(idx_a)
            if hasattr(self, 'combo_edge_color_mode'):
                idx_cm = self.combo_edge_color_mode.findData(self.settings.get("edge_bar_color_mode", "theme"))
                if idx_cm >= 0:
                    self.combo_edge_color_mode.setCurrentIndex(idx_cm)
            if hasattr(self, 'slider_edge_width'):
                self.slider_edge_width.setValue(int(self.settings.get("edge_bar_width", 140)))
            if hasattr(self, 'slider_edge_thickness'):
                self.slider_edge_thickness.setValue(int(self.settings.get("edge_bar_thickness", 4)))
            if hasattr(self, 'chk_radial_menu'):
                self.chk_radial_menu.setChecked(self.settings.get("radial_menu_enabled", True))
            if hasattr(self, 'combo_radial_key'):
                idx_rk = self.combo_radial_key.findData(self.settings.get("radial_summon_key", "Alt"))
                if idx_rk >= 0:
                    self.combo_radial_key.setCurrentIndex(idx_rk)
            if hasattr(self, 'slider_radial_hold'):
                curr_hold = int(self.settings.get("radial_summon_hold_ms", 400))
                self.slider_radial_hold.setValue(curr_hold)
                if hasattr(self, 'lbl_radial_hold'):
                    self.lbl_radial_hold.setText(f"{curr_hold} ms")
            if hasattr(self, 'chk_radial_shake'):
                self.chk_radial_shake.setChecked(self.settings.get("radial_shake_dismiss_enabled", True))
            if hasattr(self, 'chk_radial_magic'):
                self.chk_radial_magic.setChecked(self.settings.get("radial_magic_cursor", True))
            if hasattr(self, 'chk_radial_bottom_music'):
                self.chk_radial_bottom_music.setChecked(self.settings.get("radial_bottom_music_overlay", True))
            if hasattr(self, 'chk_radial_search'):
                self.chk_radial_search.setChecked(self.settings.get("radial_search_enabled", True))
            if hasattr(self, 'chk_radial_qs'):
                self.chk_radial_qs.setChecked(self.settings.get("radial_qs_enabled", True))
            if hasattr(self, 'chk_radial_phone'):
                self.chk_radial_phone.setChecked(self.settings.get("radial_phone_enabled", True))
            if hasattr(self, 'chk_hide_edge_bar'):
                self.chk_hide_edge_bar.setChecked(self.settings.get("hide_edge_bar", False))
            if hasattr(self, 'chk_dynamic_max_delay'):
                self.chk_dynamic_max_delay.setChecked(self.settings.get("dynamic_maximized_delay", True))
            if hasattr(self, 'chk_ui_plus'):
                self.chk_ui_plus.setChecked(self.settings.get("ui_show_plus_button", True))
            if hasattr(self, 'chk_ui_quick_settings'):
                self.chk_ui_quick_settings.setChecked(self.settings.get("ui_show_quick_settings_button", True))
            if hasattr(self, 'chk_ui_music'):
                self.chk_ui_music.setChecked(self.settings.get("ui_show_music_button", True))
            if hasattr(self, 'chk_ui_lens'):
                self.chk_ui_lens.setChecked(self.settings.get("ui_show_lens_button", True))
            if hasattr(self, 'chk_ui_settings'):
                self.chk_ui_settings.setChecked(self.settings.get("ui_show_settings_button", True))
            if hasattr(self, 'chk_ui_edge_bar'):
                self.chk_ui_edge_bar.setChecked(self.settings.get("ui_show_edge_indicator", True))
            if hasattr(self, 'chk_ui_power_controls'):
                self.chk_ui_power_controls.setChecked(self.settings.get("ui_show_power_controls", True))
            if hasattr(self, 'combo_action_btn'):
                idx_ab = self.combo_action_btn.findData(self.settings.get("search_pill_action_button", "both"))
                if idx_ab >= 0:
                    self.combo_action_btn.setCurrentIndex(idx_ab)
            if hasattr(self, 'chk_mod_clip'):
                self.chk_mod_clip.setChecked(self.settings.get("enable_clipboard_history", True))
            if hasattr(self, 'chk_mod_notes'):
                self.chk_mod_notes.setChecked(self.settings.get("enable_quick_notes", True))
            if hasattr(self, 'chk_mod_conv'):
                self.chk_mod_conv.setChecked(self.settings.get("enable_unit_converter", True))
            if hasattr(self, 'chk_mod_sys'):
                self.chk_mod_sys.setChecked(self.settings.get("enable_system_commands", True))
            if hasattr(self, 'chk_mod_clock'):
                self.chk_mod_clock.setChecked(self.settings.get("enable_world_clock", True))
            if hasattr(self, 'chk_mod_color'):
                self.chk_mod_color.setChecked(self.settings.get("enable_color_inspector", True))
            if hasattr(self, 'chk_mod_calc'):
                self.chk_mod_calc.setChecked(self.settings.get("enable_calculator", True))
            if hasattr(self, 'chk_mod_web'):
                self.chk_mod_web.setChecked(self.settings.get("enable_web_shortcuts", True))
            if hasattr(self, 'chk_mod_fallbacks'):
                self.chk_mod_fallbacks.setChecked(self.settings.get("enable_web_fallbacks", True))
            if hasattr(self, 'chk_mod_messaging'):
                self.chk_mod_messaging.setChecked(self.settings.get("enable_quick_messaging", True))
            if hasattr(self, 'combo_messaging_provider'):
                idx_mp = self.combo_messaging_provider.findData(self.settings.get("messaging_provider", "whatsapp_desktop"))
                if idx_mp >= 0:
                    self.combo_messaging_provider.setCurrentIndex(idx_mp)
            if hasattr(self, 'chk_island_media'):
                self.chk_island_media.setChecked(self.settings.get("island_show_media_hud", True))
            if hasattr(self, 'chk_island_volume'):
                self.chk_island_volume.setChecked(self.settings.get("island_show_volume_hud", True))
            if hasattr(self, 'chk_island_battery'):
                self.chk_island_battery.setChecked(self.settings.get("island_show_battery_hud", True))
            if hasattr(self, 'chk_island_timer'):
                self.chk_island_timer.setChecked(self.settings.get("island_show_timer_ticker", True))
            if hasattr(self, 'chk_island_caps'):
                self.chk_island_caps.setChecked(self.settings.get("island_show_caps_lock_hud", True))
            if hasattr(self, 'chk_island_clip'):
                self.chk_island_clip.setChecked(self.settings.get("island_show_clipboard_hud", True))
            if hasattr(self, 'chk_island_downloads'):
                self.chk_island_downloads.setChecked(self.settings.get("enable_download_mode", True))
            if hasattr(self, 'chk_island_activity_mem'):
                self.chk_island_activity_mem.setChecked(self.settings.get("enable_activity_memory", True))
            if hasattr(self, 'chk_island_reminders'):
                self.chk_island_reminders.setChecked(self.settings.get("enable_island_reminders", True))
            if hasattr(self, 'chk_island_notifications'):
                self.chk_island_notifications.setChecked(self.settings.get("island_show_system_notifications", True))
            if hasattr(self, 'combo_notification_duration'):
                dur = int(self.settings.get("notification_duration_sec", 5))
                idx = self.combo_notification_duration.findData(dur)
                if idx >= 0:
                    self.combo_notification_duration.setCurrentIndex(idx)
            if hasattr(self, 'chk_water_reminder'):
                self.chk_water_reminder.setChecked(self.settings.get("enable_water_reminder", True))
            if hasattr(self, 'bottle_selector'):
                self.bottle_selector.set_style(self.settings.get("water_bottle_style", "broader_2l"))
            if hasattr(self, 'mode_water'):
                self.mode_water.set_mode(self.settings.get("water_reminder_mode", "work"))
            if hasattr(self, 'combo_water_interval'):
                cur_w = int(self.settings.get("water_reminder_interval_min", 45))
                idx_w = self.combo_water_interval.findData(cur_w)
                if idx_w >= 0:
                    self.combo_water_interval.setCurrentIndex(idx_w)
            if hasattr(self, 'chk_water_working_hours'):
                self.chk_water_working_hours.setChecked(self.settings.get("water_working_hours_only", True))
            if hasattr(self, 'edit_water_start'):
                self.edit_water_start.setText(str(self.settings.get("water_start_time", "09:00")))
            if hasattr(self, 'edit_water_end'):
                self.edit_water_end.setText(str(self.settings.get("water_end_time", "17:00")))

            # Notch Styling Reset
            if hasattr(self, 'combo_notch_style'):
                ns_val = str(self.settings.get("edge_notch_style", "simple")).strip().lower()
                if ns_val in ("bar", "pulse", "arrow", "hand", "head"):
                    ns_val = "simple"
                elif ns_val in ("text_static", "text_scroll"):
                    ns_val = "worded"
                idx_ns = self.combo_notch_style.findData(ns_val)
                if idx_ns >= 0:
                    self.combo_notch_style.setCurrentIndex(idx_ns)
            if hasattr(self, 'edit_notch_text'):
                self.edit_notch_text.setText(str(self.settings.get("edge_notch_text", "ODD")))
            if hasattr(self, 'combo_worded_mode'):
                raw_wm = str(self.settings.get("edge_worded_mode", "static")).strip().lower()
                idx_wm = self.combo_worded_mode.findData("scroll" if "scroll" in raw_wm else "static")
                if idx_wm >= 0:
                    self.combo_worded_mode.setCurrentIndex(idx_wm)

            # Wellness Reminders Reset
            if hasattr(self, 'chk_eye_rest'):
                self.chk_eye_rest.setChecked(self.settings.get("enable_eye_rest_reminder", True))
            if hasattr(self, 'mode_eye_rest'):
                self.mode_eye_rest.set_mode(self.settings.get("eye_rest_reminder_mode", "work"))
            if hasattr(self, 'combo_eye_interval'):
                idx_ei = self.combo_eye_interval.findData(int(self.settings.get("eye_rest_interval_min", 60)))
                if idx_ei >= 0:
                    self.combo_eye_interval.setCurrentIndex(idx_ei)

            if hasattr(self, 'chk_posture'):
                self.chk_posture.setChecked(self.settings.get("enable_posture_reminder", True))
            if hasattr(self, 'combo_posture_interval'):
                idx_pi = self.combo_posture_interval.findData(int(self.settings.get("posture_interval_min", 60)))
                if idx_pi >= 0:
                    self.combo_posture_interval.setCurrentIndex(idx_pi)

            if hasattr(self, 'chk_ventilation'):
                self.chk_ventilation.setChecked(self.settings.get("enable_ventilation_reminder", True))
            if hasattr(self, 'combo_vent_interval'):
                idx_vi = self.combo_vent_interval.findData(int(self.settings.get("ventilation_interval_min", 120)))
                if idx_vi >= 0:
                    self.combo_vent_interval.setCurrentIndex(idx_vi)

            # Battery Care & Storage Hygiene Reset
            if hasattr(self, 'chk_battery_health'):
                self.chk_battery_health.setChecked(self.settings.get("enable_battery_health_alert", True))
            if hasattr(self, 'chk_battery_auto_detect'):
                self.chk_battery_auto_detect.setChecked(self.settings.get("battery_auto_detect_plug", True))
            if hasattr(self, 'chk_system_needs'):
                self.chk_system_needs.setChecked(self.settings.get("system_needs_intelligence", True))
            if hasattr(self, 'spin_battery_high'):
                self.spin_battery_high.setValue(int(self.settings.get("battery_high_limit", 80)))
            if hasattr(self, 'spin_battery_low'):
                self.spin_battery_low.setValue(int(self.settings.get("battery_low_limit", 30)))

            if hasattr(self, 'chk_storage_purge'):
                self.chk_storage_purge.setChecked(self.settings.get("enable_storage_purge_reminder", True))
            if hasattr(self, 'combo_purge_interval'):
                idx_purg = self.combo_purge_interval.findData(int(self.settings.get("storage_purge_interval_days", 14)))
                if idx_purg >= 0:
                    self.combo_purge_interval.setCurrentIndex(idx_purg)

            self._sync_home_quick_controls_from_main()
            self._update_edge_preview()
            self.populate_prefixes_table()

    # ------------------- Theme & Styling (Neutral Dark Gray / Light Settings Style) -------------------
    def apply_global_theme(self):
        theme = str(self.settings.get("theme", "dark")).lower()

        for sw in self._toggle_switches:
            sw.set_theme_mode(theme)

        if hasattr(self, 'logo_lbl'):
            self.logo_lbl.setPixmap(get_odd_logo_pixmap((30, 30), theme))
        if hasattr(self, 'logo_lbl_u'):
            self.logo_lbl_u.setPixmap(get_odd_logo_pixmap((44, 44), theme))
        if hasattr(self, 'search_bar'):
            self.search_bar.set_theme_mode(theme)
        if hasattr(self, 'shortcut_selector'):
            self.shortcut_selector.apply_theme(theme)
        if hasattr(self, 'home_shortcut_selector'):
            self.home_shortcut_selector.apply_theme(theme)

        if theme == "light":
            text_primary = "#18181B"
            text_secondary = "#52525B"
            text_sub_lbl = "#71717A"
            bg_dialog = "#F4F4F5"
            bg_sidebar = "#EAEAEF"
            bg_card = "#FFFFFF"
            bg_card_hover = "#FAFAFA"
            border_card = "#E4E4E7"
            border_card_hover = "#A1A1AA"
            divider_col = "#ECECEE"
            bg_input = "#FFFFFF"
            border_input = "1px solid #D4D4D8"
            bg_badge = "#E4E4E7"
            border_badge = "1px solid #D4D4D8"
            icon_box_bg = "#E4E4E7"
            icon_box_col = "#27272A"
            nav_item_color = "#3F3F46"
            nav_item_hover_bg = "rgba(0, 0, 0, 0.05)"
            nav_item_hover_col = "#18181B"
            nav_item_sel_bg = "#E4E4E7"
            nav_item_sel_col = "#18181B"
            btn_primary_bg = "#27272A"
            btn_primary_col = "#FFFFFF"
            btn_primary_hover = "#3F3F46"
            btn_sec_bg = "#FFFFFF"
            btn_sec_col = "#18181B"
            btn_sec_border = "1px solid #D4D4D8"
            btn_sec_hover = "#F4F4F5"
            nav_icon_color = "#52525B"
            nav_icon_active = "#18181B"
            combo_arrow_svg = get_combo_arrow_svg_path("#18181B")
            slider_groove = "#D4D4D8"
            slider_fill = "#3F3F46"
            popup_bg = "#FFFFFF"
        else:
            # Modern Neutral Dark Gray Settings palette (#111113 background, #1C1C1F separated containers)
            text_primary = "#F4F4F5"
            text_secondary = "#D4D4D8"
            text_sub_lbl = "#A1A1AA"
            bg_dialog = "#111113"
            bg_sidebar = "#18181B"
            bg_card = "#1C1C1F"
            bg_card_hover = "#252529"
            border_card = "rgba(255, 255, 255, 0.08)"
            border_card_hover = "rgba(255, 255, 255, 0.18)"
            divider_col = "rgba(255, 255, 255, 0.06)"
            bg_input = "#161618"
            border_input = "1px solid rgba(255, 255, 255, 0.12)"
            bg_badge = "#222225"
            border_badge = "1px solid rgba(255, 255, 255, 0.12)"
            icon_box_bg = "#222225"
            icon_box_col = "#E4E4E7"
            nav_item_color = "#D4D4D8"
            nav_item_hover_bg = "rgba(255, 255, 255, 0.06)"
            nav_item_hover_col = "#FFFFFF"
            nav_item_sel_bg = "#2C2C30"
            nav_item_sel_col = "#FAFAFA"
            btn_primary_bg = "#2E2E32"
            btn_primary_col = "#FAFAFA"
            btn_primary_hover = "#3E3E44"
            btn_sec_bg = "#1C1C1F"
            btn_sec_col = "#F4F4F5"
            btn_sec_border = "1px solid rgba(255, 255, 255, 0.12)"
            btn_sec_hover = "#28282D"
            nav_icon_color = "#A1A1AA"
            nav_icon_active = "#FAFAFA"
            combo_arrow_svg = get_combo_arrow_svg_path("#E4E4E7")
            slider_groove = "#252528"
            slider_fill = "#71717A"
            popup_bg = "#1C1C1F"

        accent = "#18181B" if theme == "light" else "#D4D4D8"

        style = f"""
            * {{ outline: none; }}
            QDialog {{
                background-color: {bg_dialog};
                color: {text_primary};
            }}
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background: transparent;
            }}
            QFrame#SidebarPanel {{
                background-color: {bg_sidebar};
                border: 1px solid {border_card};
                border-radius: 12px;
            }}
            QFrame#SettingCard {{
                background-color: {bg_card};
                border: 1px solid {border_card};
                border-radius: 12px;
            }}
            QFrame#SettingCard:hover {{
                border: 1px solid {border_card_hover};
            }}
            QFrame#SettingDivider {{
                background-color: {divider_col};
                border: none;
            }}
            QFrame#Forms11Card {{
                background-color: {bg_card};
                border: 1px solid {border_card};
                border-radius: 12px;
            }}
            QFrame#Forms11Header {{
                background: transparent;
                border: none;
            }}
            QLabel#Forms11Title {{
                color: {text_primary};
                font-weight: 600;
            }}
            QLabel#Forms11Sub {{
                color: {text_sub_lbl};
            }}
            QLabel#Forms11Badge {{
                background: {bg_badge};
                color: {accent};
                border: {border_badge};
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: bold;
            }}
            QLabel#UseCaseTitle {{
                color: {text_primary};
                font-weight: 600;
            }}
            QLabel#UseCaseSub {{
                color: {text_sub_lbl};
            }}
            QLabel#UseCaseBadge {{
                background: {bg_badge};
                color: {icon_box_col};
                border: {border_badge};
                border-radius: 6px;
                padding: 1px 6px;
                font-size: 9.5px;
                font-weight: bold;
            }}
            QLabel#UseCaseIconBox {{
                background-color: {icon_box_bg};
                border-radius: 8px;
            }}
            QFrame#AssetCard {{
                background-color: {bg_card};
                border: 1px solid {border_card};
                border-radius: 10px;
            }}
            QFrame#AssetCard:hover {{
                background-color: {bg_card_hover};
                border: 1px solid {border_card_hover};
            }}
            QLabel#AssetTitle {{
                color: {text_primary};
                font-weight: 600;
            }}
            QLabel#AssetSub {{
                color: {text_sub_lbl};
            }}
            QLabel#AssetIconBox {{
                background-color: {icon_box_bg};
                border-radius: 8px;
            }}
            QLabel#AssetCategoryBadge {{
                background: {bg_badge};
                color: {icon_box_col};
                border: {border_badge};
                border-radius: 4px;
                padding: 1px 5px;
                font-size: 9px;
                font-weight: bold;
            }}
            QLabel#AssetMetaChip {{
                color: {text_sub_lbl};
                font-size: 10px;
                background: rgba(0, 0, 0, 0.04);
                border-radius: 4px;
                padding: 1px 6px;
            }}
            QFrame#QuietHoursCard {{
                background-color: {bg_card};
                border: 1px solid {border_card};
                border-radius: 12px;
            }}
            QLabel#QuietHoursIconBox {{
                background-color: {icon_box_bg};
                border-radius: 8px;
            }}
            QFrame#IntegrationCard {{
                background-color: {bg_card};
                border: 1px solid {border_card};
                border-radius: 10px;
            }}
            QFrame#IntegrationCard:hover {{
                background-color: {bg_card_hover};
                border: 1px solid {border_card_hover};
            }}
            QLabel#IntegrationTitle {{
                color: {text_primary};
                font-weight: 600;
            }}
            QLabel#IntegrationSub {{
                color: {text_sub_lbl};
            }}
            QLabel#IntegrationIconBox {{
                background-color: {icon_box_bg};
                border-radius: 8px;
            }}
            QLabel#IntegrationCategoryBadge {{
                background: {bg_badge};
                color: {icon_box_col};
                border: {border_badge};
                border-radius: 4px;
                padding: 1px 5px;
                font-size: 9px;
                font-weight: bold;
            }}
            QLabel#IntegrationStatusPill {{
                color: #10B981;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton#IntegrationActionBtn {{
                background: {btn_sec_bg};
                color: {btn_sec_col};
                border: {btn_sec_border};
                border-radius: 6px;
                padding: 2px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#IntegrationActionBtn:hover {{
                background: {btn_sec_hover};
                color: {text_primary};
            }}
            QFrame#HomeCategoryCard {{
                background-color: {bg_card};
                border: 1px solid {border_card};
                border-radius: 11px;
            }}
            QFrame#HomeCategoryCard:hover {{
                background-color: {bg_card_hover};
                border: 1px solid {border_card_hover};
            }}
            QFrame#SearchResultCard {{
                background-color: {bg_card};
                border: 1px solid {border_card};
                border-radius: 10px;
            }}
            QFrame#SearchResultCard:hover {{
                background-color: {bg_card_hover};
                border: 1px solid {border_card_hover};
            }}
            QPushButton#SearchResultOpenBtn {{
                background: {btn_sec_bg};
                color: {btn_sec_col};
                border: {btn_sec_border};
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton#SearchResultOpenBtn:hover {{
                background: {btn_sec_hover};
                color: {text_primary};
            }}
            QLabel#HomeCardIconBox {{
                background-color: {icon_box_bg};
                border-radius: 10px;
            }}
            QLabel#HomeCardTitle {{
                color: {text_primary};
                background: transparent;
            }}
            QLabel#HomeCardSub {{
                color: {text_sub_lbl};
                background: transparent;
            }}
            QLabel#HomeCardArrow {{
                color: {text_sub_lbl};
                background: transparent;
            }}
            QLabel#HomeCardBadge {{
                background: {bg_badge};
                color: {icon_box_col};
                border: {border_badge};
                border-radius: 8px;
                padding: 1px 7px;
                font-size: 10px;
                font-weight: 600;
            }}
            QLabel {{
                color: {text_primary};
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 7px;
                margin: 0px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {border_card_hover};
                min-height: 26px;
                border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QSlider::groove:horizontal {{
                height: 5px;
                background: {slider_groove};
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {slider_fill};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                border: 2px solid {slider_fill};
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
        """
        self.setStyleSheet(style)

        # Update Home Category Card icons
        for card in self._home_cards:
            card.update_icon_theme(icon_box_col)

        # Update Group Section Headers, Row Titles, and Subtitles
        for gh in self._group_headers:
            gh.setStyleSheet(f"color: {text_secondary}; font-size: 11.5px; font-weight: 700; letter-spacing: 0.3px;")
        for rt in self._row_titles:
            rt.setStyleSheet(f"color: {text_primary};")
        for rs in self._row_subtitles:
            rs.setStyleSheet(f"color: {text_sub_lbl};")

        # ComboBoxes
        combo_box_style = f"""
            QComboBox {{
                background-color: {bg_input};
                border: {border_input};
                border-radius: 7px;
                padding: 5px 26px 5px 11px;
                color: {text_primary};
                font-size: 11.5px;
                font-weight: 500;
                min-height: 22px;
                outline: none;
            }}
            QComboBox:hover {{
                border-color: {border_card_hover};
            }}
            QComboBox:focus, QComboBox:on {{
                border-color: {icon_box_col};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border: none;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({combo_arrow_svg});
                width: 10px;
                height: 10px;
            }}
        """
        combo_view_style = f"""
            QListView {{
                background-color: {popup_bg};
                color: {text_primary};
                border: 1px solid {border_card_hover};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QListView::item {{
                color: {text_primary};
                background-color: transparent;
                padding: 6px 10px;
                border-radius: 5px;
                margin: 1px 0px;
                min-height: 20px;
            }}
            QListView::item:hover {{
                background-color: {nav_item_hover_bg};
                color: {text_primary};
            }}
            QListView::item:selected {{
                background-color: {nav_item_sel_bg};
                color: {nav_item_sel_col};
                font-weight: 600;
            }}
        """
        for combo_attr in (
            'home_combo_theme', 'home_combo_messaging',
            'combo_sound_theme', 'combo_music_mode', 'combo_paused_media',
            'combo_action_btn', 'combo_theme', 'combo_edge', 'combo_mode',
            'combo_anim', 'combo_edge_color_mode', 'combo_topic',
            'combo_media_style', 'combo_media_visibility',
            'combo_messaging_provider', 'combo_notification_duration',
            'combo_notch_style', 'combo_water_interval', 'combo_eye_interval',
            'combo_posture_interval', 'combo_vent_interval', 'combo_purge_interval'
        ):
            if hasattr(self, combo_attr):
                cb = getattr(self, combo_attr)
                if cb:
                    cb.setStyleSheet(combo_box_style)
                    if cb.view():
                        cb.view().setStyleSheet(combo_view_style)

        # Header & Back to Home Buttons
        if hasattr(self, 'title_lbl'):
            self.title_lbl.setStyleSheet(f"color: {text_primary};")
        if hasattr(self, 'sub_lbl'):
            self.sub_lbl.setStyleSheet(f"color: {text_sub_lbl};")
        if hasattr(self, 'ver_badge'):
            self.ver_badge.setStyleSheet(
                f"background: {bg_badge}; color: {icon_box_col}; border-radius: 10px; padding: 3px 10px; border: {border_badge};"
            )
        if hasattr(self, 'btn_back_home'):
            self.btn_back_home.setStyleSheet(f"""
                QPushButton {{
                    background: {btn_sec_bg};
                    color: {text_primary};
                    border: {btn_sec_border};
                    border-radius: 8px;
                    padding: 4px 12px;
                    font-size: 11.5px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background: {btn_sec_hover};
                    border-color: {border_card_hover};
                }}
            """)
        if hasattr(self, 'btn_search_back'):
            self.btn_search_back.setStyleSheet(f"""
                QPushButton {{
                    background: {btn_sec_bg};
                    color: {text_primary};
                    border: {btn_sec_border};
                    border-radius: 8px;
                    padding: 4px 12px;
                    font-size: 11.5px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background: {btn_sec_hover};
                    border-color: {border_card_hover};
                }}
            """)
        if hasattr(self, 'lbl_search_header'):
            self.lbl_search_header.setStyleSheet(f"color: {text_primary};")
        if hasattr(self, 'lbl_search_count'):
            self.lbl_search_count.setStyleSheet(f"color: {text_secondary};")
        if hasattr(self, 'search_bar'):
            self.search_bar.set_theme_mode(theme)
        if hasattr(self, 'btn_sidebar_home'):
            self.btn_sidebar_home.setStyleSheet(f"""
                QPushButton {{
                    background: {bg_card};
                    color: {text_primary};
                    border: 1px solid {border_card};
                    border-radius: 7px;
                    padding: 6px 10px;
                    font-size: 12px;
                    font-weight: 600;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: {bg_card_hover};
                    border-color: {border_card_hover};
                    color: {text_primary};
                }}
            """)
        if hasattr(self, 'btn_header_close'):
            self.btn_header_close.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {text_sub_lbl};
                    border: none;
                    border-radius: 14px;
                    font-size: 13px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: {nav_item_hover_bg}; color: {text_primary}; }}
            """)

        # Sidebar Nav List
        if hasattr(self, 'nav_list'):
            self.nav_list.setStyleSheet(f"""
                QListWidget {{
                    background: transparent;
                    border: none;
                    padding: 0px;
                    outline: none;
                }}
                QListWidget::item {{
                    color: {nav_item_color};
                    padding: 8px 10px;
                    border-radius: 7px;
                    margin-bottom: 2px;
                    font-size: 12px;
                    font-weight: 500;
                }}
                QListWidget::item:hover {{
                    background: {nav_item_hover_bg};
                    color: {nav_item_hover_col};
                }}
                QListWidget::item:selected {{
                    background: {nav_item_sel_bg};
                    color: {nav_item_sel_col};
                    font-weight: 600;
                }}
            """)
            if hasattr(self, 'nav_defs'):
                for i, (_t_title, i_name, _desc) in enumerate(self.nav_defs):
                    item = self.nav_list.item(i)
                    if item:
                        item.setIcon(get_vector_icon(i_name, nav_icon_color, 16, active_color=nav_icon_active))

        # Value Badges
        for val_attr in ('vol_val_lbl', 'op_val_lbl', 'lbl_ew_val', 'lbl_et_val'):
            if hasattr(self, val_attr):
                getattr(self, val_attr).setStyleSheet(f"color: {text_primary}; font-size: 11px; font-weight: 600;")
        if hasattr(self, 'lbl_upd_cur_ver'):
            self.lbl_upd_cur_ver.setStyleSheet(
                f"background: {bg_badge}; color: {icon_box_col}; border: {border_badge}; border-radius: 5px; padding: 2px 8px;"
            )
        for desc_attr in ('lbl_platform', 'lbl_email_link'):
            if hasattr(self, desc_attr):
                getattr(self, desc_attr).setStyleSheet(f"color: {text_sub_lbl}; font-size: 11px;")

        # Footer & Secondary Buttons
        if hasattr(self, 'btn_reset'):
            self.btn_reset.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {text_sub_lbl};
                    border: none;
                    padding: 6px 10px;
                    font-size: 11.5px;
                }}
                QPushButton:hover {{ color: #F87171; }}
            """)
        if hasattr(self, 'btn_cancel'):
            self.btn_cancel.setStyleSheet(f"""
                QPushButton {{
                    background: {btn_sec_bg};
                    color: {text_secondary};
                    border: {btn_sec_border};
                    border-radius: 7px;
                    padding: 7px 18px;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background: {btn_sec_hover}; color: {text_primary}; }}
            """)
        if hasattr(self, 'btn_save'):
            self.btn_save.setStyleSheet(f"""
                QPushButton {{
                    background: {btn_primary_bg};
                    color: {btn_primary_col};
                    border: 1px solid {border_card_hover};
                    border-radius: 7px;
                    padding: 7px 22px;
                    font-size: 12px;
                    font-weight: 700;
                }}
                QPushButton:hover {{ background: {btn_primary_hover}; }}
            """)

        for btn_sec_attr in ('btn_test_sound', 'btn_pick_custom', 'btn_add_prefix', 'btn_check_update', 'btn_copy', 'btn_reset_prefixes'):
            if hasattr(self, btn_sec_attr):
                getattr(self, btn_sec_attr).setStyleSheet(f"""
                    QPushButton {{
                        background: {btn_sec_bg};
                        color: {btn_sec_col};
                        border: {btn_sec_border};
                        border-radius: 6px;
                        padding: 5px 12px;
                        font-size: 11.5px;
                    }}
                    QPushButton:hover {{ background: {btn_sec_hover}; }}
                """)

        if hasattr(self, 'btn_mail'):
            self.btn_mail.setStyleSheet(f"""
                QPushButton {{
                    background: {btn_primary_bg};
                    color: {btn_primary_col};
                    border: 1px solid {border_card_hover};
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-weight: 600;
                    font-size: 11.5px;
                }}
                QPushButton:hover {{ background: {btn_primary_hover}; }}
            """)
        if hasattr(self, 'btn_visit_site'):
            self.btn_visit_site.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {text_secondary};
                    border: none;
                    font-size: 11.5px;
                    text-decoration: underline;
                }}
                QPushButton:hover {{ color: {text_primary}; }}
            """)

        # Prefixes Table
        if hasattr(self, 'table_prefixes'):
            self.table_prefixes.setStyleSheet(f"""
                QTableWidget {{
                    background: transparent;
                    border: none;
                    selection-background-color: {nav_item_sel_bg};
                    color: {text_primary};
                }}
                QTableWidget::item {{
                    padding: 7px 10px;
                    border-bottom: 1px solid {divider_col};
                }}
                QHeaderView::section {{
                    background: transparent;
                    color: {text_sub_lbl};
                    padding: 6px 10px;
                    font-weight: 600;
                    font-size: 11.5px;
                    border: none;
                    border-bottom: 1px solid {border_card};
                }}
            """)

        # Text & Input Fields
        for in_attr in ('feed_subject', 'feed_body', 'txt_release_notes'):
            if hasattr(self, in_attr):
                getattr(self, in_attr).setStyleSheet(f"""
                    QLineEdit, QTextEdit {{
                        background: {bg_input};
                        border: {border_input};
                        border-radius: 7px;
                        padding: 8px 10px;
                        color: {text_primary};
                        font-size: 12px;
                    }}
                    QLineEdit:focus, QTextEdit:focus {{
                        border-color: {border_card_hover};
                    }}
                """)

    def save_and_apply(self):
        self._on_setting_live_changed()

        new_prefixes = {}
        for r in range(self.table_prefixes.rowCount()):
            p_item = self.table_prefixes.item(r, 0)
            a_item = self.table_prefixes.item(r, 1)
            if p_item and a_item:
                p_text = p_item.text().strip()
                a_text = a_item.text().strip()
                if p_text and a_text:
                    new_prefixes[p_text] = a_text
        if new_prefixes:
            self.settings["prefixes"] = new_prefixes

        save_settings(self.settings)
        try:
            set_startup_enabled(self.settings.get("run_on_startup", True))
        except Exception:
            pass
        try:
            import odd_weather
            odd_weather.WeatherManager.get_instance().refresh(force=True, settings=self.settings)
        except Exception:
            pass
        self.settings_changed.emit(self.settings)
        self.accept()

    def closeEvent(self, event):
        self._flush_save_settings()
        event.accept()

    def show_updates_tab(self):
        for idx, (title, _, _) in enumerate(self.nav_defs):
            if "Update" in title:
                self.open_category(idx)
                break
        self.show()
        self.raise_()
        self.activateWindow()

    def show_feedback_tab(self):
        for idx, (title, _, _) in enumerate(self.nav_defs):
            if "Feedback" in title:
                self.open_category(idx)
                break
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.root_stack.currentIndex() == 1:
                self.show_home_view()
                return
            self.reject()
            return
        super().keyPressEvent(event)
