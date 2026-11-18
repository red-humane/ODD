"""

ODD Physics-Based Motion System & Apple Dynamic Island Motion Engine

Implements tactile, liquid surface-tension physics for Windows:

- 1. Fluid Morphing (anti-jerk damped springs, pill radius r=h/2, perpendicular squash)

- 2. Splitting and Merging (analytic metaball cubic Bezier neck with hysteresis)

- 3. Bouncing and Easing (semi-implicit 240Hz integrator, tunable presets, velocity preservation)

- 4. Apple Intelligence Style Ripple (clone-and-mask, radial gradient ring, screen/plus blend)

- 5. Odometer Rotary Digit Roll (cached glyph strip, clipped translation)

- 6. Unified MotionClock (zero idle CPU when settled)

"""



import math

import time

from typing import Dict, List, Optional, Tuple, Callable

from enum import Enum, auto



from PySide6.QtCore import QObject, QTimer, Signal, QPointF, QRectF, QSize, Qt, QRect

from PySide6.QtGui import (

    QPainter, QPainterPath, QColor, QBrush, QPen, QPixmap, QImage,

    QRadialGradient, QLinearGradient, QFont, QFontMetrics, QRegion

)

from PySide6.QtWidgets import QWidget, QApplication



from odd_crash_capture import log_breadcrumb, logger, safe_slot





# =========================================================================

# 1. Physics Spring Presets & 240Hz Semi-Implicit Integrator

# =========================================================================



class SpringPreset:

    """Tunable physical spring preset defining harmonic behavior"""

    def __init__(self, name: str, response: float, damping_ratio: float, mass: float = 1.0):

        self.name = name

        self.response = max(0.05, float(response))          # Duration in seconds to target

        self.damping_ratio = max(0.1, float(damping_ratio))  # <1.0 = bouncy overshoot, 1.0 = critical

        self.mass = max(0.01, float(mass))



    def copy(self) -> "SpringPreset":

        return SpringPreset(self.name, self.response, self.damping_ratio, self.mass)





# Default Tunable Presets

PRESET_SNAPPY = SpringPreset("SNAPPY", response=0.26, damping_ratio=0.72)  # Open / Close

PRESET_LIQUID = SpringPreset("LIQUID", response=0.36, damping_ratio=0.68)  # Morph / Split / Merge

PRESET_SOFT   = SpringPreset("SOFT",   response=0.46, damping_ratio=0.82)  # Popups & Notifications

PRESET_GENTLE = SpringPreset("GENTLE", response=0.62, damping_ratio=0.96)  # Idle Breathing & Subtle settles





