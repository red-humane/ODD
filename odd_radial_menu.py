"""
ODD Contextual E2U Radial Arc & Dedicated Search Interface System
=================================================================
"ODD should disappear when you don't need it, appear when you summon it, and get out of your way when you're done."

Key Characteristics:
- The Arc is centered directly around the cursor with ZERO central circle/hub.
- Compact, minimal, monochrome Black & White aesthetic.
- 5 Primary Actions:
    0: Quick Settings
    1: Google Lens
    2: Search (Apex/Middle)
    3: Phone Mirror
    4: ODD Settings (Official ODD Logo Icon: white orbital ring + red dot)
- Selected slice expands slightly on hover (+6px pop).
- Small contextual floating pill label on hover (no permanent large text).
- Automatic edge-aware positioning (never clips offscreen).
- Liquid Morphing Animation:
    - Typing or clicking Search morphs smoothly into the DEDICATED Dynamic-Island-Style Search UI
      positioned contextually around the cursor.
    - Uses authentic ResultItemWidget rendering (matching Image 2 with 28x28 plates,
      APP/FOLDER/FILE/CODE/DOC pill badges, Segoe UI Variable typography).
    - Phone Mirror opens the Android Phone Mirror interface and stays open.
    - Quick Settings opens the Quick Settings interface.
- Zero-latency dismissal on click-outside, Esc, and rapid cursor shake.
"""

import sys
import os
import time
import math
import ctypes
import threading
from ctypes import wintypes
from typing import Optional, Tuple, List, Callable

from PySide6.QtCore import (
    Qt, QObject, Signal, Slot, QTimer, QRect, QRectF, QPoint, QPointF,
    QSize, QEvent, QPropertyAnimation, QEasingCurve
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QPainterPath, QLinearGradient,
    QRadialGradient, QCursor, QGuiApplication, QKeyEvent, QMouseEvent,
    QIcon, QPixmap
)
from PySide6.QtWidgets import (
    QWidget, QApplication, QLineEdit, QListWidget, QListWidgetItem,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout, QPushButton
)

try:
    from odd_sound import play_sound, play_hover, play_action, play_sink
except Exception:
    def play_sound(*args, **kwargs): pass
    def play_hover(*args, **kwargs): pass
    def play_action(*args, **kwargs): pass
    def play_sink(*args, **kwargs): pass

try:
    from odd_spring import SpringValue
except Exception:
    class SpringValue:
        def __init__(self, initial_value=0.0, **kwargs):
            self.value = float(initial_value)
            self.target = float(initial_value)
        def set_target(self, t, **kwargs): self.target = float(t)
        def update(self, dt): self.value += (self.target - self.value) * min(1.0, dt * 14.0)
        def snap_to(self, v): self.value = self.target = float(v)
        def is_settled(self): return abs(self.target - self.value) < 0.005

try:
    from odd_theme import create_squircle_path
except Exception:
    def create_squircle_path(rect, r):
        p = QPainterPath()
        p.addRoundedRect(QRectF(rect), float(r), float(r))
        return p

try:
    from odd_overlay import ResultItemWidget, get_search_item_monochrome_pixmap, QuickSettingsCard
except Exception:
    ResultItemWidget = None
    get_search_item_monochrome_pixmap = None
    QuickSettingsCard = None

try:
    from odd_search import SearchItem, WindowsSearchEngine
except Exception:
    class SearchItem:
        def __init__(self, id, title, subtitle, category="app", target="", action=None):
            self.id = id
            self.title = title
            self.subtitle = subtitle
            self.category = category
            self.target = target
            self.action = action


# ---------------------------------------------------------------------------
# Win32 Text Field / Caret & Drag Detection
# ---------------------------------------------------------------------------

class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_uint),
        ('flags', ctypes.c_uint),
        ('hwndActive', wintypes.HWND),
        ('hwndFocus', wintypes.HWND),
        ('hwndCapture', wintypes.HWND),
        ('hwndMenuOwner', wintypes.HWND),
        ('hwndMoveSize', wintypes.HWND),
        ('hwndCaret', wintypes.HWND),
        ('rcCaret', wintypes.RECT),
    ]


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('hCursor', wintypes.HANDLE),
        ('ptScreenPos', wintypes.POINT)
    ]


def is_caret_or_text_focused() -> bool:
    """Detects whether the user is actively typing or focused in an editable text field."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        fg = user32.GetForegroundWindow()
        if not fg:
            return False

        # 1. Cursor shape check (I-beam cursor: mouse is over or inside editable text)
        ci = _CURSORINFO()
        ci.cbSize = ctypes.sizeof(_CURSORINFO)
        if user32.GetCursorInfo(ctypes.byref(ci)):
            ibeam = user32.LoadCursorW(0, 32513)  # IDC_IBEAM
            if ci.hCursor and ibeam and ci.hCursor == ibeam:
                return True

        # 2. GUI Thread Info check (active caret or blinking text input)
        pid = wintypes.DWORD()
        tid = user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        if tid:
            gui = _GUITHREADINFO()
            gui.cbSize = ctypes.sizeof(_GUITHREADINFO)
            if user32.GetGUIThreadInfo(tid, ctypes.byref(gui)):
                if gui.hwndCaret or (gui.flags & 1):
                    return True
                if gui.hwndFocus:
                    buf = ctypes.create_unicode_buffer(128)
                    user32.GetClassNameW(gui.hwndFocus, buf, 128)
                    cls_name = buf.value.lower()
                    if any(t in cls_name for t in ('edit', 'richedit', 'textbox', 'scintilla', 'searchbox', 'input', 'textarea')):
                        return True
    except Exception:
        pass
    return False


def is_mouse_dragging() -> bool:
    """Returns True if any mouse button is currently held down (drag/drop or text selection)."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        return bool((user32.GetAsyncKeyState(0x01) | user32.GetAsyncKeyState(0x02) | user32.GetAsyncKeyState(0x04)) & 0x8000)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Radial Hold Indicator & Magic Animated Cursor (Specular Shine & Music Progress)
# ---------------------------------------------------------------------------

