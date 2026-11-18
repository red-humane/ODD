from enum import Enum, auto

"""

ODD Animated Buttons & Overlay Animation Subsystem

Implements:

1. Animate.css `animate__headShake` entrance kinematics

2. Animate.css `animate__backOutUp` exit kinematics

3. Uiverse.io by vinodjangid07: Recycle Bin Clear Expand Button (50px circle -> 140px red pill, sliding trash & Delete text)

4. Uiverse.io by iZOXVL: `.boton-elegante` Reminder/Overlay Action Button (dark pill, radial bloom scale 0->4)

5. Uiverse.io by KhaledMatalkah: Dual Split-Curtain Wipe Cancel Button (split top/bottom white wipe)

"""



import math

from typing import Optional, Tuple

from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QTimer, Property, Signal, QEasingCurve

from PySide6.QtGui import (

    QPainter, QPainterPath, QColor, QPen, QBrush, QFont, QFontMetrics,

    QRadialGradient, QLinearGradient

)

from PySide6.QtWidgets import QPushButton, QWidget





# =========================================================================

# 1. ANIMATE.CSS KINEMATICS

# =========================================================================



def get_headshake_offset(t: float) -> float:

    """

    Evaluates animate__headShake horizontal translation (dx) in pixels.

    Keyframes:

      0%: dx = 0

      6.5%: dx = -6px

      18.5%: dx = +5px

      31.5%: dx = -3px

      43.5%: dx = +2px

      50%..100%: dx = 0px

    """

    if t <= 0.0 or t >= 0.50:

        return 0.0



    if t < 0.065:

        p = t / 0.065

        return -6.0 * math.sin(p * math.pi / 2.0)

    elif t < 0.185:

        p = (t - 0.065) / 0.120

        # -6 to +5

        return -6.0 + 11.0 * (0.5 - 0.5 * math.cos(p * math.pi))

    elif t < 0.315:

        p = (t - 0.185) / 0.130

        # +5 to -3

        return 5.0 - 8.0 * (0.5 - 0.5 * math.cos(p * math.pi))

    elif t < 0.435:

        p = (t - 0.315) / 0.120

        # -3 to +2

        return -3.0 + 5.0 * (0.5 - 0.5 * math.cos(p * math.pi))

    else:

        p = (t - 0.435) / 0.065

        # +2 to 0

        return 2.0 - 2.0 * (0.5 - 0.5 * math.cos(p * math.pi))





def get_bounceoutup_transform(t: float, total_height: float = 80.0) -> Tuple[float, float, float, float]:

    """

    Evaluates animate__bounceOutUp transform parameters: (scale_x, scale_y, dy, opacity).

    From Animate.css keyframes:

      20%: transform: translate3d(0, -10px, 0) scaleY(0.985);

      40%, 45%: opacity: 1; transform: translate3d(0, 20px, 0) scaleY(0.9);

      to: opacity: 0; transform: translate3d(0, -2000px, 0) scaleY(3);

    """

    t = max(0.0, min(1.0, float(t)))

    if t <= 0.20:

        p = t / 0.20

        # Smooth bounce upward initial nudge (-10px) and vertical compression (0.985)

        ease = 0.5 - 0.5 * math.cos(p * math.pi)

        scale_x = 1.0 + 0.01 * ease

        scale_y = 1.0 - 0.015 * ease

        dy = -10.0 * ease

        opacity = 1.0

    elif t <= 0.40:

        p = (t - 0.20) / 0.20

        # Spring dip downward to +20px and squash to 0.90

        ease = 0.5 - 0.5 * math.cos(p * math.pi)

        scale_x = 1.01 + 0.04 * ease

        scale_y = 0.985 - 0.085 * ease

        dy = -10.0 + 30.0 * ease

        opacity = 1.0

    elif t <= 0.45:

        # Hold at bottom of bounce before rocket launch

        scale_x = 1.05

        scale_y = 0.90

        dy = 20.0

        opacity = 1.0

    else:

        p = (t - 0.45) / 0.55

        # Upward launch: shoots up to -(total_height + 450) and stretches vertically up to 3.0

        ease_launch = p ** 2.4

        scale_x = max(0.65, 1.05 - 0.35 * p)

        scale_y = 0.90 + 2.10 * p

        dy = 20.0 - ease_launch * (total_height + 500.0)

        opacity = max(0.0, 1.0 - (p ** 1.8))



    return scale_x, scale_y, dy, opacity