class Spring:

    """

    Second-Order Physical Damped Harmonic Oscillator with Velocity Preservation (Anti-Jerk).

    Uses a fixed-timestep 240 Hz semi-implicit Euler integrator accumulated per frame.

    Stable at any display refresh rate and during slow frame drops.

    """

    def __init__(self, initial_value: float = 0.0, preset: Optional[SpringPreset] = None):

        self.value: float = float(initial_value)

        self.target: float = float(initial_value)

        self.velocity: float = 0.0

        self.preset = (preset or PRESET_LIQUID).copy()

        self._recompute_constants()



    def _recompute_constants(self):

        # k = m * (2*pi / response)^2

        self.stiffness = self.preset.mass * (2.0 * math.pi / self.preset.response) ** 2

        # c = 2 * damping_ratio * sqrt(k * m)

        self.damping = 2.0 * self.preset.damping_ratio * math.sqrt(self.stiffness * self.preset.mass)



    def set_preset(self, preset: SpringPreset):

        self.preset = preset.copy()

        self._recompute_constants()



    def retarget(self, new_target: float, preserve_velocity: bool = True, preset: Optional[SpringPreset] = None):

        """

        Anti-Jerk: Retargeting preserves current value and velocity mid-flight.

        No abrupt snapping or restart.

        """

        self.target = float(new_target)

        if preset is not None:

            self.set_preset(preset)

        if not preserve_velocity:

            self.velocity = 0.0



    def snap_to(self, value: float):

        """Teleports directly to target with zero momentum."""

        self.value = float(value)

        self.target = float(value)

        self.velocity = 0.0



    def update(self, dt: float) -> float:

        """

        Advances spring physics by dt seconds using fixed-step 240 Hz substeps.

        """

        if self.is_settled():

            self.value = self.target

            self.velocity = 0.0

            return self.value



        # Cap dt to avoid huge steps on system hiccups

        dt_clamped = min(0.06, max(0.0001, dt))



        # Check performance tier to adapt substep budget

        try:

            from odd_tier import TierManager

            tier = TierManager.get_instance().tier

            substep_hz = 120.0 if tier == 0 else 240.0

        except Exception:

            substep_hz = 240.0



        sub_dt = 1.0 / substep_hz

        num_substeps = max(1, min(12, int(dt_clamped * substep_hz) + 1))

        actual_sub_dt = dt_clamped / num_substeps



        for _ in range(num_substeps):

            displacement = self.value - self.target

            spring_force = -self.stiffness * displacement

            damping_force = -self.damping * self.velocity

            acceleration = (spring_force + damping_force) / self.preset.mass



            # Semi-implicit Euler integration

            self.velocity += acceleration * actual_sub_dt

            self.value += self.velocity * actual_sub_dt



        # Settle check

        if abs(self.value - self.target) < 0.002 and abs(self.velocity) < 0.02:

            self.value = self.target

            self.velocity = 0.0



        return self.value



    def is_settled(self, dist_eps: float = 0.002, vel_eps: float = 0.02) -> bool:

        return abs(self.value - self.target) <= dist_eps and abs(self.velocity) <= vel_eps





# =========================================================================

# 2. Capsule State Machine & MotionState

# =========================================================================



class CapsuleMode(Enum):

    IDLE = auto()           # Sleek 240x40 pill

    SEARCH = auto()         # 480x56 search input

    RESULTS = auto()        # 480x(56 + results)

    MEDIA = auto()          # 380x64 media bar

    POPUP = auto()          # 340x60 volume/brightness popup

    QUICK_SETTINGS = auto() # 360x280 control center

    SPLIT = auto()          # Two concurrent activities separated by liquid neck





