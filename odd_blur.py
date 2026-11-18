"""
Native Windows Transparent Window Support & Solid Surface Engine for ODD.
Configures 100% per-pixel alpha transparency for the frameless canvas while
UI island surfaces render pure AMOLED black (#080808) with subtle grey borders.
All experimental DWM acrylic backdrops, fake blurs, and ripple distortions are removed.
"""

import sys
import ctypes
from ctypes import wintypes, c_int, byref, sizeof, Structure, POINTER

# DWM Window Attributes
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38

# DWM System Backdrop Types
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2
DWMSBT_TRANSIENTWINDOW = 3

# DWM Window Corner Preferences
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2

class ACCENT_POLICY(Structure):
    _fields_ = [
        ('AccentState', c_int),
        ('AccentFlags', c_int),
        ('GradientColor', c_int),
        ('AnimationId', c_int)
    ]

class WINCOMPATTRDATA(Structure):
    _fields_ = [
        ('Attribute', c_int),
        ('Data', POINTER(c_int)),
        ('SizeOfData', ctypes.c_size_t)
    ]

ACCENT_DISABLED = 0

def get_windows_build() -> int:
    """Returns the Windows build number, or 0 if not Windows"""
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def ensure_transparent_hwnd(hwnd: int) -> bool:
    """
    Ensures the native Windows HWND maintains 100% per-pixel alpha transparency
    for empty canvas pixels with zero rectangular backdrop or black backing quad.
    Configures DWM corner preference to DO NOT ROUND and sets system backdrop type
    to DWMSBT_NONE with ACCENT_DISABLED.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
        build = get_windows_build()

        if build >= 22000:
            corner_pref = c_int(DWMWCP_DONOTROUND)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                DWMWA_WINDOW_CORNER_PREFERENCE,
                byref(corner_pref),
                sizeof(corner_pref),
            )
        if build >= 22621:
            backdrop_none = c_int(DWMSBT_NONE)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                DWMWA_SYSTEMBACKDROP_TYPE,
                byref(backdrop_none),
                sizeof(backdrop_none),
            )

        # Disable any accent policy so DWM never composites a rectangular quad
        try:
            user32 = ctypes.windll.user32
            accent = ACCENT_POLICY()
            accent.AccentState = ACCENT_DISABLED
            accent.AccentFlags = 0
            accent.GradientColor = 0
            accent.AnimationId = 0

            data = WINCOMPATTRDATA()
            data.Attribute = 19
            data.Data = ctypes.cast(byref(accent), POINTER(c_int))
            data.SizeOfData = sizeof(accent)

            set_win_attr = user32.SetWindowCompositionAttribute
            set_win_attr.argtypes = [wintypes.HWND, POINTER(WINCOMPATTRDATA)]
            set_win_attr.restype = wintypes.BOOL
            set_win_attr(wintypes.HWND(hwnd), byref(data))
        except Exception:
            pass

        return True
    except Exception:
        return False


def apply_dark_acrylic_blur(hwnd: int, dark_tint: int = 0xDD12141C) -> bool:
    """Maintains transparent canvas without rectangular DWM slabs."""
    return ensure_transparent_hwnd(hwnd)


def apply_light_acrylic_blur(hwnd: int) -> bool:
    return ensure_transparent_hwnd(hwnd)


def apply_surface_backdrop_blur(
    hwnd: int,
    rounded_rects: list = None,
    dpr: float = 1.0,
    enable: bool = True,
) -> bool:
    """Ensures transparent HWND canvas with zero full-window DWM slabs."""
    return ensure_transparent_hwnd(hwnd)


class ODDOverlaySurface:
    """
    ODD 2.0 Shared Solid AMOLED Black Surface Renderer
    Used across ALL ODD surfaces:
    - Search Island & Suggestion Cards
    - Dynamic Island Top Capsule
    - System-Status Pills
    - Notification, Download, and Reminder Cards

    Visual Characteristics:
    - Pure AMOLED black (#080808), 100% opaque, no gradients, no noise
    - Subtle dark-grey border (#292929, 0.8px)
    - Soft ambient drop shadows beneath the island
    - Continuous superellipse squircle geometry
    """

    @staticmethod
    def paint_glass_surface(
        painter,
        rect,
        radius: float,
        theme: str = "dark",
        opacity: float = 1.0,
        hover_val: float = 0.0,
        pulse_val: float = 0.0,
        press_val: float = 0.0,
        hwnd: int = 0,
        ambient_color=None,
        hover_pos=None,
        hover_color=None,
        surface_type: str = "primary",
        focus_val: float = 0.0,
        widget=None,
    ):
        eff_op = max(0.0, min(1.0, float(opacity)))
        if eff_op <= 0.004:
            return

        try:
            from fluentapp.windoweffect import WindowBlur
            WindowBlur.paint_acrylic_surface(
                painter,
                rect,
                radius,
                theme=theme,
                opacity=eff_op,
                hover_val=hover_val,
                pulse_val=pulse_val,
                press_val=press_val,
                ambient_color=ambient_color,
                hover_pos=hover_pos,
                hover_color=hover_color,
                surface_type=surface_type,
                focus_val=focus_val,
                widget=widget,
            )
        except Exception:
            from PySide6.QtCore import QRectF, Qt
            from PySide6.QtGui import QPainterPath, QColor, QBrush, QPen

            r_rect = QRectF(rect)
            if r_rect.width() <= 1.0 or r_rect.height() <= 1.0:
                return

            r = max(2.0, min(float(radius), r_rect.width() / 2.0, r_rect.height() / 2.0))
            try:
                from odd_theme import create_squircle_path
                path = create_squircle_path(r_rect, r)
            except Exception:
                path = QPainterPath()
                path.addRoundedRect(r_rect, r, r)

            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing)

            bg_col = QColor(8, 8, 8, 255) if surface_type != "secondary" else QColor(14, 14, 15, 255)
            border_col = QColor(41, 41, 41, 255)

            painter.fillPath(path, QBrush(bg_col))
            painter.strokePath(path, QPen(border_col, 0.8))
            painter.restore()


class GlassDisplacementRipple:
    """Inert ripple wave stub (experimental ripple distortion completely removed)."""
    def __init__(self, is_smooth: bool = True):
        self.is_active = False
        self.duration_ms = 0.0
        self.origin_x = 0.0
        self.origin_y = 0.0

    def trigger(self, *args, **kwargs):
        self.is_active = False

    def get_progress(self) -> float:
        self.is_active = False
        return 1.0

    def paint(self, *args, **kwargs):
        pass


# Backward compatibility alias
WaterRippleWave = GlassDisplacementRipple
