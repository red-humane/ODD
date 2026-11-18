"""
ODD Component Library (odd_ui.py)
Premium Monochrome Dynamic Island UI Components for Windows.
Custom-painted, low-overhead, GPU-accelerated, zero-color-hue design system.
"""

import time
import math
from typing import Optional, List, Callable
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal, QTimer, Property
from PySide6.QtWidgets import (
    QWidget, QPushButton, QLineEdit, QLabel, QHBoxLayout, QVBoxLayout,
    QScrollArea, QFrame, QSizePolicy
)
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QPen, QBrush, QLinearGradient,
    QPixmap, QFont, QFontMetrics, QKeyEvent, QMouseEvent
)

from odd_theme import Tokens, Fonts, create_squircle_path, MonochromeIcons
from odd_motion import ShadowCache
from odd_spring import SpringValue as Spring


# ---------------------------------------------------------------------------
# 1. FAKE FROST NOISE & SHADOW PRE-RENDER ENGINE
# Pre-rendered once per DPI scale. Cross-version safe, zero DWM artifacts.
# ---------------------------------------------------------------------------

class FakeFrostTexture:
    """Pre-rendered subtle micro-noise texture for tactile glass surface"""
    _pixmap: Optional[QPixmap] = None

    @classmethod
    def get_texture(cls, size: int = 128) -> QPixmap:
        if cls._pixmap is None or cls._pixmap.isNull():
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            # Procedural monochromatic micro-grain
            # Deterministic pseudo-random distribution
            seed = 1337
            for y in range(size):
                for x in range(size):
                    seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
                    if (seed & 0xFF) < 32:  # 12% density
                        alpha = 8 + (seed & 0x0F)
                        painter.setPen(QColor(255, 255, 255, alpha))
                        painter.drawPoint(x, y)
            painter.end()
            cls._pixmap = pm
        return cls._pixmap


# ---------------------------------------------------------------------------
# 2. ISLAND SURFACE (The Living Squircle Body)
# ---------------------------------------------------------------------------

class IslandSurface(QWidget):
    """
    Continuous Squircle body of the Dynamic Island.
    Features:
    - Analytic G2 continuous-curvature superellipse path
    - Cached 9-slice soft ambient drop shadow (Zero QGraphicsDropShadowEffect)
    - Cross-version safe fake-frost micro-grain texture
    - Hairline top edge specular highlight (1px 16% white alpha)
    - Zero background artifacts on Windows 10/11
    """
    def __init__(self, radius: float = Tokens.RADIUS_PANEL, parent=None):
        super().__init__(parent)
        self.radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._reduce_transparency = False
        self._surface_opacity = 1.0

    def set_radius(self, radius: float):
        if abs(self.radius - radius) > 0.5:
            self.radius = radius
            self.update()

    def set_surface_opacity(self, opacity: float):
        self._surface_opacity = max(0.0, min(1.0, float(opacity)))
        self.update()

    def set_reduce_transparency(self, enabled: bool):
        self._reduce_transparency = bool(enabled)
        self.update()

    def paintEvent(self, event):
        if self.width() <= 4 or self.height() <= 4:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        squircle = create_squircle_path(rect, self.radius)

        # 1. Soft Ambient Drop Shadow under the island
        if not self._reduce_transparency and self.width() > 30 and self.height() > 30:
            shadow_pm = ShadowCache.get_shadow(int(self.width()), int(self.height()), int(self.radius), "dark")
            if shadow_pm and not shadow_pm.isNull():
                painter.save()
                painter.setOpacity(0.55 * self._surface_opacity)
                painter.drawPixmap(0, 0, shadow_pm)
                painter.restore()

        # 2. Island Body Fill (Translucent Black or Solid Black if reduce transparency)
        painter.save()
        painter.setOpacity(self._surface_opacity)
        if self._reduce_transparency:
            body_brush = QBrush(Tokens.SURFACE_0_SOLID)
        else:
            # Subtle top-to-bottom depth gradient (94% to 90% black alpha)
            grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
            grad.setColorAt(0.0, QColor(10, 10, 12, 240))
            grad.setColorAt(1.0, QColor(5, 5, 7, 230))
            body_brush = QBrush(grad)

        painter.fillPath(squircle, body_brush)

        # 3. Micro-grain tactile frost texture (clipped to squircle)
        if not self._reduce_transparency:
            painter.save()
            painter.setClipPath(squircle)
            painter.setOpacity(0.35 * self._surface_opacity)
            tex = FakeFrostTexture.get_texture(128)
            painter.drawTiledPixmap(rect.toRect(), tex)
            painter.restore()

        # 4. Hairline Edge Highlight (Top specular rim 16% -> sides 8% -> bottom 4%)
        rim_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        rim_grad.setColorAt(0.00, Tokens.BORDER_STRONG)
        rim_grad.setColorAt(0.30, Tokens.BORDER_SUBTLE)
        rim_grad.setColorAt(1.00, QColor(255, 255, 255, 10))

        painter.strokePath(squircle, QPen(QBrush(rim_grad), 1.0))
        painter.restore()