def get_backoutup_transform(t: float, total_height: float = 80.0) -> Tuple[float, float, float]:

    """

    Evaluates bounce out up / back out up transform parameters: (scale, dy, opacity).

    Routes to animate__bounceOutUp for unified bounce-out behavior.

    """

    sx, sy, dy, opacity = get_bounceoutup_transform(t, total_height)

    return sy, dy, opacity





# =========================================================================

# 2. PAINTER IMPLEMENTATIONS FOR CUSTOM BUTTONS

# =========================================================================



def draw_trash_icon(painter: QPainter, cx: float, cy: float, size: float = 14.0, color: QColor = QColor(255, 255, 255)):

    """Draws a clean, crisp vector trash / recycle bin icon centered at (cx, cy)."""

    painter.save()

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(color, 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    painter.setPen(pen)

    painter.setBrush(Qt.BrushStyle.NoBrush)



    w = size * 0.72

    h = size * 0.85

    hw = w / 2.0

    hh = h / 2.0



    # 1. Lid / Handle

    lid_y = cy - hh + 1.0

    painter.drawLine(QPointF(cx - hw - 2.0, lid_y), QPointF(cx + hw + 2.0, lid_y))

    # Handle arch

    handle = QPainterPath()

    handle.moveTo(cx - 2.5, lid_y)

    handle.lineTo(cx - 2.5, lid_y - 2.5)

    handle.lineTo(cx + 2.5, lid_y - 2.5)

    handle.lineTo(cx + 2.5, lid_y)

    painter.strokePath(handle, pen)



    # 2. Bin body

    body = QPainterPath()

    body.moveTo(cx - hw + 1.0, lid_y + 1.0)

    body.lineTo(cx - hw + 2.2, cy + hh)

    body.lineTo(cx + hw - 2.2, cy + hh)

    body.lineTo(cx + hw - 1.0, lid_y + 1.0)

    painter.strokePath(body, pen)



    # 3. Ribs

    rib_pen = QPen(color, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)

    painter.setPen(rib_pen)

    painter.drawLine(QPointF(cx - 2.2, lid_y + 3.5), QPointF(cx - 1.8, cy + hh - 2.5))

    painter.drawLine(QPointF(cx + 2.2, lid_y + 3.5), QPointF(cx + 1.8, cy + hh - 2.5))



    painter.restore()





def paint_recycle_bin_clear_button(

    painter: QPainter,

    rect: QRectF,

    hover_progress: float = 0.0,

    text: str = "Delete",

    is_pressed: bool = False

):

    """

    Renders Uiverse.io by vinodjangid07 Recycle Bin Clear Overlay Button:

    - Normal: 50px circle, background rgb(20, 20, 20), centered trash icon

    - Hover: Expands to 140px pill, background rgb(255, 69, 69), trash icon translateY(60%),

             'Delete' text smoothly slides down into center.

    """

    p = max(0.0, min(1.0, float(hover_progress)))

    painter.save()

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)



    # Background color interpolation: rgb(20,20,20) -> rgb(255, 69, 69)

    r = int(20 + (255 - 20) * p)

    g = int(20 + (69 - 20) * p)

    b = int(20 + (69 - 20) * p)

    bg_col = QColor(r, g, b)



    radius = rect.height() / 2.0



    # Soft ambient drop shadow

    if p > 0.05:

        shadow_col = QColor(255, 69, 69, int(60 * p))

        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(shadow_col)

        painter.drawRoundedRect(rect.adjusted(-2.0, 1.0, 2.0, 4.0), radius + 2.0, radius + 2.0)

    else:

        shadow_col = QColor(0, 0, 0, 45)

        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(shadow_col)

        painter.drawRoundedRect(rect.adjusted(-1.0, 1.0, 1.0, 3.0), radius + 1.0, radius + 1.0)



    # Pill / Circle surface

    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(bg_col)

    painter.drawRoundedRect(rect, radius, radius)



    # Subtly darker edge border

    border_col = QColor(255, 255, 255, int(25 + 30 * p))

    painter.setPen(QPen(border_col, 0.9))

    painter.setBrush(Qt.BrushStyle.NoBrush)

    painter.drawRoundedRect(rect.adjusted(0.4, 0.4, -0.4, -0.4), radius - 0.4, radius - 0.4)



    # Clip to button body for clean slide-in / slide-out

    clip_path = QPainterPath()

    clip_path.addRoundedRect(rect, radius, radius)

    painter.setClipPath(clip_path)



    cx = rect.center().x()

    cy = rect.center().y()



    # Icon vertical offset: translates down (+60% height on full hover)

    icon_dy = p * (rect.height() * 0.60)

    icon_alpha = max(0.0, 1.0 - p * 0.75) if rect.width() < 70 else 1.0

    icon_col = QColor(255, 255, 255, int(255 * icon_alpha))

    

    # If expanded (pill width >= 100), position trash icon slightly lower or centered with Delete text above

    if rect.width() >= 80:

        # In expanded state: Trash icon moves down, Delete text slides from top: -20px to center:

        # Trash icon translateY

        draw_trash_icon(painter, cx, cy + icon_dy, size=13.0, color=icon_col)



        # "Delete" text slides into center from top

        text_y = rect.top() - 15.0 + p * (cy - rect.top() + 15.0)

        font_size = 2.0 + p * 10.5

        font = QFont("Segoe UI Variable Text", font_size, QFont.Weight.Bold)

        painter.setFont(font)

        painter.setPen(QColor(255, 255, 255, int(255 * p)))

        text_rect = QRectF(rect.left(), text_y - 10.0, rect.width(), 20.0)

        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    else:

        # Circular resting state: Centered icon

        draw_trash_icon(painter, cx, cy + icon_dy, size=14.0, color=icon_col)



    painter.restore()