class MotionState:

    """

    Manages the coupled physical parameters of the primary capsule and secondary bubble.

    Enforces surface tension squashing (perpendicular compression on fast stretch),

    pill corner radius ($r = h/2$), and split/merge hysteresis.

    """

    def __init__(self):

        # Primary body springs

        self.spring_x = Spring(0.0, PRESET_SNAPPY)

        self.spring_y = Spring(0.0, PRESET_SNAPPY)

        self.spring_w = Spring(240.0, PRESET_LIQUID)

        self.spring_h = Spring(40.0, PRESET_LIQUID)

        self.spring_squash = Spring(0.0, PRESET_LIQUID)



        # Secondary bubble springs (for concurrent activities)

        self.spring_x2 = Spring(0.0, PRESET_LIQUID)

        self.spring_y2 = Spring(0.0, PRESET_LIQUID)

        self.spring_w2 = Spring(44.0, PRESET_LIQUID)

        self.spring_h2 = Spring(44.0, PRESET_LIQUID)



        # Split / Merge hysteresis thresholds

        self.is_split: bool = False

        self.split_dist_threshold: float = 24.0   # Must separate >24px to snap neck

        self.merge_dist_threshold: float = 16.0   # Must approach <16px to fuse neck

        self.neck_tension: float = 0.65



        self.current_mode: CapsuleMode = CapsuleMode.IDLE

        self._last_w = 240.0



    def update(self, dt: float) -> bool:

        """Updates all springs. Returns True if any spring is still moving."""

        moving = False

        for s in (self.spring_x, self.spring_y, self.spring_w, self.spring_h, self.spring_squash,

                  self.spring_x2, self.spring_y2, self.spring_w2, self.spring_h2):

            s.update(dt)

            if not s.is_settled():

                moving = True



        # Calculate dynamic squash from horizontal velocity

        dw = abs(self.spring_w.velocity)

        squash_target = min(1.0, dw / 1200.0)

        self.spring_squash.retarget(squash_target, preserve_velocity=True)



        # Check split/merge hysteresis

        if self.current_mode == CapsuleMode.SPLIT:

            dist = abs((self.spring_x2.value) - (self.spring_x.value + self.spring_w.value))

            if not self.is_split and dist > self.split_dist_threshold:

                self.is_split = True

                try:

                    import odd_audio

                    odd_audio.AudioEventBus.get_instance().on_capsule_split()

                except Exception:

                    pass

            elif self.is_split and dist < self.merge_dist_threshold:

                self.is_split = False

                try:

                    import odd_audio

                    odd_audio.AudioEventBus.get_instance().on_capsule_merge()

                except Exception:

                    pass



        return moving



    def is_all_settled(self) -> bool:

        return (

            self.spring_x.is_settled() and

            self.spring_y.is_settled() and

            self.spring_w.is_settled() and

            self.spring_h.is_settled() and

            self.spring_squash.is_settled() and

            self.spring_x2.is_settled() and

            self.spring_y2.is_settled() and

            self.spring_w2.is_settled() and

            self.spring_h2.is_settled()

        )



    def get_primary_geometry(self) -> Tuple[float, float, float, float, float]:

        """

        Returns (x, y, w, h, corner_radius) with perpendicular squash applied.

        Pill rule: corner_radius = effective_height / 2.0 at every single frame.

        """

        w = max(40.0, self.spring_w.value)

        h = max(24.0, self.spring_h.value)

        squash = self.spring_squash.value



        # Perpendicular compression (compress height by up to 5% during fast horizontal stretch)

        eff_h = h * (1.0 - squash * 0.05)

        eff_y = self.spring_y.value + (h - eff_h) / 2.0

        eff_x = self.spring_x.value

        r = eff_h / 2.0

        return eff_x, eff_y, w, eff_h, r



    def get_secondary_geometry(self) -> Tuple[float, float, float, float, float]:

        w2 = max(20.0, self.spring_w2.value)

        h2 = max(20.0, self.spring_h2.value)

        r2 = h2 / 2.0

        return self.spring_x2.value, self.spring_y2.value, w2, h2, r2





# =========================================================================

# 3. Analytic Metaball Neck & Island Shape Painter

# =========================================================================



