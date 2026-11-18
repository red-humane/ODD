"""
fluentapp.windoweffect - Native Windows Transparent Blur & Acrylic Window Effects
Provides high-performance backdrop blur and acrylic transparency via Win32 DWM and
SetWindowCompositionAttribute APIs.
"""

import sys
import ctypes
from ctypes import wintypes, c_int, byref, sizeof, Structure, POINTER

# DWM Window Attributes
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38

# DWM System Backdrop Types (Windows 11 build 22621+)
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2       # Mica
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic
DWMSBT_TABBEDWINDOW = 4     # Mica Alt

# DWM Window Corner Preferences (Windows 11 build 22000+)
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3

class ACCENT_POLICY(Structure):
    _fields_ = [
        ('AccentState', c_int),
        ('AccentFlags', c_int),
        ('GradientColor', c_int),
        ('AnimationId', c_int)
    ]

class MARGINS(Structure):
    _fields_ = [
        ('cxLeftWidth', c_int),
        ('cxRightWidth', c_int),
        ('cyTopHeight', c_int),
        ('cyBottomHeight', c_int),
    ]

class WINCOMPATTRDATA(Structure):
    _fields_ = [
        ('Attribute', c_int),
        ('Data', POINTER(c_int)),
        ('SizeOfData', ctypes.c_size_t)
    ]

ACCENT_DISABLED = 0
ACCENT_ENABLE_GRADIENT = 1
ACCENT_ENABLE_TRANSPARENTGRADIENT = 2
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

def get_windows_build() -> int:
    """Returns the Windows build number, or 0 if not Windows"""
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