# ---------------------------------------------------------------------------
# 3. ICON BUTTON (20px / 24px Glyph with Micro-Spring Press)
# ---------------------------------------------------------------------------

class IconButton(QPushButton):
    """Monochrome Line-Icon Button with spring scale and hover surface-2 background"""
    def __init__(self, icon_name: str, size: int = 28, icon_size: float = 18.0, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.box_size = size
        self.icon_size = icon_size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._scale_spring = Spring(1.0, response=0.08, damping_ratio=0.82)
        self._hover_spring = Spring(0.0, response=0.10, damping_ratio=0.88)
        self._is_active = False

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_tick)
        self._last_time = time.perf_counter()

    def set_icon_name(self, name: str):
        if self.icon_name != name:
            self.icon_name = name
            self.update()

    def set_active(self, active: bool):
        if self._is_active != active:
            self._is_active = active
            self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._hover_spring.set_target(1.0)
        self._start_anim()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover_spring.set_target(0.0)
        self._start_anim()

    def mousePressEvent(self, event: QMouseEvent):
        super().mousePressEvent(event)
        self._scale_spring.set_target(0.90)
        self._start_anim()

    def mouseReleaseEvent(self, event: QMouseEvent):
        super().mouseReleaseEvent(event)
        target = 1.05 if self.underMouse() else 1.0
        self._scale_spring.set_target(target)
        self._start_anim()

    def _start_anim(self):
        self._last_time = time.perf_counter()
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _on_tick(self):
        now = time.perf_counter()
        dt = min(0.033, now - self._last_time)
        self._last_time = now
        self._scale_spring.update(dt)
        self._hover_spring.update(dt)
        self.update()
        if self._scale_spring.is_settled() and self._hover_spring.is_settled():
            self._anim_timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        s = self._scale_spring.value
        h = self._hover_spring.value

        painter.save()
        painter.translate(cx, cy)
        painter.scale(s, s)
        painter.translate(-cx, -cy)

        # Soft circular surface-2 highlight on hover
        if h > 0.01 or self._is_active:
            r = min(cx, cy) - 1.5
            alpha = int((18 * h) + (26 if self._is_active else 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, alpha))
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Draw Monochrome Vector Icon
        icon_col = Tokens.TEXT_PRIMARY if (self.underMouse() or self._is_active) else Tokens.TEXT_SECONDARY
        MonochromeIcons.draw(self.icon_name, painter, QPointF(cx, cy), size=self.icon_size, color=icon_col)
        painter.restore()


# ---------------------------------------------------------------------------
# 4. CHIP / BADGE (Filled vs. Outlined with State Without Color)
# ---------------------------------------------------------------------------

