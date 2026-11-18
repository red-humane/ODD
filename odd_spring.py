"""
Physics-Based Spring Animation Engine & Vector Metaball Liquid-Goo Bridge for ODD (Dynamic Island)
- Damped Harmonic Oscillator with Mass, Stiffness, Damping Ratio (CASpringAnimation fidelity)
- Velocity Preservation ("Anti-Jerk" System) ensuring seamless momentum across animation interruptions
- Vector Metaball Liquid-Goo generator creating digital droplet bridges with high surface tension and snap
"""

import math
import time
from typing import Dict, Optional, Tuple, Callable
from PySide6.QtCore import QObject, QTimer, Signal, QPointF, QRectF
from PySide6.QtGui import QPainterPath, QColor, QPainter, QBrush
from PySide6.QtWidgets import QApplication


# Material 3 Expressive Spring Motion Presets (Damping Ratio, Stiffness in N/m)
EXPRESSIVE_SPATIAL_FAST = (0.60, 800.0)      # Rapid overshoot & responsive oscillation
EXPRESSIVE_SPATIAL_DEFAULT = (0.80, 380.0)   # Balanced physical spring expansion
EXPRESSIVE_SPATIAL_SLOW = (0.80, 200.0)      # Smooth relaxed settling
EXPRESSIVE_EFFECTS_FAST = (1.00, 3800.0)     # Critically damped fast effects
EXPRESSIVE_EFFECTS_DEFAULT = (1.00, 1600.0)  # Standard effects
EXPRESSIVE_EFFECTS_SLOW = (1.00, 800.0)      # Gentle effects


class SpringValue:
    """
    Second-order physical spring model with Velocity Preservation (Anti-Jerk).
    Features exact analytical damped harmonic oscillator integration:
    - 100% unconditionally mathematically stable at all timesteps and high stiffnesses.
    - Zero numerical drift, zero Euler explosion, and zero possibility of coordinate overflow.
    - Retains authentic iOS/Dynamic Island natural subtle bounce and fluid momentum blending.
    """
    def __init__(
        self,
        initial_value: float = 0.0,
        response: float = 0.32,      # Approximate duration in seconds to target
        damping_ratio: float = 0.74, # < 1.0 produces natural iOS bounce & overshooting (0.70-0.78 is sweet spot)
        mass: float = 1.0
    ):
        self.value: float = float(initial_value)
        self.target: float = float(initial_value)
        self.velocity: float = 0.0
        self._mass: float = max(0.001, float(mass))
        self._response: float = max(0.05, float(response))
        self._damping_ratio: float = max(0.05, float(damping_ratio))
        self._recompute_constants()

    @property
    def response(self) -> float:
        return self._response

    @response.setter
    def response(self, val: float):
        self._response = max(0.05, float(val))
        self._recompute_constants()

    @property
    def damping_ratio(self) -> float:
        return self._damping_ratio

    @damping_ratio.setter
    def damping_ratio(self, val: float):
        self._damping_ratio = max(0.05, float(val))
        self._recompute_constants()

    @property
    def mass(self) -> float:
        return self._mass

    @mass.setter
    def mass(self, val: float):
        self._mass = max(0.001, float(val))
        self._recompute_constants()

    def _recompute_constants(self):
        # Stiffness (k): related to response time T = 2 * pi * sqrt(m / k)  =>  k = m * (2 * pi / response)^2
        self.stiffness = self._mass * (2.0 * math.pi / self._response) ** 2
        # Critical damping c_crit = 2 * sqrt(k * m)
        # Damping c = damping_ratio * c_crit = 2 * damping_ratio * sqrt(k * m)
        self.damping = 2.0 * self._damping_ratio * math.sqrt(self.stiffness * self._mass)

    def set_config(self, response: Optional[float] = None, damping_ratio: Optional[float] = None):
        if response is not None:
            self._response = max(0.05, float(response))
        if damping_ratio is not None:
            self._damping_ratio = max(0.05, float(damping_ratio))
        self._recompute_constants()

    @classmethod
    def from_expressive(cls, initial_value: float, damping: float, stiffness: float, mass: float = 1.0):
        omega_n = math.sqrt(max(1.0, float(stiffness)) / max(0.001, float(mass)))
        response = (2.0 * math.pi) / omega_n
        return cls(initial_value=initial_value, response=response, damping_ratio=damping, mass=mass)

    def set_expressive_preset(self, damping: float, stiffness: float):
        """Configures the spring using damping ratio and stiffness directly (Material 3 Expressive spec)."""
        omega_n = math.sqrt(max(1.0, float(stiffness)) / self._mass)
        self._response = max(0.05, (2.0 * math.pi) / omega_n)
        self._damping_ratio = max(0.05, float(damping))
        self._recompute_constants()

    def set_target(self, new_target: float, preserve_velocity: bool = True):
        """
        Anti-Jerk System:
        When the target changes midway through flight, we PRESERVE the current velocity.
        The spring seamlessly absorbs the existing physical energy and blends it into the new motion path.
        """
        self.target = float(new_target)
        if not preserve_velocity:
            self.velocity = 0.0

    def snap_to(self, value: float):
        """Instantly teleport to value and cancel momentum."""
        self.value = float(value)
        self.target = float(value)
        self.velocity = 0.0

    def update(self, dt: float) -> float:
        if self.is_settled():
            self.value = self.target
            self.velocity = 0.0
            return self.value

        dt_clamped = min(0.05, max(0.0001, float(dt)))
        omega0 = 2.0 * math.pi / self._response
        zeta = self._damping_ratio
        x0 = self.value - self.target
        v0 = self.velocity
        decay = math.exp(-zeta * omega0 * dt_clamped)

        if zeta < 0.999: # Underdamped (natural subtle overshoot)
            omegad = omega0 * math.sqrt(max(0.0001, 1.0 - zeta * zeta))
            cos_val = math.cos(omegad * dt_clamped)
            sin_val = math.sin(omegad * dt_clamped)
            c2 = (v0 + zeta * omega0 * x0) / omegad
            new_x = decay * (x0 * cos_val + c2 * sin_val)
            new_v = decay * (v0 * cos_val - (zeta * omega0 * v0 + omega0 * omega0 * x0) / omegad * sin_val)
        elif zeta > 1.001: # Overdamped
            omegad = omega0 * math.sqrt(zeta * zeta - 1.0)
            arg = min(30.0, omegad * dt_clamped)
            cosh_val = math.cosh(arg)
            sinh_val = math.sinh(arg)
            c2 = (v0 + zeta * omega0 * x0) / omegad
            new_x = decay * (x0 * cosh_val + c2 * sinh_val)
            new_v = decay * (v0 * cosh_val - (zeta * omega0 * v0 + omega0 * omega0 * x0) / omegad * sinh_val)
        else: # Critically damped
            c2 = v0 + omega0 * x0
            new_x = decay * (x0 + c2 * dt_clamped)
            new_v = decay * (v0 - omega0 * c2 * dt_clamped)

        if math.isnan(new_x) or math.isinf(new_x):
            new_x = 0.0
            new_v = 0.0

        # Physical safety clamp: prevent rogue extreme pixel bounds
        self.value = max(-2000.0, min(10000.0, float(new_x + self.target)))
        self.velocity = max(-20000.0, min(20000.0, float(new_v)))

        # Settle if close enough and nearly zero velocity (supports both 0..1 normalized and pixel springs)
        if abs(self.value - self.target) < 0.002 and abs(self.velocity) < 0.02:
            self.value = self.target
            self.velocity = 0.0

        return self.value

    def is_settled(self, dist_eps: float = 0.002, vel_eps: float = 0.02) -> bool:
        return abs(self.value - self.target) <= dist_eps and abs(self.velocity) <= vel_eps