class IslandShapePainter:

    """

    Renders the unified liquid Dynamic Island body using analytic cubic Beziers.

    Fills the primary pill, secondary bubble, and stretching liquid neck into ONE

    closed QPainterPath with zero shaders, zero blur effects, and pre-rendered shadow.

    """

    @staticmethod

    def build_liquid_path(

        x1: float, y1: float, w1: float, h1: float, r1: float,

        x2: float, y2: float, w2: float, h2: float, r2: float,

        is_active_secondary: bool = False,

        tension: float = 0.65

    ) -> QPainterPath:

        path = QPainterPath()

        rect1 = QRectF(x1, y1, w1, h1)

        path.addRoundedRect(rect1, r1, r1)



        if not is_active_secondary:

            return path



        rect2 = QRectF(x2, y2, w2, h2)

        path.addRoundedRect(rect2, r2, r2)



        # Center points of the two adjacent circular caps

        c1 = QPointF(x1 + w1 - r1, y1 + r1)

        c2 = QPointF(x2 + r2, y2 + r2)



        dx = c2.x() - c1.x()

        dy = c2.y() - c1.y()

        dist = math.hypot(dx, dy)

        d_touch = r1 + r2

        d_snap = d_touch * 2.5



        # If within stretching surface-tension distance, bridge them with liquid neck

        if dist < d_snap:

            angle = math.atan2(dy, dx)

            progress = max(0.0, (dist - d_touch) / max(0.001, d_snap - d_touch))



            spread = (math.pi * 0.42) * (1.0 - progress * 0.48)

            p1_top = QPointF(c1.x() + r1 * math.cos(angle + spread), c1.y() + r1 * math.sin(angle + spread))

            p1_bot = QPointF(c1.x() + r1 * math.cos(angle - spread), c1.y() + r1 * math.sin(angle - spread))

            p2_top = QPointF(c2.x() + r2 * math.cos(angle + math.pi - spread), c2.y() + r2 * math.sin(angle + math.pi - spread))

            p2_bot = QPointF(c2.x() + r2 * math.cos(angle - math.pi + spread), c2.y() + r2 * math.sin(angle - math.pi + spread))



            mid_x = (c1.x() + c2.x()) / 2.0

            mid_y = (c1.y() + c2.y()) / 2.0



            waist_scale = max(0.0, (1.0 - progress) ** 1.7)

            waist_r = ((r1 + r2) / 2.0) * waist_scale * tension



            perp_x = -math.sin(angle)

            perp_y = math.cos(angle)

            c_top = QPointF(mid_x + perp_x * waist_r, mid_y + perp_y * waist_r)

            c_bot = QPointF(mid_x - perp_x * waist_r, mid_y - perp_y * waist_r)



            handle_len = (dist / 2.0) * 0.52

            h1_top = QPointF(p1_top.x() + math.cos(angle) * handle_len, p1_top.y() + math.sin(angle) * handle_len)

            h2_top = QPointF(p2_top.x() - math.cos(angle) * handle_len, p2_top.y() - math.sin(angle) * handle_len)

            h1_bot = QPointF(p1_bot.x() + math.cos(angle) * handle_len, p1_bot.y() + math.sin(angle) * handle_len)

            h2_bot = QPointF(p2_bot.x() - math.cos(angle) * handle_len, p2_bot.y() - math.sin(angle) * handle_len)



            neck = QPainterPath()

            neck.moveTo(p1_top)

            neck.cubicTo(h1_top, c_top, p2_top)

            neck.lineTo(p2_bot)

            neck.cubicTo(h2_bot, c_bot, p1_bot)

            neck.closeSubpath()



            # Fuse neck and bodies into one unified liquid manifold

            path = path.united(neck)



        return path





class ShadowCache:

    """

    Pre-renders and caches 9-slice drop shadow pixmaps.

    Eliminates all per-frame QGraphicsDropShadowEffect overhead at 60 FPS.

    """

    _cache: Dict[Tuple[int, int, int, str], QPixmap] = {}



    @classmethod

    def get_shadow(cls, w: int, h: int, radius: int, color_hex: str = "#000000", blur_radius: int = 16) -> QPixmap:

        key = (w, h, radius, color_hex)

        if key in cls._cache:

            return cls._cache[key]



        pad = blur_radius * 2

        pix = QPixmap(w + pad * 2, h + pad * 2)

        pix.fill(Qt.GlobalColor.transparent)



        painter = QPainter(pix)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)



        # Soft layered alpha radial steps

        for step in range(blur_radius, 0, -2):

            alpha = int(45 * (1.0 - step / blur_radius) ** 1.8)

            col = QColor(0, 0, 0, alpha)

            painter.setPen(Qt.PenStyle.NoPen)

            painter.setBrush(QBrush(col))

            s_rect = QRectF(pad - step, pad - step + 3.0, w + step * 2, h + step * 2)

            r = radius + step

            painter.drawRoundedRect(s_rect, r, r)



        painter.end()



        # Bounded LRU cache

        if len(cls._cache) > 40:

            cls._cache.pop(next(iter(cls._cache)))

        cls._cache[key] = pix

        return pix