class ChipBadge(QWidget):
    """
    Monochrome Status Badge communicating state strictly through shape, fill, and weight:
    - DISCONNECTED: Outlined badge, hollow dot, secondary text
    - CONNECTED: Solid white badge with dark text and solid breathing dot
    - BUSY / PAIRING: Outlined badge with pulsing dot
    """
    def __init__(self, text: str, state: str = "disconnected", parent=None):
        super().__init__(parent)
        self.text = text
        self.state = state  # "connected", "disconnected", "busy"
        self.setFixedHeight(22)
        self._dot_pulse = 0.0
        self._pulse_dir = 1.0

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._on_pulse)

        if self.state in ("connected", "busy"):
            self._pulse_timer.start()

    def set_status(self, text: str, state: str):
        self.text = text
        self.state = state
        if self.state in ("connected", "busy") and not self._pulse_timer.isActive():
            self._pulse_timer.start()
        elif self.state == "disconnected" and self._pulse_timer.isActive():
            self._pulse_timer.stop()
            self._dot_pulse = 0.0
        self.update()

    def _on_pulse(self):
        self._dot_pulse += 0.05 * self._pulse_dir
        if self._dot_pulse >= 1.0:
            self._dot_pulse = 1.0
            self._pulse_dir = -1.0
        elif self._dot_pulse <= 0.0:
            self._dot_pulse = 0.0
            self._pulse_dir = 1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        font = Fonts.caption(9.5, bold=True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        txt_w = fm.horizontalAdvance(self.text)
        w = float(txt_w + 26.0)
        h = float(self.height())
        rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
        r = h / 2.0

        path = QPainterPath()
        path.addRoundedRect(rect, r, r)

        if self.state == "connected":
            # Solid White Fill with Black Text
            painter.fillPath(path, QBrush(Tokens.INVERT_BG))
            painter.strokePath(path, QPen(Tokens.BORDER_STRONG, 1.0))

            # Solid Breathing Dot
            dot_rad = 3.2 + 0.6 * self._dot_pulse
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(Tokens.INVERT_TEXT))
            painter.drawEllipse(QPointF(rect.left() + 9.0, rect.center().y()), dot_rad, dot_rad)

            # Black Text
            painter.setPen(Tokens.INVERT_TEXT)
            painter.drawText(QRectF(rect.left() + 16.0, rect.top(), txt_w + 4.0, h),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)
        else:
            # Outlined Monochrome Badge
            painter.fillPath(path, QBrush(Tokens.SURFACE_1))
            painter.strokePath(path, QPen(Tokens.BORDER_SUBTLE, 1.0))

            # Hollow / Pulsing Dot
            dot_y = rect.center().y()
            if self.state == "busy":
                b_alpha = int(120 + 135 * self._dot_pulse)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, b_alpha))
                painter.drawEllipse(QPointF(rect.left() + 9.0, dot_y), 3.0, 3.0)
            else:
                # Hollow dot for disconnected
                painter.setPen(QPen(Tokens.TEXT_SECONDARY, 1.4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(rect.left() + 9.0, dot_y), 2.8, 2.8)

            painter.setPen(Tokens.TEXT_SECONDARY)
            painter.drawText(QRectF(rect.left() + 16.0, rect.top(), txt_w + 4.0, h),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)

    def sizeHint(self) -> QSize:
        font = Fonts.caption(9.5, bold=True)
        fm = QFontMetrics(font)
        txt_w = fm.horizontalAdvance(self.text)
        return QSize(int(txt_w + 32), 22)

    def setText(self, text: str):
        t_upper = str(text).upper()
        if "CONNECT" in t_upper and "DIS" not in t_upper:
            st = "connected"
        elif "BUSY" in t_upper or "PAIR" in t_upper:
            st = "busy"
        else:
            st = "disconnected"
        self.set_status(str(text), st)

    def setStyleSheet(self, ss: str):
        pass  # Native custom-painted monochrome chip


# ---------------------------------------------------------------------------
# 5. BUTTONS: PRIMARY, SECONDARY, GHOST
# ---------------------------------------------------------------------------

class PrimaryButton(QPushButton):
    """Signature Solid White Capsule / Squircle Button with Inverted Black Typography"""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(Fonts.body(11.5, bold=True))
        self._press_spring = Spring(1.0, response=0.08, damping_ratio=0.84)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_tick)
        self._last_time = time.perf_counter()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._press_spring.set_target(0.94)
        self._last_time = time.perf_counter()
        self._anim_timer.start()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._press_spring.set_target(1.0)
        self._last_time = time.perf_counter()
        self._anim_timer.start()

    def _on_tick(self):
        now = time.perf_counter()
        dt = min(0.033, now - self._last_time)
        self._last_time = now
        self._press_spring.update(dt)
        self.update()
        if self._press_spring.is_settled():
            self._anim_timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        s = self._press_spring.value
        painter.save()
        painter.translate(cx, cy)
        painter.scale(s, s)
        painter.translate(-cx, -cy)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        r = rect.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)

        bg = Tokens.INVERT_HOVER if self.underMouse() else Tokens.INVERT_BG
        painter.fillPath(path, QBrush(bg))
        painter.strokePath(path, QPen(Tokens.BORDER_STRONG, 1.0))

        painter.setFont(self.font())
        painter.setPen(Tokens.INVERT_TEXT)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.restore()