def paint_boton_elegante(

    painter: QPainter,

    rect: QRectF,

    text: str,

    hover_progress: float = 0.0,

    theme: str = "dark",

    is_pressed: bool = False,

    font_size: float = 8.5

):

    """

    Renders Uiverse.io by iZOXVL `.boton-elegante` Reminder/Overlay Action Button:

    - Base: background #1a1a1a, border 2px solid #2c2c2c, text white, rounded pill

    - Hover: border #666666, background #292929, radial-gradient blooming scale(0) -> scale(4)

    """

    p = max(0.0, min(1.0, float(hover_progress)))

    painter.save()

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)



    radius = rect.height() / 2.0



    # Background color interpolation: #1a1a1a (26,26,26) -> #292929 (41,41,41)

    r = int(26 + (41 - 26) * p)

    g = int(26 + (41 - 26) * p)

    b = int(26 + (41 - 26) * p)

    bg_col = QColor(r, g, b)



    # Border color interpolation: #2c2c2c (44,44,44) -> #666666 (102,102,102)

    br = int(44 + (102 - 44) * p)

    bg = int(44 + (102 - 44) * p)

    bb = int(44 + (102 - 44) * p)

    border_col = QColor(br, bg, bb)



    # Base background

    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(bg_col)

    painter.drawRoundedRect(rect, radius, radius)



    # Radial gradient bloom on hover: scale(0) -> scale(4)

    if p > 0.01:

        clip_path = QPainterPath()

        clip_path.addRoundedRect(rect, radius, radius)

        painter.setClipPath(clip_path)



        cx = rect.center().x()

        cy = rect.center().y()

        max_dim = max(rect.width(), rect.height())

        # Radial radius expands up to 4x

        grad_radius = max_dim * (0.15 + 3.85 * p)



        rad_grad = QRadialGradient(cx, cy, grad_radius)

        # 0%: rgba(255, 255, 255, 0.25 * p)

        # 70%: rgba(255, 255, 255, 0.0)

        center_alpha = int(64 * p)

        rad_grad.setColorAt(0.0, QColor(255, 255, 255, center_alpha))

        rad_grad.setColorAt(0.70, QColor(255, 255, 255, 0))

        rad_grad.setColorAt(1.0, QColor(255, 255, 255, 0))



        painter.setBrush(QBrush(rad_grad))

        painter.setPen(Qt.PenStyle.NoPen)

        painter.drawRect(rect)



        # Restore clip for border drawing

        painter.setClipping(False)



    # 2px border

    border_width = 1.65 if rect.height() < 32 else 2.0

    painter.setPen(QPen(border_col, border_width))

    painter.setBrush(Qt.BrushStyle.NoBrush)

    inset = border_width / 2.0

    painter.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), radius - inset, radius - inset)



    # Crisp white bold text

    painter.setFont(QFont("Segoe UI Variable Text", font_size, QFont.Weight.Bold))

    painter.setPen(QColor(255, 255, 255))

    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)



    painter.restore()