class SpringEngine(QObject):
    """
    High-precision animation engine driving multiple SpringValues simultaneously at 60+ FPS.
    """
    frame_tick = Signal()
    all_settled = Signal()

    def __init__(self, parent: Optional[QObject] = None, fps: int = 60):
        super().__init__(parent)
        self.springs: Dict[str, SpringValue] = {}
        self.timer = QTimer(self)
        
        # Ultra-smooth high refresh rate adaptation (60Hz baseline, up to 120Hz on gaming displays)
        tick_interval = 16  # 60 FPS baseline (lightweight, zero lag on low-end hardware)
        try:
            screen = QApplication.primaryScreen()
            if screen:
                hz = int(screen.refreshRate())
                if hz > 60:
                    tick_interval = max(8, int(1000.0 / min(120, hz)))
        except Exception:
            pass

        self.timer.setInterval(tick_interval)
        self.timer.timeout.connect(self._on_tick)
        self._last_time: Optional[float] = None
        self._is_active: bool = False

    def add_spring(self, name: str, initial_value: float, response: float = 0.32, damping_ratio: float = 0.74) -> SpringValue:
        sv = SpringValue(initial_value, response, damping_ratio)
        self.springs[name] = sv
        return sv

    def get(self, name: str) -> Optional[SpringValue]:
        return self.springs.get(name)

    def val(self, name: str, default: float = 0.0) -> float:
        sv = self.springs.get(name)
        return sv.value if sv else default

    def set_target(self, name: str, target: float, preserve_velocity: bool = True):
        sv = self.springs.get(name)
        if sv:
            sv.set_target(target, preserve_velocity)
            self.start()

    def start(self):
        if not self.timer.isActive():
            self._last_time = time.perf_counter()
            self._is_active = True
            self.timer.start()

    def stop(self):
        if self.timer.isActive():
            self.timer.stop()
        self._is_active = False
        self._last_time = None

    def _on_tick(self):
        now = time.perf_counter()
        if self._last_time is None:
            self._last_time = now
            return

        dt = min(0.05, now - self._last_time)
        self._last_time = now

        try:
            from odd_tier import TierManager
            TierManager.get_instance().record_frame_time(dt * 1000.0)
        except Exception:
            pass

        try:
            import odd_profiler
            odd_profiler.get_fps_counter().tick()
        except Exception:
            pass

        all_settled = True
        for sv in self.springs.values():
            sv.update(dt)
            if not sv.is_settled():
                all_settled = False

        self.frame_tick.emit()

        if all_settled:
            self.stop()
            self.all_settled.emit()
            try:
                import odd_profiler
                print(odd_profiler.get_fps_counter().report())
                odd_profiler.get_fps_counter().reset()
            except Exception:
                pass