class SecondaryButton(QPushButton):
    """Surface-2 Monochrome Button with Hairline Border"""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(Fonts.body(11.5, bold=False))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        r = 8.0
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)

        bg = Tokens.SURFACE_3 if self.underMouse() else Tokens.SURFACE_2
        border = Tokens.BORDER_STRONG if self.underMouse() else Tokens.BORDER_SUBTLE

        painter.fillPath(path, QBrush(bg))
        painter.strokePath(path, QPen(border, 1.0))

        painter.setFont(self.font())
        painter.setPen(Tokens.TEXT_PRIMARY if self.underMouse() else Tokens.TEXT_SECONDARY)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


# ---------------------------------------------------------------------------
# 6. SEGMENTED CONTROL (Sliding White Thumb with Spring Physics)
# ---------------------------------------------------------------------------

class SegmentedControl(QWidget):
    """
    Monochrome Segmented Tab Control.
    Sliding solid white indicator thumb with spring physics.
    Zero color accents.
    """
    selection_changed = Signal(int, str)

    def __init__(self, items: List[str], current_index: int = 0, parent=None):
        super().__init__(parent)
        self.items = items
        self.current_index = current_index
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._thumb_x_spring = Spring(0.0, response=0.10, damping_ratio=0.88)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_tick)
        self._last_time = time.perf_counter()

    def set_index(self, idx: int):
        if 0 <= idx < len(self.items) and idx != self.current_index:
            self.current_index = idx
            target_x = self._get_target_x(idx)
            self._thumb_x_spring.set_target(target_x)
            self._last_time = time.perf_counter()
            self._anim_timer.start()
            self.selection_changed.emit(idx, self.items[idx])
            self.update()

    def _get_target_x(self, idx: int) -> float:
        if not self.items:
            return 2.0
        seg_w = (self.width() - 4.0) / len(self.items)
        return 2.0 + idx * seg_w

    def _on_tick(self):
        now = time.perf_counter()
        dt = min(0.033, now - self._last_time)
        self._last_time = now
        self._thumb_x_spring.update(dt)
        self.update()
        if self._thumb_x_spring.is_settled():
            self._anim_timer.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._thumb_x_spring.snap_to(self._get_target_x(self.current_index))

    def mousePressEvent(self, event: QMouseEvent):
        if not self.items:
            return
        seg_w = self.width() / len(self.items)
        clicked_idx = int(event.position().x() // seg_w)
        clicked_idx = max(0, min(len(self.items) - 1, clicked_idx))
        self.set_index(clicked_idx)

    def paintEvent(self, event):
        if not self.items:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        r = rect.height() / 2.0
        base_path = QPainterPath()
        base_path.addRoundedRect(rect, r, r)

        # Background track
        painter.fillPath(base_path, QBrush(Tokens.SURFACE_1))
        painter.strokePath(base_path, QPen(Tokens.BORDER_SUBTLE, 1.0))

        # Sliding White Thumb
        seg_w = (rect.width() - 2.0) / len(self.items)
        thumb_h = rect.height() - 4.0
        thumb_x = self._thumb_x_spring.value
        thumb_rect = QRectF(thumb_x, rect.top() + 2.0, seg_w, thumb_h)
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb_rect, thumb_h / 2.0, thumb_h / 2.0)

        painter.fillPath(thumb_path, QBrush(Tokens.INVERT_BG))
        painter.strokePath(thumb_path, QPen(Tokens.BORDER_STRONG, 1.0))

        # Text labels
        painter.setFont(Fonts.body(11, bold=True))
        for idx, item in enumerate(self.items):
            item_x = 2.0 + idx * seg_w
            item_rect = QRectF(item_x, rect.top(), seg_w, rect.height())
            is_active = (idx == self.current_index)
            painter.setPen(Tokens.INVERT_TEXT if is_active else Tokens.TEXT_SECONDARY)
            painter.drawText(item_rect, Qt.AlignmentFlag.AlignCenter, item)


# ---------------------------------------------------------------------------
# 7. SEARCH FIELD (Borderless, Big Caret, Focus White Glow)
# ---------------------------------------------------------------------------