# =========================================================================

# 4. Apple Intelligence Style Ripple (Clone-and-Mask, No Shaders)

# =========================================================================



class RippleEffect:

    """

    Translates the Apple Intelligence liquid ripple into Qt via Clone-and-Mask:

    - Grabs snapshot of the capsule content into an offscreen QPixmap.

    - Applies expanding QRadialGradient ring mask with soft inner/outer falloff.

    - Blends back over the original with CompositionMode_Screen / Plus at 1.00 -> 1.03 scale.

    - Sweeps subtle accent glow and rim-light along the perimeter.

    - Zero shaders, zero OpenGL dependency, restricted entirely to the capsule bounding box.

    """

    def __init__(self):

        self.is_active = False

        self.center = QPointF(0.0, 0.0)

        self.max_radius = 280.0

        self.current_radius = 0.0

        self.duration = 0.58  # 580ms

        self.t_start = 0.0

        self.accent_color = QColor(255, 255, 255, 180)

        self.snapshot_pixmap: Optional[QPixmap] = None

        self._mask_pixmap: Optional[QPixmap] = None



    def trigger(self, widget: QWidget, center_point: QPointF, accent_color: Optional[QColor] = None, duration_ms: float = 580.0):

        try:

            # Respect tier

            from odd_tier import TierManager

            if not TierManager.get_instance().enable_gooey_effects:

                return

        except Exception:

            pass



        self.center = center_point

        self.accent_color = accent_color or QColor(255, 255, 255, 180)

        self.duration = max(0.2, duration_ms / 1000.0)

        self.t_start = time.perf_counter()

        self.current_radius = 0.0



        # Snapshot current capsule visual content

        dpr = widget.devicePixelRatio()

        self.snapshot_pixmap = widget.grab()

        self.is_active = True



        # Pre-allocate offscreen buffer sized to widget

        w, h = widget.width(), widget.height()

        if w > 0 and h > 0:

            self._mask_pixmap = QPixmap(w, h)



        # Notify audio system

        try:

            import odd_audio

            odd_audio.AudioEventBus.get_instance().on_ripple_start(intensity=1.0)

        except Exception:

            pass



    def update(self) -> bool:

        """Advances ripple animation. Returns True while active."""

        if not self.is_active:

            return False



        now = time.perf_counter()

        elapsed = now - self.t_start

        p = elapsed / self.duration



        if p >= 1.0:

            self.is_active = False

            self.snapshot_pixmap = None

            self._mask_pixmap = None

            return False



        # Ease-out expansion: quick burst outward, slowing near perimeter

        self.current_radius = self.max_radius * (1.0 - (1.0 - p) ** 2.2)

        return True



    def paint(self, painter: QPainter, bounds: QRectF):

        if not self.is_active or self.snapshot_pixmap is None or self._mask_pixmap is None:

            return



        w = int(bounds.width())

        h = int(bounds.height())

        if w <= 0 or h <= 0:

            return



        now = time.perf_counter()

        p = min(1.0, (now - self.t_start) / self.duration)

        alpha_fade = max(0.0, 1.0 - p ** 1.4)



        # Ring band width widens as it travels outward

        ring_r = self.current_radius

        band_width = 30.0 + 55.0 * p



        # 1. Prepare offscreen gradient ring mask

        self._mask_pixmap.fill(Qt.GlobalColor.transparent)

        mask_painter = QPainter(self._mask_pixmap)

        mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing)



        grad = QRadialGradient(self.center, ring_r + band_width / 2.0)

        inner_norm = max(0.0, (ring_r - band_width / 2.0) / max(1.0, ring_r + band_width / 2.0))

        peak_norm = max(0.0, ring_r / max(1.0, ring_r + band_width / 2.0))



        grad.setColorAt(0.0, QColor(0, 0, 0, 0))

        if inner_norm > 0.0:

            grad.setColorAt(inner_norm, QColor(0, 0, 0, 0))

        grad.setColorAt(peak_norm, QColor(0, 0, 0, int(220 * alpha_fade)))

        grad.setColorAt(1.0, QColor(0, 0, 0, 0))



        mask_painter.setPen(Qt.PenStyle.NoPen)

        mask_painter.setBrush(QBrush(grad))

        mask_painter.drawRect(0, 0, w, h)



        # 2. Apply DestinationIn: carve out the clone content under the ring mask

        mask_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)

        scaled_clone = self.snapshot_pixmap.scaled(

            int(w * 1.025), int(h * 1.025),

            Qt.AspectRatioMode.IgnoreAspectRatio,

            Qt.TransformationMode.SmoothTransformation

        )

        # Center the slight 1.025x scale-up

        ox = int((w - scaled_clone.width()) / 2.0)

        oy = int((h - scaled_clone.height()) / 2.0)

        mask_painter.drawPixmap(ox, oy, scaled_clone)

        mask_painter.end()



        # 3. Composite the masked ripple clone over the original using Screen blend

        painter.save()

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)

        painter.drawPixmap(0, 0, self._mask_pixmap)



        # 4. Soft accent glow band & rim specular

        glow_grad = QRadialGradient(self.center, ring_r + 14.0)

        glow_col = QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), int(65 * alpha_fade))

        glow_grad.setColorAt(0.0, QColor(0, 0, 0, 0))

        glow_grad.setColorAt(max(0.0, (ring_r - 8.0) / (ring_r + 14.0)), QColor(0, 0, 0, 0))

        glow_grad.setColorAt(ring_r / (ring_r + 14.0), glow_col)

        glow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))



        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QBrush(glow_grad))

        painter.drawRect(bounds)

        painter.restore()