def paint_split_wipe_cancel_button(

    painter: QPainter,

    rect: QRectF,

    text: str = "Cancel",

    hover_progress: float = 0.0,

    theme: str = "dark",

    is_pressed: bool = False,

    font_size: float = 8.2

):

    """

    Renders Uiverse.io by KhaledMatalkah Split-Curtain Wipe Cancel Button:

    - Top half: white block wipes from left (-100% -> 0%)

    - Bottom half: white block wipes from right (+100% -> 0%)

    - Text transitions from white to crisp black on hover

    - Border is subtle resting outline pill

    """

    p = max(0.0, min(1.0, float(hover_progress)))

    painter.save()

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)



    radius = rect.height() / 2.0

    w = rect.width()

    h = rect.height()



    # Base resting border & translucent dark background

    rest_bg = QColor(255, 255, 255, int(12 * (1.0 - p))) if theme != "light" else QColor(0, 0, 0, int(8 * (1.0 - p)))

    rest_border = QColor(255, 255, 255, int(45 * (1.0 - p))) if theme != "light" else QColor(0, 0, 0, int(35 * (1.0 - p)))



    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(rest_bg)

    painter.drawRoundedRect(rect, radius, radius)



    # Clip to rounded pill shape for dual-wipe curtain blocks

    clip_path = QPainterPath()

    clip_path.addRoundedRect(rect, radius, radius)

    painter.setClipPath(clip_path)



    # Dual Split Wipe:

    # 1. Top half (:before) slides in from LEFT (-100% to 0%)

    # x goes from (rect.left() - w) to rect.left()

    top_x = rect.left() - w * (1.0 - p)

    top_rect = QRectF(top_x, rect.top(), w, h / 2.0 + 0.5)



    # 2. Bottom half (:after) slides in from RIGHT (+100% to 0%)

    # x goes from (rect.left() + w) to rect.left()

    bottom_x = rect.left() + w * (1.0 - p)

    bottom_rect = QRectF(bottom_x, rect.top() + h / 2.0 - 0.5, w, h / 2.0 + 0.5)



    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(QColor(255, 255, 255))

    painter.drawRect(top_rect)

    painter.drawRect(bottom_rect)



    # Outline border

    painter.setClipping(False)

    painter.setPen(QPen(rest_border, 0.85))

    painter.setBrush(Qt.BrushStyle.NoBrush)

    painter.drawRoundedRect(rect.adjusted(0.4, 0.4, -0.4, -0.4), radius - 0.4, radius - 0.4)



    # Text color transitions smoothly from white (or dark in light theme) to solid black on hover

    if theme == "light":

        # in light theme, start dark (40,40,45) and stay dark black (0,0,0)

        text_r = int(40 * (1.0 - p))

        text_g = int(40 * (1.0 - p))

        text_b = int(45 * (1.0 - p))

    else:

        # in dark theme: white rgb(240, 240, 245) -> black rgb(0, 0, 0)

        text_r = int(240 * (1.0 - p))

        text_g = int(240 * (1.0 - p))

        text_b = int(245 * (1.0 - p))



    text_col = QColor(text_r, text_g, text_b)

    painter.setFont(QFont("Segoe UI Variable Text", font_size, QFont.Weight.Bold))

    painter.setPen(text_col)

    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)



    painter.restore()