class RadialHoldIndicator(QWidget):
    """
    Minimal Radial Summon Hold Indicator:
    - Pure luminous white hairline progress arc (1.8px) around cursor during Alt hold.
    - Zero background, completely non-intrusive.
    - Dismisses instantly when Alt is released or completed.
    """
    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._size = 40
        self.setFixedSize(self._size, self._size)
        self._progress: float = 0.0

    def set_progress(self, val: float):
        self._progress = max(0.0, min(1.0, val))
        if self._progress > 0.005:
            if not self.isVisible():
                self._reposition_to_cursor()
                self.show()
                self.raise_()
        else:
            if self.isVisible():
                self.hide()
        self.update()

    def set_music_state(self, is_playing: bool = False, progress: float = 0.0, cover_color: Optional[QColor] = None):
        """Deprecated: Cursor music progress removed per user request."""
        pass

    def _reposition_to_cursor(self):
        try:
            from ctypes import wintypes
            pt = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                pos_x, pos_y = pt.x, pt.y
            else:
                p = QCursor.pos()
                pos_x, pos_y = p.x(), p.y()
        except Exception:
            p = QCursor.pos()
            pos_x, pos_y = p.x(), p.y()

        half = self.width() / 2.0
        tx = int(pos_x - half)
        ty = int(pos_y - half)

        try:
            hwnd = int(self.winId())
            # SWP_NOSIZE (0x0001) | SWP_NOACTIVATE (0x0010) | SWP_NOZORDER (0x0004)
            ctypes.windll.user32.SetWindowPos(hwnd, -1, tx, ty, 0, 0, 0x0001 | 0x0010 | 0x0004)
        except Exception:
            self.move(tx, ty)

    def paintEvent(self, event):
        if self._progress <= 0.005:
            return

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            cx = self.width() / 2.0
            cy = self.height() / 2.0
            r_outer = 13.0

            arc_rect = QRectF(cx - r_outer, cy - r_outer, r_outer * 2.0, r_outer * 2.0)
            start_angle = 90 * 16  # Top (12 o'clock)
            span_angle = -int(self._progress * 360 * 16)  # Clockwise sweep

            # Crisp white progress arc - hairline 1.8px
            progress_pen = QPen(QColor(255, 255, 255, 255), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(progress_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(arc_rect, start_angle, span_angle)

            # Leading Edge Dot
            lead_rad = (math.pi / 2.0) - (self._progress * 2.0 * math.pi)
            dot_x = cx + r_outer * math.cos(lead_rad)
            dot_y = cy - r_outer * math.sin(lead_rad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
            painter.drawEllipse(QPointF(dot_x, dot_y), 1.8, 1.8)
        finally:
            painter.end()


# ---------------------------------------------------------------------------
# Minimal Bottom Music Overlay for Radial Menu
# ---------------------------------------------------------------------------

class RadialBottomMusicBar(QWidget):
    """
    Very minimal bottom music overlay for the Radial Menu:
    Shows music name (title • artist) and pause/play button.
    Dark frosted AMOLED pill with clean typography and vector controls.
    """
    def __init__(self, overlay=None, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self._is_playing = False
        self._title = ""
        self._artist = ""
        self.setFixedHeight(32)
        self.setFixedWidth(206)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(6)

        # Micro music note icon
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(14, 14)
        self._render_music_icon()
        layout.addWidget(self.icon_label)

        # Song info label
        self.title_label = QLabel("No Media", self)
        self.title_label.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet("color: rgba(255, 255, 255, 0.90); background: transparent;")
        self.title_label.setToolTip("")
        layout.addWidget(self.title_label, 1)

        # Play / Pause vector button
        self.btn_play = QPushButton(self)
        self.btn_play.setFixedSize(22, 22)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.24);
                border: 1px solid rgba(255, 255, 255, 0.32);
            }
        """)
        self.btn_play.clicked.connect(self._on_toggle_play_pause)
        layout.addWidget(self.btn_play)
        self._update_play_icon()

    def _render_music_icon(self):
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(QBrush(QColor(255, 255, 255, 210)))
        p.drawEllipse(2, 8, 4, 3)
        p.drawLine(6, 9, 6, 3)
        p.drawLine(6, 3, 10, 2)
        p.drawLine(10, 2, 10, 7)
        p.drawEllipse(7, 7, 4, 3)
        p.end()
        self.icon_label.setPixmap(pix)

    def _update_play_icon(self):
        pix = QPixmap(22, 22)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._is_playing:
            # Draw Pause bars
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 240)))
            p.drawRoundedRect(QRectF(7.0, 6.0, 2.4, 10.0), 1.0, 1.0)
            p.drawRoundedRect(QRectF(12.6, 6.0, 2.4, 10.0), 1.0, 1.0)
            self.btn_play.setToolTip("Pause")
        else:
            # Draw Play triangle
            path = QPainterPath()
            path.moveTo(8.5, 6.0)
            path.lineTo(15.5, 11.0)
            path.lineTo(8.5, 16.0)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.fillPath(path, QBrush(QColor(255, 255, 255, 240)))
            self.btn_play.setToolTip("Play")
        p.end()
        self.btn_play.setIcon(QIcon(pix))
        self.btn_play.setIconSize(QSize(22, 22))

    def _on_toggle_play_pause(self):
        play_action(getattr(self.overlay, "settings", {}))
        if hasattr(self.overlay, "media_mgr") and self.overlay.media_mgr:
            try:
                self.overlay.media_mgr.toggle_play_pause()
            except Exception:
                pass
        self._is_playing = not self._is_playing
        self._update_play_icon()

    def update_state(self, state: dict):
        if not state:
            self._is_playing = False
            self.hide()
            return
        self._is_playing = bool(state.get("is_playing", False))
        raw_title = str(state.get("title", "")).strip()
        raw_artist = str(state.get("artist", "")).strip()

        if self._is_playing and raw_title:
            self._title = raw_title
            self._artist = raw_artist
            full_text = f"{raw_title} • {raw_artist}" if raw_artist else raw_title
            self.title_label.setText(self._elide_text(full_text, 138))
            self.title_label.setToolTip(full_text)
            self._update_play_icon()
            self.show()
        else:
            self._title = ""
            self._artist = ""
            self.hide()

    def _elide_text(self, text: str, max_w: int) -> str:
        fm = self.title_label.fontMetrics()
        return fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w)

    def mousePressEvent(self, event):
        # Prevent radial menu from closing when clicking on the music bar
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
            path = create_squircle_path(r, 16.0)

            # Translucent dark frosted AMOLED glass
            painter.fillPath(path, QBrush(QColor(18, 18, 22, 235)))
            painter.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
            painter.strokePath(path, painter.pen())
        finally:
            painter.end()


# ---------------------------------------------------------------------------
# Liquid Morphing Animation (Proxy from Cursor Arc to Dedicated Search UI)
# ---------------------------------------------------------------------------

class ArcMorphToOverlayAnimation(QWidget):
    """
    Fluid Liquid Morph Animation:
    Morphs smoothly from the circular Arc geometry at cursor into the dedicated
    Dynamic Island Search Panel geometry right at the cursor.
    """
    def __init__(self, overlay=None, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.overlay = overlay
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._start_rect = QRectF(0, 0, 0, 0)
        self._target_rect = QRectF(0, 0, 0, 0)
        self._cur_rect = QRectF(0, 0, 0, 0)
        self._cur_radius = 20.0
        self._opacity = 1.0

        self._timer = QTimer(self)
        self._timer.setInterval(12)
        self._timer.timeout.connect(self._step)
        self._start_time = 0.0
        self._duration = 0.12  # Snappy 120ms morph
        self._on_finished_callback: Optional[Callable] = None

    def start_morph(self, from_pos_or_rect, target_rect: Optional[QRect] = None, on_finished: Optional[Callable] = None):
        if isinstance(from_pos_or_rect, QPoint):
            from_pt = from_pos_or_rect
            start_w, start_h = 140.0, 140.0
            self._start_rect = QRectF(from_pt.x() - start_w / 2.0, from_pt.y() - start_h / 2.0, start_w, start_h)
        else:
            self._start_rect = QRectF(from_pos_or_rect)

        if target_rect is not None:
            self._target_rect = QRectF(target_rect)
        else:
            # Fallback target geometry around center of start rect
            cx = self._start_rect.center().x()
            cy = self._start_rect.center().y()
            self._target_rect = QRectF(cx - 280, cy - 26, 560, 52)

        self._cur_rect = QRectF(self._start_rect)
        self._cur_radius = min(self._start_rect.width(), self._start_rect.height()) / 2.0
        self._on_finished_callback = on_finished
        self._start_time = time.time()
        self._opacity = 1.0

        screen = QGuiApplication.screenAt(self._start_rect.center().toPoint()) or QApplication.primaryScreen()
        s_rect = screen.availableGeometry()
        self.setGeometry(s_rect)

        self.show()
        self.raise_()
        self._timer.start()

    def _step(self):
        elapsed = time.time() - self._start_time
        t = min(1.0, elapsed / self._duration)
        e = 1.0 - math.pow(1.0 - t, 3)

        x = self._start_rect.x() + (self._target_rect.x() - self._start_rect.x()) * e
        y = self._start_rect.y() + (self._target_rect.y() - self._start_rect.y()) * e
        w = self._start_rect.width() + (self._target_rect.width() - self._start_rect.width()) * e
        h = self._start_rect.height() + (self._target_rect.height() - self._start_rect.height()) * e

        r_start = min(self._start_rect.width(), self._start_rect.height()) / 2.0
        r_end = 20.0
        self._cur_radius = r_start + (r_end - r_start) * e
        self._cur_rect = QRectF(x, y, w, h)

        if t >= 0.85:
            self._opacity = max(0.0, (1.0 - t) / 0.15)

        self.update()

        if t >= 1.0:
            self._timer.stop()
            self.hide()
            if self._on_finished_callback:
                cb = self._on_finished_callback
                self._on_finished_callback = None
                cb()

    def _on_tick(self):
        self._step()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)

        painter.setBrush(QBrush(QColor(14, 14, 18, 240)))
        painter.setPen(QPen(QColor(255, 255, 255, 140), 1.0))
        painter.drawRoundedRect(self._cur_rect, self._cur_radius, self._cur_radius)
        painter.end()


# ---------------------------------------------------------------------------
# ODD Radial Arc Menu (Cursor Origin, Ultra-Compact, Black & White)
# ---------------------------------------------------------------------------

class RadialActionItem:
    def __init__(self, key: str, label: str, icon_type: str, color_hex: str = "#2563EB", glow_hex: str = "#3B82F6", sub: str = "", hotkey: str = "1"):
        self.key = key
        self.id = key
        self.label = label
        self.icon_type = icon_type
        self.color_hex = color_hex
        self.glow_hex = glow_hex
        self.sub = sub
        self.hotkey = hotkey


class OddRadialArcMenu(QWidget):
    """
    Orbital Modular Squircle Radial Menu:
    - Cursor is the interaction origin (Diamond Center & Connecting Filaments).
    - 5 Modular Squircle Cards inspired by physical / industrial design references:
        0: Quick Settings (Emerald Green #10B981)
        1: Google Lens (Warm Amber #F59E0B)
        2: Search (Electric Cobalt Blue #2563EB)
        3: Phone Mirror (Neon Violet #8B5CF6)
        4: ODD Hub / Settings (Dark Titanium #374151)
    - Redesigned Selection:
        - Tactile Spring elevation (+16% scale)
        - Dynamic Specular Shine Reflection sweeping across the active card surface
        - Glowing connecting bezier filament from cursor diamond to active card node
        - Contextual floating action badge
    - Zero-friction search: type any key or press [3] / Enter to immediately morph into Dedicated Search.
    - Zero-latency dismissal on click-outside, Esc, and rapid cursor shake.
    """
    closed = Signal()
    request_morph_search = Signal(QPoint, str)  # (cursor_pos, initial_char)
    request_morph_quick_settings = Signal(QPoint)
    request_morph_phone_mirror = Signal(QPoint)

    def __init__(self, overlay, settings: dict = None, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.overlay = overlay
        self.settings = settings or {}

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._canvas_size = 280
        self.setFixedSize(self._canvas_size, self._canvas_size)

        # 5 Primary Actions (Modular Squircle Tiles with distinctive identities)
        self.actions = [
            RadialActionItem("quick_settings", "Quick Settings", "sliders", color_hex="#10B981", glow_hex="#34D399", sub="Wi-Fi • Audio • Toggles", hotkey="1"),
            RadialActionItem("google_lens", "Google Lens", "lens", color_hex="#F59E0B", glow_hex="#FBBF24", sub="AI Vision & OCR", hotkey="2"),
            RadialActionItem("search", "Search", "search", color_hex="#2563EB", glow_hex="#60A5FA", sub="Apps, files, web", hotkey="3"),
            RadialActionItem("phone_mirror", "Phone Mirror", "phone", color_hex="#8B5CF6", glow_hex="#A78BFA", sub="Android Screen", hotkey="4"),
            RadialActionItem("settings", "ODD Settings", "odd_logo", color_hex="#374151", glow_hex="#9CA3AF", sub="ODD Hub & Config", hotkey="5"),
        ]

        # Compact Arc Dimensions (Tight around cursor)
        self._r_inner = 34.0
        self._r_outer = 92.0
        self._r_hover_pop = 98.0
        self._orbit_r = 92.0
        self._card_size = 52.0
        self._span_deg = 190.0
        self._slice_span = self._span_deg / len(self.actions)

        # Orientation & Hover State
        self._center_angle = 270.0  # Upward by default
        self._hover_index = -1
        self._anim_scale = 0.88
        self._anim_opacity = 0.0
        self._is_dismissing = False
        self._cursor_anchor = QPoint(0, 0)

        # Per-card smooth hover springs and dynamic shine reflection phase
        self._hover_springs = [SpringValue(initial_value=0.0, response=0.12, damping_ratio=0.75) for _ in range(len(self.actions))]
        self._shine_phase = 0.0

        # Dedicated 60 FPS animation timer for card springs & shine reflection sweep
        self._card_anim_timer = QTimer(self)
        self._card_anim_timer.setInterval(16)
        self._card_anim_timer.timeout.connect(self._step_card_animation)

        # Fast Shake Detection
        self._shake_history: List[Tuple[float, float, float]] = []
        self._last_shake_dismiss_time = 0.0

        # Cursor tracking timer to detect cursor shake anywhere on screen (even outside the panel)
        self._cursor_tracker_timer = QTimer(self)
        self._cursor_tracker_timer.setInterval(16)
        self._cursor_tracker_timer.timeout.connect(self._poll_cursor_shake)

        # Snappy Entry Animation Timer
        self._entry_anim = QTimer(self)
        self._entry_anim.setInterval(16)
        self._entry_anim.timeout.connect(self._step_entry_animation)
        self._entry_start_time = 0.0

        # Cursor tracking timer to detect cursor shake anywhere on screen (even outside the menu)
        self._cursor_tracker_timer = QTimer(self)
        self._cursor_tracker_timer.setInterval(16)
        self._cursor_tracker_timer.timeout.connect(self._poll_cursor_shake)

        # Very minimal bottom music overlay (Title & Play/Pause)
        self.music_bar = RadialBottomMusicBar(self.overlay, parent=self)

    # ------------------- Positioning & Orientation -------------------

    def open_at_cursor(self, cursor_pos: QPoint):
        self._is_dismissing = False
        self._shake_history.clear()
        self._cursor_anchor = cursor_pos
        self._hover_index = -1

        screen = QGuiApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        screen_rect = screen.availableGeometry()

        cx = float(cursor_pos.x())
        cy = float(cursor_pos.y())

        d_top = cy - screen_rect.top()
        d_bottom = screen_rect.bottom() - cy
        d_left = cx - screen_rect.left()
        d_right = screen_rect.right() - cx

        edge_threshold = 140.0

        # Edge-Aware Orientation (0° = East, 90° = South/Down, 180° = West/Left, 270° = North/Up)
        if d_top < edge_threshold and d_left < edge_threshold:
            self._center_angle = 45.0
        elif d_top < edge_threshold and d_right < edge_threshold:
            self._center_angle = 135.0
        elif d_bottom < edge_threshold and d_left < edge_threshold:
            self._center_angle = 315.0
        elif d_bottom < edge_threshold and d_right < edge_threshold:
            self._center_angle = 225.0
        elif d_top < edge_threshold:
            self._center_angle = 90.0
        elif d_bottom < edge_threshold:
            self._center_angle = 270.0
        elif d_left < edge_threshold:
            self._center_angle = 0.0
        elif d_right < edge_threshold:
            self._center_angle = 180.0
        else:
            self._center_angle = 270.0

        # Clamp canvas so it never renders outside the screen
        half_canvas = self._canvas_size / 2.0
        r_max = self._r_hover_pop + 22.0
        margin = 10.0

        if cx - r_max < screen_rect.left() + margin:
            cx = screen_rect.left() + margin + r_max
        if cx + r_max > screen_rect.right() - margin:
            cx = screen_rect.right() - margin - r_max
        if cy - r_max < screen_rect.top() + margin:
            cy = screen_rect.top() + margin + r_max
        if cy + r_max > screen_rect.bottom() - margin:
            cy = screen_rect.bottom() - margin - r_max

        win_x = int(cx - half_canvas)
        win_y = int(cy - half_canvas)
        self.move(win_x, win_y)

        # Entry Animation
        self._anim_scale = 0.88
        self._anim_opacity = 0.1
        self._entry_start_time = time.time()
        self._entry_anim.start()
        self._card_anim_timer.start()

        # Refresh and position minimal bottom music overlay ONLY if media is playing
        if self.settings.get("radial_bottom_music_overlay", True):
            media_s = getattr(self.overlay, "media_state", None)
            if not media_s and hasattr(self.overlay, "media_mgr") and self.overlay.media_mgr:
                cur = getattr(self.overlay.media_mgr, "_current_state", None)
                if cur and hasattr(cur, "to_dict"):
                    media_s = cur.to_dict()
            if media_s:
                self.music_bar.update_state(media_s)

            if getattr(self.music_bar, "_is_playing", False) and getattr(self.music_bar, "_title", ""):
                mb_w = self.music_bar.width()
                mb_h = self.music_bar.height()
                mb_x = int((self._canvas_size - mb_w) / 2.0)
                # Position at bottom if arc fans upwards, else at top
                if self._center_angle > 180 and self._center_angle < 360:
                    mb_y = int(self._canvas_size - mb_h - 12)
                else:
                    mb_y = int(12)
                self.music_bar.move(mb_x, mb_y)
                self.music_bar.show()
                self.music_bar.raise_()
            else:
                self.music_bar.hide()
        else:
            self.music_bar.hide()

        self._cursor_tracker_timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

        play_sound("droplet", self.settings)

    def update_media_state(self, state: dict):
        if hasattr(self, "music_bar") and self.music_bar:
            if not self.settings.get("radial_bottom_music_overlay", True):
                self.music_bar.hide()
                return
            self.music_bar.update_state(state)
            if getattr(self.music_bar, "_is_playing", False) and getattr(self.music_bar, "_title", "") and self.isVisible():
                mb_w = self.music_bar.width()
                mb_h = self.music_bar.height()
                mb_x = int((self._canvas_size - mb_w) / 2.0)
                if self._center_angle > 180 and self._center_angle < 360:
                    mb_y = int(self._canvas_size - mb_h - 12)
                else:
                    mb_y = int(12)
                self.music_bar.move(mb_x, mb_y)
                self.music_bar.show()
                self.music_bar.raise_()
            else:
                self.music_bar.hide()

    def _poll_cursor_shake(self):
        if not self.isVisible() or self._is_dismissing:
            self._cursor_tracker_timer.stop()
            return
        gpos = QCursor.pos()
        self._record_shake_point(gpos.x(), gpos.y())
        if self.settings.get("radial_shake_dismiss_enabled", True):
            if self._check_is_shake():
                self.dismiss(immediate=True)

    def hideEvent(self, event):
        self._cursor_tracker_timer.stop()
        super().hideEvent(event)

    def _step_card_animation(self):
        dt = 0.016
        self._shine_phase = (self._shine_phase + 0.038) % 1.0
        for i, s in enumerate(self._hover_springs):
            target = 1.0 if i == self._hover_index else 0.0
            s.set_target(target, preserve_velocity=True)
            s.update(dt)
        self.update()

    def _step_entry_animation(self):
        elapsed = time.time() - self._entry_start_time
        duration = 0.12
        t = min(1.0, elapsed / duration)
        e = 1.0 - math.pow(1.0 - t, 3)

        self._anim_scale = 0.88 + (0.12 * e)
        self._anim_opacity = min(1.0, e * 1.05)

        self.update()
        if t >= 1.0:
            self._entry_anim.stop()

    def dismiss(self, immediate: bool = False):
        if self._is_dismissing:
            return
        self._is_dismissing = True
        self._entry_anim.stop()
        self._card_anim_timer.stop()
        self._cursor_tracker_timer.stop()
        self.hide()
        self.closed.emit()

    def changeEvent(self, event: QEvent):
        # 0ms Instant Dismissal when clicking outside or focus is transferred
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_dismissing:
                self.dismiss(immediate=True)
        super().changeEvent(event)

    # ------------------- Hit-Testing & Hover -------------------

    def _get_hovered_slice(self, local_pos: QPoint) -> int:
        cx = self._canvas_size / 2.0
        cy = self._canvas_size / 2.0
        dx = local_pos.x() - cx
        dy = local_pos.y() - cy
        dist = math.hypot(dx, dy)

        # Center deadzone to prevent jitter when resting at cursor origin
        if dist < self._r_inner:
            return -1

        start_deg = self._center_angle - (self._span_deg / 2.0)

        # 1. Direct card proximity hit-test
        for i in range(len(self.actions)):
            mid_deg = start_deg + (i + 0.5) * self._slice_span
            mid_rad = math.radians(mid_deg)
            ccx = self._orbit_r * math.cos(mid_rad)
            ccy = self._orbit_r * math.sin(mid_rad)
            if math.hypot(dx - ccx, dy - ccy) <= 32.0:
                return i

        # 2. Infinite outer sector reach for marking gestures (Fitts's Law)
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad) % 360.0
        rel_deg = (angle_deg - (start_deg % 360.0)) % 360.0
        if rel_deg <= self._span_deg:
            idx = int(rel_deg / self._slice_span)
            if 0 <= idx < len(self.actions):
                return idx
        return -1

    def get_hovered_index(self) -> int:
        return self._hover_index

    def execute_hovered(self) -> bool:
        if 0 <= self._hover_index < len(self.actions):
            self._trigger_action(self.actions[self._hover_index])
            return True
        return False

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.pos()
        old_idx = self._hover_index
        new_idx = self._get_hovered_slice(pos)

        # Shake Detection (deliberate high-frequency shake)
        gpos = event.globalPosition().toPoint()
        self._record_shake_point(gpos.x(), gpos.y())
        if self.settings.get("radial_shake_dismiss_enabled", True):
            if self._check_is_shake():
                self.dismiss(immediate=True)
                return

        if new_idx != old_idx:
            self._hover_index = new_idx
            if new_idx != -1:
                play_hover(self.settings)
            self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if 0 <= self._hover_index < len(self.actions):
                self._trigger_action(self.actions[self._hover_index])
            else:
                self.dismiss(immediate=True)
        elif event.button() == Qt.MouseButton.RightButton:
            self.dismiss(immediate=True)

    def _trigger_action(self, item: RadialActionItem):
        """Dispatches or morphs into the target interface."""
        play_action(self.settings)
        anchor_pos = QPoint(self._cursor_anchor)

        if item.key == "search":
            # Morphs directly into the Dedicated Square Search UI
            self.dismiss(immediate=True)
            self.request_morph_search.emit(anchor_pos, "")
        elif item.key == "quick_settings":
            self.dismiss(immediate=True)
            self.request_morph_quick_settings.emit(anchor_pos)
        elif item.key == "phone_mirror":
            self.dismiss(immediate=True)
            self.request_morph_phone_mirror.emit(anchor_pos)
        elif item.key == "google_lens":
            self.dismiss(immediate=True)
            if hasattr(self.overlay, "start_google_lens_search"):
                self.overlay.start_google_lens_search()
        elif item.key == "settings":
            self.dismiss(immediate=True)
            if hasattr(self.overlay, "on_open_settings") and self.overlay.on_open_settings:
                self.overlay.on_open_settings()
            elif hasattr(self.overlay, "_open_settings_modal"):
                self.overlay._open_settings_modal()

    # ------------------- Key Events (Instant Navigation & Type-to-Search) -------------------

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.dismiss(immediate=True)
            return

        # Direct Number Key Shortcuts (1 to 5)
        if key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3, Qt.Key.Key_4, Qt.Key.Key_5):
            idx = int(key - Qt.Key.Key_1)
            if 0 <= idx < len(self.actions):
                self._trigger_action(self.actions[idx])
                return

        # Arrow navigation
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            new_idx = (self._hover_index - 1) % len(self.actions) if self._hover_index >= 0 else 0
            self._hover_index = new_idx
            play_hover(self.settings)
            self.update()
            return
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            new_idx = (self._hover_index + 1) % len(self.actions) if self._hover_index >= 0 else 0
            self._hover_index = new_idx
            play_hover(self.settings)
            self.update()
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if 0 <= self._hover_index < len(self.actions):
                self._trigger_action(self.actions[self._hover_index])
            else:
                self._trigger_action(self.actions[2])
            return

        # Typing immediately morphs the Arc into the Dedicated Search UI
        text = event.text()
        if text and text.isprintable():
            self.dismiss(immediate=True)
            self.request_morph_search.emit(self._cursor_anchor, text)
            return

        super().keyPressEvent(event)

    # ------------------- Fast Shake Detection (0ms Delay) -------------------

    def _record_shake_point(self, x: float, y: float):
        now = time.time()
        self._shake_history.append((now, x, y))
        cutoff = now - 0.22
        while self._shake_history and self._shake_history[0][0] < cutoff:
            self._shake_history.pop(0)

    def _check_is_shake(self) -> bool:
        if len(self._shake_history) < 4:
            return False

        reversals_x = 0
        reversals_y = 0
        last_sign_x = 0
        last_sign_y = 0
        total_dist = 0.0

        for i in range(1, len(self._shake_history)):
            t0, x0, y0 = self._shake_history[i - 1]
            t1, x1, y1 = self._shake_history[i]
            dx = x1 - x0
            dy = y1 - y0
            total_dist += math.hypot(dx, dy)

            if abs(dx) > 14.0:
                cur_sign = 1 if dx > 0 else -1
                if last_sign_x != 0 and cur_sign != last_sign_x:
                    reversals_x += 1
                last_sign_x = cur_sign

            if abs(dy) > 14.0:
                cur_sign = 1 if dy > 0 else -1
                if last_sign_y != 0 and cur_sign != last_sign_y:
                    reversals_y += 1
                last_sign_y = cur_sign

        now = time.time()
        if max(reversals_x, reversals_y) >= 2 and total_dist > 45.0 and (now - self._last_shake_dismiss_time > 0.8):
            self._last_shake_dismiss_time = now
            return True
        return False

    # ------------------- Rendering (Orbital Modular Squircle Tiles) -------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            canvas_center = self._canvas_size / 2.0
            painter.translate(canvas_center, canvas_center)
            painter.scale(self._anim_scale, self._anim_scale)
            painter.setOpacity(self._anim_opacity)

            start_deg = self._center_angle - (self._span_deg / 2.0)

            # 1. Magic Connecting Filament from Center to Hovered Card (Reference Image 4)
            if 0 <= self._hover_index < len(self.actions):
                item = self.actions[self._hover_index]
                mid_deg = start_deg + (self._hover_index + 0.5) * self._slice_span
                mid_rad = math.radians(mid_deg)
                card_cx = self._orbit_r * math.cos(mid_rad)
                card_cy = self._orbit_r * math.sin(mid_rad)

                fil_path = QPainterPath()
                fil_path.moveTo(0, 0)
                ctrl_x = card_cx * 0.45 - math.sin(mid_rad) * 10.0
                ctrl_y = card_cy * 0.45 + math.cos(mid_rad) * 10.0
                fil_path.quadTo(ctrl_x, ctrl_y, card_cx * 0.70, card_cy * 0.70)

                g_col = QColor(item.glow_hex)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(g_col.red(), g_col.green(), g_col.blue(), 120), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawPath(fil_path)
                painter.setPen(QPen(QColor(255, 255, 255, 220), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawPath(fil_path)

                # Traveling Photon Pulse along the filament
                t_spark = (self._shine_phase * 2.2) % 1.0
                sp_pt = fil_path.pointAtPercent(t_spark)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
                painter.drawEllipse(sp_pt, 2.4, 2.4)

            # 2. Center Origin Diamond Emblem (Reference Image Accent)
            d_sz = 5.2
            d_path = QPainterPath()
            d_path.moveTo(0, -d_sz)
            d_path.lineTo(d_sz, 0)
            d_path.lineTo(0, d_sz)
            d_path.lineTo(-d_sz, 0)
            d_path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(246, 245, 241, 200)))
            painter.drawPath(d_path)

            # 3. Render 5 Modular Squircle Cards (Reference Images 1 & 2)
            for i, item in enumerate(self.actions):
                mid_deg = start_deg + (i + 0.5) * self._slice_span
                mid_rad = math.radians(mid_deg)
                ccx = self._orbit_r * math.cos(mid_rad)
                ccy = self._orbit_r * math.sin(mid_rad)
                is_hover = (i == self._hover_index)
                h_val = float(self._hover_springs[i].value) if i < len(self._hover_springs) else (1.0 if is_hover else 0.0)

                self._draw_squircle_card(painter, i, item, ccx, ccy, is_hover, h_val)

            # 4. Contextual Floating Status Badge (Reference Image 5)
            if 0 <= self._hover_index < len(self.actions):
                item = self.actions[self._hover_index]
                mid_deg = start_deg + (self._hover_index + 0.5) * self._slice_span
                lbl_text = f"{item.label}  •  [{item.hotkey}]"
                self._draw_contextual_pill(painter, lbl_text, mid_deg)
        finally:
            painter.end()

    def _draw_squircle_card(self, painter: QPainter, index: int, item: RadialActionItem, ccx: float, ccy: float, is_hover: bool, hover_val: float):
        painter.save()
        painter.translate(ccx, ccy)

        scale = 1.0 + (0.16 * hover_val)
        painter.scale(scale, scale)

        sz = self._card_size
        r_box = QRectF(-sz / 2.0, -sz / 2.0, sz, sz)
        card_path = create_squircle_path(r_box, 14.5)

        base_color = QColor(item.color_hex)
        glow_color = QColor(item.glow_hex)

        # 1. Hover Ambient Glow
        if hover_val > 0.01:
            rad_glow = QRadialGradient(0, 0, sz * 0.95)
            rad_glow.setColorAt(0.0, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), int(135 * hover_val)))
            rad_glow.setColorAt(0.7, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), int(40 * hover_val)))
            rad_glow.setColorAt(1.0, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(rad_glow))
            painter.drawEllipse(QPointF(0, 0), sz * 0.95, sz * 0.95)

        # 2. Card Background & Specular Shine
        if is_hover:
            # Rich saturated gradient matching reference image
            grad = QLinearGradient(-sz / 2.0, -sz / 2.0, sz / 2.0, sz / 2.0)
            grad.setColorAt(0.0, base_color.lighter(135))
            grad.setColorAt(1.0, base_color.darker(110))
            painter.fillPath(card_path, QBrush(grad))

            # Specular Shine Reflection Sweep
            shine_peak = (self._shine_phase + index * 0.22) % 1.0
            shine_grad = QLinearGradient(-sz / 2.0, -sz / 2.0, sz / 2.0, sz / 2.0)
            shine_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            p_lo = max(0.0, shine_peak - 0.20)
            p_hi = min(1.0, shine_peak + 0.20)
            shine_grad.setColorAt(p_lo, QColor(255, 255, 255, 30))
            shine_grad.setColorAt(shine_peak, QColor(255, 255, 255, 185))
            shine_grad.setColorAt(p_hi, QColor(255, 255, 255, 30))
            shine_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(card_path, QBrush(shine_grad))

            # Crisp border
            painter.setPen(QPen(QColor(255, 255, 255, 235), 1.4))
            painter.strokePath(card_path, painter.pen())
        else:
            # Translucent frosted AMOLED plate with subtle tint
            bg_col = QColor(18, 18, 22, 230)
            painter.fillPath(card_path, QBrush(bg_col))
            border_col = QColor(255, 255, 255, 36)
            painter.setPen(QPen(border_col, 0.9))
            painter.strokePath(card_path, painter.pen())

        # 3. Vector Icon (Centered upper)
        icon_cy = -5.0
        self._draw_action_icon(painter, item.icon_type, 0.0, icon_cy, is_hover)

        # 4. Clean Bottom Label (Segoe UI Variable Bold)
        painter.setFont(QFont("Segoe UI Variable Text", 7.5, QFont.Weight.Bold))
        text_rect = QRectF(-sz / 2.0 + 2.0, 9.5, sz - 4.0, 14.0)
        text_col = QColor(255, 255, 255, 255) if is_hover else QColor(210, 210, 218, 195)
        painter.setPen(text_col)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, item.label.split()[0] if len(item.label) > 8 else item.label)

        painter.restore()

    def _draw_contextual_pill(self, painter: QPainter, label_text: str, mid_deg: float):
        painter.save()
        rad = math.radians(mid_deg)
        r_pill = self._r_hover_pop + 24.0
        px = r_pill * math.cos(rad)
        py = r_pill * math.sin(rad)

        font = QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label_text)
        th = fm.height()

        pw = tw + 18.0
        ph = th + 6.0

        pill_rect = QRectF(px - (pw / 2.0), py - (ph / 2.0), pw, ph)

        # Off-white pill with dark charcoal text (Reference aesthetic)
        painter.setBrush(QBrush(QColor(246, 245, 241, 250)))
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1.0))
        painter.drawRoundedRect(pill_rect, ph / 2.0, ph / 2.0)

        painter.setPen(QPen(QColor(18, 18, 22, 245)))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, label_text)
        painter.restore()

    def _draw_action_icon(self, painter: QPainter, icon_type: str, cx: float, cy: float, is_hover: bool):
        painter.save()
        # High contrast: Dark charcoal on ceramic hover plate, pure white when unhovered
        color = QColor(18, 18, 22, 250) if is_hover else QColor(255, 255, 255, 225)
        pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if icon_type == "sliders":
            painter.drawLine(int(cx - 7), int(cy - 4), int(cx + 7), int(cy - 4))
            painter.drawLine(int(cx - 7), int(cy + 4), int(cx + 7), int(cy + 4))
            painter.drawEllipse(QPointF(cx - 2, cy - 4), 2.2, 2.2)
            painter.drawEllipse(QPointF(cx + 2, cy + 4), 2.2, 2.2)
        elif icon_type == "lens":
            r = 6.0
            painter.drawRoundedRect(QRectF(cx - r, cy - r, r * 2.0, r * 2.0), 3.0, 3.0)
            painter.drawEllipse(QPointF(cx, cy), 2.8, 2.8)
            painter.drawPoint(QPointF(cx + 3.8, cy - 3.8))
        elif icon_type == "search":
            r = 5.2
            painter.drawEllipse(QPointF(cx - 1.5, cy - 1.5), r, r)
            painter.drawLine(int(cx + 2.5), int(cy + 2.5), int(cx + 7.5), int(cy + 7.5))
        elif icon_type == "phone":
            w, h = 9.0, 15.0
            painter.drawRoundedRect(QRectF(cx - (w / 2.0), cy - (h / 2.0), w, h), 2.5, 2.5)
            painter.drawPoint(QPointF(cx, cy + (h / 2.0) - 2.5))
        elif icon_type == "odd_logo":
            logo_pix = None
            for p in ["odd_logo.png", "odd_logo_black.png"]:
                if os.path.exists(p):
                    logo_pix = QPixmap(p)
                    break
            if logo_pix and not logo_pix.isNull():
                target_sz = 17
                scaled = logo_pix.scaled(target_sz, target_sz, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap(int(cx - scaled.width() / 2.0), int(cy - scaled.height() / 2.0), scaled)
            else:
                r = 7.5
                ring_color = QColor(18, 18, 22, 250) if is_hover else QColor(255, 255, 255, 255)
                painter.setPen(QPen(ring_color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                r_rect = QRectF(cx - r, cy - r, r * 2.0, r * 2.0)
                painter.drawArc(r_rect, int(42 * 16), int(310 * 16))

                dot_angle = math.radians(24)
                dot_x = cx + r * math.cos(dot_angle)
                dot_y = cy - r * math.sin(dot_angle)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(229, 57, 53, 255)))
                painter.drawEllipse(QPointF(dot_x, dot_y), 3.0, 3.0)

        painter.restore()


# ---------------------------------------------------------------------------
# Dedicated Dynamic-Island-Style Search Interface for the Radial Menu
# ---------------------------------------------------------------------------

class DedicatedRadialSearchPanel(QWidget):
    """
    Dedicated Square Search Interface for the ODD Radial Menu.
    Positioned contextually near the summon cursor with edge-aware screen clamping.

    Aesthetic:
    - Square Shape UI with Curved Corners (380x380, border-radius: 24px)
    - Curved search input row (height 46px, border-radius: 14px)
    - When empty: 4 square category shortcut tiles (Apps, Files, Web, Settings)
    - When searching: curved result items with category pill badges and plate icons
    - Zero-latency keyboard navigation (Arrow Up/Down, Enter, Esc)
    """
    closed = Signal()
    search_results_ready = Signal(int, list)

    def __init__(self, overlay=None, settings: dict = None, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.overlay = overlay
        self.settings = settings or {}

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)

        self._panel_width = 380
        self._empty_panel_height = 244
        self._panel_height = self._empty_panel_height
        self._header_height = 44
        self._current_results: List[SearchItem] = []
        self._cursor_anchor = QPoint(0, 0)
        self._is_dismissing = False

        # Fast Shake Detection
        self._shake_history: List[Tuple[float, float, float]] = []
        self._last_shake_dismiss_time = 0.0

        # Cursor tracking timer to detect cursor shake anywhere on screen (even outside the panel)
        self._cursor_tracker_timer = QTimer(self)
        self._cursor_tracker_timer.setInterval(16)
        self._cursor_tracker_timer.timeout.connect(self._poll_cursor_shake)

        # Non-blocking 0ms debounce and background worker
        self._search_generation = 0
        self._search_cancel_event = threading.Event()
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(25)
        self._search_debounce_timer.timeout.connect(self._on_search_debounce_timeout)
        self.search_results_ready.connect(self._on_search_results_ready)

        self._build_ui()

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(0)

        # Square Frosted / AMOLED Glass Card Frame with Curved Corners
        self.card_frame = QFrame(self)
        self.card_frame.setObjectName("SearchCardFrame")
        self.card_frame.setStyleSheet("""
            QFrame#SearchCardFrame {
                background-color: rgba(18, 18, 22, 0.98);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 24px;
            }
        """)

        self.card_layout = QVBoxLayout(self.card_frame)
        self.card_layout.setContentsMargins(12, 12, 12, 12)
        self.card_layout.setSpacing(8)

        # 1. Header Search Row (Curved Square Search Box)
        self.header_widget = QWidget(self.card_frame)
        self.header_widget.setFixedHeight(44)
        self.header_widget.setObjectName("SearchHeaderRow")
        self.header_widget.setStyleSheet("""
            QWidget#SearchHeaderRow {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.13);
                border-radius: 14px;
            }
        """)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(10, 0, 8, 0)
        header_layout.setSpacing(8)

        # Magnifying Glass Icon
        self.icon_label = QLabel(self.header_widget)
        self.icon_label.setFixedSize(20, 20)
        self._render_search_icon()
        header_layout.addWidget(self.icon_label)

        # Search Input
        self.search_input = QLineEdit(self.header_widget)
        self.search_input.setPlaceholderText("Search apps, files, web...")
        self.search_input.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.Medium))
        self.search_input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #FFFFFF;
                padding: 0px;
                selection-background-color: rgba(255, 255, 255, 0.25);
            }
            QLineEdit::placeholder {
                color: #8E8E96;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.returnPressed.connect(self._on_search_return_pressed)
        self.search_input.installEventFilter(self)
        header_layout.addWidget(self.search_input, 1)

        # Esc badge
        self.esc_badge = QLabel("Esc", self.header_widget)
        self.esc_badge.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
        self.esc_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.esc_badge.setFixedSize(32, 20)
        self.esc_badge.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 6px;
                color: rgba(255, 255, 255, 0.65);
            }
        """)
        header_layout.addWidget(self.esc_badge)

        self.card_layout.addWidget(self.header_widget)

        # Subtle separator line
        self.separator = QFrame(self.card_frame)
        self.separator.setFrameShape(QFrame.Shape.HLine)
        self.separator.setFixedHeight(1)
        self.separator.setStyleSheet("background-color: rgba(255, 255, 255, 0.08); border: none;")
        self.separator.hide()
        self.card_layout.addWidget(self.separator)

        # 2. Empty State: 2x2 Square Shortcut Tiles with Curved Corners (snug fit)
        self.empty_widget = QWidget(self.card_frame)
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setContentsMargins(0, 2, 0, 0)
        empty_layout.setSpacing(6)

        grid_tiles = QGridLayout()
        grid_tiles.setSpacing(6)

        shortcuts = [
            ("Apps", "Launch programs", "apps: "),
            ("Folders", "Browse directories", "folders: "),
            ("Files", "Search documents", "files: "),
            ("Settings", "Configure ODD", "settings: "),
        ]

        for i, (title, sub, cat) in enumerate(shortcuts):
            btn = QPushButton(self.empty_widget)
            btn.setFixedHeight(58)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 14px;
                    text-align: left;
                    padding: 6px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.10);
                    border: 1px solid rgba(255, 255, 255, 0.18);
                }
            """)
            btn_layout = QVBoxLayout(btn)
            btn_layout.setContentsMargins(8, 6, 8, 6)
            btn_layout.setSpacing(2)

            lbl_t = QLabel(title, btn)
            lbl_t.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 11px; background: transparent;")
            lbl_s = QLabel(sub, btn)
            lbl_s.setStyleSheet("color: rgba(255, 255, 255, 0.45); font-size: 8.5px; background: transparent;")
            lbl_s.setWordWrap(True)

            btn_layout.addWidget(lbl_t)
            btn_layout.addWidget(lbl_s)
            btn_layout.addStretch(1)

            def _make_handler(p=cat):
                def _apply():
                    self.search_input.setText(p)
                    self.search_input.setFocus()
                    self.search_input.setCursorPosition(len(p))
                return _apply
            btn.clicked.connect(_make_handler(cat))

            r = i // 2
            c = i % 2
            grid_tiles.addWidget(btn, r, c)

        empty_layout.addLayout(grid_tiles)

        # Footer hint (snug bottom, no dead empty space)
        hint_lbl = QLabel("<↑/↓> Navigate  <Enter> Open  <Esc> Close", self.empty_widget)
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.35); font-size: 8px; font-weight: 600; padding: 2px;")
        empty_layout.addWidget(hint_lbl)

        self.card_layout.addWidget(self.empty_widget)

        # 3. Results List Widget (Curved Corner Items)
        self.results_list = QListWidget(self.card_frame)
        self.results_list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 0px;
                margin-bottom: 3px;
                border-radius: 12px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 5px;
                margin: 4px 1px 4px 0px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.20);
                min-height: 24px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.35);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.results_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.results_list.setAutoScroll(True)
        self.results_list.itemClicked.connect(self._on_item_clicked)
        self.results_list.currentRowChanged.connect(self._on_row_changed)
        self.results_list.hide()
        self.card_layout.addWidget(self.results_list)

        self.main_layout.addWidget(self.card_frame)

    def _render_search_icon(self):
        pix = QPixmap(20, 20)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(8.5, 8.5), 5.0, 5.0)
        p.drawLine(12, 12, 16.5, 16.5)
        p.end()
        self.icon_label.setPixmap(pix)

    def get_target_rect(self, cursor_pos: QPoint, target_h: Optional[int] = None) -> QRect:
        screen = QGuiApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        s_rect = screen.availableGeometry()

        panel_w = self._panel_width
        panel_h = target_h if target_h is not None else (self._empty_panel_height if self.results_list.isHidden() else self.height())

        tx = int(cursor_pos.x() - (panel_w / 2.0))
        ty = int(cursor_pos.y() - (panel_h / 2.0))

        tx = max(s_rect.left() + 16, min(s_rect.right() - panel_w - 16, tx))
        ty = max(s_rect.top() + 16, min(s_rect.bottom() - panel_h - 16, ty))

        return QRect(tx, ty, panel_w, panel_h)

    def open_at_cursor(self, cursor_pos: QPoint, initial_text: str = ""):
        self._is_dismissing = False
        self._shake_history.clear()
        self._cursor_anchor = cursor_pos

        target_geom = self.get_target_rect(cursor_pos, target_h=self._empty_panel_height if not initial_text else None)
        self.setGeometry(target_geom)
        self._adjust_panel_height(0 if not initial_text else len(self._current_results))

        # Subtle opening fade-in animation
        self.setWindowOpacity(0.0)
        self._cursor_tracker_timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

        self._anim_open = QPropertyAnimation(self, b"windowOpacity")
        self._anim_open.setDuration(140)
        self._anim_open.setStartValue(0.0)
        self._anim_open.setEndValue(1.0)
        self._anim_open.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_open.start()

        if initial_text:
            self.search_input.setText(initial_text)
            self.search_input.setCursorPosition(len(initial_text))
            self._do_search(initial_text)
        else:
            self.search_input.clear()
            self._do_search("")

        self.search_input.setFocus()
        play_sound("droplet", self.settings)

    def dismiss(self, immediate: bool = False):
        if self._is_dismissing:
            return
        self._is_dismissing = True
        self._cursor_tracker_timer.stop()
        self.hide()
        self.search_input.clear()
        self.results_list.clear()
        self._current_results.clear()
        self.closed.emit()

    def hideEvent(self, event):
        self._cursor_tracker_timer.stop()
        super().hideEvent(event)

    def _poll_cursor_shake(self):
        if not self.isVisible() or self._is_dismissing:
            self._cursor_tracker_timer.stop()
            return
        gpos = QCursor.pos()
        self._record_shake_point(gpos.x(), gpos.y())
        if self.settings.get("radial_shake_dismiss_enabled", True):
            if self._check_is_shake():
                self.dismiss(immediate=True)

    def changeEvent(self, event: QEvent):
        # 0ms Instant Dismissal on focus loss
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_dismissing:
                self.dismiss(immediate=True)
        super().changeEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        gpos = event.globalPosition().toPoint()
        self._record_shake_point(gpos.x(), gpos.y())
        if self.settings.get("radial_shake_dismiss_enabled", True):
            if self._check_is_shake():
                self.dismiss(immediate=True)
                return
        super().mouseMoveEvent(event)

    def _record_shake_point(self, x: float, y: float):
        now = time.time()
        self._shake_history.append((now, x, y))
        cutoff = now - 0.22
        while self._shake_history and self._shake_history[0][0] < cutoff:
            self._shake_history.pop(0)

    def _check_is_shake(self) -> bool:
        if len(self._shake_history) < 4:
            return False
        reversals_x, reversals_y = 0, 0
        last_sign_x, last_sign_y = 0, 0
        total_dist = 0.0

        for i in range(1, len(self._shake_history)):
            t0, x0, y0 = self._shake_history[i - 1]
            t1, x1, y1 = self._shake_history[i]
            dx, dy = x1 - x0, y1 - y0
            total_dist += math.hypot(dx, dy)

            if abs(dx) > 14.0:
                cur_sign = 1 if dx > 0 else -1
                if last_sign_x != 0 and cur_sign != last_sign_x:
                    reversals_x += 1
                last_sign_x = cur_sign
            if abs(dy) > 14.0:
                cur_sign = 1 if dy > 0 else -1
                if last_sign_y != 0 and cur_sign != last_sign_y:
                    reversals_y += 1
                last_sign_y = cur_sign

        now = time.time()
        if max(reversals_x, reversals_y) >= 2 and total_dist > 45.0 and (now - self._last_shake_dismiss_time > 0.8):
            self._last_shake_dismiss_time = now
            return True
        return False

    def eventFilter(self, obj, event):
        if obj == self.search_input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                cur = self.results_list.currentRow()
                cnt = self.results_list.count()
                if cnt > 0:
                    next_row = (cur + 1) % cnt
                    self.results_list.setCurrentRow(next_row)
                return True
            elif key == Qt.Key.Key_Up:
                cur = self.results_list.currentRow()
                cnt = self.results_list.count()
                if cnt > 0:
                    prev_row = (cur - 1 + cnt) % cnt
                    self.results_list.setCurrentRow(prev_row)
                return True
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_search_return_pressed()
                return True
            elif key == Qt.Key.Key_Escape:
                self.dismiss(immediate=True)
                return True
        return super().eventFilter(obj, event)

    def _on_search_return_pressed(self):
        cur = self.results_list.currentRow()
        if cur < 0 and self.results_list.count() > 0:
            cur = 0
        self._execute_row(cur)

    def _on_search_text_changed(self, text: str):
        raw_text = text.strip()
        if not raw_text:
            self._search_debounce_timer.stop()
            self._search_cancel_event.set()
            self._search_generation += 1
            self._current_results = []
            self._populate_results([])
            return

        low_t = raw_text.lower()
        # Fast category prefix detection: display category defaults immediately
        if low_t in ("apps:", "app:", "folders:", "folder:", "dir:", "files:", "file:", "doc:", "settings:", "setting:", "web:", "url:"):
            self._search_debounce_timer.stop()
            self._search_cancel_event.set()
            self._search_generation += 1
            cat = "app" if "app" in low_t else ("folder" if "folder" in low_t or "dir" in low_t else ("file" if "file" in low_t or "doc" in low_t else ("settings" if "setting" in low_t else "web")))
            self._current_results = self._get_category_default_items(cat)
            self._populate_results(self._current_results)
            return

        # 0ms typing response: keep GUI typing instant, debounce background worker
        self._search_debounce_timer.start(25)

    def _on_search_debounce_timeout(self):
        raw_q = self.search_input.text().strip()
        if not raw_q:
            return

        self._search_cancel_event.set()
        self._search_cancel_event = threading.Event()
        self._search_generation += 1
        gen = self._search_generation
        cancel_evt = self._search_cancel_event

        thread = threading.Thread(
            target=self._run_background_search,
            args=(raw_q, gen, cancel_evt),
            daemon=True,
            name=f"DedicatedSearchThread-{gen}"
        )
        thread.start()

    def _run_background_search(self, raw_query: str, gen: int, cancel_evt: threading.Event):
        if cancel_evt.is_set():
            return
        results = self._execute_search_query(raw_query, cancel_evt)
        if not cancel_evt.is_set():
            self.search_results_ready.emit(gen, results)

    @Slot(int, list)
    def _on_search_results_ready(self, gen: int, results: list):
        if gen != self._search_generation:
            return  # Discard stale search results
        self._current_results = results or []
        self._populate_results(self._current_results)

    def _execute_search_query(self, raw_query: str, cancel_evt: Optional[threading.Event] = None) -> List[SearchItem]:
        if cancel_evt and cancel_evt.is_set():
            return []

        search_engine = getattr(self.overlay, "search_engine", None)
        if not search_engine:
            return []

        raw_q = raw_query.strip()
        low_q = raw_q.lower()
        target_cat = None
        filter_term = raw_q

        # Detect category prefix filters
        if low_q.startswith("apps:") or low_q.startswith("app:"):
            target_cat = "app"
            filter_term = raw_q.split(":", 1)[1].strip()
        elif low_q.startswith("folders:") or low_q.startswith("folder:") or low_q.startswith("dir:"):
            target_cat = "folder"
            filter_term = raw_q.split(":", 1)[1].strip()
        elif low_q.startswith("files:") or low_q.startswith("file:") or low_q.startswith("doc:"):
            target_cat = "file"
            filter_term = raw_q.split(":", 1)[1].strip()
        elif low_q.startswith("settings:") or low_q.startswith("setting:"):
            target_cat = "settings"
            filter_term = raw_q.split(":", 1)[1].strip()
        elif low_q.startswith("web:") or low_q.startswith("url:"):
            target_cat = "web"
            filter_term = raw_q.split(":", 1)[1].strip()

        # If user opened category with no specific sub-term
        if target_cat and not filter_term:
            return self._get_category_default_items(target_cat)

        query_to_search = filter_term if target_cat else raw_q
        if not query_to_search or (cancel_evt and cancel_evt.is_set()):
            return []

        try:
            results = search_engine.search(query_to_search, max_results=12, include_windows_search=True, cancel_event=cancel_evt)
        except TypeError:
            try:
                results = search_engine.search(query_to_search, max_results=12)
            except Exception:
                results = []
        except Exception:
            results = []

        if cancel_evt and cancel_evt.is_set():
            return []

        # Strict category isolation: if prefix was specified, filter out everything else!
        if target_cat and results:
            filtered = []
            for item in results:
                cat = str(getattr(item, 'category', '')).lower()
                kind = str(getattr(item, 'kind', '')).lower()
                if target_cat == "app" and (cat in ("app", "application", "program", "executable") or kind == "app"):
                    filtered.append(item)
                elif target_cat == "folder" and (cat in ("folder", "directory") or kind == "folder"):
                    filtered.append(item)
                elif target_cat == "file" and (cat in ("file", "document", "media") or kind == "file"):
                    filtered.append(item)
                elif target_cat == "settings" and (cat in ("settings", "system", "control_panel") or kind == "settings"):
                    filtered.append(item)
                elif target_cat == "web" and (cat in ("web", "url", "bookmark") or kind == "web"):
                    filtered.append(item)
            results = filtered

        return results or []

    def _do_search(self, raw_query: str):
        self._search_debounce_timer.stop()
        self._search_cancel_event.set()
        self._search_generation += 1
        results = self._execute_search_query(raw_query)
        self._current_results = results or []
        self._populate_results(self._current_results)

    def _get_category_default_items(self, category: str) -> List[SearchItem]:
        items = []
        search_engine = getattr(self.overlay, "search_engine", None)
        if category == "app":
            if search_engine and hasattr(search_engine, "apps") and search_engine.apps:
                for a in search_engine.apps[:8]:
                    name, path_str = a[0], a[1]
                    icon = a[2] if len(a) > 2 else None
                    def _make_app_launch(p=path_str):
                        return lambda: os.startfile(p) if os.path.exists(p) else None
                    items.append(SearchItem(
                        id=f"app_{name}",
                        title=name,
                        subtitle=path_str,
                        category="app",
                        target=path_str,
                        action=_make_app_launch(path_str),
                        icon=icon
                    ))
            elif search_engine:
                try:
                    res = search_engine.search("", max_results=8)
                    for r in res:
                        if getattr(r, 'category', '') in ('app', 'application') or getattr(r, 'kind', '') == 'app':
                            items.append(r)
                except Exception:
                    pass
        elif category == "folder":
            common_dirs = [
                ("Desktop", os.path.expanduser("~/Desktop")),
                ("Downloads", os.path.expanduser("~/Downloads")),
                ("Documents", os.path.expanduser("~/Documents")),
                ("Pictures", os.path.expanduser("~/Pictures")),
                ("Videos", os.path.expanduser("~/Videos")),
            ]
            for name, path_str in common_dirs:
                if os.path.exists(path_str):
                    def _make_folder_open(p=path_str):
                        return lambda: os.startfile(p)
                    items.append(SearchItem(
                        id=f"folder_{name}",
                        title=name,
                        subtitle=path_str,
                        category="folder",
                        target=path_str,
                        action=_make_folder_open(path_str)
                    ))
        elif category == "file":
            common_dirs = [
                ("Downloads", os.path.expanduser("~/Downloads")),
                ("Documents", os.path.expanduser("~/Documents")),
            ]
            for name, path_str in common_dirs:
                if os.path.exists(path_str):
                    try:
                        for entry in os.listdir(path_str)[:4]:
                            f_path = os.path.join(path_str, entry)
                            if os.path.isfile(f_path):
                                def _make_f_open(p=f_path):
                                    return lambda: os.startfile(p)
                                items.append(SearchItem(
                                    id=f"file_{entry}",
                                    title=entry,
                                    subtitle=f_path,
                                    category="file",
                                    target=f_path,
                                    action=_make_f_open(f_path)
                                ))
                    except Exception:
                        pass
        elif category == "settings":
            common_settings = [
                ("Display Settings", "ms-settings:display", "Change resolution, scaling, brightness"),
                ("Sound Settings", "ms-settings:sound", "Output devices, master volume"),
                ("Bluetooth & Devices", "ms-settings:bluetooth", "Manage wireless peripherals"),
                ("Network & Wi-Fi", "ms-settings:network", "Manage Wi-Fi and ethernet"),
                ("Windows Update", "ms-settings:windowsupdate", "Check for system updates"),
                ("ODD Settings", "odd:settings", "Configure ODD desktop HUD & hotkeys"),
            ]
            for title, target_uri, sub in common_settings:
                def _make_set_open(uri=target_uri):
                    def _launch():
                        if uri == "odd:settings" and hasattr(self.overlay, "on_open_settings"):
                            self.overlay.on_open_settings()
                        else:
                            try:
                                subprocess.Popen(f"start {uri}", shell=True)
                            except Exception:
                                pass
                    return _launch
                items.append(SearchItem(
                    id=f"set_{title}",
                    title=title,
                    subtitle=sub,
                    category="settings",
                    target=target_uri,
                    action=_make_set_open(target_uri)
                ))
        return items

    def _populate_results(self, results: List[SearchItem]):
        self.results_list.clear()

        if not results:
            self.separator.hide()
            self.results_list.hide()
            self.empty_widget.show()
            self._adjust_panel_height(0)
            return

        self.empty_widget.hide()
        self.separator.show()
        self.results_list.show()

        theme = "dark"
        if hasattr(self.overlay, "get_current_theme"):
            theme = self.overlay.get_current_theme()

        for idx, item in enumerate(results):
            list_item = QListWidgetItem(self.results_list)
            is_sel = (idx == 0)

            if ResultItemWidget is not None:
                widget = ResultItemWidget(item, theme=theme)
                widget.set_selected(is_sel, immediate=True)
                list_item.setSizeHint(widget.sizeHint())
            else:
                widget = QLabel(f"{item.title} ({item.category})", self.results_list)
                widget.setStyleSheet("color: white; padding: 10px;")
                list_item.setSizeHint(QSize(0, 56))

            self.results_list.addItem(list_item)
            self.results_list.setItemWidget(list_item, widget)

        self.results_list.setCurrentRow(0)
        self._adjust_panel_height(len(results))

    def _adjust_panel_height(self, count: int):
        if count == 0:
            target_h = self._empty_panel_height
        else:
            target_h = min(440, max(160, 96 + count * 48))
        cur_geom = self.geometry()
        self.setGeometry(cur_geom.x(), cur_geom.y(), self._panel_width, target_h)
        self.card_frame.setFixedHeight(target_h - 20)
        if count > 0:
            self.results_list.setFixedHeight(target_h - 96)

    def _on_row_changed(self, current_row: int):
        count = self.results_list.count()
        for i in range(count):
            it = self.results_list.item(i)
            w = self.results_list.itemWidget(it)
            if hasattr(w, "set_selected"):
                w.set_selected(i == current_row)

    def _on_item_clicked(self, list_item: QListWidgetItem):
        row = self.results_list.row(list_item)
        self._execute_row(row)

    def _execute_row(self, row: int):
        q = self.search_input.text().strip()
        if 0 <= row < len(self._current_results):
            res = self._current_results[row]
            play_action(self.settings)
            self.dismiss(immediate=True)
            if res and hasattr(res, "action") and callable(res.action):
                try:
                    res.action()
                except Exception as e:
                    print(f"[RADIAL SEARCH] Error executing action: {e}")
        elif q:
            # Fallback web execution if no specific item selected
            play_action(self.settings)
            self.dismiss(immediate=True)
            try:
                import urllib.parse
                import webbrowser
                if q.startswith("http://") or q.startswith("https://"):
                    webbrowser.open(q)
                elif "." in q and " " not in q:
                    webbrowser.open(f"https://{q}")
                else:
                    webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(q)}")
            except Exception as e:
                print(f"[RADIAL SEARCH] Web fallback error: {e}")

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.dismiss(immediate=True)
            return

        if key == Qt.Key.Key_Down:
            cur = self.results_list.currentRow()
            cnt = self.results_list.count()
            if cnt > 0:
                next_row = (cur + 1) % cnt
                self.results_list.setCurrentRow(next_row)
            return

        if key == Qt.Key.Key_Up:
            cur = self.results_list.currentRow()
            cnt = self.results_list.count()
            if cnt > 0:
                prev_row = (cur - 1 + cnt) % cnt
                self.results_list.setCurrentRow(prev_row)
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_search_return_pressed()
            return

        super().keyPressEvent(event)


# Alias for backward-compatibility
ContextualSearchPanel = DedicatedRadialSearchPanel


# ---------------------------------------------------------------------------
# Dedicated Quick Settings Interface for the Radial Menu (Matching Reference Image)
# ---------------------------------------------------------------------------

class ContextualQuickSettingsPanel(QWidget):
    """
    Dedicated Quick Settings Interface hosted near the cursor.
    """
    closed = Signal()

    def __init__(self, overlay=None, settings: dict = None, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.overlay = overlay
        self.settings = settings or {}

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)

        self.qs_card = None
        if QuickSettingsCard is not None and self.overlay is not None:
            try:
                self.qs_card = QuickSettingsCard(self.overlay, parent=self)
                self._layout.addWidget(self.qs_card)
            except Exception:
                self.qs_card = QLabel("Quick Settings", self)
                self._layout.addWidget(self.qs_card)
        else:
            self.qs_card = QLabel("Quick Settings", self)
            self._layout.addWidget(self.qs_card)

        self._is_dismissing = False

        # Fast Shake Detection
        self._shake_history = []
        self._last_shake_dismiss_time = 0.0
        self._cursor_tracker_timer = QTimer(self)
        self._cursor_tracker_timer.setInterval(16)
        self._cursor_tracker_timer.timeout.connect(self._poll_cursor_shake)

    def sizeHint(self) -> QSize:
        if self.qs_card and hasattr(self.qs_card, "sizeHint"):
            c_hint = self.qs_card.sizeHint()
            return QSize(c_hint.width() + 16, c_hint.height() + 16)
        return QSize(252, 252)

    def adjust_geometry_to_screen(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        s_rect = screen.availableGeometry()

        s_hint = self.sizeHint()
        panel_w = max(246, s_hint.width())
        panel_h = s_hint.height()

        cur = self.geometry()
        tx = cur.x()
        ty = cur.y()

        # If expanding downwards hits taskbar or bottom edge, slide up so bottom is visible
        if ty + panel_h > s_rect.bottom() - 10:
            ty = s_rect.bottom() - 10 - panel_h

        # Top clamp
        if ty < s_rect.top() + 10:
            ty = s_rect.top() + 10
            panel_h = min(panel_h, s_rect.height() - 20)

        # Horizontal clamps
        if tx + panel_w > s_rect.right() - 10:
            tx = s_rect.right() - 10 - panel_w
        if tx < s_rect.left() + 10:
            tx = s_rect.left() + 10

        self.setGeometry(int(tx), int(ty), int(panel_w), int(panel_h))
        self.update()

    def open_at_cursor(self, cursor_pos: QPoint):
        self._is_dismissing = False
        self._shake_history.clear()
        screen = QGuiApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        s_rect = screen.availableGeometry()

        s_hint = self.sizeHint()
        panel_w = max(246, s_hint.width())
        panel_h = s_hint.height()

        tx = int(cursor_pos.x() - (panel_w / 2.0))
        ty = int(cursor_pos.y() - (panel_h / 2.0))

        # Bottom / Taskbar edge safety
        if ty + panel_h > s_rect.bottom() - 10:
            ty = s_rect.bottom() - 10 - panel_h
        if ty < s_rect.top() + 10:
            ty = s_rect.top() + 10
        if tx + panel_w > s_rect.right() - 10:
            tx = s_rect.right() - 10 - panel_w
        if tx < s_rect.left() + 10:
            tx = s_rect.left() + 10

        self.setGeometry(int(tx), int(ty), int(panel_w), int(panel_h))
        self.setWindowOpacity(0.0)
        self._cursor_tracker_timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

        self._anim_open = QPropertyAnimation(self, b"windowOpacity")
        self._anim_open.setDuration(140)
        self._anim_open.setStartValue(0.0)
        self._anim_open.setEndValue(1.0)
        self._anim_open.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_open.start()

    def dismiss(self, immediate: bool = False):
        if self._is_dismissing:
            return
        self._is_dismissing = True
        self._cursor_tracker_timer.stop()
        self.hide()
        self.closed.emit()

    def hideEvent(self, event):
        self._cursor_tracker_timer.stop()
        super().hideEvent(event)

    def _record_shake_point(self, x: float, y: float):
        now = time.time()
        self._shake_history.append((now, x, y))
        cutoff = now - 0.22
        while self._shake_history and self._shake_history[0][0] < cutoff:
            self._shake_history.pop(0)

    def _check_is_shake(self) -> bool:
        if len(self._shake_history) < 4:
            return False
        reversals_x, reversals_y = 0, 0
        last_sign_x, last_sign_y = 0, 0
        total_dist = 0.0

        for i in range(1, len(self._shake_history)):
            t0, x0, y0 = self._shake_history[i - 1]
            t1, x1, y1 = self._shake_history[i]
            dx, dy = x1 - x0, y1 - y0
            total_dist += math.hypot(dx, dy)

            cur_sign = 1 if dx > 6.0 else (-1 if dx < -6.0 else 0)
            if cur_sign != 0:
                if last_sign_x != 0 and cur_sign != last_sign_x:
                    reversals_x += 1
                last_sign_x = cur_sign

            cur_sign_y = 1 if dy > 6.0 else (-1 if dy < -6.0 else 0)
            if cur_sign_y != 0:
                if last_sign_y != 0 and cur_sign_y != last_sign_y:
                    reversals_y += 1
                last_sign_y = cur_sign_y

        now = time.time()
        if max(reversals_x, reversals_y) >= 2 and total_dist > 45.0 and (now - self._last_shake_dismiss_time > 0.8):
            self._last_shake_dismiss_time = now
            return True
        return False

    def _poll_cursor_shake(self):
        if not self.isVisible() or self._is_dismissing:
            self._cursor_tracker_timer.stop()
            return
        gpos = QCursor.pos()
        self._record_shake_point(gpos.x(), gpos.y())
        if self.settings.get("radial_shake_dismiss_enabled", True):
            if self._check_is_shake():
                self.dismiss(immediate=True)

    def changeEvent(self, event: QEvent):
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_dismissing:
                self.dismiss(immediate=True)
        super().changeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self.qs_card and self.qs_card.isVisible():
                g = self.qs_card.geometry()
                from odd_theme import create_squircle_path
                sh_rect = QRectF(g.x() - 1.5, g.y() - 1.0, g.width() + 3.0, g.height() + 4.0)
                sh_path = create_squircle_path(sh_rect, 28.0)
                painter.fillPath(sh_path, QBrush(QColor(0, 0, 0, 95)))
        finally:
            painter.end()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss(immediate=True)
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Dedicated Android Phone Mirroring Interface for Radial Menu
# ---------------------------------------------------------------------------

class ContextualPhoneMirrorPanel(QWidget):
    """
    Dedicated Android Phone Mirroring Interface hosted near the cursor.
    """
    closed = Signal()

    def __init__(self, overlay=None, settings: dict = None, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.overlay = overlay
        self.settings = settings or {}

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)

        self.mirror_card = None
        try:
            import odd_android_mirror
            self.mirror_card = odd_android_mirror.AndroidMirrorCard(self.overlay, parent=self)
            self._layout.addWidget(self.mirror_card)
        except Exception as e:
            self.mirror_card = QLabel(f"Phone Mirror: {e}", self)
            self.mirror_card.setStyleSheet("color: white; padding: 14px;")
            self._layout.addWidget(self.mirror_card)

        self._is_dismissing = False

    def sizeHint(self) -> QSize:
        if self.mirror_card and hasattr(self.mirror_card, "sizeHint"):
            c_hint = self.mirror_card.sizeHint()
            return QSize(max(440, c_hint.width() + 16), max(260, c_hint.height() + 16))
        return QSize(460, 360)

    def adjust_geometry_to_screen(self):
        screen = QGuiApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        s_rect = screen.availableGeometry()

        s_hint = self.sizeHint()
        panel_w = max(440, s_hint.width())
        panel_h = s_hint.height()

        cur = self.geometry()
        tx = cur.x()
        ty = cur.y()

        if ty + panel_h > s_rect.bottom() - 10:
            ty = s_rect.bottom() - 10 - panel_h
        if ty < s_rect.top() + 10:
            ty = s_rect.top() + 10
            panel_h = min(panel_h, s_rect.height() - 20)
        if tx + panel_w > s_rect.right() - 10:
            tx = s_rect.right() - 10 - panel_w
        if tx < s_rect.left() + 10:
            tx = s_rect.left() + 10

        self.setGeometry(int(tx), int(ty), int(panel_w), int(panel_h))
        self.update()

    def open_at_cursor(self, cursor_pos: QPoint):
        self._is_dismissing = False
        screen = QGuiApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        s_rect = screen.availableGeometry()

        s_hint = self.sizeHint()
        panel_w = max(440, s_hint.width())
        panel_h = s_hint.height()

        tx = int(cursor_pos.x() - (panel_w / 2.0))
        ty = int(cursor_pos.y() - (panel_h / 2.0))

        if ty + panel_h > s_rect.bottom() - 10:
            ty = s_rect.bottom() - 10 - panel_h
        if ty < s_rect.top() + 10:
            ty = s_rect.top() + 10
        if tx + panel_w > s_rect.right() - 10:
            tx = s_rect.right() - 10 - panel_w
        if tx < s_rect.left() + 10:
            tx = s_rect.left() + 10

        self.setGeometry(int(tx), int(ty), int(panel_w), int(panel_h))
        if self.mirror_card and hasattr(self.mirror_card, "refresh_status"):
            try:
                self.mirror_card.refresh_status()
            except Exception:
                pass
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()

        self._anim_open = QPropertyAnimation(self, b"windowOpacity")
        self._anim_open.setDuration(140)
        self._anim_open.setStartValue(0.0)
        self._anim_open.setEndValue(1.0)
        self._anim_open.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_open.start()

    def dismiss(self, immediate: bool = False):
        if self._is_dismissing:
            return
        self._is_dismissing = True
        self.hide()
        self.closed.emit()

    def changeEvent(self, event: QEvent):
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and self.isVisible() and not self._is_dismissing:
                self.dismiss(immediate=True)
        super().changeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self.mirror_card and self.mirror_card.isVisible():
                g = self.mirror_card.geometry()
                from odd_theme import create_squircle_path
                sh_rect = QRectF(g.x() - 1.5, g.y() - 1.0, g.width() + 3.0, g.height() + 4.0)
                sh_path = create_squircle_path(sh_rect, 24.0)
                painter.fillPath(sh_path, QBrush(QColor(0, 0, 0, 95)))
        finally:
            painter.end()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss(immediate=True)
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Radial Summon Controller
# ---------------------------------------------------------------------------

class RadialSummonController(QObject):
    """
    Coordinates Hold-to-Summon, Progress Ring, Arc, and Liquid Morphing into the Dedicated Search UI.
    """
    sig_hold_started = Signal(QPoint)
    sig_hold_cancelled = Signal()
    sig_hold_completed = Signal(QPoint)

    def __init__(self, overlay, settings: dict = None, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.settings = settings or {}

        # Widgets
        self.hold_indicator = RadialHoldIndicator()
        self.radial_menu = OddRadialArcMenu(self.overlay, self.settings)
        self.morph_anim = ArcMorphToOverlayAnimation(self.overlay)
        self.search_panel = DedicatedRadialSearchPanel(self.overlay, self.settings)
        self.qs_panel = ContextualQuickSettingsPanel(self.overlay, self.settings)
        self.phone_panel = ContextualPhoneMirrorPanel(self.overlay, self.settings)

        # Wire Morphing Actions from Arc
        self.radial_menu.request_morph_search.connect(self._on_morph_search)
        self.radial_menu.request_morph_quick_settings.connect(self._on_morph_quick_settings)
        self.radial_menu.request_morph_phone_mirror.connect(self._on_morph_phone_mirror)

        # State
        self._is_holding = False
        self._hold_start_time = 0.0
        self._has_summoned = False

        # Progress Timer (60 FPS)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(16)
        self._tick_timer.timeout.connect(self._on_tick)

        # Thread-safe signal connections
        self.sig_hold_started.connect(self._do_start_hold)
        self.sig_hold_cancelled.connect(self._do_cancel_hold)
        self.sig_hold_completed.connect(self._do_complete_hold)

        # Wire Media Progress for Cursor Indicator
        if hasattr(self.overlay, "media_mgr") and self.overlay.media_mgr:
            try:
                self.overlay.media_mgr.media_changed.connect(self._on_media_state_changed, Qt.ConnectionType.QueuedConnection)
            except Exception:
                pass

    @Slot(dict)
    def _on_media_state_changed(self, state: dict):
        if hasattr(self, "radial_menu") and self.radial_menu:
            self.radial_menu.update_media_state(state)

    def update_settings(self, new_settings: dict):
        self.settings = new_settings
        self.radial_menu.settings = new_settings
        self.search_panel.settings = new_settings
        self.qs_panel.settings = new_settings
        if hasattr(self, 'phone_panel'):
            self.phone_panel.settings = new_settings

    def is_menu_open(self) -> bool:
        return (
            self.radial_menu.isVisible() or
            self.search_panel.isVisible() or
            self.qs_panel.isVisible() or
            (hasattr(self, 'phone_panel') and self.phone_panel.isVisible())
        )

    # ------------------- Key Handlers -------------------

    def on_global_key_down(self, key_name: str):
        if not self.settings.get("radial_menu_enabled", True):
            return

        target_key = str(self.settings.get("radial_summon_key", "Alt")).lower().strip()
        k = key_name.lower().strip()

        is_target_key = False
        if target_key in ("alt", "menu"):
            is_target_key = "alt" in k
        elif target_key in ("ctrl", "control"):
            is_target_key = "ctrl" in k
        elif target_key in ("shift",):
            is_target_key = "shift" in k
        elif target_key in ("win", "cmd"):
            is_target_key = "cmd" in k or "win" in k
        else:
            is_target_key = (k == target_key)

        if is_target_key:
            if sys.platform == "win32":
                try:
                    user32 = ctypes.windll.user32
                    is_win = bool((user32.GetAsyncKeyState(0x5B) | user32.GetAsyncKeyState(0x5C)) & 0x8000)
                    is_ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
                    is_shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
                    if target_key in ("alt", "menu") and (is_win or is_ctrl or is_shift):
                        if self._is_holding:
                            self.sig_hold_cancelled.emit()
                        return
                except Exception:
                    pass

            if self.is_menu_open():
                return
            if is_caret_or_text_focused():
                return
            if is_mouse_dragging():
                return

            if not self._is_holding:
                pos = QCursor.pos()
                self.sig_hold_started.emit(pos)
        else:
            if self._is_holding:
                self.sig_hold_cancelled.emit()

    def on_global_key_up(self, key_name: str):
        target_key = str(self.settings.get("radial_summon_key", "Alt")).lower().strip()
        k = key_name.lower().strip()

        is_target_key = False
        if target_key in ("alt", "menu"):
            is_target_key = "alt" in k
        elif target_key in ("ctrl", "control"):
            is_target_key = "ctrl" in k
        elif target_key in ("shift",):
            is_target_key = "shift" in k
        elif target_key in ("win", "cmd"):
            is_target_key = "cmd" in k or "win" in k
        else:
            is_target_key = (k == target_key)

        if is_target_key:
            if self._is_holding:
                self.sig_hold_cancelled.emit()
            elif self._has_summoned and self.radial_menu.isVisible():
                # Marking Menu Gesture: if a slice is hovered when key is released, execute it immediately!
                if self.radial_menu.get_hovered_index() >= 0:
                    self.radial_menu.execute_hovered()
                self._has_summoned = False

    # ------------------- Main Thread Slots -------------------

    @Slot(QPoint)
    def _do_start_hold(self, cursor_pos: QPoint):
        self._is_holding = True
        self._has_summoned = False
        self._hold_start_time = time.time()

        half = self.hold_indicator.width() / 2
        self.hold_indicator.move(int(cursor_pos.x() - half), int(cursor_pos.y() - half))
        self.hold_indicator.set_progress(0.0)
        self.hold_indicator.show()
        self.hold_indicator.raise_()

        self._tick_timer.start()

    @Slot()
    def _do_cancel_hold(self):
        self._is_holding = False
        self._tick_timer.stop()
        self.hold_indicator.hide()
        self.hold_indicator.set_progress(0.0)

    @Slot(QPoint)
    def _do_complete_hold(self, cursor_pos: QPoint):
        self._is_holding = False
        self._has_summoned = True
        self._tick_timer.stop()
        self.hold_indicator.hide()

        # Open Arc Menu around cursor
        self.radial_menu.open_at_cursor(cursor_pos)

    def _on_tick(self):
        if not self._is_holding:
            self._tick_timer.stop()
            return

        if is_mouse_dragging():
            self._do_cancel_hold()
            return

        hold_duration_ms = float(self.settings.get("radial_summon_hold_ms", 400))
        elapsed = time.time() - self._hold_start_time
        progress = elapsed / (hold_duration_ms / 1000.0)

        curr_pos = QCursor.pos()
        half = self.hold_indicator.width() / 2
        self.hold_indicator.move(int(curr_pos.x() - half), int(curr_pos.y() - half))
        self.hold_indicator.set_progress(progress)

        if progress >= 1.0:
            self.sig_hold_completed.emit(curr_pos)

    # ------------------- Liquid Morphing into Dedicated Interfaces -------------------

    @Slot(QPoint, str)
    def _on_morph_search(self, cursor_pos: QPoint, initial_text: str):
        """Morphs the Arc directly into the Dedicated Dynamic-Island-Style Search UI near cursor."""
        target_rect = self.search_panel.get_target_rect(cursor_pos)

        def finish_search():
            self.search_panel.open_at_cursor(cursor_pos, initial_text=initial_text)

        self.morph_anim.start_morph(cursor_pos, target_rect=target_rect, on_finished=finish_search)

    @Slot(QPoint)
    def _on_morph_quick_settings(self, cursor_pos: QPoint):
        """Opens Quick Settings near cursor."""
        self.qs_panel.open_at_cursor(cursor_pos)

    @Slot(QPoint)
    def _on_morph_phone_mirror(self, cursor_pos: QPoint):
        """Opens dedicated contextual Phone Mirror right at cursor without opening top search bar."""
        self.phone_panel.open_at_cursor(cursor_pos)