# =========================================================================

# 5. Odometer Rotary Digit Roll Widget

# =========================================================================



class OdometerDigitWidget(QWidget):

    """

    Smooth vertical sliding rotary digit wheel (Apple watchOS / Dynamic Island style).

    Clipped viewport sliding over a single cached vertical glyph strip ('0'-'9').

    Animates with spring physics. Zero widget recreations per number change.

    """

    def __init__(self, font_size: int = 14, font_weight: QFont.Weight = QFont.Weight.Medium, text_color: QColor = QColor(255, 255, 255), parent=None):

        super().__init__(parent)

        self.font_size = font_size

        self.font = QFont("Segoe UI Variable Display", font_size, font_weight)

        self.text_color = text_color

        self._current_digit = 0

        self.spring_y = Spring(0.0, PRESET_SNAPPY)



        fm = QFontMetrics(self.font)

        self.digit_h = fm.height()

        self.digit_w = fm.horizontalAdvance("8")

        self.setFixedSize(self.digit_w + 2, self.digit_h)



        # Pre-render vertical strip '0' through '9'

        self._strip_pixmap = QPixmap(self.digit_w + 2, self.digit_h * 10)

        self._strip_pixmap.fill(Qt.GlobalColor.transparent)

        p = QPainter(self._strip_pixmap)

        p.setFont(self.font)

        p.setPen(self.text_color)

        for d in range(10):

            r = QRectF(0, d * self.digit_h, self.digit_w + 2, self.digit_h)

            p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(d))

        p.end()



    def set_digit(self, digit: int, animate: bool = True):

        d = max(0, min(9, int(digit)))

        if d != self._current_digit:

            self._current_digit = d

            target_y = float(d * self.digit_h)

            if animate:

                self.spring_y.retarget(target_y, preserve_velocity=True)

                MotionClock.get_instance().register_spring(self.spring_y, self.update)

                try:

                    import odd_audio

                    odd_audio.AudioEventBus.get_instance().on_odometer_tick()

                except Exception:

                    pass

            else:

                self.spring_y.snap_to(target_y)

                self.update()



    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)



        # Clip inside single-digit viewport

        painter.setClipRect(0, 0, self.width(), self.height())

        y_offset = -self.spring_y.value

        painter.drawPixmap(0, int(y_offset), self._strip_pixmap)