# =========================================================================

# 3. REUSABLE QPUSHBUTTON WIDGETS

# =========================================================================



class RecycleBinClearButton(QPushButton):

    """

    Uiverse.io vinodjangid07 animated clear recycle bin button.

    Resting: 50x50 circle. Hover: expands to 140px width red pill with sliding 'Delete' text.

    """

    def __init__(self, parent=None, on_clear_callback=None):

        super().__init__(parent)

        self._hover_progress = 0.0

        self._on_clear_callback = on_clear_callback

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setFixedSize(50, 50)

        self.setStyleSheet("background: transparent; border: none;")



        self._anim_timer = QTimer(self)

        self._anim_timer.setInterval(16)

        self._anim_timer.timeout.connect(self._on_anim_step)

        self._target_progress = 0.0



        if on_clear_callback:

            self.clicked.connect(on_clear_callback)



    def enterEvent(self, event):

        self._target_progress = 1.0

        if not self._anim_timer.isActive():

            self._anim_timer.start()

        super().enterEvent(event)



    def leaveEvent(self, event):

        self._target_progress = 0.0

        if not self._anim_timer.isActive():

            self._anim_timer.start()

        super().leaveEvent(event)



    def _on_anim_step(self):

        diff = self._target_progress - self._hover_progress

        if abs(diff) < 0.02:

            self._hover_progress = self._target_progress

            self._anim_timer.stop()

        else:

            self._hover_progress += diff * 0.22



        # Dynamically expand width: 50px -> 140px

        cur_w = int(50 + 90 * self._hover_progress)

        if self.width() != cur_w:

            self.setFixedWidth(cur_w)

        self.update()



    def paintEvent(self, event):

        painter = QPainter(self)

        rect = QRectF(0, 0, self.width(), self.height())

        paint_recycle_bin_clear_button(painter, rect, self._hover_progress, "Delete", self.isDown())





class BotonEleganteButton(QPushButton):

    """

    Uiverse.io iZOXVL .boton-elegante button for reminder / overlay actions.

    Pill with radial gradient blooming on hover.

    """

    def __init__(self, text: str = "Done", parent=None, font_size: float = 8.5):

        super().__init__(text, parent)

        self._font_size = font_size

        self._hover_progress = 0.0

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setStyleSheet("background: transparent; border: none;")



        self._anim_timer = QTimer(self)

        self._anim_timer.setInterval(16)

        self._anim_timer.timeout.connect(self._on_anim_step)

        self._target_progress = 0.0



    def enterEvent(self, event):

        self._target_progress = 1.0

        if not self._anim_timer.isActive():

            self._anim_timer.start()

        super().enterEvent(event)



    def leaveEvent(self, event):

        self._target_progress = 0.0

        if not self._anim_timer.isActive():

            self._anim_timer.start()

        super().leaveEvent(event)



    def _on_anim_step(self):

        diff = self._target_progress - self._hover_progress

        if abs(diff) < 0.02:

            self._hover_progress = self._target_progress

            self._anim_timer.stop()

        else:

            self._hover_progress += diff * 0.20

        self.update()



    def paintEvent(self, event):

        painter = QPainter(self)

        rect = QRectF(0, 0, self.width(), self.height())

        paint_boton_elegante(painter, rect, self.text(), self._hover_progress, "dark", self.isDown(), self._font_size)