class MetaballBridge:
    """
    Vector Liquid-Goo / Metaball Generator for Dynamic Island elements.
    Connects two circles / rounded pill caps with an elastic fluid neck that stretches,
    thins based on surface tension, and cleanly snaps into distinct bubbles.
    """
    @staticmethod
    def create_bridge_path(
        c1: QPointF, r1: float,
        c2: QPointF, r2: float,
        max_stretch_factor: float = 2.4,
        tension: float = 0.65
    ) -> Optional[QPainterPath]:
        """
        Generates the QPainterPath of the liquid goo connecting two circular caps.
        Returns None if the distance exceeds surface tension (bridge has snapped).
        """
        dx = c2.x() - c1.x()
        dy = c2.y() - c1.y()
        d = math.hypot(dx, dy)

        # Total resting contact distance
        d_touch = r1 + r2
        d_snap = d_touch * max_stretch_factor

        # If too far apart, the liquid bridge has severed
        if d >= d_snap:
            return None

        # Angle between centers
        angle = math.atan2(dy, dx)

        # Tension progress: 0.0 (touching) -> 1.0 (snapping point)
        if d <= d_touch:
            progress = 0.0
        else:
            progress = (d - d_touch) / max(0.001, d_snap - d_touch)

        # Tangent spread angles on circles: as they pull apart, anchor points migrate toward the bridge axis
        spread_base = math.pi * 0.42
        spread1 = spread_base * (1.0 - progress * 0.45)
        spread2 = spread_base * (1.0 - progress * 0.45)

        # Points on circle 1
        p1_top = QPointF(c1.x() + r1 * math.cos(angle + spread1), c1.y() + r1 * math.sin(angle + spread1))
        p1_bot = QPointF(c1.x() + r1 * math.cos(angle - spread1), c1.y() + r1 * math.sin(angle - spread1))

        # Points on circle 2
        p2_top = QPointF(c2.x() + r2 * math.cos(angle + math.pi - spread2), c2.y() + r2 * math.sin(angle + math.pi - spread2))
        p2_bot = QPointF(c2.x() + r2 * math.cos(angle - math.pi + spread2), c2.y() + r2 * math.sin(angle - math.pi + spread2))

        # Center midpoint between the two bubbles
        mid_x = (c1.x() + c2.x()) / 2.0
        mid_y = (c1.y() + c2.y()) / 2.0

        # Waist thinning: neck thins out with a smooth cubic tension curve
        # At progress = 0: waist is full; at progress = 1: waist thins to 0
        waist_scale = max(0.0, (1.0 - progress) ** 1.8)
        waist_r = ((r1 + r2) / 2.0) * waist_scale * tension

        # Perpendicular unit vector
        perp_x = -math.sin(angle)
        perp_y = math.cos(angle)

        # Inward-pinched waist control points
        c_top = QPointF(mid_x + perp_x * waist_r, mid_y + perp_y * waist_r)
        c_bot = QPointF(mid_x - perp_x * waist_r, mid_y - perp_y * waist_r)

        # Outer curve control points
        handle_len = (d / 2.0) * 0.55
        h1_top = QPointF(p1_top.x() + math.cos(angle) * handle_len, p1_top.y() + math.sin(angle) * handle_len)
        h2_top = QPointF(p2_top.x() - math.cos(angle) * handle_len, p2_top.y() - math.sin(angle) * handle_len)

        h1_bot = QPointF(p1_bot.x() + math.cos(angle) * handle_len, p1_bot.y() + math.sin(angle) * handle_len)
        h2_bot = QPointF(p2_bot.x() - math.cos(angle) * handle_len, p2_bot.y() - math.sin(angle) * handle_len)

        # Construct smooth closed vector path for the liquid bridge
        path = QPainterPath()
        path.moveTo(p1_top)
        path.cubicTo(h1_top, c_top, p2_top)
        path.lineTo(p2_bot)
        path.cubicTo(h2_bot, c_bot, p1_bot)
        path.closeSubpath()

        return path