class SearchField(QLineEdit):
    """
    Clean borderless search field with soft white outline glow on focus.
    Monochrome typography and native keyboard navigation.
    """
    def __init__(self, placeholder: str = "Search here...", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFont(Fonts.title(14))
        self.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #FFFFFF;
                padding: 4px 6px;
                selection-background-color: rgba(255, 255, 255, 0.25);
                selection-color: #FFFFFF;
            }
        """)


# ---------------------------------------------------------------------------
# 8. TILE (Surface-1 Rounded Container) & DIVIDER
# ---------------------------------------------------------------------------

class Tile(QWidget):
    """Soft Surface-1 Squircle Container with 1px border-subtle"""
    def __init__(self, radius: float = Tokens.RADIUS_TILE, parent=None):
        super().__init__(parent)
        self.radius = radius

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        path = create_squircle_path(rect, self.radius)

        painter.fillPath(path, QBrush(Tokens.SURFACE_1))
        painter.strokePath(path, QPen(Tokens.BORDER_SUBTLE, 1.0))


class Divider(QWidget):
    """1px Hairline Content Divider"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Tokens.DIVIDER)


class SectionLabel(QLabel):
    """10.5px All-Caps Section Header with +8% Tracking"""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(Fonts.section_header())
        self.setStyleSheet("color: rgba(255, 255, 255, 0.50); letter-spacing: 0.8px;")


# ---------------------------------------------------------------------------
# 9. STEP LIST (Numbered Steps with Clean Outlined Number Circles)
# ---------------------------------------------------------------------------

class StepList(QWidget):
    """Numbered Step List for Guides with Circle Number Badges"""
    def __init__(self, steps: List[str], parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)

        for idx, step_txt in enumerate(steps, 1):
            row = QWidget(self)
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(0, 0, 0, 0)
            r_lay.setSpacing(10)

            # Circle badge
            badge = QLabel(str(idx), row)
            badge.setFixedSize(20, 20)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFont(Fonts.caption(9.5, bold=True))
            badge.setStyleSheet("""
                QLabel {
                    background: rgba(255, 255, 255, 0.08);
                    border: 1px solid rgba(255, 255, 255, 0.20);
                    border-radius: 10px;
                    color: #FFFFFF;
                }
            """)
            r_lay.addWidget(badge)

            # Step text
            lbl = QLabel(step_txt, row)
            lbl.setFont(Fonts.body(11))
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: rgba(255, 255, 255, 0.85); line-height: 1.3;")
            r_lay.addWidget(lbl, stretch=1)

            layout.addWidget(row)


# ---------------------------------------------------------------------------
# 10. MONOCHROME SLIDER (Thin Track, White Fill, Live Odometer)
# ---------------------------------------------------------------------------

class MonochromeSlider(QWidget):
    """Thin track slider with live percentage feedback"""
    value_changed = Signal(int)

    def __init__(self, min_val: int = 0, max_val: int = 100, init_val: int = 50, parent=None):
        super().__init__(parent)
        self.min_val = min_val
        self.max_val = max_val
        self.current_val = init_val
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dragging = False

    def set_value(self, val: int):
        val = max(self.min_val, min(self.max_val, val))
        if val != self.current_val:
            self.current_val = val
            self.value_changed.emit(val)
            self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_pos(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._update_from_pos(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _update_from_pos(self, x: float):
        w = float(self.width())
        t = max(0.0, min(1.0, x / w))
        new_val = int(self.min_val + t * (self.max_val - self.min_val))
        self.set_value(new_val)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        cy = self.height() / 2.0
        track_h = 4.0
        track_rect = QRectF(0.0, cy - track_h / 2.0, w, track_h)

        # Background track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Tokens.SURFACE_2)
        painter.drawRoundedRect(track_rect, 2.0, 2.0)

        # Active Fill
        pct = (self.current_val - self.min_val) / max(1, self.max_val - self.min_val)
        fill_w = max(4.0, w * pct)
        fill_rect = QRectF(0.0, cy - track_h / 2.0, fill_w, track_h)
        painter.setBrush(Tokens.INVERT_BG)
        painter.drawRoundedRect(fill_rect, 2.0, 2.0)

        # Handle
        handle_x = fill_w
        handle_r = 6.0 if self._dragging or self.underMouse() else 4.5
        painter.setBrush(Tokens.INVERT_BG)
        painter.setPen(QPen(Tokens.BORDER_STRONG, 1.0))
        painter.drawEllipse(QPointF(handle_x, cy), handle_r, handle_r)