class SplitWipeCancelButton(QPushButton):

    """

    Uiverse.io KhaledMatalkah dual split-curtain wipe Cancel button.

    Top half wipes left, bottom half wipes right, text inverts to black.

    """

    def __init__(self, text: str = "Cancel", parent=None, font_size: float = 8.2):

        super().__init__(text, parent)

        self._font_size = font_size

        self._hover_progress = 0.0

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setStyleSheet("background: transparent; border: none;")



        self._anim_timer = QTimer(self)

        self._anim_timer.setInterval(16)

        self._anim_timer.timeout.connect(self._on_anim_step)

        self._target_progress = 0.0



    def enterEvent(self, event):

        self._target_progress = 1.0

        if not self._anim_timer.isActive():

            self._anim_timer.start()

        super().enterEvent(event)



    def leaveEvent(self, event):

        self._target_progress = 0.0

        if not self._anim_timer.isActive():

            self._anim_timer.start()

        super().leaveEvent(event)



    def _on_anim_step(self):

        diff = self._target_progress - self._hover_progress

        if abs(diff) < 0.02:

            self._hover_progress = self._target_progress

            self._anim_timer.stop()

        else:

            self._hover_progress += diff * 0.20

        self.update()



    def paintEvent(self, event):

        painter = QPainter(self)

        rect = QRectF(0, 0, self.width(), self.height())

        paint_split_wipe_cancel_button(painter, rect, self.text(), self._hover_progress, "dark", self.isDown(), self._font_size)





# =========================================================================

# 4. REFINED 3-TIER BUTTON SYSTEM (Primary, Secondary, Tertiary)

# =========================================================================



class ButtonType(Enum):

    PRIMARY   = auto()  # White filled, main action

    SECONDARY = auto()  # Elevated dark surface (#171719), supporting action

    TERTIARY  = auto()  # Text only, low-priority action





def paint_primary_button(

    painter: QPainter,

    rect: QRectF,

    text: str,

    hover_progress: float = 0.0,

    is_pressed: bool = False,

    font_size: float = 11.0

):

    """

    Primary Button:

    - Pure white filled surface (#FFFFFF)

    - Solid dark text (#101012)

    - Hover: subtle warmth (#EBEBEE)

    - Press: slight scale/darkening, zero unnecessary gradient

    """

    p = max(0.0, min(1.0, float(hover_progress)))

    painter.save()

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)



    radius = rect.height() / 2.0

    

    # Scale slightly on press

    draw_rect = rect

    if is_pressed:

        draw_rect = rect.adjusted(1.0, 1.0, -1.0, -1.0)



    # Color interpolation: #FFFFFF -> #EBEBEE

    val = int(255 - 15 * p)

    bg_col = QColor(val, val, val) if not is_pressed else QColor(220, 220, 225)



    painter.setPen(Qt.PenStyle.NoPen)

    painter.setBrush(bg_col)

    painter.drawRoundedRect(draw_rect, radius, radius)



    # Dark text

    painter.setFont(QFont("Segoe UI Variable Text", font_size, QFont.Weight.DemiBold))

    painter.setPen(QColor(16, 16, 18))

    painter.drawText(draw_rect, Qt.AlignmentFlag.AlignCenter, text)

    painter.restore()





def paint_secondary_button(

    painter: QPainter,

    rect: QRectF,

    text: str,

    hover_progress: float = 0.0,

    is_pressed: bool = False,

    font_size: float = 11.0

):

    """

    Secondary Button:

    - Elevated dark surface (#171719)

    - Subtle 7% white border (BORDER_SUBTLE)

    - Hover: #202023 with 16% active border (BORDER_ACTIVE)

    - Text: 94% white (PRIMARY_TEXT)

    """

    p = max(0.0, min(1.0, float(hover_progress)))

    painter.save()

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)



    radius = rect.height() / 2.0

    draw_rect = rect

    if is_pressed:

        draw_rect = rect.adjusted(1.0, 1.0, -1.0, -1.0)



    # Pure solid AMOLED black (#0E0E0F) with #292929 border
    v = int(14 + 10 * p)
    bg_col = QColor(v, v, v + 1, 255)
    b_v = int(41 + 14 * p)
    border_col = QColor(b_v, b_v, b_v, 255)

    path = QPainterPath()
    path.addRoundedRect(draw_rect, radius, radius)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg_col)
    painter.fillPath(path, QBrush(bg_col))

    # Subtle upper edge specular highlight
    spec_h = min(2.5, draw_rect.height() * 0.15)
    specular = QLinearGradient(0, draw_rect.top(), 0, draw_rect.top() + spec_h)
    specular.setColorAt(0.0, QColor(255, 255, 255, int(18 + 8 * p)))
    specular.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(path, QBrush(specular))

    painter.setPen(QPen(border_col, 0.85))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.strokePath(path, QPen(border_col, 0.85))

    # White 94% text

    painter.setFont(QFont("Segoe UI Variable Text", font_size, QFont.Weight.Medium))

    painter.setPen(QColor(255, 255, 255, 240))

    painter.drawText(draw_rect, Qt.AlignmentFlag.AlignCenter, text)

    painter.restore()