# =========================================================================

# 6. Unified Motion Clock (Single 60FPS Refresh Engine, Zero Idle CPU)

# =========================================================================



class MotionClock(QObject):

    """

    ONE Shared Animation Clock for ODD.

    Drives all active Springs, the Ripple effect, Odometer rolls, and Island morphing.

    Stops completely when all springs settle -> 0.0% CPU at idle.

    """

    _instance = None

    tick = Signal(float)  # dt in seconds



    @classmethod

    def get_instance(cls) -> "MotionClock":

        if cls._instance is None:

            cls._instance = MotionClock()

        return cls._instance



    def __init__(self):

        super().__init__()

        self.timer = QTimer(self)

        

        # High refresh display rate adaptation (60Hz default, 120Hz capable)

        interval = 16

        try:

            screen = QApplication.primaryScreen()

            if screen and screen.refreshRate() > 60:

                interval = max(8, int(1000.0 / min(120, int(screen.refreshRate()))))

        except Exception:

            interval = 16



        self.timer.setInterval(interval)

        self.timer.timeout.connect(self._on_tick)



        self._last_time: Optional[float] = None

        self._active_springs: List[Tuple[Spring, Callable[[], None]]] = []

        self._registered_updaters: List[Callable[[float], bool]] = []

        self._is_running = False



    def register_spring(self, spring: Spring, on_update: Callable[[], None]):

        """Registers a spring to be stepped by the master clock."""

        for s, _ in self._active_springs:

            if s is spring:

                return

        self._active_springs.append((spring, on_update))

        self.start()



    def register_updater(self, updater: Callable[[float], bool]):

        """Registers a custom update callback (e.g. MotionState, Ripple)."""

        if updater not in self._registered_updaters:

            self._registered_updaters.append(updater)

        self.start()



    def start(self):

        if not self.timer.isActive():

            self._last_time = time.perf_counter()

            self._is_running = True

            self.timer.start()



    def stop(self):

        if self.timer.isActive():

            self.timer.stop()

        self._is_running = False

        self._last_time = None



    def _on_tick(self):

        now = time.perf_counter()

        if self._last_time is None:

            self._last_time = now

            return



        dt = min(0.05, now - self._last_time)

        self._last_time = now



        # Feed frame timing to adaptive tier manager

        try:

            from odd_tier import TierManager

            TierManager.get_instance().record_frame_time(dt * 1000.0)

        except Exception:

            pass



        still_moving = False



        # 1. Update standalone springs

        retained = []

        for spring, callback in self._active_springs:

            spring.update(dt)

            try:

                callback()

            except Exception:

                pass

            if not spring.is_settled():

                still_moving = True

                retained.append((spring, callback))

        self._active_springs = retained



        # 2. Update registered motion updaters (MotionState, Ripple, etc.)

        retained_updaters = []

        for upd in self._registered_updaters:

            try:

                active = upd(dt)

                if active:

                    still_moving = True

                    retained_updaters.append(upd)

            except Exception:

                pass

        self._registered_updaters = retained_updaters



        # Emit tick signal

        self.tick.emit(dt)



        # If everything has settled, stop clock completely -> 0% CPU!

        if not still_moving and len(self._active_springs) == 0 and len(self._registered_updaters) == 0:

            self.stop()





# =========================================================================


# =========================================================================
# 7. Motion Intelligence & Apple Spatial Layer Integration (PEP 562)
# =========================================================================

def __getattr__(name: str):
    import odd_motion_intelligence
    if hasattr(odd_motion_intelligence, name):
        return getattr(odd_motion_intelligence, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
