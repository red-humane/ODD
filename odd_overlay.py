import sys
import os
import math
import time
import ctypes
import base64
import threading
import concurrent.futures
import subprocess
import calendar
import datetime
import uuid
import webbrowser
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from PySide6.QtCore import (
    Qt, QPoint, QPointF, QRect, QRectF, QSize, QPropertyAnimation,
    QSequentialAnimationGroup, QParallelAnimationGroup, QEasingCurve, QTimer, QEvent, QByteArray, Signal, Property, Slot
)
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QPainterPath, QPixmap, QIcon, QCursor, QLinearGradient, QRadialGradient, QConicalGradient, QFontMetrics, QRegion, QGuiApplication, QImage
from PySide6.QtWidgets import (
    QApplication, QWidget, QLineEdit, QVBoxLayout, QListWidget,
    QListWidgetItem, QLabel, QHBoxLayout, QPushButton, QFrame, QMenu, QSlider,
    QGridLayout, QGraphicsBlurEffect, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QSizePolicy, QScrollArea
)
from PySide6.QtSvg import QSvgRenderer
import odd_theme
from odd_theme import Tokens, Fonts, MonochromeIcons
import odd_ui
import odd_search
from odd_search import WindowsSearchEngine, SearchItem
import odd_sound
import odd_media
import odd_blur
import odd_icons
import odd_island
from odd_island import DynamicIslandHUD, DynamicIslandMonitor, OddBezelHUD
from odd_spring import SpringEngine, SpringValue
import odd_com
import odd_tier
from odd_crash_capture import log_breadcrumb, safe_slot

# Bounded threadpool for non-blocking search execution (prevents thread storms on low-end dual-core PCs)
_SEARCH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="OddSearchWorker")


def create_frosted_blur_effect(blur_radius: float = 15.0, parent=None) -> QGraphicsBlurEffect:
    """
    Creates a hardware-accelerated translucent blur effect for frosted glass cards.
    Example:
        blur = create_frosted_blur_effect(15.0)
        widget.setGraphicsEffect(blur)
    """
    blur = QGraphicsBlurEffect(parent)
    blur.setBlurRadius(blur_radius)
    blur.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    return blur


def apply_blur_behind(hwnd: int, enable: bool = True):
    """No-op on HWND to prevent Windows DWM from rendering a dark rectangular panel behind transparent floating widgets"""
    pass


def is_window_fullscreen(hwnd: int = 0) -> bool:
    """Accurately detects whether the active or given window is running in fullscreen mode."""
    try:
        user32 = ctypes.windll.user32
        if not hwnd:
            hwnd = user32.GetForegroundWindow()
        if not hwnd or not user32.IsWindow(hwnd):
            return False

        rect = ctypes.wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False

        h_mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if not h_mon:
            return False

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.wintypes.DWORD),
            ]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
            return False

        m = mi.rcMonitor
        return (
            rect.left <= m.left + 2 and
            rect.top <= m.top + 2 and
            rect.right >= m.right - 2 and
            rect.bottom >= m.bottom - 2
        )
    except Exception:
        return False

def force_foreground_focus(win_id):
    """Reliably forces foreground keyboard activation on Windows even from hover or background"""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = int(win_id)
        if not hwnd:
            return

        foreground_hwnd = user32.GetForegroundWindow()
        if foreground_hwnd == hwnd:
            user32.SetActiveWindow(hwnd)
            return

        # Attempt clean foreground transfer first to avoid sending synthetic Alt keys over fullscreen windows
        if user32.SetForegroundWindow(hwnd):
            user32.SetActiveWindow(hwnd)
            return

        # Simulate Alt key event only if initial transfer didn't succeed to unlock Windows foreground lock restriction
        user32.keybd_event(0x12, 0, 0, 0) # VK_MENU down
        user32.keybd_event(0x12, 0, 2, 0) # VK_MENU up

        try:
            user32.AllowSetForegroundWindow(-1)
            user32.LockSetForegroundWindow(2)
        except Exception:
            pass

        fore_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        app_thread = kernel32.GetCurrentThreadId()

        if fore_thread and fore_thread != app_thread:
            user32.AttachThreadInput(fore_thread, app_thread, True)
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0043)  # HWND_TOPMOST, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.AttachThreadInput(fore_thread, app_thread, False)
        else:
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0043)
            user32.ShowWindow(hwnd, 5)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
    except Exception:
        pass

def is_mouse_dragging() -> bool:
    """Returns True if any mouse button is currently held down (e.g. dragging a file, window, or selecting)"""
    try:
        user32 = ctypes.windll.user32
        # VK_LBUTTON = 0x01, VK_RBUTTON = 0x02, VK_MBUTTON = 0x04
        return bool(user32.GetAsyncKeyState(0x01) & 0x8000 or 
                    user32.GetAsyncKeyState(0x02) & 0x8000 or 
                    user32.GetAsyncKeyState(0x04) & 0x8000)
    except Exception:
        return False

def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        base_path = Path(__file__).resolve().parent
    return base_path / relative_path

def get_app_icon() -> QIcon:
    """Load application icon for tray and windows"""
    ico_path = get_resource_path("odd.ico")
    if ico_path.exists():
        return QIcon(str(ico_path))
    png_path = get_resource_path("odd_logo.png")
    if png_path.exists():
        return QIcon(str(png_path))
    return QIcon()


class VisualCaptureOverlay(QWidget):
    """Fullscreen drag selection used by visual tools such as Similar Image Search."""
    def __init__(self, on_captured, parent=None):
        super().__init__(parent)
        self.on_captured = on_captured
        self.screen = QGuiApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.origin = None
        self.selection = QRect()
        self.setGeometry(self.screen.geometry())
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.selection = QRect(self.origin, self.origin)
            self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection = QRect(self.origin, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        selection = self.selection.normalized()
        if selection.width() < 20 or selection.height() < 20:
            center = event.position().toPoint()
            selection = QRect(center.x() - 140, center.y() - 140, 280, 280).intersected(self.rect())
        self.hide()
        QTimer.singleShot(80, lambda: self._capture(selection))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def _capture(self, selection: QRect):
        pixmap = self.screen.grabWindow(0, selection.x(), selection.y(), selection.width(), selection.height())
        if not pixmap.isNull():
            captures_dir = Path.home() / "Pictures" / "ODD Captures"
            captures_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            path = captures_dir / f"similar-image-{timestamp}-{uuid.uuid4().hex[:6]}.png"
            if pixmap.save(str(path), "PNG"):
                self.on_captured(path)
                self.deleteLater()
                return
        self.on_captured(None)
        self.deleteLater()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 92))
        if not self.selection.isNull():
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self.selection, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(255, 255, 255, 225), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.selection), 4.0, 4.0)


def get_odd_logo_pixmap(size=(24, 24), theme="dark") -> QPixmap:
    """Returns official ODD logo pixmap, automatically using odd_logo_black.png for light theme or odd_logo.png for dark/oled theme"""
    is_light = (str(theme).lower() == "light")
    target_name = "odd_logo_black.png" if is_light else "odd_logo.png"
    png_path = get_resource_path(target_name)
    if not png_path.exists():
        png_path = Path(__file__).resolve().parent / target_name
    if not png_path.exists():
        png_path = get_resource_path("odd_logo.png")
        if not png_path.exists():
            png_path = Path(__file__).resolve().parent / "odd_logo.png"

    src = QPixmap()
    if png_path.exists():
        src = QPixmap(str(png_path)).scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    if src.isNull():
        # Fallback to base64 embedded source if present
        b64_path = get_resource_path("odd_logo_b64.txt")
        if not b64_path.exists():
            b64_path = Path(__file__).resolve().parent / "odd_logo_b64.txt"
        if b64_path.exists():
            try:
                import base64
                b64_data = b64_path.read_text(encoding="utf-8").strip()
                raw_bytes = base64.b64decode(b64_data)
                src.loadFromData(raw_bytes)
                if not src.isNull():
                    src = src.scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            except Exception:
                pass

    return src


class BorderGlowEffect:
    """
    Inactive - Search box hover reflection removed per user request.
    """
    @classmethod
    def paint_glow(
        cls,
        painter: QPainter,
        rect: QRectF,
        radius: float = 28.0,
        mouse_pos: Optional[QPointF] = None,
        theme: str = "dark",
        anim_phase: float = 0.0,
        active: bool = False
    ):
        return
        if not active or rect.width() <= 2.0 or rect.height() <= 2.0 or mouse_pos is None:
            return

        mx = float(mouse_pos.x())
        my = float(mouse_pos.y())
        margin = cls.EDGE_SENSITIVITY

        # Hovered area check
        if not (rect.left() - margin <= mx <= rect.right() + margin and rect.top() - margin <= my <= rect.bottom() + margin):
            return

        cx = max(rect.left(), min(rect.right(), mx))

        # Vertical proximity
        if rect.top() <= my <= rect.bottom():
            glow_alpha = cls.GLOW_INTENSITY
        else:
            vert_d = min(abs(my - rect.top()), abs(my - rect.bottom()))
            glow_alpha = max(0.0, min(1.0, 1.0 - (vert_d / margin))) * cls.GLOW_INTENSITY

        if glow_alpha <= 0.01:
            return

        r = max(2.0, min(float(radius), rect.width() / 2.0, rect.height() / 2.0))
        border_path = QPainterPath()
        border_path.addRoundedRect(rect, r, r)

        top_pt = QPointF(cx, rect.top())
        bottom_pt = QPointF(cx, rect.bottom())

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        spread = cls.CONE_SPREAD
        bloom_rad = cls.GLOW_RADIUS

        # Clip strictly to top and bottom of that hovered area
        clip_path = QPainterPath()
        clip_path.addEllipse(top_pt, spread * 1.5, spread * 1.3)
        clip_path.addEllipse(bottom_pt, spread * 1.5, spread * 1.3)
        painter.setClipPath(clip_path)

        for pt in (top_pt, bottom_pt):
            # 1. Soft atmospheric bloom strictly in white family
            grad = QRadialGradient(pt.x(), pt.y(), bloom_rad)
            grad.setColorAt(0.0, QColor(255, 255, 255, int(min(220, 190 * glow_alpha))))
            grad.setColorAt(0.35, QColor(255, 255, 255, int(min(140, 100 * glow_alpha))))
            grad.setColorAt(0.70, QColor(255, 255, 255, int(min(60, 35 * glow_alpha))))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.strokePath(border_path, QPen(QBrush(grad), 3.0))

            # 2. Focused pure white specular crest
            line_grad = QLinearGradient(pt.x() - spread, pt.y(), pt.x() + spread, pt.y())
            line_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            line_grad.setColorAt(0.5, QColor(255, 255, 255, int(min(255, 220 * glow_alpha))))
            line_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            core_pen = QPen(QBrush(line_grad), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(border_path, core_pen)

        painter.restore()


class MetallicPaint:
    """
    MetallicPaint shader effect for ODD icons and logo:
    import MetallicPaint from './MetallicPaint';
    <MetallicPaint text="Liquid" color="#f2c46b" edgeBend={0.9}
      color="#ffffff"
      density={2}
      softness={0.1}
      dispersion={0.3}
      distortion={0.07}
      edgeBend={0.6}
      angle={70}
      scale={0.6}
      speed={1}
      rotation={0}
      mouseTilt={0.5}
      intro
    />
    """
    ANGLE = 70.0
    EDGE_BEND = 0.6
    DISPERSION = 0.3
    MOUSE_TILT = 0.5

    _pixmap_cache = {}

    @classmethod
    def get_gradient(
        cls,
        rect: QRectF,
        angle: float = 70.0,
        mouse_pos: Optional[QPointF] = None,
        center: Optional[QPointF] = None,
        phase: float = 0.0,
        theme: str = "dark"
    ) -> QLinearGradient:
        cx = center.x() if center else rect.center().x()
        cy = center.y() if center else rect.center().y()
        w = max(1.0, rect.width())
        h = max(1.0, rect.height())

        eff_angle = angle
        if mouse_pos is not None:
            dx = (mouse_pos.x() - cx) / (w * 0.5)
            dy = (mouse_pos.y() - cy) / (h * 0.5)
            tilt = dx * cls.MOUSE_TILT * 30.0 - dy * cls.MOUSE_TILT * 15.0
            eff_angle = (angle + tilt) % 360.0

        rad = math.radians(eff_angle)
        span = max(w, h) * 0.85
        p1 = QPointF(cx - math.cos(rad) * span, cy - math.sin(rad) * span)
        p2 = QPointF(cx + math.cos(rad) * span, cy + math.sin(rad) * span)

        grad = QLinearGradient(p1, p2)
        shimmer = math.sin(phase) * 0.08

        if str(theme).lower() == "light":
            grad.setColorAt(0.0, QColor("#27272a"))
            grad.setColorAt(0.25, QColor("#3f3f46"))
            s1 = max(0.0, min(1.0, 0.40 + shimmer))
            grad.setColorAt(s1, QColor("#71717a"))
            s2 = max(0.0, min(1.0, 0.50 + shimmer))
            grad.setColorAt(s2, QColor("#d4d4d8"))
            s3 = max(0.0, min(1.0, 0.60 + shimmer))
            grad.setColorAt(s3, QColor("#52525b"))
            grad.setColorAt(0.85, QColor("#27272a"))
            grad.setColorAt(1.0, QColor("#18181b"))
        else:
            grad.setColorAt(0.0, QColor("#a1a1aa"))
            grad.setColorAt(0.20, QColor("#d4d4d8"))
            s_disp1 = max(0.05, min(0.95, 0.36 + shimmer))
            grad.setColorAt(s_disp1, QColor("#e4e4e7"))
            s_peak = max(0.10, min(0.90, 0.48 + shimmer))
            grad.setColorAt(s_peak, QColor("#ffffff"))
            s_disp2 = max(0.15, min(0.95, 0.58 + shimmer))
            grad.setColorAt(s_disp2, QColor("#f4f4f5"))
            grad.setColorAt(0.72, QColor("#71717a"))
            grad.setColorAt(0.88, QColor("#f4f4f5"))
            grad.setColorAt(1.0, QColor("#a1a1aa"))

        return grad

    @classmethod
    def get_pen_and_brush(
        cls,
        rect: QRectF,
        stroke_width: float = 1.4,
        angle: float = 70.0,
        mouse_pos: Optional[QPointF] = None,
        center: Optional[QPointF] = None,
        phase: float = 0.0,
        theme: str = "dark"
    ) -> Tuple[QPen, QBrush]:
        grad = cls.get_gradient(rect, angle=angle, mouse_pos=mouse_pos, center=center, phase=phase, theme=theme)
        brush = QBrush(grad)
        pen = QPen(brush, stroke_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        return pen, brush

    @classmethod
    def render_metallic_pixmap(
        cls,
        src: QPixmap,
        angle: float = 70.0,
        mouse_offset: Tuple[float, float] = (0.0, 0.0),
        phase: float = 0.0,
        theme: str = "dark"
    ) -> QPixmap:
        if not src or src.isNull():
            return src

        ck = (src.cacheKey(), int(angle), int(mouse_offset[0] * 5), int(mouse_offset[1] * 5), int(phase * 4), str(theme).lower())
        if ck in cls._pixmap_cache:
            return cls._pixmap_cache[ck]

        w, h = src.width(), src.height()
        result = QPixmap(w, h)
        result.fill(Qt.GlobalColor.transparent)

        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        painter.drawPixmap(0, 0, src)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)

        m_pos = QPointF(w / 2.0 + mouse_offset[0], h / 2.0 + mouse_offset[1]) if (mouse_offset != (0.0, 0.0)) else None
        grad = cls.get_gradient(QRectF(0, 0, w, h), angle=angle, mouse_pos=m_pos, center=QPointF(w / 2.0, h / 2.0), phase=phase, theme=theme)
        painter.fillRect(0, 0, w, h, QBrush(grad))

        # Edge-bend specular bevel pass (edgeBend=0.6)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        bevel_pen = QPen(QColor(255, 255, 255, int(50 * cls.EDGE_BEND)), 0.7)
        painter.setPen(bevel_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 3.0, 3.0)

        painter.end()

        if len(cls._pixmap_cache) > 120:
            cls._pixmap_cache.clear()
        cls._pixmap_cache[ck] = result
        return result


class MediaControlIconButton(QPushButton):
    """Sleek minimalist vector-drawn button with zero drop shadows, crisp specular highlights, and spring micro-interactions"""
    def __init__(self, icon_type="play", theme="dark", size=(28, 28), parent=None):
        super().__init__(parent)
        self.icon_type = icon_type  # "play", "pause", "prev", "next", "search", "music", "volume", "mute", "plus", "close", "mic", "waveform", "star", "sliders", "lens", "phone"
        self.theme = theme
        self._is_active = False
        self.setFixedSize(size[0], size[1])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Micro-interaction spring physics (ExpressiveButtonAnimation)
        self.scale_spring = SpringValue(initial_value=1.0, response=0.07, damping_ratio=0.78)
        self.radius_spring = SpringValue(initial_value=14.0, response=0.10, damping_ratio=0.75)
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(8)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

        # Hamburger to Close morph animation
        self._hamburger_progress = 0.0
        self._hamburger_target = 0.0
        self._hamburger_timer = QTimer(self)
        self._hamburger_timer.setInterval(16)
        self._hamburger_timer.timeout.connect(self._on_hamburger_tick)

        # React-UseAnimations Player integration
        try:
            from odd_useanimations import UseAnimationPlayer, canonical_anim_name
            c_name = canonical_anim_name(self.icon_type)
            if c_name in ("smartphone", "camera", "volume", "wifi", "wifiOff", "bluetooth", "scissors", "clock", "download"):
                self._use_anim_player = UseAnimationPlayer(self.icon_type, parent=self)
                self._use_anim_player.frame_changed.connect(lambda _: self.update())
            else:
                self._use_anim_player = None
        except Exception:
            self._use_anim_player = None

    def set_active(self, active: bool):
        act = bool(active)
        if self._is_active != act:
            self._is_active = act
            self._hamburger_target = 1.0 if act else 0.0
            if not self._hamburger_timer.isActive():
                self._hamburger_timer.start()
            self.update()

    def _on_hamburger_tick(self):
        diff = self._hamburger_target - self._hamburger_progress
        if abs(diff) < 0.02:
            self._hamburger_progress = self._hamburger_target
            self._hamburger_timer.stop()
        else:
            self._hamburger_progress += diff * 0.22
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.04, now - self._last_step)
        self._last_step = now
        self.scale_spring.update(dt)
        if hasattr(self, 'radius_spring'):
            self.radius_spring.update(dt)
        self._anim_phase += 0.06
        self.update()
        if self.scale_spring.is_settled():
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._hover_pos = event.position() if hasattr(event, "position") else event.pos()
        self.update()

    def enterEvent(self, event):
        self._hover_pos = event.position() if hasattr(event, "position") else event.pos()
        super().enterEvent(event)
        self.scale_spring.set_target(1.08, preserve_velocity=True)
        self._wake_anim()
        if getattr(self, '_use_anim_player', None):
            self._use_anim_player.handle_hover_enter()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()
        if getattr(self, '_use_anim_player', None):
            self._use_anim_player.handle_hover_leave()

    def set_icon_type(self, icon_type: str):
        if self.icon_type != icon_type:
            self.icon_type = icon_type
            if getattr(self, '_use_anim_player', None):
                self._use_anim_player.set_animation(icon_type)
            self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # ExpressiveButtonAnimation: Corner radius morphs towards 6.0px, scale expands to 1.08
        if hasattr(self, 'radius_spring'):
            self.radius_spring.set_target(6.0, preserve_velocity=True)
        self.scale_spring.set_target(1.08, preserve_velocity=True)
        self._wake_anim()
        if getattr(self, '_use_anim_player', None):
            self._use_anim_player.handle_click()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # ExpressiveButtonAnimation: Corner radius springs back to 14.0px, scale settles
        if hasattr(self, 'radius_spring'):
            self.radius_spring.set_target(14.0, preserve_velocity=True)
        target = 1.04 if self.underMouse() else 1.0
        self.scale_spring.set_target(target, preserve_velocity=True)
        self._wake_anim()

    def paintEvent(self, event):
        try:
            self._do_paint_event(event)
        except Exception:
            pass

    def _do_paint_event(self, event):
        parent_op = getattr(self.parentWidget(), "_content_progress", 1.0) if self.parentWidget() else 1.0
        if parent_op <= 0.01:
            return
        painter = QPainter(self)
        try:
            self._draw_media_control_content(painter, parent_op)
        finally:
            if painter.isActive():
                painter.end()

    def _draw_media_control_content(self, painter, parent_op):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if parent_op < 0.999:
            painter.setOpacity(max(0.0, min(1.0, float(parent_op))))

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        s = self.scale_spring.value

        painter.save()
        painter.translate(cx, cy)
        painter.scale(s, s)
        painter.translate(-cx, -cy)

        pad = 2.5 if self.width() >= 36 else 2.0
        rect = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        r_target = self.radius_spring.value if hasattr(self, 'radius_spring') else min(rect.width(), rect.height()) / 2.0
        r = max(4.0, min(min(rect.width(), rect.height()) / 2.0, r_target))
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)

        theme = str(self.theme).lower()
        is_standalone = (self.width() >= 36)

        if is_standalone:
            # Standalone Circular Button (Apple Music signature Play/Pause centerpiece if play/pause)
            if self.icon_type in ("play", "pause"):
                if theme == "light":
                    if self.isDown():
                        bg_color = QColor(200, 204, 214, 250)
                    elif self.underMouse():
                        bg_color = QColor(215, 220, 230, 255)
                    else:
                        bg_color = QColor(230, 234, 242, 245)
                    border_color = QColor(0, 0, 0, 45)
                    icon_color = QColor(20, 22, 28, 255)
                elif theme == "oled":
                    if self.isDown():
                        bg_color = QColor(16, 18, 22, 250)
                    elif self.underMouse():
                        bg_color = QColor(32, 36, 44, 255)
                    else:
                        bg_color = QColor(24, 26, 32, 245)
                    border_color = QColor(255, 255, 255, 55)
                    icon_color = QColor(255, 255, 255, 255)
                else: # dark theme (sleek dark translucent circle - NO WHITE BACKGROUND!)
                    if self.isDown():
                        bg_color = QColor(24, 26, 32, 245)
                    elif self.underMouse():
                        bg_color = QColor(50, 54, 66, 245)
                    else:
                        bg_color = QColor(36, 38, 46, 235)
                    border_color = QColor(255, 255, 255, 50)
                    icon_color = QColor(255, 255, 255, 255)

                painter.fillPath(path, QBrush(bg_color))
                painter.strokePath(path, QPen(border_color, 1.0))
            elif theme == "light":
                if self.isDown():
                    bg_color = QColor(220, 222, 228, 230)
                    border_color = QColor(0, 0, 0, 45)
                elif self.underMouse():
                    bg_color = QColor(255, 255, 255, 240)
                    border_color = QColor(0, 0, 0, 50)
                else:
                    bg_color = QColor(245, 246, 250, 205)
                    border_color = QColor(0, 0, 0, 25)
                icon_color = QColor(23, 23, 23, 255)

                painter.fillPath(path, QBrush(bg_color))
                painter.strokePath(path, QPen(border_color, 1.0))
            elif theme == "oled":
                if self.isDown():
                    bg_color = QColor(14, 14, 18, 250)
                    border_color = QColor(255, 255, 255, 90)
                elif self.underMouse():
                    bg_color = QColor(24, 24, 30, 245)
                    border_color = QColor(255, 255, 255, 70)
                else:
                    bg_color = QColor(6, 6, 8, 235)
                    border_color = QColor(255, 255, 255, 40)
                icon_color = QColor(255, 255, 255, 255)

                painter.fillPath(path, QBrush(bg_color))
                painter.strokePath(path, QPen(border_color, 1.0))
            else: # dark (neutral translucent frosted glass)
                grad = QLinearGradient(0, 0, 0, self.height())
                if self.isDown():
                    grad.setColorAt(0.0, QColor(24, 26, 32, 240))
                    grad.setColorAt(1.0, QColor(12, 14, 18, 245))
                    border_alpha = 50
                elif self.underMouse():
                    grad.setColorAt(0.0, QColor(56, 62, 74, 225))
                    grad.setColorAt(0.4, QColor(36, 40, 50, 230))
                    grad.setColorAt(1.0, QColor(22, 25, 32, 240))
                    border_alpha = 100
                else:
                    grad.setColorAt(0.0, QColor(42, 46, 56, 205))
                    grad.setColorAt(0.4, QColor(26, 30, 38, 215))
                    grad.setColorAt(1.0, QColor(16, 18, 24, 225))
                    border_alpha = 70

                painter.fillPath(path, QBrush(grad))

                border_grad = QLinearGradient(0, 0, 0, self.height())
                border_grad.setColorAt(0.0, QColor(255, 255, 255, border_alpha))
                border_grad.setColorAt(0.35, QColor(255, 255, 255, int(border_alpha * 0.6)))
                border_grad.setColorAt(1.0, QColor(255, 255, 255, int(border_alpha * 0.25)))
                painter.strokePath(path, QPen(QBrush(border_grad), 1.0))

                highlight_path = QPainterPath()
                highlight_rect = rect.adjusted(1, 1, -1, -1)
                highlight_path.addRoundedRect(highlight_rect, r - 1, r - 1)
                painter.strokePath(highlight_path, QPen(QColor(255, 255, 255, 28), 0.8))

                icon_color = QColor(245, 245, 245, 240)
        else:
            # Inline button inside Search Pill (e.g. sliders, lens, phone, waveform)
            if self._is_active:
                if theme == "light":
                    active_bg = QColor(0, 0, 0, 24)
                    active_stroke = QColor(0, 0, 0, 48)
                    icon_color = QColor(18, 22, 30, 255)
                else:
                    active_bg = Tokens.SURFACE_3
                    active_stroke = Tokens.BORDER_STRONG
                    icon_color = Tokens.TEXT_PRIMARY
                painter.fillPath(path, QBrush(active_bg))
                painter.strokePath(path, QPen(active_stroke, 1.0))
            elif self.underMouse():
                hover_bg = QColor(0, 0, 0, 16) if theme == "light" else Tokens.SURFACE_2
                painter.fillPath(path, QBrush(hover_bg))
                icon_color = QColor(23, 23, 23, 255) if theme == "light" else Tokens.TEXT_PRIMARY
            else:
                icon_color = QColor(100, 100, 100, 220) if theme == "light" else Tokens.TEXT_SECONDARY

            # Vector monochrome icon rendering with 0 artifacts
            if self.icon_type in ("quick_settings", "sliders"):
                self._draw_animated_hamburger(painter, cx, cy, icon_color)
            else:
                MonochromeIcons.draw(self.icon_type, painter, QPointF(cx, cy), size=18.0, color=icon_color, stroke_width=1.7)
            painter.restore()
            return

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        eff_icon_pen, eff_icon_brush = MetallicPaint.get_pen_and_brush(
            QRectF(cx - 10.0, cy - 10.0, 20.0, 20.0),
            stroke_width=1.4,
            angle=70.0,
            mouse_pos=getattr(self, "_hover_pos", None),
            center=QPointF(cx, cy),
            phase=getattr(self, "_anim_phase", 0.0),
            theme=theme
        )

        painter.setBrush(eff_icon_brush if theme != "light" else QBrush(icon_color))
        painter.setPen(eff_icon_pen if theme != "light" else QPen(icon_color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        if self.icon_type in ("plus", "menu"):
            # Clean minimalist plus crosshair icon
            painter.setPen(eff_icon_pen if theme != "light" else QPen(icon_color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(cx - 5.0), int(cy), int(cx + 5.0), int(cy))
            painter.drawLine(int(cx), int(cy - 5.0), int(cx), int(cy + 5.0))
        elif self.icon_type == "close":
            painter.drawLine(int(cx - 4.5), int(cy - 4.5), int(cx + 4.5), int(cy + 4.5))
            painter.drawLine(int(cx + 4.5), int(cy - 4.5), int(cx - 4.5), int(cy + 4.5))
        elif self.icon_type == "mic":
            # Clean vector microphone
            painter.setBrush(eff_icon_brush if theme != "light" else QBrush(icon_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(cx - 2.8, cy - 6.5, 5.6, 8.5), 2.8, 2.8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(eff_icon_pen if theme != "light" else QPen(icon_color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(cx - 5.0, cy - 4.0, 10.0, 9.0), 0, -180 * 16)
            painter.drawLine(int(cx), int(cy + 5.0), int(cx), int(cy + 7.5))
            painter.drawLine(int(cx - 3.0), int(cy + 7.5), int(cx + 3.0), int(cy + 7.5))
        elif self.icon_type == "waveform":
            # 5-bar vector sound equalizer
            painter.setBrush(eff_icon_brush if theme != "light" else QBrush(icon_color))
            painter.setPen(Qt.PenStyle.NoPen)
            bars = [-5.5, -2.75, 0.0, 2.75, 5.5]
            heights = [5, 10, 14, 8, 4]
            for x_off, h in zip(bars, heights):
                painter.drawRoundedRect(QRectF(cx + x_off - 0.75, cy - h / 2.0, 1.5, h), 0.75, 0.75)
        elif self.icon_type in ("chat", "share", "nearby", "sync", "devices"):
            # Vector Nearby Share / Universal Device Drop icon (overlapping beaming nodes)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(eff_icon_pen if theme != "light" else QPen(icon_color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(QPoint(int(cx - 4.5), int(cy - 2.5)), 3, 3)
            painter.drawEllipse(QPoint(int(cx + 4.5), int(cy + 2.5)), 3, 3)
            painter.drawLine(int(cx - 2.0), int(cy - 1.2), int(cx + 2.0), int(cy + 1.2))
        elif self.icon_type == "star":
            # 5-point vector star
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(icon_color, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            star_path = QPainterPath()
            points = []
            for i in range(10):
                angle = -math.pi / 2.0 + i * math.pi / 5.0
                r_val = 5.8 if i % 2 == 0 else 2.6
                points.append(QPoint(int(cx + r_val * math.cos(angle)), int(cy + r_val * math.sin(angle))))
            star_path.moveTo(points[0])
            for p in points[1:]:
                star_path.lineTo(p)
            star_path.closeSubpath()
            painter.drawPath(star_path)
        elif self.icon_type in ("sun", "brightness"):
            # Clean vector Sun / Brightness icon
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(eff_icon_pen if theme != "light" else QPen(icon_color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
            for i in range(8):
                ang = i * math.pi / 4.0
                x1 = cx + 4.8 * math.cos(ang)
                y1 = cy + 4.8 * math.sin(ang)
                x2 = cx + 6.8 * math.cos(ang)
                y2 = cy + 6.8 * math.sin(ang)
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        elif self.icon_type in ("sliders", "quick_settings", "controls"):
            self._draw_animated_hamburger(painter, cx, cy, icon_color)
        elif self.icon_type in ("phone", "phone_mirror", "android", "mirror", "smartphone", "mobile"):
            # Material Symbols Outlined: 'mobile'
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(icon_color, 1.55, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            # Clean smartphone body
            phone_rect = QRectF(cx - 4.6, cy - 7.4, 9.2, 14.8)
            painter.drawRoundedRect(phone_rect, 2.2, 2.2)
            # Top speaker slot
            painter.setPen(QPen(icon_color, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(cx - 1.2, cy - 5.4), QPointF(cx + 1.2, cy - 5.4))
            # Bottom home bar
            painter.drawLine(QPointF(cx - 1.6, cy + 5.2), QPointF(cx + 1.6, cy + 5.2))
        elif self.icon_type == "play":
            path = QPainterPath()
            if self.width() >= 36:
                # Prominent centerpiece play triangle
                path.moveTo(cx - 5.2, cy - 7.5)
                path.lineTo(cx + 7.5, cy)
                path.lineTo(cx - 5.2, cy + 7.5)
            else:
                path.moveTo(cx - 3.8, cy - 5.8)
                path.lineTo(cx + 5.8, cy)
                path.lineTo(cx - 3.8, cy + 5.8)
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(path, QBrush(icon_color))
        elif self.icon_type == "pause":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_color))
            if self.width() >= 36:
                bar_w, bar_h, r_bar = 3.8, 13.5, 1.9
                painter.drawRoundedRect(QRectF(cx - 5.5, cy - bar_h / 2.0, bar_w, bar_h), r_bar, r_bar)
                painter.drawRoundedRect(QRectF(cx + 1.7, cy - bar_h / 2.0, bar_w, bar_h), r_bar, r_bar)
            else:
                bar_w, bar_h, r_bar = 3.2, 10.8, 1.6
                painter.drawRoundedRect(QRectF(cx - 4.6, cy - bar_h / 2.0, bar_w, bar_h), r_bar, r_bar)
                painter.drawRoundedRect(QRectF(cx + 1.4, cy - bar_h / 2.0, bar_w, bar_h), r_bar, r_bar)
        elif self.icon_type == "prev":
            if self.width() >= 32 and not is_standalone:
                hover_alpha = 38 if self.underMouse() else 16
                bg_c = QColor(0, 0, 0, hover_alpha) if theme == "light" else QColor(255, 255, 255, hover_alpha)
                painter.fillPath(path, QBrush(bg_c))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_color))
            if self.width() >= 32:
                painter.drawRoundedRect(QRectF(cx - 7.5, cy - 6.0, 2.3, 12.0), 1.1, 1.1)
                p_arr = QPainterPath()
                p_arr.moveTo(cx + 6.0, cy - 6.0)
                p_arr.lineTo(cx - 4.0, cy)
                p_arr.lineTo(cx + 6.0, cy + 6.0)
                p_arr.closeSubpath()
                painter.fillPath(p_arr, QBrush(icon_color))
            else:
                painter.drawRoundedRect(QRectF(cx - 6.5, cy - 5.0, 2.0, 10.0), 1.0, 1.0)
                p_arr = QPainterPath()
                p_arr.moveTo(cx + 5.0, cy - 5.0)
                p_arr.lineTo(cx - 3.5, cy)
                p_arr.lineTo(cx + 5.0, cy + 5.0)
                p_arr.closeSubpath()
                painter.fillPath(p_arr, QBrush(icon_color))
        elif self.icon_type == "next":
            if self.width() >= 32 and not is_standalone:
                hover_alpha = 38 if self.underMouse() else 16
                bg_c = QColor(0, 0, 0, hover_alpha) if theme == "light" else QColor(255, 255, 255, hover_alpha)
                painter.fillPath(path, QBrush(bg_c))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_color))
            if self.width() >= 32:
                painter.drawRoundedRect(QRectF(cx + 5.2, cy - 6.0, 2.3, 12.0), 1.1, 1.1)
                p_arr = QPainterPath()
                p_arr.moveTo(cx - 6.0, cy - 6.0)
                p_arr.lineTo(cx + 4.0, cy)
                p_arr.lineTo(cx - 6.0, cy + 6.0)
                p_arr.closeSubpath()
                painter.fillPath(p_arr, QBrush(icon_color))
            else:
                painter.drawRoundedRect(QRectF(cx + 4.5, cy - 5.0, 2.0, 10.0), 1.0, 1.0)
                p_arr = QPainterPath()
                p_arr.moveTo(cx - 5.0, cy - 5.0)
                p_arr.lineTo(cx + 3.5, cy)
                p_arr.lineTo(cx - 5.0, cy + 5.0)
                p_arr.closeSubpath()
                painter.fillPath(p_arr, QBrush(icon_color))
        elif self.icon_type == "search":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(int(cx - 1.5), int(cy - 1.5)), 4, 4)
            painter.drawLine(int(cx + 1.5), int(cy + 1.5), int(cx + 6), int(cy + 6))
        elif self.icon_type == "music":
            painter.setBrush(eff_icon_brush if theme != "light" else QBrush(icon_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(int(cx - 5), int(cy + 1), 4, 3)
            painter.drawEllipse(int(cx + 2), int(cy - 1), 4, 3)
            painter.setPen(eff_icon_pen if theme != "light" else QPen(icon_color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(cx - 2), int(cy + 2), int(cx - 2), int(cy - 5))
            painter.drawLine(int(cx + 5), int(cy), int(cx + 5), int(cy - 7))
            painter.drawLine(int(cx - 2), int(cy - 5), int(cx + 5), int(cy - 7))
        elif self.icon_type in ("lens", "google_lens", "image_search", "camera"):
            # Material Symbols Outlined: 'image_search'
            lens_color = icon_color
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(lens_color, 1.45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

            # 1. Photo frame (top-left)
            frame_rect = QRectF(cx - 7.6, cy - 7.0, 11.2, 9.6)
            painter.drawRoundedRect(frame_rect, 1.8, 1.8)

            # 2. Sun dot inside frame
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(lens_color))
            painter.drawEllipse(QPointF(cx - 4.4, cy - 4.2), 1.2, 1.2)

            # 3. Mountain line inside frame
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(lens_color, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            mtn = QPainterPath()
            mtn.moveTo(cx - 7.2, cy + 1.0)
            mtn.lineTo(cx - 4.4, cy - 1.2)
            mtn.lineTo(cx - 2.2, cy + 0.8)
            mtn.lineTo(cx - 0.4, cy - 2.0)
            mtn.lineTo(cx + 3.0, cy + 1.0)
            painter.drawPath(mtn)

            # 4. Magnifying search glass in bottom-right corner
            glass_cx = cx + 3.8
            glass_cy = cy + 3.2
            glass_r = 3.2
            painter.setPen(QPen(lens_color, 1.45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(QPointF(glass_cx, glass_cy), glass_r, glass_r)
            # 45-degree angled handle
            painter.setPen(QPen(lens_color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(glass_cx + 2.2, glass_cy + 2.2), QPointF(glass_cx + 4.6, glass_cy + 4.6))
        elif self.icon_type in ("volume", "unmute"):
            from odd_icons import get_icons8_pixmap
            col_str = "#FFFFFF" if theme != "light" else "#18181B"
            i8_pix = get_icons8_pixmap("volume", color=col_str, size=16)
            if i8_pix and not i8_pix.isNull():
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                painter.drawPixmap(int(cx - i8_pix.width() / 2.0), int(cy - i8_pix.height() / 2.0), i8_pix)
            else:
                path = QPainterPath()
                path.moveTo(cx - 5, cy - 2.5)
                path.lineTo(cx - 2, cy - 2.5)
                path.lineTo(cx + 1.5, cy - 5.5)
                path.lineTo(cx + 1.5, cy + 5.5)
                path.lineTo(cx - 2, cy + 2.5)
                path.lineTo(cx - 5, cy + 2.5)
                path.closeSubpath()
                painter.fillPath(path, (eff_icon_brush if theme != "light" else QBrush(icon_color)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawArc(int(cx + 1), int(cy - 4), 6, 8, -50 * 16, 100 * 16)
        elif self.icon_type == "mute":
            from odd_icons import get_icons8_pixmap
            col_str = "#FFFFFF" if theme != "light" else "#18181B"
            i8_pix = get_icons8_pixmap("volume", color=col_str, size=16)
            if i8_pix and not i8_pix.isNull():
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                painter.drawPixmap(int(cx - i8_pix.width() / 2.0), int(cy - i8_pix.height() / 2.0), i8_pix)
                painter.setPen(QPen(icon_color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(int(cx - 6), int(cy + 6), int(cx + 6), int(cy - 6))
            else:
                path = QPainterPath()
                path.moveTo(cx - 5, cy - 2.5)
                path.lineTo(cx - 2, cy - 2.5)
                path.lineTo(cx + 1.5, cy - 5.5)
                path.lineTo(cx + 1.5, cy + 5.5)
                path.lineTo(cx - 2, cy + 2.5)
                path.lineTo(cx - 5, cy + 2.5)
                path.closeSubpath()
                painter.fillPath(path, (eff_icon_brush if theme != "light" else QBrush(icon_color)))
                painter.setPen(QPen(icon_color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(int(cx - 5), int(cy + 5), int(cx + 5), int(cy - 5))
        painter.restore()

    def _draw_animated_hamburger(self, painter, cx, cy, color):
        """
        Renders the Uiverse.io (by JulanDeAlb) animated hamburger-to-close toggle icon.
        Transition is dynamically animated via cubic easing as _hamburger_progress slides 0.0 -> 1.0.
        """
        p = max(0.0, min(1.0, float(getattr(self, "_hamburger_progress", 0.0))))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Scale 32x32 SVG viewBox to target button size (~16-18px)
        btn_min = min(float(self.width()), float(self.height()))
        scale = max(0.3, (btn_min * 0.60) / 32.0)
        painter.translate(cx, cy)
        painter.scale(scale, scale)
        painter.rotate(-45.0 * p)
        painter.translate(-16.0, -16.0)

        # Path: top & bottom lines with connecting spine loop
        path = QPainterPath()
        path.moveTo(27, 10)
        path.lineTo(13, 10)
        path.cubicTo(10.8, 10, 9, 8.2, 9, 6)
        path.cubicTo(9, 3.5, 10.8, 2, 13, 2)
        path.cubicTo(15.2, 2, 17, 3.8, 17, 6)
        path.lineTo(17, 26)
        path.cubicTo(17, 28.2, 18.8, 30, 21, 30)
        path.cubicTo(23.2, 30, 25, 28.2, 25, 26)
        path.cubicTo(25, 23.8, 23.2, 22, 21, 22)
        path.lineTo(7, 22)

        # Interpolate stroke-dasharray and stroke-dashoffset:
        # Unchecked: stroke-dasharray: 12 63 (normalized to stroke width 3.0: 4.0, 21.0), offset: 0
        # Checked: stroke-dasharray: 20 300 (normalized to stroke width 3.0: 20/3, 100.0), offset: -32.42/3
        dash_len = (12.0 + (20.0 - 12.0) * p) / 3.0
        gap_len = (63.0 + (300.0 - 63.0) * p) / 3.0
        dash_offset = (-32.42 * p) / 3.0

        pen_dashed = QPen(color, 3.0, Qt.PenStyle.CustomDashLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        pen_dashed.setDashPattern([dash_len, gap_len])
        pen_dashed.setDashOffset(dash_offset)
        painter.setPen(pen_dashed)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Middle horizontal line: (7, 16) to (27, 16)
        pen_solid = QPen(color, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen_solid)
        painter.drawLine(QPointF(7, 16), QPointF(27, 16))

        painter.restore()


class MediaSourceItemWidget(QWidget):
    """Row representing an individual active media session across apps or browser tabs (Monochrome)"""
    def __init__(self, session_data: dict, is_selected: bool = False, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.session_data = session_data or {}
        self.is_selected = is_selected
        self.theme = theme
        self.is_hovered = False
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        title = str(self.session_data.get("title") or "Media Track").strip()
        artist = str(self.session_data.get("artist") or "").strip()
        app_name = str(self.session_data.get("app_name") or "Media Player").strip()
        tip_lines = [title]
        if artist:
            tip_lines.append(artist)
        tip_lines.append(f"Source: {app_name}")
        self.setToolTip("\n".join(tip_lines))

    def sizeHint(self):
        return QSize(440, 46)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.is_hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.is_hovered = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._draw_source_item(painter)
        finally:
            if painter.isActive():
                painter.end()

    def _draw_source_item(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = self.rect().adjusted(2, 2, -2, -2)
        theme = str(self.theme).lower()

        if self.is_selected or self.is_hovered:
            if theme == "light":
                bg = QColor(0, 0, 0, 18 if self.is_selected else 10)
                border = QColor(0, 0, 0, 28 if self.is_selected else 14)
            else:
                bg = QColor(255, 255, 255, 26 if self.is_selected else 14)
                border = QColor(255, 255, 255, 45 if self.is_selected else 22)
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(QRectF(rect), 8.0, 8.0)

        # 1. Left App Badge (fits full names like "Apple Music", "Spotify", "Chrome")
        raw_app = str(self.session_data.get("app_name") or "Media").strip()
        short_app = raw_app.replace("Google ", "").replace("Microsoft ", "").replace(" Player", "").strip() or "Media"
        badge_font = QFont("Segoe UI Variable Display", 7.5, QFont.Weight.Bold)
        fm_badge = QFontMetrics(badge_font)
        badge_w = max(58, min(92, fm_badge.horizontalAdvance(short_app) + 16))
        badge_h = 22
        badge_x = rect.left() + 8
        badge_y = rect.top() + (rect.height() - badge_h) // 2
        badge_rect = QRectF(badge_x, badge_y, badge_w, badge_h)

        if theme == "light":
            badge_bg = QColor(0, 0, 0, 16)
            badge_border = QColor(0, 0, 0, 32)
            badge_fg = QColor("#171717")
        else:
            badge_bg = QColor(255, 255, 255, 22)
            badge_border = QColor(255, 255, 255, 38)
            badge_fg = QColor("#FFFFFF")

        painter.setBrush(QBrush(badge_bg))
        painter.setPen(QPen(badge_border, 1.0))
        painter.drawRoundedRect(badge_rect, 6.0, 6.0)

        painter.setFont(badge_font)
        painter.setPen(badge_fg)
        badge_text = fm_badge.elidedText(short_app, Qt.TextElideMode.ElideRight, int(badge_w - 10))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # 2. Right Status Indicator ("PLAYING" / "PAUSED")
        is_playing = bool(self.session_data.get("is_playing", False))
        status_text = "PLAYING" if is_playing else "PAUSED"
        status_font = QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold)
        fm_status = QFontMetrics(status_font)
        status_text_w = fm_status.horizontalAdvance(status_text)
        dot_space = 10 if is_playing else 0
        status_total_w = status_text_w + dot_space + 6
        status_right = rect.right() - 10
        status_left = status_right - status_total_w

        if is_playing:
            status_col = QColor("#171717") if theme == "light" else QColor("#FFFFFF")
            dot_cy = rect.center().y()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(status_col))
            painter.drawEllipse(QPointF(status_left + 3.0, dot_cy), 2.5, 2.5)
        else:
            status_col = QColor("#737373") if theme == "light" else QColor(255, 255, 255, 130)

        painter.setFont(status_font)
        painter.setPen(status_col)
        status_rect = QRectF(status_left + dot_space, rect.top(), status_text_w + 6, rect.height())
        painter.drawText(status_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, status_text)

        # 3. Center Title & Artist with strict elision so long text never overflows
        text_left = int(badge_rect.right()) + 10
        avail_w = max(60, int(status_left - text_left - 10))

        title = str(self.session_data.get("title") or "Media Track").strip()
        artist = str(self.session_data.get("artist") or "").strip()

        title_font = QFont("Segoe UI Variable Text", 9, QFont.Weight.DemiBold)
        fm_title = QFontMetrics(title_font)
        elided_title = fm_title.elidedText(title, Qt.TextElideMode.ElideRight, avail_w)
        title_col = QColor("#171717") if theme == "light" else QColor("#FFFFFF")

        if artist:
            painter.setFont(title_font)
            painter.setPen(title_col)
            title_rect = QRectF(text_left, rect.top() + 4, avail_w, 19)
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

            sub_font = QFont("Segoe UI Variable Text", 8)
            fm_sub = QFontMetrics(sub_font)
            elided_artist = fm_sub.elidedText(artist, Qt.TextElideMode.ElideRight, avail_w)
            sub_col = QColor("#737373") if theme == "light" else QColor(255, 255, 255, 175)
            painter.setFont(sub_font)
            painter.setPen(sub_col)
            sub_rect = QRectF(text_left, rect.top() + 22, avail_w, 17)
            painter.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_artist)
        else:
            painter.setFont(title_font)
            painter.setPen(title_col)
            title_rect = QRectF(text_left, rect.top(), avail_w, rect.height())
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)


def format_time_seconds(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    s = int(seconds)
    mins = s // 60
    secs = s % 60
    return f"{mins}:{secs:02d}"


class MediaSeekBar(QWidget):
    """
    Sleek interactive timeline scrubber for live media.
    Supports click-to-seek, drag-to-seek, hover timestamps, and smooth progress track rendering.
    """
    seek_requested = Signal(float)  # Requested position in seconds

    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.duration_sec = 0.0
        self.position_sec = 0.0
        self.is_dragging = False
        self.drag_position_sec = 0.0
        self.is_hovered = False
        self.hover_pos_x = 0.0
        self.setFixedHeight(18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def set_duration(self, duration_sec: float):
        self.duration_sec = max(0.0, float(duration_sec))
        self.update()

    def set_position(self, position_sec: float):
        if not self.is_dragging:
            self.position_sec = max(0.0, min(self.duration_sec, float(position_sec))) if self.duration_sec > 0 else max(0.0, float(position_sec))
            self.update()

    def _get_sec_from_x(self, x: float) -> float:
        margin = 6
        usable_w = max(1, self.width() - 2 * margin)
        ratio = max(0.0, min(1.0, (x - margin) / float(usable_w)))
        return ratio * self.duration_sec

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        if self.duration_sec <= 0:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        if delta != 0:
            # Scroll step: 5 seconds per standard 120 wheel tick
            step = 5.0 * (delta / 120.0)
            curr = self.drag_position_sec if self.is_dragging else self.position_sec
            target = max(0.0, min(self.duration_sec, curr + step))
            self.position_sec = target
            self.drag_position_sec = target
            self.seek_requested.emit(target)
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseMoveEvent(self, event):
        self.hover_pos_x = event.position().x() if hasattr(event, 'position') else event.x()
        if self.is_dragging and self.duration_sec > 0:
            self.drag_position_sec = self._get_sec_from_x(self.hover_pos_x)
            self.position_sec = self.drag_position_sec
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.duration_sec > 0:
            self.is_dragging = True
            pos_x = event.position().x() if hasattr(event, 'position') else event.x()
            self.drag_position_sec = self._get_sec_from_x(pos_x)
            self.position_sec = self.drag_position_sec
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_dragging:
            self.is_dragging = False
            pos_x = event.position().x() if hasattr(event, 'position') else event.x()
            target_sec = self._get_sec_from_x(pos_x)
            self.position_sec = target_sec
            self.drag_position_sec = target_sec
            self.seek_requested.emit(target_sec)
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        theme = str(self.theme).lower()
        margin = 6
        track_w = max(1.0, float(self.width() - 2 * margin))
        is_active = (self.is_hovered or self.is_dragging)
        track_h = 5.0 if is_active else 3.5
        track_y = (self.height() - track_h) / 2.0
        r_track = track_h / 2.0

        # Background track: ultra-clean Apple translucent pill
        bg_col = QColor(0, 0, 0, 25) if theme == "light" else QColor(255, 255, 255, 42)
        painter.setBrush(QBrush(bg_col))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(margin, track_y, track_w, track_h), r_track, r_track)

        curr_sec = self.drag_position_sec if self.is_dragging else self.position_sec
        ratio = (curr_sec / self.duration_sec) if self.duration_sec > 0 else 0.0
        ratio = max(0.0, min(1.0, ratio))
        fill_w = track_w * ratio

        # Progress fill
        if fill_w > 0:
            if theme == "light":
                fill_color = QColor(24, 24, 28, 230)
            else:
                fill_color = QColor(255, 255, 255, 230)
            
            painter.setBrush(QBrush(fill_color))
            painter.drawRoundedRect(QRectF(margin, track_y, max(track_h, fill_w), track_h), r_track, r_track)

        # Scrubber Thumb (Apple Music signature expanding handle)
        if self.duration_sec > 0:
            thumb_x = margin + fill_w
            thumb_y = self.height() / 2.0
            thumb_r = 5.5 if is_active else 3.2
            
            if self.is_dragging:
                painter.setBrush(QBrush(QColor(255, 255, 255, 40)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(thumb_x, thumb_y), thumb_r + 4.0, thumb_r + 4.0)

            painter.setBrush(QBrush(QColor(255, 255, 255) if theme != "light" else QColor(20, 20, 24)))
            painter.setPen(QPen(QColor(0, 0, 0, 60) if theme != "light" else QColor(255, 255, 255, 80), 0.8))
            painter.drawEllipse(QPointF(thumb_x, thumb_y), thumb_r, thumb_r)


class LiveEqVisualizerWidget(QWidget):
    """Dynamic 4-bar dancing EQ waveform visualizer for Apple Music controls"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 14)
        self.phase = 0.0
        self.is_playing = False
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(40)
        self.anim_timer.timeout.connect(self._on_tick)

    def set_playing(self, is_playing: bool):
        self.is_playing = is_playing
        if is_playing:
            if not self.anim_timer.isActive():
                self.anim_timer.start()
        else:
            self.anim_timer.stop()
        self.update()

    def _on_tick(self):
        self.phase += 0.28
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        col = QColor(255, 255, 255, 220)
        painter.setBrush(QBrush(col))

        for i in range(4):
            if self.is_playing:
                h = max(2.5, 3.0 + 8.5 * (math.sin(self.phase + i * 1.25) ** 2))
            else:
                h = 2.5
            bx = 1.0 + i * 5.2
            by = (self.height() - h) / 2.0
            painter.drawRoundedRect(QRectF(bx, by, 2.8, h), 1.4, 1.4)


class VinylDiscThumbnailWidget(QWidget):
    """
    Apple Music Squircle Artwork & Vinyl Disc widget.
    Features continuous rounded squircle corners, specular glass rim, and smooth subtle breathing when playing.
    """
    def __init__(self, size=(46, 46), style="squircle", parent=None):
        super().__init__(parent)
        self.setFixedSize(size[0], size[1])
        self.style = style  # "squircle" or "vinyl"
        self.thumb_pixmap = None
        self.angle = 0.0
        self.pulse_phase = 0.0
        self.is_playing = False
        self.theme = "dark"

        self.rot_timer = QTimer(self)
        self.rot_timer.setInterval(35)
        self.rot_timer.timeout.connect(self._on_tick)

    def set_media_data(self, thumb_bytes: bytes, is_playing: bool, theme: str = "dark"):
        self.is_playing = is_playing
        self.theme = theme
        if thumb_bytes:
            pix = QPixmap()
            if pix.loadFromData(thumb_bytes):
                self.thumb_pixmap = pix
            else:
                self.thumb_pixmap = None
        else:
            self.thumb_pixmap = None

        if self.is_playing:
            if not self.rot_timer.isActive():
                self.rot_timer.start()
        else:
            self.rot_timer.stop()
        self.update()

    def _on_tick(self):
        if self.is_playing:
            self.angle = (self.angle + 2.0) % 360.0
            self.pulse_phase += 0.08
            self.update()

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            w = float(self.width())
            h = float(self.height())
            cx, cy = w / 2.0, h / 2.0

            if self.style == "squircle":
                # Apple Music squircle artwork with subtle breathing pulse
                scale = (1.0 + 0.016 * math.sin(self.pulse_phase)) if self.is_playing else 1.0
                painter.save()
                painter.translate(cx, cy)
                painter.scale(scale, scale)
                painter.translate(-cx, -cy)

                rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
                r = 10.0
                path = QPainterPath()
                path.addRoundedRect(rect, r, r)

                # Thumbnail Artwork or Fallback Gradient
                drawn_art = False
                if self.thumb_pixmap and not self.thumb_pixmap.isNull():
                    scaled = self.thumb_pixmap.scaled(
                        int(w), int(h),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    painter.save()
                    painter.setClipPath(path)
                    painter.drawPixmap(0, 0, scaled)
                    painter.restore()
                    drawn_art = True

                if not drawn_art:
                    grad = QLinearGradient(0, 0, w, h)
                    grad.setColorAt(0.0, QColor(38, 42, 54, 240))
                    grad.setColorAt(1.0, QColor(18, 20, 26, 240))
                    painter.fillPath(path, QBrush(grad))

                    # Vector music notes
                    painter.setBrush(QBrush(QColor(255, 255, 255, 180)))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(QPointF(cx - 5.0, cy + 3.0), 3.0, 2.5)
                    painter.drawEllipse(QPointF(cx + 4.0, cy + 1.0), 3.0, 2.5)
                    painter.setPen(QPen(QColor(255, 255, 255, 180), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    painter.drawLine(QPointF(cx - 2.5, cy + 3.0), QPointF(cx - 2.5, cy - 5.0))
                    painter.drawLine(QPointF(cx + 6.5, cy + 1.0), QPointF(cx + 6.5, cy - 7.0))
                    painter.drawLine(QPointF(cx - 2.5, cy - 5.0), QPointF(cx + 6.5, cy - 7.0))

                # Apple glass specular rim highlight
                painter.strokePath(path, QPen(QColor(255, 255, 255, 30), 1.0))
                painter.restore()
            else:
                # Rotating Vinyl Record Disc
                r = min(w, h) / 2.0 - 1.0
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(self.angle)

                painter.setBrush(QBrush(QColor(16, 16, 18)))
                painter.setPen(QPen(QColor(55, 55, 60), 1.0))
                painter.drawEllipse(QPointF(0, 0), r, r)

                # Grooves
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(255, 255, 255, 20), 0.8))
                painter.drawEllipse(QPointF(0, 0), r - 4, r - 4)
                painter.drawEllipse(QPointF(0, 0), r - 8, r - 8)
                painter.drawEllipse(QPointF(0, 0), r - 12, r - 12)

                # Center Label
                label_r = r * 0.46
                drawn_label = False
                if self.thumb_pixmap and not self.thumb_pixmap.isNull():
                    scaled = self.thumb_pixmap.scaled(int(label_r * 2), int(label_r * 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                    path = QPainterPath()
                    path.addEllipse(QPointF(0, 0), label_r, label_r)
                    painter.save()
                    painter.setClipPath(path)
                    painter.drawPixmap(int(-label_r), int(-label_r), scaled)
                    painter.restore()
                    drawn_label = True

                if not drawn_label:
                    painter.setBrush(QBrush(QColor("#00E5FF")))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(QPointF(0, 0), label_r, label_r)

                # Spindle
                painter.setBrush(QBrush(QColor(10, 10, 12)))
                painter.setPen(QPen(QColor(255, 255, 255, 100), 0.8))
                painter.drawEllipse(QPointF(0, 0), 2.5, 2.5)

                painter.restore()
        except Exception:
            pass


class OddHeaderPillButton(QPushButton):
    """Button in Music player header with official ODD logo to open ODD search window"""
    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(66, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Open ODD Search Window (Esc / Tab)")
        self.pixmap = get_odd_logo_pixmap((15, 15), self.theme)

    def set_theme(self, theme: str):
        self.theme = theme
        self.pixmap = get_odd_logo_pixmap((15, 15), self.theme)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        is_hover = self.underMouse()
        theme = str(self.theme).lower()

        if theme == "light":
            bg = QColor(0, 0, 0, 22) if is_hover else QColor(0, 0, 0, 10)
            border = QColor(0, 0, 0, 36) if is_hover else QColor(0, 0, 0, 18)
            text_col = QColor(18, 18, 18)
        elif theme == "oled":
            bg = QColor(255, 255, 255, 25) if is_hover else QColor(0, 0, 0, 255)
            border = QColor(255, 255, 255, 60) if is_hover else QColor(255, 255, 255, 30)
            text_col = QColor(255, 255, 255)
        else: # dark
            bg = QColor(255, 255, 255, 28) if is_hover else QColor(255, 255, 255, 12)
            border = QColor(255, 255, 255, 45) if is_hover else QColor(255, 255, 255, 20)
            text_col = QColor(255, 255, 255, 230)

        path = QPainterPath()
        path.addRoundedRect(rect, 13, 13)
        painter.fillPath(path, QBrush(bg))
        painter.strokePath(path, QPen(border, 1.0))

        # Draw logo icon (auto negative black in light theme, white in dark/oled)
        if self.pixmap and not self.pixmap.isNull():
            painter.drawPixmap(8, (self.height() - 15) // 2, self.pixmap)
            text_x = 28
        else:
            text_x = 10

        painter.setFont(QFont("Segoe UI Variable Display", 8, QFont.Weight.Bold))
        painter.setPen(text_col)
        painter.drawText(QRect(text_x, 0, self.width() - text_x - 4, self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "ODD")


class MusicCapsuleBar(QWidget):
    """Refined Dynamic Island Notch Music Player card with interactive live seekbar"""
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self.duration_sec = 0.0
        self.position_sec = 0.0
        self.last_updated_time = 0.0
        self.is_playing = False
        self._raw_title = "No Media Playing"
        self._raw_artist = "Windows Media"
        self._raw_app = "Media"
        # Lock exact height so sibling cards (like sources_card) or spring transitions
        # can NEVER vertically crush Row 1 / Row 2 / Row 3 into overlapping each other.
        self.setFixedHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.init_ui()

        # Real-time timeline tick timer (updates seekbar smoothly without CPU load)
        self.timeline_timer = QTimer(self)
        self.timeline_timer.setInterval(250)
        self.timeline_timer.timeout.connect(self._on_timeline_tick)
        self.timeline_timer.start()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(4)

        # ----------------- ROW 1: Left Media Image + Center Top Title + Right Corner App & Overlay Button -----------------
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        # 1. Left Corner: Media Image (Apple Music squircle artwork or rotating vinyl)
        self.thumb_widget = VinylDiscThumbnailWidget(size=(50, 50), style="squircle", parent=self)
        top_row.addWidget(self.thumb_widget, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # 2. Center Top: Media Title & Artist (Centered)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(2, 0, 2, 0)
        text_layout.setSpacing(2)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.title_label = QLabel("No Media Playing", self)
        self.title_label.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.DemiBold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFixedHeight(20)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        text_layout.addWidget(self.title_label)

        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(6)
        source_row.addStretch(1)

        self.artist_label = QLabel("Windows Media", self)
        self.artist_label.setFont(QFont("Segoe UI Variable Text", 8.5))
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_label.setFixedHeight(18)
        source_row.addWidget(self.artist_label)

        # Animated live EQ waveform bars beside artist
        self.live_eq = LiveEqVisualizerWidget(parent=self)
        source_row.addWidget(self.live_eq)
        source_row.addStretch(1)

        text_layout.addLayout(source_row)
        top_row.addLayout(text_layout, stretch=1)

        # 3. Right Corner: Back Button + App of that media + Music/ODD Overlay Button
        right_corner = QHBoxLayout()
        right_corner.setContentsMargins(0, 0, 0, 0)
        right_corner.setSpacing(6)
        right_corner.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self.btn_back = QPushButton("← Back", self)
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
        self.btn_back.setFixedHeight(26)
        self.btn_back.setToolTip("Back to Search (Esc)")
        self.btn_back.clicked.connect(self.overlay.switch_to_search_mode)
        right_corner.addWidget(self.btn_back)

        self.btn_sources = QPushButton("MEDIA", self)
        self.btn_sources.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sources.setFont(QFont("Segoe UI Variable Text", 7.5, QFont.Weight.Bold))
        self.btn_sources.setFixedHeight(26)
        self.btn_sources.setToolTip("Active Media App — Click to view and switch media sources (S)")
        self.btn_sources.clicked.connect(self.overlay.toggle_media_sources_panel)
        right_corner.addWidget(self.btn_sources)

        self.btn_odd = OddHeaderPillButton(theme=self.theme, parent=self)
        self.btn_odd.setToolTip("Back to Search")
        self.btn_odd.clicked.connect(self.overlay.switch_to_search_mode)
        right_corner.addWidget(self.btn_odd)

        top_row.addLayout(right_corner)
        main_layout.addLayout(top_row)

        # ----------------- ROW 2: Interactive Seekbar & Timestamps -----------------
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(6)

        self.lbl_time_elapsed = QLabel("0:00", self)
        self.lbl_time_elapsed.setFont(QFont("Segoe UI Variable Text", 7.5))
        self.lbl_time_elapsed.setFixedSize(34, 16)
        self.lbl_time_elapsed.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self.lbl_time_elapsed)

        self.seekbar = MediaSeekBar(theme=self.theme, parent=self)
        self.seekbar.seek_requested.connect(self._on_seek_requested)
        progress_row.addWidget(self.seekbar, stretch=1)

        self.lbl_time_remaining = QLabel("-0:00", self)
        self.lbl_time_remaining.setFont(QFont("Segoe UI Variable Text", 7.5))
        self.lbl_time_remaining.setFixedSize(38, 16)
        self.lbl_time_remaining.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self.lbl_time_remaining)

        main_layout.addLayout(progress_row)

        # ----------------- ROW 3: Bottom Centered Media Control Buttons (A Little Big) -----------------
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(2, 0, 2, 0)
        controls_row.setSpacing(14)

        # Star button
        self.btn_star = MediaControlIconButton("star", theme=self.theme, size=(28, 28), parent=self)
        self.btn_star.setToolTip("Favorite Track")
        controls_row.addWidget(self.btn_star)

        controls_row.addStretch()

        # Prev (Skip backward - bigger 36x36)
        self.btn_prev = MediaControlIconButton("prev", theme=self.theme, size=(36, 36), parent=self)
        self.btn_prev.setToolTip("Previous Track (Left Arrow)")
        self.btn_prev.clicked.connect(self._on_prev_clicked)
        controls_row.addWidget(self.btn_prev)

        # Play / Pause (Prominent 44x44 centerpiece)
        self.btn_play_pause = MediaControlIconButton("play", theme=self.theme, size=(44, 44), parent=self)
        self.btn_play_pause.setToolTip("Play / Pause (Spacebar)")
        self.btn_play_pause.clicked.connect(self._on_play_pause_clicked)
        controls_row.addWidget(self.btn_play_pause)

        # Next (Skip forward - bigger 36x36)
        self.btn_next = MediaControlIconButton("next", theme=self.theme, size=(36, 36), parent=self)
        self.btn_next.setToolTip("Next Track (Right Arrow)")
        self.btn_next.clicked.connect(self._on_next_clicked)
        controls_row.addWidget(self.btn_next)

        controls_row.addStretch()

        # Audio Mute / Speaker Button
        self.btn_mute = MediaControlIconButton("volume", theme=self.theme, size=(28, 28), parent=self)
        self.btn_mute.setToolTip("Toggle Audio Mute (M)")
        self.btn_mute.clicked.connect(self._on_mute_clicked)
        controls_row.addWidget(self.btn_mute)

        main_layout.addLayout(controls_row)

    def _on_seek_requested(self, position_sec: float):
        self.position_sec = position_sec
        self.last_updated_time = time.time()
        self.seekbar.set_position(position_sec)
        self.overlay.media_mgr.seek_to(position_sec)
        self.lbl_time_elapsed.setText(format_time_seconds(position_sec))
        if self.duration_sec > 0:
            rem = max(0.0, self.duration_sec - position_sec)
            self.lbl_time_remaining.setText(f"-{format_time_seconds(rem)}")

    def _on_timeline_tick(self):
        if not self.overlay.is_open or self.overlay.capsule_mode != "music":
            return

        if self.seekbar.is_dragging:
            drag_sec = self.seekbar.drag_position_sec
            self.lbl_time_elapsed.setText(format_time_seconds(drag_sec))
            if self.duration_sec > 0:
                rem = max(0.0, self.duration_sec - drag_sec)
                self.lbl_time_remaining.setText(f"-{format_time_seconds(rem)}")
            return

        if self.is_playing:
            now = time.time()
            elapsed = now - self.last_updated_time if self.last_updated_time > 0 else 0.0
            live_pos = self.position_sec + elapsed
            if self.duration_sec > 0:
                live_pos = min(self.duration_sec, live_pos)
            self.seekbar.set_position(live_pos)
            self.lbl_time_elapsed.setText(format_time_seconds(live_pos))
            if self.duration_sec > 0:
                rem = max(0.0, self.duration_sec - live_pos)
                self.lbl_time_remaining.setText(f"-{format_time_seconds(rem)}")
            else:
                self.lbl_time_remaining.setText("Live")
        else:
            self.seekbar.set_position(self.position_sec)
            self.lbl_time_elapsed.setText(format_time_seconds(self.position_sec))
            if self.duration_sec > 0:
                rem = max(0.0, self.duration_sec - self.position_sec)
                self.lbl_time_remaining.setText(f"-{format_time_seconds(rem)}")

    def set_theme(self, theme: str):
        self.theme = theme
        self.apply_theme_styles()

    def apply_theme_styles(self):
        theme = str(getattr(self, "theme", self.overlay.get_current_theme())).lower()
        self.btn_star.set_theme(theme)
        self.btn_mute.set_theme(theme)
        self.btn_prev.set_theme(theme)
        self.btn_play_pause.set_theme(theme)
        self.btn_next.set_theme(theme)
        self.btn_odd.set_theme(theme)
        self.seekbar.set_theme(theme)

        if theme == "light":
            self.title_label.setStyleSheet("color: #171717;")
            self.artist_label.setStyleSheet("color: #737373;")
            self.lbl_time_elapsed.setStyleSheet("color: #737373;")
            self.lbl_time_remaining.setStyleSheet("color: #737373;")
            if hasattr(self, 'btn_back'):
                self.btn_back.setStyleSheet("""
                    QPushButton {
                        background: rgba(0, 0, 0, 0.08);
                        color: #171717;
                        border: 1px solid rgba(0, 0, 0, 0.14);
                        border-radius: 12px;
                        padding: 2px 10px;
                        font-size: 8px;
                        font-weight: bold;
                        outline: none;
                    }
                    QPushButton:hover {
                        background: rgba(0, 0, 0, 0.16);
                    }
                """)
            self.btn_sources.setStyleSheet("""
                QPushButton {
                    background: rgba(0, 0, 0, 0.08);
                    color: #171717;
                    border: 1px solid rgba(0, 0, 0, 0.14);
                    border-radius: 12px;
                    padding: 2px 9px;
                    font-size: 8px;
                    font-weight: bold;
                    letter-spacing: 0.4px;
                    outline: none;
                }
                QPushButton:hover {
                    background: rgba(0, 0, 0, 0.16);
                }
            """)
        else:
            self.title_label.setStyleSheet("color: #FFFFFF;")
            self.artist_label.setStyleSheet("color: rgba(255, 255, 255, 0.70);")
            self.lbl_time_elapsed.setStyleSheet("color: rgba(255, 255, 255, 0.60);")
            self.lbl_time_remaining.setStyleSheet("color: rgba(255, 255, 255, 0.60);")
            if hasattr(self, 'btn_back'):
                self.btn_back.setStyleSheet("""
                    QPushButton {
                        background: rgba(255, 255, 255, 0.12);
                        color: #FFFFFF;
                        border: 1px solid rgba(255, 255, 255, 0.20);
                        border-radius: 12px;
                        padding: 2px 10px;
                        font-size: 8px;
                        font-weight: bold;
                        outline: none;
                    }
                    QPushButton:hover {
                        background: rgba(255, 255, 255, 0.24);
                        border: 1px solid rgba(255, 255, 255, 0.35);
                    }
                """)
            self.btn_sources.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.10);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.16);
                    border-radius: 12px;
                    padding: 2px 9px;
                    font-size: 8px;
                    font-weight: bold;
                    letter-spacing: 0.4px;
                    outline: none;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.20);
                    border: 1px solid rgba(255, 255, 255, 0.30);
                }
            """)

    def _update_elided_labels(self):
        """Dynamically elides title and artist based on actual available width between thumbnail and right buttons."""
        card_w = self.width() if self.width() > 260 else getattr(self.overlay, "capsule_width_expanded", 480)
        src_w = max(62, self.btn_sources.sizeHint().width())
        back_w = max(55, self.btn_back.sizeHint().width()) if hasattr(self, 'btn_back') else 55
        # Left = 14 margin + 50 thumb + 10 spacing = 74
        # Right = 14 margin + 56 ODD pill + 6 spacing + src_w + 6 spacing + back_w + 10 spacing = 92 + src_w + back_w
        avail_title_w = max(80, card_w - 74 - (92 + src_w + back_w))
        avail_artist_w = max(70, avail_title_w - 28)

        metrics = self.title_label.fontMetrics()
        elided_title = metrics.elidedText(self._raw_title, Qt.TextElideMode.ElideRight, avail_title_w)
        self.title_label.setText(elided_title)
        self.title_label.setToolTip(f"{self._raw_title}\n{self._raw_artist} ({self._raw_app})")

        metrics_a = self.artist_label.fontMetrics()
        elided_artist = metrics_a.elidedText(self._raw_artist, Qt.TextElideMode.ElideRight, avail_artist_w)
        self.artist_label.setText(elided_artist)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_labels()

    def update_state(self, state: dict):
        title = (state.get("title", "") or "No Media Playing").strip()
        app_disp = (state.get("app_display_name", "") or "Media").strip()
        artist = (state.get("artist", "") or app_disp).strip()
        self.is_playing = bool(state.get("is_playing", False))
        is_muted = bool(state.get("is_muted", False))
        sessions = state.get("available_sessions", [])
        thumb_bytes = state.get("thumbnail_bytes", None)

        self._raw_title = title
        self._raw_artist = artist
        self._raw_app = app_disp

        self.duration_sec = float(state.get("duration_sec", 0.0) or 0.0)
        self.position_sec = float(state.get("position_sec", 0.0) or 0.0)
        self.last_updated_time = float(state.get("last_updated_time", time.time()) or time.time())

        self.seekbar.set_duration(self.duration_sec)
        self.seekbar.set_position(self.position_sec)

        count = len(sessions)
        app_short = app_disp.replace("Google ", "").replace("Microsoft ", "").replace(" Player", "").strip() or "Media"
        if count > 1:
            self.btn_sources.setText(f"{app_short[:13].upper()} • {count} v")
            self.btn_sources.show()
        elif count == 1:
            s_name = sessions[0].get("app_name", app_short).replace("Google ", "").replace("Microsoft ", "").replace(" Player", "").strip() or app_short
            self.btn_sources.setText(s_name[:14].upper())
            self.btn_sources.show()
        else:
            self.btn_sources.setText(app_short[:14].upper())
            self.btn_sources.show()

        self._update_elided_labels()

        self.btn_play_pause.set_icon_type("pause" if self.is_playing else "play")
        self.btn_mute.set_icon_type("mute" if is_muted else "volume")

        # Initial time display
        self.lbl_time_elapsed.setText(format_time_seconds(self.position_sec))
        if self.duration_sec > 0:
            rem = max(0.0, self.duration_sec - self.position_sec)
            self.lbl_time_remaining.setText(f"-{format_time_seconds(rem)}")
        else:
            self.lbl_time_remaining.setText("-0:00")

        self.thumb_widget.set_media_data(thumb_bytes, self.is_playing, theme=self.theme)
        if hasattr(self, 'live_eq'):
            self.live_eq.set_playing(self.is_playing)

    def paintEvent(self, event):
        # Outer continuous acrylic surface is painted by IslandSurfaceContainer (self.pill_column)
        return

    def _on_mute_clicked(self):
        try:
            import odd_sound
            odd_sound.play_mute_sound(not getattr(self.overlay.media_mgr, "_is_muted", False), self.overlay.settings)
        except Exception:
            pass
        self.overlay.media_mgr.toggle_master_mute()

    def _on_play_pause_clicked(self):
        self.overlay.media_mgr.toggle_play_pause()

    def _on_prev_clicked(self):
        self.overlay.media_mgr.previous_track()

    def _on_next_clicked(self):
        self.overlay.media_mgr.next_track()


class OddLogoButton(QPushButton):
    """
    Settings / ODD Logo Button:
    - Sleek thin Liquid Metal border (1.0px, LiquidMetalButton style)
    - Crystal-clear, high-contrast crisp white ODD settings icon
    - High-response micro-interaction springs
    - Guaranteed fallback vector gear mark if pixmap is missing
    """
    def __init__(self, theme="dark", size=(56, 56), parent=None):
        super().__init__(parent)
        self.theme = theme
        self._opacity = 1.0
        self.setFixedSize(size[0], size[1])
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pixmap = get_odd_logo_pixmap((24, 24), self.theme)

        # Micro-interaction physics springs
        from odd_spring import SpringValue
        self.scale_spring = SpringValue(initial_value=1.0, response=0.08, damping_ratio=0.82)
        self.hover_spring = SpringValue(initial_value=0.0, response=0.08, damping_ratio=0.82)
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(8)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

    def set_opacity(self, opacity: float):
        op = max(0.0, min(1.0, float(opacity)))
        if abs(self._opacity - op) > 0.005:
            self._opacity = op
            self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.04, now - self._last_step)
        self._last_step = now
        self.scale_spring.update(dt)
        if hasattr(self, 'radius_spring'):
            self.radius_spring.update(dt)
        self._anim_phase += 0.06
        self.hover_spring.update(dt)
        self.update()
        if self.scale_spring.is_settled() and self.hover_spring.is_settled():
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.scale_spring.set_target(1.06, preserve_velocity=True)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._hover_pos = event.position() if hasattr(event, "position") else event.pos()
        self.update()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.scale_spring.set_target(0.94, preserve_velocity=True)
        self._wake_anim()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        target = 1.06 if self.underMouse() else 1.0
        self.scale_spring.set_target(target, preserve_velocity=True)
        self._wake_anim()

    def set_theme(self, theme: str):
        self.theme = theme
        self.pixmap = get_odd_logo_pixmap((24, 24), self.theme)
        self.update()

    def paintEvent(self, event):
        try:
            parent_op = getattr(self.parentWidget(), "_surface_opacity", 1.0) if self.parentWidget() else 1.0
            eff_op = max(0.0, min(1.0, self._opacity * float(parent_op)))
            if eff_op <= 0.01:
                return
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            cx = self.width() / 2.0
            cy = self.height() / 2.0
            s = self.scale_spring.value

            painter.save()
            painter.translate(cx, cy)
            painter.scale(s, s)
            painter.translate(-cx, -cy)

            # Adaptive transparent margin and squircle radius
            pad = 5.0 if self.width() >= 50 else 2.0
            rect = QRectF(pad, pad, self.width() - pad * 2.0, self.height() - pad * 2.0)
            r = min(rect.width(), rect.height()) / 2.0
            desired_logo_sz = min(24, max(14, int(min(rect.width(), rect.height()) * 0.68)))
            if self.pixmap.isNull() or abs(self.pixmap.width() - desired_logo_sz) > 2:
                self.pixmap = get_odd_logo_pixmap((desired_logo_sz, desired_logo_sz), self.theme)

            btn_path = QPainterPath()
            btn_path.addRoundedRect(rect, r, r)

            theme = str(self.theme).lower()
            h_val = max(0.0, min(1.0, self.hover_spring.value))
            pr_val = 1.0 if self.isDown() else 0.0

            # 1. Base acrylic / glass surface
            odd_blur.ODDOverlaySurface.paint_glass_surface(
                painter,
                rect,
                r,
                theme=theme,
                opacity=eff_op,
                hover_val=h_val,
                press_val=pr_val,
                hover_pos=None,
                hover_color=QColor(255, 255, 255) if theme != "light" else QColor(220, 220, 220),
            )

            # 2. Restrained 0.8px #292929 border & solid surface handled in paint_glass_surface
            # (Zero spinning chrome gradients; pure Apple & Teenage Engineering minimalism)
            # 3. Direct, high-contrast, crystal-clear ODD Settings Logo
            logo_pix = self.pixmap
            if not logo_pix or logo_pix.isNull():
                self.pixmap = get_odd_logo_pixmap((24, 24), self.theme)
                logo_pix = self.pixmap

            painter.save()
            painter.setClipping(False)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setOpacity(eff_op)

            if logo_pix and not logo_pix.isNull():
                px = int(round(cx - logo_pix.width() / 2.0))
                py = int(round(cy - logo_pix.height() / 2.0))
                painter.drawPixmap(px, py, logo_pix)
            else:
                # Guaranteed high-precision vector settings gear fallback
                icon_col = QColor(255, 255, 255, int(245 * eff_op)) if theme != "light" else QColor(18, 18, 18, int(245 * eff_op))
                rot = (self._anim_phase * 60.0) % 360.0
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(rot)
                gear = QPainterPath()
                n_teeth = 8
                r_outer = 11.0
                r_inner = 8.5
                r_hole = 4.2
                for i in range(n_teeth):
                    angle_center = i * (2.0 * math.pi / n_teeth)
                    step = (2.0 * math.pi / n_teeth)
                    tooth_half = step * 0.22
                    valley_half = step * 0.28
                    a1 = angle_center - tooth_half
                    a2 = angle_center + tooth_half
                    a3 = angle_center + step - valley_half
                    if i == 0:
                        gear.moveTo(r_inner * math.cos(a1), r_inner * math.sin(a1))
                    gear.lineTo(r_outer * math.cos(a1), r_outer * math.sin(a1))
                    gear.lineTo(r_outer * math.cos(a2), r_outer * math.sin(a2))
                    gear.lineTo(r_inner * math.cos(a2), r_inner * math.sin(a2))
                    gear.lineTo(r_inner * math.cos(a3), r_inner * math.sin(a3))
                gear.closeSubpath()
                hole = QPainterPath()
                hole.addEllipse(QPointF(0.0, 0.0), r_hole, r_hole)
                gear = gear.subtracted(hole)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(icon_col))
                painter.fillPath(gear, QBrush(icon_col))
                painter.restore()

            painter.restore() # restore logo state

            painter.restore() # restore scale state
            painter.end()
        except Exception:
            pass


class MinimalMusicBar(QWidget):
    """Semi-transparent music overlay shown directly below the ODD search pill"""
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self.setFixedHeight(84)
        self.setMouseTracking(True)
        self.current_info = {"title": "No Media Playing", "artist": "", "app_display_name": "Media", "is_playing": False, "thumbnail": b""}
        self._thumb_pixmap = None

        from odd_spring import SpringValue
        self.hover_spring = SpringValue(initial_value=0.0, response=0.18, damping_ratio=0.82)
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(12)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

        self.init_ui()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.04, now - self._last_step)
        self._last_step = now
        self.hover_spring.update(dt)
        self.update()
        if self.hover_spring.is_settled():
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()
        if getattr(self, '_use_anim_player', None):
            self._use_anim_player.handle_hover_enter()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()

    def init_ui(self):
        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(12, 8, 10, 8)
        outer_layout.setSpacing(10)

        # 1. Left Corner: Media Image / Album Artwork (56x56 rounded squircle)
        self.art_btn = QPushButton(self)
        self.art_btn.setFixedSize(56, 56)
        self.art_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.art_btn.setToolTip("Expand Full Music Player")
        self.art_btn.setStyleSheet("background: transparent; border: none;")
        self.art_btn.clicked.connect(self.overlay.switch_to_music_mode)
        outer_layout.addWidget(self.art_btn, alignment=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        # 2. Right Column: Top Row (Center Top Title + Right Corner App & Buttons) + Bottom Row (Centered Big Media Controls)
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(4)

        # --- TOP ROW: Center Top Title + Right Corner (App of Media + Music Overlay Button + Close 'X' Button) ---
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(5)

        self.title_lbl = QLabel("No Media Playing", self)
        self.title_lbl.setFont(QFont("Segoe UI Variable Display", 9.5, QFont.Weight.DemiBold))
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        top_row.addWidget(self.title_lbl, stretch=1)

        # Right Corner: App of that media badge
        self.app_badge_btn = QPushButton("Media", self)
        self.app_badge_btn.setFixedHeight(20)
        self.app_badge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.app_badge_btn.setFont(QFont("Segoe UI Variable Text", 7.5, QFont.Weight.DemiBold))
        self.app_badge_btn.setToolTip("Media Source App — Click to open Full Music Player")
        self.app_badge_btn.clicked.connect(self.overlay.switch_to_music_mode)
        top_row.addWidget(self.app_badge_btn, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Right Corner: Our Music Overlay Button
        self.btn_expand = MediaControlIconButton("waveform", theme=self.theme, size=(24, 24), parent=self)
        self.btn_expand.setToolTip("Open Full Music Overlay")
        self.btn_expand.clicked.connect(self.overlay.switch_to_music_mode)
        top_row.addWidget(self.btn_expand, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Right Corner: Close '✕' Button (to dismiss minimal music overlay when paused or anytime)
        self.btn_close = MediaControlIconButton("close", theme=self.theme, size=(24, 24), parent=self)
        self.btn_close.setToolTip("Close Music Overlay")
        self.btn_close.clicked.connect(self._on_close_clicked)
        top_row.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        right_col.addLayout(top_row)

        # --- BOTTOM ROW: Bottom Centered Media Control Buttons (A Little Big) ---
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 42, 0)
        bottom_row.setSpacing(12)
        bottom_row.addStretch(1)

        self.btn_prev = MediaControlIconButton("prev", theme=self.theme, size=(34, 34), parent=self)
        self.btn_prev.setToolTip("Previous Track")
        self.btn_prev.clicked.connect(lambda: self.overlay.media_mgr.previous_track())
        bottom_row.addWidget(self.btn_prev)

        self.btn_play = MediaControlIconButton("play", theme=self.theme, size=(40, 40), parent=self)
        self.btn_play.setToolTip("Play / Pause")
        self.btn_play.clicked.connect(self._on_play_clicked)
        bottom_row.addWidget(self.btn_play)

        self.btn_next = MediaControlIconButton("next", theme=self.theme, size=(34, 34), parent=self)
        self.btn_next.setToolTip("Next Track")
        self.btn_next.clicked.connect(lambda: self.overlay.media_mgr.next_track())
        bottom_row.addWidget(self.btn_next)

        bottom_row.addStretch(1)
        right_col.addLayout(bottom_row)

        outer_layout.addLayout(right_col, stretch=1)

        # Legacy artist_lbl reference for compatibility
        self.artist_lbl = QLabel("", self)
        self.artist_lbl.hide()

        self.set_theme(self.theme)

    def _on_close_clicked(self):
        self.overlay.dismiss_minimal_music_bar()

    def _on_play_clicked(self):
        self.overlay.media_mgr.toggle_play_pause()
        is_p = not bool(self.current_info.get("is_playing", False))
        self.current_info["is_playing"] = is_p
        self.btn_play.set_icon_type("pause" if is_p else "play")
        self.btn_play.setToolTip("Pause" if is_p else "Play")

    def mousePressEvent(self, event):
        pos = event.pos()
        for btn in (self.btn_prev, self.btn_play, self.btn_next, self.btn_expand, self.btn_close, self.app_badge_btn, self.art_btn):
            if btn.geometry().contains(pos):
                super().mousePressEvent(event)
                return

        if event.button() == Qt.MouseButton.LeftButton and hasattr(self, 'title_lbl') and self.title_lbl.geometry().contains(pos):
            self.overlay.switch_to_music_mode()
            event.accept()
            return

        super().mousePressEvent(event)

    def update_media_info(self, info: dict):
        self.current_info = dict(info) if info else {}
        title = str(self.current_info.get("title") or "No Media Playing").strip()
        artist = str(self.current_info.get("artist") or "").strip()
        app_name = str(self.current_info.get("app_display_name") or "").strip()
        if not app_name:
            sessions = self.current_info.get("available_sessions", [])
            if sessions:
                app_name = str(sessions[0].get("app_name") or "Media").strip()
            else:
                app_name = "Media"
        short_app = app_name.replace("Google ", "").replace("Microsoft ", "").replace(" Player", "").strip() or "Media"
        is_playing = bool(self.current_info.get("is_playing", False))

        self.app_badge_btn.setText(short_app[:14])
        self.app_badge_btn.setToolTip(f"Playing from {app_name} — Click to open Full Music Overlay")

        badge_w = max(48, self.app_badge_btn.sizeHint().width())
        avail_title_w = max(110, 205 - badge_w)
        fm_title = self.title_lbl.fontMetrics()
        self.title_lbl.setText(fm_title.elidedText(title, Qt.TextElideMode.ElideRight, avail_title_w))
        tip_parts = [title]
        if artist:
            tip_parts.append(artist)
        tip_parts.append(f"App: {app_name}")
        self.title_lbl.setToolTip("\n".join(tip_parts))

        self.btn_play.set_icon_type("pause" if is_playing else "play")
        self.btn_play.setToolTip("Pause" if is_playing else "Play")

        thumb_bytes = self.current_info.get("thumbnail_bytes") or self.current_info.get("thumbnail") or b""
        if thumb_bytes:
            pix = QPixmap()
            if pix.loadFromData(thumb_bytes):
                rounded = QPixmap(56, 56)
                rounded.fill(Qt.GlobalColor.transparent)
                p = QPainter(rounded)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                path = QPainterPath()
                path.addRoundedRect(0, 0, 56, 56, 12, 12)
                p.setClipPath(path)
                scaled = pix.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(0, 0, scaled)
                p.end()
                self._thumb_pixmap = rounded
            else:
                self._thumb_pixmap = None
        else:
            self._thumb_pixmap = None
        self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        is_light = str(theme).lower() == "light"
        title_col = "#121212" if is_light else "#F5F5F7"
        self.title_lbl.setStyleSheet(f"color: {title_col}; background: transparent; border: none;")
        if is_light:
            self.app_badge_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(0, 0, 0, 0.08);
                    color: #262626;
                    border: 1px solid rgba(0, 0, 0, 0.14);
                    border-radius: 10px;
                    padding: 1px 7px;
                    font-size: 8px;
                    font-weight: 600;
                    outline: none;
                }
                QPushButton:hover {
                    background: rgba(0, 0, 0, 0.15);
                }
            """)
        else:
            self.app_badge_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.10);
                    color: rgba(255, 255, 255, 0.90);
                    border: 1px solid rgba(255, 255, 255, 0.16);
                    border-radius: 10px;
                    padding: 1px 7px;
                    font-size: 8px;
                    font-weight: 600;
                    outline: none;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.20);
                    border: 1px solid rgba(255, 255, 255, 0.28);
                }
            """)
        for btn in (self.btn_prev, self.btn_play, self.btn_next, self.btn_expand, self.btn_close):
            btn.set_theme(theme)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        theme = str(self.theme).lower()
        art_rect = self.art_btn.geometry()
        badge_path = QPainterPath()
        badge_path.addRoundedRect(QRectF(art_rect), 12.0, 12.0)
        if self._thumb_pixmap and not self._thumb_pixmap.isNull():
            painter.drawPixmap(art_rect.topLeft(), self._thumb_pixmap)
            painter.strokePath(badge_path, QPen(QColor(255, 255, 255, 34) if theme != "light" else QColor(0, 0, 0, 24), 0.9))
        else:
            badge_bg = QColor(0, 0, 0, 22) if theme == "light" else QColor(255, 255, 255, 22)
            painter.fillPath(badge_path, QBrush(badge_bg))
            painter.strokePath(badge_path, QPen(QColor(255, 255, 255, 28) if theme != "light" else QColor(0, 0, 0, 20), 0.8))
            icon_col = QColor(34, 197, 94) if self.current_info.get("is_playing") else (
                QColor(24, 24, 28, 190) if theme == "light" else QColor(245, 245, 247, 200)
            )
            painter.setPen(QPen(icon_col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            cx, cy = art_rect.center().x(), art_rect.center().y()
            for dx, h in ((-8, 4), (-3, 9), (2, 6), (7, 3)):
                painter.drawLine(cx + dx, cy - h, cx + dx, cy + h)


class IslandSurfaceContainer(QWidget):
    """
    Single continuous physical AMOLED surface for the ODD Island (self.pill_column).
    Top-anchored continuous superellipse geometry with shape-aware hit testing.
    """
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(False)
        self.setMinimumWidth(0)
        self._anim_phase = 0.0

    def get_surface_path(self) -> QPainterPath:
        rect = QRectF(self.rect())
        if rect.width() <= 1.0 or rect.height() <= 1.0:
            return QPainterPath()
        from odd_theme import calculate_dynamic_squircle_radius, create_squircle_path
        r = calculate_dynamic_squircle_radius(rect.width(), rect.height())
        return create_squircle_path(rect, r)
        self._flow_timer = QTimer(self)
        self._flow_timer.setInterval(33)
        self._flow_timer.timeout.connect(self._on_flow_step)
        self._flow_timer.start()

    def _on_flow_step(self):
        self._anim_phase = (self._anim_phase + 0.04) % (math.pi * 20.0)
        if not self.isVisible() or not getattr(self.overlay, "is_open", False):
            return
        if getattr(self.overlay, "is_animating", False):
            # SpringEngine is already driving 60+ FPS animation frames; avoid redundant duplicate repaints
            return
        # During active typing, give 100% CPU/GPU headroom to search query & list rendering
        last_type = getattr(self.overlay, "last_typing_time", 0.0)
        if time.time() - last_type < 0.28:
            return
        self.update()

    def paintEvent(self, event):
        try:
            self._do_paint_event(event)
        except Exception:
            pass

    def _do_paint_event(self, event):
        if self.width() <= 2 or self.height() <= 2:
            return
        surf_op = float(getattr(self.overlay, "_surface_opacity", 1.0)) * float(getattr(self.overlay, "_pill_surface_opacity", 1.0))
        if surf_op <= 0.005:
            return
        painter = QPainter(self)
        try:
            self._draw_island_surface_content(painter, surf_op)
        finally:
            if painter.isActive():
                painter.end()

    def _draw_island_surface_content(self, painter, surf_op):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect())
        if rect.width() <= 1.0 or rect.height() <= 1.0:
            return
        from odd_theme import calculate_dynamic_squircle_radius
        r = calculate_dynamic_squircle_radius(rect.width(), rect.height())

        theme = str(self.overlay.get_current_theme()).lower()
        sp = getattr(self.overlay, "search_pill", None)
        h_val = sp.hover_spring.value if (sp is not None and sp.isVisible()) else 0.0
        p_val = sp.pulse_spring.value if (sp is not None and sp.isVisible()) else 0.0
        amb_col = None
        if self.overlay.capsule_mode == "music" or (getattr(self.overlay, "minimal_music_bar", None) is not None and not self.overlay.minimal_music_bar.isHidden()):
            amb_col = getattr(self.overlay, "ambient_music_color", None)

        refl_col = amb_col or (QColor(255, 255, 255) if theme != "light" else QColor(220, 220, 220))

        top_h = float(sp.height()) if sp is not None and sp.isVisible() else 48.0
        gap = 8.0
        side_mode = str(self.overlay.settings.get("side_view", "off")).lower()
        has_card = (
            side_mode not in ("left", "right") and (
                (hasattr(self.overlay, 'results_card') and self.overlay.results_card.isVisible()) or
                (hasattr(self.overlay, 'weather_card') and self.overlay.weather_card.isVisible()) or
                (hasattr(self.overlay, 'calendar_card') and self.overlay.calendar_card.isVisible()) or
                (hasattr(self.overlay, 'quick_settings_card') and self.overlay.quick_settings_card.isVisible()) or
                (hasattr(self.overlay, 'power_card') and self.overlay.power_card.isVisible()) or
                (self.height() > (top_h + 16.0))
            )
        )

        if has_card and sp is not None and sp.isVisible():
            # 1. Paint top search pill surface
            top_rect = QRectF(rect.left(), rect.top(), rect.width(), top_h)
            from odd_theme import calculate_dynamic_squircle_radius
            top_r = calculate_dynamic_squircle_radius(top_rect.width(), top_rect.height())
            odd_blur.ODDOverlaySurface.paint_glass_surface(
                painter,
                top_rect,
                top_r,
                theme=theme,
                opacity=surf_op,
                hover_val=h_val,
                pulse_val=p_val,
                hwnd=int(self.overlay.winId()),
                ambient_color=amb_col,
                hover_pos=None,
                hover_color=refl_col,
                surface_type="primary",
            )

            # 2. Paint bottom card surface with solid AMOLED glass and 8px floating transparent gap
            bottom_y = rect.top() + top_h + gap
            bottom_h = rect.bottom() - bottom_y
            if bottom_h > 12.0:
                bottom_rect = QRectF(rect.left(), bottom_y, rect.width(), bottom_h)
                bottom_r = 18.0
                odd_blur.ODDOverlaySurface.paint_glass_surface(
                    painter,
                    bottom_rect,
                    bottom_r,
                    theme=theme,
                    opacity=surf_op,
                    hover_val=0.0,
                    pulse_val=0.0,
                    hwnd=int(self.overlay.winId()),
                    ambient_color=amb_col,
                    hover_pos=None,
                    hover_color=refl_col,
                    surface_type="primary",
                )
        else:
            odd_blur.ODDOverlaySurface.paint_glass_surface(
                painter,
                rect,
                r,
                theme=theme,
                opacity=surf_op,
                hover_val=h_val,
                pulse_val=p_val,
                hwnd=int(self.overlay.winId()),
                ambient_color=amb_col,
                hover_pos=None,
                hover_color=refl_col,
                surface_type="primary",
            )

        # 2. Restrained 0.7px perimeter border & superellipse geometry handled cleanly in paint_glass_surface
        # (Zero spinning mercury / chrome gradients; pure Apple & Teenage Engineering minimalism)

        # 3. Subtle hairline divider beneath search field when card unfolds downward
        if sp is not None and sp.isVisible() and self.height() > 62:
            expand_t = max(0.0, min(1.0, (float(self.height()) - 58.0) / 24.0))
            div_y = 52.0
            div_alpha = int((22 if theme == "light" else 26) * expand_t * surf_op)
            if div_alpha > 1:
                div_col = QColor(0, 0, 0, div_alpha) if theme == "light" else QColor(255, 255, 255, div_alpha)
                painter.setPen(QPen(div_col, 0.8))
                painter.drawLine(QPointF(rect.left() + 14.0, div_y), QPointF(rect.right() - 14.0, div_y))

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        super().leaveEvent(event)


class SearchPillBar(QWidget):
    """Sleek rounded search pill with spring physics micro-interactions and tactile typing feedback.
    Supports both Classic (floating pill + standalone button) and Container (unified card with bottom dock) themes."""
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self.setFixedHeight(48)
        self.setMinimumWidth(0)
        self.setMouseTracking(True)
        self._content_progress = 1.0
        self._current_mode = None

        # Micro-interaction physics springs (120-180ms)
        from odd_spring import SpringValue
        self.hover_spring = SpringValue(initial_value=0.0, response=0.08, damping_ratio=0.82)
        self.pulse_spring = SpringValue(initial_value=0.0, response=0.07, damping_ratio=0.80)
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

        self.init_ui()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._forward_hover_pos(event.pos())

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        parent_surf = getattr(self.overlay, "pill_column", None)
        if parent_surf:
            parent_surf._hover_pos = None
            parent_surf.update()
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()

    def _forward_hover_pos(self, local_pos):
        if getattr(self.overlay, "capsule_mode", "") == "search":
            return
        parent_surf = getattr(self.overlay, "pill_column", None)
        if parent_surf:
            parent_surf._hover_pos = self.mapTo(parent_surf, local_pos)
            parent_surf.update()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove:
            if hasattr(event, "pos"):
                self._forward_hover_pos(watched.mapTo(self, event.pos()))
        return super().eventFilter(watched, event)

    def set_content_opacity(self, alpha: float):
        alpha = max(0.0, min(1.0, float(alpha)))
        if abs(self._content_progress - alpha) < 0.004 and (alpha not in (0.0, 1.0)):
            return
        self._content_progress = alpha
        if hasattr(self, "input") and self.input:
            if not self.input.isVisible():
                self.input.setVisible(True)
        for child_btn in (
            getattr(self, "btn_plus", None),
            getattr(self, "btn_quick", None),
            getattr(self, "btn_music", None),
            getattr(self, "btn_lens", None),
            getattr(self, "btn_weather", None),
            getattr(self, "btn_phone", None),
            getattr(self, "btn_odd_center", None),
            getattr(self, "search_icon", None),
        ):
            if child_btn is not None:
                child_btn.update()
        if hasattr(self, "btn_clear") and self.btn_clear:
            if alpha <= 0.05:
                self.btn_clear.hide()
            elif bool(self.input.text()):
                self.btn_clear.show()
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.04, now - self._last_step)
        self._last_step = now
        self.hover_spring.update(dt)
        self.pulse_spring.update(dt)
        self.update()
        if self.parentWidget():
            self.parentWidget().update()
        if self.hover_spring.is_settled() and self.pulse_spring.is_settled():
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def init_ui(self):
        self.btn_plus = None

        # 1. Text Input (Center)
        self.input = QLineEdit(self)
        self.input.setMinimumWidth(0)
        self.input.setPlaceholderText("Search apps, files, web (Win+Alt)...")
        self.input.setFont(QFont("Segoe UI Variable Text", 11, QFont.Weight.Normal))
        self.input.setMouseTracking(True)
        self.input.textChanged.connect(self._on_text_changed)

        # 2. Clear 'X' button (Appears when text is typed)
        self.btn_clear = QPushButton("✕", self)
        self.btn_clear.setFixedSize(16, 16)
        self.btn_clear.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setToolTip("Clear search")
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        self.btn_clear.hide()

        # 3. Magnifier vector icon (Used in Container Mode)
        self.search_icon = MediaControlIconButton("search", theme=self.theme, size=(18, 18), parent=self)
        self.search_icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.search_icon.setToolTip("Search")
        self.search_icon.clicked.connect(lambda: self.input.setFocus())

        # 4. Action buttons
        self.btn_quick = MediaControlIconButton("sliders", theme=self.theme, size=(28, 28), parent=self)
        self.btn_quick.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_quick.setToolTip("Quick Settings Overlay (Wi-Fi, Bluetooth, Audio, Screenshot)")
        self.btn_quick.clicked.connect(self.overlay.toggle_quick_settings_panel)

        self.btn_music = MediaControlIconButton("waveform", theme=self.theme, size=(28, 28), parent=self)
        self.btn_music.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_music.setToolTip("Music Overlay — View & Play Back Media")
        self.btn_music.clicked.connect(self.overlay.on_music_overlay_button_clicked)

        self.btn_lens = MediaControlIconButton("lens", theme=self.theme, size=(28, 28), parent=self)
        self.btn_lens.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_lens.setToolTip("Google Lens: select a screen region")
        self.btn_lens.clicked.connect(self._on_action_button_clicked)

        self.btn_weather = WeatherWidgetButton(theme=self.theme, parent=self)
        self.btn_weather.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_weather.clicked.connect(self.overlay.toggle_weather_panel)

        self.btn_phone = MediaControlIconButton("phone", theme=self.theme, size=(28, 28), parent=self)
        self.btn_phone.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_phone.setToolTip("Android Phone Mirror (Scrcpy 60FPS)")
        self.btn_phone.clicked.connect(self.overlay.on_phone_mirror_button_clicked)

        # 5. ODD Center Button (for Container bottom dock: prominent capsule with ODD settings logo)
        self.btn_odd_center = OddLogoButton(theme=self.theme, size=(44, 28), parent=self)
        self.btn_odd_center.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_odd_center.setToolTip("ODD Settings & Preferences")
        self.btn_odd_center.clicked.connect(self.overlay._open_settings_modal)

        # 6. Close '✕' Button (Fast 1-click dismissal)
        self.btn_close = MediaControlIconButton("close", theme=self.theme, size=(26, 26), parent=self)
        self.btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_close.setToolTip("Dismiss ODD (Esc / Click Outside / Shake Cursor)")
        self.btn_close.clicked.connect(self.overlay.sink)

        for w in (self.input, self.btn_quick, self.btn_music, self.btn_lens, self.btn_weather, self.btn_phone, self.btn_clear, self.btn_odd_center, self.search_icon, self.btn_close):
            if w is not None:
                w.installEventFilter(self)

        # Main Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Classic Mode Container
        self.classic_box = QWidget(self)
        self.classic_layout = QHBoxLayout(self.classic_box)
        self.classic_layout.setContentsMargins(14, 0, 8, 0)
        self.classic_layout.setSpacing(4)
        self.main_layout.addWidget(self.classic_box)

        # Container Mode Container (Height 96px, balanced 36px top search bar + 36px bottom dock)
        self.container_box = QWidget(self)
        self.container_layout = QVBoxLayout(self.container_box)
        self.container_layout.setContentsMargins(10, 8, 10, 8)
        self.container_layout.setSpacing(6)

        # Container Top Inset Search Pill (Pristine 36px pill)
        self.top_search_frame = QFrame(self.container_box)
        self.top_search_frame.setFixedHeight(36)
        self.top_search_layout = QHBoxLayout(self.top_search_frame)
        self.top_search_layout.setContentsMargins(12, 0, 10, 0)
        self.top_search_layout.setSpacing(8)
        self.top_search_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.container_layout.addWidget(self.top_search_frame)

        # Container Bottom Dock (36px high with vertically centered buttons)
        self.dock_frame = QWidget(self.container_box)
        self.dock_frame.setFixedHeight(36)
        self.dock_layout = QHBoxLayout(self.dock_frame)
        self.dock_layout.setContentsMargins(8, 0, 8, 0)
        self.dock_layout.setSpacing(0)
        self.dock_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.container_layout.addWidget(self.dock_frame)

        self.main_layout.addWidget(self.container_box)

        self.apply_layout_mode("classic")
        self.update_settings(self.overlay.settings)

    def apply_layout_mode(self, mode: str = None):
        if mode is None:
            mode = str(self.overlay.settings.get("ui_theme_style", "classic")).lower().strip()
        self._current_mode = mode
        is_light = (str(self.theme).lower() == "light")
        txt_col = "#1E1E1E" if is_light else "#FFFFFF"

        if mode == "container":
            # Reparent into Container sub-frames
            self.top_search_layout.addWidget(self.search_icon)
            self.top_search_layout.addWidget(self.input, stretch=1)
            self.top_search_layout.addWidget(self.btn_clear)
            self.top_search_layout.addWidget(self.btn_close)

            while self.dock_layout.count() > 0:
                self.dock_layout.takeAt(0)
            self.dock_layout.addStretch(1)
            self.dock_layout.addWidget(self.btn_quick)
            self.dock_layout.addStretch(1)
            self.dock_layout.addWidget(self.btn_weather)
            self.dock_layout.addStretch(1)
            self.dock_layout.addWidget(self.btn_odd_center)
            self.dock_layout.addStretch(1)
            self.dock_layout.addWidget(self.btn_lens)
            self.dock_layout.addStretch(1)
            self.dock_layout.addWidget(self.btn_phone)
            self.dock_layout.addStretch(1)

            # Styling for container search frame: recessed sleek pill with subtle border
            inset_bg = "rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.07)"
            inset_border = "rgba(0, 0, 0, 0.09)" if is_light else "rgba(255, 255, 255, 0.10)"
            self.top_search_frame.setStyleSheet(f"QFrame {{ background: {inset_bg}; border: 1px solid {inset_border}; border-radius: 18px; }}")
            self.input.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {txt_col}; font-size: 12px; font-weight: 400; outline: none; }}")

            self.classic_box.hide()
            self.container_box.show()
            self.setFixedHeight(96)

            self.btn_odd_center.show()
            self.search_icon.show()
            self.btn_music.hide()

            if hasattr(self.overlay, "settings_btn") and self.overlay.settings_btn:
                self.overlay.settings_btn.hide()
        else:
            # Reparent into Classic single row
            while self.classic_layout.count() > 0:
                self.classic_layout.takeAt(0)

            self.classic_layout.addWidget(self.input, stretch=1)
            self.classic_layout.addWidget(self.btn_clear)
            self.classic_layout.addWidget(self.btn_quick)
            self.classic_layout.addWidget(self.btn_music)
            self.classic_layout.addWidget(self.btn_lens)
            self.classic_layout.addWidget(self.btn_weather)
            self.classic_layout.addWidget(self.btn_phone)
            self.classic_layout.addWidget(self.btn_close)

            self.input.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {txt_col}; font-size: 13px; outline: none; }}")

            self.container_box.hide()
            self.classic_box.show()
            self.setFixedHeight(48)

            self.btn_odd_center.hide()
            self.search_icon.hide()

            if hasattr(self.overlay, "settings_btn") and self.overlay.settings_btn:
                self.overlay.settings_btn.setVisible(bool(self.overlay.settings.get("ui_show_settings_button", True)))

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if hasattr(self, 'input') and self.input and not self.input.hasFocus():
            self.input.setFocus()

    def update_settings(self, settings: dict):
        mode = str(settings.get("ui_theme_style", "classic")).lower().strip()
        if mode != getattr(self, "_current_mode", None):
            self.apply_layout_mode(mode)

        if self.btn_plus is not None:
            self.btn_plus.setVisible(bool(settings.get("ui_show_plus_button", False)))

        # Side view mode: New UI with JUST the search bar and ODD settings button!
        is_side = str(settings.get("side_view", "off")).lower() in ("left", "right")
        if is_side:
            if hasattr(self, 'btn_weather'): self.btn_weather.hide()
            if hasattr(self, 'btn_phone'): self.btn_phone.hide()
            if hasattr(self, 'btn_quick'): self.btn_quick.hide()
            if hasattr(self, 'btn_lens'): self.btn_lens.hide()
            if hasattr(self, 'btn_music'): self.btn_music.hide()
            return

        enable_weather = bool(settings.get("enable_weather_widget", True))
        enable_mirror = bool(settings.get("enable_android_mirror", True))
        show_quick = bool(settings.get("ui_show_quick_settings_button", True))
        show_music_pref = bool(settings.get("ui_show_music_button", True)) and bool(settings.get("enable_music_overlay", True))
        show_lens_pref = bool(settings.get("ui_show_lens_button", True))

        if mode == "container":
            # Container layout: exactly 5 buttons at bottom dock:
            # [Quick settings] [Weather] [ODD settings center] [Image search] [Phone]
            if hasattr(self, 'btn_quick'): self.btn_quick.setVisible(show_quick)
            if hasattr(self, 'btn_weather'): self.btn_weather.setVisible(enable_weather)
            if hasattr(self, 'btn_odd_center'): self.btn_odd_center.setVisible(True)
            if hasattr(self, 'btn_lens'): self.btn_lens.setVisible(show_lens_pref)
            if hasattr(self, 'btn_phone'): self.btn_phone.setVisible(enable_mirror)
            if hasattr(self, 'btn_music'): self.btn_music.setVisible(False)
            if hasattr(self.overlay, "settings_btn") and self.overlay.settings_btn:
                self.overlay.settings_btn.hide()
            return

        # Classic Layout slot replacement & display logic
        replace_slot = str(settings.get("weather_replace_slot", "music")).lower().strip()
        if hasattr(self, 'btn_weather'):
            self.btn_weather.setVisible(enable_weather)

        mirror_slot = str(settings.get("android_mirror_replace_slot", "standalone")).lower().strip()
        if hasattr(self, 'btn_phone'):
            self.btn_phone.setVisible(enable_mirror and mirror_slot != "none")

        if hasattr(self, 'btn_quick'):
            self.btn_quick.setVisible(show_quick)

        action_mode = str(settings.get("search_pill_action_button", "both")).lower().strip()
        if action_mode in ("lens", "similar_image", "bing_visual"):
            action_mode = "google_lens"

        media_state = getattr(self.overlay, 'media_state', {})
        is_playing = bool(media_state.get("is_playing", False))
        has_title = bool(media_state.get("has_media", False)) or bool(media_state.get("title", ""))
        media_active = is_playing or has_title

        if action_mode == "both":
            self.btn_lens.set_icon_type("lens")
            self.btn_lens.setToolTip("Google Lens: select a screen region")
            self.btn_lens.setVisible(show_lens_pref)
            if hasattr(self, 'btn_music'):
                self.btn_music.setVisible(show_music_pref)
        elif action_mode == "dynamic":
            self.btn_lens.set_icon_type("lens")
            self.btn_lens.setToolTip("Google Lens: select a screen region")
            self.btn_lens.setVisible(show_lens_pref)
            if hasattr(self, 'btn_music'):
                self.btn_music.setVisible(show_music_pref and (media_active or str(settings.get("paused_media_behavior", "show_minimal")) == "button_only"))
        elif action_mode == "dynamic_swap":
            if hasattr(self, 'btn_music'):
                self.btn_music.setVisible(False)
            if is_playing and show_music_pref:
                self.btn_lens.set_icon_type("waveform")
                self.btn_lens.setToolTip("Music & Audio Controls (Media Playing)")
                self.btn_lens.setVisible(True)
            else:
                self.btn_lens.set_icon_type("lens")
                self.btn_lens.setToolTip("Google Lens: select a screen region")
                self.btn_lens.setVisible(show_lens_pref)
        elif action_mode == "music":
            if hasattr(self, 'btn_music'):
                self.btn_music.setVisible(show_music_pref)
            self.btn_lens.setVisible(False)
        elif action_mode == "none":
            if hasattr(self, 'btn_music'):
                self.btn_music.setVisible(False)
            self.btn_lens.setVisible(False)
        else:  # google_lens
            if hasattr(self, 'btn_music'):
                self.btn_music.setVisible(False)
            self.btn_lens.set_icon_type("lens")
            self.btn_lens.setToolTip("Google Lens: select a screen region")
            self.btn_lens.setVisible(show_lens_pref)

        if enable_weather:
            if replace_slot == "music":
                if hasattr(self, 'btn_music'):
                    self.btn_music.setVisible(False)
            elif replace_slot == "lens":
                if hasattr(self, 'btn_lens'):
                    self.btn_lens.setVisible(False)
            elif replace_slot == "quick_settings":
                if hasattr(self, 'btn_quick'):
                    self.btn_quick.setVisible(False)

        if enable_mirror and mirror_slot != "none":
            if mirror_slot == "music":
                if hasattr(self, 'btn_music'):
                    self.btn_music.setVisible(False)
            elif mirror_slot == "lens":
                if hasattr(self, 'btn_lens'):
                    self.btn_lens.setVisible(False)
            elif mirror_slot == "quick_settings":
                if hasattr(self, 'btn_quick'):
                    self.btn_quick.setVisible(False)
            elif mirror_slot == "weather":
                if hasattr(self, 'btn_weather'):
                    self.btn_weather.setVisible(False)

    def _on_action_button_clicked(self):
        action_mode = str(self.overlay.settings.get("search_pill_action_button", "both")).lower().strip()
        is_playing = bool(getattr(self.overlay, 'media_state', {}).get("is_playing", False))
        if action_mode == "music" or (action_mode == "dynamic_swap" and is_playing):
            self.overlay.on_music_overlay_button_clicked()
        else:
            self.overlay.start_google_lens_search()

    def _on_text_changed(self, text: str):
        visible = bool(text)
        if self.btn_clear.isVisible() != visible:
            self.btn_clear.setVisible(visible)

    def _on_clear_clicked(self):
        self.input.clear()
        self.input.setFocus()

    def _on_plus_clicked(self):
        try:
            self.overlay.toggle_commands_guide_panel()
        except Exception as e:
            print(f"[ODD] Error in _on_plus_clicked: {e}")

    def set_theme(self, theme: str):
        self.theme = theme
        if self.btn_plus is not None:
            self.btn_plus.set_theme(theme)
        if hasattr(self, 'search_icon') and self.search_icon:
            self.search_icon.set_theme(theme)
        if hasattr(self, 'btn_quick') and self.btn_quick:
            self.btn_quick.set_theme(theme)
        if hasattr(self, 'btn_music') and self.btn_music:
            self.btn_music.set_theme(theme)
        if hasattr(self, 'btn_lens') and self.btn_lens:
            self.btn_lens.set_theme(theme)
        if hasattr(self, 'btn_weather') and self.btn_weather:
            self.btn_weather.set_theme(theme)
        if hasattr(self, 'btn_phone') and self.btn_phone:
            self.btn_phone.set_theme(theme)
        if hasattr(self, 'btn_odd_center') and self.btn_odd_center:
            self.btn_odd_center.set_theme(theme)
        self.apply_layout_mode()
        self.update_settings(self.overlay.settings)
        self.update()

    def paintEvent(self, event):
        return

_SEARCH_MONO_ICON_CACHE: Dict[str, QPixmap] = {}

def get_search_item_monochrome_pixmap(item: SearchItem, is_light: bool, target_size: int = 20) -> QPixmap:
    import odd_icons
    if not item:
        return QPixmap()
    cache_key = f"{getattr(item, 'id', '')}|{getattr(item, 'category', '')}|{getattr(item, 'target', '')}|{is_light}|{target_size}"
    if cache_key in _SEARCH_MONO_ICON_CACHE:
        return _SEARCH_MONO_ICON_CACHE[cache_key]

    cat = (getattr(item, 'category', '') or "").upper()
    icon_col = "#1E1E1E" if is_light else "#FFFFFF"

    # 1. APPLICATION: Monochromatic app icon
    if "APP" in cat or cat == "APPLICATION":
        pix = odd_icons.get_vector_pixmap("application", color=icon_col, size=target_size)
        _SEARCH_MONO_ICON_CACHE[cache_key] = pix
        return pix

    # 2. FILE: Monochromatic file/document/media vector icon by category (no thumbnails)
    if cat in ("FILE", "FILE PREVIEW", "DOCUMENT", "DOC", "PDF", "IMAGE", "VIDEO", "AUDIO"):
        if cat == "IMAGE":
            icon_name = "appearance"
        elif cat == "VIDEO":
            icon_name = "cast"
        elif cat == "AUDIO":
            icon_name = "volume"
        elif cat == "PDF" or cat == "DOC":
            icon_name = "file"
        else:
            t_path = getattr(item, 'target', '') or ""
            ext = os.path.splitext(t_path)[1].lower() if t_path else ""
            if ext in (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus"):
                icon_name = "volume"
            elif ext in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v"):
                icon_name = "cast"
            elif ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".tiff", ".psd"):
                icon_name = "appearance"
            else:
                icon_name = "file"
        pix = odd_icons.get_vector_pixmap(icon_name, color=icon_col, size=target_size)
        _SEARCH_MONO_ICON_CACHE[cache_key] = pix
        return pix

    # 3. FOLDER: Monochromatic folder vector
    if cat in ("FOLDER", "FOLDER PREVIEW", "DIRECTORY", "EXPLORER", "DIR", "COPY PATH"):
        pix = odd_icons.get_vector_pixmap("folder", color=icon_col, size=target_size)
        _SEARCH_MONO_ICON_CACHE[cache_key] = pix
        return pix

    # 4. LINK: Monochromatic link vector
    if cat in ("LINK", "LINK PREVIEW", "WEB", "COPY LINK", "URL", "SEARCH", "GOOGLE"):
        pix = odd_icons.get_vector_pixmap("link", color=icon_col, size=target_size)
        _SEARCH_MONO_ICON_CACHE[cache_key] = pix
        return pix

    if "CALC" in cat:
        pix = odd_icons.get_vector_pixmap("modules", color=icon_col, size=target_size)
    elif "POWER" in cat or "SYSTEM" in cat:
        pix = odd_icons.get_vector_pixmap("power", color=icon_col, size=target_size)
    elif "CLIP" in cat:
        pix = odd_icons.get_vector_pixmap("copy", color=icon_col, size=target_size)
    else:
        pix = odd_icons.get_vector_pixmap("general", color=icon_col, size=target_size)

    _SEARCH_MONO_ICON_CACHE[cache_key] = pix
    return pix


class LivePreviewCard(QWidget):
    """
    Live visual preview card for Websites and Files/Folders inside ResultsCard.
    Renders an interactive, rich preview (website snapshot/status, syntax code snippet, or image preview)
    directly preceding the actionable results (Open Link / Open File).
    """
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.preview_data: Dict[str, Any] = {}
        self.setFixedHeight(126)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cached_image: Optional[QPixmap] = None
        self._cached_image_path: str = ""

    def set_preview(self, data: Dict[str, Any]):
        self.preview_data = data or {}
        p_type = self.preview_data.get("preview_type", "")
        p_path = self.preview_data.get("path", "")
        if p_type == "file" and p_path != self._cached_image_path:
            ext = str(self.preview_data.get("ext", "")).lower()
            if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".ico") and os.path.exists(p_path):
                try:
                    pix = QPixmap(p_path)
                    if not pix.isNull():
                        self._cached_image = pix.scaled(130, 84, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self._cached_image_path = p_path
                except Exception:
                    self._cached_image = None
            else:
                self._cached_image = None
                self._cached_image_path = ""
        self.update()

    def mousePressEvent(self, event):
        p_type = self.preview_data.get("preview_type", "")
        if p_type == "website":
            url = self.preview_data.get("url", "")
            if url:
                import webbrowser
                webbrowser.open(url)
                if self.overlay and hasattr(self.overlay, "dismiss"):
                    self.overlay.dismiss()
        elif p_type in ("file", "folder"):
            fpath = self.preview_data.get("path", "")
            if fpath and os.path.exists(fpath):
                os.startfile(fpath)
                if self.overlay and hasattr(self.overlay, "dismiss"):
                    self.overlay.dismiss()
        event.accept()

    def paintEvent(self, event):
        if not self.preview_data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        theme = str(self.overlay.get_current_theme()).lower()
        is_light = (theme == "light")
        p_type = self.preview_data.get("preview_type", "website")
        card_rect = self.rect().adjusted(4, 2, -4, -2)

        # 1. Frosted Surface
        bg_col = QColor(255, 255, 255, 14) if not is_light else QColor(0, 0, 0, 10)
        border_col = QColor(255, 255, 255, 28) if not is_light else QColor(0, 0, 0, 20)
        painter.setBrush(QBrush(bg_col))
        painter.setPen(QPen(border_col, 0.8))
        painter.drawRoundedRect(card_rect, 10, 10)

        if p_type == "website":
            self._paint_website(painter, card_rect, is_light)
        elif p_type == "file":
            self._paint_file(painter, card_rect, is_light)
        elif p_type == "folder":
            self._paint_folder(painter, card_rect, is_light)

    def _paint_website(self, painter: QPainter, rect: QRect, is_light: bool):
        domain = self.preview_data.get("domain", "Website")
        raw_url = self.preview_data.get("url", "")

        hdr_rect = QRectF(rect.left() + 12, rect.top() + 10, rect.width() - 24, 20)
        link_icon = odd_icons.get_vector_pixmap("link", color="#10B981" if not is_light else "#059669", size=14)
        if link_icon and not link_icon.isNull():
            painter.drawPixmap(int(hdr_rect.left()), int(hdr_rect.top() + 3), link_icon)

        ssl_rect = QRectF(hdr_rect.left() + 20, hdr_rect.top(), 80, 18)
        painter.setBrush(QBrush(QColor(16, 185, 129, 25) if not is_light else QColor(16, 185, 129, 35)))
        painter.setPen(QPen(QColor(16, 185, 129, 80), 0.7))
        painter.drawRoundedRect(ssl_rect, 9, 9)
        painter.setFont(QFont("Segoe UI Variable Text", 6.8, QFont.Weight.Bold))
        painter.setPen(QColor(52, 211, 153) if not is_light else QColor(5, 150, 105))
        painter.drawText(ssl_rect, Qt.AlignmentFlag.AlignCenter, "SSL SECURED")

        painter.setFont(QFont("Segoe UI Variable Display", 9.5, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255, 245) if not is_light else QColor(20, 20, 24, 245))
        painter.drawText(QRectF(ssl_rect.right() + 10, hdr_rect.top(), hdr_rect.width() - 110, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, domain)

        # Simulated Live Browser Preview Frame
        frame_rect = QRectF(rect.left() + 12, rect.top() + 36, 154, 76)
        painter.setBrush(QBrush(QColor(0, 0, 0, 45) if not is_light else QColor(255, 255, 255, 80)))
        painter.setPen(QPen(QColor(255, 255, 255, 20) if not is_light else QColor(0, 0, 0, 15), 0.8))
        painter.drawRoundedRect(frame_rect, 6, 6)

        dot_y = frame_rect.top() + 7
        for di, col in enumerate((QColor(239, 68, 68, 160), QColor(245, 158, 11, 160), QColor(16, 185, 129, 160))):
            painter.setBrush(QBrush(col))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(frame_rect.left() + 7 + di * 9, dot_y, 5, 5))

        addr_rect = QRectF(frame_rect.left() + 38, frame_rect.top() + 5, frame_rect.width() - 44, 10)
        painter.setBrush(QBrush(QColor(255, 255, 255, 15) if not is_light else QColor(0, 0, 0, 10)))
        painter.drawRoundedRect(addr_rect, 4, 4)

        painter.setBrush(QBrush(QColor(255, 255, 255, 16) if not is_light else QColor(0, 0, 0, 12)))
        painter.drawRoundedRect(QRectF(frame_rect.left() + 10, frame_rect.top() + 22, frame_rect.width() - 20, 16), 3, 3)
        painter.setBrush(QBrush(QColor(255, 255, 255, 10) if not is_light else QColor(0, 0, 0, 8)))
        painter.drawRoundedRect(QRectF(frame_rect.left() + 10, frame_rect.top() + 42, 58, 24), 3, 3)
        painter.drawRoundedRect(QRectF(frame_rect.left() + 74, frame_rect.top() + 42, 70, 24), 3, 3)

        info_x = frame_rect.right() + 14
        info_w = rect.right() - info_x - 12
        painter.setFont(QFont("Segoe UI Variable Display", 9.2, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255, 250) if not is_light else QColor(18, 18, 20, 245))
        painter.drawText(QRectF(info_x, rect.top() + 38, info_w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"Live Website: {domain}")

        painter.setFont(QFont("Segoe UI Variable Text", 8.0))
        painter.setPen(QColor(165, 170, 180, 220) if not is_light else QColor(100, 105, 115, 220))
        painter.drawText(QRectF(info_x, rect.top() + 58, info_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Ready to launch in default web browser")

        painter.setFont(QFont("Segoe UI Variable Text", 7.6))
        painter.setPen(QColor(130, 135, 145, 180) if not is_light else QColor(140, 145, 155, 180))
        elided_url = QFontMetrics(painter.font()).elidedText(raw_url, Qt.TextElideMode.ElideRight, int(info_w))
        painter.drawText(QRectF(info_x, rect.top() + 76, info_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_url)

        painter.setFont(QFont("Segoe UI Variable Text", 7.4, QFont.Weight.Medium))
        painter.setPen(QColor(56, 189, 248, 220) if not is_light else QColor(37, 99, 235, 220))
        painter.drawText(QRectF(info_x, rect.top() + 94, info_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "↵ Press Enter or click card to open")

    def _paint_file(self, painter: QPainter, rect: QRect, is_light: bool):
        base_name = self.preview_data.get("base_name", "File")
        ext = self.preview_data.get("ext", "").upper().replace(".", "") or "FILE"
        sz_str = self.preview_data.get("size", "")
        mtime = self.preview_data.get("mtime", "")
        snippet = self.preview_data.get("snippet", "")
        fpath = self.preview_data.get("path", "")

        hdr_rect = QRectF(rect.left() + 12, rect.top() + 8, rect.width() - 24, 20)
        file_icon = odd_icons.get_vector_pixmap("file", color="#A0AEC0" if not is_light else "#4A5568", size=14)
        if file_icon and not file_icon.isNull():
            painter.drawPixmap(int(hdr_rect.left()), int(hdr_rect.top() + 3), file_icon)

        ext_rect = QRectF(hdr_rect.left() + 20, hdr_rect.top(), 64, 18)
        painter.setBrush(QBrush(QColor(255, 255, 255, 20) if not is_light else QColor(0, 0, 0, 14)))
        painter.setPen(QPen(QColor(255, 255, 255, 36) if not is_light else QColor(0, 0, 0, 24), 0.7))
        painter.drawRoundedRect(ext_rect, 9, 9)
        painter.setFont(QFont("Segoe UI Variable Text", 7.0, QFont.Weight.Bold))
        painter.setPen(QColor(240, 240, 240) if not is_light else QColor(40, 40, 40))
        painter.drawText(ext_rect, Qt.AlignmentFlag.AlignCenter, ext[:7])

        painter.setFont(QFont("Segoe UI Variable Display", 9.2, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255, 245) if not is_light else QColor(20, 20, 24, 245))
        painter.drawText(QRectF(ext_rect.right() + 10, hdr_rect.top(), hdr_rect.width() - 180, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, base_name)

        painter.setFont(QFont("Segoe UI Variable Text", 7.6))
        painter.setPen(QColor(160, 164, 175) if not is_light else QColor(100, 105, 115))
        meta_str = f"{sz_str} • {mtime}" if sz_str and mtime else (sz_str or mtime)
        painter.drawText(QRectF(rect.right() - 170, hdr_rect.top(), 158, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, meta_str)

        if self._cached_image and not self._cached_image.isNull():
            img_x = rect.left() + 14
            img_y = rect.top() + 34
            painter.drawPixmap(img_x, img_y, self._cached_image)

            info_x = img_x + self._cached_image.width() + 14
            info_w = rect.right() - info_x - 12
            painter.setFont(QFont("Segoe UI Variable Text", 8.2, QFont.Weight.Medium))
            painter.setPen(QColor(255, 255, 255, 240) if not is_light else QColor(20, 20, 24, 240))
            painter.drawText(QRectF(info_x, rect.top() + 40, info_w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, snippet or "Image Preview")
            painter.setFont(QFont("Segoe UI Variable Text", 7.6))
            painter.setPen(QColor(140, 145, 155))
            elided_p = QFontMetrics(painter.font()).elidedText(fpath, Qt.TextElideMode.ElideMiddle, int(info_w))
            painter.drawText(QRectF(info_x, rect.top() + 62, info_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_p)
            painter.setFont(QFont("Segoe UI Variable Text", 7.4, QFont.Weight.Medium))
            painter.setPen(QColor(56, 189, 248) if not is_light else QColor(37, 99, 235))
            painter.drawText(QRectF(info_x, rect.top() + 84, info_w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "↵ Press Enter or click to open image")
        else:
            code_rect = QRectF(rect.left() + 12, rect.top() + 34, rect.width() - 24, 80)
            painter.setBrush(QBrush(QColor(0, 0, 0, 45) if not is_light else QColor(255, 255, 255, 75)))
            painter.setPen(QPen(QColor(255, 255, 255, 16) if not is_light else QColor(0, 0, 0, 14), 0.7))
            painter.drawRoundedRect(code_rect, 6, 6)

            lines = []
            if os.path.exists(fpath) and os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for _ in range(4):
                            line = f.readline()
                            if not line:
                                break
                            lines.append(line.rstrip("\r\n")[:80])
                except Exception:
                    pass

            if not lines and snippet:
                lines = snippet.split(" | ")[:3]

            if lines:
                code_font = QFont("Consolas", 8.0)
                painter.setFont(code_font)
                for li, ltext in enumerate(lines[:4]):
                    ly = code_rect.top() + 6 + li * 17
                    painter.setPen(QColor(100, 105, 115) if not is_light else QColor(150, 155, 165))
                    painter.drawText(QRectF(code_rect.left() + 8, ly, 18, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(li + 1))
                    painter.setPen(QColor(235, 238, 242) if not is_light else QColor(30, 30, 35))
                    painter.drawText(QRectF(code_rect.left() + 32, ly, code_rect.width() - 40, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, ltext)
            else:
                painter.setFont(QFont("Segoe UI Variable Text", 8.2))
                painter.setPen(QColor(160, 165, 175))
                elided_p = QFontMetrics(painter.font()).elidedText(fpath, Qt.TextElideMode.ElideMiddle, int(code_rect.width() - 20))
                painter.drawText(QRectF(code_rect.left() + 12, code_rect.top() + 18, code_rect.width() - 24, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_p)
                painter.setFont(QFont("Segoe UI Variable Text", 7.6, QFont.Weight.Medium))
                painter.setPen(QColor(56, 189, 248) if not is_light else QColor(37, 99, 235))
                painter.drawText(QRectF(code_rect.left() + 12, code_rect.top() + 44, code_rect.width() - 24, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "↵ Press Enter or click to open file")

    def _paint_folder(self, painter: QPainter, rect: QRect, is_light: bool):
        base_name = self.preview_data.get("base_name", "Folder")
        cnt_str = self.preview_data.get("cnt_str", "Directory")
        mtime = self.preview_data.get("mtime", "")
        fpath = self.preview_data.get("path", "")

        hdr_rect = QRectF(rect.left() + 12, rect.top() + 8, rect.width() - 24, 20)
        folder_icon = odd_icons.get_vector_pixmap("folder", color="#E4E4E7" if not is_light else "#27272A", size=15)
        if folder_icon and not folder_icon.isNull():
            painter.drawPixmap(int(hdr_rect.left()), int(hdr_rect.top() + 2), folder_icon)

        badge_rect = QRectF(hdr_rect.left() + 22, hdr_rect.top(), 72, 18)
        painter.setBrush(QBrush(QColor(56, 189, 248, 25) if not is_light else QColor(2, 132, 199, 25)))
        painter.setPen(QPen(QColor(56, 189, 248, 70), 0.7))
        painter.drawRoundedRect(badge_rect, 9, 9)
        painter.setFont(QFont("Segoe UI Variable Text", 7.0, QFont.Weight.Bold))
        painter.setPen(QColor(186, 230, 253) if not is_light else QColor(3, 105, 161))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "DIRECTORY")

        painter.setFont(QFont("Segoe UI Variable Display", 9.2, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255, 245) if not is_light else QColor(20, 20, 24, 245))
        painter.drawText(QRectF(badge_rect.right() + 10, hdr_rect.top(), hdr_rect.width() - 190, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, base_name)

        painter.setFont(QFont("Segoe UI Variable Text", 7.6))
        painter.setPen(QColor(160, 164, 175) if not is_light else QColor(100, 105, 115))
        meta_str = f"{cnt_str} • {mtime}" if mtime else cnt_str
        painter.drawText(QRectF(rect.right() - 170, hdr_rect.top(), 158, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, meta_str)

        f_box = QRectF(rect.left() + 12, rect.top() + 34, rect.width() - 24, 80)
        painter.setBrush(QBrush(QColor(0, 0, 0, 45) if not is_light else QColor(255, 255, 255, 75)))
        painter.setPen(QPen(QColor(255, 255, 255, 16) if not is_light else QColor(0, 0, 0, 14), 0.7))
        painter.drawRoundedRect(f_box, 6, 6)

        sub_items = []
        if os.path.exists(fpath) and os.path.isdir(fpath):
            try:
                sub_items = os.listdir(fpath)[:4]
            except Exception:
                sub_items = []

        painter.setFont(QFont("Segoe UI Variable Text", 8.0))
        if sub_items:
            for si, sname in enumerate(sub_items):
                sy = f_box.top() + 7 + si * 17
                is_sub_dir = os.path.isdir(os.path.join(fpath, sname))
                gly = "[DIR] " if is_sub_dir else ""
                painter.setPen(QColor(225, 230, 238) if not is_light else QColor(30, 30, 35))
                elided_sub = QFontMetrics(painter.font()).elidedText(f"{gly}{sname}", Qt.TextElideMode.ElideRight, int(f_box.width() - 24))
                painter.drawText(QRectF(f_box.left() + 10, sy, f_box.width() - 20, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_sub)
        else:
            painter.setPen(QColor(150, 155, 165))
            painter.drawText(QRectF(f_box.left() + 12, f_box.top() + 18, f_box.width() - 24, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, fpath)
            painter.setFont(QFont("Segoe UI Variable Text", 7.6, QFont.Weight.Medium))
            painter.setPen(QColor(220, 220, 225) if not is_light else QColor(40, 40, 45))
            painter.drawText(QRectF(f_box.left() + 12, f_box.top() + 44, f_box.width() - 24, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Press Enter or click to open directory")


class ResultsCard(QWidget):
    """Results region inside the continuous IslandSurfaceContainer with fluid cascade reveal"""
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self.card_layout = QVBoxLayout(self)
        self.card_layout.setContentsMargins(6, 4, 6, 8)
        self.card_layout.setSpacing(6)
        import odd_goo
        self._stagger = odd_goo.GooeyStaggerHelper(stagger_ms=28.0, duration_ms=130.0)
        self._cascade_timer = QTimer(self)
        self._cascade_timer.setInterval(16)
        self._cascade_timer.timeout.connect(self._on_cascade_tick)
        # One shared, low-frequency timer drives the shiny title sweep for all rows.
        self._shine_timer = QTimer(self)
        self._shine_timer.setInterval(48)
        self._shine_timer.timeout.connect(self._on_shine_tick)

    def trigger_cascade(self):
        """Triggers a crisp, fluid staggered cascade: items droplet out one by one"""
        self._shine_timer.stop()
        self._stagger.start()
        if not self._cascade_timer.isActive():
            self._cascade_timer.start()
        self._on_cascade_tick()

    def _on_cascade_tick(self):
        all_done = True
        list_widget = getattr(self.overlay, "list_widget", None)
        if list_widget:
            count = list_widget.count()
            for i in range(count):
                item = list_widget.item(i)
                w = list_widget.itemWidget(item)
                if isinstance(w, ResultItemWidget):
                    progress, y_off, stretch = self._stagger.get_item_state(i, count)
                    w.set_cascade_state(progress, y_off, stretch)
                    if progress < 1.0:
                        all_done = False
        if all_done:
            self._cascade_timer.stop()
            if self.isVisible() and self.overlay.list_widget.count():
                self.start_shine()

    def start_shine(self):
        if not self.isVisible() or not self.overlay.list_widget.count():
            return
        self._shine_start_ts = time.perf_counter()
        self._shine_timer.start()

    def stop_shine(self):
        self._shine_timer.stop()

    def stop_animations_for_typing(self):
        """Drop result motion as soon as new input arrives to protect keystroke latency."""
        if not self._cascade_timer.isActive() and not self._shine_timer.isActive():
            return
        self._cascade_timer.stop()
        self._shine_timer.stop()
        list_widget = getattr(self.overlay, "list_widget", None)
        if not list_widget:
            return
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            widget = list_widget.itemWidget(item) if item else None
            if not isinstance(widget, ResultItemWidget):
                continue
            if widget._blur_effect is not None or widget._cascade_progress < 1.0:
                widget.set_cascade_state(1.0, 0.0, 1.0)
            if widget._shine_phase > 0.0:
                widget.set_shine_phase(0.0)

    def _on_shine_tick(self):
        if not self.isVisible() or not self.overlay.list_widget.count():
            self._shine_timer.stop()
            return
        phase = (time.perf_counter() - getattr(self, "_shine_start_ts", time.perf_counter())) / 0.9
        if phase >= 1.0:
            phase = 1.0
        for i in range(self.overlay.list_widget.count()):
            item = self.overlay.list_widget.item(i)
            widget = self.overlay.list_widget.itemWidget(item) if item else None
            if isinstance(widget, ResultItemWidget):
                widget.set_shine_phase(phase)
        if phase >= 1.0:
            self._shine_timer.stop()

    def hideEvent(self, event):
        self._cascade_timer.stop()
        self._shine_timer.stop()
        super().hideEvent(event)

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            is_light = (str(self.theme).lower() == "light")
            bg_col = QColor(245, 245, 248, 255) if is_light else QColor(10, 10, 12, 255)
            border_col = QColor(220, 220, 225, 255) if is_light else QColor(36, 36, 40, 255)
            r = 16.0
            from odd_theme import create_squircle_path
            path = create_squircle_path(rect, r)
            painter.fillPath(path, QBrush(bg_col))
            painter.strokePath(path, QPen(border_col, 0.8))
        finally:
            if painter.isActive():
                painter.end()


class ResultItemWidget(QWidget):
    """
    High-performance painted ResultItemWidget with clean spacing and instant typing updates.
    """
    def __init__(self, item: SearchItem, theme="dark", parent=None):
        super().__init__(parent)
        self.item = item
        self.theme = theme
        self.is_selected = False
        self._sel_progress = 0.0
        self._cascade_progress = 1.0
        self._shine_phase = 0.0
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.font_badge = QFont("Segoe UI Variable Text", 7, QFont.Weight.Bold)
        self.font_title = QFont("Segoe UI Variable Text", 9, QFont.Weight.Medium)
        self.font_sub = QFont("Segoe UI Variable Text", 8, QFont.Weight.Normal)
        self._blur_effect = None


    def set_cascade_progress(self, p: float):
        p = max(0.0, min(1.0, float(p)))
        if abs(self._cascade_progress - p) > 0.005:
            self._cascade_progress = p
            self.update()

    def set_cascade_state(self, progress: float, y_offset: float = 0.0, stretch: float = 1.0):
        self._cascade_progress = max(0.0, min(1.0, float(progress)))
        self._cascade_y_offset = float(y_offset)
        self._cascade_stretch = float(stretch)
        if self._blur_effect is not None:
            self._blur_effect.setBlurRadius(5.0 * (1.0 - self._cascade_progress))
            if self._cascade_progress >= 0.999:
                self.setGraphicsEffect(None)
                self._blur_effect = None
        self.update()

    def sizeHint(self):
        return QSize(0, 56)

    @staticmethod
    def _soft_ease_out(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1.0 - ((1.0 - t) ** 3)

    def start_staggered_enter(self, delay_ms: int = 0):
        """Reveal each result with a short staggered fade and blur settle."""
        self._cascade_progress = 0.0
        self._cascade_y_offset = 7.0
        if self._blur_effect is None:
            self._blur_effect = QGraphicsBlurEffect(self)
            self._blur_effect.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
        self._blur_effect.setBlurRadius(5.0)
        self.setGraphicsEffect(self._blur_effect)
        self.update()

    def transition_to_item(self, new_item: SearchItem, theme: str, selected: bool, delay_ms: int = 0):
        """Update the existing row immediately without delaying text input."""
        self.item = new_item
        self.theme = theme
        self._shine_phase = 0.0
        if self._blur_effect is not None:
            self.setGraphicsEffect(None)
            self._blur_effect = None
        self._cascade_progress = 1.0
        self.set_selected(selected, immediate=True)
        self.update()

    def set_selected(self, selected: bool, immediate: bool = False):
        if self.is_selected == selected and not immediate:
            return
        self.is_selected = selected
        target = 1.0 if selected else 0.0
        self._sel_progress = target
        self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def set_shine_phase(self, phase: float):
        self._shine_phase = max(0.0, min(1.0, float(phase)))
        self.update()

    def _draw_item_row(self, painter: QPainter, item_obj: SearchItem, w: int, h: int, is_light: bool, opacity: float, y_offset: float):
        if opacity <= 0.01 or item_obj is None:
            return
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, opacity)))
        if abs(y_offset) > 0.05:
            painter.translate(0.0, y_offset)

        # 1. Monochromatic thumbnail container: 28x28 at x=12
        thumb_x = 12
        thumb_y = (h - 28) // 2
        thumb_rect = QRectF(thumb_x, thumb_y, 28, 28)

        plate_col = QColor(0, 0, 0, 10) if is_light else QColor(255, 255, 255, 12)
        plate_border = QColor(0, 0, 0, 16) if is_light else QColor(255, 255, 255, 22)
        painter.setBrush(QBrush(plate_col))
        painter.setPen(QPen(plate_border, 0.7))
        painter.drawRoundedRect(thumb_rect, 6, 6)

        mono_pix = get_search_item_monochrome_pixmap(item_obj, is_light, target_size=18)
        if mono_pix and not mono_pix.isNull():
            px = thumb_x + (28 - mono_pix.width()) / 2.0
            py = thumb_y + (28 - mono_pix.height()) / 2.0
            painter.drawPixmap(QPointF(px, py), mono_pix)

        # 2. Category badge at x = 48
        cat = (item_obj.category or "SEARCH").upper()
        metrics_b = QFontMetrics(self.font_badge)
        badge_w = max(44, metrics_b.horizontalAdvance(cat) + 14)
        badge_h = 18
        badge_x = thumb_x + 28 + 8  # 48
        badge_y = (h - badge_h) // 2
        badge_rect = QRectF(badge_x, badge_y, badge_w, badge_h)

        is_split_cat = cat in ("SPLIT", "TILE 3", "GRID 4")
        if is_light:
            if is_split_cat:
                painter.setBrush(QBrush(QColor(0, 0, 0, 24)))
                painter.setPen(QPen(QColor(0, 0, 0, 48), 1.0))
                badge_text_color = QColor(20, 20, 20)
            else:
                painter.setBrush(QBrush(QColor(0, 0, 0, 12)))
                painter.setPen(QPen(QColor(0, 0, 0, 24), 1.0))
                badge_text_color = QColor(50, 50, 50)
            title_color = QColor(20, 20, 20)
            sub_color = QColor(110, 110, 110)
        else:
            if is_split_cat:
                painter.setBrush(QBrush(Tokens.SURFACE_3))
                painter.setPen(QPen(Tokens.BORDER_STRONG, 1.0))
                badge_text_color = Tokens.TEXT_PRIMARY
            else:
                painter.setBrush(QBrush(Tokens.SURFACE_2))
                painter.setPen(QPen(Tokens.BORDER_SUBTLE, 1.0))
                badge_text_color = Tokens.TEXT_PRIMARY
            title_color = Tokens.TEXT_PRIMARY
            sub_color = Tokens.TEXT_SECONDARY

        # Sleek pill badge (fully rounded)
        painter.drawRoundedRect(badge_rect, 9, 9)

        painter.setFont(self.font_badge)
        painter.setPen(badge_text_color)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, cat)

        text_x = badge_x + badge_w + 12
        text_w = max(10, w - text_x - 14)

        # Title row: upper half
        title_y = max(4, (h // 2) - 20)
        title_h = 20
        title_rect = QRect(text_x, title_y, text_w, title_h)
        text_col_clean = QColor(0xFA, 0xFA, 0xFA) if not is_light else QColor(0x20, 0x20, 0x20)
        painter.setFont(self.font_title)
        shine = self._shine_phase
        if shine > 0.0:
            shine_center = -0.28 + shine * 1.56
            grad = QLinearGradient(title_rect.left(), title_rect.top(), title_rect.right(), title_rect.top())
            if is_light:
                shine_color = QColor(105, 105, 112)
            else:
                shine_color = QColor(255, 255, 255)
            stops = [
                (0.0, text_col_clean),
                (max(0.0, min(1.0, shine_center - 0.16)), text_col_clean),
                (max(0.0, min(1.0, shine_center)), shine_color),
                (max(0.0, min(1.0, shine_center + 0.16)), text_col_clean),
                (1.0, text_col_clean),
            ]
            # Keep stops strictly ordered while the highlight moves beyond the text bounds.
            compact_stops = []
            for pos, color in stops:
                if compact_stops and pos <= compact_stops[-1][0]:
                    continue
                compact_stops.append((pos, color))
            for pos, color in compact_stops:
                grad.setColorAt(pos, color)
            painter.setPen(QPen(QBrush(grad), 1.0))
        else:
            painter.setPen(text_col_clean)
        metrics_title = QFontMetrics(self.font_title)
        elided_title = metrics_title.elidedText(item_obj.title, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        # Subtitle row: lower half
        sub_y = title_y + title_h + 1
        sub_h = 17
        painter.setFont(self.font_sub)
        painter.setPen(sub_color)
        metrics_sub = QFontMetrics(self.font_sub)
        elided_sub = metrics_sub.elidedText(item_obj.subtitle, Qt.TextElideMode.ElideRight, text_w)
        sub_rect = QRect(text_x, sub_y, text_w, sub_h)
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_sub)
        painter.restore()


    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._draw_frosted_pill(painter)
        finally:
            if painter.isActive():
                painter.end()

    def _draw_frosted_pill(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        theme = str(self.theme).lower()
        is_light = (theme == "light")

        row_vis = self._cascade_progress
        sel_alpha = self._sel_progress * row_vis

        # Selection Background Highlight with spacious inset padding
        if sel_alpha > 0.01:
            rect = self.rect().adjusted(4, 2, -4, -2)
            if is_light:
                bg = QColor(0, 0, 0, int(16 * sel_alpha))
                border = QColor(0, 0, 0, int(22 * sel_alpha))
            elif theme == "oled":
                bg = QColor(255, 255, 255, int(26 * sel_alpha))
                border = QColor(255, 255, 255, int(40 * sel_alpha))
            else:
                bg = QColor(255, 255, 255, int(22 * sel_alpha))
                border = QColor(255, 255, 255, int(34 * sel_alpha))

            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(rect, 8, 8)

        # Render item content with smooth liquid droplet fade-in reveal and soft spring overshoot
        if row_vis < 1.0:
            y_off = getattr(self, "_cascade_y_offset", 12.0 * (1.0 - row_vis))
            self._draw_item_row(painter, self.item, w, h, is_light, row_vis, y_off)
        else:
            self._draw_item_row(painter, self.item, w, h, is_light, 1.0, 0.0)


# =====================================================================
# POWER CONTROLS & QUICK SETTINGS FROSTED COMPONENTS
# =====================================================================

def get_master_volume_info() -> Tuple[int, bool, Any]:
    """Returns (volume_pct, is_muted, None) safely from dedicated COM worker cache with 0ms GUI latency"""
    try:
        v, m = odd_com.ComWorker.get_instance().get_cached_volume()
        return v, m, None
    except Exception:
        return 70, False, None

def set_master_volume(vol_pct: int, vol_endpoint=None):
    """Sets master volume level (0-100) instantly and safely via dedicated COM worker thread"""
    try:
        odd_com.ComWorker.get_instance().set_volume(vol_pct)
    except Exception:
        pass

def toggle_master_mute(vol_endpoint=None) -> bool:
    """Toggles master audio mute state safely via dedicated COM worker thread"""
    try:
        worker = odd_com.ComWorker.get_instance()
        _, m = worker.get_cached_volume()
        new_m = not m
        worker.set_mute(new_m)
        return new_m
    except Exception:
        return False

_cached_brightness_val: Optional[int] = None
_brightness_supported: Optional[bool] = None

def get_brightness_info() -> int:
    """Returns current monitor brightness (0-100) from ComWorker cache without any WMI or process spawning stalls"""
    global _cached_brightness_val
    try:
        val = odd_com.ComWorker.get_instance().get_cached_brightness()
        _cached_brightness_val = val
        return val
    except Exception:
        return _cached_brightness_val if _cached_brightness_val is not None else 70

def set_brightness_async(val: int):
    """Sets monitor brightness (0-100) via ComWorker with latest-value-wins coalescing"""
    global _cached_brightness_val
    _cached_brightness_val = max(0, min(100, int(val)))
    try:
        odd_com.ComWorker.get_instance().set_brightness(val)
    except Exception:
        pass

def set_radio_state_async(kind: str, enable: bool):
    """Directly sets Windows radio state ('WiFi' or 'Bluetooth') asynchronously via ComWorker"""
    try:
        odd_com.ComWorker.get_instance().toggle_radio(kind, enable)
    except Exception:
        pass


def get_connected_bluetooth_devices() -> list:
    """
    Returns the friendly names of currently CONNECTED Bluetooth devices only.
    Excludes paired-but-disconnected devices and internal adapter hardware.
    """
    import ctypes
    from ctypes import wintypes

    connected = []
    seen = set()
    ignore_keywords = (
        'adapter', 'radio', 'transport', 'service', 'enumerator',
        'profile', 'protocol', 'generic attribute', 'rfcomm', 'virtual'
    )

    # 1. SetupAPI with DEVPKEY_Device_IsConnected (covers classic & BLE devices)
    try:
        class _GUID(ctypes.Structure):
            _fields_ = [
                ('Data1', wintypes.DWORD),
                ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD),
                ('Data4', wintypes.BYTE * 8)
            ]

        class _SP_DEVINFO_DATA(ctypes.Structure):
            _fields_ = [
                ('cbSize', wintypes.DWORD),
                ('ClassGuid', _GUID),
                ('DevInst', wintypes.DWORD),
                ('Reserved', ctypes.c_void_p)
            ]

        class _DEVPROPKEY(ctypes.Structure):
            _fields_ = [
                ('fmtid_Data1', wintypes.DWORD),
                ('fmtid_Data2', wintypes.WORD),
                ('fmtid_Data3', wintypes.WORD),
                ('fmtid_Data4', wintypes.BYTE * 8),
                ('pid', wintypes.ULONG),
            ]

        key_isConnected = _DEVPROPKEY(
            0xa8b865dd, 0x2e3d, 0x4094,
            (wintypes.BYTE * 8)(0xad, 0x97, 0xe5, 0x93, 0xa7, 0x0c, 0x75, 0xd6),
            26
        )
        key_devName = _DEVPROPKEY(
            0xb725f130, 0x47ef, 0x101a,
            (wintypes.BYTE * 8)(0xa5, 0xf1, 0x02, 0x60, 0x8c, 0x9e, 0xeb, 0xac),
            10
        )

        setupapi = ctypes.WinDLL('setupapi.dll')
        setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
        setupapi.SetupDiEnumDeviceInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(_SP_DEVINFO_DATA)]
        setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
        setupapi.SetupDiGetDevicePropertyW.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_SP_DEVINFO_DATA),
            ctypes.POINTER(_DEVPROPKEY), ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.DWORD
        ]
        setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
        setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
        setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

        bth_guid = _GUID(0xe0cbf06c, 0xcd8b, 0x4647, (wintypes.BYTE * 8)(0xbb, 0x8a, 0x26, 0x3b, 0x43, 0xf0, 0xf9, 0x74))
        DIGCF_PRESENT = 0x00000002

        hDevInfo = setupapi.SetupDiGetClassDevsW(ctypes.byref(bth_guid), None, None, DIGCF_PRESENT)
        if hDevInfo and hDevInfo != -1:
            dev_info = _SP_DEVINFO_DATA()
            dev_info.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            index = 0
            while setupapi.SetupDiEnumDeviceInfo(hDevInfo, index, ctypes.byref(dev_info)):
                prop_type = wintypes.DWORD()
                conn_buf = wintypes.BYTE()
                is_conn = False
                if setupapi.SetupDiGetDevicePropertyW(
                    hDevInfo, ctypes.byref(dev_info), ctypes.byref(key_isConnected),
                    ctypes.byref(prop_type), ctypes.cast(ctypes.byref(conn_buf), ctypes.c_void_p),
                    1, None, 0
                ):
                    is_conn = bool(conn_buf.value)

                if is_conn:
                    req_size = wintypes.DWORD()
                    setupapi.SetupDiGetDevicePropertyW(
                        hDevInfo, ctypes.byref(dev_info), ctypes.byref(key_devName),
                        ctypes.byref(prop_type), None, 0, ctypes.byref(req_size), 0
                    )
                    if req_size.value > 0:
                        buf = ctypes.create_unicode_buffer(req_size.value // 2 + 1)
                        if setupapi.SetupDiGetDevicePropertyW(
                            hDevInfo, ctypes.byref(dev_info), ctypes.byref(key_devName),
                            ctypes.byref(prop_type), ctypes.cast(buf, ctypes.c_void_p),
                            req_size.value, None, 0
                        ):
                            d_name = buf.value.strip()
                            d_name_l = d_name.lower()
                            if d_name and not any(k in d_name_l for k in ignore_keywords):
                                if d_name not in seen:
                                    seen.add(d_name)
                                    connected.append(d_name)
                index += 1
            setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)
    except Exception:
        pass

    # 2. Classic Bluetooth fallback via BluetoothAPIs.dll
    try:
        class _SYSTEMTIME(ctypes.Structure):
            _fields_ = [
                ('wYear', wintypes.WORD), ('wMonth', wintypes.WORD),
                ('wDayOfWeek', wintypes.WORD), ('wDay', wintypes.WORD),
                ('wHour', wintypes.WORD), ('wMinute', wintypes.WORD),
                ('wSecond', wintypes.WORD), ('wMilliseconds', wintypes.WORD),
            ]

        class _BLUETOOTH_DEVICE_INFO(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('Address', ctypes.c_ulonglong),
                ('ulClassofDevice', wintypes.ULONG),
                ('fConnected', wintypes.BOOL),
                ('fRemembered', wintypes.BOOL),
                ('fAuthenticated', wintypes.BOOL),
                ('stLastSeen', _SYSTEMTIME),
                ('stLastUsed', _SYSTEMTIME),
                ('szName', wintypes.WCHAR * 248),
            ]

        class _BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('fReturnAuthenticated', wintypes.BOOL),
                ('fReturnRemembered', wintypes.BOOL),
                ('fReturnUnknown', wintypes.BOOL),
                ('fReturnConnected', wintypes.BOOL),
                ('fIssueInquiry', wintypes.BOOL),
                ('cTimeoutMultiplier', ctypes.c_ubyte),
                ('hRadio', wintypes.HANDLE),
            ]

        bth = ctypes.WinDLL('BluetoothAPIs.dll')
        bth.BluetoothFindFirstDevice.restype = wintypes.HANDLE
        bth.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(_BLUETOOTH_DEVICE_SEARCH_PARAMS), ctypes.POINTER(_BLUETOOTH_DEVICE_INFO)]
        bth.BluetoothFindNextDevice.restype = wintypes.BOOL
        bth.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BLUETOOTH_DEVICE_INFO)]
        bth.BluetoothFindDeviceClose.restype = wintypes.BOOL
        bth.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]

        search_params = _BLUETOOTH_DEVICE_SEARCH_PARAMS()
        search_params.dwSize = ctypes.sizeof(_BLUETOOTH_DEVICE_SEARCH_PARAMS)
        search_params.fReturnAuthenticated = True
        search_params.fReturnRemembered = True
        search_params.fReturnUnknown = False
        search_params.fReturnConnected = True
        search_params.fIssueInquiry = False

        device_info = _BLUETOOTH_DEVICE_INFO()
        device_info.dwSize = ctypes.sizeof(_BLUETOOTH_DEVICE_INFO)

        hFind = bth.BluetoothFindFirstDevice(ctypes.byref(search_params), ctypes.byref(device_info))
        if hFind:
            while True:
                if device_info.fConnected:
                    d_name = device_info.szName.strip()
                    d_name_l = d_name.lower()
                    if d_name and not any(k in d_name_l for k in ignore_keywords):
                        if d_name not in seen:
                            seen.add(d_name)
                            connected.append(d_name)
                device_info.dwSize = ctypes.sizeof(_BLUETOOTH_DEVICE_INFO)
                if not bth.BluetoothFindNextDevice(hFind, ctypes.byref(device_info)):
                    break
            bth.BluetoothFindDeviceClose(hFind)
    except Exception:
        pass

    return connected


def set_nearby_sharing_state_async(enable: bool):
    """Directly toggles Windows Nearby Sharing in user registry"""
    def _run():
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\CDP")
            winreg.SetValueEx(key, "NearShareChannelStatus", 0, winreg.REG_DWORD, 1 if enable else 0)
            winreg.CloseKey(key)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

def get_quick_slider_style(theme="dark", muted: bool = False) -> str:
    theme = str(theme).lower()
    if theme == "light":
        sub_bg = "rgba(239, 68, 68, 0.70)" if muted else "rgba(71, 85, 105, 0.85)"
        handle_border = "rgba(239, 68, 68, 0.75)" if muted else "rgba(0, 0, 0, 0.22)"
        return f"""
            QSlider {{
                min-height: 22px;
            }}
            QSlider::groove:horizontal {{
                height: 5px;
                background: rgba(0, 0, 0, 0.12);
                border-radius: 2.5px;
            }}
            QSlider::sub-page:horizontal {{
                background: {sub_bg};
                border-radius: 2.5px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                border: 1px solid {handle_border};
                width: 14px;
                height: 14px;
                margin: -4.5px 0;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #F1F5F9;
                border: 1px solid rgba(0, 0, 0, 0.40);
            }}
        """
    elif theme == "oled":
        sub_bg = "rgba(248, 113, 113, 0.75)" if muted else "#FFFFFF"
        handle_bg = "#FCA5A5" if muted else "#FFFFFF"
        return f"""
            QSlider {{
                min-height: 22px;
            }}
            QSlider::groove:horizontal {{
                height: 5px;
                background: rgba(255, 255, 255, 0.20);
                border-radius: 2.5px;
            }}
            QSlider::sub-page:horizontal {{
                background: {sub_bg};
                border-radius: 2.5px;
            }}
            QSlider::handle:horizontal {{
                background: {handle_bg};
                border: 1px solid rgba(0, 0, 0, 0.35);
                width: 14px;
                height: 14px;
                margin: -4.5px 0;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #E2E8F0;
            }}
        """
    else:  # dark
        sub_bg = "rgba(248, 113, 113, 0.75)" if muted else "rgba(255, 255, 255, 0.78)"
        handle_bg = "#FCA5A5" if muted else "#FFFFFF"
        return f"""
            QSlider {{
                min-height: 22px;
            }}
            QSlider::groove:horizontal {{
                height: 5px;
                background: rgba(255, 255, 255, 0.14);
                border-radius: 2.5px;
            }}
            QSlider::sub-page:horizontal {{
                background: {sub_bg};
                border-radius: 2.5px;
            }}
            QSlider::handle:horizontal {{
                background: {handle_bg};
                border: 1px solid rgba(0, 0, 0, 0.3);
                width: 14px;
                height: 14px;
                margin: -4.5px 0;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #F1F5F9;
            }}
        """


class FrostedPillButton(QPushButton):
    """Centered compact rounded frosted glass pill button for quick controls"""
    def __init__(self, icon_name="power", text="Power Controls", theme="dark", parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.text_label = text
        self.theme = theme
        self.is_active = False
        self.setFixedSize(128, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def set_active(self, active: bool):
        if self.is_active != active:
            self.is_active = active
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        r = float(rect.height()) / 2.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), r, r)

        theme = str(self.theme).lower()
        is_hover = self.underMouse()
        is_down = self.isDown()
        active = getattr(self, 'is_active', False)

        if theme == "light":
            if is_down:
                bg = QColor(220, 224, 232, 240)
                border = QColor(0, 0, 0, 60) if active else QColor(0, 0, 0, 45)
                text_col = QColor(15, 23, 42)
                icon_col = QColor(15, 23, 42) if active else QColor(30, 41, 59)
            elif active:
                bg = QColor(218, 224, 234, 245)
                border = QColor(160, 170, 186, 255)
                text_col = QColor(15, 23, 42)
                icon_col = QColor(15, 23, 42)
            elif is_hover:
                bg = QColor(255, 255, 255, 245)
                border = QColor(0, 0, 0, 40)
                text_col = QColor(15, 23, 42)
                icon_col = QColor(30, 41, 59)
            else:
                bg = QColor(245, 246, 250, 200)
                border = QColor(0, 0, 0, 24)
                text_col = QColor(51, 65, 85)
                icon_col = QColor(71, 85, 105)

            painter.fillPath(path, QBrush(bg))
            painter.strokePath(path, QPen(border, 1.2 if active else 1.0))

        elif theme == "oled":
            if is_down:
                bg = QColor(28, 28, 34, 245)
                border = QColor(255, 255, 255, 110) if active else QColor(255, 255, 255, 70)
                text_col = QColor(255, 255, 255)
                icon_col = QColor(255, 255, 255) if active else QColor(230, 230, 230)
            elif active:
                bg = QColor(70, 74, 86, 245)
                border = QColor(255, 255, 255, 120)
                text_col = QColor(255, 255, 255)
                icon_col = QColor(255, 255, 255)
            elif is_hover:
                bg = QColor(24, 24, 30, 240)
                border = QColor(255, 255, 255, 65)
                text_col = QColor(255, 255, 255)
                icon_col = QColor(245, 245, 245)
            else:
                bg = QColor(10, 10, 14, 225)
                border = QColor(255, 255, 255, 32)
                text_col = QColor(200, 205, 215)
                icon_col = QColor(180, 185, 195)

            painter.fillPath(path, QBrush(bg))
            painter.strokePath(path, QPen(border, 1.2 if active else 1.0))

        else:  # Dark mode
            grad = QLinearGradient(0, 0, 0, self.height())
            if is_down:
                grad.setColorAt(0.0, QColor(48, 54, 70, 240))
                grad.setColorAt(1.0, QColor(24, 28, 38, 245))
                border = QColor(255, 255, 255, 110) if active else QColor(255, 255, 255, 60)
                text_col = QColor(255, 255, 255)
                icon_col = QColor(255, 255, 255) if active else QColor(230, 230, 235)
            elif active:
                grad.setColorAt(0.0, QColor(76, 82, 96, 245))
                grad.setColorAt(1.0, QColor(56, 62, 74, 250))
                border = QColor(255, 255, 255, 115)
                text_col = QColor(255, 255, 255)
                icon_col = QColor(255, 255, 255)
            elif is_hover:
                grad.setColorAt(0.0, QColor(54, 60, 74, 225))
                grad.setColorAt(0.4, QColor(36, 40, 52, 230))
                grad.setColorAt(1.0, QColor(22, 24, 32, 235))
                border = QColor(255, 255, 255, 70)
                text_col = QColor(255, 255, 255)
                icon_col = QColor(250, 250, 250)
            else:
                grad.setColorAt(0.0, QColor(38, 42, 54, 195))
                grad.setColorAt(0.4, QColor(26, 28, 38, 205))
                grad.setColorAt(1.0, QColor(16, 18, 24, 215))
                border = QColor(255, 255, 255, 36)
                text_col = QColor(215, 220, 230)
                icon_col = QColor(190, 200, 215)

            painter.fillPath(path, QBrush(grad))
            painter.strokePath(path, QPen(border, 1.2 if active else 1.0))

            hl_path = QPainterPath()
            hl_rect = rect.adjusted(1, 1, -1, -1)
            hl_path.addRoundedRect(QRectF(hl_rect), r - 1, r - 1)
            painter.strokePath(hl_path, QPen(QColor(255, 255, 255, 22 if not is_hover else 36), 0.8))

        font = QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium)
        painter.setFont(font)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(self.text_label)
        icon_size = 14
        spacing = 6
        total_content_w = icon_size + spacing + text_w
        start_x = int((self.width() - total_content_w) / 2.0)
        cy = self.height() / 2.0
        icon_cx = start_x + icon_size / 2.0
        icon_cy = cy

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(icon_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        if self.icon_name == "power":
            arc_r = 4.5
            arc_rect = QRectF(icon_cx - arc_r, icon_cy - arc_r + 0.5, arc_r * 2, arc_r * 2)
            painter.drawArc(arc_rect, 125 * 16, 290 * 16)
            painter.drawLine(QPointF(icon_cx, icon_cy - arc_r - 0.5), QPointF(icon_cx, icon_cy - 0.5))
        elif self.icon_name == "quick_settings":
            bar_len = 5.0
            y1 = icon_cy - 3.5
            y2 = icon_cy
            y3 = icon_cy + 3.5
            painter.drawLine(QPointF(icon_cx - bar_len, y1), QPointF(icon_cx + bar_len, y1))
            painter.drawLine(QPointF(icon_cx - bar_len, y2), QPointF(icon_cx + bar_len, y2))
            painter.drawLine(QPointF(icon_cx - bar_len, y3), QPointF(icon_cx + bar_len, y3))
            painter.drawLine(QPointF(icon_cx - 2.0, y1 - 1.5), QPointF(icon_cx - 2.0, y1 + 1.5))
            painter.drawLine(QPointF(icon_cx + 2.5, y2 - 1.5), QPointF(icon_cx + 2.5, y2 + 1.5))
            painter.drawLine(QPointF(icon_cx - 1.0, y3 - 1.5), QPointF(icon_cx - 1.0, y3 + 1.5))

        painter.setPen(text_col)
        text_rect = QRect(int(start_x + icon_size + spacing), 0, text_w + 4, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text_label)


class PowerCircleButton(QPushButton):
    """Circular frosted icon button with label underneath (Control Center / Launchpad style)"""
    def __init__(self, action_id: str, title: str, subtitle: str, theme="dark", parent=None):
        super().__init__(parent)
        self.action_id = action_id
        self.title = title
        self.subtitle = subtitle
        self.theme = theme
        self.setFixedSize(60, 68)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(f"{title} ({subtitle})")

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = float(self.width())
        theme = str(self.theme).lower()
        is_hover = self.underMouse()
        is_down = self.isDown()

        accent_map = {
            "shutdown": QColor(239, 68, 68),     # Red
            "restart": QColor(245, 158, 11),     # Amber
            "sleep": QColor(220, 220, 225),       # Blue
            "lock": QColor(168, 85, 247),        # Purple
            "logout": QColor(16, 185, 129),      # Emerald
            "hibernate": QColor(6, 182, 212)     # Cyan
        }
        accent = accent_map.get(self.action_id, QColor(96, 165, 250))

        circle_size = 40.0
        cx = w / 2.0
        cy = 22.0
        circle_rect = QRectF(cx - circle_size / 2.0, cy - circle_size / 2.0, circle_size, circle_size)

        circle_path = QPainterPath()
        circle_path.addEllipse(circle_rect)

        if theme == "light":
            if is_down:
                bg = QColor(accent.red(), accent.green(), accent.blue(), 55)
                border = accent
                icon_col = accent
                label_col = QColor(15, 23, 42)
            elif is_hover:
                bg = QColor(accent.red(), accent.green(), accent.blue(), 35)
                border = accent
                icon_col = accent
                label_col = QColor(15, 23, 42)
            else:
                bg = QColor(245, 247, 252, 210)
                border = QColor(0, 0, 0, 25)
                icon_col = QColor(51, 65, 85)
                label_col = QColor(71, 85, 105)

            painter.fillPath(circle_path, QBrush(bg))
            painter.strokePath(circle_path, QPen(border, 1.4 if is_hover else 1.0))

        elif theme == "oled":
            if is_down:
                bg = QColor(accent.red(), accent.green(), accent.blue(), 60)
                border = accent
                icon_col = accent
                label_col = QColor(255, 255, 255)
            elif is_hover:
                bg = QColor(accent.red(), accent.green(), accent.blue(), 40)
                border = accent
                icon_col = accent
                label_col = QColor(255, 255, 255)
            else:
                bg = QColor(12, 12, 16, 235)
                border = QColor(255, 255, 255, 35)
                icon_col = QColor(210, 215, 225)
                label_col = QColor(180, 185, 195)

            painter.fillPath(circle_path, QBrush(bg))
            painter.strokePath(circle_path, QPen(border, 1.4 if is_hover else 1.0))

        else:  # Dark mode
            grad = QLinearGradient(0, circle_rect.top(), 0, circle_rect.bottom())
            if is_down:
                grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 75))
                grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 45))
                border = accent
                icon_col = accent
                label_col = QColor(255, 255, 255)
            elif is_hover:
                grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 55))
                grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 28))
                border = accent
                icon_col = accent
                label_col = QColor(255, 255, 255)
            else:
                grad.setColorAt(0.0, QColor(42, 46, 58, 205))
                grad.setColorAt(1.0, QColor(20, 22, 30, 220))
                border = QColor(255, 255, 255, 38)
                icon_col = QColor(220, 225, 235)
                label_col = QColor(180, 190, 205)

            painter.fillPath(circle_path, QBrush(grad))
            painter.strokePath(circle_path, QPen(border, 1.4 if is_hover else 1.0))

            rim_rect = circle_rect.adjusted(1, 1, -1, -1)
            rim_path = QPainterPath()
            rim_path.addEllipse(rim_rect)
            painter.strokePath(rim_path, QPen(QColor(255, 255, 255, 24 if not is_hover else 40), 0.8))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen_w = 1.6 if is_hover else 1.4
        painter.setPen(QPen(icon_col, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        if self.action_id == "shutdown":
            arc_r = 6.5
            arc_rect = QRectF(cx - arc_r, cy - arc_r + 1.0, arc_r * 2, arc_r * 2)
            painter.drawArc(arc_rect, 130 * 16, 280 * 16)
            painter.drawLine(QPointF(cx, cy - arc_r - 0.5), QPointF(cx, cy))

        elif self.action_id == "restart":
            arc_r = 6.5
            arc_rect = QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)
            painter.drawArc(arc_rect, 45 * 16, 280 * 16)
            arr_x = cx + arc_r * 0.707
            arr_y = cy - arc_r * 0.707
            painter.drawLine(QPointF(arr_x - 2.5, arr_y - 1.5), QPointF(arr_x, arr_y))
            painter.drawLine(QPointF(arr_x + 2.0, arr_y - 2.0), QPointF(arr_x, arr_y))

        elif self.action_id == "sleep":
            moon = QPainterPath()
            moon.moveTo(cx - 2.0, cy - 7.0)
            moon.cubicTo(cx + 6.5, cy - 4.5, cx + 6.5, cy + 4.5, cx - 2.0, cy + 7.0)
            moon.cubicTo(cx + 2.5, cy + 4.5, cx + 2.5, cy - 4.5, cx - 2.0, cy - 7.0)
            painter.strokePath(moon, QPen(icon_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        elif self.action_id == "lock":
            body_w, body_h = 12.0, 9.0
            body_rect = QRectF(cx - body_w / 2.0, cy - 0.5, body_w, body_h)
            painter.drawRoundedRect(body_rect, 1.8, 1.8)
            shackle_w, shackle_h = 7.0, 7.0
            painter.drawArc(QRectF(cx - shackle_w / 2.0, cy - 6.5, shackle_w, shackle_h * 2), 0, 180 * 16)
            painter.drawPoint(QPointF(cx, cy + 3.5))

        elif self.action_id == "logout":
            door_rect = QRectF(cx - 7.0, cy - 6.5, 8.0, 13.0)
            door_path = QPainterPath()
            door_path.moveTo(door_rect.right(), door_rect.top())
            door_path.lineTo(door_rect.left(), door_rect.top())
            door_path.lineTo(door_rect.left(), door_rect.bottom())
            door_path.lineTo(door_rect.right(), door_rect.bottom())
            painter.drawPath(door_path)
            painter.drawLine(QPointF(cx - 2.5, cy), QPointF(cx + 6.5, cy))
            painter.drawLine(QPointF(cx + 3.5, cy - 3.0), QPointF(cx + 6.5, cy))
            painter.drawLine(QPointF(cx + 3.5, cy + 3.0), QPointF(cx + 6.5, cy))

        elif self.action_id == "hibernate":
            arm = 6.0
            painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))
            painter.drawLine(QPointF(cx - arm * 0.866, cy - arm * 0.5), QPointF(cx + arm * 0.866, cy + arm * 0.5))
            painter.drawLine(QPointF(cx - arm * 0.866, cy + arm * 0.5), QPointF(cx + arm * 0.866, cy - arm * 0.5))
            tip = 1.8
            painter.drawLine(QPointF(cx - tip, cy - arm + tip), QPointF(cx, cy - arm))
            painter.drawLine(QPointF(cx + tip, cy - arm + tip), QPointF(cx, cy - arm))
            painter.drawLine(QPointF(cx - tip, cy + arm - tip), QPointF(cx, cy + arm))
            painter.drawLine(QPointF(cx + tip, cy + arm - tip), QPointF(cx, cy + arm))

        label_font = QFont("Segoe UI Variable Text", 8, QFont.Weight.Medium if not is_hover else QFont.Weight.DemiBold)
        painter.setFont(label_font)
        painter.setPen(label_col)
        label_rect = QRect(0, int(cy + circle_size / 2.0 + 3), int(w), 16)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.title)


class PowerControlsCard(QWidget):
    """Frosted glass container card with Control Center style circular power actions"""
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self.init_ui()

    def set_theme(self, theme: str):
        self.theme = theme
        for btn in getattr(self, 'power_buttons', []):
            btn.set_theme(theme)
        if theme == "light":
            self.lbl_title.setStyleSheet("color: rgba(15, 23, 42, 0.75); font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px;")
            self.lbl_esc.setStyleSheet("color: rgba(100, 116, 139, 0.6); font-size: 9px;")
        else:
            self.lbl_title.setStyleSheet("color: rgba(255, 255, 255, 0.7); font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px;")
            self.lbl_esc.setStyleSheet("color: rgba(255, 255, 255, 0.35); font-size: 9px;")
        self.update()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(4)

        hdr_layout = QHBoxLayout()
        hdr_layout.setContentsMargins(4, 0, 4, 0)
        self.lbl_title = QLabel("Power Controls", self)
        hdr_layout.addWidget(self.lbl_title)

        self.lbl_esc = QLabel("Esc to close", self)
        hdr_layout.addWidget(self.lbl_esc, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(hdr_layout)

        # Single row of 6 circular action buttons centered horizontally
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 2, 0, 0)
        row_layout.setSpacing(4)
        row_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        actions = [
            ("shutdown", "Shut Down", "Power off PC", "shutdown /s /t 0"),
            ("restart", "Restart", "Reboot system", "shutdown /r /t 0"),
            ("sleep", "Sleep", "Low power mode", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"),
            ("lock", "Lock", "Protect session", "rundll32.exe user32.dll,LockWorkStation"),
            ("logout", "Log Out", "Sign out user", "shutdown /l"),
            ("hibernate", "Hibernate", "Save to disk", "shutdown /h"),
        ]

        self.power_buttons = []
        for act_id, title, sub, cmd in actions:
            btn = PowerCircleButton(act_id, title, sub, theme=self.theme, parent=self)
            btn.clicked.connect(lambda _, command=cmd: self._execute_power_action(command))
            row_layout.addWidget(btn)
            self.power_buttons.append(btn)

        layout.addLayout(row_layout)
        self.set_theme(self.theme)

    def _execute_power_action(self, cmd: str):
        try:
            import odd_sound
            odd_sound.play_sound("droplet", self.overlay.settings)
        except Exception:
            pass
        try:
            subprocess.Popen(cmd, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            try:
                err_path = Path(os.environ.get("APPDATA", "")) / "ODD" / "error.log"
                with open(err_path, "a") as f:
                    f.write(f"\\n--- Power Action Error ---\\n{e}\\n")
            except Exception:
                pass
        self.overlay.sink()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = float(self.width())
            h = float(self.height())
            rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
            from odd_theme import create_squircle_path
            card_path = create_squircle_path(rect, 18.0)
            is_light = (str(self.theme).lower() == "light")
            bg_col = QColor(245, 245, 248, 255) if is_light else QColor(8, 8, 10, 255)
            border_col = QColor(220, 220, 225, 255) if is_light else QColor(41, 41, 41, 255)
            painter.fillPath(card_path, QBrush(bg_col))
            painter.setPen(QPen(border_col, 0.8))
            painter.strokePath(card_path, painter.pen())
        finally:
            if painter.isActive():
                painter.end()


_cached_qs_hardware_state = {
    "wifi_on": True,
    "wifi_name": "Wi-Fi",
    "bt_on": False,
    "bt_name": "Bluetooth",
    "night_on": False,
    "sound_name": "Sound",
    "batt_pct": -1,
    "batt_plugged": False,
}
_cached_qs_hardware_ts = 0.0

def query_system_quick_settings_state() -> dict:
    """Fast, non-blocking hardware inspector for Windows Quick Settings via ComWorker cache"""
    try:
        worker = odd_com.ComWorker.get_instance()
        cached = worker.get_cached_hardware()
        if cached:
            return cached
        worker.request_hardware_sync()
        return worker.get_cached_hardware() or {
            "wifi_on": True, "wifi_name": "Wi-Fi", "bt_on": False, "bt_name": "OFF",
            "night_on": False, "sound_name": "Speakers", "batt_pct": -1, "batt_plugged": False
        }
    except Exception:
        return {
            "wifi_on": True, "wifi_name": "Wi-Fi", "bt_on": False, "bt_name": "OFF",
            "night_on": False, "sound_name": "Speakers", "batt_pct": -1, "batt_plugged": False
        }


def _lerp_qcolor(c1: QColor, c2: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, float(t)))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
        int(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


def _draw_quick_vector_icon(
    painter: QPainter,
    icon_type: str,
    cx: float,
    cy: float,
    icon_col: QColor,
    anim_val: float = 0.0,
    active_val: float = 0.0,
    hover_val: float = 0.0,
    phase: float = 0.0,
):
    """Draws pixel-perfect anti-aliased vector icons with subtle micro-animations for Quick Settings toggles"""
    painter.save()
    try:
        from odd_icons import get_icons8_pixmap
        col_hex = f"#{icon_col.red():02X}{icon_col.green():02X}{icon_col.blue():02X}"
        i8_pix = get_icons8_pixmap(icon_type, color=col_hex, size=20)
        if i8_pix is not None and not i8_pix.isNull():
            lift = -0.6 * hover_val
            scale = 1.0 + 0.04 * min(1.0, active_val + hover_val * 0.4)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.translate(cx, cy + lift)
            if scale != 1.0:
                painter.scale(scale, scale)
            w = i8_pix.width()
            h = i8_pix.height()
            painter.drawPixmap(int(-w / 2.0), int(-h / 2.0), i8_pix)
            # The enclosing finally restores this save exactly once. Restoring
            # here as well underflows Qt's painter stack on every Icons8 glyph.
            return

        energy = max(0.0, min(1.5, anim_val + hover_val * 0.35))
        if icon_type == "wifi":
            lift = -0.7 * hover_val - 0.9 * math.sin(phase * math.pi) * min(1.0, anim_val)
            painter.translate(0.0, lift)

            # Outer wave arc with subtle phase propagation
            outer_alpha = int(icon_col.alpha() * (0.78 + 0.22 * math.cos(phase * math.pi * 2.0) * min(1.0, energy)))
            outer_col = QColor(icon_col.red(), icon_col.green(), icon_col.blue(), max(60, min(255, outer_alpha)))
            outer_spread = 0.65 * anim_val
            painter.setPen(QPen(outer_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(
                QRectF(cx - 7.0 - outer_spread, cy - 5.5 - outer_spread * 0.7, 14.0 + outer_spread * 2.0, 10.0 + outer_spread * 1.4),
                45 * 16,
                90 * 16,
            )

            # Inner wave arc
            inner_alpha = int(icon_col.alpha() * (0.85 + 0.15 * math.sin(phase * math.pi * 2.0) * min(1.0, energy)))
            inner_col = QColor(icon_col.red(), icon_col.green(), icon_col.blue(), max(80, min(255, inner_alpha)))
            inner_spread = 0.35 * anim_val
            painter.setPen(QPen(inner_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(
                QRectF(cx - 4.5 - inner_spread, cy - 3.0 - inner_spread * 0.6, 9.0 + inner_spread * 2.0, 7.0 + inner_spread * 1.2),
                45 * 16,
                90 * 16,
            )

            # Base dot
            dot_r = 1.2 + 0.25 * energy
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx, cy + 3.0), dot_r, dot_r)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        elif icon_type == "bluetooth":
            tilt_deg = 7.0 * math.sin(phase * math.pi * 2.0) * min(1.0, anim_val) + 3.0 * hover_val
            painter.translate(cx, cy)
            painter.rotate(tilt_deg)
            painter.translate(-cx, -cy)

            painter.setPen(QPen(icon_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(QPointF(cx, cy - 6.5), QPointF(cx, cy + 6.5))
            painter.drawLine(QPointF(cx - 3.5, cy - 3.0), QPointF(cx + 3.5, cy + 3.0))
            painter.drawLine(QPointF(cx + 3.5, cy + 3.0), QPointF(cx, cy + 6.5))
            painter.drawLine(QPointF(cx - 3.5, cy + 3.0), QPointF(cx + 3.5, cy - 3.0))
            painter.drawLine(QPointF(cx + 3.5, cy - 3.0), QPointF(cx, cy - 6.5))

            # Subtle Bluetooth radio wave arcs on hover / click / active
            wave_strength = max(hover_val * 0.75, min(1.0, anim_val), active_val * 0.85)
            if wave_strength > 0.05:
                wave_col = QColor(icon_col.red(), icon_col.green(), icon_col.blue(), int(175 * wave_strength))
                painter.setPen(QPen(wave_col, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                offset = 0.8 * wave_strength
                painter.drawArc(QRectF(cx + 2.8 + offset, cy - 3.2, 3.2, 6.4), -45 * 16, 90 * 16)
                painter.drawArc(QRectF(cx - 6.0 - offset, cy - 3.2, 3.2, 6.4), 135 * 16, 90 * 16)

        elif icon_type in ("dnd", "moon", "do_not_disturb_on_total_silence"):
            # Material 3 Expressive: do_not_disturb_on_total_silence
            painter.save()
            painter.translate(cx, cy)
            # Outer boundary ring
            painter.setPen(QPen(icon_col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(0.0, 0.0), 6.5, 6.5)
            # Inner concentric ring
            painter.setPen(QPen(icon_col, 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(QPointF(0.0, 0.0), 4.2, 4.2)
            # Center silence horizontal bar
            painter.setPen(QPen(icon_col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(-3.8, 0.0), QPointF(3.8, 0.0))
            painter.restore()

        elif icon_type in ("camera", "mirror", "seeme"):
            # Clean Camera glyph for See Me (Live Camera Mirror)
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(cx - 6.2, cy - 3.8, 12.4, 8.8), 2.2, 2.2)
            # Top shutter bump
            painter.drawLine(QPointF(cx - 2.6, cy - 3.8), QPointF(cx - 1.8, cy - 5.4))
            painter.drawLine(QPointF(cx - 1.8, cy - 5.4), QPointF(cx + 1.2, cy - 5.4))
            painter.drawLine(QPointF(cx + 1.2, cy - 5.4), QPointF(cx + 2.0, cy - 3.8))
            # Circular camera lens
            painter.drawEllipse(QPointF(cx - 0.5, cy + 0.6), 2.3, 2.3)
            # Flash light dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx + 3.6, cy - 1.8), 0.85, 0.85)

        elif icon_type in ("snip", "screenshot", "tasks", "tarefas"):
            # Windows Snip selection crop box (4 corner brackets + center crosshair)
            painter.setPen(QPen(icon_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # Top-left corner
            painter.drawLine(QPointF(cx - 5.5, cy - 2.5), QPointF(cx - 5.5, cy - 5.5))
            painter.drawLine(QPointF(cx - 5.5, cy - 5.5), QPointF(cx - 2.5, cy - 5.5))
            # Top-right corner
            painter.drawLine(QPointF(cx + 2.5, cy - 5.5), QPointF(cx + 5.5, cy - 5.5))
            painter.drawLine(QPointF(cx + 5.5, cy - 5.5), QPointF(cx + 5.5, cy - 2.5))
            # Bottom-left corner
            painter.drawLine(QPointF(cx - 5.5, cy + 2.5), QPointF(cx - 5.5, cy + 5.5))
            painter.drawLine(QPointF(cx - 5.5, cy + 5.5), QPointF(cx - 2.5, cy + 5.5))
            # Bottom-right corner
            painter.drawLine(QPointF(cx + 2.5, cy + 5.5), QPointF(cx + 5.5, cy + 5.5))
            painter.drawLine(QPointF(cx + 5.5, cy + 5.5), QPointF(cx + 5.5, cy + 2.5))
            # Center crosshair
            painter.drawLine(QPointF(cx - 1.8, cy), QPointF(cx + 1.8, cy))
            painter.drawLine(QPointF(cx, cy - 1.8), QPointF(cx, cy + 1.8))

        elif icon_type == "weather":
            # Compact cloud-and-sun forecast glyph for the Quick Settings shortcut.
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx + 3.2, cy - 3.2), 2.2, 2.2)
            for angle in (0.0, 1.57, 3.14, 4.71):
                inner = QPointF(cx + 3.2 + 3.0 * math.cos(angle), cy - 3.2 + 3.0 * math.sin(angle))
                outer = QPointF(cx + 3.2 + 4.0 * math.cos(angle), cy - 3.2 + 4.0 * math.sin(angle))
                painter.drawLine(inner, outer)
            cloud = QPainterPath()
            cloud.moveTo(cx - 6.2, cy + 3.6)
            cloud.cubicTo(cx - 7.4, cy + 1.8, cx - 5.9, cy - 0.2, cx - 3.8, cy - 0.2)
            cloud.cubicTo(cx - 2.9, cy - 3.7, cx + 1.6, cy - 3.5, cx + 2.2, cy - 0.3)
            cloud.cubicTo(cx + 5.4, cy - 0.4, cx + 6.4, cy + 1.4, cx + 5.4, cy + 3.6)
            cloud.lineTo(cx - 6.2, cy + 3.6)
            painter.drawPath(cloud)

        elif icon_type == "wellness":
            # Clean water drop with internal ripple (Hydration & Eye Rest)
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            drp = QPainterPath()
            drp.moveTo(cx, cy - 6.2)
            drp.quadTo(cx - 5.0, cy + 0.2, cx, cy + 5.8)
            drp.quadTo(cx + 5.0, cy + 0.2, cx, cy - 6.2)
            drp.closeSubpath()
            painter.strokePath(drp, painter.pen())
            painter.drawArc(QRectF(cx - 2.8, cy + 1.2, 5.6, 3.0), 0, 180 * 16)

        elif icon_type == "island":
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(cx - 6.5, cy - 3.2, 13.0, 6.4), 3.2, 3.2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx + 2.2, cy), 1.2, 1.2)

        elif icon_type in ("infomatic", "edgebar", "clock"):
            # Info-matic Clock / Time Edge Bar icon (replaces old quotes)
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), 5.5, 5.5)
            # Clock hands showing ~10:10
            painter.drawLine(QPointF(cx, cy), QPointF(cx - 1.8, cy - 2.4))
            painter.drawLine(QPointF(cx, cy), QPointF(cx + 2.6, cy - 1.0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx, cy), 0.9, 0.9)

        elif icon_type in ("nightlight", "sun", "brightness", "bright"):
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), 3.4, 3.4)
            for i in range(8):
                ang = i * (math.pi / 4.0)
                x1 = cx + 4.9 * math.cos(ang)
                y1 = cy + 4.9 * math.sin(ang)
                x2 = cx + 6.8 * math.cos(ang)
                y2 = cy + 6.8 * math.sin(ang)
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        elif icon_type == "network":
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(QPointF(cx, cy), 6.5, 6.5)
            painter.drawLine(QPointF(cx - 6.5, cy), QPointF(cx + 6.5, cy))
            meridian_w = 3.5 + 1.2 * math.sin(phase * math.pi + hover_val * 0.6) * max(hover_val, min(1.0, anim_val))
            painter.drawArc(QRectF(cx - meridian_w, cy - 6.5, meridian_w * 2.0, 13.0), 0, 360 * 16)

        elif icon_type in ("sound", "volume", "vol", "audio"):
            speaker_shift = -0.35 * hover_val
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            horn = QPainterPath()
            horn.moveTo(cx - 5.5 + speaker_shift, cy - 2.8)
            horn.lineTo(cx - 2.8 + speaker_shift, cy - 2.8)
            horn.lineTo(cx + 1.5 + speaker_shift, cy - 5.8)
            horn.lineTo(cx + 1.5 + speaker_shift, cy + 5.8)
            horn.lineTo(cx - 2.8 + speaker_shift, cy + 2.8)
            horn.lineTo(cx - 5.5 + speaker_shift, cy + 2.8)
            horn.closeSubpath()
            painter.fillPath(horn, QBrush(icon_col))

            wave_shift = 0.55 * math.sin(phase * math.pi) * min(1.0, anim_val) + 0.3 * hover_val
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(cx + 2.3 + wave_shift, cy - 4.0, 4.8, 8.0), -60 * 16, 120 * 16)
            if energy > 0.12 or active_val > 0.1:
                outer_wave = QColor(icon_col.red(), icon_col.green(), icon_col.blue(), int(155 * min(1.0, energy + 0.3)))
                painter.setPen(QPen(outer_wave, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawArc(QRectF(cx + 4.0 + wave_shift * 1.2, cy - 5.5, 5.8, 11.0), -55 * 16, 110 * 16)

        elif icon_type == "battery":
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawRoundedRect(QRectF(cx - 6.0, cy - 4.0, 11.0, 8.0), 2.2, 2.2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawRoundedRect(QRectF(cx + 5.6, cy - 1.8, 1.6, 3.6), 0.6, 0.6)
            fill_ratio = 0.82 + 0.18 * math.sin(phase * math.pi) * min(1.0, anim_val) + 0.12 * hover_val
            fill_w = max(3.5, min(7.8, 7.0 * fill_ratio))
            painter.drawRoundedRect(QRectF(cx - 4.4, cy - 2.4, fill_w, 4.8), 1.2, 1.2)

        elif icon_type == "settings":
            rot = phase * 60.0 + hover_val * 24.0 + active_val * 30.0
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(rot)
            gear = QPainterPath()
            n_teeth = 8
            r_outer = 6.4
            r_inner = 5.0
            r_hole = 2.4
            for i in range(n_teeth):
                angle_center = i * (2.0 * math.pi / n_teeth)
                step = (2.0 * math.pi / n_teeth)
                tooth_half = step * 0.22
                valley_half = step * 0.28
                a1 = angle_center - tooth_half
                a2 = angle_center + tooth_half
                a3 = angle_center + step - valley_half
                if i == 0:
                    gear.moveTo(r_inner * math.cos(a1), r_inner * math.sin(a1))
                gear.lineTo(r_outer * math.cos(a1), r_outer * math.sin(a1))
                gear.lineTo(r_outer * math.cos(a2), r_outer * math.sin(a2))
                gear.lineTo(r_inner * math.cos(a2), r_inner * math.sin(a2))
                gear.lineTo(r_inner * math.cos(a3), r_inner * math.sin(a3))
            gear.closeSubpath()
            hole = QPainterPath()
            hole.addEllipse(QPointF(0.0, 0.0), r_hole, r_hole)
            gear = gear.subtracted(hole)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.fillPath(gear, QBrush(icon_col))
            painter.restore()

        elif icon_type == "display":
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawRoundedRect(QRectF(cx - 6.0, cy - 4.8, 12.0, 8.0), 2.0, 2.0)
            painter.drawLine(QPointF(cx - 2.5, cy + 4.5), QPointF(cx + 2.5, cy + 4.5))

        elif icon_type == "cable":
            # Monitor + Ethernet connector
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawRoundedRect(QRectF(cx - 6.0, cy - 5.0, 12.0, 8.0), 1.8, 1.8)
            painter.drawLine(QPointF(cx - 1.5, cy + 3.0), QPointF(cx - 1.5, cy + 5.0))
            painter.drawLine(QPointF(cx + 1.5, cy + 3.0), QPointF(cx + 1.5, cy + 5.0))
            painter.drawLine(QPointF(cx - 3.5, cy + 5.0), QPointF(cx + 3.5, cy + 5.0))
            # cable connector plug dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx + 3.2, cy + 1.2), 1.4, 1.4)

        elif icon_type in ("airplane", "aeroplane"):
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(-45.0)
            plane = QPainterPath()
            plane.moveTo(0.0, -7.0)
            plane.lineTo(1.1, -4.8)
            plane.lineTo(1.1, -1.8)
            plane.lineTo(7.0, 1.2)
            plane.lineTo(7.0, 2.4)
            plane.lineTo(1.1, 1.4)
            plane.lineTo(1.1, 4.8)
            plane.lineTo(3.4, 6.2)
            plane.lineTo(3.4, 7.0)
            plane.lineTo(0.0, 6.2)
            plane.lineTo(-3.4, 7.0)
            plane.lineTo(-3.4, 6.2)
            plane.lineTo(-1.1, 4.8)
            plane.lineTo(-1.1, 1.4)
            plane.lineTo(-7.0, 2.4)
            plane.lineTo(-7.0, 1.2)
            plane.lineTo(-1.1, -1.8)
            plane.lineTo(-1.1, -4.8)
            plane.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.fillPath(plane, QBrush(icon_col))
            painter.restore()

        elif icon_type in ("darkmode", "theme"):
            # Clean Fluent dual theme contrast icon (left half filled, right half outline)
            # ZERO tail bug: path explicitly starts at top of circle before arcing
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), 5.5, 5.5)
            half = QPainterPath()
            half.moveTo(cx, cy - 5.5)
            half.arcTo(QRectF(cx - 5.5, cy - 5.5, 11.0, 11.0), 90, 180)
            half.lineTo(cx, cy - 5.5)
            half.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.fillPath(half, QBrush(icon_col))

        elif icon_type in ("updates", "refresh", "sync"):
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(cx - 5.5, cy - 5.5, 11.0, 11.0), 35 * 16, 120 * 16)
            painter.drawArc(QRectF(cx - 5.5, cy - 5.5, 11.0, 11.0), 215 * 16, 120 * 16)
            painter.drawLine(QPointF(cx + 3.2, cy - 5.2), QPointF(cx + 5.0, cy - 4.0))
            painter.drawLine(QPointF(cx + 5.0, cy - 4.0), QPointF(cx + 4.2, cy - 1.8))
            painter.drawLine(QPointF(cx - 3.2, cy + 5.2), QPointF(cx - 5.0, cy + 4.0))
            painter.drawLine(QPointF(cx - 5.0, cy + 4.0), QPointF(cx - 4.2, cy + 1.8))

        elif icon_type in ("energysaver", "energy", "batterysaver"):
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawRoundedRect(QRectF(cx - 5.5, cy - 4.2, 10.0, 8.4), 2.0, 2.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawRoundedRect(QRectF(cx + 5.0, cy - 1.8, 1.5, 3.6), 0.6, 0.6)
            # Energy leaf inside
            leaf = QPainterPath()
            leaf.moveTo(cx - 2.8, cy + 1.8)
            leaf.quadTo(cx - 2.6, cy - 2.5, cx + 2.2, cy - 2.2)
            leaf.quadTo(cx + 2.2, cy + 2.0, cx - 2.8, cy + 1.8)
            leaf.closeSubpath()
            painter.fillPath(leaf, QBrush(icon_col))

        elif icon_type in ("nearbysharing", "nearby", "share"):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx, cy), 1.8, 1.8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(cx - 4.8, cy - 4.8, 9.6, 9.6), 30 * 16, 120 * 16)
            painter.drawArc(QRectF(cx - 4.8, cy - 4.8, 9.6, 9.6), 210 * 16, 120 * 16)
            painter.drawArc(QRectF(cx - 7.5, cy - 7.5, 15.0, 15.0), 40 * 16, 100 * 16)
            painter.drawArc(QRectF(cx - 7.5, cy - 7.5, 15.0, 15.0), 220 * 16, 100 * 16)

        elif icon_type in ("notes", "anotacoes"):
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            doc = QPainterPath()
            doc.moveTo(cx - 4.5, cy - 6.0)
            doc.lineTo(cx + 2.0, cy - 6.0)
            doc.lineTo(cx + 4.5, cy - 3.5)
            doc.lineTo(cx + 4.5, cy + 6.0)
            doc.lineTo(cx - 4.5, cy + 6.0)
            doc.closeSubpath()
            painter.drawPath(doc)
            painter.drawLine(QPointF(cx + 2.0, cy - 6.0), QPointF(cx + 2.0, cy - 3.5))
            painter.drawLine(QPointF(cx + 2.0, cy - 3.5), QPointF(cx + 4.5, cy - 3.5))
            painter.drawLine(QPointF(cx - 2.5, cy + 0.5), QPointF(cx + 2.5, cy + 0.5))
            painter.drawLine(QPointF(cx - 2.5, cy + 3.2), QPointF(cx + 1.5, cy + 3.2))

        elif icon_type in ("tasks", "tarefas"):
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for y_off in (-3.5, 0.5, 4.5):
                painter.drawLine(QPointF(cx - 5.0, cy + y_off - 1.0), QPointF(cx - 4.0, cy + y_off))
                painter.drawLine(QPointF(cx - 4.0, cy + y_off), QPointF(cx - 2.5, cy + y_off - 2.0))
                painter.drawLine(QPointF(cx - 0.5, cy + y_off - 0.5), QPointF(cx + 5.0, cy + y_off - 0.5))

        elif icon_type in ("pencil", "edit", "editar"):
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(-45.0)
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawRect(QRectF(-1.5, -4.5, 3.0, 7.5))
            painter.drawLine(QPointF(-1.5, 3.0), QPointF(0.0, 5.5))
            painter.drawLine(QPointF(1.5, 3.0), QPointF(0.0, 5.5))
            painter.restore()

        elif icon_type in ("cellular", "mobile", "signal", "vodafone"):
            tri = QPainterPath()
            tri.moveTo(cx - 5.5, cy + 5.5)
            tri.lineTo(cx + 5.5, cy + 5.5)
            tri.lineTo(cx + 5.5, cy - 5.5)
            tri.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.fillPath(tri, QBrush(icon_col))

        elif icon_type in ("sync", "autorotate", "rotate"):
            painter.setPen(QPen(icon_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(QPointF(cx - 4.5, cy - 2.2), QPointF(cx + 4.5, cy - 2.2))
            painter.drawLine(QPointF(cx + 2.5, cy - 4.2), QPointF(cx + 4.5, cy - 2.2))
            painter.drawLine(QPointF(cx + 2.5, cy - 0.2), QPointF(cx + 4.5, cy - 2.2))
            painter.drawLine(QPointF(cx + 4.5, cy + 2.2), QPointF(cx - 4.5, cy + 2.2))
            painter.drawLine(QPointF(cx - 2.5, cy + 0.2), QPointF(cx - 4.5, cy + 2.2))
            painter.drawLine(QPointF(cx - 2.5, cy + 4.2), QPointF(cx - 4.5, cy + 2.2))

        elif icon_type in ("hotspot", "broadcast"):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx, cy), 1.8, 1.8)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(cx - 5.0, cy - 5.0, 10.0, 10.0), 35 * 16, 110 * 16)
            painter.drawArc(QRectF(cx - 5.0, cy - 5.0, 10.0, 10.0), 215 * 16, 110 * 16)
            painter.drawArc(QRectF(cx - 7.8, cy - 7.8, 15.6, 15.6), 40 * 16, 100 * 16)
            painter.drawArc(QRectF(cx - 7.8, cy - 7.8, 15.6, 15.6), 220 * 16, 100 * 16)

        elif icon_type in ("torch", "flashlight"):
            fl = QPainterPath()
            fl.moveTo(cx - 3.8, cy - 5.8)
            fl.lineTo(cx + 3.8, cy - 5.8)
            fl.lineTo(cx + 2.4, cy - 1.8)
            fl.lineTo(cx + 2.4, cy + 5.8)
            fl.lineTo(cx - 2.4, cy + 5.8)
            fl.lineTo(cx - 2.4, cy - 1.8)
            fl.closeSubpath()
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.strokePath(fl, painter.pen())
            painter.drawLine(QPointF(cx, cy + 0.2), QPointF(cx, cy + 3.2))

        elif icon_type in ("record", "screenrecord"):
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine))
            painter.drawEllipse(QPointF(cx, cy), 5.6, 5.6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx, cy), 2.8, 2.8)

        elif icon_type in ("cast", "screenmirror"):
            painter.setPen(QPen(icon_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            scr = QPainterPath()
            scr.moveTo(cx - 1.5, cy + 4.5)
            scr.lineTo(cx + 5.5, cy + 4.5)
            scr.lineTo(cx + 5.5, cy - 4.5)
            scr.lineTo(cx - 5.5, cy - 4.5)
            scr.lineTo(cx - 5.5, cy + 0.5)
            painter.drawPath(scr)
            painter.drawArc(QRectF(cx - 6.5, cy + 0.5, 8.0, 8.0), 0, 90 * 16)
            painter.drawArc(QRectF(cx - 6.5, cy + 2.5, 4.0, 4.0), 0, 90 * 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawEllipse(QPointF(cx - 5.0, cy + 4.0), 0.9, 0.9)

        elif icon_type in ("wallet", "card"):
            painter.setPen(QPen(icon_col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawRoundedRect(QRectF(cx - 6.0, cy - 4.2, 12.0, 8.4), 2.0, 2.0)
            painter.drawLine(QPointF(cx - 6.0, cy - 1.2), QPointF(cx + 6.0, cy - 1.2))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(icon_col))
            painter.drawRoundedRect(QRectF(cx - 4.0, cy + 0.8, 3.2, 1.8), 0.5, 0.5)
    finally:
        painter.restore()


# =========================================================================
# High-Definition Apple Dynamic Island & Fluent Vector Weather Icons
# =========================================================================
WEATHER_SVGS = {
    "sun": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <radialGradient id="sunG" cx="38%" cy="35%" r="65%">
      <stop offset="0%" stop-color="#FFF275"/>
      <stop offset="55%" stop-color="#FFB300"/>
      <stop offset="100%" stop-color="#F57C00"/>
    </radialGradient>
  </defs>
  <g stroke="#FFA000" stroke-width="2" stroke-linecap="round">
    <line x1="12" y1="1.8" x2="12" y2="4.2"/>
    <line x1="12" y1="19.8" x2="12" y2="22.2"/>
    <line x1="1.8" y1="12" x2="4.2" y2="12"/>
    <line x1="19.8" y1="12" x2="22.2" y2="12"/>
    <line x1="4.78" y1="4.78" x2="6.48" y2="6.48"/>
    <line x1="17.52" y1="17.52" x2="19.22" y2="19.22"/>
    <line x1="4.78" y1="19.22" x2="6.48" y2="17.52"/>
    <line x1="17.52" y1="6.48" x2="19.22" y2="4.78"/>
  </g>
  <circle cx="12" cy="12" r="5.6" fill="url(#sunG)"/>
</svg>""",

    "moon": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="moonG" x1="20%" y1="0%" x2="80%" y2="100%">
      <stop offset="0%" stop-color="#FFF9C4"/>
      <stop offset="60%" stop-color="#FDD835"/>
      <stop offset="100%" stop-color="#FBC02D"/>
    </linearGradient>
  </defs>
  <path d="M15.2 2.5 A9.5 9.5 0 1 0 21.5 15.8 A8 8 0 0 1 12.8 4.2 A9.2 9.2 0 0 1 15.2 2.5 Z" 
        fill="url(#moonG)"/>
</svg>""",

    "cloud_sun": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <radialGradient id="sunSubG" cx="38%" cy="35%" r="65%">
      <stop offset="0%" stop-color="#FFF275"/>
      <stop offset="55%" stop-color="#FFB300"/>
      <stop offset="100%" stop-color="#F57C00"/>
    </radialGradient>
    <linearGradient id="cloudG1" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="65%" stop-color="#F1F5F9"/>
      <stop offset="100%" stop-color="#CBD5E1"/>
    </linearGradient>
  </defs>
  <g stroke="#FFA000" stroke-width="1.8" stroke-linecap="round">
    <line x1="15.5" y1="1.5" x2="15.5" y2="3.2"/>
    <line x1="20.5" y1="3.5" x2="19.2" y2="4.8"/>
    <line x1="22.2" y1="8.5" x2="20.5" y2="8.5"/>
    <line x1="10.5" y1="3.5" x2="11.8" y2="4.8"/>
  </g>
  <circle cx="15.5" cy="8.2" r="5.0" fill="url(#sunSubG)"/>
  <path d="M6 19 C3.8 19 2 17.2 2 15 C2 13 3.4 11.4 5.3 11.1 C6.1 8.2 8.8 6 12 6 C15.7 6 18.8 8.8 19.1 12.5 C20.2 13.2 21 14.5 21 16 C21 17.7 19.7 19 18 19 Z" 
        fill="url(#cloudG1)" stroke="rgba(148, 163, 184, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
</svg>""",

    "cloud_moon": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="moonSubG" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FFF9C4"/>
      <stop offset="100%" stop-color="#FBC02D"/>
    </linearGradient>
    <linearGradient id="cloudG2" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="65%" stop-color="#F1F5F9"/>
      <stop offset="100%" stop-color="#CBD5E1"/>
    </linearGradient>
  </defs>
  <path d="M15.5 2.5 A6.5 6.5 0 0 1 20.8 11.8 A5.5 5.5 0 0 1 15 3.2 Z" 
        fill="url(#moonSubG)"/>
  <path d="M6 19 C3.8 19 2 17.2 2 15 C2 13 3.4 11.4 5.3 11.1 C6.1 8.2 8.8 6 12 6 C15.7 6 18.8 8.8 19.1 12.5 C20.2 13.2 21 14.5 21 16 C21 17.7 19.7 19 18 19 Z" 
        fill="url(#cloudG2)" stroke="rgba(148, 163, 184, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
</svg>""",

    "cloud": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="cloudPure" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="65%" stop-color="#F8FAFC"/>
      <stop offset="100%" stop-color="#CBD5E1"/>
    </linearGradient>
  </defs>
  <path d="M6 18.5 C3.8 18.5 2 16.7 2 14.5 C2 12.5 3.4 10.9 5.3 10.6 C6.1 7.7 8.8 5.5 12 5.5 C15.7 5.5 18.8 8.3 19.1 12 C20.2 12.7 21 14 21 15.5 C21 17.2 19.7 18.5 18 18.5 Z" 
        fill="url(#cloudPure)" stroke="rgba(148, 163, 184, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
</svg>""",

    "rain_light": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="cloudRainL" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="100%" stop-color="#CBD5E1"/>
    </linearGradient>
  </defs>
  <path d="M6 16 C3.8 16 2 14.2 2 12 C2 10 3.4 8.4 5.3 8.1 C6.1 5.3 8.8 3.2 12 3.2 C15.7 3.2 18.8 6 19.1 9.6 C20.2 10.3 21 11.5 21 13 C21 14.7 19.7 16 18 16 Z" 
        fill="url(#cloudRainL)" stroke="rgba(148, 163, 184, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
  <g stroke="#38BDF8" stroke-width="2.2" stroke-linecap="round">
    <line x1="8.5" y1="18" x2="7" y2="22"/>
    <line x1="14.5" y1="18" x2="13" y2="22"/>
  </g>
</svg>""",

    "rain": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="cloudRainM" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#F1F5F9"/>
      <stop offset="100%" stop-color="#94A3B8"/>
    </linearGradient>
  </defs>
  <path d="M6 15.5 C3.8 15.5 2 13.7 2 11.5 C2 9.5 3.4 7.9 5.3 7.6 C6.1 4.8 8.8 2.7 12 2.7 C15.7 2.7 18.8 5.5 19.1 9.1 C20.2 9.8 21 11 21 12.5 C21 14.2 19.7 15.5 18 15.5 Z" 
        fill="url(#cloudRainM)" stroke="rgba(100, 116, 139, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
  <g stroke="#0ea5e9" stroke-width="2.2" stroke-linecap="round">
    <line x1="7" y1="17.5" x2="5.5" y2="22"/>
    <line x1="11.5" y1="17.5" x2="10" y2="22"/>
    <line x1="16" y1="17.5" x2="14.5" y2="22"/>
  </g>
</svg>""",

    "rain_heavy": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="cloudRainH" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#E2E8F0"/>
      <stop offset="100%" stop-color="#64748B"/>
    </linearGradient>
  </defs>
  <path d="M6 15 C3.8 15 2 13.2 2 11 C2 9 3.4 7.4 5.3 7.1 C6.1 4.3 8.8 2.2 12 2.2 C15.7 2.2 18.8 5 19.1 8.6 C20.2 9.3 21 10.5 21 12 C21 13.7 19.7 15 18 15 Z" 
        fill="url(#cloudRainH)" stroke="rgba(71, 85, 105, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
  <g stroke="#0284c7" stroke-width="2.4" stroke-linecap="round">
    <line x1="6" y1="17" x2="4" y2="22.5"/>
    <line x1="10.5" y1="17" x2="8.5" y2="22.5"/>
    <line x1="15" y1="17" x2="13" y2="22.5"/>
    <line x1="19.5" y1="17" x2="17.5" y2="22.5"/>
  </g>
</svg>""",

    "thunder": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="cloudTh" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#E2E8F0"/>
      <stop offset="100%" stop-color="#64748B"/>
    </linearGradient>
  </defs>
  <path d="M6 15.5 C3.8 15.5 2 13.7 2 11.5 C2 9.5 3.4 7.9 5.3 7.6 C6.1 4.8 8.8 2.7 12 2.7 C15.7 2.7 18.8 5.5 19.1 9.1 C20.2 9.8 21 11 21 12.5 C21 14.2 19.7 15.5 18 15.5 Z" 
        fill="url(#cloudTh)" stroke="rgba(71, 85, 105, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
  <polygon points="12.8,14 8.5,19 12,19 10.2,23.5 16,17.5 12.5,17.5" 
           fill="#FACC15" stroke="#CA8A04" stroke-width="0.6" stroke-linejoin="round"/>
</svg>""",

    "snow": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="cloudSn" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="100%" stop-color="#E2E8F0"/>
    </linearGradient>
  </defs>
  <path d="M6 15.5 C3.8 15.5 2 13.7 2 11.5 C2 9.5 3.4 7.9 5.3 7.6 C6.1 4.8 8.8 2.7 12 2.7 C15.7 2.7 18.8 5.5 19.1 9.1 C20.2 9.8 21 11 21 12.5 C21 14.2 19.7 15.5 18 15.5 Z" 
        fill="url(#cloudSn)" stroke="rgba(148, 163, 184, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
  <g fill="#38BDF8">
    <circle cx="7.5" cy="19" r="1.4"/>
    <circle cx="12" cy="21.2" r="1.5"/>
    <circle cx="16.5" cy="19" r="1.4"/>
  </g>
</svg>""",

    "snow_heavy": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="cloudSnH" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#F1F5F9"/>
      <stop offset="100%" stop-color="#CBD5E1"/>
    </linearGradient>
  </defs>
  <path d="M6 15 C3.8 15 2 13.2 2 11 C2 9 3.4 7.4 5.3 7.1 C6.1 4.3 8.8 2.2 12 2.2 C15.7 2.2 18.8 5 19.1 8.6 C20.2 9.3 21 10.5 21 12 C21 13.7 19.7 15 18 15 Z" 
        fill="url(#cloudSnH)" stroke="rgba(148, 163, 184, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
  <g fill="#38BDF8">
    <circle cx="6.5" cy="18" r="1.3"/>
    <circle cx="11.5" cy="18" r="1.3"/>
    <circle cx="16.5" cy="18" r="1.3"/>
    <circle cx="9" cy="21.5" r="1.3"/>
    <circle cx="14" cy="21.5" r="1.3"/>
  </g>
</svg>""",

    "fog": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <defs>
    <linearGradient id="cloudFg" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#FFFFFF"/>
      <stop offset="100%" stop-color="#E2E8F0"/>
    </linearGradient>
  </defs>
  <path d="M6 14 C3.8 14 2 12.2 2 10 C2 8 3.4 6.4 5.3 6.1 C6.1 3.3 8.8 1.2 12 1.2 C15.7 1.2 18.8 4 19.1 7.6 C20.2 8.3 21 9.5 21 11 C21 12.7 19.7 14 18 14 Z" 
        fill="url(#cloudFg)" stroke="rgba(148, 163, 184, 0.45)" stroke-width="0.75" stroke-linejoin="round"/>
  <g stroke="#94A3B8" stroke-width="2" stroke-linecap="round">
    <line x1="5" y1="17.5" x2="19" y2="17.5"/>
    <line x1="7" y1="21" x2="17" y2="21"/>
  </g>
</svg>""",

    "wind": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <g stroke="#38BDF8" stroke-width="2.2" stroke-linecap="round" fill="none">
    <path d="M3 8h12a3 3 0 1 0-3-3"/>
    <path d="M2 13h15a3.5 3.5 0 1 1-3.5 3.5"/>
    <path d="M5 18h7a2 2 0 1 0-2-2"/>
  </g>
</svg>"""
}

# Synonyms and condition aliases
WEATHER_SVGS["sun_cloud"] = WEATHER_SVGS["cloud_sun"]
WEATHER_SVGS["moon_cloud"] = WEATHER_SVGS["cloud_moon"]
WEATHER_SVGS["night"] = WEATHER_SVGS["moon"]
WEATHER_SVGS["drizzle"] = WEATHER_SVGS["rain_light"]
WEATHER_SVGS["thunderstorm"] = WEATHER_SVGS["thunder"]
WEATHER_SVGS["storm"] = WEATHER_SVGS["thunder"]
WEATHER_SVGS["haze"] = WEATHER_SVGS["fog"]
WEATHER_SVGS["smoke"] = WEATHER_SVGS["fog"]
WEATHER_SVGS["dust"] = WEATHER_SVGS["fog"]
WEATHER_SVGS["breeze"] = WEATHER_SVGS["wind"]

_WEATHER_SVG_RENDERERS = {}

def get_weather_svg_renderer(icon_type: str) -> QSvgRenderer:
    itype = str(icon_type).lower().strip()
    if itype in _WEATHER_SVG_RENDERERS:
        return _WEATHER_SVG_RENDERERS[itype]
    svg_str = WEATHER_SVGS.get(itype) or WEATHER_SVGS.get("cloud_sun") or WEATHER_SVGS.get("cloud")
    renderer = QSvgRenderer(QByteArray(svg_str.encode("utf-8")))
    _WEATHER_SVG_RENDERERS[itype] = renderer
    return renderer

def draw_material_cloud(painter: QPainter, cx: float, cy: float, col: QColor, size: float = 14.0):
    """Draws Material Symbols Outlined 'cloud' glyph."""
    s = size / 14.0
    pen = QPen(col, 1.45 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    path = QPainterPath()
    # Bottom flat line
    path.moveTo(cx + 4.2 * s, cy + 2.8 * s)
    path.lineTo(cx - 3.4 * s, cy + 2.8 * s)
    # Left puff curve
    path.arcTo(QRectF(cx - 6.0 * s, cy - 0.4 * s, 4.4 * s, 3.8 * s), -90, 160)
    # Main top dome
    path.arcTo(QRectF(cx - 2.8 * s, cy - 4.2 * s, 5.8 * s, 5.4 * s), 170, 160)
    # Right puff curve
    path.arcTo(QRectF(cx + 1.8 * s, cy - 1.0 * s, 4.0 * s, 4.0 * s), 70, 150)
    path.closeSubpath()
    painter.drawPath(path)

def _draw_weather_vector_icon(painter: QPainter, icon_type: str, cx: float, cy: float, col: QColor = None, size: float = 16.0):
    """Draws crisp Material Symbols Outlined 'cloud' weather vector icon."""
    c = col or Tokens.TEXT_PRIMARY
    draw_material_cloud(painter, cx, cy, c, size=size)

def render_weather_pixmap(icon_type: str, size: int = 24, color: Optional[QColor] = None) -> QPixmap:
    """Renders a standalone QPixmap with monochrome vector line weather icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = color or Tokens.TEXT_PRIMARY
        MonochromeIcons.draw(icon_type, p, QPointF(size / 2.0, size / 2.0), size=float(size * 0.82), color=c, stroke_width=1.75)
    finally:
        if p.isActive():
            p.end()
    return pix


class QuickSquircleButton(QPushButton):
    """
    Curved Corner Square (Squircle) UI for high-priority Quick Settings
    (Wi-Fi, Bluetooth, Do Not Disturb, Screenshot/Snip).
    Features rounded corners, centered vector icon, bold label, active/toggle state,
    and subtle spring/ripple micro-animations.
    """
    def __init__(self, icon_type: str, label: str, theme="dark", is_active=False, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.label = label
        self.theme = theme
        self.is_active = bool(is_active)
        self.setFixedSize(70, 52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.scale_spring = SpringValue(initial_value=1.0, response=0.13, damping_ratio=0.72)
        self.radius_spring = SpringValue(initial_value=16.0, response=0.12, damping_ratio=0.76)
        self.active_spring = SpringValue(initial_value=1.0 if self.is_active else 0.0, response=0.18, damping_ratio=0.82)
        self.hover_spring = SpringValue(initial_value=0.0, response=0.14, damping_ratio=0.85)
        self.pulse_spring = SpringValue(initial_value=0.0, response=0.22, damping_ratio=0.68)
        self.anim_phase = 0.0
        self.ripple_prog = 1.0

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

    def set_active(self, active: bool, animate: bool = True):
        active = bool(active)
        changed = (self.is_active != active)
        self.is_active = active
        if animate:
            self.active_spring.set_target(1.0 if active else 0.0, preserve_velocity=True)
            if changed:
                self.trigger_pulse()
            else:
                self._wake_anim()
        else:
            self.active_spring.snap_to(1.0 if active else 0.0)
            self.update()

    def set_label(self, label: str):
        if str(label) != self.label:
            self.label = str(label)
            self._marquee_offset = 0.0
            self._marquee_dir = 1.0
            self._marquee_pause_until = time.perf_counter() + 1.2
            self.update()

    def trigger_pulse(self):
        """Triggers a subtle tactile icon micro-animation and soft inner ripple"""
        self.pulse_spring.snap_to(1.0)
        self.pulse_spring.set_target(0.0, preserve_velocity=False)
        self.ripple_prog = 0.0
        self.anim_phase = 0.0
        self._wake_anim()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_step))
        self._last_step = now

        self.scale_spring.update(dt)
        self._anim_phase += 0.06
        self.active_spring.update(dt)
        self.hover_spring.update(dt)
        self.pulse_spring.update(dt)

        if self.ripple_prog < 1.0:
            self.ripple_prog = min(1.0, self.ripple_prog + dt * 2.8)
        if not self.pulse_spring.is_settled(0.01) or self.ripple_prog < 1.0:
            self.anim_phase = min(1.0, self.anim_phase + dt * 2.6)

        # Smooth horizontal marquee scrolling if label overflows
        text_overflows = getattr(self, "_overflow_dist", 0.0) > 0.0
        if text_overflows:
            if not hasattr(self, "_marquee_offset"):
                self._marquee_offset = 0.0
                self._marquee_dir = 1.0
                self._marquee_pause_until = now + 1.2

            if now >= self._marquee_pause_until:
                max_scroll = self._overflow_dist
                speed = 18.0  # Slow, elegant readable marquee speed in pixels/sec
                self._marquee_offset += self._marquee_dir * speed * dt
                if self._marquee_offset >= max_scroll:
                    self._marquee_offset = max_scroll
                    self._marquee_dir = -1.0
                    self._marquee_pause_until = now + 1.6  # Pause at end
                elif self._marquee_offset <= 0.0:
                    self._marquee_offset = 0.0
                    self._marquee_dir = 1.0
                    self._marquee_pause_until = now + 1.6  # Pause at beginning

        self.update()
        if (
            self.scale_spring.is_settled()
            and self.active_spring.is_settled()
            and self.hover_spring.is_settled()
            and self.pulse_spring.is_settled(0.01)
            and self.ripple_prog >= 1.0
            and not text_overflows
        ):
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # ExpressiveButtonAnimation: animatedRadius 16dp -> 6dp, animatedWeight expansion +0.25
        if hasattr(self, 'radius_spring'):
            self.radius_spring.set_target(6.0, preserve_velocity=True)
        self.scale_spring.set_target(1.06, preserve_velocity=True)
        self._wake_anim()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # ExpressiveButtonAnimation: radius returns to 16dp
        if hasattr(self, 'radius_spring'):
            self.radius_spring.set_target(16.0, preserve_velocity=True)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self.trigger_pulse()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        s = self.scale_spring.value
        act_t = max(0.0, min(1.0, self.active_spring.value))
        hov_t = max(0.0, min(1.0, self.hover_spring.value))
        pulse_t = max(0.0, min(1.2, self.pulse_spring.value))

        painter.save()
        try:
            # 1. Clean squircle background (adjusted safely inside widget bounds so corners are never clipped)
            rect = self.rect().adjusted(1, 1, -1, -1)
            r_val = self.radius_spring.value if hasattr(self, 'radius_spring') else 16.0
            r = max(4.0, min(16.0, r_val))
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), r, r)

            theme = str(self.theme).lower()
            is_down = self.isDown()

            # Elegant neutral gray tones (no bright blue)
            if theme == "light":
                if is_down:
                    # ExpressiveButtonAnimation checkedColor #554F6E and uncheckedColor #EAE5FF
                    base_bg = QColor(0x55, 0x4F, 0x6E)
                    base_border = QColor(0x55, 0x4F, 0x6E)
                    base_icon = QColor(0xEA, 0xE5, 0xFF)
                    base_text = QColor(0xEA, 0xE5, 0xFF)
                else:
                    base_bg = _lerp_qcolor(QColor(242, 244, 248, 175), QColor(234, 238, 244, 245), hov_t)
                    base_border = _lerp_qcolor(QColor(0, 0, 0, 24), QColor(0, 0, 0, 48), hov_t)
                    base_icon = _lerp_qcolor(QColor(50, 56, 68), QColor(25, 30, 40), hov_t)
                    base_text = QColor(30, 36, 48)

                # Active state: Clean elevated light slate gray
                act_bg = _lerp_qcolor(QColor(218, 224, 234, 250), QColor(208, 215, 228, 255), hov_t)
                act_border = _lerp_qcolor(QColor(160, 170, 186, 255), QColor(140, 152, 170, 255), hov_t)
                act_icon = QColor(15, 20, 30)
                act_text = QColor(15, 20, 30)
            elif theme == "oled":
                if is_down:
                    base_bg = QColor(26, 26, 32, 245)
                    base_border = QColor(255, 255, 255, 55)
                else:
                    base_bg = _lerp_qcolor(QColor(12, 12, 16, 215), QColor(24, 24, 30, 240), hov_t)
                    base_border = _lerp_qcolor(QColor(255, 255, 255, 24), QColor(255, 255, 255, 60), hov_t)
                base_icon = _lerp_qcolor(QColor(210, 214, 224), QColor(245, 245, 250), hov_t)
                base_text = QColor(230, 232, 240)

                # Active state: Sleek luminous gray
                act_bg = _lerp_qcolor(QColor(70, 74, 86, 245), QColor(84, 88, 102, 250), hov_t)
                act_border = _lerp_qcolor(QColor(255, 255, 255, 110), QColor(255, 255, 255, 160), hov_t)
                act_icon = QColor(255, 255, 255)
                act_text = QColor(255, 255, 255)
            else:  # Dark mode
                if is_down:
                    base_top = QColor(36, 40, 50, 235)
                    base_bot = QColor(22, 26, 34, 245)
                    base_border = QColor(255, 255, 255, 50)
                else:
                    base_top = _lerp_qcolor(QColor(32, 36, 46, 190), QColor(48, 54, 68, 235), hov_t)
                    base_bot = _lerp_qcolor(QColor(18, 20, 26, 200), QColor(30, 34, 44, 245), hov_t)
                    base_border = _lerp_qcolor(QColor(255, 255, 255, 26), QColor(255, 255, 255, 65), hov_t)
                base_icon = _lerp_qcolor(QColor(215, 220, 230), QColor(250, 252, 255), hov_t)
                base_text = QColor(235, 238, 245)

                # Active state: Sophisticated frosted silver/gray tone
                act_top = _lerp_qcolor(QColor(76, 82, 96, 235), QColor(92, 98, 114, 245), hov_t)
                act_bot = _lerp_qcolor(QColor(56, 62, 74, 240), QColor(68, 74, 88, 250), hov_t)
                act_border = _lerp_qcolor(QColor(255, 255, 255, 95), QColor(255, 255, 255, 140), hov_t)
                act_icon = QColor(255, 255, 255)
                act_text = QColor(255, 255, 255)

            if theme not in ("light", "oled"):
                grad = QLinearGradient(0, 0, 0, self.height())
                grad.setColorAt(0.0, _lerp_qcolor(base_top, act_top, act_t))
                grad.setColorAt(1.0, _lerp_qcolor(base_bot, act_bot, act_t))
                painter.fillPath(path, QBrush(grad))
            else:
                bg = _lerp_qcolor(base_bg, act_bg, act_t)
                painter.fillPath(path, QBrush(bg))

            border_col = _lerp_qcolor(base_border, act_border, act_t)
            painter.strokePath(path, QPen(border_col, 1.0))

            # Subtle expanding ripple ring on click / toggle
            if self.ripple_prog < 1.0:
                painter.save()
                painter.setClipPath(path)
                rip_alpha = int(75 * ((1.0 - self.ripple_prog) ** 1.5))
                rip_col = QColor(255, 255, 255, rip_alpha) if theme != "light" else QColor(0, 0, 0, rip_alpha)
                rip_r = 6.0 + self.ripple_prog * 36.0
                painter.setBrush(QBrush(rip_col))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(cx, 19.0), rip_r, rip_r)
                painter.restore()

            icon_col = _lerp_qcolor(base_icon, act_icon if theme == "light" else QColor(255, 255, 255), act_t)
            text_col = _lerp_qcolor(base_text, act_text if theme == "light" else QColor(255, 255, 255), act_t)

            # 2. Vector Icon (Upper Half) with subtle press micro-scale
            painter.save()
            if s != 1.0:
                painter.translate(cx, 19.0)
                painter.scale(s, s)
                painter.translate(-cx, -19.0)

            _draw_quick_vector_icon(
                painter,
                self.icon_type,
                cx,
                19.0,
                icon_col,
                anim_val=pulse_t,
                active_val=act_t,
                hover_val=hov_t,
                phase=self.anim_phase,
            )
            painter.restore()

            # 3. Label (Lower Half) with smooth horizontal marquee scrolling for long text
            font_weight = QFont.Weight.DemiBold if self.is_active else QFont.Weight.Medium
            font = QFont("Segoe UI Variable Text", 8, font_weight)
            painter.setFont(font)
            painter.setPen(text_col)
            fm = QFontMetrics(font)

            avail_w = max(10, int(self.width() - 8.0))
            text_w = fm.horizontalAdvance(self.label)
            lbl_rect = QRectF(4.0, 31.0, float(avail_w), 16.0)

            if text_w > avail_w:
                self._overflow_dist = float(text_w - avail_w + 4.0)
                if not self.anim_timer.isActive():
                    self.anim_timer.start()

                scroll_x = getattr(self, "_marquee_offset", 0.0)
                painter.save()
                painter.setClipRect(lbl_rect)
                text_rect = QRectF(lbl_rect.x() - scroll_x, lbl_rect.y(), float(text_w + 4.0), lbl_rect.height())
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label)
                painter.restore()
            else:
                self._overflow_dist = 0.0
                painter.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, self.label)
        finally:
            painter.restore()


class QuickCircleButton(QPushButton):
    """
    Circular Icon Button for secondary Quick Settings actions
    (Night Light, Network, Sound Output, Battery, Windows Settings).
    Features smooth spring scale, hover glow, soft ripple, and vector micro-animations.
    """
    def __init__(self, icon_type: str, tooltip_text: str = "", theme="dark", is_active=False, inverted_inactive=False, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.tooltip_text = tooltip_text
        self.theme = theme
        self.is_active = bool(is_active)
        self.inverted_inactive = bool(inverted_inactive)
        self.setFixedSize(38, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tooltip_text:
            self.setToolTip(tooltip_text)

        self.scale_spring = SpringValue(initial_value=1.0, response=0.13, damping_ratio=0.72)
        self.active_spring = SpringValue(initial_value=1.0 if self.is_active else 0.0, response=0.18, damping_ratio=0.82)
        self.hover_spring = SpringValue(initial_value=0.0, response=0.14, damping_ratio=0.85)
        self.pulse_spring = SpringValue(initial_value=0.0, response=0.22, damping_ratio=0.68)
        self.anim_phase = 0.0
        self.ripple_prog = 1.0

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

    def set_active(self, active: bool, animate: bool = True):
        active = bool(active)
        changed = (self.is_active != active)
        self.is_active = active
        if animate:
            self.active_spring.set_target(1.0 if active else 0.0, preserve_velocity=True)
            if changed:
                self.trigger_pulse()
            else:
                self._wake_anim()
        else:
            self.active_spring.snap_to(1.0 if active else 0.0)
            self.update()

    def trigger_pulse(self):
        """Triggers a subtle tactile icon micro-animation and soft circular ripple"""
        self.pulse_spring.snap_to(1.0)
        self.pulse_spring.set_target(0.0, preserve_velocity=False)
        self.ripple_prog = 0.0
        self.anim_phase = 0.0
        self._wake_anim()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_step))
        self._last_step = now

        self.scale_spring.update(dt)
        self._anim_phase += 0.06
        self.active_spring.update(dt)
        self.hover_spring.update(dt)
        self.pulse_spring.update(dt)

        if self.ripple_prog < 1.0:
            self.ripple_prog = min(1.0, self.ripple_prog + dt * 2.8)
        if not self.pulse_spring.is_settled(0.01) or self.ripple_prog < 1.0:
            self.anim_phase = min(1.0, self.anim_phase + dt * 2.6)

        self.update()
        if (
            self.scale_spring.is_settled()
            and self.active_spring.is_settled()
            and self.hover_spring.is_settled()
            and self.pulse_spring.is_settled(0.01)
            and self.ripple_prog >= 1.0
        ):
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.scale_spring.set_target(0.94, preserve_velocity=True)
        self._wake_anim()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self.trigger_pulse()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        s = self.scale_spring.value
        act_t = max(0.0, min(1.0, self.active_spring.value))
        hov_t = max(0.0, min(1.0, self.hover_spring.value))
        pulse_t = max(0.0, min(1.2, self.pulse_spring.value))

        painter.save()
        try:
            painter.translate(cx, cy)
            painter.scale(s, s)
            painter.translate(-cx, -cy)

            rect = self.rect().adjusted(1, 1, -1, -1)
            path = QPainterPath()
            path.addEllipse(QRectF(rect))

            theme = str(self.theme).lower()
            is_down = self.isDown()

            # Clean neutral gray tones (no blue)
            if theme == "light":
                if is_down:
                    base_bg = QColor(220, 224, 232, 235)
                    base_border = QColor(0, 0, 0, 45)
                else:
                    base_bg = _lerp_qcolor(QColor(242, 244, 248, 175), QColor(234, 238, 244, 245), hov_t)
                    base_border = _lerp_qcolor(QColor(0, 0, 0, 24), QColor(0, 0, 0, 48), hov_t)
                base_icon = _lerp_qcolor(QColor(50, 56, 68), QColor(25, 30, 40), hov_t)

                act_bg = _lerp_qcolor(QColor(218, 224, 234, 250), QColor(208, 215, 228, 255), hov_t)
                act_border = _lerp_qcolor(QColor(160, 170, 186, 255), QColor(140, 152, 170, 255), hov_t)
                act_icon = QColor(15, 20, 30)
            elif theme == "oled":
                if is_down:
                    base_bg = QColor(26, 26, 32, 245)
                    base_border = QColor(255, 255, 255, 55)
                else:
                    base_bg = _lerp_qcolor(QColor(12, 12, 16, 215), QColor(24, 24, 30, 240), hov_t)
                    base_border = _lerp_qcolor(QColor(255, 255, 255, 24), QColor(255, 255, 255, 60), hov_t)
                base_icon = _lerp_qcolor(QColor(210, 214, 224), QColor(245, 245, 250), hov_t)

                act_bg = _lerp_qcolor(QColor(70, 74, 86, 245), QColor(84, 88, 102, 250), hov_t)
                act_border = _lerp_qcolor(QColor(255, 255, 255, 110), QColor(255, 255, 255, 160), hov_t)
                act_icon = QColor(255, 255, 255)
            else:
                if is_down:
                    base_bg = QColor(36, 40, 50, 235)
                    base_border = QColor(255, 255, 255, 50)
                else:
                    base_bg = _lerp_qcolor(QColor(32, 36, 46, 190), QColor(48, 54, 68, 235), hov_t)
                    base_border = _lerp_qcolor(QColor(255, 255, 255, 26), QColor(255, 255, 255, 65), hov_t)
                base_icon = _lerp_qcolor(QColor(215, 220, 230), QColor(250, 252, 255), hov_t)

                act_bg = _lerp_qcolor(QColor(76, 82, 96, 245), QColor(92, 98, 114, 250), hov_t)
                act_border = _lerp_qcolor(QColor(255, 255, 255, 95), QColor(255, 255, 255, 140), hov_t)
                act_icon = QColor(255, 255, 255)

            bg = _lerp_qcolor(base_bg, act_bg, act_t)
            border = _lerp_qcolor(base_border, act_border, act_t)
            icon_col = _lerp_qcolor(base_icon, act_icon, act_t)

            painter.fillPath(path, QBrush(bg))
            painter.strokePath(path, QPen(border, 1.0))

            # Subtle circular ripple on click
            if self.ripple_prog < 1.0:
                painter.save()
                painter.setClipPath(path)
                rip_alpha = int(75 * ((1.0 - self.ripple_prog) ** 1.5))
                rip_col = QColor(255, 255, 255, rip_alpha) if theme != "light" else QColor(0, 0, 0, rip_alpha)
                rip_r = 4.0 + self.ripple_prog * 20.0
                painter.setBrush(QBrush(rip_col))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(cx, cy), rip_r, rip_r)
                painter.restore()

            # Centered Vector Icon with subtle micro-animation
            _draw_quick_vector_icon(
                painter,
                self.icon_type,
                cx,
                cy,
                icon_col,
                anim_val=pulse_t,
                active_val=act_t,
                hover_val=hov_t,
                phase=self.anim_phase,
            )
        finally:
            painter.restore()


# Retain QuickTileButton for backward compatibility
class QuickTileButton(QuickSquircleButton):
    pass


class NothingDualTileCard(QPushButton):
    """
    Nothing OS Control Center stacked rounded squircle card (Wi-Fi, Cellular / Network).
    - Height 50px
    - 34px circular icon container on left: solid white when ON, dark charcoal when OFF.
    - Two lines of text on right: Title (bold) + Subtitle
    - Clickable right chevron arrow corner if has_chevron
    - Spring micro-animations on hover/click
    """
    corner_clicked = Signal()

    def __init__(self, icon_type: str, title: str, subtitle: str, theme="dark", is_active=False, has_chevron=False, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.title = str(title)
        self.subtitle = str(subtitle)
        self.theme = theme
        self.is_active = bool(is_active)
        self.has_chevron = bool(has_chevron)
        self._corner_hovered = False
        self._press_in_corner = False
        self.setFixedHeight(50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        self.scale_spring = SpringValue(initial_value=1.0, response=0.13, damping_ratio=0.72)
        self.active_spring = SpringValue(initial_value=1.0 if self.is_active else 0.0, response=0.18, damping_ratio=0.82)
        self.hover_spring = SpringValue(initial_value=0.0, response=0.14, damping_ratio=0.85)

        try:
            from odd_useanimations import UseAnimationPlayer
            anim_n = "wifi" if "wifi" in self.icon_type.lower() else "bluetooth"
            if anim_n == "wifi" and not self.is_active:
                anim_n = "wifiOff"
            self._use_anim_player = UseAnimationPlayer(anim_n, parent=self)
            self._use_anim_player.set_active(self.is_active, animate=False)
            self._use_anim_player.frame_changed.connect(lambda _: self.update())
        except Exception:
            self._use_anim_player = None

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

    def set_active(self, active: bool, animate: bool = True):
        active = bool(active)
        self.is_active = active
        if getattr(self, '_use_anim_player', None):
            if "wifi" in self.icon_type.lower():
                target_anim = "wifi" if active else "wifiOff"
                self._use_anim_player.set_animation(target_anim)
                self._use_anim_player.replay()
            else:
                self._use_anim_player.set_active(active, animate=animate)
        if animate:
            self.active_spring.set_target(1.0 if active else 0.0, preserve_velocity=True)
            self._wake_anim()
        else:
            self.active_spring.snap_to(1.0 if active else 0.0)
            self.update()

    def set_subtitle(self, sub: str):
        self.subtitle = str(sub)
        self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_step))
        self._last_step = now
        self.scale_spring.update(dt)
        self._anim_phase += 0.06
        self.active_spring.update(dt)
        self.hover_spring.update(dt)
        self.update()
        if self.scale_spring.is_settled() and self.active_spring.is_settled() and self.hover_spring.is_settled():
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self._corner_hovered = False
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.has_chevron:
            is_c = (event.position().x() >= float(self.width()) - 26.0)
            if is_c != self._corner_hovered:
                self._corner_hovered = is_c
                self.update()

    def mousePressEvent(self, event):
        self._press_in_corner = False
        if event.button() == Qt.MouseButton.LeftButton:
            if self.has_chevron and (event.position().x() >= float(self.width()) - 26.0):
                self._press_in_corner = True
                event.accept()
                return
        self.scale_spring.set_target(0.96, preserve_velocity=True)
        self._wake_anim()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press_in_corner and event.button() == Qt.MouseButton.LeftButton:
            self._press_in_corner = False
            if self.has_chevron and (event.position().x() >= float(self.width()) - 26.0):
                self.corner_clicked.emit()
                event.accept()
                return
        self._press_in_corner = False
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            w = float(self.width())
            h = float(self.height())
            scale = float(self.scale_spring.value)

            painter.translate(w / 2.0, h / 2.0)
            painter.scale(scale, scale)
            painter.translate(-w / 2.0, -h / 2.0)

            # Squircle Card Path
            margin = 1.0
            card_rect = QRectF(margin, margin, w - margin * 2.0, h - margin * 2.0)
            from odd_theme import create_squircle_path
            path = create_squircle_path(card_rect, 14.0)

            is_light = (str(self.theme).lower() == "light")
            is_active = self.is_active
            h_val = float(self.hover_spring.value)

            # Background color
            if is_light:
                bg_col = QColor(255, 255, 255, 255) if is_active else QColor(238, 238, 242, 230)
                border_col = QColor(215, 215, 220, 240) if not is_active else QColor(190, 190, 198, 255)
            else:
                bg_col = QColor(36, 36, 42, 255) if is_active else QColor(22, 22, 26, 230)
                border_col = QColor(255, 255, 255, 45) if is_active else QColor(255, 255, 255, 22)

            if h_val > 0.01:
                bg_col = QColor(
                    min(255, int(bg_col.red() + 15 * h_val)),
                    min(255, int(bg_col.green() + 15 * h_val)),
                    min(255, int(bg_col.blue() + 15 * h_val)),
                    bg_col.alpha()
                )

            painter.fillPath(path, QBrush(bg_col))
            painter.setPen(QPen(border_col, 0.8))
            painter.strokePath(path, painter.pen())

            # Left 34px Icon Circle Plate
            icon_cx = 24.0
            icon_cy = h / 2.0
            icon_r = 17.0
            icon_rect = QRectF(icon_cx - icon_r, icon_cy - icon_r, icon_r * 2.0, icon_r * 2.0)

            if is_active:
                ic_plate_col = QColor(255, 255, 255, 255) if not is_light else QColor(20, 20, 24, 255)
            else:
                ic_plate_col = QColor(38, 38, 44, 220) if not is_light else QColor(220, 220, 226, 220)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(ic_plate_col))
            painter.drawEllipse(icon_rect)

            # Icon inside plate
            icon_glyph_col = QColor(15, 15, 18, 255) if (is_active and not is_light) else (
                QColor(255, 255, 255, 255) if (is_active and is_light) else (
                    QColor(255, 255, 255, 220) if not is_light else QColor(30, 30, 36, 220)
                )
            )

            # Draw vector icon
            itype = self.icon_type.lower()
            pen_ic = QPen(icon_glyph_col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_ic)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            if "wifi" in itype:
                for r in (3.5, 7.5, 11.5):
                    rect_arc = QRectF(icon_cx - r, icon_cy + 4.0 - r, r * 2.0, r * 2.0)
                    painter.drawArc(rect_arc, 45 * 16, 90 * 16)
                painter.setBrush(QBrush(icon_glyph_col))
                painter.drawEllipse(QPointF(icon_cx, icon_cy + 4.0), 1.3, 1.3)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            elif "blue" in itype:
                painter.drawLine(QPointF(icon_cx, icon_cy - 9.0), QPointF(icon_cx, icon_cy + 9.0))
                painter.drawLine(QPointF(icon_cx, icon_cy), QPointF(icon_cx + 5.0, icon_cy - 4.5))
                painter.drawLine(QPointF(icon_cx + 5.0, icon_cy - 4.5), QPointF(icon_cx, icon_cy - 9.0))
                painter.drawLine(QPointF(icon_cx, icon_cy), QPointF(icon_cx + 5.0, icon_cy + 4.5))
                painter.drawLine(QPointF(icon_cx + 5.0, icon_cy + 4.5), QPointF(icon_cx, icon_cy + 9.0))
                painter.drawLine(QPointF(icon_cx, icon_cy - 9.0), QPointF(icon_cx - 4.0, icon_cy - 4.5))
                painter.drawLine(QPointF(icon_cx, icon_cy + 9.0), QPointF(icon_cx - 4.0, icon_cy + 4.5))

            # Typography: Title + Subtitle
            text_x = 48.0
            text_max_w = w - text_x - (28.0 if self.has_chevron else 10.0)

            title_col = QColor(15, 23, 42, 255) if is_light else QColor(255, 255, 255, 255)
            sub_col = QColor(113, 113, 122, 210) if is_light else QColor(160, 160, 168, 200)

            f_title = QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold)
            painter.setFont(f_title)
            painter.setPen(title_col)
            fm = painter.fontMetrics()
            t_elided = fm.elidedText(self.title, Qt.TextElideMode.ElideRight, int(text_max_w))
            painter.drawText(int(text_x), int(icon_cy - 1.0), t_elided)

            f_sub = QFont("Segoe UI Variable Text", 8, QFont.Weight.Normal)
            painter.setFont(f_sub)
            painter.setPen(sub_col)
            fm_sub = painter.fontMetrics()
            s_elided = fm_sub.elidedText(self.subtitle, Qt.TextElideMode.ElideRight, int(text_max_w))
            painter.drawText(int(text_x), int(icon_cy + 13.0), s_elided)

            # Chevron on right
            if self.has_chevron:
                chev_col = QColor(180, 180, 190, 220) if not self._corner_hovered else QColor(255, 255, 255, 255)
                pen_chev = QPen(chev_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(pen_chev)
                ch_x = w - 16.0
                painter.drawLine(QPointF(ch_x - 3.0, icon_cy - 4.0), QPointF(ch_x + 1.5, icon_cy))
                painter.drawLine(QPointF(ch_x + 1.5, icon_cy), QPointF(ch_x - 3.0, icon_cy + 4.0))

        finally:
            painter.end()


# ---------------------------------------------------------------------------
# Reference Industrial-Design Quadrant Tile & Quick Settings Components
# (Redesigned per Reference Image)
# ---------------------------------------------------------------------------

class ReferenceQuadrantTile(QPushButton):
    """
    Physical ceramic squircle quadrant tile matching the reference image.
    - Off-white ceramic background (#F4F3EE / #FAF9F5)
    - Generous curved corners (radius ~22-24px)
    - Centered crisp vector icon (Wi-Fi, Bluetooth, Hotspot, Speaker)
    - Top-right status dot indicators (1 dot for Wi-Fi, 2 dots for Bluetooth)
    - Responsive hover / press physics spring feedback
    - Mouse wheel support on volume tile for seamless audio adjustment
    """
    corner_clicked = Signal()
    volume_stepped = Signal(int)

    def __init__(self, icon_type: str, title: str, subtitle: str = "", theme="dark", is_active=False, has_dots=0, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.title = str(title)
        self.subtitle = str(subtitle)
        self.theme = theme
        self.is_active = bool(is_active)
        self.has_dots = int(has_dots)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setFixedHeight(76)
        self.setMinimumWidth(82)

        self.scale_spring = SpringValue(initial_value=1.0, response=0.13, damping_ratio=0.72)
        self.active_spring = SpringValue(initial_value=1.0 if self.is_active else 0.0, response=0.18, damping_ratio=0.82)
        self.hover_spring = SpringValue(initial_value=0.0, response=0.14, damping_ratio=0.85)

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()

    def set_active(self, active: bool, animate: bool = True):
        self.is_active = bool(active)
        if animate:
            self.active_spring.set_target(1.0 if active else 0.0, preserve_velocity=True)
            self._wake_anim()
        else:
            self.active_spring.snap_to(1.0 if active else 0.0)
            self.update()

    def set_subtitle(self, sub: str):
        self.subtitle = str(sub)
        self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_step))
        self._last_step = now
        self.scale_spring.update(dt)
        self.active_spring.update(dt)
        self.hover_spring.update(dt)
        self.update()
        if self.scale_spring.is_settled() and self.active_spring.is_settled() and self.hover_spring.is_settled():
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self.scale_spring.set_target(1.02, preserve_velocity=True)
        self._wake_anim()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.corner_clicked.emit()
            event.accept()
            return
        self.scale_spring.set_target(0.96, preserve_velocity=True)
        self._wake_anim()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.scale_spring.set_target(1.0 if not self.underMouse() else 1.02, preserve_velocity=True)
        self._wake_anim()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self.icon_type in ("volume", "sound", "speaker"):
            delta = event.angleDelta().y()
            if delta > 0:
                self.volume_stepped.emit(5)
            elif delta < 0:
                self.volume_stepped.emit(-5)
            event.accept()
            return
        super().wheelEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            w = float(self.width())
            h = float(self.height())
            scale = float(self.scale_spring.value)

            painter.translate(w / 2.0, h / 2.0)
            painter.scale(scale, scale)
            painter.translate(-w / 2.0, -h / 2.0)

            # Squircle Card Path (generous radius ~16px matching reference image)
            margin = 1.0
            card_rect = QRectF(margin, margin, w - margin * 2.0, h - margin * 2.0)
            from odd_theme import create_squircle_path
            path = create_squircle_path(card_rect, 16.0)

            # Reference Image style: Off-white ceramic background
            is_active = self.is_active
            h_val = float(self.hover_spring.value)

            if is_active:
                bg_col = QColor(246, 245, 241, 255) # Clean off-white
            else:
                bg_col = QColor(238, 237, 233, 240) if self.icon_type != "hotspot" else QColor(242, 241, 237, 250)

            if h_val > 0.01:
                bg_col = QColor(255, 255, 255, 255)

            painter.fillPath(path, QBrush(bg_col))

            # Border: ultra-subtle border
            border_col = QColor(0, 0, 0, 16) if not is_active else QColor(0, 0, 0, 24)
            painter.setPen(QPen(border_col, 0.8))
            painter.strokePath(path, painter.pen())

            # Top-Right Status Dots (per reference image: 1 dot for Wi-Fi, 2 dots for BT)
            painter.setPen(Qt.PenStyle.NoPen)
            dot_col = QColor(20, 20, 24, 235) if is_active else QColor(160, 160, 165, 180)
            painter.setBrush(QBrush(dot_col))

            if self.has_dots == 1:
                painter.drawEllipse(QPointF(w - 13.0, 13.0), 2.1, 2.1)
            elif self.has_dots == 2:
                painter.drawEllipse(QPointF(w - 18.0, 13.0), 1.9, 1.9)
                painter.drawEllipse(QPointF(w - 11.5, 13.0), 1.9, 1.9)

            # Center Icon (Crisp dark vector drawing matching the reference image)
            cx = w / 2.0
            cy = h / 2.0
            icon_col = QColor(20, 20, 24, 250) if is_active else QColor(50, 50, 55, 220)
            pen = QPen(icon_col, 1.85, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            itype = self.icon_type.lower()
            if "wifi" in itype:
                painter.setBrush(QBrush(icon_col))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(cx, cy + 5.5), 1.8, 1.8)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(pen)

                r1 = 5.0
                painter.drawArc(QRectF(cx - r1, cy + 5.5 - r1, r1 * 2.0, r1 * 2.0), 45 * 16, 90 * 16)
                r2 = 9.2
                painter.drawArc(QRectF(cx - r2, cy + 5.5 - r2, r2 * 2.0, r2 * 2.0), 45 * 16, 90 * 16)
                r3 = 13.5
                painter.drawArc(QRectF(cx - r3, cy + 5.5 - r3, r3 * 2.0, r3 * 2.0), 45 * 16, 90 * 16)

            elif "blue" in itype:
                pen.setWidthF(1.9)
                painter.setPen(pen)
                spine_top = cy - 11.0
                spine_bot = cy + 11.0
                painter.drawLine(QPointF(cx, spine_top), QPointF(cx, spine_bot))
                pt_tr = QPointF(cx + 5.5, cy - 5.5)
                painter.drawLine(QPointF(cx, cy), pt_tr)
                painter.drawLine(pt_tr, QPointF(cx, spine_top))
                pt_br = QPointF(cx + 5.5, cy + 5.5)
                painter.drawLine(QPointF(cx, cy), pt_br)
                painter.drawLine(pt_br, QPointF(cx, spine_bot))
                painter.drawLine(QPointF(cx, spine_top), QPointF(cx - 4.5, cy - 5.5))
                painter.drawLine(QPointF(cx, spine_bot), QPointF(cx - 4.5, cy + 5.5))

            elif "hotspot" in itype or "cellular" in itype or "antenna" in itype:
                painter.setBrush(QBrush(icon_col))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(cx, cy), 2.2, 2.2)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(pen)

                r1 = 6.2
                painter.drawArc(QRectF(cx - r1, cy - r1, r1 * 2.0, r1 * 2.0), 135 * 16, 90 * 16)
                painter.drawArc(QRectF(cx - r1, cy - r1, r1 * 2.0, r1 * 2.0), -45 * 16, 90 * 16)
                r2 = 11.2
                painter.drawArc(QRectF(cx - r2, cy - r2, r2 * 2.0, r2 * 2.0), 135 * 16, 90 * 16)
                painter.drawArc(QRectF(cx - r2, cy - r2, r2 * 2.0, r2 * 2.0), -45 * 16, 90 * 16)

            elif "vol" in itype or "sound" in itype or "speaker" in itype:
                pen.setWidthF(1.75)
                painter.setPen(pen)
                sp_path = QPainterPath()
                sp_x = cx - 4.5
                sp_path.moveTo(sp_x - 3.5, cy - 3.2)
                sp_path.lineTo(sp_x - 1.0, cy - 3.2)
                sp_path.lineTo(sp_x + 3.2, cy - 6.8)
                sp_path.lineTo(sp_x + 3.2, cy + 6.8)
                sp_path.lineTo(sp_x - 1.0, cy + 3.2)
                sp_path.lineTo(sp_x - 3.5, cy + 3.2)
                sp_path.closeSubpath()
                painter.strokePath(sp_path, pen)

                if is_active:
                    r_w1 = 5.5
                    painter.drawArc(QRectF(sp_x + 0.8, cy - r_w1, r_w1 * 2.0, r_w1 * 2.0), -40 * 16, 80 * 16)
                    r_w2 = 9.2
                    painter.drawArc(QRectF(sp_x + 0.8, cy - r_w2, r_w2 * 2.0, r_w2 * 2.0), -40 * 16, 80 * 16)
                else:
                    slash_pen = QPen(QColor(180, 40, 40, 220), 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                    painter.setPen(slash_pen)
                    painter.drawLine(QPointF(cx + 2.5, cy - 4.5), QPointF(cx + 10.5, cy + 4.5))
        finally:
            painter.end()


class ReferenceDiamondCenter(QWidget):
    """
    Diamond center accent sitting right at the intersection of the 4 quadrant tiles.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            d_sz = 4.2
            path = QPainterPath()
            path.moveTo(cx, cy - d_sz)
            path.lineTo(cx + d_sz, cy)
            path.lineTo(cx, cy + d_sz)
            path.lineTo(cx - d_sz, cy)
            path.closeSubpath()

            painter.setPen(QPen(QColor(246, 245, 241, 255), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QBrush(QColor(20, 20, 22, 255)))
            painter.drawPath(path)
        finally:
            painter.end()


class ReferenceHeaderPill(QFrame):
    """
    Top rounded pill header with 'Quick settings' and Settings gear button.
    """
    settings_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setStyleSheet("""
            QFrame {
                background-color: #F4F3EE;
                border-radius: 16px;
            }
        """)
        h_layout = QHBoxLayout(self)
        h_layout.setContentsMargins(14, 0, 8, 0)
        h_layout.setSpacing(6)

        self.lbl_title = QLabel("Quick settings", self)
        self.lbl_title.setStyleSheet("""
            QLabel {
                color: #161618;
                font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: 700;
                background: transparent;
            }
        """)
        h_layout.addWidget(self.lbl_title)
        h_layout.addStretch(1)

        self.btn_gear = QPushButton(self)
        self.btn_gear.setFixedSize(20, 20)
        self.btn_gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_gear.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.08);
            }
        """)
        self.btn_gear.setToolTip("ODD Settings")
        self.btn_gear.clicked.connect(lambda: self.settings_clicked.emit())
        self._render_gear_icon()
        h_layout.addWidget(self.btn_gear)

    def _render_gear_icon(self):
        pix = QPixmap(18, 18)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(24, 24, 28, 230), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(9, 9), 3.0, 3.0)
        for i in range(6):
            rad = math.radians(i * 60)
            p.drawLine(QPointF(9 + 4.2 * math.cos(rad), 9 + 4.2 * math.sin(rad)),
                        QPointF(9 + 6.5 * math.cos(rad), 9 + 6.5 * math.sin(rad)))
        p.end()
        self.btn_gear.setIcon(QIcon(pix))
        self.btn_gear.setIconSize(QSize(16, 16))


# Backward compatibility alias
QuickDualTileButton = NothingDualTileCard


class NothingSquareCard(QPushButton):
    """
    Nothing OS Control Center large squircle card (Bluetooth).
    - Spans the combined height of two stacked cards (106px).
    - 38px circular icon on top: solid white when ON, dark charcoal when OFF.
    - Title + Subtitle in the middle
    - 3 indicator dots (• • •) at the bottom
    - Clickable right chevron arrow corner if has_chevron
    """
    corner_clicked = Signal()

    def __init__(self, icon_type: str, title: str, subtitle: str, theme="dark", is_active=False, has_chevron=True, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.title = str(title)
        self.subtitle = str(subtitle)
        self.theme = theme
        self.is_active = bool(is_active)
        self.has_chevron = bool(has_chevron)
        self._corner_hovered = False
        self._press_in_corner = False
        self.setFixedHeight(106)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        self.scale_spring = SpringValue(initial_value=1.0, response=0.13, damping_ratio=0.72)
        self.active_spring = SpringValue(initial_value=1.0 if self.is_active else 0.0, response=0.18, damping_ratio=0.82)
        self.hover_spring = SpringValue(initial_value=0.0, response=0.14, damping_ratio=0.85)

        try:
            from odd_useanimations import UseAnimationPlayer, canonical_anim_name
            c_name = canonical_anim_name(self.icon_type)
            if c_name in ("volume", "scissors", "clock", "camera", "wifi", "bluetooth", "smartphone"):
                self._use_anim_player = UseAnimationPlayer(self.icon_type, parent=self)
                self._use_anim_player.frame_changed.connect(lambda _: self.update())
            else:
                self._use_anim_player = None
        except Exception:
            self._use_anim_player = None

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

    def set_active(self, active: bool, animate: bool = True):
        active = bool(active)
        self.is_active = active
        if animate:
            self.active_spring.set_target(1.0 if active else 0.0, preserve_velocity=True)
            self._wake_anim()
        else:
            self.active_spring.snap_to(1.0 if active else 0.0)
            self.update()

    def set_subtitle(self, sub: str):
        self.subtitle = str(sub)
        self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_step))
        self._last_step = now
        self.scale_spring.update(dt)
        self._anim_phase += 0.06
        self.active_spring.update(dt)
        self.hover_spring.update(dt)
        self.update()
        if self.scale_spring.is_settled() and self.active_spring.is_settled() and self.hover_spring.is_settled():
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self._corner_hovered = False
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.has_chevron:
            is_c = (event.position().x() >= float(self.width()) - 26.0 and event.position().y() <= 30.0)
            if is_c != self._corner_hovered:
                self._corner_hovered = is_c
                self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.has_chevron and event.position().x() >= float(self.width()) - 26.0 and event.position().y() <= 30.0:
                self._press_in_corner = True
                self.update()
                return
            else:
                self._press_in_corner = False
                self.scale_spring.set_target(0.96, preserve_velocity=True)
                self._wake_anim()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()
        if event.button() == Qt.MouseButton.LeftButton:
            if self.has_chevron and getattr(self, '_press_in_corner', False):
                self._press_in_corner = False
                self.update()
                if event.position().x() >= float(self.width()) - 30.0 and self.rect().contains(event.position().toPoint()):
                    self.corner_clicked.emit()
                return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._draw_square_card(painter)
        finally:
            if painter.isActive():
                painter.end()

    def _draw_square_card(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = float(self.width())
        h = float(self.height())
        cx = w / 2.0
        cy = h / 2.0
        s = self.scale_spring.value
        act_t = max(0.0, min(1.0, self.active_spring.value))
        hov_t = max(0.0, min(1.0, self.hover_spring.value))

        painter.save()
        try:
            painter.translate(cx, cy)
            painter.scale(s, s)
            painter.translate(-cx, -cy)

            rect = self.rect().adjusted(1, 1, -1, -1)
            r = 18.0
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), r, r)

            theme = str(self.theme).lower()
            if theme == "light":
                card_bg = _lerp_qcolor(QColor(238, 241, 246, 220), QColor(228, 233, 242, 240), hov_t)
                card_border = QColor(0, 0, 0, 18)
                circle_off_bg = QColor(214, 218, 226)
                circle_on_bg = QColor(24, 28, 36)
                icon_off_col = QColor(50, 56, 66)
                icon_on_col = QColor(255, 255, 255)
                title_col = QColor(20, 24, 32)
                sub_col = QColor(100, 110, 125)
                dots_col = QColor(130, 140, 155)
            else:
                card_bg = _lerp_qcolor(QColor(28, 28, 30, 220), QColor(40, 40, 44, 240), hov_t)
                card_border = QColor(255, 255, 255, 18)
                circle_off_bg = QColor(44, 44, 48)
                circle_on_bg = QColor(255, 255, 255)
                icon_off_col = QColor(240, 240, 242)
                icon_on_col = QColor(18, 20, 24)
                title_col = QColor(255, 255, 255)
                sub_col = QColor(160, 160, 165)
                dots_col = QColor(90, 96, 110)

            painter.fillPath(path, QBrush(card_bg))
            painter.strokePath(path, QPen(card_border, 0.9))

            # Top circular icon (38px diameter, radius 19px)
            icon_cx = 28.0
            icon_cy = 28.0
            circle_r = 18.0
            circle_col = _lerp_qcolor(circle_off_bg, circle_on_bg, act_t)
            painter.setBrush(QBrush(circle_col))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(icon_cx, icon_cy), circle_r, circle_r)

            icon_col = _lerp_qcolor(icon_off_col, icon_on_col, act_t)
            _draw_quick_vector_icon(painter, self.icon_type, icon_cx, icon_cy, icon_col, active_val=act_t, hover_val=hov_t)

            # Chevron in upper right corner
            if self.has_chevron:
                ch_cx = w - 14.0
                ch_cy = 20.0
                ch_col = title_col if self._corner_hovered else sub_col
                painter.setPen(QPen(ch_col, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawLine(QPointF(ch_cx - 2.0, ch_cy - 3.8), QPointF(ch_cx + 1.8, ch_cy))
                painter.drawLine(QPointF(ch_cx + 1.8, ch_cy), QPointF(ch_cx - 2.0, ch_cy + 3.8))

            # Middle text: Title + Subtitle
            text_x = 12.0
            text_w = w - 24.0
            painter.setFont(QFont("Segoe UI Variable Text", 10, QFont.Weight.Bold))
            painter.setPen(title_col)
            painter.drawText(QRectF(text_x, 56.0, text_w, 18.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)

            painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Normal))
            painter.setPen(sub_col)
            painter.drawText(QRectF(text_x, 74.0, text_w, 16.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.subtitle)

            # Bottom 3 indicator dots (• • •)
            dots_y = 96.0
            dot_spacing = 6.0
            dot_r = 1.6
            for di in (-1, 0, 1):
                dot_x = cx + di * dot_spacing
                d_color = title_col if di == 0 else dots_col
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(d_color))
                painter.drawEllipse(QPointF(dot_x, dots_y), dot_r, dot_r)
        finally:
            painter.restore()


class NothingCircleButton(QPushButton):
    """
    Nothing OS Control Center 44x44 circular action button.
    Solid white when ON with dark vector icon, dark charcoal with white icon when OFF.
    """
    def __init__(self, icon_type: str, tooltip_text: str = "", theme="dark", is_active=False, inverted_inactive: bool = False, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.tooltip_text = tooltip_text
        self.theme = theme
        self.is_active = bool(is_active)
        self.inverted_inactive = bool(inverted_inactive)
        self.setFixedSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tooltip_text:
            self.setToolTip(tooltip_text)

        self.scale_spring = SpringValue(initial_value=1.0, response=0.13, damping_ratio=0.72)
        self.active_spring = SpringValue(initial_value=1.0 if self.is_active else 0.0, response=0.18, damping_ratio=0.82)
        self.hover_spring = SpringValue(initial_value=0.0, response=0.14, damping_ratio=0.85)

        try:
            from odd_useanimations import UseAnimationPlayer, canonical_anim_name
            c_name = canonical_anim_name(self.icon_type)
            if c_name in ("volume", "scissors", "clock", "camera", "wifi", "bluetooth", "smartphone"):
                self._use_anim_player = UseAnimationPlayer(self.icon_type, parent=self)
                self._use_anim_player.frame_changed.connect(lambda _: self.update())
            else:
                self._use_anim_player = None
        except Exception:
            self._use_anim_player = None

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0

    def set_active(self, active: bool, animate: bool = True):
        active = bool(active)
        self.is_active = active
        if animate:
            self.active_spring.set_target(1.0 if active else 0.0, preserve_velocity=True)
            self._wake_anim()
        else:
            self.active_spring.snap_to(1.0 if active else 0.0)
            self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_step))
        self._last_step = now
        self.scale_spring.update(dt)
        self._anim_phase += 0.06
        self.active_spring.update(dt)
        self.hover_spring.update(dt)
        self.update()
        if self.scale_spring.is_settled() and self.active_spring.is_settled() and self.hover_spring.is_settled():
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()
        if getattr(self, '_use_anim_player', None):
            self._use_anim_player.handle_hover_enter()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()
        if getattr(self, '_use_anim_player', None):
            self._use_anim_player.handle_hover_leave()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.scale_spring.set_target(0.92, preserve_velocity=True)
        self._wake_anim()
        if getattr(self, '_use_anim_player', None):
            self._use_anim_player.handle_click()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            cx = self.width() / 2.0
            cy = self.height() / 2.0
            s = self.scale_spring.value
            act_t = max(0.0, min(1.0, self.active_spring.value))
            hov_t = max(0.0, min(1.0, self.hover_spring.value))

            painter.save()
            try:
                painter.translate(cx, cy)
                painter.scale(s, s)
                painter.translate(-cx, -cy)

                circle_r = (min(self.width(), self.height()) / 2.0) - 1.5

                theme = str(self.theme).lower()
                if theme == "light":
                    off_bg = _lerp_qcolor(QColor(226, 230, 238), QColor(214, 220, 230), hov_t)
                    on_bg = QColor(24, 28, 36)
                    off_border = QColor(0, 0, 0, 20)
                    on_border = QColor(0, 0, 0, 40)
                    off_icon = QColor(40, 45, 55)
                    on_icon = QColor(255, 255, 255)
                else:
                    off_bg = _lerp_qcolor(QColor(38, 38, 42, 220), QColor(52, 52, 56, 240), hov_t)
                    on_bg = QColor(255, 255, 255)
                    off_border = QColor(255, 255, 255, 18)
                    on_border = QColor(255, 255, 255, 60)
                    off_icon = QColor(240, 240, 242)
                    on_icon = QColor(18, 20, 24)

                if getattr(self, "inverted_inactive", False):
                    # Inverted inactive: when inactive (act_t=0), colors are inverted (white button with dark icon)
                    if theme == "light":
                        off_bg = _lerp_qcolor(QColor(24, 28, 36), QColor(36, 42, 54), hov_t)
                        off_icon = QColor(255, 255, 255)
                        off_border = QColor(0, 0, 0, 50)
                        on_bg = QColor(226, 230, 238)
                        on_icon = QColor(40, 45, 55)
                        on_border = QColor(0, 0, 0, 25)
                    else:
                        off_bg = _lerp_qcolor(QColor(245, 245, 248), QColor(230, 230, 236), hov_t)
                        off_icon = QColor(18, 20, 24)
                        off_border = QColor(255, 255, 255, 75)
                        on_bg = QColor(38, 38, 42, 220)
                        on_icon = QColor(240, 240, 242)
                        on_border = QColor(255, 255, 255, 20)

                bg_col = _lerp_qcolor(off_bg, on_bg, act_t)
                border_col = _lerp_qcolor(off_border, on_border, act_t)
                icon_col = _lerp_qcolor(off_icon, on_icon, act_t)

                painter.setBrush(QBrush(bg_col))
                painter.setPen(QPen(border_col, 0.9))
                painter.drawEllipse(QPointF(cx, cy), circle_r, circle_r)

                # Icon render: check UseAnimation first, then Icons8 / PNG icons, then MonochromeIcons
                rendered_anim = False
                try:
                    from odd_useanimations import get_useanimation_pixmap
                    col_hex = f"#{icon_col.red():02X}{icon_col.green():02X}{icon_col.blue():02X}"
                    f_idx = getattr(self, '_use_anim_player', None).current_frame if getattr(self, '_use_anim_player', None) else 0
                    ua_pix = get_useanimation_pixmap(self.icon_type, frame_idx=f_idx, color=col_hex, size=22)
                    if ua_pix and not ua_pix.isNull():
                        painter.drawPixmap(int(cx - ua_pix.width() / 2.0), int(cy - ua_pix.height() / 2.0), ua_pix)
                        rendered_anim = True
                except Exception:
                    pass
                if not rendered_anim:
                    try:
                        import odd_icons
                        col_hex = f"#{icon_col.red():02X}{icon_col.green():02X}{icon_col.blue():02X}"
                        icon_pix = odd_icons.get_icons8_pixmap(self.icon_type, color=col_hex, size=22)
                        if icon_pix and not icon_pix.isNull():
                            painter.drawPixmap(int(cx - icon_pix.width() / 2.0), int(cy - icon_pix.height() / 2.0), icon_pix)
                            rendered_anim = True
                    except Exception:
                        pass
                if not rendered_anim:
                    MonochromeIcons.draw(self.icon_type, painter, QPointF(cx, cy), size=20.0, color=icon_col)
            finally:
                painter.restore()
        finally:
            painter.end()


# Backward compatibility alias
QuickActionItem = NothingCircleButton



class WakeSlider(QWidget):
    """
    Dynamic wake wave slider for volume and brightness:
    import WakeSlider from './WakeSlider';
    <WakeSlider
      defaultValue={50}
      min={0}
      max={100}
      step={1}
      bars={32}
      height={56}
      restHeight={12}
      gap={4}
      fillColor="#f5f5f5"
      trackColor="#27272a"
      sensitivity={1}
      reach={6}
      skew={0.6}
      glide={0.3}
      smoothing={100}
      showValue
      onChange={value => console.log('value', value)}
      disabled={false}
    />
    """
    valueChanged = Signal(int)

    def __init__(
        self,
        icon_type: str = "sun",
        defaultValue: int = 50,
        min_val: int = 0,
        max_val: int = 100,
        step: int = 1,
        bars: int = 32,
        height: int = 56,
        restHeight: int = 12,
        gap: int = 4,
        fillColor: str = "#f5f5f5",
        trackColor: str = "#27272a",
        sensitivity: float = 1.0,
        reach: float = 6.0,
        skew: float = 0.6,
        glide: float = 0.3,
        smoothing: float = 100.0,
        showValue: bool = True,
        disabled: bool = False,
        theme: str = "dark",
        label: str = "",
        parent=None
    ):
        super().__init__(parent)
        self.icon_type = icon_type
        self.label_title = label if label else ("Brightness" if icon_type in ("sun", "brightness") else "Volume")
        self._value = max(min_val, min(max_val, int(defaultValue)))
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.num_bars = bars
        self.slider_height = height
        self.rest_height = restHeight
        self.gap = gap
        self.fill_color_hex = fillColor
        self.track_color_hex = trackColor
        self.sensitivity = sensitivity
        self.reach = reach
        self.skew = skew
        self.glide = glide
        self.smoothing = smoothing
        self.show_value = showValue
        self.is_disabled = disabled
        self.theme = theme

        self._is_dragging = False
        self._is_muted = False
        self._hover_pos = None

        initial_focus = (float(self._value) / 100.0) * float(self.num_bars - 1)
        self._current_focus = initial_focus
        self._target_focus = initial_focus
        self._is_hovered = False

        self._bar_heights = [float(self.rest_height)] * self.num_bars
        self._anim_phase = 0.0
        self._last_emit_ts = 0.0

        self.setFixedHeight(self.slider_height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        # Pre-cached fonts to avoid GUI thread allocation in paintEvent
        self._font_title = QFont("Segoe UI Variable Display", 8.6, QFont.Weight.Medium)
        self._font_val = QFont("Segoe UI Variable Text", 8.2, QFont.Weight.Bold)

        self.anim_timer = QTimer(self)
        try:
            from odd_tier import TierManager
            self.anim_timer.setInterval(16 if TierManager.get_instance().target_fps >= 60 else 33)
        except Exception:
            self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_tick)

    def value(self) -> int:
        return self._value

    def setValue(self, val: int):
        val = max(self.min_val, min(self.max_val, int(val)))
        if self._value != val:
            self._value = val
            if not self._is_hovered and not self._is_dragging:
                self._target_focus = (float(self._value) / 100.0) * float(self.num_bars - 1)
                self._wake_anim()
            self.update()

    def set_muted(self, muted: bool):
        if self._is_muted != bool(muted):
            self._is_muted = bool(muted)
            self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def isSliderDown(self) -> bool:
        return self._is_dragging

    def _wake_anim(self):
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def _on_anim_tick(self):
        # Silky spring decay: runs during hover, drag, and settle-out equally.
        # Exponential decay coefficient k=0.72 per 16ms tick gives critically-damped feel.
        K_FOCUS = 0.82   # focus tracking spring (higher = snappier)
        K_BAR   = 0.76   # bar height settle spring (higher = snappier settle)

        focus_diff = self._target_focus - self._current_focus
        if abs(focus_diff) > 0.005:
            self._current_focus += focus_diff * K_FOCUS
        else:
            self._current_focus = self._target_focus

        if not (self._is_hovered or self._is_dragging):
            val_bar = (float(self._value) / 100.0) * float(self.num_bars - 1)
        else:
            val_bar = self._current_focus

        changed = False
        for i in range(self.num_bars):
            if self._is_hovered or self._is_dragging:
                dist = float(i) - self._current_focus
                if abs(dist) <= self.reach:
                    u = dist / self.reach
                    wake = math.cos(u * math.pi * 0.5) ** 2
                    skew = self.skew * 0.22 * (u**2 - 1.0) * (1.0 if dist >= 0 else -1.0)
                    wake = max(0.0, min(1.0, wake + skew))
                    target_h = float(self.rest_height) + (28.0 - float(self.rest_height)) * wake
                else:
                    target_h = float(self.rest_height)
            else:
                target_h = float(self.rest_height)

            diff = target_h - self._bar_heights[i]
            if abs(diff) > 0.08:
                self._bar_heights[i] += diff * K_BAR
                changed = True
            else:
                self._bar_heights[i] = target_h

        self.update()
        # Keep timer alive during hover/drag; stop only when fully settled
        if not changed and abs(focus_diff) <= 0.005 and not (self._is_hovered or self._is_dragging):
            self.anim_timer.stop()

    def _x_to_bar_focus(self, x: float) -> float:
        margin_x = 16.0
        avail_w = max(10.0, float(self.width()) - margin_x * 2.0)
        norm_x = max(0.0, min(1.0, (x - margin_x) / avail_w))
        return norm_x * float(self.num_bars - 1)

    def _x_to_value(self, x: float) -> int:
        margin_x = 16.0
        avail_w = max(10.0, float(self.width()) - margin_x * 2.0)
        pct = max(0.0, min(1.0, (x - margin_x) / avail_w))
        new_val = int(round(self.min_val + pct * (self.max_val - self.min_val)))
        if self.step > 1:
            new_val = int(round(new_val / self.step) * self.step)
        return max(self.min_val, min(self.max_val, new_val))

    def _recompute_wake_bars(self, focus: float, max_bar_h: float = 24.0):
        for i in range(self.num_bars):
            dist = float(i) - focus
            if abs(dist) <= self.reach:
                u = dist / self.reach
                w = math.cos(u * math.pi * 0.5) ** 2
                skew_comp = self.skew * 0.22 * (u**2 - 1.0) * (1.0 if dist >= 0 else -1.0)
                wake = max(0.0, min(1.0, w + skew_comp))
                self._bar_heights[i] = float(self.rest_height) + (max_bar_h - float(self.rest_height)) * wake
            else:
                self._bar_heights[i] = float(self.rest_height)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._is_hovered = True
        pos = event.position() if hasattr(event, "position") else event.pos()
        x = pos.x()
        self._hover_pos = pos
        self._target_focus = self._x_to_bar_focus(x)
        self._current_focus = self._target_focus
        # Keep timer alive: _on_anim_tick handles hover bars too
        self._wake_anim()
        self.update()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self._is_hovered = False
        self._target_focus = (float(self._value) / 100.0) * float(self.num_bars - 1)
        # Bars smoothly settle back via _on_anim_tick spring decay
        self._wake_anim()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.is_disabled:
            self._is_dragging = True
            x = event.position().x() if hasattr(event, "position") else event.x()
            self._hover_pos = event.position() if hasattr(event, "position") else event.pos()
            self._target_focus = self._x_to_bar_focus(x)
            self._current_focus = self._target_focus
            val = self._x_to_value(x)
            self._value = val
            self._last_emit_ts = time.perf_counter()
            self.valueChanged.emit(self._value)
            self._recompute_wake_bars(self._current_focus)
            self.update()

    def mouseMoveEvent(self, event):
        x = event.position().x() if hasattr(event, "position") else event.x()
        self._hover_pos = event.position() if hasattr(event, "position") else event.pos()
        self._target_focus = self._x_to_bar_focus(x)
        self._current_focus = self._target_focus
        if self._is_dragging and not self.is_disabled:
            val = self._x_to_value(x)
            if val != self._value:
                self._value = val
                now = time.perf_counter()
                # Coalesce slider events to ~35 Hz max during continuous mouse moves
                if now - self._last_emit_ts >= 0.028:
                    self._last_emit_ts = now
                    self.valueChanged.emit(self._value)
        # Immediate 0ms 1:1 hardware responsiveness for visual wake bars and handle!
        self._recompute_wake_bars(self._current_focus)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            self.valueChanged.emit(self._value)  # Send exact final value on release!
            self.update()

    def wheelEvent(self, event):
        if not self.is_disabled:
            delta = 4 if event.angleDelta().y() > 0 else -4
            new_val = max(self.min_val, min(self.max_val, self._value + delta))
            if new_val != self._value:
                self._value = new_val
                self._target_focus = (float(self._value) / 100.0) * float(self.num_bars - 1)
                self.valueChanged.emit(self._value)
                self._wake_anim()
                self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._draw_wake_slider(painter)
        finally:
            if painter.isActive():
                painter.end()

    def _draw_wake_slider(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w = float(self.width())
        h = float(self.height())
        r = 14.0

        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        capsule = QPainterPath()
        capsule.addRoundedRect(rect, r, r)

        is_light = (str(self.theme).lower() == "light")

        if is_light:
            bg_color = QColor(240, 243, 248, 235)
            border_color = QColor(0, 0, 0, 25)
            fill_col = QColor(24, 28, 36, 235)
            track_col = QColor(215, 220, 230, 200)
            text_title_col = QColor(30, 36, 48, 230)
            text_val_col = QColor(80, 90, 105, 220)
        else:
            bg_color = QColor(18, 15, 23, 225) # matching user's backgroundColor="#120F17"
            border_color = QColor(255, 255, 255, 22)
            fill_col = QColor(self.fill_color_hex) if self.fill_color_hex else QColor("#f5f5f5")
            track_col = QColor(self.track_color_hex) if self.track_color_hex else QColor("#27272a")
            text_title_col = QColor(240, 244, 250, 230)
            text_val_col = QColor(165, 175, 190, 210)

        # 1. Base card
        painter.fillPath(capsule, QBrush(bg_color))
        painter.strokePath(capsule, QPen(border_color, 0.9))

        # 1b. BorderGlow effect
        if self._hover_pos is not None:
            BorderGlowEffect.paint_glow(
                painter,
                rect,
                radius=r,
                mouse_pos=self._hover_pos,
                theme=self.theme,
                anim_phase=self._anim_phase,
                active=True
            )

        # 2. Header: Icon + Title + Value
        icon_cx = 24.0
        icon_cy = 16.0
        _draw_quick_vector_icon(painter, self.icon_type, icon_cx, icon_cy, icon_col=text_title_col, hover_val=(1.0 if self._is_hovered else 0.0), phase=self._anim_phase)

        painter.setFont(self._font_title)
        painter.setPen(text_title_col)
        painter.drawText(QRectF(38.0, 6.0, w - 100.0, 20.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label_title)

        if self.show_value:
            val_str = "Muted" if (self.icon_type in ("volume", "sound") and (self._is_muted or self._value <= 0)) else f"{self._value}%"
            painter.setFont(self._font_val)
            painter.setPen(text_val_col)
            painter.drawText(QRectF(w - 65.0, 6.0, 50.0, 20.0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, val_str)

        # 3. 32 Wake Bars
        margin_x = 16.0
        avail_w = max(10.0, w - margin_x * 2.0)
        gap = float(self.gap)
        bw = max(2.0, (avail_w - float(self.num_bars - 1) * gap) / float(self.num_bars))
        baseline_y = 50.0

        val_threshold = float(self._value) / 100.0

        if not is_light:
            b_grad = QLinearGradient(0, baseline_y - 25.0, 0, baseline_y)
            b_grad.setColorAt(0.0, QColor(255, 255, 255, 250))
            b_grad.setColorAt(0.5, fill_col)
            b_grad.setColorAt(1.0, QColor(210, 215, 225, 235))
            filled_brush = QBrush(b_grad)
        else:
            filled_brush = QBrush(fill_col)
        unfilled_brush = QBrush(track_col)
        painter.setPen(Qt.PenStyle.NoPen)

        for i in range(self.num_bars):
            bx = margin_x + float(i) * (bw + gap)
            bh = max(float(self.rest_height), min(25.0, self._bar_heights[i]))
            by = baseline_y - bh
            bar_rect = QRectF(bx, by, bw, bh)
            bar_r = bw / 2.0

            is_filled = (float(i) / float(self.num_bars - 1) <= val_threshold) and not (self._is_muted and self.icon_type in ("volume", "sound"))
            painter.setBrush(filled_brush if is_filled else unfilled_brush)
            painter.drawRoundedRect(bar_rect, bar_r, bar_r)


class CapsuleSlider(WakeSlider):
    pass

class _LegacyCapsuleSlider(QWidget):
    """
    Modern Control Center Capsule Slider:
    - 36px sleek pill with embedded vector icon on left, label, and percentage value on right.
    - Smooth continuous progress fill with dual-tone dynamic contrast.
    - Interactive dragging, clicking, and mouse wheel support.
    """
    valueChanged = Signal(int)

    def __init__(self, icon_type: str = "sun", initial_val: int = 50, theme="dark", label: str = "", parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.label_title = label if label else ("Brightness" if icon_type == "sun" else "Volume")
        self._value = max(0, min(100, int(initial_val)))
        self.theme = theme
        self._is_dragging = False
        self._is_muted = False
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def value(self) -> int:
        return self._value

    def setValue(self, val: int):
        val = max(0, min(100, int(val)))
        if self._value != val:
            self._value = val
            self.update()

    def set_muted(self, muted: bool):
        if self._is_muted != bool(muted):
            self._is_muted = bool(muted)
            self.update()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def isSliderDown(self) -> bool:
        return self._is_dragging

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._update_val_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        if self._is_dragging:
            self._update_val_from_x(event.position().x())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            self._update_val_from_x(event.position().x())

    def wheelEvent(self, event):
        delta = 4 if event.angleDelta().y() > 0 else -4
        new_val = max(0, min(100, self._value + delta))
        if new_val != self._value:
            self._value = new_val
            self.update()
            self.valueChanged.emit(self._value)

    def _update_val_from_x(self, x: float):
        w = float(self.width())
        pct = max(0.0, min(1.0, x / max(1.0, w)))
        new_val = int(round(pct * 100.0))
        if new_val != self._value:
            self._value = new_val
            self.update()
            self.valueChanged.emit(self._value)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w = float(self.width())
        h = float(self.height())
        r = h / 2.0

        rect = QRectF(0.0, 0.0, w, h)
        capsule = QPainterPath()
        capsule.addRoundedRect(rect, r, r)

        theme = str(self.theme).lower()
        is_light = (theme == "light")

        if is_light:
            track_bg = QColor(228, 232, 240, 230)
            track_border = QColor(0, 0, 0, 18)
            fill_col = QColor(24, 28, 36, 220)
            unfill_text_col = QColor(30, 36, 48, 220)
            unfill_val_col = QColor(90, 100, 115, 200)
            unfill_icon_col = QColor(40, 48, 60, 220)
            fill_text_col = QColor(255, 255, 255, 245)
            fill_val_col = QColor(255, 255, 255, 200)
            fill_icon_col = QColor(255, 255, 255, 250)
        else:
            track_bg = QColor(24, 26, 32, 220)
            track_border = QColor(255, 255, 255, 20)
            fill_col = QColor(255, 255, 255, 215)
            unfill_text_col = QColor(240, 244, 250, 220)
            unfill_val_col = QColor(160, 170, 185, 200)
            unfill_icon_col = QColor(220, 228, 240, 220)
            fill_text_col = QColor(18, 22, 28, 245)
            fill_val_col = QColor(45, 52, 65, 220)
            fill_icon_col = QColor(15, 18, 24, 250)

        # 1. Base track pill
        painter.fillPath(capsule, QBrush(track_bg))
        painter.strokePath(capsule, QPen(track_border, 0.8))

        # 2. Progress fill
        fill_pct = float(self._value) / 100.0
        fill_w = max(0.0, w * fill_pct)

        # Content positions
        icon_cx = 20.0
        icon_cy = h / 2.0
        text_x = 36.0
        text_w = max(40.0, w - text_x - 55.0)

        val_str = "Muted" if (self.icon_type in ("volume", "sound") and (self._is_muted or self._value <= 0)) else f"{self._value}%"
        title_font = QFont("Segoe UI Variable Display", 8.8, QFont.Weight.Medium)
        val_font = QFont("Segoe UI Variable Text", 8.2, QFont.Weight.Bold)

        # Layer A: Draw base unfilled content across entire slider
        _draw_quick_vector_icon(painter, self.icon_type, icon_cx, icon_cy, unfill_icon_col)
        painter.setFont(title_font)
        painter.setPen(unfill_text_col)
        painter.drawText(QRectF(text_x, 0.0, text_w, h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label_title)

        painter.setFont(val_font)
        painter.setPen(unfill_val_col)
        painter.drawText(QRectF(w - 55.0, 0.0, 42.0, h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, val_str)

        # Layer B: Draw filled portion with inverted contrast text & icon clipped to fill rect
        if fill_w > 1.0:
            painter.save()
            fill_clip = QPainterPath()
            fill_clip.addRect(QRectF(0.0, 0.0, fill_w, h))
            painter.setClipPath(capsule.intersected(fill_clip))

            # Fill color
            painter.fillRect(QRectF(0.0, 0.0, fill_w, h), QBrush(fill_col))

            # Inverted content inside fill
            _draw_quick_vector_icon(painter, self.icon_type, icon_cx, icon_cy, fill_icon_col)
            painter.setFont(title_font)
            painter.setPen(fill_text_col)
            painter.drawText(QRectF(text_x, 0.0, text_w, h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label_title)

            painter.setFont(val_font)
            painter.setPen(fill_val_col)
            painter.drawText(QRectF(w - 55.0, 0.0, 42.0, h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, val_str)
            painter.restore()


class QuickSettingsCard(QWidget):
    """
    Nothing OS Control Center Quick Settings Card:
    - Top: Dual stacked squircle cards on left (Wi-Fi, Cellular / Network) + Large Bluetooth card on right
    - Sliders: Display Brightness & Volume with Nothing OS dotted track and white pill thumb
    - Bottom: 4x2 grid of circular toggle buttons (Auto-rotate/Sync, Airplane mode, Hotspot, Flashlight, Snip, Dark mode, Cast, Power/Wallet)
    - Footer: Settings button
    """
    audio_state_ready = Signal(int, bool)
    brightness_state_ready = Signal(int)
    sys_stats_ready = Signal(dict)
    hardware_state_ready = Signal(dict)

    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self._is_muted = False
        self._last_unmuted_vol = 70
        self._user_dragging_vol_until = 0.0
        self._user_dragging_bright_until = 0.0

        self.audio_state_ready.connect(self._apply_audio_val)
        self.brightness_state_ready.connect(self._apply_brightness_val)
        self.sys_stats_ready.connect(self._apply_sys_stats)
        self.hardware_state_ready.connect(self._apply_hardware_state)

        # Connect cleanly to dedicated COM worker thread (no cross-thread COM pointers)
        try:
            worker = odd_com.ComWorker.get_instance()
            # Always marshal worker emissions to the GUI thread. Connecting Python
            # lambdas here can execute QWidget updates on the COM worker thread.
            worker.audio_state_changed.connect(self._on_worker_audio_state, Qt.ConnectionType.QueuedConnection)
            worker.brightness_state_changed.connect(self._on_worker_brightness_state, Qt.ConnectionType.QueuedConnection)
            worker.hardware_state_changed.connect(self._on_worker_hardware_state, Qt.ConnectionType.QueuedConnection)
            worker.radio_state_changed.connect(self._on_worker_radio_state, Qt.ConnectionType.QueuedConnection)
        except Exception:
            pass

        self.live_sync_timer = QTimer(self)
        self.live_sync_timer.setInterval(450)
        self.live_sync_timer.timeout.connect(self._on_live_sync_tick)

        self.init_ui()

    def sizeHint(self) -> QSize:
        if self.layout():
            lh = self.layout().sizeHint().height()
            lw = self.layout().sizeHint().width()
            return QSize(max(242, lw), max(254, lh))
        return QSize(242, 254)

    def showEvent(self, event):
        super().showEvent(event)
        # Let Qt finish laying out this card before syncing child widgets or querying
        # the COM worker. This avoids re-entrant layout changes during showEvent.
        QTimer.singleShot(0, self._refresh_if_visible)
        if hasattr(self, 'live_sync_timer') and not self.live_sync_timer.isActive():
            self.live_sync_timer.start()

    def _refresh_if_visible(self):
        if self.isVisible():
            self.refresh_state()

    @Slot(int, bool, str)
    def _on_worker_audio_state(self, volume: int, muted: bool, _device_name: str):
        self._apply_audio_val(volume, muted)

    @Slot(int, bool)
    def _on_worker_brightness_state(self, brightness: int, _supported: bool):
        self._apply_brightness_val(brightness)

    @Slot(dict)
    def _on_worker_hardware_state(self, state: dict):
        self._apply_hardware_state(state)

    @Slot(str, bool)
    def _on_worker_radio_state(self, kind: str, enable: bool):
        k = str(kind or "").strip().lower()
        if k == "bluetooth":
            self.btn_tile_bluetooth.set_active(enable, animate=True)
            self.btn_tile_bluetooth.set_subtitle("ON" if enable else "OFF")
            odd_com.ComWorker.get_instance().request_hardware_sync(force=True)
        elif k in ("wifi", "wi-fi"):
            self.btn_tile_wifi.set_active(enable, animate=True)
            odd_com.ComWorker.get_instance().request_hardware_sync(force=True)

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, 'live_sync_timer') and self.live_sync_timer.isActive():
            self.live_sync_timer.stop()

    @safe_slot
    def _on_live_sync_tick(self):
        if not self.isVisible():
            if hasattr(self, 'live_sync_timer') and self.live_sync_timer.isActive():
                self.live_sync_timer.stop()
            return
        now = time.time()
        if now >= self._user_dragging_vol_until and not self.slider_vol.isSliderDown():
            v, m = odd_com.ComWorker.get_instance().get_cached_volume()
            self._apply_audio_val(v, m)

        if now >= self._user_dragging_bright_until and not self.slider_bright.isSliderDown():
            b = odd_com.ComWorker.get_instance().get_cached_brightness()
            self._apply_brightness_val(b)

        if now - getattr(self, '_last_hw_sync_ts', 0.0) >= 1.0:
            self._last_hw_sync_ts = now
            odd_com.ComWorker.get_instance().request_hardware_sync()

    def _notify_user_interaction(self):
        if not self.overlay:
            return
        self.overlay.last_typing_time = time.time()
        if hasattr(self.overlay, 'key_inactivity_timer') and self.overlay.key_inactivity_timer.isActive():
            self.overlay.key_inactivity_timer.stop()
        if hasattr(self.overlay, 'leave_sink_timer') and self.overlay.leave_sink_timer.isActive():
            self.overlay.leave_sink_timer.stop()

    def set_theme(self, theme: str):
        self.theme = theme
        self.slider_vol.set_theme(theme)
        self.slider_bright.set_theme(theme)
        for tile in (self.btn_tile_wifi, self.btn_tile_bluetooth, getattr(self, 'btn_tile_hotspot', None), getattr(self, 'btn_tile_volume', None)):
            if tile is not None:
                tile.set_theme(theme)
        for circle in (
            getattr(self, 'btn_circle_weather', None), getattr(self, 'btn_circle_wellness', None),
            getattr(self, 'btn_circle_island', None), getattr(self, 'btn_circle_dnd', None),
            getattr(self, 'btn_circle_sound', None), getattr(self, 'btn_circle_infomatic', None),
            getattr(self, 'btn_circle_mirror', None), getattr(self, 'btn_circle_snip', None)
        ):
            if circle is not None:
                circle.set_theme(theme)
        if hasattr(self, 'btn_footer_settings') and hasattr(self.btn_footer_settings, 'set_theme'):
            self.btn_footer_settings.set_theme(theme)

        text_title_col = "#0F172A" if theme == "light" else "#FFFFFF"
        text_sub_col = "rgba(113, 113, 122, 0.75)" if theme == "light" else "rgba(255, 255, 255, 0.40)"
        self.lbl_title.setStyleSheet(f"color: #161618; font-size: 12px; font-weight: 700;")
        self.lbl_esc.setStyleSheet(f"color: {text_sub_col}; font-size: 8px;")
        self.lbl_bright_name.setStyleSheet(f"color: {text_title_col}; font-size: 10px; font-weight: 600;")
        self.lbl_bright_val.setStyleSheet(f"color: {text_sub_col}; font-size: 9px;")
        self.lbl_vol_name.setStyleSheet(f"color: {text_title_col}; font-size: 10px; font-weight: 600;")
        self.lbl_vol_val.setStyleSheet(f"color: {text_sub_col}; font-size: 9px;")
        self.update()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 1. Top Section: Header Pill matching reference image
        self.header_pill = ReferenceHeaderPill(self)
        self.header_pill.settings_clicked.connect(self._open_settings_dialog)
        layout.addWidget(self.header_pill)

        # Labels for compatibility
        self.lbl_title = self.header_pill.lbl_title
        self.lbl_esc = QLabel("Esc to close", self)
        self.lbl_esc.hide()

        # 2. Main 4-Quadrant Section (2x2 Grid with Center Diamond Cutout per reference image)
        self.quad_container = QWidget(self)
        quad_layout = QGridLayout(self.quad_container)
        quad_layout.setContentsMargins(0, 0, 0, 0)
        quad_layout.setSpacing(8)

        # Tile 1: Top-Left Wi-Fi (1 dot in top-right corner)
        self.btn_tile_wifi = ReferenceQuadrantTile("wifi", "Wi-Fi", "Connected", theme=self.theme, is_active=True, has_dots=1, parent=self.quad_container)
        self.btn_tile_wifi.setToolTip("Wi-Fi (Click to toggle | Right-click for networks)")
        self.btn_tile_wifi.clicked.connect(self._toggle_wifi)
        self.btn_tile_wifi.corner_clicked.connect(self._open_wifi_flyout)
        quad_layout.addWidget(self.btn_tile_wifi, 0, 0)

        # Tile 2: Top-Right Bluetooth (2 dots in top-right corner)
        init_hw = odd_com.ComWorker.get_instance().get_cached_hardware()
        init_bt_on = bool(init_hw.get("bt_on", False)) if init_hw else False
        init_bt_name = str(init_hw.get("bt_name", "")).strip() if init_hw else ""
        if not init_bt_name:
            init_bt_name = "ON" if init_bt_on else "OFF"
        self.btn_tile_bluetooth = ReferenceQuadrantTile("bluetooth", "Bluetooth", init_bt_name if init_bt_on else "OFF", theme=self.theme, is_active=init_bt_on, has_dots=2, parent=self.quad_container)
        self.btn_tile_bluetooth.setToolTip("Bluetooth (Click to toggle | Right-click for devices)")
        self.btn_tile_bluetooth.clicked.connect(self._toggle_bluetooth)
        self.btn_tile_bluetooth.corner_clicked.connect(self._open_bluetooth_flyout)
        quad_layout.addWidget(self.btn_tile_bluetooth, 0, 1)

        # Tile 3: Bottom-Left Hotspot / Cellular broadcast ((o))
        self.btn_tile_hotspot = ReferenceQuadrantTile("hotspot", "Hotspot", "Off", theme=self.theme, is_active=False, has_dots=0, parent=self.quad_container)
        self.btn_tile_hotspot.setToolTip("Mobile Hotspot / Network Sharing (Click to toggle)")
        self.btn_tile_hotspot.clicked.connect(self._toggle_hotspot)
        quad_layout.addWidget(self.btn_tile_hotspot, 1, 0)

        # Tile 4: Bottom-Right Audio / Volume (Speaker wave icon, scroll wheel support!)
        init_vol = 70
        init_muted = False
        try:
            import odd_island
            inst = odd_island.DynamicIslandMonitor.get_instance()
            if inst and getattr(inst, "_last_vol", -1) >= 0:
                init_vol = int(inst._last_vol)
                init_muted = bool(getattr(inst, "_last_mute", False))
            else:
                v, m, _ = get_master_volume_info()
                init_vol = int(v)
                init_muted = bool(m)
        except Exception:
            try:
                v, m, _ = get_master_volume_info()
                init_vol = int(v)
                init_muted = bool(m)
            except Exception:
                init_vol = 70
                init_muted = False

        init_vol = max(0, min(100, int(init_vol)))
        self._is_muted = bool(init_muted or init_vol <= 0)
        if init_vol > 0:
            self._last_unmuted_vol = init_vol

        self.btn_tile_volume = ReferenceQuadrantTile("volume", "Volume", "Muted" if self._is_muted else f"{init_vol}%", theme=self.theme, is_active=(not self._is_muted), has_dots=0, parent=self.quad_container)
        self.btn_tile_volume.setToolTip("Audio Volume (Scroll to adjust | Click to mute/unmute)")
        self.btn_tile_volume.clicked.connect(self._toggle_quad_mute)
        self.btn_tile_volume.volume_stepped.connect(self._on_quad_vol_step)
        quad_layout.addWidget(self.btn_tile_volume, 1, 1)

        # Center Diamond Accent at Quadrant Intersection
        self.diamond_center = ReferenceDiamondCenter(self.quad_container)
        layout.addWidget(self.quad_container)

        # Reposition diamond at exact center on resize
        def _reposition_diamond(event=None):
            cw = self.quad_container.width()
            ch = self.quad_container.height()
            self.diamond_center.move(int((cw - self.diamond_center.width()) / 2), int((ch - self.diamond_center.height()) / 2))
            self.diamond_center.raise_()
        self.quad_container.resizeEvent = _reposition_diamond

        # 3. Expandable Secondary Drawer (Sliders & Tool Controls for Full Feature Parity)
        self.drawer_widget = QWidget(self)
        drawer_layout = QVBoxLayout(self.drawer_widget)
        drawer_layout.setContentsMargins(0, 4, 0, 0)
        drawer_layout.setSpacing(6)

        # Brightness Slider
        init_b = _cached_brightness_val if _cached_brightness_val is not None else 70
        init_b = max(0, min(100, int(init_b)))
        self.lbl_bright_name = QLabel("Brightness", self)
        self.lbl_bright_name.hide()
        self.lbl_bright_val = QLabel(f"{init_b}%", self)
        self.lbl_bright_val.hide()

        self.slider_bright = WakeSlider(icon_type="sun", defaultValue=init_b, theme=self.theme, label="Brightness", parent=self)
        self.slider_bright.valueChanged.connect(self._on_bright_changed)
        drawer_layout.addWidget(self.slider_bright)

        # Volume Slider
        lbl_vol_text = "Muted" if self._is_muted else f"{init_vol}%"
        self.lbl_vol_name = QLabel("Volume", self)
        self.lbl_vol_name.hide()
        self.lbl_vol_val = QLabel(lbl_vol_text, self)
        self.lbl_vol_val.hide()

        self.slider_vol = WakeSlider(icon_type="volume", defaultValue=(0 if self._is_muted else init_vol), theme=self.theme, label="Volume", parent=self)
        self.slider_vol.set_muted(self._is_muted)
        self.slider_vol.valueChanged.connect(self._on_vol_changed)
        drawer_layout.addWidget(self.slider_vol)

        # Bottom 4x2 Grid of 44x44 Circular Buttons
        grid_circles = QGridLayout()
        grid_circles.setHorizontalSpacing(10)
        grid_circles.setVerticalSpacing(12)
        grid_circles.setContentsMargins(4, 6, 4, 4)

        self.btn_circle_weather = NothingCircleButton("weather", "ODD Weather Forecast", theme=self.theme, is_active=False, inverted_inactive=True, parent=self)
        self.btn_circle_weather.clicked.connect(self._open_weather_overlay)
        grid_circles.addWidget(self.btn_circle_weather, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_circle_wellness = NothingCircleButton("wellness", "Wellness & Health Alerts", theme=self.theme, is_active=bool(self.overlay.settings.get("enable_water_reminder", True)), parent=self)
        self.btn_circle_wellness.clicked.connect(self._toggle_wellness)
        grid_circles.addWidget(self.btn_circle_wellness, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_circle_island = NothingCircleButton("island", "Dynamic Island HUD", theme=self.theme, is_active=bool(self.overlay.settings.get("enable_dynamic_island", True)), inverted_inactive=True, parent=self)
        self.btn_circle_island.clicked.connect(self._toggle_island)
        grid_circles.addWidget(self.btn_circle_island, 0, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_circle_dnd = NothingCircleButton("dnd", "Do Not Disturb", theme=self.theme, is_active=bool(self.overlay.settings.get("dnd_enabled", False)), inverted_inactive=True, parent=self)
        self.btn_circle_dnd.clicked.connect(self._toggle_dnd)
        grid_circles.addWidget(self.btn_circle_dnd, 0, 3, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_circle_sound = NothingCircleButton("sound", "ODD Sound Effects", theme=self.theme, is_active=bool(self.overlay.settings.get("sound_enabled", True)), parent=self)
        self.btn_circle_sound.clicked.connect(self._toggle_sound)
        grid_circles.addWidget(self.btn_circle_sound, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_circle_infomatic = NothingCircleButton("infomatic", "Info-matic Edge Bar", theme=self.theme, is_active=bool(self.overlay.settings.get("edge_bar_infomatic", True)), parent=self)
        self.btn_circle_infomatic.clicked.connect(self._toggle_infomatic)
        grid_circles.addWidget(self.btn_circle_infomatic, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_circle_mirror = NothingCircleButton("seeme", "See Me live camera mirror", theme=self.theme, is_active=False, parent=self)
        self.btn_circle_mirror.clicked.connect(self._open_see_me_mirror)
        grid_circles.addWidget(self.btn_circle_mirror, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_circle_snip = NothingCircleButton("snip", "Screen Snip", theme=self.theme, is_active=False, parent=self)
        self.btn_circle_snip.clicked.connect(self._trigger_screenshot)
        grid_circles.addWidget(self.btn_circle_snip, 1, 3, alignment=Qt.AlignmentFlag.AlignCenter)

        drawer_layout.addLayout(grid_circles)
        self.drawer_widget.hide()
        layout.addWidget(self.drawer_widget)

        # Drawer toggle pill button at bottom
        self.btn_drawer_toggle = QPushButton("Sliders & Extra Tools", self)
        self.btn_drawer_toggle.setFixedHeight(24)
        self.btn_drawer_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_drawer_toggle.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 12px;
                color: rgba(255, 255, 255, 0.55);
                font-family: 'Segoe UI Variable Text', sans-serif;
                font-size: 9px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: rgba(255, 255, 255, 0.85);
            }
        """)
        self.btn_drawer_toggle.clicked.connect(self._toggle_drawer)
        layout.addWidget(self.btn_drawer_toggle)

        # Aliases for compatibility
        self.btn_wifi = self.btn_tile_wifi
        self.btn_bt = self.btn_tile_bluetooth
        self.btn_dnd = self.btn_circle_dnd
        self.btn_snip = self.btn_circle_snip
        self.btn_footer_settings = self.header_pill.btn_gear
        self.squircle_buttons = [self.btn_tile_wifi, self.btn_tile_bluetooth, self.btn_tile_hotspot, self.btn_tile_volume]
        self.circle_buttons = [
            self.btn_circle_weather, self.btn_circle_wellness, self.btn_circle_island, self.btn_circle_dnd,
            self.btn_circle_sound, self.btn_circle_infomatic, self.btn_circle_mirror, self.btn_circle_snip
        ]

        self.set_theme(self.theme)
        self.refresh_state()

    def _toggle_drawer(self):
        self._notify_user_interaction()
        new_vis = not self.drawer_widget.isVisible()
        self.drawer_widget.setVisible(new_vis)
        self.btn_drawer_toggle.setText("Collapse Sliders & Tools" if new_vis else "Sliders & Extra Tools")
        self.updateGeometry()

        new_h = self.sizeHint().height()
        self.setFixedHeight(new_h)

        p = self.parentWidget()
        if p:
            if hasattr(p, "adjust_geometry_to_screen"):
                p.adjust_geometry_to_screen()
            else:
                p.adjustSize()

        if self.overlay and hasattr(self.overlay, "animate_to_geometry") and self.isVisible():
            try:
                screen = QGuiApplication.screenAt(self.overlay.pos()) or QApplication.primaryScreen()
                s_rect = screen.availableGeometry()
                target_h = self.overlay._get_resting_search_height() + 6 + new_h + 8
                max_allowed_h = s_rect.height() - getattr(self.overlay, "edge_offset", 0) - 20
                if target_h > max_allowed_h:
                    target_h = max_allowed_h
                self.overlay.animate_to_geometry(self.overlay.capsule_width_contracted, target_h)
            except Exception:
                pass
        self.update()

    def _on_quad_vol_step(self, step: int):
        self._notify_user_interaction()
        worker = odd_com.ComWorker.get_instance()
        v, _ = worker.get_cached_volume()
        new_v = max(0, min(100, v + step))
        self._on_vol_changed(new_v)

    def _toggle_quad_mute(self):
        self._notify_user_interaction()
        self._is_muted = not self._is_muted
        if self._is_muted:
            self._on_vol_changed(0)
        else:
            target_v = self._last_unmuted_vol if self._last_unmuted_vol > 0 else 70
            self._on_vol_changed(target_v)

    def _toggle_hotspot(self):
        self._notify_user_interaction()
        new_st = not self.btn_tile_hotspot.is_active
        self.btn_tile_hotspot.set_active(new_st, animate=True)
        self.btn_tile_hotspot.set_subtitle("Active" if new_st else "Off")
        try:
            subprocess.Popen("start ms-settings:network-mobilehotspot", shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
        except Exception:
            pass

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = float(self.width())
            h = float(self.height())
            rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
            from odd_theme import create_squircle_path
            card_path = create_squircle_path(rect, 24.0)
            is_light = (str(self.theme).lower() == "light")
            bg_col = QColor(230, 229, 224, 255) if is_light else QColor(24, 24, 26, 255)
            border_col = QColor(200, 200, 205, 255) if is_light else QColor(48, 48, 52, 255)
            painter.fillPath(card_path, QBrush(bg_col))
            painter.setPen(QPen(border_col, 1.0))
            painter.strokePath(card_path, painter.pen())
        finally:
            if painter.isActive():
                painter.end()

    def _open_weather_overlay(self):
        self._notify_user_interaction()
        if self.overlay and hasattr(self.overlay, "toggle_weather_panel"):
            self.overlay.toggle_weather_panel()

    def _toggle_wellness(self):
        self._notify_user_interaction()
        new_st = not bool(self.overlay.settings.get("enable_water_reminder", True))
        self.overlay.settings["enable_water_reminder"] = new_st
        self.overlay.settings["enable_eye_rest_reminder"] = new_st
        self.btn_circle_wellness.set_active(new_st, animate=True)
        try:
            import odd_wellness
            odd_wellness.WellnessManager.get_instance().update_settings(self.overlay.settings)
        except Exception:
            pass
        try:
            import odd_settings
            odd_settings.save_settings(self.overlay.settings)
        except Exception:
            pass
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
        except Exception:
            pass

    def _toggle_island(self):
        self._notify_user_interaction()
        new_st = not bool(self.overlay.settings.get("enable_dynamic_island", True))
        self.overlay.settings["enable_dynamic_island"] = new_st
        self.btn_circle_island.set_active(new_st, animate=True)
        if hasattr(self.overlay, 'trigger_window') and self.overlay.trigger_window:
            self.overlay.trigger_window.settings["enable_dynamic_island"] = new_st
        try:
            import odd_settings
            odd_settings.save_settings(self.overlay.settings)
        except Exception:
            pass
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
        except Exception:
            pass

    def _toggle_sound(self):
        self._notify_user_interaction()
        new_st = not bool(self.overlay.settings.get("sound_enabled", True))
        self.overlay.settings["sound_enabled"] = new_st
        self.btn_circle_sound.set_active(new_st, animate=True)
        try:
            import odd_settings
            odd_settings.save_settings(self.overlay.settings)
        except Exception:
            pass
        if new_st:
            try:
                odd_sound.play_sound("droplet", enabled=True, volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
            except Exception:
                pass

    def _toggle_infomatic(self):
        self._notify_user_interaction()
        new_st = not bool(self.overlay.settings.get("edge_bar_infomatic", True))
        self.overlay.settings["edge_bar_infomatic"] = new_st
        self.btn_circle_infomatic.set_active(new_st, animate=True)
        if hasattr(self.overlay, 'trigger_window') and self.overlay.trigger_window:
            self.overlay.trigger_window.settings["edge_bar_infomatic"] = new_st
            self.overlay.trigger_window.reposition()
            self.overlay.trigger_window.update()
        try:
            import odd_settings
            odd_settings.save_settings(self.overlay.settings)
        except Exception:
            pass
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
        except Exception:
            pass

    def _open_see_me_mirror(self):
        self._notify_user_interaction()
        try:
            import odd_camera
            odd_camera.SeeMeOverlay.instance().open_overlay()
        except Exception as e:
            print(f"[ODD QuickSettings] Error launching See Me: {e}")

    def _check_updates(self):
        self._notify_user_interaction()
        try:
            import odd_updater
            odd_updater.check_for_updates_background(notify_ui=True)
        except Exception:
            pass

    def _open_quick_notes(self):
        self._notify_user_interaction()
        try:
            subprocess.Popen("notepad.exe")
        except Exception:
            pass
        QTimer.singleShot(150, self.overlay.sink)

    def _open_settings_dialog(self):
        self._notify_user_interaction()
        if hasattr(self.overlay, 'on_open_settings') and callable(self.overlay.on_open_settings):
            self.overlay.on_open_settings()
        else:
            self._open_protocol("ms-settings:")

    def _toggle_dnd(self):
        self._notify_user_interaction()
        cur = bool(self.overlay.settings.get("dnd_enabled", False))
        new_dnd = not cur
        self.overlay.settings["dnd_enabled"] = new_dnd
        if hasattr(self.overlay, 'trigger_window') and self.overlay.trigger_window:
            try:
                self.overlay.trigger_window.settings["dnd_enabled"] = new_dnd
            except Exception:
                pass
        try:
            import odd_settings
            odd_settings.save_settings(self.overlay.settings)
        except Exception:
            pass
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
        except Exception:
            pass
        if new_dnd and hasattr(self.overlay, 'trigger_window') and self.overlay.trigger_window:
            if hasattr(self.overlay.trigger_window, 'bezel_hud') and self.overlay.trigger_window.bezel_hud:
                self.overlay.trigger_window.bezel_hud.cancel_notification()

    @safe_slot
    def refresh_state(self):
        # Sync ODD added quick settings button states from active settings
        if hasattr(self, 'btn_circle_weather'):
            self.btn_circle_weather.set_active(False, animate=False)
        if hasattr(self, 'btn_circle_wellness'):
            self.btn_circle_wellness.set_active(bool(self.overlay.settings.get("enable_water_reminder", True)), animate=False)
        if hasattr(self, 'btn_circle_island'):
            self.btn_circle_island.set_active(bool(self.overlay.settings.get("enable_dynamic_island", True)), animate=False)
        if hasattr(self, 'btn_circle_dnd'):
            self.btn_circle_dnd.set_active(bool(self.overlay.settings.get("dnd_enabled", False)), animate=False)
        if hasattr(self, 'btn_circle_sound'):
            self.btn_circle_sound.set_active(bool(self.overlay.settings.get("sound_enabled", True)), animate=False)
        if hasattr(self, 'btn_circle_infomatic'):
            self.btn_circle_infomatic.set_active(bool(self.overlay.settings.get("edge_bar_infomatic", True)), animate=False)
        if hasattr(self, 'btn_circle_mirror'):
            self.btn_circle_mirror.set_active(False, animate=False)
        if hasattr(self, 'btn_circle_snip'):
            self.btn_circle_snip.set_active(False, animate=False)

        worker = odd_com.ComWorker.get_instance()
        cached_hw = worker.get_cached_hardware()
        if cached_hw:
            self._apply_hardware_state(cached_hw)

        v, m = worker.get_cached_volume()
        self._apply_audio_val(v, m)

        b = worker.get_cached_brightness()
        self._apply_brightness_val(b)

        # Trigger async queries safely on COM worker thread (zero thread spawning!)
        worker.request_hardware_sync(force=True)
        worker.request_audio_sync()
        worker.request_brightness_sync()

    @safe_slot
    def _apply_hardware_state(self, state: dict):
        if not state:
            return

        if time.time() >= getattr(self, '_user_toggled_wifi_until', 0.0):
            wifi_on = bool(state.get("wifi_on", False))
            wifi_name = str(state.get("wifi_name", "")).strip() or ("Connected" if wifi_on else "Off")
            self.btn_tile_wifi.set_active(wifi_on, animate=False)
            self.btn_tile_wifi.set_subtitle(wifi_name)

        if time.time() >= getattr(self, '_user_toggled_bt_until', 0.0):
            bt_on = bool(state.get("bt_on", False))
            bt_name = str(state.get("bt_name", "")).strip() or ("ON" if bt_on else "OFF")
            self.btn_tile_bluetooth.set_active(bt_on, animate=False)
            self.btn_tile_bluetooth.set_subtitle(bt_name if bt_on else "OFF")

        if hasattr(self, 'btn_circle_airplane'):
            self.btn_circle_airplane.set_active(False, animate=False)

    @safe_slot
    def _apply_audio_val(self, vol: int, muted: bool):
        if not hasattr(self, 'slider_vol') or not self.slider_vol:
            return
        if time.time() < self._user_dragging_vol_until or self.slider_vol.isSliderDown():
            return
        vol = max(0, min(100, int(vol)))
        if vol > 0:
            self._last_unmuted_vol = vol
        is_effectively_muted = bool(muted) or (vol <= 0)
        self._is_muted = is_effectively_muted
        self.slider_vol.blockSignals(True)
        try:
            self.slider_vol.set_muted(is_effectively_muted)
            self.slider_vol.setValue(0 if is_effectively_muted else vol)
        finally:
            self.slider_vol.blockSignals(False)

        if hasattr(self, 'btn_tile_volume') and self.btn_tile_volume:
            self.btn_tile_volume.set_active(not is_effectively_muted and vol > 0, animate=False)
            self.btn_tile_volume.set_subtitle("Muted" if is_effectively_muted else f"{vol}%")

        if is_effectively_muted:
            self.lbl_vol_val.setText("Muted")
        else:
            self.lbl_vol_val.setText(f"{vol}%")

    def _apply_sys_stats(self, stats: dict):
        pass

    @safe_slot
    def _apply_brightness_val(self, b: int):
        if not hasattr(self, 'slider_bright') or not self.slider_bright:
            return
        if time.time() < self._user_dragging_bright_until or self.slider_bright.isSliderDown():
            return
        b = max(0, min(100, int(b)))
        self.slider_bright.blockSignals(True)
        try:
            self.slider_bright.setValue(b)
        finally:
            self.slider_bright.blockSignals(False)
        self.lbl_bright_val.setText(f"{b}%")

    @safe_slot
    def _on_vol_changed(self, val: int):
        t0 = time.perf_counter()
        self._notify_user_interaction()
        self._user_dragging_vol_until = time.time() + 1.2
        val = max(0, min(100, int(val)))
        if val > 0:
            self._last_unmuted_vol = val
            self._is_muted = False
            self.lbl_vol_val.setText(f"{val}%")
        else:
            self._is_muted = True
            self.lbl_vol_val.setText("Muted")
        self.slider_vol.set_muted(self._is_muted)
        set_master_volume(val)
        try:
            import odd_profiler
            odd_profiler.record_slider_latency("Volume", val, (time.perf_counter() - t0) * 1000.0)
        except Exception:
            pass

    @safe_slot
    def _on_bright_changed(self, val: int):
        t0 = time.perf_counter()
        self._notify_user_interaction()
        self._user_dragging_bright_until = time.time() + 1.2
        val = max(0, min(100, int(val)))
        self.lbl_bright_val.setText(f"{val}%")
        set_brightness_async(val)
        try:
            import odd_profiler
            odd_profiler.record_slider_latency("Brightness", val, (time.perf_counter() - t0) * 1000.0)
        except Exception:
            pass

    @safe_slot
    def _toggle_wifi(self):
        self._notify_user_interaction()
        new_st = not self.btn_tile_wifi.is_active
        self._user_toggled_wifi_until = time.time() + 4.0
        self.btn_tile_wifi.set_active(new_st, animate=True)
        self.btn_tile_wifi.set_subtitle("Connecting..." if new_st else "Off")
        set_radio_state_async("WiFi", new_st)
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
        except Exception:
            pass
        QTimer.singleShot(2000, self.refresh_state)

    @safe_slot
    def _open_wifi_flyout(self):
        self._notify_user_interaction()
        try:
            subprocess.Popen("start ms-availablenetworks:", shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            try:
                subprocess.Popen("start ms-settings:network-wifi", shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        QTimer.singleShot(150, self.overlay.sink)

    def _open_wifi(self):
        self._open_wifi_flyout()

    @safe_slot
    def _toggle_bluetooth(self):
        self._notify_user_interaction()
        new_st = not self.btn_tile_bluetooth.is_active
        self._user_toggled_bt_until = time.time() + 4.0
        self.btn_tile_bluetooth.set_active(new_st, animate=True)
        self.btn_tile_bluetooth.set_subtitle("ON" if new_st else "OFF")
        set_radio_state_async("Bluetooth", new_st)
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
        except Exception:
            pass
        QTimer.singleShot(2000, self.refresh_state)

    @safe_slot
    def _open_bluetooth_flyout(self):
        self._notify_user_interaction()
        try:
            subprocess.Popen("start ms-settings:bluetooth", shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        QTimer.singleShot(150, self.overlay.sink)

    @safe_slot
    def _toggle_airplane(self):
        self._notify_user_interaction()
        new_st = not self.btn_circle_airplane.is_active
        self.btn_circle_airplane.set_active(new_st, animate=True)
        if new_st:
            set_radio_state_async("WiFi", False)
            set_radio_state_async("Bluetooth", False)
            self.btn_tile_wifi.set_active(False, animate=True)
            self.btn_tile_wifi.set_subtitle("Off")
            self.btn_tile_bluetooth.set_active(False, animate=True)
            self.btn_tile_bluetooth.set_subtitle("OFF")
        else:
            set_radio_state_async("WiFi", True)
            set_radio_state_async("Bluetooth", True)
            self.btn_tile_wifi.set_active(True, animate=True)
            self.btn_tile_wifi.set_subtitle("Connected")
            self.btn_tile_bluetooth.set_active(True, animate=True)
            self.btn_tile_bluetooth.set_subtitle("ON")
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.65)
        except Exception:
            pass
        QTimer.singleShot(1800, self.refresh_state)

    def _toggle_energy_saver(self):
        self._notify_user_interaction()
        new_st = not self.btn_circle_wallet.is_active
        self.btn_circle_wallet.set_active(new_st, animate=True)
        try:
            val = "100" if new_st else "0"
            subprocess.Popen(f"powercfg /setdcvalueindex SCHEME_CURRENT SUB_ENERGYSAVER ESBATTTHRESHOLD {val}", shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _toggle_nearby_sharing(self):
        self._toggle_hotspot()

    def _open_protocol(self, uri: str, btn=None):
        self._notify_user_interaction()
        if btn is not None and hasattr(btn, "trigger_pulse"):
            btn.trigger_pulse()
        try:
            odd_sound.play_sound("droplet", enabled=self.overlay.settings.get("sound_enabled", True), volume=float(self.overlay.settings.get("sound_volume", 0.75)) * 0.55)
        except Exception:
            pass
        try:
            subprocess.Popen(f"start {uri}", shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        QTimer.singleShot(150, self.overlay.sink)

    def _trigger_screenshot(self):
        """Hides/sinks ODD overlay and launches Windows Screen Snip / Snipping Tool"""
        self._notify_user_interaction()
        try:
            import odd_sound
            odd_sound.play_preview(0.9)
        except Exception:
            pass
        QTimer.singleShot(140, self.overlay.sink)
        QTimer.singleShot(280, self._launch_snipping_tool)

    def _launch_snipping_tool(self):
        try:
            os.startfile("ms-screenclip:")
        except Exception:
            try:
                subprocess.Popen(["snippingtool.exe", "/clip"])
            except Exception:
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    user32.keybd_event(0x5B, 0, 0, 0)
                    user32.keybd_event(0x10, 0, 0, 0)
                    user32.keybd_event(0x53, 0, 0, 0)
                    user32.keybd_event(0x53, 0, 2, 0)
                    user32.keybd_event(0x10, 0, 2, 0)
                    user32.keybd_event(0x5B, 0, 2, 0)
                except Exception:
                    try:
                        import ctypes
                        user32 = ctypes.windll.user32
                        user32.keybd_event(0x2C, 0, 0, 0)
                        user32.keybd_event(0x2C, 0, 2, 0)
                    except Exception:
                        pass

    def paintEvent(self, event):
        return


class WeatherTimingItem(QWidget):
    """Clean minimal hourly column matching Image 1: Time on top, white weather icon, temp below."""
    def __init__(self, time_label: str, icon_type: str, temp_str: str, theme="dark", parent=None):
        super().__init__(parent)
        self.time_label = str(time_label)
        self.icon_type = str(icon_type)
        self.temp_str = str(temp_str)
        self.theme = theme
        self.setFixedWidth(48)
        self.setFixedHeight(68)

    def update_data(self, time_label: str, icon_type: str, temp_str: str, theme: str = None):
        self.time_label = str(time_label)
        self.icon_type = str(icon_type)
        self.temp_str = str(temp_str)
        if theme:
            self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w = float(self.width())
        h = float(self.height())

        time_text = self.time_label
        if ":" in time_text:
            try:
                hr = int(time_text.split(":")[0])
                suffix = "AM" if hr < 12 else "PM"
                disp_hr = hr % 12
                if disp_hr == 0: disp_hr = 12
                time_text = f"{disp_hr} {suffix}"
            except Exception:
                pass

        painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Normal))
        painter.setPen(QColor(255, 255, 255, 130))
        painter.drawText(QRectF(0, 0, w, 16), Qt.AlignmentFlag.AlignCenter, time_text)

        pix = render_weather_pixmap(self.icon_type, 20)
        if pix and not pix.isNull():
            painter.drawPixmap(int((w - pix.width()) / 2.0), 20, pix)
        else:
            MonochromeIcons.draw(self.icon_type, painter, QPointF(w / 2.0, 30.0), size=18.0, color=QColor(255, 255, 255, 240), stroke_width=1.6)

        t_str = self.temp_str if "°" in self.temp_str else f"{self.temp_str}°"
        painter.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(QRectF(0, 46, w, 18), Qt.AlignmentFlag.AlignCenter, t_str)


class WeatherCard(QWidget):
    """
    Dedicated minimalist Weather Overlay Card matching Image 1:
    - Pitch black rounded card
    - Top Left: Big white weather icon + huge bold temperature (e.g. 23°)
    - Top Right: Condition name in bold white (e.g. Rain) + Location (e.g. Singapore)
    - Bottom Row: 6 hourly columns (Time, Weather icon, Temp)
    """
    weather_ready = Signal(dict)

    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self.setFixedSize(340, 146)
        self.weather_ready.connect(self._apply_weather_data)
        self.weather_data = {}
        self.hourly_timing_items = []
        self.init_ui()

        try:
            import odd_weather
            wm = odd_weather.WeatherManager.get_instance()
            wm.weather_updated.connect(self.weather_ready.emit)
            self._apply_weather_data(wm.get_weather())
        except Exception:
            pass

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        left_layout = QHBoxLayout()
        left_layout.setSpacing(6)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_hero_icon = QLabel(self)
        self.lbl_hero_icon.setFixedSize(32, 32)
        self.lbl_hero_icon.setScaledContents(True)
        left_layout.addWidget(self.lbl_hero_icon)

        self.lbl_big_temp = QLabel("23°", self)
        self.lbl_big_temp.setFont(QFont("Segoe UI Variable Display", 28, QFont.Weight.Bold))
        self.lbl_big_temp.setStyleSheet("color: #FFFFFF;")
        left_layout.addWidget(self.lbl_big_temp)
        top_layout.addLayout(left_layout)

        top_layout.addStretch()

        right_layout = QVBoxLayout()
        right_layout.setSpacing(0)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_cond = QLabel("Rain", self)
        self.lbl_cond.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        self.lbl_cond.setStyleSheet("color: #FFFFFF;")
        self.lbl_cond.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_layout.addWidget(self.lbl_cond)

        self.lbl_city = QLabel("Singapore", self)
        self.lbl_city.setFont(QFont("Segoe UI Variable Text", 9, QFont.Weight.Normal))
        self.lbl_city.setStyleSheet("color: rgba(255, 255, 255, 0.55);")
        self.lbl_city.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_city.setMaximumWidth(140)
        right_layout.addWidget(self.lbl_city)
        top_layout.addLayout(right_layout)

        layout.addLayout(top_layout)
        layout.addSpacing(2)

        self.hourly_container = QWidget(self)
        self.hourly_layout = QHBoxLayout(self.hourly_container)
        self.hourly_layout.setContentsMargins(0, 0, 0, 0)
        self.hourly_layout.setSpacing(4)
        layout.addWidget(self.hourly_container)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = float(self.width())
            h = float(self.height())
            rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
            from odd_theme import create_squircle_path
            card_path = create_squircle_path(rect, 18.0)
            is_light = (str(self.theme).lower() == "light")
            bg_col = QColor(245, 245, 248, 255) if is_light else QColor(8, 8, 10, 255)
            border_col = QColor(220, 220, 225, 255) if is_light else QColor(41, 41, 41, 255)
            painter.fillPath(card_path, QBrush(bg_col))
            painter.setPen(QPen(border_col, 0.8))
            painter.strokePath(card_path, painter.pen())
        finally:
            if painter.isActive():
                painter.end()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    @safe_slot
    def _apply_weather_data(self, data: dict):
        if not data:
            return
        self.weather_data = data
        city = data.get("city", "Current Location")
        cond = data.get("condition", "Partly Cloudy")
        temp = data.get("temp", "23")
        temp_str = str(temp) + "°" if "°" not in str(temp) else str(temp)
        icon_type = data.get("icon", "cloud")

        self.lbl_city.setText(city)
        self.lbl_cond.setText(cond)
        self.lbl_big_temp.setText(temp_str)
        self.lbl_hero_icon.setPixmap(render_weather_pixmap(icon_type, 38))

        hourly_list = data.get("hourly", [])[:6]
        if not hourly_list:
            now_h = time.localtime().tm_hour
            hourly_list = [
                {"time": f"{(now_h + i) % 12 or 12} {'AM' if (now_h + i) % 24 < 12 else 'PM'}", "icon": icon_type, "temp": temp_str}
                for i in range(6)
            ]

        while len(self.hourly_timing_items) < len(hourly_list):
            item_w = WeatherTimingItem("4 PM", "cloud", "23°", theme=self.theme, parent=self.hourly_container)
            self.hourly_layout.addWidget(item_w)
            self.hourly_timing_items.append(item_w)

        for idx, h_item in enumerate(hourly_list):
            t_str = str(h_item.get("temp", temp_str))
            t_clean = t_str if "°" in t_str else f"{t_str}°"
            self.hourly_timing_items[idx].update_data(
                time_label=h_item.get("time", "Now"),
                icon_type=h_item.get("icon", icon_type),
                temp_str=t_clean,
                theme=self.theme,
            )
        self.update()

    def refresh_weather(self):
        try:
            import odd_weather
            wm = odd_weather.WeatherManager.get_instance()
            data = wm.get_weather()
            if data:
                self._apply_weather_data(data)
            wm.refresh(settings=self.overlay.settings if hasattr(self, 'overlay') and self.overlay else None)
        except Exception:
            pass

    def refresh_state(self):
        self.refresh_weather()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(60, self.refresh_weather)


class WeatherWidgetButton(QPushButton):
    """
    Island Weather Widget Button:
    - Matches Image 1: Clean white weather icon + bold white temperature (e.g. '17°')
    - Micro-interaction springs (press scale, hover highlight)
    - Automatically updates when fresh weather data arrives
    """
    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.temp_str = "17°"
        self.icon_type = "cloud"
        self._is_active = False
        self.setFixedHeight(25)
        self.setMinimumWidth(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.scale_spring = SpringValue(initial_value=1.0, response=0.13, damping_ratio=0.75)
        self.hover_spring = SpringValue(initial_value=0.0, response=0.14, damping_ratio=0.85)

        # Reveal animation: 0.0 = hidden (icon+temp offscreen), 1.0 = fully revealed
        self._reveal_t = 0.0
        self._reveal_target = 1.0

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_step)
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        self._bob_phase = 0.0  # hover cloud bob oscillation

        try:
            import odd_weather
            wm = odd_weather.WeatherManager.get_instance()
            wm.weather_updated.connect(self._on_weather_updated)
            self._apply_weather_dict(wm.get_weather())
            # Start reveal animation on first load
            self._reveal_t = 0.0
            self._wake_anim()
        except Exception:
            self._reveal_t = 1.0
            pass

    def set_active(self, active: bool):
        if self._is_active != active:
            self._is_active = active
            self.update()

    def _apply_weather_dict(self, data: dict):
        if not data:
            return
        self.temp_str = str(data.get("temp_str", "17°"))
        self.icon_type = str(data.get("icon", "cloud"))
        city = data.get("city", "Weather")
        cond = data.get("condition", "")
        self.setToolTip(f"{city}: {self.temp_str} • {cond} (Click to open forecast)")
        self._adjust_width()
        # Re-trigger reveal animation whenever new weather data arrives
        self._reveal_t = 0.0
        self._reveal_target = 1.0
        self._wake_anim()
        self.update()

    def _on_weather_updated(self, data: dict):
        self._apply_weather_dict(data)

    def _adjust_width(self):
        fm = QFontMetrics(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
        text_w = fm.horizontalAdvance(self.temp_str)
        target_w = max(42, 13 + 4 + text_w + 10)
        self.setFixedWidth(target_w)

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def _on_anim_step(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_step))
        self._last_step = now
        self.scale_spring.update(dt)
        self._anim_phase += 0.06
        self.hover_spring.update(dt)
        # Smooth reveal: spring-lerp reveal_t toward reveal_target
        rev_diff = self._reveal_target - self._reveal_t
        if abs(rev_diff) > 0.005:
            self._reveal_t += rev_diff * 0.11  # ~220ms reveal
        else:
            self._reveal_t = self._reveal_target
        # Hover bob oscillation: gentle cloud float when hovered
        hov = max(0.0, min(1.0, self.hover_spring.value))
        if hov > 0.01:
            self._bob_phase += dt * 3.8  # ~0.6Hz bob
        self.update()
        settled = (self.scale_spring.is_settled() and self.hover_spring.is_settled()
                   and abs(rev_diff) <= 0.005 and hov < 0.01)
        if settled:
            self.anim_timer.stop()

    def _wake_anim(self):
        self._last_step = time.perf_counter()
        self.setMouseTracking(True)
        self._hover_pos = None
        self._anim_phase = 0.0
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hover_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.hover_spring.set_target(0.0, preserve_velocity=True)
        self._wake_anim()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.scale_spring.set_target(0.92, preserve_velocity=True)
        self._wake_anim()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.scale_spring.set_target(1.0, preserve_velocity=True)
        self._wake_anim()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._draw_weather_button(painter)
        finally:
            if painter.isActive():
                painter.end()

    def _draw_weather_button(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = float(self.width())
        h = float(self.height())
        cx = w / 2.0
        cy = h / 2.0
        s = self.scale_spring.value
        hov_t = max(0.0, min(1.0, self.hover_spring.value))
        rev   = max(0.0, min(1.0, getattr(self, '_reveal_t', 1.0)))

        # Ease-out cubic for silky deceleration
        rev_ease = 1.0 - (1.0 - rev) ** 3

        # Hover bob: gentle sinusoidal float (±1.8px amplitude)
        bob_phase = getattr(self, '_bob_phase', 0.0)
        bob_y = math.sin(bob_phase) * 1.8 * hov_t

        painter.save()
        try:
            painter.translate(cx, cy)
            painter.scale(s, s)
            painter.translate(-cx, -cy)

            if self._is_active:
                active_bg = QColor(255, 255, 255, 38) if self.theme != "light" else QColor(0, 0, 0, 24)
                painter.setBrush(QBrush(active_bg))
                stroke_col = QColor(255, 255, 255, 55) if self.theme != "light" else QColor(0, 0, 0, 45)
                painter.setPen(QPen(stroke_col, 1.0))
                painter.drawRoundedRect(QRectF(1.0, 1.0, w - 2.0, h - 2.0), h / 2.0, h / 2.0)
            elif hov_t > 0.01:
                bg_col = QColor(255, 255, 255, int(26 * hov_t)) if self.theme != "light" else QColor(0, 0, 0, int(18 * hov_t))
                painter.setBrush(QBrush(bg_col))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(QRectF(1.0, 1.0, w - 2.0, h - 2.0), h / 2.0, h / 2.0)

            text_color = QColor(255, 255, 255, 255) if self.theme != "light" else QColor(20, 24, 32, 255)

            # Reveal: icon slides in from left (-8px → 0), temp from right (+8px → 0)
            SLIDE = 8.0
            icon_slide_x  = -SLIDE * (1.0 - rev_ease)
            text_slide_x  =  SLIDE * (1.0 - rev_ease)
            reveal_alpha  = int(rev_ease * 255)

            # Paint icon with slide + bob
            icon_cx = 11.0 + icon_slide_x
            icon_cy = cy + bob_y
            if reveal_alpha < 255:
                effect_col = QColor(text_color)
                effect_col.setAlpha(reveal_alpha)
                painter.setOpacity(rev_ease)
            draw_material_cloud(painter, icon_cx, icon_cy, text_color, size=13.0)
            painter.setOpacity(1.0)

            # Paint temperature with slide + bob
            painter.setOpacity(rev_ease)
            font_col = QColor(text_color)
            font_col.setAlpha(reveal_alpha)
            painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
            painter.setPen(font_col)
            text_rect = QRectF(21.0 + text_slide_x, bob_y, w - 23.0, h)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.temp_str)
            painter.setOpacity(1.0)
        finally:
            painter.restore()



MONTH_MAP = {
    "jan": 1, "january": 1, "1": 1, "01": 1,
    "feb": 2, "february": 2, "2": 2, "02": 2,
    "mar": 3, "march": 3, "3": 3, "03": 3,
    "apr": 4, "april": 4, "4": 4, "04": 4,
    "may": 5, "5": 5, "05": 5,
    "jun": 6, "june": 6, "6": 6, "06": 6,
    "jul": 7, "july": 7, "7": 7, "07": 7,
    "aug": 8, "august": 8, "8": 8, "08": 8,
    "sep": 9, "sept": 9, "september": 9, "9": 9, "09": 9,
    "oct": 10, "october": 10, "10": 10,
    "nov": 11, "november": 11, "11": 11,
    "dec": 12, "december": 12, "12": 12
}


class CalendarNavButton(QPushButton):
    """Frosted pill mini-button for calendar navigation"""
    def __init__(self, text: str, theme="dark", parent=None):
        super().__init__(text, parent)
        self.theme = theme
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        r = float(rect.height()) / 2.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), r, r)

        theme = str(self.theme).lower()
        is_hover = self.underMouse()
        is_down = self.isDown()

        if theme == "light":
            if is_down:
                bg = QColor(220, 224, 232, 240)
                border = QColor(0, 0, 0, 45)
            elif is_hover:
                bg = QColor(255, 255, 255, 245)
                border = QColor(0, 0, 0, 35)
            else:
                bg = QColor(245, 247, 250, 200)
                border = QColor(0, 0, 0, 20)
            text_col = QColor(30, 41, 59)
        elif theme == "oled":
            if is_down:
                bg = QColor(28, 28, 34, 245)
                border = QColor(255, 255, 255, 80)
            elif is_hover:
                bg = QColor(22, 22, 28, 240)
                border = QColor(255, 255, 255, 50)
            else:
                bg = QColor(10, 10, 14, 220)
                border = QColor(255, 255, 255, 25)
            text_col = QColor(240, 240, 245)
        else:
            if is_down:
                bg = QColor(48, 54, 70, 235)
                border = QColor(255, 255, 255, 70)
            elif is_hover:
                bg = QColor(44, 48, 62, 220)
                border = QColor(255, 255, 255, 50)
            else:
                bg = QColor(32, 36, 46, 185)
                border = QColor(255, 255, 255, 28)
            text_col = QColor(230, 235, 245)

        painter.fillPath(path, QBrush(bg))
        painter.strokePath(path, QPen(border, 1.0))

        painter.setFont(QFont("Segoe UI Variable Text", 8.5, QFont.Weight.Medium))
        painter.setPen(text_col)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class MonthlyCalendarCard(QWidget):
    """
    Dedicated minimalist Split Calendar Card matching Image 2:
    - Pitch black rounded card (340 x 180)
    - Left column: Weekday + Month in coral red/gray, huge white day number (e.g. 15)
    - Right column: "MONTH YEAR" header with interactive ‹ and › buttons for month switching,
      "M T W T F S S" headers, monthly date grid with current day circled in coral red
    - Mouse wheel scrolls through months
    - Clicking any day highlights that date and updates the left column
    """
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        now = datetime.datetime.now()
        self.year = now.year
        self.month = now.month
        self.today_year = now.year
        self.today_month = now.month
        self.today_day = now.day
        self.selected_day = now.day
        self.setFixedSize(340, 180)
        self.setMouseTracking(True)
        self._prev_btn_rect = QRectF()
        self._next_btn_rect = QRectF()
        self._hovered_btn = None
        self._day_cell_rects = []

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def set_query(self, query: str):
        now = datetime.datetime.now()
        self.year = now.year
        self.month = now.month
        self.selected_day = now.day
        self.update()

    def copy_selected_date(self):
        try:
            d_str = f"{self.year}-{self.month:02d}-{self.selected_day:02d}"
            QApplication.clipboard().setText(d_str)
        except Exception:
            pass

    def select_offset_days(self, offset: int):
        max_d = calendar.monthrange(self.year, self.month)[1]
        self.selected_day = max(1, min(max_d, self.selected_day + offset))
        self.update()

    def _prev_month(self):
        if self.month == 1:
            self.month = 12
            self.year -= 1
        else:
            self.month -= 1
        max_d = calendar.monthrange(self.year, self.month)[1]
        self.selected_day = min(self.selected_day, max_d)
        self.update()

    def _next_month(self):
        if self.month == 12:
            self.month = 1
            self.year += 1
        else:
            self.month += 1
        max_d = calendar.monthrange(self.year, self.month)[1]
        self.selected_day = min(self.selected_day, max_d)
        self.update()

    def _jump_to_today(self):
        now = datetime.datetime.now()
        self.year = now.year
        self.month = now.month
        self.selected_day = now.day
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._prev_month()
        elif delta < 0:
            self._next_month()
        event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        old_hover = self._hovered_btn
        if self._prev_btn_rect.contains(pos):
            self._hovered_btn = "prev"
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._next_btn_rect.contains(pos):
            self._hovered_btn = "next"
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            is_over_day = any(r.contains(pos) for _, r in self._day_cell_rects)
            if is_over_day:
                self._hovered_btn = "day"
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self._hovered_btn = None
                self.setCursor(Qt.CursorShape.ArrowCursor)

        if self._hovered_btn != old_hover:
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hovered_btn = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        if self._prev_btn_rect.contains(pos):
            self._prev_month()
            return
        if self._next_btn_rect.contains(pos):
            self._next_month()
            return
        for d_num, r in self._day_cell_rects:
            if r.contains(pos):
                self.selected_day = d_num
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = float(self.width())
        h = float(self.height())

        # Solid opaque AMOLED background matching Nothing OS / ODD design
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        from odd_theme import create_squircle_path
        card_path = create_squircle_path(rect, 18.0)
        is_light = (str(self.theme).lower() == "light")
        bg_col = QColor(245, 245, 248, 255) if is_light else QColor(8, 8, 10, 255)
        border_col = QColor(220, 220, 225, 255) if is_light else QColor(41, 41, 41, 255)
        painter.fillPath(card_path, QBrush(bg_col))
        painter.setPen(QPen(border_col, 0.8))
        painter.strokePath(card_path, painter.pen())

        now = datetime.datetime.now()
        coral_red = QColor(255, 69, 58)   # #FF453A
        dim_gray = QColor(142, 142, 147)  # #8E8E93
        text_white = QColor(255, 255, 255)

        max_days = calendar.monthrange(self.year, self.month)[1]
        display_day = max(1, min(max_days, self.selected_day))
        try:
            view_date = datetime.date(self.year, self.month, display_day)
            day_name = view_date.strftime("%a")
            month_short = view_date.strftime("%b")
            day_str = str(display_day)
        except Exception:
            day_name = now.strftime("%a")
            month_short = now.strftime("%b")
            day_str = str(now.day)

        left_w = 88.0
        gap = 12.0
        right_w = 208.0
        total_content_w = left_w + gap + right_w
        start_x = max(14.0, (w - total_content_w) / 2.0)
        left_x = start_x
        right_x = start_x + left_w + gap

        # Left Column: Weekday + Month and Big Day Number
        painter.setFont(QFont("Segoe UI Variable Display", 15, QFont.Weight.Bold))
        fm_day = QFontMetrics(painter.font())
        day_w = fm_day.horizontalAdvance(day_name)

        painter.setPen(coral_red)
        painter.drawText(QPointF(left_x, 34.0), day_name)

        painter.setPen(dim_gray)
        painter.drawText(QPointF(left_x + day_w + 5.0, 34.0), month_short)

        painter.setFont(QFont("Segoe UI Variable Display", 52, QFont.Weight.Bold))
        painter.setPen(text_white)
        painter.drawText(QRectF(left_x, 42.0, left_w, 96.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, day_str)

        # Right Column Header: Month & Year (e.g. NOVEMBER 2026) + Chevrons
        month_full = f"{calendar.month_name[self.month].upper()} {self.year}"
        painter.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold))
        painter.setPen(coral_red)
        painter.drawText(QRectF(right_x, 14.0, right_w - 52.0, 18.0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, month_full)

        # ‹ and › buttons
        prev_rect = QRectF(right_x + right_w - 48.0, 13.0, 20.0, 20.0)
        next_rect = QRectF(right_x + right_w - 22.0, 13.0, 20.0, 20.0)
        self._prev_btn_rect = prev_rect
        self._next_btn_rect = next_rect

        if self._hovered_btn == "prev":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 40))
            painter.drawRoundedRect(prev_rect, 10.0, 10.0)
        painter.setFont(QFont("Segoe UI Variable Text", 12, QFont.Weight.Bold))
        painter.setPen(text_white if self._hovered_btn == "prev" else QColor(255, 255, 255, 180))
        painter.drawText(prev_rect, Qt.AlignmentFlag.AlignCenter, "‹")

        if self._hovered_btn == "next":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 40))
            painter.drawRoundedRect(next_rect, 10.0, 10.0)
        painter.setPen(text_white if self._hovered_btn == "next" else QColor(255, 255, 255, 180))
        painter.drawText(next_rect, Qt.AlignmentFlag.AlignCenter, "›")

        # Weekdays Row
        col_w = right_w / 7.0
        weekdays = ["M", "T", "W", "T", "F", "S", "S"]
        painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.DemiBold))
        painter.setPen(QColor(255, 255, 255, 220))
        for c, wd in enumerate(weekdays):
            cell_x = right_x + c * col_w
            painter.drawText(QRectF(cell_x, 36.0, col_w, 14.0), Qt.AlignmentFlag.AlignCenter, wd)

        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdayscalendar(self.year, self.month)
        grid_top = 53.0
        row_h = 19.5

        self._day_cell_rects = []
        painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Normal))
        for r_idx, week in enumerate(weeks):
            cell_y = grid_top + r_idx * row_h
            for c_idx, d_num in enumerate(week):
                if d_num == 0:
                    continue
                cell_x = right_x + c_idx * col_w
                cell_rect = QRectF(cell_x, cell_y, col_w, 16.0)
                self._day_cell_rects.append((d_num, cell_rect))

                is_today = (d_num == self.today_day and self.month == self.today_month and self.year == self.today_year)
                is_selected = (d_num == self.selected_day)

                cx = cell_x + col_w / 2.0
                cy = cell_y + 8.0

                if is_today:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(coral_red))
                    painter.drawEllipse(QPointF(cx, cy), 9.0, 9.0)
                    painter.setPen(text_white)
                    painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
                    painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, str(d_num))
                    painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Normal))
                elif is_selected:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(255, 255, 255, 45))
                    painter.drawEllipse(QPointF(cx, cy), 9.0, 9.0)
                    painter.setPen(text_white)
                    painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Bold))
                    painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, str(d_num))
                    painter.setFont(QFont("Segoe UI Variable Text", 8, QFont.Weight.Normal))
                else:
                    painter.setPen(text_white)
                    painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, str(d_num))


class ChargingCard(QWidget):
    """
    Dedicated Charging & Battery Overlay Card matching Image 3:
    - Pitch dark background with deep green glow
    - Top: Green lightning bolt + "Charging"
    - Middle: "59% • 34 min left"
    - Bottom: Horizontal rounded battery gauge with vibrant neon green progress pill
    """
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self.setFixedSize(340, 136)
        self.power_data = {}
        self._refresh_battery()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._refresh_battery)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_battery()
        self._poll_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._poll_timer.stop()

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def _refresh_battery(self):
        try:
            import psutil
            b = psutil.sensors_battery()
            if b:
                self.power_data = {
                    "percent": b.percent,
                    "is_charging": b.power_plugged,
                    "secsleft": b.secsleft
                }
            else:
                self.power_data = {"percent": 100, "is_charging": True, "secsleft": 0}
        except Exception:
            self.power_data = {"percent": 59, "is_charging": True, "secsleft": 2040}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        pct = max(0, min(100, int(self.power_data.get("percent", 59))))
        is_charging = bool(self.power_data.get("is_charging", False))
        secsleft = self.power_data.get("secsleft", -1)

        card_w = float(self.width())
        card_h = float(self.height())
        grad = QRadialGradient(card_w * 0.35, card_h * 0.45, card_w * 0.8)
        grad.setColorAt(0.0, QColor(10, 28, 14, 250))
        grad.setColorAt(1.0, QColor(3, 8, 4, 250))

        p_path = QPainterPath()
        p_path.addRoundedRect(QRectF(1.0, 1.0, card_w - 2.0, card_h - 2.0), 22.0, 22.0)
        painter.fillPath(p_path, QBrush(grad))
        painter.strokePath(p_path, QPen(QColor(255, 255, 255, 28), 1.0))

        neon_green = QColor(0, 230, 118)
        text_white = QColor(255, 255, 255)
        text_dim = QColor(255, 255, 255, 150)

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

        painter.setPen(QPen(QColor(255, 255, 255, 60), 1.2))
        painter.setBrush(QBrush(QColor(0, 0, 0, 80)))
        painter.drawRoundedRect(gauge_rect, 18.0, 18.0)

        fill_max = gauge_w - 6.0
        fill_w = max(16.0, (pct / 100.0) * fill_max)
        fill_rect = QRectF(gauge_x + 3.0, gauge_y + 3.0, fill_w, gauge_h - 6.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(neon_green))
        painter.drawRoundedRect(fill_rect, 15.0, 15.0)


COMMANDS_GUIDE_DATA = [
    # PAGE 1 (12 commands - 2x6 grid)
    {
        "prefix": "calc:",
        "title": "Calculator",
        "icon": "",
        "example": "calc: 125 * 8 - 50",
        "tip": "Evaluates math, trigonometry, percentages",
    },
    {
        "prefix": "convert:",
        "title": "Currency & Units",
        "icon": "",
        "example": "convert: 100 USD in EUR",
        "tip": "Live exchange rates, km/miles, °C/°F",
    },
    {
        "prefix": "g:",
        "title": "Google Search",
        "icon": "",
        "example": "g: quantum computing",
        "tip": "Instant web search in default browser",
    },
    {
        "prefix": "yt:",
        "title": "YouTube Search",
        "icon": "",
        "example": "yt: lofi beats",
        "tip": "Stream videos and music directly on YouTube",
    },
    {
        "prefix": "clp",
        "title": "Clipboard History",
        "icon": "",
        "example": "clp",
        "tip": "Browse clipboard snippets & 1-click paste",
    },
    {
        "prefix": "snip",
        "title": "Screen Snip",
        "icon": "",
        "example": "snip",
        "tip": "Capture any desktop screen region to clipboard",
    },
    {
        "prefix": "cal",
        "title": "Monthly Calendar",
        "icon": "",
        "example": "cal",
        "tip": "Interactive monthly calendar with jump navigation",
    },
    {
        "prefix": "time:",
        "title": "World Clock",
        "icon": "",
        "example": "time: Tokyo",
        "tip": "Check real-time local time in any global city",
    },
    {
        "prefix": "note:",
        "title": "Quick Scratchpad",
        "icon": "",
        "example": "note: review Q3 analytics",
        "tip": "Save thoughts, code snippets, and to-dos",
    },
    {
        "prefix": "sys:",
        "title": "System Controls",
        "icon": "",
        "example": "sys: lock",
        "tip": "Lock workstation, sleep display, view local IP",
    },
    {
        "prefix": "w:",
        "title": "Weather Forecast",
        "icon": "",
        "example": "w: London",
        "tip": "Live temperature, humidity & conditions",
    },
    {
        "prefix": "trans:",
        "title": "Quick Translate",
        "icon": "",
        "example": "trans: hello to Spanish",
        "tip": "Multi-language instant text translation",
    },

    # PAGE 2 (12 commands - 2x6 grid)
    {
        "prefix": "wiki:",
        "title": "Wikipedia Lookup",
        "icon": "",
        "example": "wiki: Nikola Tesla",
        "tip": "Instant summary of Wikipedia encyclopedia articles",
    },
    {
        "prefix": "app:",
        "title": "App Launcher",
        "icon": "",
        "example": "app: spotify",
        "tip": "Launch installed programs and system apps",
    },
    {
        "prefix": "def:",
        "title": "Dictionary",
        "icon": "",
        "example": "def: serendipity",
        "tip": "English word definitions, pronunciations & origins",
    },
    {
        "prefix": "timer:",
        "title": "Countdown Timer",
        "icon": "",
        "example": "timer: 15m",
        "tip": "Set desktop notification timers and alarms",
    },
    {
        "prefix": "ip:",
        "title": "Network IP Info",
        "icon": "",
        "example": "ip:",
        "tip": "View local IPv4, subnet mask, and public IP address",
    },
    {
        "prefix": "vol:",
        "title": "Volume Control",
        "icon": "",
        "example": "vol: 50",
        "tip": "Adjust Windows system master audio volume (0-100)",
    },
    {
        "prefix": "b:",
        "title": "Bing Search",
        "icon": "",
        "example": "b: latest tech news",
        "tip": "Search the web directly via Microsoft Bing",
    },
    {
        "prefix": "ddg:",
        "title": "DuckDuckGo",
        "icon": "",
        "example": "ddg: privacy search",
        "tip": "Private tracker-free web search",
    },
    {
        "prefix": "rand:",
        "title": "Random Number",
        "icon": "",
        "example": "rand: 1-100",
        "tip": "Generate random integers, coin flips, or dice rolls",
    },
    {
        "prefix": "url:",
        "title": "Open URL",
        "icon": "",
        "example": "https://github.com",
        "tip": "Open any web URL directly in default browser",
    },
    {
        "prefix": "color:",
        "title": "Color Inspector",
        "icon": "",
        "example": "color: #4A90E2",
        "tip": "HEX, RGB, and HSL color preview & conversion",
    },
    {
        "prefix": "music",
        "title": "Music Overlay",
        "icon": "",
        "example": "music",
        "tip": "Open full media controls and active player overlay",
    },
]

class CommandTileButton(QPushButton):
    """Clean, simple 2x6 command card showing prefix badge, title, example, and Try action"""
    def __init__(self, cmd_data: dict, index: int, on_try=None, theme="dark", parent=None):
        super().__init__(parent)
        self.cmd_data = cmd_data
        self.index = index
        self.on_try = on_try
        self.theme = theme
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(f"{cmd_data.get('title', '')}: {cmd_data.get('tip', '')}\nClick to try: {cmd_data.get('example', '')}")

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        self._hover_pos = None
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            w = float(self.width())
            h = float(self.height())
            rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)

            path = QPainterPath()
            path.addRoundedRect(rect, 6.0, 6.0)

            is_hov = self.underMouse()
            if is_hov:
                bg_col = QColor(255, 255, 255, 28)
                border_col = QColor(255, 255, 255, 80)
            else:
                bg_col = QColor(255, 255, 255, 12)
                border_col = QColor(255, 255, 255, 30)

            painter.fillPath(path, QBrush(bg_col))
            painter.strokePath(path, QPen(border_col, 0.8))

            # 1. Left prefix badge (pure white text #FFFFFF)
            prefix = str(self.cmd_data.get("prefix", ""))
            prefix_len = len(prefix)
            badge_w = 54.0 if prefix_len >= 7 else (46.0 if prefix_len >= 5 else 36.0)
            badge_rect = QRectF(6.0, 4.0, badge_w, 15.0)
            badge_path = QPainterPath()
            badge_path.addRoundedRect(badge_rect, 3.5, 3.5)

            badge_bg = QColor(255, 255, 255, 32) if is_hov else QColor(255, 255, 255, 18)
            badge_border = QColor(255, 255, 255, 70) if is_hov else QColor(255, 255, 255, 45)
            painter.fillPath(badge_path, QBrush(badge_bg))
            painter.strokePath(badge_path, QPen(badge_border, 0.75))

            font_badge = QFont("Segoe UI Variable Display", 7.2, QFont.Weight.Bold)
            painter.setFont(font_badge)
            painter.setPen(QColor(255, 255, 255, 255))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, prefix)

            # 2. Right "Try" pill (pure white text #FFFFFF)
            try_rect = QRectF(w - 29.0, 4.0, 23.0, 15.0)
            try_path = QPainterPath()
            try_path.addRoundedRect(try_rect, 3.5, 3.5)
            try_bg = QColor(255, 255, 255, 40) if is_hov else QColor(255, 255, 255, 16)
            painter.fillPath(try_path, QBrush(try_bg))
            painter.strokePath(try_path, QPen(QColor(255, 255, 255, 80 if is_hov else 45), 0.7))
            font_try = QFont("Segoe UI Variable Text", 6.8, QFont.Weight.Bold)
            painter.setFont(font_try)
            painter.setPen(QColor(255, 255, 255, 255))
            painter.drawText(try_rect, Qt.AlignmentFlag.AlignCenter, "Try")

            # 3. Command Title + Icon (pure white text #FFFFFF)
            font_title = QFont("Segoe UI Variable Text", 7.8, QFont.Weight.Bold)
            painter.setFont(font_title)
            painter.setPen(QColor(255, 255, 255, 255))
            title_x = badge_rect.right() + 6.0
            title_w = max(20.0, try_rect.left() - title_x - 4.0)
            title = self.cmd_data.get("title", "")
            painter.drawText(
                QRectF(title_x, 4.0, title_w, 15.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                title
            )

            # 4. Bottom Example line (pure white text #FFFFFF)
            example_str = f"e.g. {self.cmd_data.get('example', '')}"
            font_ex = QFont("Segoe UI Variable Text", 7.2, QFont.Weight.Normal)
            painter.setFont(font_ex)
            painter.setPen(QColor(255, 255, 255, 235 if is_hov else 190))
            painter.drawText(
                QRectF(7.0, 21.0, w - 14.0, 16.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                example_str
            )
        except Exception:
            pass


class CommandsGuideCard(QWidget):
    """
    Clean, simple Commands & Examples Guide Card for ODD:
    - 2x6 grid per page (12 commands on Page 1, 12 commands on Page 2)
    - Full page navigation (Prev / Next buttons, Page X of Y)
    - Users can read every command with realistic examples and 1-click test it directly
    - Pure white typography (#FFFFFF) on dark obsidian acrylic
    - Defensively guarded against crashes
    """
    def __init__(self, overlay, parent=None):
        super().__init__(parent)
        self.overlay = overlay
        self.theme = overlay.get_current_theme()
        self.tile_buttons = []
        self.setFixedHeight(362)
        self.init_ui()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(490, 362)

    def init_ui(self):
        try:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(10, 6, 10, 6)
            main_layout.setSpacing(4)

            # 1. Header Bar: Title, Subtitle, Close Button
            header = QHBoxLayout()
            header.setContentsMargins(2, 0, 2, 0)

            title_box = QVBoxLayout()
            title_box.setSpacing(1)
            lbl_title = QLabel("Commands & Quick Guide")
            lbl_title.setFont(QFont("Segoe UI Variable Display", 10.2, QFont.Weight.Bold))
            lbl_title.setStyleSheet("color: #FFFFFF; letter-spacing: 0.3px;")
            title_box.addWidget(lbl_title)

            lbl_sub = QLabel("Click any command or 'Try' to test it directly in search")
            lbl_sub.setFont(QFont("Segoe UI Variable Text", 8.0))
            lbl_sub.setStyleSheet("color: rgba(255, 255, 255, 0.85);")
            title_box.addWidget(lbl_sub)
            header.addLayout(title_box)

            header.addStretch()

            btn_close = QPushButton("✕")
            btn_close.setFixedSize(22, 22)
            btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn_close.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.15);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.30);
                    border-radius: 11px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: rgba(239, 68, 68, 0.85);
                    border-color: rgba(239, 68, 68, 1.0);
                    color: #FFFFFF;
                }
            """)
            btn_close.clicked.connect(self._close_guide)
            header.addWidget(btn_close)
            main_layout.addLayout(header)

            # 2. QStackedWidget for Paginated 2x6 Grids (Page 1: 0..11, Page 2: 12..23)
            from PySide6.QtWidgets import QStackedWidget
            self.stacked_widget = QStackedWidget(self)
            self.stacked_widget.setStyleSheet("background: transparent; border: none;")

            self.tile_buttons = []
            page_size = 12
            total_items = len(COMMANDS_GUIDE_DATA)
            num_pages = max(1, (total_items + page_size - 1) // page_size)

            for p_idx in range(num_pages):
                page_widget = QWidget()
                page_widget.setStyleSheet("background: transparent;")
                grid = QGridLayout(page_widget)
                grid.setContentsMargins(0, 2, 0, 2)
                grid.setHorizontalSpacing(8)
                grid.setVerticalSpacing(4)

                start_i = p_idx * page_size
                end_i = min(start_i + page_size, total_items)
                for local_idx, item_idx in enumerate(range(start_i, end_i)):
                    cmd_info = COMMANDS_GUIDE_DATA[item_idx]
                    tile = CommandTileButton(cmd_info, item_idx, on_try=self.use_command, theme=self.theme, parent=page_widget)
                    tile.clicked.connect(lambda _, c=cmd_info: self.use_command(c))
                    row = local_idx // 2
                    col = local_idx % 2
                    grid.addWidget(tile, row, col)
                    self.tile_buttons.append(tile)

                self.stacked_widget.addWidget(page_widget)

            main_layout.addWidget(self.stacked_widget)

            # 3. Bottom Navigation & Action Bar: [◀ Prev] [Page 1 of 2] [Next ▶]
            nav_bar = QHBoxLayout()
            nav_bar.setContentsMargins(2, 1, 2, 0)
            nav_bar.setSpacing(8)

            self.btn_prev = QPushButton("◀ Prev")
            self.btn_prev.setFixedSize(66, 24)
            self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_prev.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.btn_prev.clicked.connect(self._go_prev)

            self.lbl_page = QLabel(f"Page 1 of {num_pages}")
            self.lbl_page.setFont(QFont("Segoe UI Variable Text", 8.2, QFont.Weight.Bold))
            self.lbl_page.setStyleSheet("color: #FFFFFF;")
            self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.btn_next = QPushButton("Next ▶")
            self.btn_next.setFixedSize(66, 24)
            self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.btn_next.clicked.connect(self._go_next)

            nav_bar.addWidget(self.btn_prev)
            nav_bar.addWidget(self.lbl_page)
            nav_bar.addWidget(self.btn_next)

            nav_bar.addStretch()

            lbl_tip = QLabel("Tip: Type command prefix or math expression directly into search")
            lbl_tip.setFont(QFont("Segoe UI Variable Text", 7.5))
            lbl_tip.setStyleSheet("color: rgba(255, 255, 255, 0.82);")
            nav_bar.addWidget(lbl_tip)

            main_layout.addLayout(nav_bar)

            self._update_nav_buttons()
        except Exception as e:
            print(f"[ODD] Error initializing commands guide UI: {e}")

    def _update_nav_buttons(self):
        try:
            curr = self.stacked_widget.currentIndex()
            total = self.stacked_widget.count()
            self.lbl_page.setText(f"Page {curr + 1} of {total}")

            can_prev = curr > 0
            can_next = curr < (total - 1)

            btn_style_enabled = """
                QPushButton {
                    background: rgba(255, 255, 255, 0.16);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.35);
                    border-radius: 5px;
                    font-size: 8pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.28);
                    border-color: rgba(255, 255, 255, 0.65);
                    color: #FFFFFF;
                }
            """
            btn_style_disabled = """
                QPushButton {
                    background: rgba(255, 255, 255, 0.05);
                    color: rgba(255, 255, 255, 0.30);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 5px;
                    font-size: 8pt;
                    font-weight: bold;
                }
            """

            self.btn_prev.setEnabled(can_prev)
            self.btn_prev.setStyleSheet(btn_style_enabled if can_prev else btn_style_disabled)

            self.btn_next.setEnabled(can_next)
            self.btn_next.setStyleSheet(btn_style_enabled if can_next else btn_style_disabled)
        except Exception:
            pass

    def _go_prev(self):
        try:
            curr = self.stacked_widget.currentIndex()
            if curr > 0:
                self.stacked_widget.setCurrentIndex(curr - 1)
                self._update_nav_buttons()
        except Exception:
            pass

    def _go_next(self):
        try:
            curr = self.stacked_widget.currentIndex()
            if curr < self.stacked_widget.count() - 1:
                self.stacked_widget.setCurrentIndex(curr + 1)
                self._update_nav_buttons()
        except Exception:
            pass

    def reset_and_start_showcase(self):
        try:
            self.theme = self.overlay.get_current_theme()
            if hasattr(self, 'stacked_widget'):
                self.stacked_widget.setCurrentIndex(0)
            self._update_nav_buttons()
            for tile in self.tile_buttons:
                tile.theme = self.theme
                tile.update()
        except Exception:
            pass

    def stop_showcase(self):
        pass

    def use_command(self, cmd_info: dict):
        """Inserts the command example into ODD search input and focuses it"""
        try:
            self.hide()
            prefix = cmd_info.get("prefix", "")
            example = cmd_info.get("example", prefix)
            if prefix == "snip":
                if hasattr(self.overlay, 'quick_settings_card'):
                    self.overlay.quick_settings_card._trigger_screenshot()
                    return

            show_min = self.overlay._should_show_minimal_music() and not example
            if hasattr(self.overlay, 'minimal_music_bar'):
                self.overlay.minimal_music_bar.setVisible(show_min)
            target_h = 146 if show_min else 56
            self.overlay.animate_to_geometry(self.overlay.capsule_width_contracted, target_h)

            if hasattr(self.overlay, 'input') and self.overlay.input:
                self.overlay.input.setText(example)
                self.overlay.input.selectAll()
                self.overlay.input.setFocus()
                self.overlay.ensure_focus()
        except Exception as e:
            print(f"[ODD] Error using command: {e}")

    def _close_guide(self):
        try:
            self.overlay.toggle_commands_guide_panel()
        except Exception:
            pass

    def paintEvent(self, event):
        # Surface is rendered by parent IslandSurfaceContainer
        return


class OddOverlay(QWidget):
    async_search_ready = Signal(int, list, str, float)

    def __init__(self, search_engine: WindowsSearchEngine, settings: dict, on_open_settings=None):
        super().__init__()
        self.search_engine = search_engine
        self.settings = settings
        self.on_open_settings = on_open_settings
        self.current_results = []
        self._search_generation = 0
        self._search_request_lock = threading.Lock()
        self._pending_search_request = None
        self._search_worker_active = False
        self._search_cancel_event = threading.Event()
        self.async_search_ready.connect(self._on_async_search_ready)
        self.is_open = False
        self.is_animating = False
        self.surface_timestamp = 0
        self.capsule_mode = "search"  # "search" or "music"

        self.capsule_width_contracted = 340
        self.capsule_width_expanded = 600
        self.capsule_height_empty = 58
        self.capsule_height_expanded = 560
        self.edge_offset = 12
        self._browser_safe_top_offset = 0
        self._last_auto_hide_cursor_pos = QCursor.pos()
        self._canvas_width = 740

        self._is_morphing = False
        self._pill_surface_opacity = 1.0
        self._choreo_mode = "idle"  # "idle" | "open" | "close"
        self._choreo_start_ts = 0.0
        self._choreo_duration_ms = 220.0
        self._open_target_w = 340.0
        self._open_target_h = 56.0
        self._open_show_btn = True
        self._close_start_pill_x = 100.0
        self._close_start_pill_w = 340.0
        self._close_start_pill_h = 56.0
        self._close_start_y = 12.0
        self._close_anchor_btn_x = 550.0

        self._choreo_timer = QTimer(self)
        # Drive the intro at display cadence. A 6ms timer forced redundant frames
        # between monitor refreshes and caused repeated translucent-window redraws.
        self._choreo_timer.setInterval(16)
        self._choreo_timer.timeout.connect(self._on_choreo_tick)

        # High-performance fluid Spring Engine (sublime Apple Dynamic Island fluidity with zero lag or bounce)
        from odd_spring import SpringEngine, SpringValue
        self.spring_engine = SpringEngine(self, fps=144)
        self.spring_y = self.spring_engine.add_spring("y", 12.0, response=0.13, damping_ratio=0.84)
        self.spring_reveal = self.spring_engine.add_spring("reveal", 1.0, response=0.10, damping_ratio=0.86)
        self.spring_pill_w = self.spring_engine.add_spring("pill_w", 348.0, response=0.08, damping_ratio=0.92)
        self.spring_h = self.spring_engine.add_spring("h", 56.0, response=0.08, damping_ratio=0.92)
        self.spring_btn_opacity = self.spring_engine.add_spring("btn_opacity", 1.0, response=0.10, damping_ratio=0.88)
        self.spring_squash = self.spring_engine.add_spring("squash", 0.0, response=0.10, damping_ratio=0.84)
        self.spring_opacity = self.spring_engine.add_spring("opacity", 1.0, response=0.10, damping_ratio=0.88)

        self.spring_engine.frame_tick.connect(self._on_spring_tick)
        self.spring_engine.all_settled.connect(self._on_spring_settled)

        # Choreographed reveal timer (kept for compatibility, unused in continuous morph)
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.timeout.connect(self._on_reveal_trigger)

        # Choreographed sink stage timer (kept for compatibility, unused in continuous morph)
        self._sink_stage_timer = QTimer(self)
        self._sink_stage_timer.setSingleShot(True)
        self._sink_stage_timer.timeout.connect(self._on_sink_stage_trigger)

        # Let ordinary typing bursts settle before starting a search; the
        # active search is also cooperatively cancelled as soon as input moves.
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.setInterval(35)
        self._search_debounce_timer.timeout.connect(self._on_search_debounce_timeout)
        self._pending_search_text = ""
        self._pending_search_generation = 0

        # Key trigger 5-second inactivity auto-sink timer
        self.triggered_by_key = False
        self.key_inactivity_timer = QTimer(self)
        self.key_inactivity_timer.setSingleShot(True)
        self.key_inactivity_timer.timeout.connect(self._on_key_inactivity_timeout)

        # Fast Shake Detection to dismiss overlay
        self._shake_history = []
        self._last_shake_dismiss_time = 0.0

        # Legacy properties kept for compatibility
        self.anim_size = QPropertyAnimation(self, b"geometry")
        self.anim_size.setDuration(220)
        self.anim_size.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_pos = QPropertyAnimation(self, b"pos")
        self.anim_pos.setDuration(220)
        self.anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Animation safety watchdog (guarantees animation state never locks up)
        self._anim_watchdog = QTimer(self)
        self._anim_watchdog.setSingleShot(True)
        self._anim_watchdog.timeout.connect(self._on_anim_watchdog_timeout)

        self.trigger_window = None

        # Windows Media Manager Integration
        self.media_state = {}
        self.media_mgr = odd_media.get_media_manager()
        self.media_mgr.media_changed.connect(self._on_media_state_changed)

        # Auto-hide leave timer
        self.leave_sink_timer = QTimer(self)
        self.leave_sink_timer.setSingleShot(True)
        self.leave_sink_timer.timeout.connect(self._check_and_auto_sink)

        # Active cursor tracker while open to guarantee auto-hide & click-outside detection
        self.auto_hide_watcher = QTimer(self)
        self.auto_hide_watcher.setInterval(30)
        self.auto_hide_watcher.timeout.connect(self._poll_auto_hide)

        self.input = None
        self.search_container = None
        self._content_effects = {}
        self._content_animations = {}
        self._suppress_query_changed = False
        self.last_typing_time = 0.0
        self._minimal_music_dismissed = False
        self._target_results_card_h = 0
        self._in_messaging_disambiguation = False
        self.ambient_music_color = None
        self._last_ambient_thumb_bytes = None

        # Wire clipboard event hook to Dynamic Island
        if hasattr(odd_search, 'clipboard_mgr') and odd_search.clipboard_mgr:
            odd_search.clipboard_mgr.on_clip_event = self._on_clipboard_action_event

        # Wire Quick Text Sending disambiguation & error callbacks
        try:
            from odd_messaging import MessagingManager
            self.messaging_mgr = MessagingManager.get_instance(self.settings)
            self.messaging_mgr.disambiguation_requested.connect(self._on_messaging_disambiguation_requested)
            self.messaging_mgr.error_surfaced.connect(self._on_messaging_error_surfaced)
        except Exception:
            self.messaging_mgr = None

        self.init_window()
        self.init_ui()

        # Warm the translucent native surface before the first user-triggered reveal.
        QTimer.singleShot(0, self.prewarm_overlay_surface)
        QTimer.singleShot(150, self._prewarm_typing_pipeline)

    def _extract_ambient_cover_color(self, thumb_bytes) -> Optional[QColor]:
        """Extracts vibrant ambient cover color for subtle edge lighting in music mode"""
        if not thumb_bytes:
            return None
        if thumb_bytes == getattr(self, "_last_ambient_thumb_bytes", None):
            return self.ambient_music_color
        self._last_ambient_thumb_bytes = thumb_bytes
        try:
            pix = QPixmap()
            if not pix.loadFromData(thumb_bytes):
                return None
            img = pix.toImage().scaled(24, 24, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            w, h = img.width(), img.height()
            best_color = None
            best_score = -1.0
            for y in range(0, h, 2):
                for x in range(0, w, 2):
                    c = img.pixelColor(x, y)
                    r, g, b, a = c.red(), c.green(), c.blue(), c.alpha()
                    if a < 128:
                        continue
                    max_v = max(r, g, b)
                    min_v = min(r, g, b)
                    delta = max_v - min_v
                    if max_v == 0:
                        continue
                    sat = delta / float(max_v)
                    lum = 0.299 * r + 0.587 * g + 0.114 * b
                    if sat > 0.20 and 30 < lum < 230:
                        score = sat * 1.6 + (1.0 - abs(lum - 128.0) / 128.0)
                        if score > best_score:
                            best_score = score
                            best_color = c
            return best_color
        except Exception:
            return None

    def _on_messaging_disambiguation_requested(self, prompt_title: str, candidates: list):
        """
        Called when multiple contacts match a Quick Text Sending recipient (e.g. 'John Smith', 'John Mathew', 'John Davis').
        Pauses before sending and asks inside ODD: 'Which John should I send this to?'
        """
        self._in_messaging_disambiguation = True
        self.last_typing_time = time.time()
        if self.leave_sink_timer.isActive():
            self.leave_sink_timer.stop()
        if hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive():
            self.key_inactivity_timer.stop()

        if not self.is_open or self._choreo_mode == "close":
            self.surface(from_key=True)

        if self.capsule_mode != "search":
            self.switch_to_search_mode()

        self._suppress_query_changed = True
        try:
            if self.input:
                self.input.setText(prompt_title)
                self.input.selectAll()
        finally:
            self._suppress_query_changed = False

        disambig_items = []
        for idx, cand in enumerate(candidates):
            cname = getattr(cand, "display_name", str(cand))
            csub = getattr(cand, "subtitle", "") or "Select contact to open chat, type message, and send immediately"
            disambig_items.append(
                SearchItem(
                    id=f"msg_disambig_{idx}",
                    title=cname,
                    subtitle=f"{prompt_title} • {csub}",
                    category="CONTACT",
                    target=cname,
                    action=lambda i=idx: self._select_disambiguated_contact(i),
                    score=3000 - idx,
                )
            )

        self.current_results = disambig_items
        self._render_results(self.current_results, preserve_selection=False)
        self.ensure_focus()

    def _select_disambiguated_contact(self, index: int):
        self._in_messaging_disambiguation = False
        if getattr(self, "messaging_mgr", None) is not None:
            self.messaging_mgr.select_disambiguated_contact(index)

    def _on_messaging_error_surfaced(self, title: str, detail: str):
        """Only surfaces when a Quick Text action genuinely cannot continue."""
        try:
            if hasattr(self, "trigger_window") and self.trigger_window and hasattr(self.trigger_window, "bezel_hud"):
                self.trigger_window.bezel_hud.show_notification(
                    {"app": "ODD Messaging", "title": title, "message": detail},
                    duration_ms=4200,
                )
        except Exception:
            pass

    def _prewarm_typing_pipeline(self):
        """Pre-warms search engine, font metrics, and ResultItemWidget rendering so first-time typing has 0ms lag"""
        try:
            warm_items = self.search_engine.search("a", max_results=3, include_windows_search=False)
            if warm_items:
                dummy = ResultItemWidget(warm_items[0], theme=self.get_current_theme())
                pix = QPixmap(320, 52)
                pix.fill(Qt.GlobalColor.transparent)
                dummy.resize(320, 52)
                dummy.render(pix)
        except Exception:
            pass

    def dismiss_minimal_music_bar(self):
        """Closes and cancels the minimal music overlay below ODD search immediately."""
        self._minimal_music_dismissed = True
        if hasattr(self, 'minimal_music_bar') and self.minimal_music_bar:
            self.minimal_music_bar.hide()
        target_h = self._get_resting_search_height()
        if self.is_open and self.capsule_mode == "search" and not (self.input and self.input.text().strip()):
            self.animate_to_geometry(self.capsule_width_contracted, target_h)
        elif hasattr(self, 'pill_column') and self.pill_column:
            self.pill_column.resize(self.pill_column.width(), target_h)
        self.update()

    def on_music_overlay_button_clicked(self):
        """Opens the music overlay when the user clicks the Music button in the ODD search pill"""
        self._minimal_music_dismissed = False
        self.switch_to_music_mode()

    def _should_show_minimal_music(self) -> bool:
        """Returns True when the minimal music bar should be shown below the ODD search bar.
        Only shows when media is actively playing."""
        if not bool(self.settings.get("enable_music_overlay", True)):
            return False
        if getattr(self, "_minimal_music_dismissed", False):
            return False
        mode = str(self.settings.get("music_overlay_mode", "auto")).lower().strip()
        if mode == "disabled":
            return False
        # Media overlay strictly only when actively playing
        is_playing = bool(self.media_state.get("is_playing", False))
        if not is_playing:
            return False
        has_media = bool(self.media_state.get("has_media", False)) or bool(str(self.media_state.get("title", "")).strip())
        return is_playing and has_media

    def _get_resting_search_height(self) -> int:
        """Returns resting height of pill_column in search mode (includes minimal music bar if applicable)"""
        is_container = str(self.settings.get("ui_theme_style", "classic")).lower().strip() == "container"
        base_h = 96 if is_container else 56
        has_query = bool(self.input and self.input.text().strip())
        if has_query:
            return base_h
        if self._should_show_minimal_music():
            return base_h + 90
        return base_h

    def _fade_widget(self, widget, visible: bool, duration: int = 190):
        """Crossfade overlay sections without abrupt blank frames."""
        if widget is None:
            return

        key = id(widget)
        old_animation = self._content_animations.get(key)
        if old_animation:
            old_animation.stop()

        effect = self._content_effects.get(key)
        if effect is None:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            self._content_effects[key] = effect

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic if visible else QEasingCurve.Type.InCubic)

        if visible:
            widget.show()
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
        else:
            if not widget.isVisible():
                return
            animation.setStartValue(effect.opacity())
            animation.setEndValue(0.0)
            animation.finished.connect(widget.hide)

        self._content_animations[key] = animation
        animation.start()

    def _on_key_inactivity_timeout(self):
        if self.is_open and not self.input.text().strip() and self.capsule_mode == "search":
            if (
                (hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible())
                or (hasattr(self, 'power_card') and self.power_card.isVisible())
                or (hasattr(self, 'calendar_card') and self.calendar_card.isVisible())
                or (hasattr(self, 'weather_card') and self.weather_card.isVisible())
                or (hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible())
            ):
                return
            if time.time() - getattr(self, 'last_typing_time', 0.0) >= 4.5:
                self.sink()

    def _on_anim_watchdog_timeout(self):
        self.is_animating = False
        self._is_morphing = False

    def _on_reveal_trigger(self):
        """Ensure search surface is at full reveal and focused."""
        if self.is_open:
            has_query = bool(self.input and self.input.text().strip())
            if not has_query and self.capsule_mode == "search":
                self.spring_pill_w.set_target(float(self.capsule_width_contracted), preserve_velocity=True)
            self.spring_reveal.set_target(1.0, preserve_velocity=True)
            self.spring_engine.start()
            self.ensure_focus()

    def _on_sink_stage_trigger(self):
        """Compatibility no-op: sink() now animates as one continuous surface morph."""
        return

    def _on_clipboard_action_event(self, action: str, preview: str, chars: int):
        if action not in ("copied", "copy", "copied_file", "copy_files"):
            return
        if hasattr(self, 'trigger_window') and self.trigger_window:
            self.trigger_window.island_monitor.trigger_clipboard_action("copied", "", 0)

    def init_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("OddOverlay")
        self.setStyleSheet("#OddOverlay { background: transparent; border: none; }")
        self._surface_opacity = float(self.settings.get("opacity", 0.98))
        self.resize(self.capsule_width_contracted, self.capsule_height_empty)

        screen = QApplication.primaryScreen().geometry()
        edge = self.settings.get("edge", "top")
        contracted_w = self.capsule_width_contracted
        contracted_h = self.capsule_height_empty
        if edge == "top":
            self.setGeometry(screen.width() // 2 - contracted_w // 2, -contracted_h - 20, contracted_w, contracted_h)
        elif edge == "bottom":
            self.setGeometry(screen.width() // 2 - contracted_w // 2, screen.height() + 20, contracted_w, contracted_h)
        elif edge == "left":
            self.setGeometry(-contracted_w - 20, screen.height() // 2 - contracted_h // 2, contracted_w, contracted_h)
        else:
            self.setGeometry(screen.width() + 20, screen.height() // 2 - contracted_h // 2, contracted_w, contracted_h)
        self.hide()

    def nativeEvent(self, event_type, message):
        """
        Non-blocking Windows shape-aware hit-testing (WM_NCHITTEST = 0x0084):
        Returns False, 0 (HTCLIENT) when cursor is strictly inside the visible ODD
        island squircle surface or circular settings button so Qt processes input.
        Returns True, -1 (HTTRANSPARENT) for transparent corners, gaps, and unused
        canvas pixels, allowing clicks to pass directly through to Chrome, browser tabs,
        and underlying applications.
        """
        try:
            if event_type in ("windows_generic_MSG", "windows_dispatcher_MSG"):
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    if not getattr(self, "is_open", False) or not self.isVisible():
                        return True, -1  # HTTRANSPARENT

                    # Use QCursor.pos() for DPI-accurate Qt logical desktop coordinates
                    # (raw Win32 msg.lParam contains physical pixels which mismatch Qt coordinates on scaled displays)
                    cursor_pt = QCursor.pos()
                    if self.is_cursor_in_active_zone(cursor_pt):
                        return False, 0  # Normal Qt event dispatch: all buttons/inputs/sliders are 100% clickable!
                    else:
                        return True, -1  # HTTRANSPARENT: Click-through outside active island surface
        except Exception:
            pass
        return super().nativeEvent(event_type, message)

    def init_ui(self):
        # Manual positioning via _apply_island_frame (no conflicting top-level QLayout)
        self.master_layout = None

        # 1. Left Dynamic Island Continuous Acrylic Surface
        self.pill_column = IslandSurfaceContainer(self, parent=self)
        self.pill_column_layout = QVBoxLayout(self.pill_column)
        self.pill_column_layout.setContentsMargins(0, 0, 0, 0)
        self.pill_column_layout.setSpacing(8)
        self.pill_column_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Search Pill Bar (Top of left column)
        self.search_pill = SearchPillBar(self, parent=self.pill_column)
        self.input = self.search_pill.input
        self.input.textChanged.connect(self.on_query_changed)
        self.input.returnPressed.connect(self.execute_selected)
        self.pill_column_layout.addWidget(self.search_pill)

        # Minimal Music Overlay Bar (Shown below ODD Search Bar when music is playing)
        self.minimal_music_bar = MinimalMusicBar(self, parent=self.pill_column)
        self.minimal_music_bar.hide()
        self.pill_column_layout.addWidget(self.minimal_music_bar)

        # Dynamic Island Music Player (Expands seamlessly from search pill)
        self.music_bar = MusicCapsuleBar(self, parent=self.pill_column)
        self.music_bar.hide()
        self.pill_column_layout.addWidget(self.music_bar)

        # Dynamic Results Card (Directly underneath search pill in left column)
        self.results_card = ResultsCard(self, parent=self.pill_column)
        self.results_card.hide()

        self.list_widget = QListWidget(self.results_card)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 0px;
                margin-bottom: 4px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 4px 1px 4px 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.28);
                min-height: 24px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.48);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget.setAutoScroll(True)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        self.list_widget.currentRowChanged.connect(self.on_row_changed)
        self.results_card.card_layout.addWidget(self.list_widget)
        self.pill_column_layout.addWidget(self.results_card)

        # Dedicated Cards in left column
        self.power_card = PowerControlsCard(self, parent=self.pill_column)
        self.power_card.hide()
        self.pill_column_layout.addWidget(self.power_card)

        self.commands_guide_card = CommandsGuideCard(self, parent=self.pill_column)
        self.commands_guide_card.hide()
        self.pill_column_layout.addWidget(self.commands_guide_card)

        self.quick_settings_card = QuickSettingsCard(self, parent=self.pill_column)
        self.quick_settings_card.hide()
        self.pill_column_layout.addWidget(self.quick_settings_card)

        self.calendar_card = MonthlyCalendarCard(self, parent=self.pill_column)
        self.calendar_card.hide()
        self.pill_column_layout.addWidget(self.calendar_card)

        self.weather_card = WeatherCard(self, parent=self.pill_column)
        self.weather_card.hide()
        self.pill_column_layout.addWidget(self.weather_card)

        self.charging_card = ChargingCard(self, parent=self.pill_column)
        self.charging_card.hide()
        self.pill_column_layout.addWidget(self.charging_card)

        try:
            import odd_android_mirror
            self.android_mirror_card = odd_android_mirror.AndroidMirrorCard(self, parent=self.pill_column)
            self.android_mirror_card.hide()
            self.pill_column_layout.addWidget(self.android_mirror_card)
        except Exception as e:
            print(f"[ODD] Error initializing AndroidMirrorCard: {e}")

        # Multi-Media Sources Card
        self.sources_card = ResultsCard(self, parent=self.pill_column)
        self.sources_card.hide()
        self.sources_list_widget = QListWidget(self.sources_card)
        self.sources_list_widget.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 0px;
                margin-bottom: 2px;
            }
        """)
        self.sources_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sources_list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sources_list_widget.setAutoScroll(False)
        self.sources_list_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sources_list_widget.itemClicked.connect(self._on_source_item_clicked)
        self.sources_card.card_layout.addWidget(self.sources_list_widget)
        self.pill_column_layout.addWidget(self.sources_card)

        # 2. Right Dynamic Island Satellite: Standalone Circular ODD Button (56x56 with 5px hover expansion margin)
        self.settings_btn = OddLogoButton(theme=self.get_current_theme(), size=(56, 56), parent=self)
        self.settings_btn.setToolTip("ODD Settings & Preferences")
        self.settings_btn.clicked.connect(self._open_settings_modal)
        self.btn_opacity_effect = None
        self.settings_btn.raise_()

        # Maintain search_container compatibility reference to pill_column
        self.search_container = self.pill_column
        self.search_opacity_effect = None

        # Hidden legacy containers
        self.quick_bar = QWidget(self)
        self.quick_bar.hide()
        self.btn_power = FrostedPillButton("power", "Power Controls", theme=self.get_current_theme(), parent=self.quick_bar)
        self.btn_power.clicked.connect(self.toggle_power_controls_panel)
        self.btn_quick_settings = FrostedPillButton("quick_settings", "Quick Settings", theme=self.get_current_theme(), parent=self.quick_bar)
        self.btn_quick_settings.clicked.connect(self.toggle_quick_settings_panel)

        self.input.installEventFilter(self)
        self.search_pill.installEventFilter(self)
        self.minimal_music_bar.installEventFilter(self)
        self.results_card.installEventFilter(self)
        self.pill_column.installEventFilter(self)
        self.power_card.installEventFilter(self)
        self.quick_settings_card.installEventFilter(self)
        if hasattr(self, 'calendar_card'):
            self.calendar_card.installEventFilter(self)
        if hasattr(self, 'weather_card'):
            self.weather_card.installEventFilter(self)
        if hasattr(self, 'android_mirror_card'):
            self.android_mirror_card.installEventFilter(self)

        self.apply_theme_styles()

    def _prepare_search_panel_base(self):
        """Use the same search-header geometry before placing any utility card.

        Full music mode has a taller, standalone player header. Utility panel
        target heights are measured from the search header, so leaving the music
        bar visible underneath would clip the bottom of the panel.
        """
        if getattr(self, "capsule_mode", "search") == "music":
            self.capsule_mode = "search"
        if hasattr(self, "music_bar"):
            self.music_bar.hide()
        if hasattr(self, "search_pill"):
            self.search_pill.show()
            self.search_pill.set_content_opacity(1.0)
        if hasattr(self, "minimal_music_bar"):
            self.minimal_music_bar.hide()
        if hasattr(self, "sources_card"):
            self.sources_card.hide()
        if hasattr(self, "spring_btn_opacity"):
            self.spring_btn_opacity.set_target(1.0, preserve_velocity=True)

    def _hide_all_cards(self, except_card=None):
        """Cleanly dismisses all utility cards and synchronizes pill button active states."""
        all_cards = [
            getattr(self, 'results_card', None),
            getattr(self, 'weather_card', None),
            getattr(self, 'calendar_card', None),
            getattr(self, 'quick_settings_card', None),
            getattr(self, 'power_card', None),
            getattr(self, 'charging_card', None),
            getattr(self, 'commands_guide_card', None),
            getattr(self, 'android_mirror_card', None),
            getattr(self, 'sources_card', None),
        ]
        for c in all_cards:
            if c is not None and c is not except_card and c.isVisible():
                c.hide()

        # Invalidate layout so Qt recalculates geometries instantly
        if hasattr(self, 'pill_column_layout') and self.pill_column_layout:
            self.pill_column_layout.invalidate()
            self.pill_column_layout.activate()

        # Sync button active states
        sp = getattr(self, 'search_pill', None)
        if sp is not None:
            if hasattr(sp, 'btn_weather') and hasattr(sp.btn_weather, 'set_active'):
                sp.btn_weather.set_active(except_card is getattr(self, 'weather_card', None))
            if hasattr(sp, 'btn_quick') and hasattr(sp.btn_quick, 'set_active'):
                sp.btn_quick.set_active(except_card is getattr(self, 'quick_settings_card', None))
            if hasattr(sp, 'btn_phone') and hasattr(sp.btn_phone, 'set_active'):
                sp.btn_phone.set_active(except_card is getattr(self, 'android_mirror_card', None))
        if hasattr(self, 'btn_power') and hasattr(self.btn_power, 'set_active'):
            self.btn_power.set_active(except_card is getattr(self, 'power_card', None))
        if hasattr(self, 'btn_quick_settings') and hasattr(self.btn_quick_settings, 'set_active'):
            self.btn_quick_settings.set_active(except_card is getattr(self, 'quick_settings_card', None))

    def _raise_utility_card(self, card):
        """Raise an opened panel above any recently shown media widget and relayout it."""
        if card is None:
            return
        card.raise_()
        layout = getattr(self, "pill_column_layout", None)
        if layout is not None:
            layout.invalidate()
            layout.activate()
        if getattr(self, "pill_column", None) is not None:
            self.pill_column.update()

    def toggle_power_controls_panel(self):
        """Toggles the frosted Power Controls card"""
        self.last_typing_time = time.time()
        if hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive():
            self.key_inactivity_timer.stop()
        if hasattr(self, 'leave_sink_timer') and self.leave_sink_timer.isActive():
            self.leave_sink_timer.stop()

        if self.power_card.isVisible():
            self._hide_all_cards(except_card=None)
            if self._should_show_minimal_music() and not (self.input and self.input.text().strip()):
                self.minimal_music_bar.show()
            self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
            return

        self._hide_all_cards(except_card=self.power_card)
        self._prepare_search_panel_base()

        self.power_card.show()
        self._raise_utility_card(self.power_card)
        target_h = self._get_resting_search_height() + 116 + 8
        self.animate_to_geometry(self.capsule_width_contracted, target_h)

    def toggle_commands_guide_panel(self):
        """Toggles the interactive animated Commands Guide card"""
        try:
            self.last_typing_time = time.time()
            if hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive():
                self.key_inactivity_timer.stop()
            if hasattr(self, 'leave_sink_timer') and self.leave_sink_timer.isActive():
                self.leave_sink_timer.stop()

            if hasattr(self, 'commands_guide_card') and self.commands_guide_card.isVisible():
                self.commands_guide_card.stop_showcase()
                self.commands_guide_card.hide()
                show_min = self._should_show_minimal_music() and not (self.input and self.input.text().strip())
                if hasattr(self, 'minimal_music_bar'):
                    self.minimal_music_bar.setVisible(show_min)
                self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                return

            if hasattr(self, 'results_card'):
                self.results_card.hide()
            if hasattr(self, 'minimal_music_bar'):
                self.minimal_music_bar.hide()
            if hasattr(self, 'sources_card'):
                self.sources_card.hide()
            if hasattr(self, 'calendar_card'):
                self.calendar_card.hide()
            if hasattr(self, 'weather_card'):
                self.weather_card.hide()
            if hasattr(self, 'weather_card'):
                self.weather_card.hide()
            if hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible():
                self.quick_settings_card.hide()
                if hasattr(self, 'btn_quick_settings') and hasattr(self.btn_quick_settings, 'set_active'):
                    self.btn_quick_settings.set_active(False)
            if hasattr(self, 'power_card') and self.power_card.isVisible():
                self.power_card.hide()
                if hasattr(self, 'btn_power') and hasattr(self.btn_power, 'set_active'):
                    self.btn_power.set_active(False)

            self._prepare_search_panel_base()
            self.commands_guide_card.setGraphicsEffect(None)
            self.commands_guide_card.reset_and_start_showcase()
            self.commands_guide_card.show()
            self._raise_utility_card(self.commands_guide_card)
            guide_h = self.commands_guide_card.height() if (hasattr(self.commands_guide_card, "height") and self.commands_guide_card.height() > 200) else 362
            target_h = 56 + (guide_h or 362) + 8
            self.animate_to_geometry(self.capsule_width_expanded, target_h)
        except Exception as e:
            print(f"[ODD] Error toggling commands guide: {e}")

    def _ensure_card_parenting(self):
        is_side = str(self.settings.get("side_view", "off")).lower() in ("left", "right")
        cards = [
            getattr(self, 'results_card', None),
            getattr(self, 'weather_card', None),
            getattr(self, 'calendar_card', None),
            getattr(self, 'charging_card', None),
            getattr(self, 'power_card', None),
            getattr(self, 'quick_settings_card', None),
            getattr(self, 'commands_guide_card', None),
        ]
        for c in cards:
            if c is None: continue
            if is_side:
                if c.parent() != self:
                    if hasattr(self, 'pill_column_layout'):
                        self.pill_column_layout.removeWidget(c)
                    c.setParent(self)
            else:
                if c.parent() != self.pill_column:
                    c.setParent(self.pill_column)
                    if hasattr(self, 'pill_column_layout'):
                        self.pill_column_layout.addWidget(c)

    def show_overlay_card(self, card):
        if not card: return
        self._ensure_card_parenting()
        card.show()
        card.raise_()

        # Pure opacity entrance without positional displacement
        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve
            eff = QGraphicsOpacityEffect(card)
            card.setGraphicsEffect(eff)
            eff.setOpacity(0.0)

            anim_op = QPropertyAnimation(eff, b"opacity", card)
            anim_op.setDuration(130)
            anim_op.setStartValue(0.0)
            anim_op.setEndValue(1.0)
            anim_op.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim_op.finished.connect(lambda: card.setGraphicsEffect(None))
            anim_op.start()
            card._active_anim = anim_op
        except Exception:
            pass

    def hide_overlay_card(self, card, on_finished=None):
        if not card or not card.isVisible():
            if on_finished: on_finished()
            return

        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve
            eff = QGraphicsOpacityEffect(card)
            card.setGraphicsEffect(eff)
            eff.setOpacity(1.0)

            anim_op = QPropertyAnimation(eff, b"opacity", card)
            anim_op.setDuration(95)
            anim_op.setStartValue(1.0)
            anim_op.setEndValue(0.0)
            anim_op.setEasingCurve(QEasingCurve.Type.InCubic)

            def _on_done():
                card.hide()
                card.setGraphicsEffect(None)
                if on_finished: on_finished()

            anim_op.finished.connect(_on_done)
            anim_op.start()
            card._active_anim = anim_op
        except Exception:
            card.hide()
            if on_finished: on_finished()

    def toggle_charging_panel(self):
        """Toggles the ChargingCard overlay"""
        self.last_typing_time = time.time()
        if hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive():
            self.key_inactivity_timer.stop()
        if hasattr(self, 'leave_sink_timer') and self.leave_sink_timer.isActive():
            self.leave_sink_timer.stop()

        if hasattr(self, 'charging_card') and self.charging_card.isVisible():
            self._hide_all_cards(except_card=None)
            if self._should_show_minimal_music() and not (self.input and self.input.text().strip()):
                self.minimal_music_bar.show()
            self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
            return

        self._hide_all_cards(except_card=getattr(self, 'charging_card', None))
        self._prepare_search_panel_base()
        if hasattr(self, 'charging_card'):
            self.charging_card._refresh_battery()
            self._raise_utility_card(self.charging_card)
            target_h = self._get_resting_search_height() + self.charging_card.height() + 8
            self.animate_to_geometry(self.capsule_width_contracted, target_h)
            self.charging_card.show()

    def toggle_weather_panel(self):
        """Toggles the frosted Weather Forecast & Prediction card"""
        self.last_typing_time = time.time()
        if hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive():
            self.key_inactivity_timer.stop()
        if hasattr(self, 'leave_sink_timer') and self.leave_sink_timer.isActive():
            self.leave_sink_timer.stop()

        if hasattr(self, 'weather_card') and self.weather_card.isVisible():
            self._weather_close_generation = getattr(self, "_weather_close_generation", 0) + 1
            self._hide_all_cards(except_card=None)
            if self._should_show_minimal_music() and not (self.input and self.input.text().strip()):
                self.minimal_music_bar.show()
            self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
            return

        self._hide_all_cards(except_card=getattr(self, 'weather_card', None))
        self._prepare_search_panel_base()

        if hasattr(self, 'weather_card'):
            self._weather_close_generation = getattr(self, "_weather_close_generation", 0) + 1
            self.weather_card.refresh_weather()
            self.weather_card.setGraphicsEffect(None)
            self.weather_card.setMaximumHeight(16777215)
            self.weather_card.show()
            self._raise_utility_card(self.weather_card)
            self.weather_card.adjustSize()
            card_h = self.weather_card.height()
            target_h = self._get_resting_search_height() + card_h + 8
            self.animate_to_geometry(self.capsule_width_contracted, target_h)

    def _weather_panel_pins_overlay(self) -> bool:
        return bool(hasattr(self, 'weather_card') and self.weather_card and self.weather_card.isVisible())

    def on_phone_mirror_button_clicked(self):
        """Action on phone mirror button click:
        Instantly opens or toggles the Android Phone Mirror card with zero UI latency.
        """
        self.toggle_android_mirror_panel()

    def toggle_android_mirror_panel(self, force_show_guide=False):
        """Toggles the frosted Android Phone Mirror & Bluetooth card"""
        self.last_typing_time = time.time()
        if hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive():
            self.key_inactivity_timer.stop()
        if hasattr(self, 'leave_sink_timer') and self.leave_sink_timer.isActive():
            self.leave_sink_timer.stop()

        if not force_show_guide and hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible():
            self.android_mirror_card.hide()
            if hasattr(self, 'search_pill') and hasattr(self.search_pill, 'btn_phone') and hasattr(self.search_pill.btn_phone, 'set_active'):
                self.search_pill.btn_phone.set_active(False)
            if self._should_show_minimal_music() and not (self.input and self.input.text().strip()):
                self.minimal_music_bar.show()
            self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
            return

        self._hide_all_cards(except_card=getattr(self, 'android_mirror_card', None))
        self._prepare_search_panel_base()

        if hasattr(self, 'android_mirror_card'):
            self.android_mirror_card.setFixedWidth(self.capsule_width_expanded)
            self.android_mirror_card.setGraphicsEffect(None)
            self.android_mirror_card.show()
            self._raise_utility_card(self.android_mirror_card)
            card_h = self.android_mirror_card.get_desired_height() if hasattr(self.android_mirror_card, "get_desired_height") else self.android_mirror_card.sizeHint().height()
            target_h = self._get_resting_search_height() + card_h + 8
            self.animate_to_geometry(self.capsule_width_expanded, target_h)
            QTimer.singleShot(60, lambda: self.android_mirror_card.refresh_status(force_guide=force_show_guide) if (hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible()) else None)

    @safe_slot
    def toggle_quick_settings_panel(self):
        """Toggles the frosted Quick Settings card (Wi-Fi, Bluetooth, Volume, Brightness, Screenshot)"""
        log_breadcrumb("Toggling quick settings panel", category="ui_action")
        self.last_typing_time = time.time()
        if hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive():
            self.key_inactivity_timer.stop()
        if hasattr(self, 'leave_sink_timer') and self.leave_sink_timer.isActive():
            self.leave_sink_timer.stop()

        # Re-entrancy guard: prevent rapid toggle collision and thread storms
        if getattr(self, '_qs_transitioning', False):
            return
        self._qs_transitioning = True
        QTimer.singleShot(180, lambda: setattr(self, '_qs_transitioning', False))

        if self.quick_settings_card.isVisible():
            self._qs_close_generation = getattr(self, "_qs_close_generation", 0) + 1
            self._hide_all_cards(except_card=None)
            if self._should_show_minimal_music() and not (self.input and self.input.text().strip()):
                self.minimal_music_bar.show()
            self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
            return

        self._hide_all_cards(except_card=self.quick_settings_card)
        self._prepare_search_panel_base()

        self._qs_close_generation = getattr(self, "_qs_close_generation", 0) + 1
        self.quick_settings_card.setGraphicsEffect(None)
        self.quick_settings_card.setMaximumHeight(16777215)
        self.quick_settings_card.show()
        self._raise_utility_card(self.quick_settings_card)
        card_layout = self.quick_settings_card.layout()
        if card_layout is not None:
            card_layout.invalidate()
            card_layout.activate()
        qs_h = max(396, self.quick_settings_card.sizeHint().height())
        self.quick_settings_card.setFixedHeight(qs_h)
        target_h = self._get_resting_search_height() + 6 + qs_h + 8
        self.spring_h.set_config(response=0.18, damping_ratio=0.82)
        self.spring_pill_w.set_config(response=0.18, damping_ratio=0.82)
        self.animate_to_geometry(self.capsule_width_contracted, target_h)

    def start_screen_intelligence(self):
        """Screen Intelligence: Select a region, extract text (OCR), copy it, or search selected content."""
        if self.is_open:
            self.sink()

        def on_region_selected(image_path: Optional[Path]):
            if not image_path or not image_path.exists():
                return
            def _extract_worker():
                extracted_text = ""
                try:
                    import easyocr
                    reader = easyocr.Reader(['en'], gpu=False)
                    res = reader.readtext(str(image_path), detail=0)
                    extracted_text = " ".join(res).strip()
                except Exception:
                    pass

                if extracted_text:
                    try:
                        from PySide6.QtWidgets import QApplication
                        app = QApplication.instance()
                        if app:
                            app.clipboard().setText(extracted_text)
                    except Exception:
                        pass
                    if hasattr(self, 'trigger_window') and self.trigger_window:
                        self.trigger_window.show_infomatic_alert("copied", f"Extracted & Copied ({len(extracted_text)} chars)", duration_sec=3.0)
                else:
                    self._submit_google_lens_capture(image_path)

            _SEARCH_EXECUTOR.submit(_extract_worker)

        QTimer.singleShot(180, lambda: VisualCaptureOverlay(on_region_selected).show())

    def start_google_lens_search(self):
        """Capture a region, copy it, open Lens, then paste into its upload surface."""
        if self.is_open:
            self.sink()

        def begin_capture():
            self._visual_capture = VisualCaptureOverlay(self._submit_google_lens_capture)
            self._visual_capture.show()
            self._visual_capture.raise_()
            self._visual_capture.activateWindow()

        # Let the retract animation clear the captured area before the selector
        # becomes visible. The selector itself is a topmost overlay.
        QTimer.singleShot(180, begin_capture)

    @staticmethod
    def _is_profile_picker_title(title: str) -> bool:
        t_low = title.strip().lower()
        if not t_low:
            return True
        if t_low in (
            "google chrome", "chrome", "microsoft edge", "microsoft\u200b edge",
            "brave", "mozilla firefox", "firefox", "opera", "vivaldi", "arc",
        ):
            return True
        if t_low.startswith("sign in to ") or "who's using" in t_low:
            return True
        return False

    @staticmethod
    def _is_google_tab_ready(title: str) -> bool:
        t_low = title.strip().lower()
        return (
            t_low.startswith("google - ")
            or t_low.startswith("google — ")
            or t_low.startswith("google – ")
            or t_low.startswith("google and ")
            or t_low == "google"
        )

    @staticmethod
    def _is_browser_loading_title(title: str) -> bool:
        t_low = title.strip().lower()
        if not t_low or OddOverlay._is_profile_picker_title(t_low):
            return True
        return t_low.startswith((
            "untitled",
            "new tab",
            "about:blank",
            "www.google.",
            "https://www.google.",
            "http://www.google.",
            "google.com",
            "loading",
        ))

    @staticmethod
    def _find_visible_browser_windows() -> List[Tuple[int, str, str]]:
        """Return [(hwnd, exe_name, title), ...] for visible, non-minimized browser windows in Z-order."""
        results: List[Tuple[int, str, str]] = []
        try:
            import ctypes.wintypes as wt
            user32 = ctypes.WinDLL("user32")
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
            kernel32.OpenProcess.restype = wt.HANDLE
            kernel32.QueryFullProcessImageNameW.argtypes = [
                wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
            ]
            kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
            kernel32.CloseHandle.argtypes = [wt.HANDLE]

            browser_exes = {
                "chrome.exe", "msedge.exe", "brave.exe", "firefox.exe",
                "opera.exe", "vivaldi.exe", "arc.exe", "zen.exe",
                "waterfox.exe", "thorium.exe",
            }
            title_suffixes = (
                "- google chrome",
                "- microsoft edge",
                "- microsoft\u200b edge",
                "- brave",
                "— mozilla firefox",
                "- mozilla firefox",
                "- opera",
                "- vivaldi",
                "— arc",
            )

            WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

            def _enum_cb(hwnd, _lparam):
                try:
                    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                        return True
                    rect = wt.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        if (rect.right - rect.left) < 300 or (rect.bottom - rect.top) < 200:
                            return True

                    t_len = user32.GetWindowTextLengthW(hwnd)
                    title = ""
                    if t_len > 0:
                        t_buf = ctypes.create_unicode_buffer(t_len + 2)
                        user32.GetWindowTextW(hwnd, t_buf, t_len + 2)
                        title = t_buf.value.strip()

                    c_buf = ctypes.create_unicode_buffer(128)
                    user32.GetClassNameW(hwnd, c_buf, 128)
                    cls_name = c_buf.value

                    exe_name = ""
                    pid = wt.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
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

                    t_low = title.lower()
                    is_browser = False
                    if exe_name in browser_exes and cls_name in ("Chrome_WidgetWin_1", "MozillaWindowClass"):
                        is_browser = True
                    elif any(t_low.endswith(sfx) for sfx in title_suffixes):
                        is_browser = True

                    if is_browser:
                        results.append((int(hwnd), exe_name, title))
                except Exception:
                    pass
                return True

            enum_proc = WNDENUMPROC(_enum_cb)
            user32.EnumWindows(enum_proc, 0)
        except Exception:
            pass
        return results

    def _submit_google_lens_capture(self, image_path: Optional[Path]):
        """Copy the capture and paste it into a fresh Google Lens tab."""
        self.hide()
        if image_path is None:
            self._open_url("https://lens.google.com/")
            return

        image = QPixmap(str(image_path))
        if image.isNull():
            self._open_url("https://lens.google.com/")
            return

        clipboard = QApplication.clipboard()
        clipboard.setPixmap(image)
        # Populate the bitmap flavor as well. Chromium accepts this clipboard
        # representation in Lens' paste-to-search drop surface.
        clipboard.setImage(image.toImage())

        # Check whether an active browser window is already open before launching
        # the URL so we can distinguish a warm new-tab open from a cold browser start.
        pre_windows = self._find_visible_browser_windows()
        had_open_browser = any(
            title and not self._is_profile_picker_title(title)
            for _, _, title in pre_windows
        )

        # Open https://www.google.com/ directly instead of https://lens.google.com/
        # (?olud), because ?olud places initial keyboard focus on the "upload a file"
        # button (<span role="button" jsname="tAPGc">), which causes pressing Enter
        # to trigger <input type="file"> and open Windows File Explorer. On
        # https://www.google.com/, the search <textarea name="q"> is focused on load,
        # accepts Ctrl+V image attachments directly, and submits on Enter.
        self._open_url("https://www.google.com/")
        self._show_visual_search_status(image_path)

        # Cancel any previous pending Lens poll timer
        prev_timer = getattr(self, "_lens_poll_timer", None)
        if prev_timer is not None and prev_timer.isActive():
            prev_timer.stop()

        state = {
            "start_ts": time.monotonic(),
            "browser_win_ts": None,
            "google_ready_ts": None,
            "done": False,
        }

        poll_timer = QTimer(self)
        poll_timer.setInterval(180)
        self._lens_poll_timer = poll_timer

        def _finish_and_paste(target_hwnd: Optional[int] = None):
            if state["done"]:
                return
            state["done"] = True
            poll_timer.stop()
            try:
                if target_hwnd:
                    fg = ctypes.windll.user32.GetForegroundWindow()
                    if fg != target_hwnd:
                        force_foreground_focus(target_hwnd)
            except Exception:
                pass
            try:
                cb = QApplication.clipboard()
                cb.setPixmap(image)
                cb.setImage(image.toImage())
            except Exception:
                pass
            self._paste_image_into_lens(is_cold_start=not had_open_browser)

        def _poll_browser_ready():
            if state["done"]:
                poll_timer.stop()
                return

            now = time.monotonic()
            elapsed = now - state["start_ts"]

            wins = self._find_visible_browser_windows()
            fg_hwnd = 0
            try:
                fg_hwnd = int(ctypes.windll.user32.GetForegroundWindow())
            except Exception:
                pass

            # Prefer the foreground browser window if one is focused, otherwise the topmost visible browser window
            active_win = None
            for w in wins:
                if w[0] == fg_hwnd:
                    active_win = w
                    break
            if active_win is None and wins:
                active_win = wins[0]

            if had_open_browser:
                # Warm path: wait at least 1.6s so the newly opened tab becomes active
                if elapsed < 1.6:
                    return
                if active_win is not None:
                    hwnd, _exe, title = active_win
                    if self._is_google_tab_ready(title):
                        if state["google_ready_ts"] is None:
                            state["google_ready_ts"] = now
                            # If it was already ready at the 1.6s check, paste immediately;
                            # if it finished loading after 1.6s, give the input 450ms to settle.
                            if elapsed <= 1.85:
                                _finish_and_paste(hwnd)
                                return
                        elif (now - state["google_ready_ts"]) >= 0.45:
                            _finish_and_paste(hwnd)
                            return
                if elapsed >= 5.0:
                    _finish_and_paste(active_win[0] if active_win else None)
                return

            # Cold-start path: wait for the browser app to launch, pass any profile picker,
            # load the Google tab title, and finish initializing the search box + paste listener.
            if active_win is not None:
                hwnd, _exe, title = active_win
                if not self._is_profile_picker_title(title):
                    if state["browser_win_ts"] is None:
                        state["browser_win_ts"] = now
                        try:
                            if fg_hwnd != hwnd:
                                force_foreground_focus(hwnd)
                        except Exception:
                            pass

                    if self._is_google_tab_ready(title):
                        if state["google_ready_ts"] is None:
                            state["google_ready_ts"] = now
                        elif (
                            (now - state["google_ready_ts"]) >= 2.2
                            and (now - state["browser_win_ts"]) >= 2.8
                            and elapsed >= 3.8
                        ):
                            _finish_and_paste(hwnd)
                            return
                    elif (
                        not self._is_browser_loading_title(title)
                        and (now - state["browser_win_ts"]) >= 4.5
                        and elapsed >= 5.0
                    ):
                        _finish_and_paste(hwnd)
                        return

            # Safety fallback if cold launch takes unusually long
            if elapsed >= 18.0:
                _finish_and_paste(active_win[0] if active_win else None)

        poll_timer.timeout.connect(_poll_browser_ready)
        poll_timer.start()

    @staticmethod
    def _paste_image_into_lens(is_cold_start: bool = False):
        try:
            user32 = ctypes.windll.user32
            vk_control, vk_v, key_up = 0x11, 0x56, 0x0002
            user32.keybd_event(vk_control, 0, 0, 0)
            user32.keybd_event(vk_v, 0, 0, 0)
            user32.keybd_event(vk_v, 0, key_up, 0)
            user32.keybd_event(vk_control, 0, key_up, 0)
            # Google Search uploads the pasted screenshot in the background (~1.3-1.6s)
            # before attaching vsrid/udm=50 to the search form. Press Enter once the
            # attachment finishes registering so the visual search submits cleanly.
            QTimer.singleShot(1600, OddOverlay._press_enter_in_lens)
            QTimer.singleShot(2400, OddOverlay._press_enter_in_lens)
            if is_cold_start:
                QTimer.singleShot(3400, OddOverlay._press_enter_in_lens)
        except Exception:
            pass

    @staticmethod
    def _press_enter_in_lens():
        try:
            user32 = ctypes.windll.user32
            vk_return, key_up = 0x0D, 0x0002
            user32.keybd_event(vk_return, 0, 0, 0)
            user32.keybd_event(vk_return, 0, key_up, 0)
        except Exception:
            pass

    @staticmethod
    def _open_url(url: str):
        """Use the Windows URL association; this is more reliable than a browser module thread call."""
        try:
            os.startfile(url)
        except Exception:
            webbrowser.open_new_tab(url)

    def _show_visual_search_status(self, image_path: Path):
        try:
            trigger = getattr(self, "trigger_window", None)
            if trigger and getattr(trigger, "bezel_hud", None):
                trigger.bezel_hud.show_notification_hud(
                    "Google Lens",
                    f"Searching in Lens: {image_path.name}",
                    duration_ms=2200,
                )
        except Exception:
            pass

    def open_prefix_quick_menu(self, anchor_widget):
        self._is_menu_active = True
        menu = QMenu(self)
        theme = self.get_current_theme()
        if theme == "light":
            menu.setStyleSheet("""
                QMenu {
                    background: rgba(250, 250, 250, 0.98);
                    color: #171717;
                    border: 1px solid rgba(0, 0, 0, 0.15);
                    border-radius: 8px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 16px;
                    border-radius: 4px;
                    font-size: 11px;
                }
                QMenu::item:selected {
                    background: rgba(0, 0, 0, 0.08);
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(0, 0, 0, 0.08);
                    margin: 4px 8px;
                }
            """)
        elif theme == "oled":
            menu.setStyleSheet("""
                QMenu {
                    background: #000000;
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.22);
                    border-radius: 8px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 16px;
                    border-radius: 4px;
                    font-size: 11px;
                }
                QMenu::item:selected {
                    background: rgba(255, 255, 255, 0.18);
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(255, 255, 255, 0.12);
                    margin: 4px 8px;
                }
            """)
        else:
            menu.setStyleSheet("""
                QMenu {
                    background: rgba(24, 24, 24, 0.98);
                    color: #FFFFFF;
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    border-radius: 8px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 16px;
                    border-radius: 4px;
                    font-size: 11px;
                }
                QMenu::item:selected {
                    background: rgba(255, 255, 255, 0.14);
                }
                QMenu::separator {
                    height: 1px;
                    background: rgba(255, 255, 255, 0.10);
                    margin: 4px 8px;
                }
            """)

        # Categorized quick tools (Emoji-Free)
        quick_categories = [
            ("Clipboard & Cheatcodes", [
                ("clp", "Clipboard History & Paste Buffer"),
                ("help", "View All Cheatcodes & Shortcuts"),
                ("rook", "Rook Power Shortcuts"),
                ("note:", "Quick Notes & Tasks")
            ]),
            ("Calculations & Conversions", [
                ("calc:", "Calculator & Math"),
                ("convert:", "Unit & Currency Converter"),
                ("time:", "World Clock & Timers"),
                ("color:", "Color Inspector & Picker")
            ]),
            ("System & Shell", [
                ("qs", "Quick Settings & Controls (Wi-Fi, Vol, Display, Snip)"),
                ("snip", "Screen Snip / Screenshot (Print Screen)"),
                ("sys:", "System Power & Controls (Lock, Sleep, IP)"),
                ("f:", "Search Files & Folders"),
                ("pdf:", "Search PDF Documents"),
                ("doc:", "Search Documents & Notes"),
                ("folder:", "Search Folders & Directories"),
                ("cmd:", "Run Command")
            ]),
            ("Web Searches", [
                ("g:", "Search Google"),
                ("yt:", "Search YouTube"),
                ("gh:", "Search GitHub"),
                ("wiki:", "Search Wikipedia"),
                ("map:", "Search Google Maps"),
                ("r:", "Search Reddit")
            ])
        ]

        for cat_title, items in quick_categories:
            act_header = menu.addAction(cat_title)
            act_header.setEnabled(False)
            for p, d in items:
                act = menu.addAction(f"  {p:<8} {d}")
                act.triggered.connect(lambda _, prefix=p: self._insert_search_prefix(prefix))
            menu.addSeparator()

        menu.aboutToHide.connect(self._on_menu_closing)
        menu.exec(anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height() + 4)))
        self._is_menu_active = False
        self.ensure_focus()

    def _on_menu_closing(self):
        self._is_menu_active = False
        QTimer.singleShot(50, self.ensure_focus)

    def _insert_search_prefix(self, prefix: str):
        self._is_menu_active = False
        if prefix == "qs":
            self.toggle_quick_settings_panel()
            return
        elif prefix == "snip":
            self.quick_settings_card._trigger_screenshot()
            return
        val = prefix if prefix in ("clp", "help", "rook") else (prefix + " ")
        self.input.setText(val)
        self.input.setFocus()
        self.ensure_focus()

    def _refresh_media_sources_card(self) -> int:
        """Populates sources_list_widget and sets explicit fixed heights on sources_list_widget and sources_card."""
        sessions = self.media_state.get("available_sessions", [])
        self.sources_list_widget.clear()
        selected_idx = self.media_state.get("selected_session_index", 0)
        theme = self.get_current_theme()

        for s in sessions:
            list_item = QListWidgetItem(self.sources_list_widget)
            widget = MediaSourceItemWidget(s, is_selected=(s.get("index") == selected_idx), theme=theme)
            list_item.setSizeHint(widget.sizeHint())
            self.sources_list_widget.addItem(list_item)
            self.sources_list_widget.setItemWidget(list_item, widget)

        row_h = 48
        visible_rows = max(1, min(4, len(sessions)))
        list_h = visible_rows * row_h
        card_h = list_h + 12

        self.sources_list_widget.setFixedHeight(list_h)
        self.sources_card.setFixedHeight(card_h)
        return 148 + 8 + card_h

    def toggle_media_sources_panel(self):
        """Toggle the dropdown list showing all available media apps/tabs"""
        key = id(self.sources_card)
        old_anim = self._content_animations.pop(key, None)
        if old_anim:
            old_anim.stop()
        if key in self._content_effects:
            self._content_effects.pop(key, None)
            self.sources_card.setGraphicsEffect(None)

        if self.sources_card.isVisible():
            self.sources_card.hide()
            self.animate_to_geometry(self.capsule_width_expanded, 148)
            return

        sessions = self.media_state.get("available_sessions", [])
        if not sessions:
            return

        target_h = self._refresh_media_sources_card()
        self.sources_card.show()
        self.animate_to_geometry(self.capsule_width_expanded, target_h)

    def _on_source_item_clicked(self, item: QListWidgetItem):
        row = self.sources_list_widget.row(item)
        sessions = self.media_state.get("available_sessions", [])
        if 0 <= row < len(sessions):
            self.media_mgr.select_session(sessions[row]["index"])
        self.sources_card.hide()
        self.animate_to_geometry(self.capsule_width_expanded, 148)

    def _on_media_state_changed(self, state: dict):
        was_playing = bool(self.media_state.get("is_playing", False))
        old_title = str(self.media_state.get("title", "")).strip()
        now_playing = bool(state.get("is_playing", False))
        new_title = str(state.get("title", "")).strip()
        if (now_playing and not was_playing) or (now_playing and new_title and new_title != old_title):
            self._minimal_music_dismissed = False

        self.media_state = state
        thumb_bytes = state.get("thumbnail_bytes") or state.get("thumbnail") or b""
        new_ambient = self._extract_ambient_cover_color(thumb_bytes)
        if new_ambient != self.ambient_music_color:
            self.ambient_music_color = new_ambient
            if hasattr(self, 'pill_column') and self.pill_column:
                self.pill_column.update()

        self.music_bar.update_state(state)
        if hasattr(self, 'minimal_music_bar'):
            self.minimal_music_bar.update_media_info(state)
        if hasattr(self, 'search_pill'):
            self.search_pill.update_settings(self.settings)

        has_media = state.get("has_media", False)
        enabled = self.settings.get("enable_music_overlay", True)

        if not has_media and not enabled:
            if self.capsule_mode == "music" and self.is_open:
                self.switch_to_search_mode()
                return

        if self.is_open and self.capsule_mode == "music" and self.sources_card.isVisible():
            sessions = state.get("available_sessions", [])
            if sessions:
                target_h = self._refresh_media_sources_card()
                if abs(self.spring_h.target - target_h) > 0.5:
                    self.animate_to_geometry(self.capsule_width_expanded, target_h)
            else:
                self.sources_card.hide()
                self.animate_to_geometry(self.capsule_width_expanded, 148)

        if self.is_open and self.capsule_mode == "search" and not (self.input and self.input.text().strip()):
            subcard_active = (
                (hasattr(self, 'weather_card') and self.weather_card.isVisible())
                or (hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible())
                or (hasattr(self, 'commands_guide_card') and self.commands_guide_card.isVisible())
                or (hasattr(self, 'power_card') and self.power_card.isVisible())
                or (hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible())
                or (hasattr(self, 'calendar_card') and self.calendar_card.isVisible())
                or (hasattr(self, 'results_card') and self.results_card.isVisible())
            )
            if not subcard_active:
                show_min = self._should_show_minimal_music()
                if hasattr(self, 'minimal_music_bar'):
                    was_shown = not self.minimal_music_bar.isHidden()
                    self.minimal_music_bar.setVisible(show_min)
                    target_h = float(self._get_resting_search_height())
                    if was_shown != show_min or abs(self.spring_h.target - target_h) > 0.5:
                        self.animate_to_geometry(self.capsule_width_contracted, int(target_h))

    def switch_to_search_mode(self):
        self.capsule_mode = "search"
        self.sources_card.hide()
        self.music_bar.hide()
        self.search_pill.show()
        has_q = bool(self.input and self.input.text().strip())
        if hasattr(self, 'minimal_music_bar'):
            self.minimal_music_bar.setVisible(self._should_show_minimal_music() and not has_q)

        # Fade in ODD button smoothly
        self.spring_btn_opacity.set_target(1.0, preserve_velocity=True)

        target_w = self.capsule_width_contracted
        target_h = self._get_resting_search_height()
        if not has_q:
            self.animate_to_geometry(target_w, target_h)
        self.ensure_focus()

    def switch_to_search_mode_with_text(self, text: str):
        self.switch_to_search_mode()
        self.input.setText(text)
        self.input.setFocus()
        self.ensure_focus()

    def switch_to_music_mode(self):
        if not self.settings.get("enable_music_overlay", True):
            return
        if hasattr(self, 'key_inactivity_timer'):
            self.key_inactivity_timer.stop()
        self.triggered_by_key = False
        self.capsule_mode = "music"
        self.search_pill.hide()
        if hasattr(self, 'minimal_music_bar'):
            self.minimal_music_bar.hide()
        if hasattr(self, 'quick_bar'):
            self.quick_bar.hide()
        if hasattr(self, 'power_card'):
            self.power_card.hide()
        if hasattr(self, 'quick_settings_card'):
            self.quick_settings_card.hide()
        if hasattr(self, 'calendar_card'):
            self.calendar_card.hide()
        if hasattr(self, 'btn_power'):
            self.btn_power.set_active(False)
        if hasattr(self, 'btn_quick_settings'):
            self.btn_quick_settings.set_active(False)
        if hasattr(self, 'results_card'):
            self.results_card.hide()
        self.list_widget.clear()
        self.sources_card.hide()
        self.music_bar.show()
        if hasattr(self, 'music_bar'):
            self.music_bar.update_state(self.media_state)

        # Fade out ODD button smoothly
        self.spring_btn_opacity.set_target(0.0, preserve_velocity=True)

        target_w = self.capsule_width_expanded
        target_h = 148
        self.animate_to_geometry(target_w, target_h)
        self.ensure_focus()

    def get_current_theme(self) -> str:
        return str(self.settings.get("theme", "dark")).lower()

    def set_theme(self, theme: str):
        self.settings["theme"] = str(theme).lower()
        self.apply_theme_styles()

    def apply_theme_styles(self):
        theme = self.get_current_theme()
        self._surface_opacity = float(self.settings.get("opacity", 0.98))

        self.search_pill.set_theme(theme)
        if hasattr(self, 'minimal_music_bar'):
            self.minimal_music_bar.set_theme(theme)
        self.settings_btn.set_theme(theme)
        self.music_bar.set_theme(theme)
        self.results_card.set_theme(theme)
        self.sources_card.set_theme(theme)
        if hasattr(self, 'btn_power'):
            self.btn_power.set_theme(theme)
        if hasattr(self, 'btn_quick_settings'):
            self.btn_quick_settings.set_theme(theme)
        if hasattr(self, 'power_card'):
            self.power_card.set_theme(theme)
        if hasattr(self, 'quick_settings_card'):
            self.quick_settings_card.set_theme(theme)
        if hasattr(self, 'calendar_card'):
            self.calendar_card.set_theme(theme)
        if hasattr(self, 'weather_card'):
            self.weather_card.set_theme(theme)
        if hasattr(self, 'android_mirror_card'):
            self.android_mirror_card.set_theme(theme)
        if hasattr(self, 'commands_guide_card'):
            self.commands_guide_card.theme = theme

        if theme == "light":
            self.input.setStyleSheet("""
                QLineEdit {
                    background: transparent;
                    color: #171717;
                    border: none;
                    padding-left: 2px;
                    padding-right: 2px;
                    selection-background-color: rgba(0, 0, 0, 0.12);
                }
                QLineEdit::placeholder {
                    color: rgba(23, 23, 23, 0.45);
                }
            """)
            self.search_pill.btn_clear.setStyleSheet("""
                QPushButton {
                    background: rgba(0, 0, 0, 0.08);
                    color: #737373;
                    border: none;
                    border-radius: 9px;
                    font-size: 8px;
                    font-weight: bold;
                    padding: 0;
                    outline: none;
                }
                QPushButton:hover {
                    background: rgba(0, 0, 0, 0.18);
                    color: #171717;
                }
            """)
        else:
            self.input.setStyleSheet("""
                QLineEdit {
                    background: transparent;
                    color: #FFFFFF;
                    border: none;
                    padding-left: 2px;
                    padding-right: 2px;
                    selection-background-color: rgba(255, 255, 255, 0.20);
                }
                QLineEdit::placeholder {
                    color: rgba(255, 255, 255, 0.50);
                }
            """)
            self.search_pill.btn_clear.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.12);
                    color: #D4D4D4;
                    border: none;
                    border-radius: 9px;
                    font-size: 8px;
                    font-weight: bold;
                    padding: 0;
                    outline: none;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.24);
                    color: #FFFFFF;
                }
            """)
        is_container = str(self.settings.get("ui_theme_style", "classic")).lower().strip() == "container"
        if is_container:
            self.settings_btn.setVisible(False)
        else:
            self.settings_btn.setVisible(bool(self.settings.get("ui_show_settings_button", True)))
        self.search_pill.update_settings(self.settings)
        self.update()

    def update_settings(self, new_settings: dict):
        self.settings = new_settings
        show_pc = bool(self.settings.get("ui_show_power_controls", True))
        self.capsule_height_empty = 92 if show_pc else 58
        if hasattr(self, 'quick_bar'):
            self.quick_bar.setVisible(show_pc and not (self.input and self.input.text().strip()))
        self._surface_opacity = float(self.settings.get("opacity", 0.98))
        self.search_engine.set_settings(self.settings)

        self.apply_theme_styles()
        if self.is_open:
            panel_open = (
                (hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible())
                or (hasattr(self, 'power_card') and self.power_card.isVisible())
                or (hasattr(self, 'calendar_card') and self.calendar_card.isVisible())
                or (hasattr(self, 'weather_card') and self.weather_card.isVisible())
                or (hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible())
            )
            if self.capsule_mode == "search" and not (self.input and self.input.text().strip()) and not panel_open:
                if hasattr(self, 'minimal_music_bar'):
                    self.minimal_music_bar.setVisible(self._should_show_minimal_music())
                self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
        try:
            self._anchor_window_canvas(self.height())
        except Exception:
            pass
        try:
            import odd_weather
            odd_weather.WeatherManager.get_instance().refresh(force=True, settings=self.settings)
        except Exception:
            pass
        self.update()

    def _open_settings_modal(self):
        try:
            if self.on_open_settings:
                self._opening_settings = True
                origin = QRect(self.settings_btn.mapToGlobal(QPoint(5, 5)), QSize(46, 46))
                self.on_open_settings(origin)
                self._opening_settings = False
                if self.is_open:
                    QTimer.singleShot(45, self.sink)
        except Exception as e:
            self._opening_settings = False
            import traceback
            try:
                err_path = Path(os.environ.get("APPDATA", "")) / "ODD" / "error.log"
                err_path.parent.mkdir(parents=True, exist_ok=True)
                with open(err_path, "a") as f:
                    f.write(f"\n--- Settings Open Error ---\n{traceback.format_exc()}\n")
            except Exception:
                pass

    def _get_global_island_rect(self) -> QRect:
        rects = []
        if hasattr(self, "pill_column") and self.pill_column and self.pill_column.isVisible():
            rects.append(QRect(self.mapToGlobal(self.pill_column.pos()), self.pill_column.size()))
        if hasattr(self, "settings_btn") and self.settings_btn and self.settings_btn.isVisible():
            rects.append(QRect(self.mapToGlobal(self.settings_btn.pos()), self.settings_btn.size()))
        if not rects:
            return self.geometry()
        united = rects[0]
        for r in rects[1:]:
            united = united.united(r)
        return united

    def is_cursor_in_active_zone(self, pos: QPoint) -> bool:
        """
        Accurate shape-aware hit test:
        Returns True when global pos is within the visible island surface (pill_column)
        or the settings button, allowing 100% of clicks to reach Qt controls and buttons.
        Returns False (HTTRANSPARENT) for transparent corners and unused canvas areas.
        """
        if not getattr(self, "is_open", False) or not self.isVisible():
            return False

        if pos is None:
            pos = QCursor.pos()

        local_pt = self.mapFromGlobal(pos)

        # 1. Settings button
        if hasattr(self, "settings_btn") and self.settings_btn and self.settings_btn.isVisible():
            if self.settings_btn.geometry().contains(local_pt):
                return True

        # 2. Main Island surface (pill_column)
        if hasattr(self, "pill_column") and self.pill_column and self.pill_column.isVisible():
            pill_geo = self.pill_column.geometry()
            if pill_geo.contains(local_pt):
                return True

        # 3. Active utility cards (including when reparented to self in side view mode or child of pill_column)
        for card_attr in (
            'quick_settings_card', 'weather_card', 'calendar_card',
            'power_card', 'charging_card', 'commands_guide_card',
            'android_mirror_card', 'results_card'
        ):
            c = getattr(self, card_attr, None)
            if c and c.isVisible():
                if c.parent() == self:
                    if c.geometry().contains(local_pt):
                        return True
                elif c.parent() == getattr(self, 'pill_column', None):
                    pill_pt = self.pill_column.mapFromGlobal(pos)
                    if c.geometry().contains(pill_pt):
                        return True

        return False

    def _is_scrubbing_or_interacting(self) -> bool:
        """Returns True only if the user is actively dragging/scrubbing a slider"""
        if getattr(self, 'capsule_mode', None) == 'music':
            if hasattr(self, 'music_bar'):
                seek = getattr(self.music_bar, 'seekbar', None) or getattr(self.music_bar, 'seek_bar', None)
                if seek and getattr(seek, 'is_dragging', False):
                    return True
        if hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible():
            for slider_attr in ('slider_volume', 'slider_brightness'):
                s = getattr(self.quick_settings_card, slider_attr, None)
                if s and getattr(s, 'is_dragging', False):
                    return True
        return False

    def _is_user_actively_typing(self) -> bool:
        """Returns True only if the user has actually entered a search query or typed recently (within 2 seconds)"""
        if getattr(self, 'capsule_mode', None) == 'search':
            if hasattr(self, 'input') and self.input and bool(self.input.text().strip()):
                return True
            if hasattr(self, 'results_card') and self.results_card.isVisible():
                return True
            if time.time() - getattr(self, 'last_typing_time', 0.0) < 2.0:
                return True
        return False

    def _record_shake_point(self, x: float, y: float):
        now = time.time()
        self._shake_history.append((now, x, y))
        cutoff = now - 0.25
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
        if max(reversals_x, reversals_y) >= 2 and total_dist > 38.0 and (now - self._last_shake_dismiss_time > 0.6):
            self._last_shake_dismiss_time = now
            return True
        return False

    @safe_slot
    def _poll_auto_hide(self):
        """Active watcher to ensure search box smoothly auto-hides when mouse moves away, user clicks outside, or shakes cursor"""
        if not self.is_open or self.is_animating or getattr(self, '_opening_settings', False) or getattr(self, '_is_menu_active', False):
            return

        pos = QCursor.pos()

        # 1. Deliberate cursor shake to dismiss immediately
        self._record_shake_point(pos.x(), pos.y())
        if self._check_is_shake():
            if hasattr(self, 'key_inactivity_timer'):
                self.key_inactivity_timer.stop()
            self.sink()
            return

        # The weather card is an explicit panel mode; ignore outside-click and
        # leave polling until the user closes the card or presses Escape.
        if self._weather_panel_pins_overlay():
            if self.leave_sink_timer.isActive():
                self.leave_sink_timer.stop()
            return

        previous_pos = getattr(self, "_last_auto_hide_cursor_pos", pos)
        self._last_auto_hide_cursor_pos = pos

        in_zone = self.is_cursor_in_active_zone(pos)
        if in_zone:
            self._cursor_has_entered_island = True

        # 2. Detect click outside ODD search to immediately close it
        try:
            l_state = ctypes.windll.user32.GetAsyncKeyState(0x01)
            r_state = ctypes.windll.user32.GetAsyncKeyState(0x02)
            clicked = bool((l_state & 0x8000) or (l_state & 0x0001) or (r_state & 0x8000) or (r_state & 0x0001))
            if clicked and not in_zone:
                active_modal = QApplication.activeModalWidget()
                if not active_modal and not getattr(self, '_opening_settings', False) and not getattr(self, '_is_menu_active', False):
                    if hasattr(self, 'key_inactivity_timer'):
                        self.key_inactivity_timer.stop()
                    self.sink()
                    return
        except Exception:
            pass

        if self._browser_safe_top_offset and self.settings.get("edge", "top") == "top":
            screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
            if screen is None:
                return
            browser_band_bottom = screen.geometry().y() + self._browser_safe_top_offset
            capsule_rect = self._get_global_island_rect()
            moving_up_into_browser_band = previous_pos.y() > pos.y() and pos.y() <= browser_band_bottom
            x_over_island = capsule_rect.left() - 8 <= pos.x() <= capsule_rect.right() + 8
            if moving_up_into_browser_band and x_over_island and not (
                self._is_scrubbing_or_interacting()
                or self._is_user_actively_typing()
                or is_mouse_dragging()
            ):
                self.sink()
                return

        if not self.settings.get("auto_hide_on_leave", True):
            return

        # Never auto-hide if actively scrubbing, or if user is actively typing, or mouse is dragging
        has_query = bool(self.input and self.input.text().strip())
        if self._is_scrubbing_or_interacting() or \
           self._is_user_actively_typing() or \
           has_query or \
           is_mouse_dragging():
            if self.leave_sink_timer.isActive():
                self.leave_sink_timer.stop()
            return

        # 3. Fast auto-hide on mouse leave: closes smoothly in 120ms whenever cursor is outside
        if not in_zone:
            if not self.leave_sink_timer.isActive():
                delay = int(self.settings.get("auto_hide_delay_ms", 120))
                if self._browser_safe_top_offset:
                    delay = min(delay, 70)
                self.leave_sink_timer.start(delay)
        else:
            if self.leave_sink_timer.isActive():
                self.leave_sink_timer.stop()

    def eventFilter(self, watched, event):
        if not getattr(self, "is_open", False) or not self.isVisible():
            if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                return True
            return super().eventFilter(watched, event)

        if watched is self.input and event.type() == QEvent.Type.KeyPress:
            self.last_typing_time = time.time()
            if self.leave_sink_timer.isActive():
                self.leave_sink_timer.stop()
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down, Qt.Key.Key_Up):
                if hasattr(self, '_search_debounce_timer') and self._search_debounce_timer.isActive():
                    self._search_debounce_timer.stop()
                    self._do_search_query(self.input.text())

            if hasattr(self, 'calendar_card') and self.calendar_card.isVisible():
                if event.key() == Qt.Key.Key_Left:
                    self.calendar_card.select_offset_days(-1)
                    return True
                elif event.key() == Qt.Key.Key_Right:
                    self.calendar_card.select_offset_days(1)
                    return True
                elif event.key() == Qt.Key.Key_Up:
                    self.calendar_card.select_offset_days(-7)
                    return True
                elif event.key() == Qt.Key.Key_Down:
                    self.calendar_card.select_offset_days(7)
                    return True
                elif event.key() == Qt.Key.Key_PageUp:
                    self.calendar_card._prev_month()
                    return True
                elif event.key() == Qt.Key.Key_PageDown:
                    self.calendar_card._next_month()
                    return True
                elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.calendar_card.copy_selected_date()
                    return True
                elif event.key() == Qt.Key.Key_Escape:
                    self.calendar_card.hide()
                    self.input.clear()
                    if self._should_show_minimal_music():
                        self.minimal_music_bar.show()
                    self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                    return True

            if event.key() == Qt.Key.Key_Down:
                if self.list_widget.count() > 0:
                    curr = self.list_widget.currentRow()
                    if curr < self.list_widget.count() - 1:
                        self.list_widget.setCurrentRow(curr + 1)
                    return True
            elif event.key() == Qt.Key.Key_Up:
                if self.list_widget.count() > 0:
                    curr = self.list_widget.currentRow()
                    if curr > 0:
                        self.list_widget.setCurrentRow(curr - 1)
                    return True
            elif event.key() == Qt.Key.Key_PageDown:
                if self.list_widget.count() > 0:
                    curr = self.list_widget.currentRow()
                    self.list_widget.setCurrentRow(min(self.list_widget.count() - 1, curr + 4))
                    return True
            elif event.key() == Qt.Key.Key_PageUp:
                if self.list_widget.count() > 0:
                    curr = self.list_widget.currentRow()
                    self.list_widget.setCurrentRow(max(0, curr - 4))
                    return True
            elif event.key() == Qt.Key.Key_Escape:
                if hasattr(self, 'calendar_card') and self.calendar_card.isVisible():
                    self.calendar_card.hide()
                    self.input.clear()
                    if self._should_show_minimal_music():
                        self.minimal_music_bar.show()
                    self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                    return True
                if hasattr(self, 'power_card') and self.power_card.isVisible():
                    self.power_card.hide()
                    self.btn_power.set_active(False)
                    if self._should_show_minimal_music():
                        self.minimal_music_bar.show()
                    self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                    return True
                if hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible():
                    self.quick_settings_card.hide()
                    if hasattr(self, 'btn_quick_settings') and hasattr(self.btn_quick_settings, 'set_active'):
                        self.btn_quick_settings.set_active(False)
                    if hasattr(self, 'search_pill') and hasattr(self.search_pill, 'btn_quick') and hasattr(self.search_pill.btn_quick, 'set_active'):
                        self.search_pill.btn_quick.set_active(False)
                    if self._should_show_minimal_music():
                        self.minimal_music_bar.show()
                    self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                    return True
                if hasattr(self, 'weather_card') and self.weather_card.isVisible():
                    self.weather_card.hide()
                    if hasattr(self, 'search_pill') and hasattr(self.search_pill, 'btn_weather') and hasattr(self.search_pill.btn_weather, 'set_active'):
                        self.search_pill.btn_weather.set_active(False)
                    if self._should_show_minimal_music():
                        self.minimal_music_bar.show()
                    self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                    return True
                if hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible():
                    self.android_mirror_card.hide()
                    if hasattr(self, 'search_pill') and hasattr(self.search_pill, 'btn_phone') and hasattr(self.search_pill.btn_phone, 'set_active'):
                        self.search_pill.btn_phone.set_active(False)
                    if self._should_show_minimal_music():
                        self.minimal_music_bar.show()
                    self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                    return True
                self.sink()
                return True

        if event.type() == QEvent.Type.Enter:
            if self.leave_sink_timer.isActive():
                self.leave_sink_timer.stop()
        elif event.type() == QEvent.Type.Leave:
            if self._is_scrubbing_or_interacting() or (getattr(self, 'triggered_by_key', False) and hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive()) or self._is_user_actively_typing():
                return super().eventFilter(watched, event)
            if not getattr(self, '_is_menu_active', False):
                pos = QCursor.pos()
                if not self.is_cursor_in_active_zone(pos):
                    delay = int(self.settings.get("auto_hide_delay_ms", 120))
                    self.leave_sink_timer.start(delay)
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event):
        try:
            inp = getattr(self, 'input', None)
            if inp is not None and getattr(self, 'is_open', False) and getattr(self, 'capsule_mode', '') == "search":
                if not inp.hasFocus():
                    self.ensure_focus()
        except Exception:
            pass
        super().mouseMoveEvent(event)

    def enterEvent(self, event):
        if self.leave_sink_timer.isActive():
            self.leave_sink_timer.stop()
        if getattr(self, 'is_open', False) and getattr(self, 'capsule_mode', '') == "search":
            if not (hasattr(self, 'input') and self.input and self.input.hasFocus() and self.isActiveWindow()):
                self.ensure_focus()
        super().enterEvent(event)

    def ensure_focus(self, move_cursor_to_end: bool = False):
        """Immediately captures keyboard focus for instant typing while preserving caret position between characters."""
        if not self.isActiveWindow():
            self.raise_()
            self.activateWindow()
            force_foreground_focus(self.winId())
        if self.capsule_mode == "search":
            if hasattr(self, 'input') and self.input:
                prev_pos = self.input.cursorPosition()
                has_sel = self.input.hasSelectedText()
                sel_start = self.input.selectionStart()
                sel_len = len(self.input.selectedText()) if has_sel else 0
                if not self.input.hasFocus():
                    self.input.setFocus(Qt.FocusReason.OtherFocusReason)
                if move_cursor_to_end:
                    self.input.setCursorPosition(len(self.input.text()))
                elif has_sel and sel_start >= 0:
                    self.input.setSelection(sel_start, sel_len)
                else:
                    self.input.setCursorPosition(prev_pos)
        else:
            if not self.hasFocus():
                self.setFocus(Qt.FocusReason.OtherFocusReason)

    def leaveEvent(self, event):
        if getattr(self, '_opening_settings', False) or getattr(self, '_is_menu_active', False):
            super().leaveEvent(event)
            return
        if self._is_scrubbing_or_interacting() or (getattr(self, 'triggered_by_key', False) and hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive()) or self._is_user_actively_typing():
            super().leaveEvent(event)
            return
        pos = QCursor.pos()
        if not self.is_cursor_in_active_zone(pos):
            delay = int(self.settings.get("auto_hide_delay_ms", 120))
            self.leave_sink_timer.start(delay)
        super().leaveEvent(event)

    def _check_and_auto_sink(self):
        if not self.is_open or self.is_animating or getattr(self, '_opening_settings', False) or getattr(self, '_is_menu_active', False):
            return
        if self._weather_panel_pins_overlay():
            return
        if self._is_scrubbing_or_interacting() or (getattr(self, 'triggered_by_key', False) and hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive()) or self._is_user_actively_typing():
            return
        if not self.settings.get("auto_hide_on_leave", True):
            return
        pos = QCursor.pos()
        if not self.is_cursor_in_active_zone(pos):
            self.sink()

    def _update_surface_backdrop_blur(self):
        """Ensures the native HWND never renders a rectangular DWM backdrop behind the rounded Island surfaces."""
        try:
            hwnd = int(self.winId())
            odd_blur.ensure_transparent_hwnd(hwnd)

            rects = []
            if hasattr(self, "pill_column") and self.pill_column and self.pill_column.isVisible():
                p = self.pill_column
                from odd_theme import calculate_dynamic_squircle_radius
                r = calculate_dynamic_squircle_radius(p.width(), p.height())
                rects.append((p.x(), p.y(), p.width(), p.height(), r, r))
            if hasattr(self, "settings_btn") and self.settings_btn and self.settings_btn.isVisible():
                b = self.settings_btn
                br = min(b.width(), b.height()) / 2.0
                rects.append((b.x(), b.y(), b.width(), b.height(), br, br))

            dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
            odd_blur.apply_surface_backdrop_blur(hwnd, rects, dpr=dpr, enable=bool(rects))
        except Exception:
            return


    def mousePressEvent(self, event):
        pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
        if not self.is_cursor_in_active_zone(pos):
            if self._weather_panel_pins_overlay():
                event.ignore()
                return
            self.sink()
            event.accept()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.sink()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow() and not self._weather_panel_pins_overlay():
                if self.is_open and not getattr(self, '_opening_settings', False) and not getattr(self, '_is_menu_active', False) and not getattr(self, 'is_animating', False):
                    active_w = QApplication.activeWindow()
                    if active_w and active_w != self:
                        return super().changeEvent(event)
                    if hasattr(self, 'key_inactivity_timer'):
                        self.key_inactivity_timer.stop()
                    self.sink()
                    return super().changeEvent(event)
        super().changeEvent(event)

    def _check_focus_loss_sink(self):
        if self.is_open and not self._weather_panel_pins_overlay() and not self.isActiveWindow() and not self.is_animating and not getattr(self, '_opening_settings', False) and not getattr(self, '_is_menu_active', False):
            if getattr(self, 'capsule_mode', None) == 'music' or self._is_user_actively_typing():
                return
            if hasattr(self, 'key_inactivity_timer'):
                self.key_inactivity_timer.stop()
            self.sink()

    def keyPressEvent(self, event):
        if not getattr(self, "is_open", False) or not self.isVisible():
            return
        self.last_typing_time = time.time()
        if self.leave_sink_timer.isActive():
            self.leave_sink_timer.stop()


        if (event.key() == Qt.Key.Key_F4 and (event.modifiers() & Qt.KeyboardModifier.AltModifier)) or \
           (event.key() == Qt.Key.Key_W and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)) or \
           (event.key() == Qt.Key.Key_Escape):
            if hasattr(self, 'calendar_card') and self.calendar_card.isVisible():
                self.calendar_card.hide()
                self.input.clear()
                if self._should_show_minimal_music():
                    self.minimal_music_bar.show()
                self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                event.accept()
                return
            if hasattr(self, 'power_card') and self.power_card.isVisible():
                self.power_card.hide()
                if hasattr(self, 'btn_power') and hasattr(self.btn_power, 'set_active'):
                    self.btn_power.set_active(False)
                if self._should_show_minimal_music():
                    self.minimal_music_bar.show()
                self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                event.accept()
                return
            if hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible():
                self.quick_settings_card.hide()
                if hasattr(self, 'btn_quick_settings') and hasattr(self.btn_quick_settings, 'set_active'):
                    self.btn_quick_settings.set_active(False)
                if hasattr(self, 'search_pill') and hasattr(self.search_pill, 'btn_quick') and hasattr(self.search_pill.btn_quick, 'set_active'):
                    self.search_pill.btn_quick.set_active(False)
                if self._should_show_minimal_music():
                    self.minimal_music_bar.show()
                self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                event.accept()
                return
            if hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible():
                self.android_mirror_card.hide()
                if hasattr(self, 'search_pill') and hasattr(self.search_pill, 'btn_phone') and hasattr(self.search_pill.btn_phone, 'set_active'):
                    self.search_pill.btn_phone.set_active(False)
                self.input.clear()
                if self._should_show_minimal_music():
                    self.minimal_music_bar.show()
                self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                event.accept()
                return
            if hasattr(self, 'weather_card') and self.weather_card.isVisible():
                self.weather_card.hide()
                if hasattr(self, 'search_pill') and hasattr(self.search_pill, 'btn_weather') and hasattr(self.search_pill.btn_weather, 'set_active'):
                    self.search_pill.btn_weather.set_active(False)
                self.input.clear()
                if self._should_show_minimal_music():
                    self.minimal_music_bar.show()
                self.animate_to_geometry(self.capsule_width_contracted, self._get_resting_search_height())
                event.accept()
                return
            self.sink()
            event.accept()
            return

        # Forward any printable keystrokes to search input at its current cursor position if input was not focused
        if getattr(self, 'capsule_mode', '') == "search" and hasattr(self, 'input') and self.input and not self.input.hasFocus():
            txt = event.text()
            if txt and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
                prev_pos = self.input.cursorPosition()
                self.input.setFocus()
                self.input.setCursorPosition(prev_pos)
                self.input.insert(txt)
                event.accept()
                return

        if self.capsule_mode == "music":
            if event.key() == Qt.Key.Key_Space:
                self.media_mgr.toggle_play_pause()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Left:
                self.media_mgr.previous_track()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Right:
                self.media_mgr.next_track()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_M:
                self.media_mgr.toggle_master_mute()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_S:
                self.toggle_media_sources_panel()
                event.accept()
                return
            elif event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.switch_to_search_mode()
                event.accept()
                return
            elif event.text() and event.text().isprintable():
                self.switch_to_search_mode()
                self.input.setText(event.text())
                self.input.setFocus()
                event.accept()
                return

        super().keyPressEvent(event)

    @safe_slot
    def _on_search_debounce_timeout(self):
        self._do_search_query(
            self._pending_search_text,
            generation=self._pending_search_generation,
        )

    @safe_slot
    def on_query_changed(self, text: str):
        if getattr(self, '_suppress_query_changed', False) or not getattr(self, "is_open", False) or not self.isVisible():
            return
        try:
            # Invalidate any in-flight result as soon as the user edits, even
            # when they erase to empty and quickly retype the same query.
            self._search_cancel_event.set()
            self._search_cancel_event = threading.Event()
            if hasattr(self, "results_card"):
                self.results_card.stop_animations_for_typing()
            self._search_generation += 1
            generation = self._search_generation
            self.last_typing_time = time.time()
            if self.leave_sink_timer.isActive():
                self.leave_sink_timer.stop()
            if hasattr(self, 'key_inactivity_timer') and self.key_inactivity_timer.isActive():
                self.key_inactivity_timer.stop()

            query = text.strip()
            if not query:
                if hasattr(self, '_search_debounce_timer') and self._search_debounce_timer.isActive():
                    self._search_debounce_timer.stop()
                with self._search_request_lock:
                    self._pending_search_request = None
                self.current_results = []
                self._target_results_card_h = 0
                if hasattr(self, 'list_widget'):
                    self.list_widget.clear()
                self._hide_all_cards(except_card=None)
                show_min = self._should_show_minimal_music()
                if hasattr(self, 'minimal_music_bar'):
                    self.minimal_music_bar.setVisible(show_min)
                target_h = 146 if show_min else self._get_resting_search_height()
                self.animate_to_geometry(self.capsule_width_contracted, target_h)
                return

            self._pending_search_text = text
            self._pending_search_generation = generation

            # Instant UI command execution with 0ms debounce (calendar, weather, mirror, battery)
            low_q = query.lower()
            is_instant_command = (
                low_q in ("month cal", "cal", "calendar", "month", "monthly calendar", "month calendar", "cal today", "calendar today", "weather", "weather:", "forecast", "temp", "battery", "charging", "mirror", "phone") or
                low_q.startswith("cal ") or low_q.startswith("calendar ") or low_q.startswith("month cal ") or low_q.startswith("weather ") or low_q.startswith("w:") or low_q.startswith("mirror:") or low_q.startswith("phone:")
            )
            if is_instant_command:
                if hasattr(self, '_search_debounce_timer') and self._search_debounce_timer.isActive():
                    self._search_debounce_timer.stop()
                self._do_search_query(text, generation=generation)
                return

            # For normal search typing, immediately dismiss any open utility card
            self._hide_all_cards(except_card=getattr(self, 'results_card', None))

            # Keep file/app query work off GUI thread and debounce briefly
            if hasattr(self, '_search_debounce_timer'):
                self._search_debounce_timer.start(35)
            else:
                self._do_search_query(text, generation=generation)
        except Exception as e:
            pass

    @safe_slot
    def _on_async_search_ready(self, gen: int, results: list, query: str, t0: float):
        if gen != getattr(self, '_search_generation', 0):
            return  # Discard stale query results
        if not self.input or self.input.text().strip() != query:
            return  # Input was changed while search was computing
        self.current_results = results
        self._render_results(self.current_results, preserve_selection=False)
        t_ms = (time.perf_counter() - t0) * 1000.0
        try:
            import odd_profiler
            odd_profiler.record_search_latency(query, t_ms, len(self.current_results))
        except Exception:
            pass
        if hasattr(self, 'input') and self.input and not self.input.hasFocus():
            self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    @safe_slot
    def _do_search_query(self, text: str, generation=None):
        try:
            query = text.strip()
            if not query:
                return

            if hasattr(self, 'commands_guide_card') and self.commands_guide_card.isVisible():
                self.commands_guide_card.stop_showcase()
                self.commands_guide_card.hide()
            if hasattr(self, 'minimal_music_bar') and self.minimal_music_bar.isVisible():
                self.minimal_music_bar.hide()

            low_q = query.lower()
            is_cal_trigger = (
                low_q in ("month cal", "cal", "calendar", "month", "monthly calendar", "month calendar", "cal today", "calendar today") or
                low_q.startswith("month cal ") or low_q.startswith("monthly calendar ") or low_q.startswith("month calendar ") or
                low_q.startswith("cal ") or low_q.startswith("calendar ") or
                (low_q.startswith("month ") and any(m in low_q for m in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "next", "prev", "202", "203", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0")))
            )

            is_weather_trigger = (
                low_q in ("weather", "weather:", "forecast", "forecast:", "temp", "temperature", "w:") or
                low_q.startswith("weather") or low_q.startswith("w:")
            )
            if is_weather_trigger and hasattr(self, 'weather_card'):
                self._hide_all_cards(except_card=self.weather_card)
                self.current_results = []
                self._target_results_card_h = 0
                self.list_widget.clear()
                self.weather_card.refresh_weather()
                self._raise_utility_card(self.weather_card)
                card_h = self.weather_card.height()
                target_h = self._get_resting_search_height() + card_h + 8
                self.animate_to_geometry(self.capsule_width_contracted, target_h)
                self.weather_card.show()
                return

            is_charging_trigger = (
                low_q in ("battery", "battery:", "charging", "charging:", "charge", "charge:", "power", "batt") or
                low_q.startswith("battery") or low_q.startswith("charging") or low_q.startswith("charge")
            )
            if is_charging_trigger and hasattr(self, 'charging_card'):
                self._prepare_search_panel_base()
                self.current_results = []
                self._target_results_card_h = 0
                self.list_widget.clear()
                self.results_card.hide()
                if hasattr(self, 'weather_card') and self.weather_card.isVisible():
                    self.weather_card.hide()
                if hasattr(self, 'calendar_card') and self.calendar_card.isVisible():
                    self.calendar_card.hide()
                self.charging_card._refresh_battery()
                self._raise_utility_card(self.charging_card)
                is_side = str(self.settings.get("side_view", "off")).lower() in ("left", "right")
                if not is_side:
                    target_h = 56 + 144
                    self.animate_to_geometry(self.capsule_width_contracted, target_h)
                self.show_overlay_card(self.charging_card)
                return

            is_notif_trigger = (
                low_q in ("notification", "notifications", "notify", "notif", "alerts", "toast") or
                low_q.startswith("notif") or low_q.startswith("notify")
            )
            if is_notif_trigger:
                if hasattr(self, 'trigger_window') and hasattr(self.trigger_window, 'bezel_hud'):
                    self.trigger_window.bezel_hud.show_notification_hud(
                        "ODD Notifications Active",
                        "Windows system & app notifications are monitoring live.",
                        duration_ms=4500,
                        force=True
                    )

            if is_cal_trigger and hasattr(self, 'calendar_card'):
                self._hide_all_cards(except_card=self.calendar_card)
                self.current_results = []
                self._target_results_card_h = 0
                self.list_widget.clear()
                self.calendar_card.set_query(low_q)
                self.calendar_card.show()
                self._prepare_search_panel_base()
                self._raise_utility_card(self.calendar_card)
                cal_h = self.calendar_card.height() if hasattr(self.calendar_card, 'height') else 180
                target_h = self._get_resting_search_height() + cal_h + 8
                self.animate_to_geometry(self.capsule_width_contracted, target_h)
                return
            else:
                if hasattr(self, 'calendar_card') and self.calendar_card.isVisible():
                    self.calendar_card.hide()

            is_mirror_trigger = (
                low_q in ("mirror", "mirror:", "phone", "phone:", "android", "android:", "screen mirror", "phone mirror") or
                low_q.startswith("mirror:") or low_q.startswith("phone:")
            )
            if is_mirror_trigger and hasattr(self, 'android_mirror_card'):
                self._prepare_search_panel_base()
                self.current_results = []
                self._target_results_card_h = 0
                self.list_widget.clear()
                self.results_card.hide()
                if hasattr(self, 'quick_bar'):
                    self.quick_bar.hide()
                if hasattr(self, 'power_card') and self.power_card.isVisible():
                    self.power_card.hide()
                    self.btn_power.set_active(False)
                if hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible():
                    self.quick_settings_card.hide()
                    self.btn_quick_settings.set_active(False)
                if hasattr(self, 'weather_card') and self.weather_card.isVisible():
                    self.weather_card.hide()
                self.android_mirror_card.refresh_status()
                self.android_mirror_card.show()
                card_h = self.android_mirror_card.get_desired_height() if hasattr(self.android_mirror_card, "get_desired_height") else self.android_mirror_card.sizeHint().height()
                target_h = self._get_resting_search_height() + card_h + 8
                self.animate_to_geometry(self.capsule_width_expanded, target_h)
                return
            else:
                if hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible():
                    self.android_mirror_card.hide()

            if hasattr(self, 'quick_bar'):
                self.quick_bar.hide()
            self._hide_all_cards(except_card=getattr(self, 'results_card', None))

            try:
                odd_sound.play_type(self.settings)
            except Exception:
                pass

            # Keep only one active search runner per overlay. New keystrokes
            # replace its pending request instead of growing the executor's
            # otherwise unbounded work queue.
            gen = self._search_generation if generation is None else generation
            t0 = time.perf_counter()
            cancel_event = self._search_cancel_event

            try:
                from odd_tier import TierManager
                max_res = TierManager.get_instance().max_search_results
            except Exception:
                max_res = 6

            with self._search_request_lock:
                self._pending_search_request = (query, max_res, gen, t0, cancel_event)
                should_start_worker = not self._search_worker_active
                if should_start_worker:
                    self._search_worker_active = True

            if should_start_worker:
                try:
                    _SEARCH_EXECUTOR.submit(self._drain_search_requests)
                except RuntimeError:
                    with self._search_request_lock:
                        self._search_worker_active = False
                        self._pending_search_request = None
                    raise

        except Exception as e:
            try:
                err_path = Path(os.environ.get("APPDATA", "")) / "ODD" / "error.log"
                with open(err_path, "a") as f:
                    f.write(f"\n--- Search Query Error ---\n{e}\n")
            except Exception:
                pass

    def _drain_search_requests(self):
        """Process searches serially, coalescing queued edits to the newest text."""
        while True:
            with self._search_request_lock:
                request = self._pending_search_request
                self._pending_search_request = None
                if request is None:
                    self._search_worker_active = False
                    return

            query, max_results, gen, started_at, cancel_event = request
            try:
                results = self.search_engine.search(
                    query,
                    max_results=max_results,
                    include_windows_search=False,
                    cancel_event=cancel_event,
                )
                if cancel_event.is_set():
                    continue
                if not results:
                    import urllib.parse
                    results = [SearchItem(
                        f"g_{query}",
                        f"Search Google for '{query}'",
                        "Web Search • Press Enter to open in browser",
                        "Web",
                        f"https://www.google.com/search?q={urllib.parse.quote(query)}",
                        score=100,
                    )]
            except Exception:
                # A transient query failure should not kill the worker or the
                # app. The next edit can still be processed by this runner.
                continue

            with self._search_request_lock:
                newer_request_waiting = self._pending_search_request is not None
            if not newer_request_waiting and gen == self._search_generation:
                self.async_search_ready.emit(gen, results, query, started_at)

    def _render_results(self, items, preserve_selection: bool = False):
        """
        Transitions search items inside the continuous Island surface at instant 0ms typing speed.
        """
        if hasattr(self, 'calendar_card') and self.calendar_card.isVisible():
            return

        # Search results often stay visually identical while the user edits
        # a query. Keep the newest actions, but avoid rebuilding and animating
        # the same rows on every equivalent result set.
        signature = tuple(
            (item.id, item.title, item.subtitle, item.category, item.target, item.score)
            for item in items
        )
        if signature == getattr(self, '_rendered_result_signature', None) and self.results_card.isVisible():
            self.current_results = items
            if not preserve_selection and self.list_widget.currentRow() != 0:
                self.list_widget.setCurrentRow(0)
            return

        # Stop any lingering fade animation on results_card
        key = id(self.results_card)
        old_anim = self._content_animations.pop(key, None)
        if old_anim:
            old_anim.stop()
        self._content_effects.pop(key, None)
        self.results_card.setGraphicsEffect(None)

        if not items:
            self._rendered_result_signature = None
            self._target_results_card_h = 0
            if hasattr(self, 'results_card'):
                self.results_card.hide()
            if hasattr(self, 'list_widget'):
                for idx in range(self.list_widget.count()):
                    it = self.list_widget.item(idx)
                    w = self.list_widget.itemWidget(it)
                    if w:
                        w.deleteLater()
                self.list_widget.clear()
            has_q = bool(self.input and self.input.text().strip())
            show_min = self._should_show_minimal_music() and not has_q
            if hasattr(self, 'minimal_music_bar'):
                self.minimal_music_bar.setVisible(show_min)
            target_h = 146 if show_min else 56
            self.animate_to_geometry(self.capsule_width_contracted, target_h)
            return

        if hasattr(self, 'minimal_music_bar') and self.minimal_music_bar.isVisible():
            self.minimal_music_bar.hide()

        was_hidden = self.results_card.isHidden() or (self.spring_h.value <= 62.0 and getattr(self, "_target_results_card_h", 0) == 0)

        current_row = self.list_widget.currentRow() if preserve_selection else 0
        if current_row < 0:
            current_row = 0

        theme = self.get_current_theme()
        selected_idx = min(current_row, len(items) - 1)
        existing_count = self.list_widget.count()
        new_count = len(items)

        self.list_widget.setUpdatesEnabled(False)
        try:
            for idx, item in enumerate(items):
                is_sel = (idx == selected_idx)
                if idx < existing_count:
                    list_item = self.list_widget.item(idx)
                    widget = self.list_widget.itemWidget(list_item)
                    if isinstance(widget, ResultItemWidget):
                        if was_hidden:
                            widget.item = item
                            widget.theme = theme
                            widget.set_selected(is_sel, immediate=True)
                            widget.start_staggered_enter(delay_ms=idx * 12)
                        else:
                            widget.transition_to_item(item, theme=theme, selected=is_sel, delay_ms=0)
                    else:
                        widget = ResultItemWidget(item, theme=theme)
                        widget.set_selected(is_sel, immediate=True)
                        if was_hidden:
                            widget.start_staggered_enter(delay_ms=idx * 12)
                        list_item.setSizeHint(QSize(0, 56))
                        self.list_widget.setItemWidget(list_item, widget)
                else:
                    list_item = QListWidgetItem(self.list_widget)
                    widget = ResultItemWidget(item, theme=theme)
                    widget.set_selected(is_sel, immediate=True)
                    if was_hidden:
                        widget.start_staggered_enter(delay_ms=idx * 12)
                    list_item.setSizeHint(QSize(0, 56))
                    self.list_widget.addItem(list_item)
                    self.list_widget.setItemWidget(list_item, widget)

            # Trim any surplus rows from the bottom and safely delete widgets to prevent leaks
            for rm_idx in range(existing_count - 1, new_count - 1, -1):
                it = self.list_widget.item(rm_idx)
                w = self.list_widget.itemWidget(it)
                self.list_widget.removeItemWidget(it)
                if w:
                    w.deleteLater()
                taken = self.list_widget.takeItem(rm_idx)
                del taken

            self.list_widget.blockSignals(True)
            self.list_widget.setCurrentRow(selected_idx)
            self.list_widget.blockSignals(False)
        finally:
            self.list_widget.setUpdatesEnabled(True)

        # Each item is 56px tall + 4px bottom margin from QSS = 60px effective row height
        # Card layout has 4px top + 8px bottom margins = 12px overhead
        item_row_h = 60  # 56px widget + 4px QSS margin-bottom
        needed_list_h = len(items) * item_row_h + 8   # +8 for last item no-margin
        max_card_h = 440
        card_h = min(max_card_h, needed_list_h + 14)          # +14 for card_layout margins (4+8+2 spacing)
        self._target_results_card_h = card_h
        
        # When results exceed max_card_h, let the list widget scroll inside results_card!
        if needed_list_h + 14 > max_card_h:
            self.list_widget.setFixedHeight(card_h - 14)
            self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.list_widget.setFixedHeight(max(56, needed_list_h))
            self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.results_card.setFixedHeight(card_h)
        self._rendered_result_signature = signature

        is_side = str(self.settings.get("side_view", "off")).lower() in ("left", "right")
        if not is_side:
            target_h = min(self.capsule_height_expanded, self._get_resting_search_height() + 8 + card_h)
            self.animate_to_geometry(self.capsule_width_expanded, target_h)
        self._hide_all_cards(except_card=self.results_card)
        self.results_card.show()
        if was_hidden and hasattr(self, 'results_card') and hasattr(self.results_card, 'trigger_cascade'):
            self.results_card.trigger_cascade()
        elif hasattr(self, 'results_card'):
            self.results_card.start_shine()


    def on_row_changed(self, current_row: int):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if isinstance(widget, ResultItemWidget):
                widget.set_selected(i == current_row)
        if 0 <= current_row < self.list_widget.count():
            item = self.list_widget.item(current_row)
            self.list_widget.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible)

    def on_item_clicked(self, list_item: QListWidgetItem):
        row = self.list_widget.row(list_item)
        if 0 <= row < len(self.current_results):
            self._execute_item(self.current_results[row])

    def execute_selected(self):
        if hasattr(self, 'calendar_card') and self.calendar_card.isVisible():
            self.calendar_card.copy_selected_date()
            return

        curr = self.list_widget.currentRow()
        if 0 <= curr < len(self.current_results):
            self._execute_item(self.current_results[curr])
        else:
            query = self.input.text().strip()
            if query:
                import urllib.parse
                item = SearchItem(
                    f"g_{query}",
                    f"Search '{query}'",
                    "Web Search",
                    "Web",
                    f"https://www.google.com/search?q={urllib.parse.quote(query)}",
                    score=100
                )
                self._execute_item(item)

    def _execute_item(self, item: SearchItem):
        if item.id == "cmd_settings":
            self.sink()
            self._open_settings_modal()
            return
        elif item.id == "cmd_quick_settings":
            self.input.blockSignals(True)
            self.input.clear()
            self.input.blockSignals(False)
            if not self.quick_settings_card.isVisible():
                self.toggle_quick_settings_panel()
            return
        elif item.id == "cmd_media":
            self.switch_to_music_mode()
            return
        elif item.id == "cmd_chat" or item.id.startswith("chat_open_"):
            target_friend = getattr(item, "target", "") if item.id.startswith("chat_open_") else None
            self.switch_to_chat_mode(target_friend)
            return
        elif item.id.startswith("cheat_"):
            target_code = getattr(item, "target", "")
            if target_code:
                val = target_code if target_code in ("clp", "help", "rook") else (target_code + " ")
                self.input.setText(val)
                self.input.setFocus()
                return
        elif item.id in ("split_pending_preview", "msg_typing_preview"):
            self.input.setFocus()
            return

        # Smoothly sink and dismiss the overlay immediately on command execution ("task completed and gone")
        self.sink()

        self._in_messaging_disambiguation = False
        try:
            odd_sound.play_action(self.settings)
        except Exception:
            pass
        try:
            if hasattr(item, 'action') and callable(item.action):
                item.action()
            elif hasattr(self.search_engine, 'execute'):
                self.search_engine.execute(item)
            elif hasattr(self.search_engine, '_open_target') and hasattr(item, 'target'):
                self.search_engine._open_target(item.target)
        except Exception as e:
            try:
                err_path = Path(os.environ.get("APPDATA", "")) / "ODD" / "error.log"
                with open(err_path, "a") as f:
                    f.write(f"\n--- Execute Item Error ---\n{e}\n")
            except Exception:
                pass
        if not getattr(self, "_in_messaging_disambiguation", False):
            self.sink()

    def _detect_browser_safe_top_offset(self) -> int:
        """ODD 2.0 Dynamic Island is anchored flush to the top display edge with zero gap."""
        return 0

    def _anchor_window_canvas(self, content_bottom_y: float = 780.0):
        """Pre-calculates and anchors the top-level transparent canvas at the configured edge without X/Y jitter."""
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return
        screen = screen.geometry()
        edge = self.settings.get("edge", "top")
        side_view = str(self.settings.get("side_view", "off")).lower()
        if side_view in ("left", "right"):
            win_w = 980
            win_h = max(280, min(screen.height() - 100, int(math.ceil(content_bottom_y + 40.0))))
            win_y = screen.y() + 85
            if side_view == "left":
                win_x = screen.x()
            else:
                win_x = screen.x() + screen.width() - win_w
            cur_geo = self.geometry()
            if cur_geo.x() != win_x or cur_geo.y() != win_y or cur_geo.width() != win_w or cur_geo.height() != win_h:
                self.setGeometry(win_x, win_y, win_w, win_h)
            return

        top_safe_offset = 0
        win_w = int(self._canvas_width)
        available_h = max(160, screen.height() - top_safe_offset - 40)
        win_h = max(160, min(available_h, int(math.ceil(content_bottom_y + 40.0))))

        if edge == "top":
            win_x = screen.x() + (screen.width() - win_w) // 2
            win_y = screen.y() + top_safe_offset
        elif edge == "bottom":
            win_x = screen.x() + (screen.width() - win_w) // 2
            win_y = screen.y() + screen.height() - win_h
        elif edge == "left":
            win_x = screen.x()
            win_y = screen.y() + (screen.height() - win_h) // 2
        else:  # right
            win_x = screen.x() + screen.width() - win_w
            win_y = screen.y() + (screen.height() - win_h) // 2

        cur_geo = self.geometry()
        if cur_geo.x() != win_x or cur_geo.y() != win_y or cur_geo.width() != win_w or cur_geo.height() != win_h:
            self.setGeometry(win_x, win_y, win_w, win_h)

    def _apply_island_frame(
        self,
        pill_x: float,
        pill_y: float,
        pill_w: float,
        pill_h: float,
        btn_x: float,
        btn_y: float,
        btn_opacity: float,
        show_pill: bool = True,
        show_btn: bool = True,
    ):
        """Deterministically positions pill_column and settings_btn in a single unified coordinate pass."""
        edge = self.settings.get("edge", "top")
        if edge == "bottom":
            needed_h = max(pill_h + 56.0, 260.0)
        else:
            needed_h = max(pill_y + pill_h, btn_y + 56.0)
        if needed_h + 24.0 > self.height():
            self._anchor_window_canvas(needed_h)

        if hasattr(self, "pill_column") and self.pill_column:
            pw = max(1, min(3840, int(round(pill_w))))
            ph = max(4, min(3840, int(round(pill_h))))
            px = int(round(pill_x))
            py = int(round(pill_y))
            if self.pill_column.width() != pw or self.pill_column.height() != ph:
                self.pill_column.setFixedSize(pw, ph)
            if self.pill_column.x() != px or self.pill_column.y() != py:
                self.pill_column.move(px, py)
            vis_pill = bool(show_pill and self._pill_surface_opacity > 0.005)
            if self.pill_column.isVisible() != vis_pill:
                self.pill_column.setVisible(vis_pill)

        # Position active overlay / results cards to the side in side view
        side_mode = str(self.settings.get("side_view", "off")).lower()
        if side_mode in ("left", "right"):
            self._ensure_card_parenting()
            active_side_card = None
            for sc in (
                getattr(self, 'results_card', None),
                getattr(self, 'weather_card', None),
                getattr(self, 'calendar_card', None),
                getattr(self, 'charging_card', None),
                getattr(self, 'power_card', None),
                getattr(self, 'quick_settings_card', None),
                getattr(self, 'commands_guide_card', None),
            ):
                if sc and sc.isVisible():
                    active_side_card = sc
                    break
            if active_side_card:
                c_w = active_side_card.width()
                c_h = active_side_card.height()
                if side_mode == "left":
                    target_cx = int(pill_x + pill_w + 58.0 + 14.0)
                else:
                    target_cx = max(10, int(pill_x - c_w - 14.0))
                target_cy = int(pill_y)
                if active_side_card.x() != target_cx or active_side_card.y() != target_cy:
                    active_side_card.move(target_cx, target_cy)
                active_side_card.raise_()

        # Smooth height interpolation for ResultsCard as the single Island container expands/contracts
        if hasattr(self, "results_card") and self.results_card and self.results_card.isVisible():
            avail_card_h = max(0, int(round(pill_h - 54.0)))
            if getattr(self, "_target_results_card_h", 0) == 0 and avail_card_h <= 6:
                self.results_card.hide()
                self.list_widget.clear()
                if self.is_open and self.capsule_mode == "search" and not (self.input and self.input.text().strip()):
                    subcard_open = (
                        (hasattr(self, 'weather_card') and self.weather_card.isVisible())
                        or (hasattr(self, 'android_mirror_card') and self.android_mirror_card.isVisible())
                        or (hasattr(self, 'commands_guide_card') and self.commands_guide_card.isVisible())
                        or (hasattr(self, 'power_card') and self.power_card.isVisible())
                        or (hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible())
                        or (hasattr(self, 'calendar_card') and self.calendar_card.isVisible())
                    )
                    if not subcard_open:
                        show_min = self._should_show_minimal_music()
                        if hasattr(self, "minimal_music_bar"):
                            self.minimal_music_bar.setVisible(show_min)
                        target_h = 146 if show_min else 56
                        if abs(self.spring_h.target - target_h) > 1.0:
                            self.animate_to_geometry(self.capsule_width_contracted, target_h)
            else:
                # ResultsCard height is set once when results arrive.
                # Avoid per-frame setFixedHeight to eliminate 144 layout thrashing passes per second!
                pass

        if hasattr(self, "settings_btn") and self.settings_btn:
            bx = int(round(btn_x))
            by = int(round(btn_y))
            if self.settings_btn.x() != bx or self.settings_btn.y() != by:
                self.settings_btn.move(bx, by)
            self.settings_btn.set_opacity(max(0.0, min(1.0, btn_opacity)))
            vis_btn = bool(show_btn and btn_opacity > 0.015)
            if self.settings_btn.isVisible() != vis_btn:
                self.settings_btn.setVisible(vis_btn)
            if vis_btn:
                self.settings_btn.raise_()

        self.update()
        if hasattr(self, "_update_surface_backdrop_blur"):
            self._update_surface_backdrop_blur()



    def animate_to_geometry(self, new_width: int, new_height: int):
        """Continuous fluid critically-damped morphing of the single Island surface (zero bounce)"""
        target_pill_w = float(new_width)
        target_h = float(new_height)
        if self._choreo_mode == "open":
            # User started typing or interacting during opening: complete open state seamlessly and morph
            self._choreo_timer.stop()
            self._choreo_mode = "idle"
            self._pill_surface_opacity = 1.0
            self._surface_opacity = float(self.settings.get("opacity", 0.98))
            if hasattr(self, "search_pill") and self.search_pill:
                self.search_pill.set_content_opacity(1.0)
            edge = self.settings.get("edge", "top")
            if edge == "bottom":
                target_y = float(self.height() - target_h - self.edge_offset)
            else:
                target_y = float(self.edge_offset)
            self.spring_y.snap_to(target_y)
            self.spring_opacity.snap_to(1.0)
            self.pill_column_layout.setContentsMargins(0, 4, 0, 4)

        edge = self.settings.get("edge", "top")
        needed_h = float(target_h + self.edge_offset + 48.0)
        if needed_h > self.height():
            self._anchor_window_canvas(needed_h)

        if edge == "bottom":
            target_y = float(self.height() - target_h - self.edge_offset)
            self.spring_y.set_target(target_y, preserve_velocity=True)

        # Keep search card expansion ultra-responsive and physical (Expressive Spatial Spring)
        if self.capsule_mode == "search" and not (hasattr(self, 'quick_settings_card') and self.quick_settings_card.isVisible()):
            if target_pill_w > self.spring_pill_w.value:
                # Horizontal expansion: rapid expansion, shoots past target width (overshoot), oscillates & settles
                self.spring_pill_w.set_expressive_preset(damping=0.62, stiffness=480.0)
                self.spring_h.set_expressive_preset(damping=0.75, stiffness=520.0)
            else:
                self.spring_pill_w.set_expressive_preset(damping=0.80, stiffness=380.0)
                self.spring_h.set_expressive_preset(damping=0.82, stiffness=420.0)
        self.spring_pill_w.set_target(target_pill_w, preserve_velocity=True)
        self.spring_h.set_target(target_h, preserve_velocity=True)
        self.spring_reveal.set_target(1.0, preserve_velocity=True)
        self.spring_engine.start()

    def prewarm_overlay_surface(self):
        """
        Lightweight pre-warm:
        - Pre-anchors the canvas at screen center so geometry is calculated.
        - Pre-generates the acrylic noise tile (~16KB) ahead of time.
        - Warms the DirectX composition surface and DWM backdrop without on-screen flashing.
        - Pre-populates Qt render pipeline glyph and layout caches.
        Uses virtually zero RAM and completely eliminates first-time animation stutter.
        """
        try:
            self._anchor_window_canvas(160.0)
            try:
                from fluentapp.windoweffect import WindowBlur
                WindowBlur._get_frosted_noise_pixmap()
            except Exception:
                pass

            odd_blur.ensure_transparent_hwnd(int(self.winId()))
            if hasattr(self, 'search_pill'):
                self.search_pill.adjustSize()
            if hasattr(self, 'settings_btn'):
                self.settings_btn.adjustSize()
        except Exception as e:
            print(f"[ODD] Prewarm surface error: {e}")

    def surface(self, from_key: bool = False):
        """
        Surfaces search interface. Redirects cleanly to the cursor-first Dedicated Search Panel
        when invoked from a key press while radial menu / cursor search is enabled.
        Top hover or unprompted edge triggers are suppressed.
        """
        if not from_key and self.settings.get("radial_menu_enabled", True):
            # Suppress unprompted top-edge hover/mouse triggers from opening search under radial architecture
            return

        rc = getattr(self, "radial_controller", None)
        if rc is not None and self.settings.get("radial_menu_enabled", True):
            pos = QCursor.pos()
            rc.search_panel.open_at_cursor(pos)
            return

        if self.is_open and self._choreo_mode != "close":
            self.ensure_focus()
            return

        self.is_open = True
        self.is_animating = True
        self._is_morphing = True
        self.surface_timestamp = time.time()
        self.leave_sink_timer.stop()
        self.auto_hide_watcher.stop()
        self.spring_engine.stop()
        self._choreo_timer.stop()

        if from_key or not self.is_cursor_in_active_zone(QCursor.pos()):
            self.triggered_by_key = True
            if hasattr(self, 'key_inactivity_timer'):
                self.key_inactivity_timer.start(7000)
        else:
            self.triggered_by_key = False
            if hasattr(self, 'key_inactivity_timer'):
                self.key_inactivity_timer.stop()

        self._cursor_has_entered_island = self.is_cursor_in_active_zone(QCursor.pos())

        if hasattr(self, '_reveal_timer'):
            self._reveal_timer.stop()
        if hasattr(self, '_sink_stage_timer'):
            self._sink_stage_timer.stop()
        if hasattr(self, '_anim_watchdog'):
            self._anim_watchdog.start(420)

        # Immediately dismiss any overlapping notification HUD so it does not linger over the overlay
        if hasattr(self, 'trigger_window') and self.trigger_window:
            if hasattr(self.trigger_window, 'bezel_hud') and self.trigger_window.bezel_hud:
                if self.trigger_window.bezel_hud.isVisible():
                    self.trigger_window.bezel_hud.cancel_notification()
            if hasattr(self.trigger_window, 'hud') and self.trigger_window.hud:
                if getattr(self.trigger_window.hud, 'current_hud_type', None) in ('notification', 'reminder'):
                    self.trigger_window.hud.dismiss_hud(immediate=True)
            self.trigger_window._hover_progress = 0.0
            self.trigger_window.is_hovered = False
            self.trigger_window._hover_start_time = None
            if hasattr(self.trigger_window, 'anim_hover'):
                self.trigger_window.anim_hover.stop()
            self.trigger_window._update_input_mask()
            self.trigger_window.update()

        try:
            self._prev_foreground_hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        except Exception:
            self._prev_foreground_hwnd = None
        self._browser_safe_top_offset = self._detect_browser_safe_top_offset()
        self._last_auto_hide_cursor_pos = QCursor.pos()

        if hasattr(self, 'input') and self.input:
            self.input.setEnabled(True)

        self._suppress_query_changed = True
        try:
            self.input.clear()
        finally:
            self._suppress_query_changed = False

        self.current_results = []
        self._target_results_card_h = 0
        if hasattr(self, 'results_card'):
            self.results_card.hide()
        self.sources_card.hide()
        self.list_widget.clear()
        self.sources_list_widget.clear()
        if hasattr(self, 'calendar_card'):
            self.calendar_card.hide()
        if hasattr(self, 'quick_bar'):
            self.quick_bar.hide()
        if hasattr(self, 'power_card'):
            self.power_card.hide()
        if hasattr(self, 'quick_settings_card'):
            self.quick_settings_card.hide()
        if hasattr(self, 'weather_card'):
            self.weather_card.hide()
        if hasattr(self, 'android_mirror_card'):
            self.android_mirror_card.hide()

        if hasattr(self, 'search_pill'):
            if hasattr(self.search_pill, 'btn_weather') and hasattr(self.search_pill.btn_weather, 'set_active'):
                self.search_pill.btn_weather.set_active(False)
            if hasattr(self.search_pill, 'btn_quick') and hasattr(self.search_pill.btn_quick, 'set_active'):
                self.search_pill.btn_quick.set_active(False)
            if hasattr(self.search_pill, 'btn_phone') and hasattr(self.search_pill.btn_phone, 'set_active'):
                self.search_pill.btn_phone.set_active(False)

        music_mode = str(self.settings.get("music_overlay_mode", "auto")).lower().strip()
        enable_music = bool(self.settings.get("enable_music_overlay", True))
        is_playing = bool(self.media_state.get("is_playing", False) or self.media_state.get("has_media", False))

        if enable_music and not from_key and (music_mode == "always" or (music_mode == "full_auto" and is_playing)):
            self.search_pill.hide()
            if hasattr(self, 'minimal_music_bar'):
                self.minimal_music_bar.hide()
            self.music_bar.show()
            if hasattr(self, 'music_bar'):
                self.music_bar.update_state(self.media_state)
            self.capsule_mode = "music"
            target_w = float(self.capsule_width_expanded)
            target_h = 148.0
            show_btn = False
        else:
            self.music_bar.hide()
            self.search_pill.show()
            self.search_pill.update_settings(self.settings)
            self.search_pill.set_content_opacity(0.0)
            if hasattr(self, 'minimal_music_bar'):
                show_min = self._should_show_minimal_music()
                if show_min:
                    self.minimal_music_bar.update_media_info(self.media_state)
                self.minimal_music_bar.setVisible(show_min)
            self.capsule_mode = "search"
            target_w = float(self.capsule_width_contracted)
            target_h = float(self._get_resting_search_height())
            is_container = str(self.settings.get("ui_theme_style", "classic")).lower().strip() == "container"
            show_btn = False if is_container else bool(self.settings.get("ui_show_settings_button", True))

        edge = self.settings.get("edge", "top")
        canvas_h = max(160.0, float(target_h + self.edge_offset + 32.0))
        self._anchor_window_canvas(canvas_h)
        odd_blur.ensure_transparent_hwnd(int(self.winId()))

        if edge == "bottom":
            target_y = float(self.height() - target_h - self.edge_offset)
        else:
            target_y = float(self.edge_offset)

        self._open_target_w = target_w
        self._open_target_h = target_h
        self._open_show_btn = show_btn

        # Snap internal springs to final targets so post-open morphs start from exact resting state
        self.spring_y.snap_to(target_y)
        self.spring_pill_w.snap_to(target_w)
        self.spring_h.snap_to(target_h)
        self.spring_btn_opacity.snap_to(1.0 if show_btn else 0.0)
        self.spring_opacity.snap_to(1.0)
        self.spring_reveal.snap_to(1.0)
        self.spring_squash.snap_to(0.0)

        self._pill_surface_opacity = 1.0
        self.pill_column_layout.setContentsMargins(0, 4, 0, 4)

        # Completely hide the resting edge bar window so it never blocks overlay clicks
        if hasattr(self, 'trigger_window') and self.trigger_window:
            self.trigger_window.hide()

        odd_sound.play_hover(self.settings)

        # Pre-position at initial compact frame BEFORE showing window so there is zero jump
        self._choreo_mode = "open"
        self._choreo_start_ts = time.perf_counter()
        self._choreo_duration_ms = 220.0
        self._on_choreo_tick()
        if not self.isVisible():
            self.show()

        self._choreo_timer.start()
        self.ensure_focus()
        QTimer.singleShot(40, self.ensure_focus)

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, 'trigger_window') and self.trigger_window:
            bezel = getattr(self.trigger_window, 'bezel_hud', None)
            if not (bezel and bezel.isVisible()):
                self.trigger_window.set_edge_bar_hidden(False)

    @safe_slot
    def _on_choreo_tick(self):
        now = time.perf_counter()
        elapsed_ms = (now - self._choreo_start_ts) * 1000.0
        raw_t = max(0.0, min(1.0, elapsed_ms / max(1.0, self._choreo_duration_ms)))
        base_op = float(self.settings.get("opacity", 0.98))
        center_btn_x = (self._canvas_width - 56.0) / 2.0
        edge = self.settings.get("edge", "top")

        if self._choreo_mode == "open":
            target_w = self._open_target_w
            target_h = self._open_target_h
            show_btn = self._open_show_btn

            btn_slot = 58.0 if show_btn else 0.0
            final_group_w = target_w + btn_slot
            final_pill_x = (self._canvas_width - final_group_w) / 2.0
            final_btn_x = final_pill_x + target_w + 2.0

            side_view = str(self.settings.get("side_view", "off")).lower()
            if side_view == "left":
                final_pill_x = 24.0
                final_btn_x = final_pill_x + target_w + 10.0
            elif side_view == "right":
                final_pill_x = float(self._canvas_width - final_group_w - 24.0)
                final_btn_x = final_pill_x + target_w + 10.0

            # New In-Animation: Slides down from top and expands into place
            if edge == "bottom":
                target_y = float(self.height() - target_h - self.edge_offset)
                start_y = float(self.height() + 15.0)
            elif edge == "left":
                target_y = float(self.edge_offset)
                start_y = target_y
            elif edge == "right":
                target_y = float(self.edge_offset)
                start_y = target_y
            else: # top
                target_y = float(self.edge_offset)
                # Starts above the top edge and slides down into view
                start_y = -target_h - 16.0

            start_w = target_w * 0.76
            start_h = target_h * 0.84

            t = raw_t
            # Silky smooth ease-out with subtle spring cushion
            ease_slide = 1.0 - math.pow(1.0 - t, 3.2)
            cushion = math.sin(t * math.pi) * math.pow(1.0 - t, 1.8) * 3.5

            cur_w = start_w + (target_w - start_w) * ease_slide
            cur_h = start_h + (target_h - start_h) * ease_slide
            cur_pill_x = (self._canvas_width - (cur_w + btn_slot)) / 2.0
            if edge == "top":
                cur_y = start_y + (target_y - start_y) * ease_slide + cushion
            elif edge == "bottom":
                cur_y = start_y + (target_y - start_y) * ease_slide - cushion
            else:
                cur_y = target_y

            if show_btn:
                cur_btn_x = cur_pill_x + cur_w + 2.0
                btn_op = max(0.0, min(1.0, t * 1.5))
                btn_scale = 0.82 + 0.18 * ease_slide
                if hasattr(self, "settings_btn") and self.settings_btn:
                    self.settings_btn.scale_spring.snap_to(btn_scale)
            else:
                cur_btn_x = cur_pill_x + cur_w + 2.0
                btn_op = 0.0

            self._pill_surface_opacity = 1.0
            self._surface_opacity = base_op

            # Reveal search content smoothly as it slides down into position
            if hasattr(self, "search_pill") and self.search_pill and self.capsule_mode == "search":
                self.search_pill.setVisible(True)
                content_t = max(0.0, min(1.0, (t - 0.12) / 0.88))
                content_ease = 1.0 - math.pow(1.0 - content_t, 2.0)
                self.search_pill.set_content_opacity(content_ease)

            self._apply_island_frame(
                pill_x=cur_pill_x,
                pill_y=cur_y,
                pill_w=cur_w,
                pill_h=cur_h,
                btn_x=cur_btn_x,
                btn_y=cur_y,
                btn_opacity=btn_op,
                show_pill=True,
                show_btn=show_btn,
            )

            if raw_t >= 1.0:
                self._choreo_timer.stop()
                self._choreo_mode = "idle"
                self._surface_opacity = base_op
                self._pill_surface_opacity = 1.0
                if hasattr(self, "settings_btn") and self.settings_btn:
                    self.settings_btn.scale_spring.snap_to(1.0)
                if hasattr(self, "search_pill") and self.search_pill:
                    self.search_pill.setVisible(True)
                    self.search_pill.set_content_opacity(1.0)
                self._on_spring_settled()

        elif self._choreo_mode == "close":
            # New Out-Animation: Slides back up smoothly into top edge and collapses (~180ms)
            if hasattr(self, "search_pill") and self.search_pill:
                content_op = max(0.0, 1.0 - raw_t * 2.8)
                self.search_pill.set_content_opacity(content_op)

            start_px = self._close_start_pill_x
            start_pw = self._close_start_pill_w
            start_ph = self._close_start_pill_h
            start_y = self._close_start_y
            show_btn = hasattr(self, "settings_btn") and self.settings_btn and self.settings_btn.isVisible()
            btn_slot = 58.0 if show_btn else 0.0

            side_view = str(self.settings.get("side_view", "off")).lower()
            if side_view == "left":
                end_px = -start_pw - 20.0
                end_y = start_y
            elif side_view == "right":
                end_px = float(self._canvas_width + 20.0)
                end_y = start_y
            elif edge == "bottom":
                end_px = (self._canvas_width - start_pw) / 2.0
                end_y = float(self.height() + 20.0)
            else: # top
                end_px = (self._canvas_width - start_pw) / 2.0
                end_y = -start_ph - 18.0

            t = raw_t
            # Accelerate upward into the top bezel smoothly
            ease_up = math.pow(t, 2.2)

            cur_pw = start_pw + (start_pw * 0.72 - start_pw) * ease_up
            cur_ph = start_ph + (start_ph * 0.80 - start_ph) * ease_up
            cur_px = (self._canvas_width - (cur_pw + btn_slot)) / 2.0
            cur_y = start_y + (end_y - start_y) * ease_up

            # Settings button slides up with the pill and fades
            cur_btn_x = cur_px + cur_pw + 2.0
            btn_op = max(0.0, 1.0 - t * 2.2)
            btn_scale = max(0.2, 1.0 - 0.7 * ease_up)
            if hasattr(self, "settings_btn") and self.settings_btn:
                self.settings_btn.scale_spring.snap_to(btn_scale)

            if cur_ph < 24.0 and hasattr(self, "search_pill") and self.search_pill:
                self.search_pill.setVisible(False)

            self._surface_opacity = base_op * max(0.0, 1.0 - t * 1.6)
            self._pill_surface_opacity = 1.0

            self._apply_island_frame(
                pill_x=cur_px,
                pill_y=cur_y,
                pill_w=cur_pw,
                pill_h=cur_ph,
                btn_x=cur_btn_x,
                btn_y=cur_y,
                btn_opacity=btn_op,
                show_pill=True,
                show_btn=(btn_op > 0.01),
            )

            if raw_t >= 1.0:
                self._choreo_timer.stop()
                self._choreo_mode = "idle"
                self._on_spring_settled()

    def paintEvent(self, event):
        painter = None

        
        # Performance overlay badge if enabled
        if getattr(self, "settings", {}).get("show_perf_overlay", False):
            try:
                import odd_goo
                engine = odd_goo.GooeyEngine.get_instance()
                if painter is None:
                    painter = QPainter(self)
                odd_goo.paint_perf_overlay(painter, QRectF(self.rect()), engine.fps, engine.last_frame_ms)
            except Exception:
                pass

    def _on_spring_tick(self):
        if self._choreo_mode != "idle":
            return

        visible_pill_w = max(80.0, self.spring_pill_w.value)
        cur_h = max(34.0, self.spring_h.value)
        cur_btn_opacity = max(0.0, min(1.0, self.spring_btn_opacity.value))
        cur_opacity = max(0.0, min(1.0, self.spring_opacity.value))

        show_btn_pref = bool(self.settings.get("ui_show_settings_button", True)) and (self.capsule_mode != "music")
        btn_slot_w = 58.0 * cur_btn_opacity if (show_btn_pref and cur_btn_opacity > 0.005) else 0.0
        total_group_w = visible_pill_w + btn_slot_w

        edge = self.settings.get("edge", "top")
        if edge == "bottom":
            cur_y = float(self.height() - cur_h - self.edge_offset)
        else:
            cur_y = self.spring_y.value

        if edge == "left":
            pill_x = float(self.edge_offset)
            btn_x = pill_x + visible_pill_w + 2.0
        elif edge == "right":
            pill_x = float(self._canvas_width - total_group_w - self.edge_offset)
            btn_x = pill_x + visible_pill_w + 2.0
        else:
            pill_x = (self._canvas_width - total_group_w) / 2.0
            btn_x = pill_x + visible_pill_w + 2.0

        eff_opacity = cur_opacity * float(self.settings.get("opacity", 0.98))
        self._surface_opacity = max(0.0, min(1.0, eff_opacity))
        self._pill_surface_opacity = 1.0

        self._apply_island_frame(
            pill_x=pill_x,
            pill_y=cur_y,
            pill_w=visible_pill_w,
            pill_h=cur_h,
            btn_x=btn_x,
            btn_y=cur_y,
            btn_opacity=cur_btn_opacity if show_btn_pref else 0.0,
            show_pill=True,
            show_btn=show_btn_pref,
        )

    def _on_spring_settled(self):
        if self._choreo_mode != "idle":
            return
        self.is_animating = False
        self._is_morphing = False
        if not self.is_open:
            self.hide()
            if hasattr(self, 'trigger_window') and self.trigger_window:
                self.trigger_window.show()
                self.trigger_window._hover_progress = 0.0
                self.trigger_window.is_hovered = False
                self.trigger_window._hover_start_time = None
                if hasattr(self.trigger_window, 'anim_hover'):
                    self.trigger_window.anim_hover.stop()
                self.trigger_window._update_input_mask()
                self.trigger_window.set_edge_bar_hidden(False)
                self.trigger_window.update()
            self._suppress_query_changed = True
            try:
                self.input.clear()
            finally:
                self._suppress_query_changed = False
            self._target_results_card_h = 0
            self._pill_surface_opacity = 1.0
            if hasattr(self, "search_pill") and self.search_pill:
                self.search_pill.set_content_opacity(1.0)
            self.results_card.hide()
            self.list_widget.clear()
            if hasattr(self, 'sources_card'):
                self.sources_card.hide()
            if hasattr(self, 'sources_list_widget'):
                self.sources_list_widget.clear()
            if hasattr(self, 'minimal_music_bar'):
                self.minimal_music_bar.hide()
            if hasattr(self, 'quick_settings_card'):
                self.quick_settings_card.hide()
            if hasattr(self, 'btn_quick_settings'):
                self.btn_quick_settings.set_active(False)
            if hasattr(self, 'power_card'):
                self.power_card.hide()
            if hasattr(self, 'btn_power'):
                self.btn_power.set_active(False)
            if hasattr(self, 'calendar_card'):
                self.calendar_card.hide()
            if hasattr(self, 'weather_card'):
                self.weather_card.hide()
            if hasattr(self, 'android_mirror_card'):
                self.android_mirror_card.hide()
            if hasattr(self, 'search_pill'):
                if hasattr(self.search_pill, 'btn_weather') and hasattr(self.search_pill.btn_weather, 'set_active'):
                    self.search_pill.btn_weather.set_active(False)
                if hasattr(self.search_pill, 'btn_quick') and hasattr(self.search_pill.btn_quick, 'set_active'):
                    self.search_pill.btn_quick.set_active(False)
                if hasattr(self.search_pill, 'btn_phone') and hasattr(self.search_pill.btn_phone, 'set_active'):
                    self.search_pill.btn_phone.set_active(False)
            self.spring_squash.snap_to(0.0)
            self.spring_opacity.snap_to(1.0)
        else:
            self._pill_surface_opacity = 1.0
            if hasattr(self, "search_pill") and self.search_pill:
                self.search_pill.set_content_opacity(1.0)
            if hasattr(self, 'pill_column') and self.pill_column:
                min_col_h = self._get_resting_search_height() if self.capsule_mode == "search" else 148
                self.pill_column.setFixedHeight(max(min_col_h, int(self.spring_h.value)))
                self.pill_column_layout.setContentsMargins(0, 4, 0, 4)
                self.pill_column.show()
            if hasattr(self, 'settings_btn') and self.settings_btn:
                show_btn = self.spring_btn_opacity.value > 0.02 and bool(self.settings.get("ui_show_settings_button", True)) and (self.capsule_mode != "music")
                self.settings_btn.setVisible(show_btn)
                self.settings_btn.set_opacity(1.0 if show_btn else 0.0)
                if show_btn:
                    self.settings_btn.raise_()
            if self.capsule_mode == "search":
                if not (hasattr(self, 'input') and self.input and self.input.hasFocus()):
                    self.ensure_focus()
            self.auto_hide_watcher.start()
            self._update_surface_backdrop_blur()
        self.update()

    def sink(self):
        """
        Coordinated Center-Tuck Exit Animation (~285ms):
        1. Search content fades out cleanly before narrowing.
        2. Search bar shrinks behind the circular ODD button WHILE the ODD button moves to the center simultaneously.
        3. Centered circular ODD button smoothly rises upward into the top resting position.
        """
        if not self.is_open and not getattr(self, '_is_morphing', False):
            return

        # Invalidate any debounced or running query before the result widgets
        # are hidden and cleared during the close animation.
        self._search_cancel_event.set()
        self._search_generation += 1
        if hasattr(self, '_search_debounce_timer') and self._search_debounce_timer.isActive():
            self._search_debounce_timer.stop()
        with self._search_request_lock:
            self._pending_search_request = None

        self.is_open = False
        self.is_animating = True
        self._is_morphing = True
        self.auto_hide_watcher.stop()
        self.leave_sink_timer.stop()
        self.spring_engine.stop()
        self._choreo_timer.stop()

        if hasattr(self, '_reveal_timer'):
            self._reveal_timer.stop()
        if hasattr(self, '_sink_stage_timer'):
            self._sink_stage_timer.stop()
        if hasattr(self, '_anim_watchdog'):
            self._anim_watchdog.start(420)

        if hasattr(self, "input") and self.input:
            self.input.clearFocus()
            self.input.setEnabled(False)
        self.clearFocus()

        if getattr(self, '_prev_foreground_hwnd', None):
            try:
                ctypes.windll.user32.SetForegroundWindow(self._prev_foreground_hwnd)
            except Exception:
                pass
            self._prev_foreground_hwnd = None

        if hasattr(self, 'search_pill'):
            if hasattr(self.search_pill, 'btn_weather') and hasattr(self.search_pill.btn_weather, 'set_active'):
                self.search_pill.btn_weather.set_active(False)
            if hasattr(self.search_pill, 'btn_quick') and hasattr(self.search_pill.btn_quick, 'set_active'):
                self.search_pill.btn_quick.set_active(False)
            if hasattr(self.search_pill, 'btn_phone') and hasattr(self.search_pill.btn_phone, 'set_active'):
                self.search_pill.btn_phone.set_active(False)
        if hasattr(self, 'weather_card'):
            self.weather_card.hide()
        if hasattr(self, 'android_mirror_card'):
            self.android_mirror_card.hide()
        if hasattr(self, 'quick_settings_card'):
            self.quick_settings_card.hide()
        if hasattr(self, 'power_card'):
            self.power_card.hide()

        self._target_results_card_h = 0

        # Capture exact current geometry for smooth continuation into the exit choreography
        if hasattr(self, "pill_column") and self.pill_column:
            self._close_start_pill_x = float(self.pill_column.x())
            self._close_start_pill_w = float(max(60, self.pill_column.width()))
            self._close_start_pill_h = float(max(48, self.pill_column.height()))
            self._close_start_y = float(self.pill_column.y())
        else:
            self._close_start_pill_w = float(self.capsule_width_contracted)
            self._close_start_pill_h = 56.0
            self._close_start_y = float(self.edge_offset)
            self._close_start_pill_x = (self._canvas_width - (self._close_start_pill_w + 58.0)) / 2.0

        if hasattr(self, "settings_btn") and self.settings_btn and self.settings_btn.isVisible():
            self._close_anchor_btn_x = float(self.settings_btn.x())
        else:
            self._close_anchor_btn_x = self._close_start_pill_x + self._close_start_pill_w + 2.0

        if hasattr(self, "settings_btn") and self.settings_btn:
            self.settings_btn.set_opacity(1.0)
            self.settings_btn.show()
            self.settings_btn.raise_()

        if hasattr(self, 'commands_guide_card') and self.commands_guide_card.isVisible():
            self.commands_guide_card.stop_showcase()
            self.commands_guide_card.hide()

        self._choreo_mode = "close"
        self._choreo_start_ts = time.perf_counter()
        self._choreo_duration_ms = 180.0
        self._on_choreo_tick()
        self._choreo_timer.start()

        if self.trigger_window:
            self.trigger_window._hover_start_time = None


INFOMATIC_QUOTES = ()


class EdgeTriggerWindow(QWidget):
    """
    Living Dynamic Island for Windows.
    Acts as the physical resting notch, morphing live event HUD (Media, Volume, Battery, Timers, Lock Keys),
    and effortless edge surface trigger for ODD.
    """
    def __init__(self, overlay: OddOverlay, settings: dict):
        super().__init__()
        self.overlay = overlay
        self.settings = settings
        self.is_hovered = False
        self._hover_start_time = None
        self.is_island_expanded = False
        self._hover_progress = 0.0
        self._startup_time = time.time()
        self._initial_mouse_pos = QCursor.pos()
        self._has_mouse_moved = False
        self._is_edge_bar_hidden = False

        # Smooth hover transition animation for resting edge bar
        self.anim_hover = QPropertyAnimation(self, b"hover_progress")
        self.anim_hover.setDuration(65)
        self.anim_hover.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._mouse_local_pos = None

        # 1. Dynamic Island HUD Engine & Background System Monitor
        self.hud = DynamicIslandHUD(self, self.settings)
        self.bezel_hud = OddBezelHUD(self.settings, trigger_window=self)
        if self.overlay:
            self.overlay.bezel_hud = self.bezel_hud
            self.overlay.trigger_window = self
        self.island_monitor = DynamicIslandMonitor(self.settings)

        self.island_monitor.volume_changed.connect(self._on_island_volume)
        self.island_monitor.mute_changed.connect(self._on_island_mute)
        self.island_monitor.battery_changed.connect(self._on_island_battery)
        self.island_monitor.lock_key_changed.connect(self._on_island_lock_key)
        self.island_monitor.clipboard_event.connect(self._on_island_clip_action)
        self.island_monitor.rook_event.connect(self._on_island_rook_action)
        self.island_monitor.timer_tick.connect(self._on_island_timer)
        self.island_monitor.notification_event.connect(self._on_island_notification)
        self.island_monitor.activities_updated.connect(self._on_island_activity_update)
        self.island_monitor.reminder_event.connect(self._on_island_reminder)
        self.island_monitor.internet_changed.connect(self._on_internet_changed)
        self.island_monitor.bluetooth_changed.connect(self._on_bluetooth_changed)

        # Context-Aware System & User Needs Intelligence Engine
        try:
            from odd_system_needs import SystemNeedsIntelligence
            self.system_needs = SystemNeedsIntelligence.get_instance(self.settings)
            self.system_needs.battery_reminder_auto_resolved.connect(self._on_battery_reminder_auto_resolved)
            self.system_needs.system_resource_alert.connect(self._on_system_resource_alert)
        except Exception:
            self.system_needs = None

        # Rich monochrome Info-matic Alert Engine with premium fade-in and fade-out
        self._infomatic_alert = None
        self._infomatic_queue = []
        self._infomatic_opacity = 0.0
        self._infomatic_progress = 0.0
        self._infomatic_anim_timer = QTimer(self)
        self._infomatic_anim_timer.setInterval(16)
        self._infomatic_anim_timer.timeout.connect(self._on_infomatic_anim_tick)

        # Connect to Windows Media Manager for live track changes & waveforms
        self.overlay.media_mgr.media_changed.connect(self._on_island_media)
        self.island_monitor.start()

        # Smooth edge watcher for top border bumping
        self.edge_watcher = QTimer(self)
        self.edge_watcher.setInterval(20)
        self.edge_watcher.timeout.connect(self._poll_edge_zone)
        self.edge_watcher.start()

        # Geometry morph animation for Dynamic Island expansions
        self.is_island_collapsing = False
        self.morph_anim = QPropertyAnimation(self, b"geometry")
        self.morph_anim.setDuration(70)
        self.morph_anim.setEasingCurve(QEasingCurve.Type.OutQuart)
        self.morph_anim.finished.connect(self._on_morph_finished)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._mouse_local_pos = None

        self.reposition()

    def nativeEvent(self, event_type, message):
        """
        Windows native hit-testing for EdgeTriggerWindow (WM_NCHITTEST = 0x0084):
        Returns False, 0 (HTCLIENT) ONLY when the cursor hits the physical resting notch pill
        or an active Dynamic Island HUD squircle.
        Returns True, -1 (HTTRANSPARENT) for all surrounding pixels, ensuring Chrome's tabs,
        tab close buttons, and window controls are 100% click-through without interference.
        """
        try:
            if event_type in ("windows_generic_MSG", "windows_dispatcher_MSG"):
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    # If overlay is already open, trigger window must yield all clicks to overlay/desktop
                    if self.overlay and (getattr(self.overlay, "is_open", False) or self.overlay.isVisible()):
                        return True, -1

                    # If Bezel HUD is showing an interactive notification or overlay, yield all clicks to Bezel HUD
                    bezel = getattr(self, "bezel_hud", None)
                    if bezel and bezel.isVisible() and not bezel.is_animating_out and getattr(bezel, "hud_type", None) in ("notification", "reminder", "wellness", "activity", "timer", "chat", "nearby_share"):
                        return True, -1

                    local_pt = self.mapFromGlobal(QCursor.pos())

                    # When island is expanded (HUD active)
                    if self.is_island_expanded and getattr(self.hud, 'current_hud_type', None):
                        from odd_island import _SYSTEM_STATUS_TYPES
                        if getattr(self.hud, 'current_hud_type', None) in _SYSTEM_STATUS_TYPES:
                            return True, -1  # Status indicators are passive
                        from odd_theme import calculate_dynamic_squircle_radius, create_squircle_path
                        r = calculate_dynamic_squircle_radius(self.width(), self.height())
                        hud_path = create_squircle_path(QRectF(self.rect()), r)
                        if hud_path.contains(QPointF(local_pt)):
                            return False, 0
                        return True, -1

                    # Resting notch state: strictly test the physical resting pill
                    pill_rect = self._resting_pill_rect()
                    if pill_rect.adjusted(-2, 0, 2, 4).contains(local_pt):
                        return False, 0

                    # All empty pixels outside physical notch: 100% click-through!
                    return True, -1
        except Exception:
            pass
        return super().nativeEvent(event_type, message)

    def get_resting_rect(self) -> QRect:
        """Returns the physical screen QRect of the resting edge bar."""
        screen = self._active_screen_geometry()
        edge = self.settings.get("edge", "top")
        edge_w = max(40, int(self.settings.get("edge_bar_width", 75)))
        edge_h = max(4, int(self.settings.get("edge_bar_thickness", 4)))
        if edge == "bottom":
            return QRect(screen.x() + (screen.width() - edge_w) // 2, screen.y() + screen.height() - edge_h, edge_w, edge_h)
        elif edge == "left":
            return QRect(screen.x(), screen.y() + (screen.height() - edge_w) // 2, edge_h, edge_w)
        elif edge == "right":
            return QRect(screen.x() + screen.width() - edge_h, screen.y() + (screen.height() - edge_w) // 2, edge_h, edge_w)
        else: # top
            return QRect(screen.x() + (screen.width() - edge_w) // 2, screen.y(), edge_w, edge_h)

    def set_edge_bar_hidden(self, hidden: bool):
        """Hides or reveals the resting edge bar indicator when an overlay is expanded."""
        self._is_edge_bar_hidden = bool(hidden)
        self.update()

    def should_show_music_edge_bar(self) -> bool:
        """True when media is actively playing and user has edge bar music indicator enabled"""
        if not self.settings.get("edge_bar_music_display", True):
            return False
        if not self.has_active_media_playing():
            return False
        if self.is_island_expanded:
            return False
        return True

    def _calc_resting_dimensions(self, hover_progress: float = 0.0) -> Tuple[int, int]:
        """Calculates exact width and height for resting notch ensuring content is snugly framed without empty space."""
        p = max(0.0, min(1.0, float(hover_progress)))
        edge = self.settings.get("edge", "top")
        width = max(40, int(self.settings.get("edge_bar_width", 75)))
        thickness = max(4, int(self.settings.get("edge_bar_thickness", 4)))
        activity = self.island_monitor.activity_mgr.get_merged_state()
        n_style = self.settings.get("edge_notch_style", "simple")

        if activity.get("has_active", False):
            from odd_island import format_download_filename
            active_items = activity.get("active_items", [])
            count = len(active_items)
            fm = QFontMetrics(QFont("Segoe UI Variable Text", 7.8, QFont.Weight.DemiBold))
            if count <= 1:
                item = active_items[0] if active_items else None
                raw_n = getattr(item, 'title', 'Download') if item else 'Download'
                t_str = format_download_filename(raw_n, 16)
                p_int = int(round(getattr(item, 'progress', activity.get('merged_progress', 0.0)) if item else 0.0))
                lbl = f"{t_str} — {p_int}%"
                text_w = fm.horizontalAdvance(lbl)
                pill_w = max(130, 14 + 18 + 8 + text_w + 14)
            elif count == 2:
                i1, i2 = active_items[0], active_items[1]
                t1 = format_download_filename(getattr(i1, 'title', 'DL 1'), 13)
                p1 = int(round(getattr(i1, 'progress', 0.0)))
                t2 = format_download_filename(getattr(i2, 'title', 'DL 2'), 13)
                p2 = int(round(getattr(i2, 'progress', 0.0)))
                w1 = fm.horizontalAdvance(f"{t1} {p1}%")
                w2 = fm.horizontalAdvance(f"{t2} {p2}%")
                pill_w = max(180, 12 + (16 + 6 + w1) + 16 + (16 + 6 + w2) + 12)
            else:
                p_int = int(round(activity.get('merged_progress', 0.0)))
                lbl = f"{count} Downloads — {p_int}%"
                text_w = fm.horizontalAdvance(lbl)
                pill_w = max(140, 14 + 18 + 8 + text_w + 14)
            pill_h = max(24, thickness + 18)
        elif getattr(self, "_infomatic_alert", None) and getattr(self, "_infomatic_progress", 0.0) > 0.001:
            # Active monochrome Info-matic notification capsule with smooth expand/collapse
            normal_w = width
            normal_h = max(4, thickness)
            title = self._infomatic_alert.get("title", "")
            fm = QFontMetrics(QFont("Segoe UI Variable Display", 8.4, QFont.Weight.DemiBold))
            text_w = fm.horizontalAdvance(title)
            # Fluid bounded capsule: comfortably accommodates up to 340px; device names fit naturally
            active_w = max(width, min(340, text_w + 64))
            active_h = 28
            ease_prog = self._infomatic_progress
            shrink_factor = max(0.0, 1.0 - p / 0.30)
            pill_w = int(normal_w + (active_w - normal_w) * ease_prog * shrink_factor)
            pill_h = int(normal_h + (active_h - normal_h) * ease_prog * shrink_factor)
        elif self.should_show_music_edge_bar():
            # Sleek music capsule with Spotify green icon & animated equalizer bars
            normal_w = width
            normal_h = max(4, thickness)
            active_w = max(152, int(width * 1.1))
            active_h = 24
            shrink_factor = max(0.0, 1.0 - p / 0.30)
            pill_w = int(normal_w + (active_w - normal_w) * shrink_factor)
            pill_h = int(normal_h + (active_h - normal_h) * shrink_factor)
        elif n_style in ("worded", "text_static", "text_scroll"):
            normal_w = width
            normal_h = max(4, thickness)
            n_text = str(self.settings.get("edge_notch_text", "ODD")).strip() or "ODD"
            fm = QFontMetrics(QFont("Segoe UI Variable Display", 7.8, QFont.Weight.Bold))
            tw = fm.horizontalAdvance(n_text)
            pill_w = max(width, tw + 24)
            pill_h = max(18, thickness + 12)
        else: # simple / plain bar
            pill_w = max(40, width)
            pill_h = max(2, thickness)

        return pill_w, pill_h

    def _resting_window_bounds(self) -> Tuple[int, int]:
        """Calculates window bounding box with comfortable padding so pill edges are never clipped"""
        pw, ph = self._calc_resting_dimensions(0.0)
        info_w = 0
        if getattr(self, "_infomatic_alert", None):
            title = self._infomatic_alert.get("title", "")
            fm = QFontMetrics(QFont("Segoe UI Variable Display", 8.4, QFont.Weight.DemiBold))
            info_w = max(int(self.settings.get("edge_bar_width", 75)), min(340, fm.horizontalAdvance(title) + 64))
        w = max(pw + 32, info_w + 48, int(self.settings.get("edge_bar_width", 75)) + 60, 360)
        h = max(ph + 16, 44)
        return w, h

    def _resting_pill_rect(self, hover_progress: float = None) -> QRect:
        """Return the exact painted resting pill, anchored directly to screen bezel."""
        p = self._hover_progress if hover_progress is None else hover_progress
        pw, ph = self._calc_resting_dimensions(p)
        edge = self.settings.get("edge", "top")

        if edge == "top":
            pill_x = (self.width() - pw) // 2
            top_y = 0
            return QRect(pill_x, top_y, pw, ph)
        elif edge == "bottom":
            pill_x = (self.width() - pw) // 2
            bot_y = self.height() - ph - (3 if (getattr(self, "_infomatic_alert", None) and getattr(self, "_infomatic_progress", 0.0) > 0.001) else 0)
            return QRect(pill_x, bot_y, pw, ph)
        elif edge == "left":
            pill_y = 0 if str(self.settings.get("side_view", "off")).lower() == "left" else (self.height() - pw) // 2
            return QRect(0, pill_y, ph, pw)
        else: # right
            pill_y = 0 if str(self.settings.get("side_view", "off")).lower() == "right" else (self.height() - pw) // 2
            return QRect(self.width() - ph, pill_y, ph, pw)

    @staticmethod
    def _rounded_region(rect: QRect, radius: float) -> QRegion:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        return QRegion(path.toFillPolygon().toPolygon())

    def _active_screen_geometry(self) -> QRect:
        scr = QApplication.screenAt(QCursor.pos()) or self.screen() or QApplication.primaryScreen()
        return scr.geometry() if scr is not None else QRect(0, 0, 1920, 1080)

    def _update_input_mask(self):
        """Make the invisible part of the transparent top-level window click-through."""
        if self.overlay and (self.overlay.is_open or self.overlay.isVisible()) and not self.is_island_expanded:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            if not getattr(self, '_mask_cleared', False):
                self.clearMask()
                self._mask_cleared = True
            return

        has_hud = bool(self.hud.current_hud_type)
        is_status_hud = bool(self.hud.current_hud_type in odd_island._SYSTEM_STATUS_TYPES)
        if has_hud and (self.is_island_expanded or self.is_island_collapsing):
            if is_status_hud:
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            else:
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            if not getattr(self, '_mask_cleared', False):
                self.clearMask()
                self._mask_cleared = True
            return

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        if self.settings.get("hide_edge_bar", False) or not self.settings.get("ui_show_edge_indicator", True):
            if self._hover_progress <= 0.05:
                if not getattr(self, '_mask_cleared', False):
                    self.clearMask()
                    self._mask_cleared = True
                return

        # During hover stretching or infomatic animation, clear mask so DWM renders smooth 60fps without GDI stutter
        if self._hover_progress > 0.03 or getattr(self, "_infomatic_alert", None) is not None:
            if not getattr(self, '_mask_cleared', False):
                self.clearMask()
                self._mask_cleared = True
            return

        pill_rect = self._resting_pill_rect()
        r_c = max(2.0, min(pill_rect.width(), pill_rect.height()) / 2.0)
        self.setMask(self._rounded_region(pill_rect, r_c))
        self._mask_cleared = False

    def resizeEvent(self, event):
        self._update_input_mask()
        super().resizeEvent(event)

    def _on_morph_finished(self):
        if getattr(self, "is_island_collapsing", False):
            self.is_island_collapsing = False
            self._status_pill_active = False
            self.hud.current_hud_type = None
            self.hud.hud_data = {}
            if self.hud.anim_timer.isActive() and not self.has_active_media_playing():
                self.hud.anim_timer.stop()
            self.reposition()
            self.update()
        self._update_input_mask()

    def update_settings(self, new_settings: dict):
        self.settings = new_settings
        self.hud.settings = new_settings
        self.bezel_hud.update_settings(new_settings)
        self.island_monitor.update_settings(new_settings)
        self.reposition()

    def has_active_media_playing(self) -> bool:
        return bool(self.overlay.media_state.get("is_playing", False))

    def _on_island_activity_update(self, state_dict: dict):
        has_active = state_dict.get("has_active", False)
        if not has_active:
            if self.is_island_expanded and getattr(self.hud, 'current_hud_type', None) in ("activity", "downloads"):
                self.hud.dismiss_hud()
        else:
            if self.is_island_expanded and getattr(self.hud, 'current_hud_type', None) in ("activity", "downloads"):
                self.hud.hud_data = state_dict
                self.hud.update()
        if not (self.morph_anim.state() == QPropertyAnimation.State.Running or getattr(self, "is_island_collapsing", False)):
            self.reposition()
        self.update()

    def _on_island_volume(self, vol: int):
        muted = bool(getattr(self.island_monitor, "_last_mute", False)) or (vol <= 0)
        if hasattr(self.overlay, "quick_settings_card") and self.overlay.quick_settings_card:
            self.overlay.quick_settings_card._apply_audio_val(vol, muted)
        if hasattr(self.overlay, "music_bar") and self.overlay.music_bar and hasattr(self.overlay.music_bar, "btn_mute"):
            self.overlay.music_bar.btn_mute.set_icon_type("mute" if muted else "volume")

    def _on_island_mute(self, is_muted: bool):
        vol = int(getattr(self.island_monitor, "_last_vol", 70))
        if vol < 0:
            vol = 70
        if hasattr(self.overlay, "quick_settings_card") and self.overlay.quick_settings_card:
            self.overlay.quick_settings_card._apply_audio_val(vol, is_muted)
        if hasattr(self.overlay, "music_bar") and self.overlay.music_bar and hasattr(self.overlay.music_bar, "btn_mute"):
            self.overlay.music_bar.btn_mute.set_icon_type("mute" if is_muted else "volume")
        if not self.overlay.is_open and self.settings.get("island_show_volume_hud", True):
            try:
                import odd_sound
                odd_sound.play_mute_sound(is_muted, self.settings)
            except Exception:
                pass
            self.bezel_hud.show_mute_hud(is_muted)

    def _on_island_battery(self, power_dict: dict):
        # 1. Update system & user needs intelligence
        try:
            from odd_system_needs import SystemNeedsIntelligence
            sni = SystemNeedsIntelligence.get_instance(self.settings)
            sni.on_power_changed(power_dict)
        except Exception:
            pass

        # 2. Check if the Dynamic Island HUD is displaying a battery reminder
        # If so, automatically identify whether charger is plugged/unplugged and auto-resolve!
        resolved = False
        if hasattr(self, 'hud') and self.hud and hasattr(self.hud, 'on_power_changed'):
            resolved = self.hud.on_power_changed(power_dict)

        # 3. Check if BezelHUD has an active battery reminder or notification
        if hasattr(self, 'bezel_hud') and self.bezel_hud and hasattr(self.bezel_hud, 'on_power_changed'):
            self.bezel_hud.on_power_changed(power_dict)

        # 4. If no active reminder was auto-resolved, show the battery HUD popup
        if not resolved and not self.overlay.is_open and self.settings.get("island_show_battery_hud", True):
            self.bezel_hud.show_battery_hud(power_dict)

    def _on_island_lock_key(self, key_name: str, is_on: bool):
        if not self.overlay.is_open and self.settings.get("island_show_caps_lock_hud", True):
            try:
                import odd_sound
                odd_sound.play_lock_sound(is_on, self.settings)
            except Exception:
                pass
            if key_name == "caps_lock":
                self.bezel_hud.show_caps_lock_hud(is_on)
            elif key_name == "num_lock":
                self.bezel_hud.show_num_lock_hud(is_on)
            elif key_name == "scroll_lock":
                self.bezel_hud.show_scroll_lock_hud(is_on)
            else:
                self.bezel_hud.show_caps_lock_hud(is_on)

    def _on_island_notification(self, title: str, message: str, app_icon=None, primary_id: str = ""):
        if not self.overlay.is_open and self.settings.get("island_show_system_notifications", True) and not self.settings.get("dnd_enabled", False):
            try:
                import odd_sound
                odd_sound.play_notification(self.settings)
            except Exception:
                pass
            dur_sec = float(self.settings.get("notification_duration_sec", 5))
            self.bezel_hud.show_notification_hud(title, message, duration_ms=int(dur_sec * 1000), app_icon=app_icon, primary_id=primary_id)

    def _on_island_reminder(self, reminder_dict: dict):
        if self.settings.get("enable_dynamic_island", True):
            if self.overlay.is_open:
                self.overlay.sink()
            try:
                import odd_sound
                odd_sound.play_reminder(self.settings)
            except Exception:
                pass
            self.hud.show_hud("reminder", reminder_dict, duration_ms=0, persistent=True)
            self.raise_()
        else:
            if hasattr(self, 'bezel_hud'):
                title = reminder_dict.get("title", "Battery Alert")
                note = reminder_dict.get("note", "")
                self.bezel_hud.show_notification_hud(title, note, duration_ms=5000)

    def _on_battery_reminder_auto_resolved(self, event_dict: dict):
        title = event_dict.get("title", "Battery Reminder")
        action = event_dict.get("action", "")
        if action == "plugged_in":
            self.bezel_hud.show_notification_hud("Auto-Completed", f'Completed "{title}" (Charger detected)', duration_ms=2200)
        elif action == "unplugged":
            self.bezel_hud.show_notification_hud("Auto-Completed", f'Completed "{title}" (Charger disconnected)', duration_ms=2200)

    def _on_system_resource_alert(self, alert_dict: dict):
        if not self.overlay.is_open and self.settings.get("system_needs_intelligence", True):
            title = alert_dict.get("title", "Resource Alert")
            note = alert_dict.get("note", "")
            self.bezel_hud.show_notification_hud(title, note, duration_ms=4000)

    def _on_island_clip_action(self, action: str, preview: str, chars: int):
        act_lower = str(action or "").lower().strip()
        if "paste" in act_lower:
            return
        if act_lower not in ("copied", "copy", "copied_file", "copy_files"):
            return
        now = time.time()
        if now - getattr(self, "_last_clip_alert_t", 0.0) < 2.0:
            return
        self._last_clip_alert_t = now
        self.show_infomatic_alert("copied", "Copied", duration_sec=2.2)

    def _on_internet_changed(self, is_connected: bool):
        if not is_connected:
            self.show_infomatic_alert("no_internet", "Internet Disconnected", duration_sec=3.5)
        else:
            self.show_infomatic_alert("internet_connected", "Internet Connected", duration_sec=2.5)

    def _on_bluetooth_changed(self, event_type: str, device_name: str):
        d_clean = str(device_name or "").strip()
        if not d_clean or d_clean.lower() in ("bluetooth", "device", "unknown device", "unknown", "none", "null"):
            return

        now = time.time()
        if not hasattr(self, "_bt_alert_cooldowns"):
            self._bt_alert_cooldowns: Dict[str, Tuple[str, float]] = {}

        last_ev, last_t = self._bt_alert_cooldowns.get(d_clean, (None, 0.0))
        # Prevent spamming alerts within 20 seconds for the same device
        if (now - last_t) < 20.0:
            return
        self._bt_alert_cooldowns[d_clean] = (event_type, now)

        if event_type == "connected":
            title = f"Connected: {d_clean}"
            self.show_infomatic_alert("bluetooth_connected", title, duration_sec=2.6)
        elif event_type == "disconnected":
            title = f"Disconnected: {d_clean}"
            self.show_infomatic_alert("bluetooth_disconnected", title, duration_sec=2.6)

        try:
            odd_com.ComWorker.get_instance().request_hardware_sync(force=True)
        except Exception:
            pass

    def show_infomatic_alert(self, alert_type: str, title: str, subtitle: str = "", duration_sec: float = 2.4):
        """Displays a rich monochrome animated alert in the resting info-matic bar with smooth fade-in and fade-out."""
        now = time.perf_counter()
        # If identical alert is currently active, refresh duration without queueing duplicates
        if self._infomatic_alert and self._infomatic_alert.get("type") == alert_type:
            elapsed = now - self._infomatic_alert.get("start_time", now)
            if elapsed > 1.2:
                self._infomatic_alert["start_time"] = now - 0.5
            self._infomatic_alert["duration"] = max(1.5, float(duration_sec))
            return

        if not hasattr(self, "_alert_type_cooldowns"):
            self._alert_type_cooldowns = {}
        last_t = self._alert_type_cooldowns.get(alert_type, 0.0)
        if (now - last_t) < 1.8:
            return
        self._alert_type_cooldowns[alert_type] = now

        # Do not queue duplicate alerts
        if any(item.get("type") == alert_type for item in self._infomatic_queue):
            return

        alert_item = {
            "type": alert_type,
            "title": title,
            "subtitle": subtitle,
            "duration": max(1.5, float(duration_sec)),
            "start_time": now,
        }

        if self._infomatic_alert is None or self._infomatic_opacity < 0.15:
            self._infomatic_alert = alert_item
            self._infomatic_progress = 0.0
            self._infomatic_opacity = 0.0
            req_w, req_h = self._resting_window_bounds()
            if self.width() < req_w or self.height() < req_h:
                self.reposition()
            if not getattr(self, '_mask_cleared', False):
                self.clearMask()
                self._mask_cleared = True
            if not self._infomatic_anim_timer.isActive():
                self._infomatic_anim_timer.start(16)
        else:
            if len(self._infomatic_queue) < 2:
                self._infomatic_queue.append(alert_item)

    def _on_infomatic_anim_tick(self):
        if not self._infomatic_alert:
            self._infomatic_progress = 0.0
            self._infomatic_opacity = 0.0
            self._infomatic_anim_timer.stop()
            self.reposition()
            self.update()
            return

        now = time.perf_counter()
        start = self._infomatic_alert.get("start_time", now)
        dur = self._infomatic_alert.get("duration", 2.4)
        elapsed = now - start

        fade_in_t = 0.26
        fade_out_t = 0.28

        if elapsed < fade_in_t:
            t = max(0.0, min(1.0, elapsed / fade_in_t))
            self._infomatic_progress = t * t * (3.0 - 2.0 * t)
            self._infomatic_opacity = self._infomatic_progress
        elif elapsed < dur - fade_out_t:
            self._infomatic_progress = 1.0
            self._infomatic_opacity = 1.0
        elif elapsed < dur:
            t = max(0.0, min(1.0, (dur - elapsed) / fade_out_t))
            self._infomatic_progress = t * t * (3.0 - 2.0 * t)
            self._infomatic_opacity = self._infomatic_progress
        else:
            if self._infomatic_queue:
                next_alert = self._infomatic_queue.pop(0)
                next_alert["start_time"] = time.perf_counter()
                self._infomatic_alert = next_alert
                self._infomatic_progress = 1.0
                self._infomatic_opacity = 1.0
            else:
                self._infomatic_alert = None
                self._infomatic_progress = 0.0
                self._infomatic_opacity = 0.0
                self._infomatic_anim_timer.stop()
                self.reposition()
                self.update()
                return

        self.update()

    def _on_island_rook_action(self, action_name: str, key_binding: str):
        if not self.overlay.is_open and self.settings.get("enable_rook_hud", True):
            self.bezel_hud.show_rook_hud(action_name, key_binding, duration_ms=1800)

    def _on_island_timer(self, label: str, sec_val: int, is_stopwatch: bool = False):
        if not self.overlay.is_open and self.settings.get("island_show_timer_ticker", True):
            self.hud.show_hud("timer", {"label": label, "sec": sec_val, "is_stopwatch": is_stopwatch}, duration_ms=1000)

    def _on_island_media(self, state_dict: dict):
        pass

    def morph_island(self, expanded: bool, hud_type: str = None):
        """Morphs geometry smoothly between resting notch and active Dynamic Island / system-status capsule"""
        active_htype = hud_type or getattr(self.hud, "current_hud_type", None)
        was_expanded = bool(self.is_island_expanded and not getattr(self, "is_island_collapsing", False))

        if expanded:
            self.is_island_expanded = True
            self.is_island_collapsing = False
        else:
            self.is_island_expanded = False
            self.is_island_collapsing = True

        # Floating top-center system-status capsule (Caps Lock, Num Lock, Mute, Battery) -> route to bezel_hud
        if active_htype in odd_island._SYSTEM_STATUS_TYPES:
            if expanded:
                data = getattr(self.hud, 'hud_data', {}) or {}
                if active_htype == "mute":
                    self.bezel_hud.show_mute_hud(bool(data.get("is_muted", False)))
                elif active_htype == "battery":
                    self.bezel_hud.show_battery_hud(data)
                elif active_htype in ("lock_key", "caps_lock", "num_lock", "scroll_lock"):
                    k = data.get("key_name", active_htype)
                    is_on = bool(data.get("is_on", False))
                    if k == "num_lock":
                        self.bezel_hud.show_num_lock_hud(is_on)
                    elif k == "scroll_lock":
                        self.bezel_hud.show_scroll_lock_hud(is_on)
                    else:
                        self.bezel_hud.show_caps_lock_hud(is_on)
            else:
                self.bezel_hud.start_out_animation()
            return

        self._status_pill_active = False
        screen = QApplication.primaryScreen().geometry()
        edge = self.settings.get("edge", "top")
        base_w = max(40, int(self.settings.get("edge_bar_width", 75)))
        base_h = max(2, int(self.settings.get("edge_bar_thickness", 4)))

        if expanded:
            target_w, target_h = self.hud.get_dynamic_hud_size(hud_type)
            self._last_expanded_dim = float(target_h if edge in ("top", "bottom") else target_w)
            if hud_type == "reminder" and edge == "top":
                # Wellness reminders enter from the top edge, then reveal their
                # wider content as the capsule settles just below the bezel.
                duration = 175
                curve = QEasingCurve(QEasingCurve.Type.OutCubic)
            else:
                duration = 130
                curve = QEasingCurve(QEasingCurve.Type.OutQuart)
        else:
            target_w, target_h = self._resting_window_bounds()
            duration = 95
            curve = QEasingCurve(QEasingCurve.Type.OutCubic)

        if edge == "top":
            top_inset = 10 if expanded and hud_type == "reminder" else 0
            target_rect = QRect(screen.x() + screen.width() // 2 - target_w // 2, screen.y() + top_inset, target_w, target_h)
        elif edge == "bottom":
            target_rect = QRect(screen.x() + screen.width() // 2 - target_w // 2, screen.y() + screen.height() - target_h, target_w, target_h)
        elif edge == "left":
            target_rect = QRect(screen.x(), screen.y() + screen.height() // 2 - target_w // 2, target_h, target_w)
        else: # right
            target_rect = QRect(screen.x() + screen.width() - target_h, screen.y() + screen.height() // 2 - target_w // 2, target_h, target_w)

        self.morph_anim.stop()
        self.morph_anim.setDuration(duration)
        self.morph_anim.setEasingCurve(curve)
        self.morph_anim.setStartValue(self.geometry())
        self.morph_anim.setEndValue(target_rect)
        self.morph_anim.start()
        self._update_input_mask()
        self.update()

    def reposition(self):
        htype = getattr(self.hud, 'current_hud_type', None)
        if self.is_island_expanded and htype in odd_island._SYSTEM_STATUS_TYPES:
            screen = self._active_screen_geometry()
            trigger_w, depth = self.hud.get_dynamic_hud_size(htype)
            target_y = screen.y()
            self._status_target_y = float(target_y)
            self.setGeometry(screen.x() + (screen.width() - trigger_w) // 2, target_y, trigger_w, depth)
            self._update_input_mask()
            self.update()
            return

        screen = QApplication.primaryScreen().geometry()
        edge = self.settings.get("edge", "top")
        base_w = max(40, int(self.settings.get("edge_bar_width", 75)))
        base_h = max(2, int(self.settings.get("edge_bar_thickness", 4)))

        if self.is_island_expanded:
            trigger_w, depth = self.hud.get_dynamic_hud_size(htype)
        else:
            trigger_w, depth = self._resting_window_bounds()

        side_view = str(self.settings.get("side_view", "off")).lower()
        if side_view in ("left", "right"):
            edge = side_view
            notch_y = screen.y() + 85
            if side_view == "left":
                self.setGeometry(screen.x(), notch_y, depth, trigger_w)
            else:
                self.setGeometry(screen.x() + screen.width() - depth, notch_y, depth, trigger_w)
            self._update_input_mask()
            self.update()
            return

        if edge == "top":
            self.setGeometry(screen.x() + screen.width() // 2 - trigger_w // 2, screen.y(), trigger_w, depth)
        elif edge == "bottom":
            self.setGeometry(screen.x() + screen.width() // 2 - trigger_w // 2, screen.y() + screen.height() - depth, trigger_w, depth)
        elif edge == "left":
            self.setGeometry(screen.x(), screen.y() + screen.height() // 2 - trigger_w // 2, depth, trigger_w)
        else:  # right
            self.setGeometry(screen.x() + screen.width() - depth, screen.y() + screen.height() // 2 - trigger_w // 2, depth, trigger_w)
        self._update_input_mask()
        self.update()

    def get_hover_progress(self) -> float:
        return self._hover_progress

    def set_hover_progress(self, val: float):
        self._hover_progress = float(val)
        self._update_input_mask()
        self.update()

    hover_progress = Property(float, get_hover_progress, set_hover_progress)

    def _set_hover_state(self, hovered: bool):
        if self.is_hovered == hovered:
            return
        self.is_hovered = hovered
        self.anim_hover.stop()
        self.anim_hover.setStartValue(self._hover_progress)
        self.anim_hover.setEndValue(1.0 if hovered else 0.0)
        self.anim_hover.start()

    def _draw_infomatic_alert(self, painter: QPainter, pill_rect: QRect, p: float):
        if not self._infomatic_alert or self._infomatic_opacity <= 0.01:
            return

        theme = str(self.settings.get("theme", "dark")).lower()
        is_light = (theme == "light")
        alert = self._infomatic_alert
        alert_type = alert.get("type", "status")
        raw_title = alert.get("title", "")
        op = max(0.0, min(1.0, self._infomatic_opacity)) * max(0.0, 1.0 - p / 0.20)
        if op <= 0.01:
            return

        painter.save()
        painter.setOpacity(op)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 1. Multi-Step Ambient Drop Shadow beneath the capsule
        r_capsule = pill_rect.height() / 2.0
        for spread, y_off, alpha in ((5.0, 2.5, 5), (3.0, 1.6, 10), (1.2, 0.8, 18)):
            s_rect = QRectF(pill_rect).adjusted(-spread, -spread + y_off, spread, spread + y_off)
            s_rad = s_rect.height() / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, int(alpha * op)))
            painter.drawRoundedRect(s_rect, s_rad, s_rad)

        # 2. Liquid Acrylic / Obsidian Glass Surface
        bg_col = QColor(13, 15, 20, int(246 * op)) if not is_light else QColor(248, 249, 251, int(246 * op))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg_col))
        painter.drawRoundedRect(QRectF(pill_rect), r_capsule, r_capsule)

        # Specular light reflection on top half
        spec_grad = QLinearGradient(0, pill_rect.top(), 0, pill_rect.bottom())
        if not is_light:
            spec_grad.setColorAt(0.0, QColor(255, 255, 255, int(28 * op)))
            spec_grad.setColorAt(0.40, QColor(255, 255, 255, int(8 * op)))
            spec_grad.setColorAt(1.0, QColor(255, 255, 255, int(2 * op)))
        else:
            spec_grad.setColorAt(0.0, QColor(255, 255, 255, int(160 * op)))
            spec_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(spec_grad))
        painter.drawRoundedRect(QRectF(pill_rect), r_capsule, r_capsule)

        # Micro-thin glass perimeter rim
        rim_col = QColor(255, 255, 255, int(38 * op)) if not is_light else QColor(0, 0, 0, int(24 * op))
        painter.setPen(QPen(rim_col, 0.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(pill_rect).adjusted(0.4, 0.4, -0.4, -0.4), r_capsule, r_capsule)

        # Monochrome palette
        fg_col = QColor(255, 255, 255, 250) if not is_light else QColor(18, 18, 20, 245)
        prefix_col = QColor(165, 170, 180, 230) if not is_light else QColor(105, 110, 120, 230)
        dim_col = QColor(130, 135, 145, 180) if not is_light else QColor(140, 145, 155, 180)

        # 3. Left circular icon badge
        badge_d = 20.0
        bx = float(pill_rect.left()) + 5.0
        by = float(pill_rect.top()) + (pill_rect.height() - badge_d) / 2.0
        badge_rect = QRectF(bx, by, badge_d, badge_d)

        plate_bg = QColor(255, 255, 255, 16) if not is_light else QColor(0, 0, 0, 12)
        plate_border = QColor(255, 255, 255, 28) if not is_light else QColor(0, 0, 0, 20)
        painter.setBrush(QBrush(plate_bg))
        painter.setPen(QPen(plate_border, 0.7))
        painter.drawEllipse(badge_rect)

        cx = badge_rect.center().x()
        cy = badge_rect.center().y()

        if alert_type == "copied":
            painter.setPen(QPen(fg_col, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            tick_path = QPainterPath()
            tick_path.moveTo(cx - 3.8, cy + 0.2)
            tick_path.lineTo(cx - 1.0, cy + 3.2)
            tick_path.lineTo(cx + 4.2, cy - 3.2)
            painter.drawPath(tick_path)
        elif alert_type in ("bluetooth_connected", "bluetooth_disconnected"):
            painter.setPen(QPen(fg_col, 1.15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            bt_path = QPainterPath()
            bt_path.moveTo(cx, cy - 5.5)
            bt_path.lineTo(cx, cy + 5.5)
            bt_path.lineTo(cx + 3.5, cy + 2.4)
            bt_path.lineTo(cx - 2.8, cy - 2.4)
            bt_path.moveTo(cx - 2.8, cy + 2.4)
            bt_path.lineTo(cx + 3.5, cy - 2.4)
            bt_path.lineTo(cx, cy - 5.5)
            painter.drawPath(bt_path)
        elif alert_type == "internet_connected":
            painter.setPen(QPen(fg_col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(cx - 5.5, cy - 5.0, 11.0, 9.0), 35 * 16, 110 * 16)
            painter.drawArc(QRectF(cx - 3.2, cy - 2.8, 6.4, 5.5), 35 * 16, 110 * 16)
            painter.setBrush(QBrush(fg_col))
            painter.drawEllipse(QRectF(cx - 1.2, cy + 1.8, 2.4, 2.4))
        elif alert_type == "no_internet":
            painter.setPen(QPen(fg_col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(cx - 5.5, cy - 5.0, 11.0, 9.0), 35 * 16, 110 * 16)
            painter.setBrush(QBrush(fg_col))
            painter.drawEllipse(QRectF(cx - 1.2, cy + 1.8, 2.4, 2.4))
            painter.setPen(QPen(QColor(239, 68, 68), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(cx - 5.0, cy + 4.0), QPointF(cx + 5.0, cy - 4.0))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fg_col))
            painter.drawEllipse(QRectF(cx - 3.5, cy - 3.5, 7.0, 7.0))

        # 4. Typography Layout
        text_x = bx + badge_d + 8.0
        avail_w = float(pill_rect.right()) - text_x - 10.0

        font_prefix = QFont("Segoe UI Variable Text", 8.0, QFont.Weight.Medium)
        font_title = QFont("Segoe UI Variable Display", 8.4, QFont.Weight.Bold)
        fm_prefix = QFontMetrics(font_prefix)
        fm_title = QFontMetrics(font_title)

        has_colon = (":" in raw_title)
        if has_colon:
            prefix_str, _, name_str = raw_title.partition(":")
            prefix_str = prefix_str.strip()
            name_str = name_str.strip()
            sep_str = " · "
            w_pref = fm_prefix.horizontalAdvance(prefix_str)
            w_sep = fm_prefix.horizontalAdvance(sep_str)
            w_name = fm_title.horizontalAdvance(name_str)
            total_text_w = w_pref + w_sep + w_name
        else:
            prefix_str = ""
            name_str = raw_title
            sep_str = ""
            w_pref = 0
            w_sep = 0
            w_name = fm_title.horizontalAdvance(name_str)
            total_text_w = w_name

        text_rect = QRectF(text_x, pill_rect.top(), max(10.0, avail_w), pill_rect.height())

        if total_text_w <= avail_w:
            cur_draw_x = text_x
            if has_colon and prefix_str:
                painter.setFont(font_prefix)
                painter.setPen(prefix_col)
                painter.drawText(QRectF(cur_draw_x, pill_rect.top(), w_pref + 2, pill_rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, prefix_str)
                cur_draw_x += w_pref
                painter.setPen(dim_col)
                painter.drawText(QRectF(cur_draw_x, pill_rect.top(), w_sep + 2, pill_rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sep_str)
                cur_draw_x += w_sep

            painter.setFont(font_title)
            painter.setPen(fg_col)
            painter.drawText(QRectF(cur_draw_x, pill_rect.top(), w_name + 4, pill_rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name_str)
        else:
            painter.save()
            painter.setClipRect(text_rect)

            full_display_str = f"{prefix_str} · {name_str}" if has_colon else name_str
            painter.setFont(font_title)
            fm_full = QFontMetrics(font_title)
            unit_title_w = fm_full.horizontalAdvance(full_display_str)

            now = time.perf_counter()
            start_t = alert.get("start_time", now)
            elapsed = max(0.0, now - start_t)
            scroll_elapsed = max(0.0, elapsed - 1.0)
            speed = 30.0
            sep_marquee = "      •      "
            sep_m_w = fm_full.horizontalAdvance(sep_marquee)
            full_cycle_w = unit_title_w + sep_m_w
            offset = (scroll_elapsed * speed) % full_cycle_w

            cur_x = text_x - offset
            while cur_x < text_rect.right() + full_cycle_w:
                painter.setPen(fg_col)
                painter.drawText(QRectF(cur_x, pill_rect.top(), unit_title_w, pill_rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, full_display_str)
                painter.setPen(dim_col)
                painter.drawText(QRectF(cur_x + unit_title_w, pill_rect.top(), sep_m_w, pill_rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sep_marquee)
                cur_x += full_cycle_w

            painter.restore()

            if offset > 2.0:
                lf_w = 14.0
                left_fade = QLinearGradient(text_x, 0, text_x + lf_w, 0)
                left_fade.setColorAt(0.0, bg_col)
                left_fade.setColorAt(1.0, QColor(bg_col.red(), bg_col.green(), bg_col.blue(), 0))
                painter.fillRect(QRectF(text_x, pill_rect.top(), lf_w, pill_rect.height()), QBrush(left_fade))

            rf_w = 16.0
            right_fade = QLinearGradient(text_rect.right() - rf_w, 0, text_rect.right(), 0)
            right_fade.setColorAt(0.0, QColor(bg_col.red(), bg_col.green(), bg_col.blue(), 0))
            right_fade.setColorAt(1.0, bg_col)
            painter.fillRect(QRectF(text_rect.right() - rf_w, pill_rect.top(), rf_w, pill_rect.height()), QBrush(right_fade))

        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Suppress resting notch / edge bar when ODD search, notifications, or overlays are expanded
        if getattr(self, "_is_edge_bar_hidden", False):
            return

        if self.bezel_hud and self.bezel_hud.isVisible():
            return

        is_collapsing = getattr(self, "is_island_collapsing", False)
        if self.overlay and (self.overlay.is_open or self.overlay.isVisible() or getattr(self.overlay, '_is_morphing', False)) and not (self.hud.current_hud_type and (self.is_island_expanded or is_collapsing)):
            return

        p = self._hover_progress
        act_state = self.island_monitor.activity_mgr.get_merged_state()
        hide_edge = bool(self.settings.get("hide_edge_bar", False)) or not bool(self.settings.get("ui_show_edge_indicator", True))
        if hide_edge and not act_state.get("has_active", False) and not (self.hud.current_hud_type and (self.is_island_expanded or is_collapsing)):
            return
        edge = self.settings.get("edge", "top")
        theme = str(self.settings.get("theme", "dark")).lower()
        color_mode = self.settings.get("edge_bar_color_mode", "theme")
        custom_hex = self.settings.get("edge_bar_color", "#00E5FF")

        if color_mode in ("preset", "custom") and custom_hex:
            base_col = QColor(custom_hex)
            if not base_col.isValid():
                base_col = QColor("#00E5FF")
            alpha = int(180 + 75 * p)
            color = QColor(base_col.red(), base_col.green(), base_col.blue(), alpha)
        else:
            if theme == "light":
                alpha = int(160 + 95 * p)
                color = QColor(25, 25, 30, alpha)
            elif theme == "oled":
                color = QColor(0, 0, 0, 255)
            else: # dark
                color = QColor(10, 11, 14, int(235 + 20 * p))

        # 2. DYNAMIC ISLAND EXPANDED / COLLAPSING HUD RENDERING
        is_collapsing = getattr(self, "is_island_collapsing", False)
        if self.hud.current_hud_type and (self.is_island_expanded or is_collapsing):
            if self.hud.current_hud_type in odd_island._SYSTEM_STATUS_TYPES:
                target_y = float(getattr(self, "_status_target_y", self.y()))
                dy = max(0.0, target_y - float(self.y()))
                if is_collapsing:
                    fade_opacity = max(0.0, min(1.0, 1.0 - (dy / 8.0)))
                else:
                    fade_opacity = max(0.08, min(1.0, 1.0 - (dy / 10.0) * 0.92))

                pill_rect = odd_island.paint_system_status_pill_surface(
                    painter,
                    self.rect(),
                    opacity=fade_opacity,
                    theme=theme,
                )
                painter.save()
                painter.setOpacity(fade_opacity)
                painter.setClipRect(pill_rect)
                self.hud.paint_island_content(painter, pill_rect.toRect())
                painter.restore()
                return

            island_rect = self.rect().adjusted(1, 1, -1, -1)
            r_corner = max(4.0, min(float(island_rect.height()) / 2.0, 22.0))

            fade_opacity = 1.0
            content_op = 1.0
            act_state = self.island_monitor.activity_mgr.get_merged_state()
            if is_collapsing:
                expanded_dim = float(getattr(self, "_last_expanded_dim", 34.0))
                resting_dim = 14.0
                curr_dim = float(island_rect.height() if edge in ("top", "bottom") else island_rect.width())
                if act_state.get("has_active", False):
                    fade_opacity = 1.0
                    content_op = max(0.0, min(1.0, (curr_dim - 24.0) / max(1.0, expanded_dim - 24.0)))
                else:
                    fade_opacity = max(0.0, min(1.0, (curr_dim - resting_dim) / max(1.0, expanded_dim - resting_dim)))
                    content_op = fade_opacity

            odd_blur.ODDOverlaySurface.paint_glass_surface(
                painter,
                island_rect,
                r_corner,
                theme=theme,
                opacity=fade_opacity,
                hover_val=p,
                hwnd=int(self.winId()),
                hover_pos=getattr(self, '_mouse_local_pos', None),
                hover_color=color,
            )

            if content_op > 0.05:
                painter.save()
                painter.setOpacity(content_op)
                painter.setClipRect(island_rect)
                content_progress = max(0.0, min(1.0, self.hud.content_reveal.value))
                painter.save()
                painter.setOpacity(content_progress * content_op)
                painter.translate(0, -4.0 * (1.0 - content_progress))
                self.hud.paint_island_content(painter, island_rect)
                painter.restore()
                painter.restore()
                return
            elif act_state.get("has_active", False):
                pass
            else:
                return

        act_state = self.island_monitor.activity_mgr.get_merged_state()

        # 3. INVISIBLE EDGE BAR CHECK: Skip rendering resting notch if user chose to hide it
        if hide_edge and not act_state.get("has_active", False):
            return

        # 4. RESTING NOTCH RENDERING (Animated with smooth liquid expansion & frosted rim)
        pill_rect = self._resting_pill_rect(p)
        pill_w = pill_rect.width()
        pill_h = pill_rect.height()
        r_corner = max(2, int(min(pill_w, pill_h) / 2.0))

        n_style = self.settings.get("edge_notch_style", "bar")
        n_text = str(self.settings.get("edge_notch_text", "ODD")).strip() or "ODD"

        # Resting notch rendering
        if not act_state["has_active"]:
            if self.should_show_music_edge_bar():
                # FOURTH IMAGE: Premium music edge bar pill
                bg_col = QColor(10, 12, 16, int(235 + 20 * p)) if theme != "light" else QColor(245, 246, 248, int(235 + 20 * p))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(bg_col))
                painter.drawRoundedRect(pill_rect, r_corner, r_corner)

                # Frosted / subtle rim
                rim_col = QColor(255, 255, 255, int(28 + 24 * p)) if theme != "light" else QColor(0, 0, 0, 24)
                painter.setPen(QPen(rim_col, 0.8))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(pill_rect.adjusted(0, 0, -1, -1), r_corner, r_corner)

                # Subtle mouse hover reflection around mouse position
                if getattr(self, '_mouse_local_pos', None) and p > 0.05:
                    m_pt = self._mouse_local_pos
                    refl_grad = QRadialGradient(QPointF(m_pt), 48.0)
                    refl_col = QColor(255, 255, 255) if theme != "light" else QColor(30, 30, 35)
                    refl_grad.setColorAt(0.0, QColor(refl_col.red(), refl_col.green(), refl_col.blue(), int(22 * p)))
                    refl_grad.setColorAt(0.6, QColor(refl_col.red(), refl_col.green(), refl_col.blue(), int(6 * p)))
                    refl_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
                    painter.save()
                    pill_clip = QPainterPath()
                    pill_clip.addRoundedRect(QRectF(pill_rect), r_corner, r_corner)
                    painter.setClipPath(pill_clip)
                    painter.fillRect(pill_rect, QBrush(refl_grad))
                    painter.restore()

                # Left: Circular monochromatic badge with 3 curved sound arcs
                m_content_op = max(0.0, 1.0 - p / 0.20)
                if m_content_op > 0.01:
                    painter.save()
                    painter.setOpacity(m_content_op)
                    badge_r = 7.5
                    badge_cx = pill_rect.left() + 15
                    badge_cy = pill_rect.center().y()
                    mono_badge_col = QColor(245, 247, 250, int(225 + 30 * p)) if theme != "light" else QColor(25, 25, 28, 235)

                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(mono_badge_col))
                    painter.drawEllipse(QPointF(badge_cx, badge_cy), badge_r, badge_r)

                    # 3 sound wave arcs inside the badge
                    arc_col = QColor(12, 14, 18, 240) if theme != "light" else QColor(245, 245, 248, 240)
                    arc_pen = QPen(arc_col, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                    painter.setPen(arc_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawArc(QRectF(badge_cx - 5.0, badge_cy - 4.2, 10.0, 7.5), 35 * 16, 110 * 16)
                    painter.drawArc(QRectF(badge_cx - 4.0, badge_cy - 2.8, 8.0, 6.2), 35 * 16, 110 * 16)
                    painter.drawArc(QRectF(badge_cx - 3.0, badge_cy - 1.4, 6.0, 4.8), 35 * 16, 110 * 16)

                    # Middle: Track info / title
                    m_state = self.overlay.media_state
                    track_title = str(m_state.get("title") or "Music").strip()
                    artist_name = str(m_state.get("artist") or "").strip()
                    display_title = f"{track_title} - {artist_name}" if (artist_name and artist_name != track_title) else track_title

                    # Right: 4 animated equalizer bars
                    eq_right = pill_rect.right() - 14
                    eq_w = 2.4
                    eq_gap = 2.4
                    total_eq_w = 4 * eq_w + 3 * eq_gap
                    eq_start_x = eq_right - total_eq_w
                    eq_cy = pill_rect.center().y()

                    painter.setPen(Qt.PenStyle.NoPen)
                    eq_bar_col = QColor(245, 247, 250, int(210 + 40 * p)) if theme != "light" else QColor(30, 30, 35, 220)
                    painter.setBrush(QBrush(eq_bar_col))
                    for bi in range(4):
                        b_phase = time.time() * 6.5 + bi * 1.4
                        h_pct = 0.22 + 0.78 * (math.sin(b_phase) ** 2)
                        bar_h = max(3.0, 13.0 * h_pct)
                        bx = eq_start_x + bi * (eq_w + eq_gap)
                        by = eq_cy - bar_h / 2.0
                        painter.drawRoundedRect(QRectF(bx, by, eq_w, bar_h), 1.2, 1.2)

                    # Draw track title in middle
                    text_left = badge_cx + badge_r + 8
                    text_right = eq_start_x - 6
                    text_w = max(10, text_right - text_left)
                    t_font = QFont("Segoe UI Variable Display", 7.8, QFont.Weight.DemiBold)
                    painter.setFont(t_font)
                    fm = QFontMetrics(t_font)
                    elided_t = fm.elidedText(display_title, Qt.TextElideMode.ElideRight, text_w)
                    t_col = QColor(245, 247, 250, int(220 + 35 * p)) if theme != "light" else QColor(25, 25, 28, 230)
                    painter.setPen(t_col)
                    painter.drawText(QRectF(text_left, pill_rect.top(), text_w, pill_rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_t)
                    painter.restore()

            elif n_style in ("worded", "text_static", "text_scroll"):
                # WORDED EDGE BAR
                if getattr(self, "_infomatic_alert", None) and getattr(self, "_infomatic_opacity", 0.0) > 0.01:
                    self._draw_infomatic_alert(painter, pill_rect, p)
                else:
                    if p > 0.04:
                        odd_blur.ODDOverlaySurface.paint_glass_surface(
                            painter,
                            pill_rect,
                            r_corner,
                            theme=theme,
                            opacity=min(1.0, 0.45 + 0.55 * p),
                            hover_val=p,
                            hwnd=int(self.winId()),
                            hover_pos=getattr(self, '_mouse_local_pos', None),
                            hover_color=color,
                        )
                    else:
                        bg_col = QColor(10, 12, 16, int(235 + 20 * p)) if theme != "light" else QColor(245, 246, 248, int(235 + 20 * p))
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(bg_col))
                        painter.drawRoundedRect(pill_rect, r_corner, r_corner)

                    rim_col = QColor(255, 255, 255, int(28 + 36 * p)) if theme != "light" else QColor(0, 0, 0, 24)
                    painter.setPen(QPen(rim_col, 0.8))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(pill_rect.adjusted(0, 0, -1, -1), r_corner, r_corner)

                    worded_mode = self.settings.get("edge_worded_mode", "static")
                    text_op = max(0.0, 1.0 - p / 0.20)
                    fg_col = QColor(255, 255, 255, int(210 + 45 * p)) if theme != "light" else QColor(30, 30, 30, 220)

                    if text_op > 0.01:
                        if worded_mode == "scroll":
                            painter.save()
                            painter.setOpacity(text_op)
                            painter.setClipRect(pill_rect.adjusted(6, 0, -6, 0))
                            painter.setFont(QFont("Segoe UI Variable Display", 7.6, QFont.Weight.Bold))
                            painter.setPen(fg_col)
                            metrics_sc = QFontMetrics(painter.font())
                            scroll_text = f"{n_text}   •   "
                            text_total_w = metrics_sc.horizontalAdvance(scroll_text)
                            if text_total_w > 0:
                                speed = 28.0 + 20.0 * p
                                offset = int((time.time() * speed) % text_total_w)
                                start_x = pill_rect.left() - offset
                                while start_x < pill_rect.right() + text_total_w:
                                    painter.drawText(QRect(start_x, pill_rect.top(), text_total_w, pill_rect.height()), Qt.AlignmentFlag.AlignVCenter, scroll_text)
                                    start_x += text_total_w
                            painter.restore()
                        else:
                            painter.save()
                            painter.setOpacity(text_op)
                            painter.setFont(QFont("Segoe UI Variable Display", 7.6, QFont.Weight.Bold))
                            painter.setPen(fg_col)
                            text_rect = QRectF(pill_rect.left(), pill_rect.top(), pill_rect.width(), pill_rect.height())
                            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, n_text)
                            painter.restore()

            else:
                # SIMPLE / PLAIN BAR
                if getattr(self, "_infomatic_alert", None) and getattr(self, "_infomatic_opacity", 0.0) > 0.01:
                    self._draw_infomatic_alert(painter, pill_rect, p)
                else:
                    if p > 0.04:
                        odd_blur.ODDOverlaySurface.paint_glass_surface(
                            painter,
                            pill_rect,
                            r_corner,
                            theme=theme,
                            opacity=min(1.0, 0.45 + 0.55 * p),
                            hover_val=p,
                            hwnd=int(self.winId()),
                            hover_pos=getattr(self, '_mouse_local_pos', None),
                            hover_color=color,
                        )
                    else:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(color))
                        painter.drawRoundedRect(pill_rect, r_corner, r_corner)

                    rim = QColor(255, 255, 255, int(36 + 32 * p)) if theme != "light" else QColor(0, 0, 0, 30)
                    painter.setPen(QPen(rim, 0.8))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(pill_rect.adjusted(0, 0, -1, -1), r_corner, r_corner)
        else:
            odd_blur.ODDOverlaySurface.paint_glass_surface(
                painter,
                pill_rect,
                r_corner,
                theme=theme,
                opacity=1.0,
                hover_val=p,
                hwnd=int(self.winId()),
                hover_pos=getattr(self, '_mouse_local_pos', None),
                hover_color=color,
            )

        # ---------------- DOWNLOAD MODE / LIVE ACTIVITY NOTCH PROGRESS RING ----------------
        if act_state["has_active"]:
            active_items = act_state.get("active_items", [])
            count = len(active_items)
            from odd_island import format_download_filename

            if count == 2:
                # DUAL DOWNLOAD MODE — Individual progress rings & percentages side-by-side
                i1, i2 = active_items[0], active_items[1]
                t1 = format_download_filename(getattr(i1, 'title', 'DL 1'), 12)
                p1 = float(getattr(i1, 'progress', 0.0))
                t2 = format_download_filename(getattr(i2, 'title', 'DL 2'), 12)
                p2 = float(getattr(i2, 'progress', 0.0))

                # Section 1 (Left): Ring 1 + File 1 + Pct 1
                r1 = 6.2
                cx1 = pill_rect.left() + 14
                cy1 = pill_rect.center().y()
                self.hud.draw_download_indicator(
                    painter, cx1, cy1, radius=r1, progress=p1,
                    stroke_width=1.7, color=color, is_active=True
                )

                painter.setFont(QFont("Segoe UI Variable Text", 7.5, QFont.Weight.DemiBold))
                fm = painter.fontMetrics()
                s1_text = f"{t1} {int(round(p1))}%"
                s1_x = cx1 + int(r1) + 6
                painter.setPen(QColor(255, 255, 255, 235) if theme != "light" else QColor(20, 20, 20, 235))
                painter.drawText(s1_x, cy1 + 3, s1_text)

                # Vertical Divider in middle
                div_x = s1_x + fm.horizontalAdvance(s1_text) + 8
                painter.setPen(QPen(QColor(255, 255, 255, 45) if theme != "light" else QColor(0, 0, 0, 45), 1.0))
                painter.drawLine(div_x, cy1 - 6, div_x, cy1 + 6)

                # Section 2 (Right): Ring 2 + File 2 + Pct 2
                cx2 = div_x + 8 + int(r1)
                self.hud.draw_download_indicator(
                    painter, cx2, cy1, radius=r1, progress=p2,
                    stroke_width=1.7, color=color, is_active=True
                )
                s2_text = f"{t2} {int(round(p2))}%"
                s2_x = cx2 + int(r1) + 6
                painter.setPen(QColor(255, 255, 255, 235) if theme != "light" else QColor(20, 20, 20, 235))
                painter.drawText(s2_x, cy1 + 3, s2_text)

            elif count <= 1:
                # SINGLE DOWNLOAD MODE — Snug, crisp indicator with percentage
                item = active_items[0] if active_items else None
                raw_n = getattr(item, 'title', act_state.get('primary_title', 'Download')) if item else act_state.get('primary_title', 'Download')
                t_str = format_download_filename(raw_n, 16)
                prog = float(getattr(item, 'progress', act_state.get('merged_progress', 0.0)) if item else act_state.get('merged_progress', 0.0))

                ring_r = 7.0
                ring_cx = pill_rect.left() + 16
                ring_cy = pill_rect.center().y()

                has_install = "install" in raw_n.lower() or (item and getattr(item, 'icon_type', '') == 'blue_sphere')
                if has_install:
                    self.hud.draw_blue_sphere(painter, ring_cx, ring_cy, ring_r)
                else:
                    self.hud.draw_download_indicator(
                        painter, ring_cx, ring_cy, radius=ring_r,
                        progress=prog, stroke_width=2.0, color=color, is_active=True
                    )

                text_x = ring_cx + int(ring_r) + 8
                disp_text = f"{t_str} — {int(round(prog))}%" if prog > 0 and not t_str.endswith("%") else t_str
                painter.setFont(QFont("Segoe UI Variable Text", 7.8, QFont.Weight.DemiBold))
                painter.setPen(QColor(255, 255, 255, 235) if theme != "light" else QColor(20, 20, 20, 235))
                painter.drawText(text_x, ring_cy + 3, disp_text)

            else:
                # MULTI-DOWNLOAD MODE (3+) — Indicator with count badge and overall progress
                merged_pct = act_state["merged_progress"]
                ring_r = 7.0
                ring_cx = pill_rect.left() + 16
                ring_cy = pill_rect.center().y()

                self.hud.draw_download_indicator(
                    painter, ring_cx, ring_cy, radius=ring_r,
                    progress=merged_pct, stroke_width=2.0, color=color, is_active=True
                )
                painter.setFont(QFont("Segoe UI Variable Text", 6, QFont.Weight.Bold))
                painter.setPen(QColor(255, 255, 255) if theme != "light" else QColor(0, 0, 0))
                painter.drawText(QRect(int(ring_cx - ring_r), int(ring_cy - ring_r), int(ring_r * 2), int(ring_r * 2)), Qt.AlignmentFlag.AlignCenter, str(count))

                text_x = ring_cx + int(ring_r) + 8
                disp_text = f"{count} Downloads — {int(round(merged_pct))}%"
                painter.setFont(QFont("Segoe UI Variable Text", 7.8, QFont.Weight.DemiBold))
                painter.setPen(QColor(255, 255, 255, 235) if theme != "light" else QColor(20, 20, 20, 235))
                painter.drawText(text_x, ring_cy + 3, disp_text)

        # Micro Animated Equalizer when music is playing and NOT in music edge bar mode
        if self.has_active_media_playing() and p < 0.3 and not act_state["has_active"] and not self.should_show_music_edge_bar():
            eq_x = pill_rect.right() + 6
            eq_y = pill_rect.center().y()
            for i in range(3):
                b_h = max(2, int(3 + 3 * (math.sin(self.hud.eq_phase + i * 1.5) ** 2)))
                painter.setBrush(QBrush(color))
                painter.drawRoundedRect(eq_x + i * 4, eq_y - b_h // 2, 2, b_h, 1, 1)

    def _is_point_on_bar(self, global_pos: QPoint) -> bool:
        """Returns True when global cursor position is directly over or bumping the resting island notch"""
        if self.is_island_expanded:
            return self.geometry().contains(global_pos)

        pill = self._resting_pill_rect()
        local_pos = self.mapFromGlobal(global_pos)
        edge = self.settings.get("edge", "top")

        if edge == "top":
            notch_left = pill.x() - 14
            notch_right = pill.x() + pill.width() + 14
            notch_bottom = pill.y() + pill.height() + 8
            if notch_left <= local_pos.x() <= notch_right and 0 <= local_pos.y() <= notch_bottom:
                return True
            return False
        elif edge == "bottom":
            notch_left = pill.x() - 14
            notch_right = pill.x() + pill.width() + 14
            notch_top = pill.y() - 8
            if notch_left <= local_pos.x() <= notch_right and local_pos.y() >= notch_top:
                return True
            return False
        else:
            return pill.adjusted(-6, -6, 6, 6).contains(local_pos)

    def _is_active_window_maximized(self) -> bool:
        """
        Detects if the foreground window (e.g. Chrome, browser, IDE) is currently maximized or fullscreen.
        Allows ODD to dynamically introduce a slight delay so closing tabs or hitting top window buttons
        does not accidentally surface ODD.
        """
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False

            # Ignore ODD's own windows
            my_hwnd = int(self.winId()) if self else 0
            overlay_hwnd = int(self.overlay.winId()) if (self.overlay and self.overlay.isVisible()) else 0
            if hwnd in (my_hwnd, overlay_hwnd):
                return False

            # 1. Fullscreen or Standard Win32 IsZoomed
            if is_window_fullscreen(hwnd) or user32.IsZoomed(hwnd):
                return True

            # 2. Borderless fullscreen or maximized window check
            rect = ctypes.wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                screen = QApplication.primaryScreen().geometry()
                if rect.top <= screen.top() + 4 and rect.bottom >= screen.bottom() - 20 and (rect.right - rect.left) >= screen.width() - 20:
                    return True
        except Exception:
            pass
        return False

    @safe_slot
    def _poll_edge_zone(self):
        """Ultra-reliable edge bar hover detection strictly confined to the physical bar"""
        if self.overlay.is_open or self.overlay.is_animating or self.is_island_expanded or getattr(self, "is_island_collapsing", False):
            self._hover_start_time = None
            return

        if is_mouse_dragging():
            self._hover_start_time = None
            return

        # Ignore hover triggering during initial startup cooldown (1.5s) to prevent auto-opening on app/system startup
        if time.time() - getattr(self, '_startup_time', 0) < 1.5:
            self._hover_start_time = None
            return

        # Animate worded scrolling/infomatic, active music edge bar, or hover micro-animations
        notch_style = self.settings.get("edge_notch_style", "simple")
        needs_anim = (
            (notch_style in ("worded", "text_scroll") and (self.settings.get("edge_worded_mode", "static") == "scroll" or self.settings.get("edge_bar_infomatic", False)))
            or self.should_show_music_edge_bar()
            or self._hover_progress > 0.02
        )
        if needs_anim:
            now_t = time.time()
            if now_t - getattr(self, '_last_notch_anim_time', 0.0) >= 0.033:
                self._last_notch_anim_time = now_t
                curr_pill = self._resting_pill_rect()
                if getattr(self, '_last_applied_mask_rect', None) != curr_pill:
                    self._last_applied_mask_rect = QRect(curr_pill)
                    self._update_input_mask()
                self.update()

        mode = self.settings.get("edge_trigger_mode", "hover")
        if mode == "hotkey_only":
            return

        pos = QCursor.pos()
        # A cursor already resting over the bar at launch is not a deliberate
        # trigger. Arm hover only after it has left the physical pill once.
        if not getattr(self, "_startup_hover_armed", False):
            if not self._is_point_on_bar(pos):
                self._startup_hover_armed = True
            else:
                self._hover_start_time = None
                self._set_hover_state(False)
                return

        if not getattr(self, '_has_mouse_moved', False):
            if pos != getattr(self, '_initial_mouse_pos', pos):
                self._has_mouse_moved = True
            else:
                return

        in_zone = self._is_point_on_bar(pos)

        if in_zone:
            self.raise_()
            self._set_hover_state(True)

            # Check if we should expand into Activity Drawer instead of search
            act_state = self.island_monitor.activity_mgr.get_merged_state()
            if act_state.get("has_active", False):
                if not self.is_island_expanded:
                    self.hud.show_hud("activity", act_state, duration_ms=0, persistent=True)
                return

            if self.settings.get("radial_menu_enabled", True):
                # When radial architecture is enabled, hovering at the top never triggers search
                return

            if mode == "click":
                return

            now = time.time()
            if self._hover_start_time is None:
                self._hover_start_time = now
            else:
                is_maximized = self._is_active_window_maximized()
                if is_maximized:
                    dwell_sec = 0.12 if mode == "deliberate" else 0.08
                else:
                    dwell_sec = 0.08 if mode == "deliberate" else 0.04

                if now - self._hover_start_time >= dwell_sec:
                    self._hover_start_time = None
                    self.overlay.surface()
        else:
            self._set_hover_state(False)
            self._hover_start_time = None
            if getattr(self.hud, 'current_hud_type', None) in ("activity", "downloads") and not self.geometry().contains(pos):
                self.hud.dismiss_hud()

    def enterEvent(self, event):
        mode = self.settings.get("edge_trigger_mode", "hover")
        if mode == "hotkey_only" or is_mouse_dragging():
            super().enterEvent(event)
            return

        if time.time() - getattr(self, '_startup_time', 0) < 1.5:
            super().enterEvent(event)
            return

        pos = QCursor.pos()
        if not self._is_point_on_bar(pos):
            super().enterEvent(event)
            return

        self._has_mouse_moved = True
        self._set_hover_state(True)

        act_state = self.island_monitor.activity_mgr.get_merged_state()
        if act_state.get("has_active", False):
            if not self.is_island_expanded:
                self.hud.show_hud("activity", act_state, duration_ms=0, persistent=True)
            super().enterEvent(event)
            return

        if self.settings.get("radial_menu_enabled", True):
            # Top edge hover for search is disabled under radial architecture
            super().enterEvent(event)
            return

        if mode != "click" and not self.overlay.is_open and not self.overlay.is_animating:
            if self._hover_start_time is None:
                self._hover_start_time = time.time()

        super().enterEvent(event)

    def mouseMoveEvent(self, event):
        self._mouse_local_pos = event.pos()
        if self.is_island_expanded and getattr(self.hud, 'current_hud_type', None):
            handled = self.hud.handle_mouse_move(event.pos())
            if handled:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            pos = QCursor.pos()
            if self._is_point_on_bar(pos):
                self._set_hover_state(True)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self._set_hover_state(False)
                self._hover_start_time = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._mouse_local_pos = None
        self._hover_start_time = None
        pos = QCursor.pos()
        if not self._is_point_on_bar(pos):
            self._set_hover_state(False)
            if getattr(self.hud, 'current_hud_type', None) in ("activity", "downloads"):
                self.hud.dismiss_hud()
        if hasattr(self.hud, 'handle_mouse_leave'):
            self.hud.handle_mouse_leave()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self.is_island_expanded and getattr(self.hud, 'current_hud_type', None):
            handled = self.hud.handle_mouse_press(event.pos())
            if handled:
                event.accept()
                return

        # If in music edge bar mode and clicked on the left Spotify badge, toggle playback directly
        act_state = self.island_monitor.activity_mgr.get_merged_state()
        if self.should_show_music_edge_bar() and not act_state.get("has_active", False):
            pill = self._resting_pill_rect()
            if QRect(pill.left(), pill.top(), 32, pill.height()).contains(event.pos()):
                if hasattr(self.overlay, "media_mgr") and self.overlay.media_mgr:
                    self.overlay.media_mgr.play_pause()
                event.accept()
                return

        mode = self.settings.get("edge_trigger_mode", "hover")
        if mode == "hotkey_only" or self.settings.get("radial_menu_enabled", True):
            super().mousePressEvent(event)
            return

        if not self._is_point_on_bar(QCursor.pos()):
            event.ignore()
            return

        self._hover_start_time = None
        if not self.overlay.is_open and not self.overlay.is_animating:
            self.overlay.surface()
        event.accept()

    def closeEvent(self, event):
        event.ignore()