def paint_tertiary_button(

    painter: QPainter,

    rect: QRectF,

    text: str,

    hover_progress: float = 0.0,

    is_pressed: bool = False,

    font_size: float = 11.0

):

    """

    Tertiary Button:

    - Text-only with zero resting background

    - Hover: subtle #171719 elevated wash

    - Text: White 58% resting -> White 94% on hover

    """

    p = max(0.0, min(1.0, float(hover_progress)))

    painter.save()

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)



    radius = rect.height() / 2.0

    draw_rect = rect

    if is_pressed:

        draw_rect = rect.adjusted(1.0, 1.0, -1.0, -1.0)



    if p > 0.01:

        # Subtle hover wash

        bg_col = QColor(255, 255, 255, int(18 * p))

        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(bg_col)

        painter.drawRoundedRect(draw_rect, radius, radius)



    # Text alpha interpolation: 58% (148) -> 94% (240)

    t_alpha = int(148 + 92 * p)

    painter.setFont(QFont("Segoe UI Variable Text", font_size, QFont.Weight.Medium))

    painter.setPen(QColor(255, 255, 255, t_alpha))

    painter.drawText(draw_rect, Qt.AlignmentFlag.AlignCenter, text)

    painter.restore()





class ODDButton(QPushButton):

    """

    Refined ODD Button component supporting PRIMARY, SECONDARY, and TERTIARY tiers.

    Features smooth tactile spring transitions, zero excessive decoration.

    """

    def __init__(self, text: str = "", button_type: ButtonType = ButtonType.SECONDARY, parent=None, font_size: float = 11.0):

        super().__init__(text, parent)

        self.button_type = button_type

        self.font_size = font_size

        self._hover_progress = 0.0

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setStyleSheet("background: transparent; border: none;")



        self._anim_timer = QTimer(self)

        self._anim_timer.setInterval(16)

        self._anim_timer.timeout.connect(self._on_anim_step)

        self._target_progress = 0.0



    def enterEvent(self, event):

        self._target_progress = 1.0

        if not self._anim_timer.isActive():

            self._anim_timer.start()

        super().enterEvent(event)



    def leaveEvent(self, event):

        self._target_progress = 0.0

        if not self._anim_timer.isActive():

            self._anim_timer.start()

        super().leaveEvent(event)



    def _on_anim_step(self):

        diff = self._target_progress - self._hover_progress

        if abs(diff) < 0.02:

            self._hover_progress = self._target_progress

            self._anim_timer.stop()

        else:

            self._hover_progress += diff * 0.24

        self.update()



    def paintEvent(self, event):

        painter = QPainter(self)

        rect = QRectF(0, 0, self.width(), self.height())

        if self.button_type == ButtonType.PRIMARY:

            paint_primary_button(painter, rect, self.text(), self._hover_progress, self.isDown(), self.font_size)

        elif self.button_type == ButtonType.SECONDARY:

            paint_secondary_button(painter, rect, self.text(), self._hover_progress, self.isDown(), self.font_size)

        else:

            paint_tertiary_button(painter, rect, self.text(), self._hover_progress, self.isDown(), self.font_size)