class WindowBlur:
    """
    Transparent blur effect engine with native Windows acrylic glass support
    and black tint styling.
    
    Usage:
        from fluentapp.windoweffect import WindowBlur
        
        # Configure global effect
        WindowBlur(radius=50, acrylic=True, draggable=False)
        
        # Or apply to a specific window
        WindowBlur(window, radius=50, acrylic=True, draggable=False)
    """
    _global_config = {
        "radius": 50,
        "acrylic": True,
        "draggable": False,
        "tint": 0x8C0C0E14,  # Deep acrylic semi-transparent black tint
    }
    _instances = []

    def __init__(
        self,
        target=None,
        *,
        radius: int = 50,
        acrylic: bool = True,
        draggable: bool = False,
        tint: int = 0x8C0C0E14,
        **kwargs
    ):
        self.radius = int(radius)
        self.acrylic = bool(acrylic)
        self.draggable = bool(draggable)
        self.tint = int(tint)
        self.target = target
        self._drag_start_pos = None

        # Update global configuration so overall UI adapts to these settings
        WindowBlur._global_config.update({
            "radius": self.radius,
            "acrylic": self.acrylic,
            "draggable": self.draggable,
            "tint": self.tint,
        })
        WindowBlur._instances.append(self)

        if target is not None:
            self.apply(target)

    @staticmethod
    def get_config() -> dict:
        return dict(WindowBlur._global_config)

    def apply(self, target=None):
        """Applies the blur and acrylic effect to a QWidget, window ID, or HWND."""
        if target is None:
            target = self.target
        if target is None:
            return False

        hwnd = 0
        widget = None
        if isinstance(target, int):
            hwnd = target
        elif hasattr(target, "winId"):
            try:
                hwnd = int(target.winId())
            except Exception:
                hwnd = 0
            widget = target
        elif hasattr(target, "hwnd"):
            hwnd = int(target.hwnd)

        if not hwnd or sys.platform != "win32":
            return False

        # Apply native Windows acrylic / blur backdrop
        success = self._apply_native_acrylic(hwnd)

        # Handle window dragging if requested
        if widget is not None:
            if self.draggable:
                self._attach_drag_handler(widget)
            else:
                self._detach_drag_handler(widget)

        return success

    def _apply_native_acrylic(self, hwnd: int) -> bool:
        """Applies Win32 acrylic backdrop blur with the configured black tint."""
        if sys.platform != "win32" or not hwnd:
            return False

        success = False
        build = get_windows_build()

        # 1. Enable Immersive Dark Mode on DWM frame
        try:
            dwmapi = ctypes.windll.dwmapi
            dark_flag = c_int(1)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                DWMWA_USE_IMMERSIVE_DARK_MODE,
                byref(dark_flag),
                sizeof(dark_flag)
            )
        except Exception:
            pass

        # 2. Windows 11 rounded corners
        if build >= 22000:
            try:
                corner_pref = c_int(DWMWCP_ROUND)
                dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd),
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    byref(corner_pref),
                    sizeof(corner_pref)
                )
            except Exception:
                pass

        # 3. Windows 11 Build 22621+: Apply native transient acrylic backdrop if acrylic is enabled
        if self.acrylic and build >= 22621:
            try:
                backdrop_type = c_int(DWMSBT_TRANSIENTWINDOW)  # Acrylic
                res = dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd),
                    DWMWA_SYSTEMBACKDROP_TYPE,
                    byref(backdrop_type),
                    sizeof(backdrop_type)
                )
                if res == 0:
                    success = True
            except Exception:
                pass

        # 3b. Extend frame into client area for native DWM client composition
        try:
            margins = MARGINS(-1, -1, -1, -1)
            dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), byref(margins))
        except Exception:
            pass

        # 4. Universal Windows 10/11 Acrylic / Blur Behind via SetWindowCompositionAttribute
        try:
            user32 = ctypes.windll.user32
            accent = ACCENT_POLICY()
            if self.acrylic:
                accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
                accent.AccentFlags = 2  # Draw borders
            else:
                accent.AccentState = ACCENT_ENABLE_BLURBEHIND
                accent.AccentFlags = 0

            # GradientColor format is AABBGGRR
            a = (self.tint >> 24) & 0xFF
            r = (self.tint >> 16) & 0xFF
            g = (self.tint >> 8) & 0xFF
            b = self.tint & 0xFF
            accent.GradientColor = (a << 24) | (b << 16) | (g << 8) | r
            accent.AnimationId = 0

            data = WINCOMPATTRDATA()
            data.Attribute = 19  # WCA_ACCENT_POLICY
            data.Data = ctypes.cast(byref(accent), POINTER(c_int))
            data.SizeOfData = sizeof(accent)

            set_win_attr = user32.SetWindowCompositionAttribute
            set_win_attr.argtypes = [wintypes.HWND, POINTER(WINCOMPATTRDATA)]
            set_win_attr.restype = wintypes.BOOL

            if set_win_attr(wintypes.HWND(hwnd), byref(data)):
                success = True
        except Exception:
            pass

        return success

    def _attach_drag_handler(self, widget):
        """Attaches mouse drag handling for frameless windows if draggable=True"""
        def mouse_press(event):
            try:
                from PySide6.QtCore import Qt
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_start_pos = event.globalPosition().toPoint() - widget.frameGeometry().topLeft()
            except Exception:
                pass

        def mouse_move(event):
            try:
                from PySide6.QtCore import Qt
                if self._drag_start_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
                    widget.move(event.globalPosition().toPoint() - self._drag_start_pos)
            except Exception:
                pass

        def mouse_release(event):
            self._drag_start_pos = None

        widget.mousePressEvent = mouse_press
        widget.mouseMoveEvent = mouse_move
        widget.mouseReleaseEvent = mouse_release

    def _detach_drag_handler(self, widget):
        self._noise_pixmap = None

    @staticmethod
    def _get_frosted_noise_pixmap():
        """Generates a high-performance frosted acrylic micro-grain noise tile with organic tactile texture"""
        if getattr(WindowBlur, "_noise_tile", None) is not None:
            return WindowBlur._noise_tile

        from PySide6.QtGui import QImage, QPixmap, QColor
        import random

        size = 128
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        rng = random.Random(42)  # Deterministic seed for stable, pleasant grain

        for y in range(size):
            for x in range(size):
                v = rng.randint(0, 255)
                # Dual-tone tactile dark-acrylic glass micro-grain (subtle highlights + absorption specks)
                if v % 3 == 0:
                    alpha = rng.randint(6, 13)
                    img.setPixelColor(x, y, QColor(255, 255, 255, alpha))
                elif v % 5 == 0:
                    alpha = rng.randint(4, 9)
                    img.setPixelColor(x, y, QColor(0, 0, 0, alpha))

        WindowBlur._noise_tile = QPixmap.fromImage(img)
        return WindowBlur._noise_tile

    @staticmethod
    def paint_acrylic_surface(
        painter,
        rect,
        radius: float,
        theme: str = "dark",
        opacity: float = 1.0,
        hover_val: float = 0.0,
        pulse_val: float = 0.0,
        press_val: float = 0.0,
        ambient_color=None,
        hover_pos=None,
        hover_color=None,
        surface_type: str = "primary",
        focus_val: float = 0.0,
        widget=None,
    ):
        """
        ODD 2.0 Pure Black Minimal & Premium Surface System
        --------------------------------------------------
        - Primary Island: Solid AMOLED black (#080808), 100% opaque, soft drop shadow, 0.8px #292929 border.
        - Secondary Panels: Solid dark elevated (#0E0E0F), subtle grey border.
        - Interactive Surfaces: Subtle hover brightness (+8 RGB), gentle compression on press.
        - Zero transparency on island surfaces; zero fake blur, zero noise/grain, zero gradients.
        - Continuous superellipse squircle geometry (G2 curvature continuity).
        """
        eff_op = max(0.0, min(1.0, float(opacity)))
        if eff_op <= 0.004:
            return

        try:
            from PySide6.QtCore import QRectF, Qt
            from PySide6.QtGui import QPainterPath, QColor, QBrush, QPen

            r_rect = QRectF(rect)
            if r_rect.width() <= 1.0 or r_rect.height() <= 1.0:
                return

            h_val = max(0.0, min(1.0, float(hover_val)))
            pr_val = max(0.0, min(1.0, float(press_val)))
            f_val = max(0.0, min(1.0, float(focus_val)))
            theme_key = str(theme or "dark").lower().strip()
            is_secondary = (surface_type == "secondary")

            # Gentle physical compression on press (0.75px inset scale)
            if pr_val > 0.01:
                comp = 0.75 * pr_val
                r_rect = r_rect.adjusted(comp, comp, -comp, -comp)

            r = max(2.0, min(float(radius), r_rect.width() / 2.0, r_rect.height() / 2.0))

            # Continuous superellipse squircle path (G2 curvature continuity)
            try:
                from odd_theme import create_squircle_path
                from odd_theme import create_top_anchored_squircle_path
                if surface_type == "top_anchored":
                    path = create_top_anchored_squircle_path(r_rect, r, 0.0)
                else:
                    path = create_squircle_path(r_rect, r)
            except Exception:
                path = QPainterPath()
                path.addRoundedRect(r_rect, r, r)

            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing)

            # -------------------------------------------------------------
            # 1. Soft Ambient Drop Shadow (subtle separation from desktop)
            # -------------------------------------------------------------
            shadow_alpha_base = 28 if is_secondary else 38
            for s_spread, s_dy, s_ratio in ((6.0, 2.5, 0.18), (3.5, 1.8, 0.35), (1.5, 0.8, 0.55)):
                sh_rect = r_rect.adjusted(-s_spread, -s_spread + s_dy, s_spread, s_spread + s_dy)
                sh_rad = max(2.0, r + s_spread)
                sh_alpha = int(shadow_alpha_base * s_ratio)
                if sh_alpha > 0:
                    painter.setPen(Qt.PenStyle.NoPen)
                    try:
                        from odd_theme import create_squircle_path
                        sh_path = create_squircle_path(sh_rect, sh_rad)
                        painter.fillPath(sh_path, QBrush(QColor(0, 0, 0, sh_alpha)))
                    except Exception:
                        painter.drawRoundedRect(sh_rect, sh_rad, sh_rad)

            # -------------------------------------------------------------
            # 2. Solid Opaque AMOLED Black Surface (No gradients, no noise)
            # -------------------------------------------------------------
            if theme_key == "light":
                bg_col = QColor(245, 245, 247, 255) if not is_secondary else QColor(238, 238, 240, 255)
                border_col = QColor(215, 215, 220, 255)
            else:
                # Pure AMOLED Black: #080808 (primary) / #0E0E0F (secondary), 100% opaque
                if is_secondary:
                    v = int(14 + 8 * h_val)
                    bg_col = QColor(v, v, v + 1, 255)

                else:
                    v = int(5 + 6 * h_val)
                    bg_col = QColor(v, v, v, 255)


                # Subtle dark-grey border: #292929
                if f_val > 0.01:
                    border_col = QColor(70, 70, 75, 255)  # Focus highlight
                else:
                    b_v = int(41 + 10 * h_val)
                    border_col = QColor(b_v, b_v, b_v, 255)

            # Fill solid opaque surface
            painter.fillPath(path, QBrush(bg_col))

            # -------------------------------------------------------------
            # 3. Subtle Perimeter Border (0.8px dark grey #292929)
            # -------------------------------------------------------------
            border_pen = QPen(border_col, 0.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(path, border_pen)

            painter.restore()
        except Exception:
            pass

            # -------------------------------------------------------------
            # 8. Subtle Inner Specular Highlight (Upper Edge Hairline)
            # -------------------------------------------------------------
            # Subtle 2.5px specular refraction along the top rim
            if theme_key != "oled":
                spec_h = min(2.5, r_rect.height() * 0.10)
                specular = QLinearGradient(0, r_rect.top(), 0, r_rect.top() + spec_h)
                specular.setColorAt(0.0, QColor(255, 255, 255, specular_alpha))
                specular.setColorAt(0.40, QColor(255, 255, 255, int(specular_alpha * 0.35)))
                specular.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillPath(path, QBrush(specular))

            # -------------------------------------------------------------
            # 9. Fine Perimeter Border (0.75-1.0px Translucent White)
            # -------------------------------------------------------------
            border_pen = QPen(border_col, 0.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(path, border_pen)

            # -------------------------------------------------------------
            # 10. Focus Highlight (Accessible Focus Ring when focused)
            # -------------------------------------------------------------
            if f_val > 0.01:
                focus_pen = QPen(QColor(255, 255, 255, int(50 * f_val)), 1.2, Qt.PenStyle.SolidLine)
                painter.strokePath(path, focus_pen)

            painter.restore()
        except Exception:
            pass
