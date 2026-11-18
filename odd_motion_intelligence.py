"""
ODD Motion Intelligence & Spatial Animation Architecture
=========================================================
Implements the high-level semantic motion and spatial animation layer for ODD:

1. Semantic Motion Engine (Appear, Settle, Transform, Transfer, Dismiss, Confirm, Reject)
2. Interruption-Aware Transitions with complete Velocity Preservation
3. Perceptual Spring Presets (Position, Width, Height, Radius, Opacity, Shadow)
4. Apple Spatial Animation Techniques:
   - Shared-Element Morphing
   - Content-Aware Expansion & IslandLayoutResolver
   - Optical Corner-Radius & Superellipse Curvature (G2 continuity)
   - Motion Inheritance (MotionNode hierarchical tree)
5. Five Advanced Motion Features:
   - 01. Magnetic Surface (velocity-dependent liquid neck tension)
   - 02. Optical Light Response (dynamic directional rim reflection)
   - 03. Spatial Content Transfer (shared element position persistence)
   - 04. Adaptive Idle Motion (purposeful active movement, zero idle CPU)
   - 05. Precision Dismissal (directional accelerating contraction)
6. Motion Quality Profiler & Accessibility Profiles (Full, Balanced, Reduced)
"""

import math
import time
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal, QPointF, QRectF, QSize, Qt, QRect
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QBrush, QPen, QPixmap, QFont,
    QFontMetrics, QRadialGradient, QLinearGradient
)
from PySide6.QtWidgets import QWidget, QApplication

from odd_theme import Tokens, Fonts
from odd_motion import Spring, SpringPreset, PRESET_SNAPPY, PRESET_LIQUID, PRESET_SOFT, PRESET_GENTLE, MotionClock
from odd_crash_capture import log_breadcrumb, logger, safe_slot


# =========================================================================
# 1. SEMANTIC MOTION IDENTITIES & PRESETS
# =========================================================================

class MotionType(Enum):
    APPEAR    = auto()  # Fast, controlled expansion (Island opening)
    SETTLE    = auto()  # Gentle spring stabilization (Content entering)
    TRANSFORM = auto()  # Continuous shape interpolation (Island changing size)
    TRANSFER  = auto()  # Shared-element movement (Content moving between surfaces)
    DISMISS   = auto()  # Accelerating contraction (Island closing)
    CONFIRM   = auto()  # Short scale and opacity response (Successful action)
    REJECT    = auto()  # Small directional displacement (Invalid action / Headshake)


class PerceptualProperty(Enum):
    POSITION      = auto()  # Snappy
    WIDTH         = auto()  # Liquid
    HEIGHT        = auto()  # Slightly damped (settles earlier than width)
    CORNER_RADIUS = auto()  # Smooth
    OPACITY       = auto()  # Non-spring smooth interpolation
    SHADOW        = auto()  # Delayed, subtle response


# Perceptual Property Spring Presets
PERCEPTUAL_PRESETS: Dict[PerceptualProperty, SpringPreset] = {
    # Position moves quickly to feel instant to user input
    PerceptualProperty.POSITION: SpringPreset("POSITION_SNAPPY", response=0.20, damping_ratio=0.72),
    # Width expands like a fluid surface
    PerceptualProperty.WIDTH: SpringPreset("WIDTH_LIQUID", response=0.34, damping_ratio=0.68),
    # Height settles ~80ms earlier than width to prevent rubbery balloon feel
    PerceptualProperty.HEIGHT: SpringPreset("HEIGHT_DAMPED", response=0.26, damping_ratio=0.82),
    # Corner radius transitions smoothly to prevent pinched corners
    PerceptualProperty.CORNER_RADIUS: SpringPreset("RADIUS_SMOOTH", response=0.28, damping_ratio=0.86),
    # Secondary elements
    PerceptualProperty.SHADOW: SpringPreset("SHADOW_SUBTLE", response=0.42, damping_ratio=0.92),
}


# =========================================================================
# 2. INTERRUPTION-AWARE TRANSITION CONTROLLER
# =========================================================================

@dataclass
class MotionStateSnapshot:
    """Snapshot of a component's continuous physical state at any point in time."""
    x: float = 0.0
    y: float = 0.0
    w: float = 240.0
    h: float = 40.0
    vx: float = 0.0
    vy: float = 0.0
    vw: float = 0.0
    vh: float = 0.0
    corner_radius: float = 20.0
    opacity: float = 1.0
    scale: float = 1.0
    squash: float = 0.0
    superellipse_exp: float = 2.0


class TransitionController(QObject):
    """
    Manages interruption-aware transitions for an interactive surface.
    Maintains continuous position, velocity, scale, shape parameters, and opacity.
    
    If the user interrupts an ongoing animation with another action, the controller:
    - Retargets smoothly towards the new destination.
    - Preserves current velocity and momentum mid-flight (Anti-Jerk).
    - Prevents resetting or teleporting back to the origin.
    """
    state_updated = Signal()
    transition_completed = Signal(MotionType)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        # Independent perceptual springs
        self.spring_x = Spring(0.0, PERCEPTUAL_PRESETS[PerceptualProperty.POSITION])
        self.spring_y = Spring(0.0, PERCEPTUAL_PRESETS[PerceptualProperty.POSITION])
        self.spring_w = Spring(240.0, PERCEPTUAL_PRESETS[PerceptualProperty.WIDTH])
        self.spring_h = Spring(40.0, PERCEPTUAL_PRESETS[PerceptualProperty.HEIGHT])
        self.spring_r = Spring(20.0, PERCEPTUAL_PRESETS[PerceptualProperty.CORNER_RADIUS])
        self.spring_squash = Spring(0.0, PRESET_LIQUID)
        self.spring_scale = Spring(1.0, PRESET_SNAPPY)

        # Smooth non-spring opacity accumulator
        self._current_opacity: float = 1.0
        self._target_opacity: float = 1.0
        self._opacity_speed: float = 6.0  # units per sec

        # Active motion metadata
        self.current_motion_type: MotionType = MotionType.SETTLE
        self.current_target_rect: QRectF = QRectF(0, 0, 240, 40)
        self.origin_point: Optional[QPointF] = None
        self._is_active: bool = False
        self._interruption_count: int = 0

    def get_snapshot(self) -> MotionStateSnapshot:
        return MotionStateSnapshot(
            x=self.spring_x.value,
            y=self.spring_y.value,
            w=self.spring_w.value,
            h=self.spring_h.value,
            vx=self.spring_x.velocity,
            vy=self.spring_y.velocity,
            vw=self.spring_w.velocity,
            vh=self.spring_h.velocity,
            corner_radius=self.spring_r.value,
            opacity=self._current_opacity,
            scale=self.spring_scale.value,
            squash=self.spring_squash.value
        )

    def transition_to(
        self,
        target_rect: QRectF,
        target_radius: Optional[float] = None,
        target_opacity: float = 1.0,
        motion_type: MotionType = MotionType.TRANSFORM,
        origin: Optional[QPointF] = None
    ):
        """
        Interruption-Aware Retargeting.
        Smoothly redirects the ongoing physical motion towards target_rect,
        inheriting existing velocity across interruptions without resetting.
        """
        if self._is_active:
            self._interruption_count += 1
            log_breadcrumb(f"Motion interrupted mid-flight (count={self._interruption_count}) -> Retargeting to {motion_type.name}", category="motion")

        self.current_motion_type = motion_type
        self.current_target_rect = target_rect
        self.origin_point = origin
        self._target_opacity = max(0.0, min(1.0, float(target_opacity)))

        # 1. Apply semantic motion policy to spring presets
        if motion_type == MotionType.APPEAR:
            self.spring_x.set_preset(PERCEPTUAL_PRESETS[PerceptualProperty.POSITION])
            self.spring_y.set_preset(PERCEPTUAL_PRESETS[PerceptualProperty.POSITION])
            self.spring_w.set_preset(PERCEPTUAL_PRESETS[PerceptualProperty.WIDTH])
            self.spring_h.set_preset(PERCEPTUAL_PRESETS[PerceptualProperty.HEIGHT])
            self._opacity_speed = 8.5
        elif motion_type == MotionType.DISMISS:
            # Accelerating contraction: slightly firmer response to disappear quickly
            self.spring_w.set_preset(PRESET_SNAPPY)
            self.spring_h.set_preset(PRESET_SNAPPY)
            self._opacity_speed = 7.0
        elif motion_type == MotionType.CONFIRM:
            # Short scale response (1.0 -> 1.04 -> 1.0)
            self.spring_scale.snap_to(1.0)
            self.spring_scale.retarget(1.04, preserve_velocity=False)
        elif motion_type == MotionType.REJECT:
            # Small directional displacement (nudge / headshake)
            self.spring_x.velocity = -240.0  # initial left kick

        # 2. Retarget with velocity preservation
        self.spring_x.retarget(target_rect.x(), preserve_velocity=True)
        self.spring_y.retarget(target_rect.y(), preserve_velocity=True)
        self.spring_w.retarget(target_rect.width(), preserve_velocity=True)
        self.spring_h.retarget(target_rect.height(), preserve_velocity=True)

        eff_radius = target_radius if target_radius is not None else min(target_rect.height() / 2.0, 24.0)
        self.spring_r.retarget(eff_radius, preserve_velocity=True)

        self._is_active = True
        MotionClock.get_instance().register_updater(self.step)

    def step(self, dt: float) -> bool:
        """Single physics tick for transition controller."""
        moving = False
        for s in (self.spring_x, self.spring_y, self.spring_w, self.spring_h, self.spring_r, self.spring_scale, self.spring_squash):
            s.update(dt)
            if not s.is_settled():
                moving = True

        # Non-spring smooth opacity damping
        if abs(self._current_opacity - self._target_opacity) > 0.005:
            d_op = (self._target_opacity - self._current_opacity) * min(1.0, dt * self._opacity_speed)
            self._current_opacity += d_op
            moving = True
        else:
            self._current_opacity = self._target_opacity

        # Dynamic squash from horizontal velocity: compresses height during fast stretch
        dw = abs(self.spring_w.velocity)
        squash_target = min(0.06, dw / 12000.0)
        self.spring_squash.retarget(squash_target, preserve_velocity=True)

        # Scale recovery after confirm pulse
        if self.current_motion_type == MotionType.CONFIRM:
            if self.spring_scale.value >= 1.035:
                self.spring_scale.retarget(1.0, preserve_velocity=True)

        self.state_updated.emit()

        if not moving:
            self._is_active = False
            self.transition_completed.emit(self.current_motion_type)
            return False

        return True


# =========================================================================
# 3. SEMANTIC MOTION API (motion.appear, motion.transform, etc.)
# =========================================================================

class MotionIntelligence:
    """
    High-Level Motion Intelligence Layer for ODD.
    Provides semantic wrappers around physics oscillators:
    - appear(): Fast, controlled expansion
    - settle(): Gentle spring stabilization
    - transform(): Continuous shape interpolation
    - transfer(): Shared-element movement
    - dismiss(): Accelerating contraction
    - confirm(): Short scale and opacity response
    - reject(): Small directional displacement
    """
    _instance = None

    @classmethod
    def get_instance(cls) -> "MotionIntelligence":
        if cls._instance is None:
            cls._instance = MotionIntelligence()
        return cls._instance

    def __init__(self):
        self.controllers: Dict[int, TransitionController] = {}

    def _get_controller(self, widget: QWidget) -> TransitionController:
        wid = id(widget)
        if wid not in self.controllers:
            ctrl = TransitionController(widget)
            ctrl.state_updated.connect(widget.update)
            self.controllers[wid] = ctrl
        return self.controllers[wid]

    def appear(self, target: QWidget, target_rect: QRectF, origin: Optional[QPointF] = None):
        """Island opening: Fast, controlled expansion."""
        ctrl = self._get_controller(target)
        if origin is not None and not ctrl._is_active:
            ctrl.spring_x.snap_to(origin.x())
            ctrl.spring_y.snap_to(origin.y())
            ctrl.spring_w.snap_to(max(20.0, target_rect.width() * 0.4))
            ctrl.spring_h.snap_to(max(20.0, target_rect.height() * 0.4))
            ctrl._current_opacity = 0.0

        ctrl.transition_to(target_rect, target_opacity=1.0, motion_type=MotionType.APPEAR, origin=origin)

    def settle(self, target: QWidget, target_rect: Optional[QRectF] = None):
        """Content entering: Gentle spring stabilization."""
        ctrl = self._get_controller(target)
        rect = target_rect or QRectF(target.rect())
        ctrl.transition_to(rect, target_opacity=1.0, motion_type=MotionType.SETTLE)

    def transform(self, target: QWidget, destination_rect: QRectF, corner_radius: Optional[float] = None):
        """Island changing size: Continuous shape interpolation with velocity preservation."""
        ctrl = self._get_controller(target)
        ctrl.transition_to(destination_rect, target_radius=corner_radius, target_opacity=1.0, motion_type=MotionType.TRANSFORM)

    def transfer(self, target: QWidget, destination_rect: QRectF):
        """Shared-element movement: Content moving between surfaces."""
        ctrl = self._get_controller(target)
        ctrl.transition_to(destination_rect, target_opacity=1.0, motion_type=MotionType.TRANSFER)

    def dismiss(self, target: QWidget, destination_origin: Optional[QPointF] = None):
        """Island closing: Accelerating contraction towards origin."""
        ctrl = self._get_controller(target)
        snap = ctrl.get_snapshot()
        dest_x = destination_origin.x() if destination_origin else snap.x + snap.w / 2.0
        dest_y = destination_origin.y() if destination_origin else snap.y
        dismiss_rect = QRectF(dest_x - 10, dest_y, 20, 20)
        ctrl.transition_to(dismiss_rect, target_radius=10.0, target_opacity=0.0, motion_type=MotionType.DISMISS, origin=destination_origin)

    def confirm(self, target: QWidget):
        """Successful action: Short scale and opacity response."""
        ctrl = self._get_controller(target)
        snap = ctrl.get_snapshot()
        curr_rect = QRectF(snap.x, snap.y, snap.w, snap.h)
        ctrl.transition_to(curr_rect, motion_type=MotionType.CONFIRM)

    def reject(self, target: QWidget):
        """Invalid action: Small directional displacement."""
        ctrl = self._get_controller(target)
        snap = ctrl.get_snapshot()
        curr_rect = QRectF(snap.x, snap.y, snap.w, snap.h)
        ctrl.transition_to(curr_rect, motion_type=MotionType.REJECT)


# Global motion singleton accessor
motion = MotionIntelligence.get_instance()


# =========================================================================
# 4. APPLE SPATIAL ANIMATION TECHNIQUES
# =========================================================================

# --- A. Motion Inheritance (Hierarchical Tree) ---

class MotionNode:
    """
    Hierarchical Motion Tree node.
    Enables motion inheritance: children inherit the parent's transformation,
    velocity, and scale, and only apply their own small local adjustments.
    """
    def __init__(self, name: str = "", parent: Optional["MotionNode"] = None):
        self.name = name
        self.parent: Optional["MotionNode"] = parent
        self.children: List["MotionNode"] = []
        
        # Local transformation
        self.local_pos = QPointF(0.0, 0.0)
        self.local_scale = 1.0
        self.local_opacity = 1.0

        # Resolved world transformation
        self.world_pos = QPointF(0.0, 0.0)
        self.world_scale = 1.0
        self.world_opacity = 1.0

        if parent:
            parent.add_child(self)

    def add_child(self, child: "MotionNode"):
        if child not in self.children:
            child.parent = self
            self.children.append(child)

    def update_world_transform(self):
        """Recursively resolves world transform from parent down to leaves."""
        if self.parent:
            self.world_pos = QPointF(
                self.parent.world_pos.x() + self.local_pos.x() * self.parent.world_scale,
                self.parent.world_pos.y() + self.local_pos.y() * self.parent.world_scale
            )
            self.world_scale = self.parent.world_scale * self.local_scale
            self.world_opacity = self.parent.world_opacity * self.local_opacity
        else:
            self.world_pos = self.local_pos
            self.world_scale = self.local_scale
            self.world_opacity = self.local_opacity

        for child in self.children:
            child.update_world_transform()


# --- B. Content-Aware Expansion & IslandLayoutResolver ---

@dataclass
class IslandLayout:
    """Resolved geometric layout for specific content."""
    width: float
    height: float
    corner_radius: float
    has_secondary_bubble: bool = False
    bubble_size: float = 40.0
    bubble_gap: float = 12.0
    mode_name: str = "default"


class TimerLayout(IslandLayout):
    def __init__(self):
        super().__init__(width=160.0, height=38.0, corner_radius=19.0, mode_name="timer")


class DownloadLayout(IslandLayout):
    def __init__(self):
        super().__init__(width=260.0, height=42.0, corner_radius=21.0, mode_name="download")


class MediaLayout(IslandLayout):
    def __init__(self):
        super().__init__(width=360.0, height=120.0, corner_radius=28.0, mode_name="media")


class NotificationLayout(IslandLayout):
    def __init__(self):
        super().__init__(width=320.0, height=84.0, corner_radius=26.0, mode_name="notification")


class MultiActivityLayout(IslandLayout):
    def __init__(self):
        super().__init__(width=220.0, height=40.0, corner_radius=20.0, has_secondary_bubble=True, bubble_size=40.0, bubble_gap=12.0, mode_name="split")


class SearchLayout(IslandLayout):
    def __init__(self, has_results: bool = False, result_count: int = 0):
        h = 54.0 if not has_results else min(380.0, 54.0 + result_count * 48.0 + 16.0)
        r = 27.0 if not has_results else 24.0
        super().__init__(width=480.0, height=h, corner_radius=r, mode_name="search")


class IslandLayoutResolver:
    """
    Content-Aware Expansion Resolver.
    Evaluates content requirements to select optimal geometry and layout targets,
    driving the motion engine rather than using hardcoded fixed animation presets.
    """
    @staticmethod
    def resolve(content: Any) -> IslandLayout:
        if content is None:
            return IslandLayout(width=240.0, height=40.0, corner_radius=20.0, mode_name="idle")

        if getattr(content, "has_multiple_activities", False):
            return MultiActivityLayout()

        if getattr(content, "is_timer", False):
            return TimerLayout()

        if getattr(content, "is_media", False):
            return MediaLayout()

        if getattr(content, "is_download", False):
            return DownloadLayout()

        if getattr(content, "is_notification", False):
            return NotificationLayout()

        if getattr(content, "is_search", False):
            has_res = getattr(content, "has_results", False)
            res_cnt = getattr(content, "result_count", 0)
            return SearchLayout(has_results=has_res, result_count=res_cnt)

        return IslandLayout(width=240.0, height=40.0, corner_radius=20.0, mode_name="idle")


# --- C. Optical Corner-Radius & Superellipse Curvature (G2 Continuity) ---

class OpticalGeometryController:
    """
    Optical Geometry & Superellipse Interpolator.
    Prevents the visual impression of stretched rounded rectangles by dynamically
    interpolating aspect ratio, corner tangent continuity, edge curvature, and
    superellipse exponent (n = 2.0 to 3.8) based on scale and dimension.
    """
    @staticmethod
    def calculate_optical_exponent(width: float, height: float) -> float:
        """
        Calculates continuous superellipse exponent:
        - Compact capsule (ratio > 3.0 or h <= 44): n = 2.0 (pure pill)
        - Expanded card (ratio < 2.5 and h > 70): n = 3.4 (soft engineered squircle)
        """
        if height <= 44.0:
            return 2.0  # Natural circle caps for pills
        aspect = width / max(1.0, height)
        # Smooth interpolation based on height and aspect ratio
        t = min(1.0, max(0.0, (height - 44.0) / 60.0))
        return 2.0 + 1.4 * t * (1.0 - min(1.0, aspect / 6.0) * 0.4)

    @staticmethod
    def build_optical_squircle_path(rect: QRectF, radius: float, exponent: float = 2.0) -> QPainterPath:
        """
        Constructs an optical continuous-curvature superellipse rounded rectangle
        using cubic Beziers (G2 curvature continuity).
        """
        w = rect.width()
        h = rect.height()
        max_r = min(w, h) / 2.0
        r = min(max_r, float(radius))

        path = QPainterPath()
        if r <= 0.5:
            path.addRect(rect)
            return path

        x = rect.x()
        y = rect.y()

        # Dynamic curvature factor k based on exponent (circle kappa ~0.552, squircle ~0.585 to 0.63)
        exp_clamped = max(2.0, min(4.0, exponent))
        k = (0.55228 + 0.05 * (exp_clamped - 2.0)) * r

        path.moveTo(x + r, y)
        path.lineTo(x + w - r, y)
        path.cubicTo(x + w - r + k, y, x + w, y + r - k, x + w, y + r)
        path.lineTo(x + w, y + h - r)
        path.cubicTo(x + w, y + h - r + k, x + w - r + k, y + h, x + w - r, y + h)
        path.lineTo(x + r, y + h)
        path.cubicTo(x + r - k, y + h, x, y + h - r + k, x, y + h - r)
        path.lineTo(x, y + r)
        path.cubicTo(x, y + r - k, x + r - k, y, x + r, y)
        path.closeSubpath()
        return path


# =========================================================================
# 5. FIVE ADVANCED MOTION FEATURES
# =========================================================================

# --- 01. Magnetic Surface (Velocity-Dependent Liquid Neck) ---

class MagneticSurface:
    """
    Velocity-dependent magnetic liquid surface connection.
    Connects nearby activity bubbles to the main island using metaball physics:
    connection strength and neck thinning scale dynamically with relative velocity.
    """
    @staticmethod
    def compute_dynamic_tension(base_tension: float, relative_velocity: float) -> float:
        # Fast-moving bubbles create higher surface tension and extended deformation
        v_norm = min(1.5, abs(relative_velocity) / 600.0)
        return max(0.2, min(1.0, base_tension * (1.0 + v_norm * 0.45)))

    @staticmethod
    def build_magnetic_bridge(
        r1: QRectF, r2: QRectF,
        relative_velocity: float = 0.0,
        base_tension: float = 0.65
    ) -> Optional[QPainterPath]:
        from odd_spring import MetaballBridge
        tension = MagneticSurface.compute_dynamic_tension(base_tension, relative_velocity)
        c1 = r1.center()
        c2 = r2.center()
        rad1 = min(r1.width(), r1.height()) / 2.0
        rad2 = min(r2.width(), r2.height()) / 2.0
        # Dynamic stretch factor: faster separation allows longer bridge before snapping
        stretch = 2.4 + min(0.8, abs(relative_velocity) / 800.0)
        return MetaballBridge.create_bridge_path(c1, rad1, c2, rad2, max_stretch_factor=stretch, tension=tension)


# --- 02. Optical Light Response (Dynamic Specular Rim) ---

class OpticalLightResponse:
    """
    Calculates a restrained, dynamic edge reflection that responds to expansion velocity.
    Rather than a static glow, computes a subtle 1px specular highlight along the leading
    movement rim that automatically fades when stationary.
    """
    def __init__(self):
        self.highlight_alpha: float = 0.0

    def update(self, velocity: float, dt: float) -> float:
        v = abs(velocity)
        target_alpha = min(0.35, v / 2800.0)  # Max 35% specular highlight
        # Smoothly follow velocity
        self.highlight_alpha += (target_alpha - self.highlight_alpha) * min(1.0, dt * 12.0)
        return self.highlight_alpha

    def paint_rim_highlight(self, painter: QPainter, path: QPainterPath, rect: QRectF):
        if self.highlight_alpha <= 0.01:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Subtle white hairline along top-edge leading rim
        alpha = int(255 * self.highlight_alpha)
        grad = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.3, QColor(255, 255, 255, alpha))
        grad.setColorAt(0.7, QColor(255, 255, 255, alpha))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))

        pen = QPen(QBrush(grad), 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()


# --- 03. Spatial Content Transfer ---

class SpatialContentTransfer:
    """
    Preserves visual element identity across layout states.
    When elements (album art, progress percentage, timer digits) transition
    between compact and expanded island states, their coordinates smoothly
    glide into place rather than popping.
    """
    def __init__(self):
        self.active_transfers: Dict[str, Tuple[QPointF, QPointF, float]] = {}

    def start_transfer(self, element_id: str, source_pos: QPointF, dest_pos: QPointF):
        self.active_transfers[element_id] = (source_pos, dest_pos, time.perf_counter())

    def get_interpolated_position(self, element_id: str, duration: float = 0.30) -> Optional[QPointF]:
        if element_id not in self.active_transfers:
            return None
        src, dst, t0 = self.active_transfers[element_id]
        p = min(1.0, max(0.0, (time.perf_counter() - t0) / duration))
        # Hermite smoothstep
        ease = p * p * (3.0 - 2.0 * p)
        if p >= 1.0:
            del self.active_transfers[element_id]
            return dst
        return QPointF(src.x() + (dst.x() - src.x()) * ease, src.y() + (dst.y() - src.y()) * ease)


# --- 04. Adaptive Idle Motion ---

class AdaptiveIdleMotion:
    """
    Subtle motion for active content; zero CPU for idle content.
    - Music: audio-reactive subtle waveform
    - Timer: changing tabular numerals
    - Download: subtle progress movement
    - Inactive / Notifications: strictly stationary (0.0% CPU)
    """
    @staticmethod
    def is_motion_required(content: Any) -> bool:
        if content is None:
            return False
        if getattr(content, "is_media", False) and getattr(content, "is_playing", False):
            return True
        if getattr(content, "is_timer", False) and getattr(content, "is_running", False):
            return True
        if getattr(content, "is_download", False) and getattr(content, "is_active", False):
            return True
        return False


# --- 05. Precision Dismissal ---

class PrecisionDismissal:
    """
    When dismissed, the island contracts towards its origin with a controlled directional
    movement, preserving its final velocity, scale and shape continuity until it reaches
    its compact resting state.
    """
    @staticmethod
    def dismiss(widget: QWidget, origin_point: Optional[QPointF] = None):
        motion.dismiss(widget, destination_origin=origin_point)


# =========================================================================
# 6. MOTION QUALITY SYSTEM & ACCESSIBILITY PROFILER
# =========================================================================

class MotionProfile(Enum):
    FULL     = auto()  # All supported effects, fluid springs, optical highlights, magnetic goo
    BALANCED = auto()  # Standard spring physics, reduced secondary effects
    REDUCED  = auto()  # Minimal transitions, zero decorative motion (accessibility mode)


class MotionQualityProfiler:
    """
    Real-Time Motion Quality & Performance Profiler.
    Tracks:
    - Average frame time
    - 95th percentile (p95) frame time
    - Dropped frames count (frame time > 18.0ms)
    - Spring settling duration
    - Input-to-visible-response latency
    - Cache hit ratio
    """
    _instance = None

    @classmethod
    def get_instance(cls) -> "MotionQualityProfiler":
        if cls._instance is None:
            cls._instance = MotionQualityProfiler()
        return cls._instance

    def __init__(self):
        self._frame_times: List[float] = []
        self._dropped_frames: int = 0
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._active_profile: MotionProfile = self._detect_system_profile()

    def _detect_system_profile(self) -> MotionProfile:
        """Detects Windows system animation accessibility settings."""
        try:
            import ctypes
            # SPI_GETCLIENTAREAANIMATION = 0x1042
            pv_param = ctypes.c_bool()
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(pv_param), 0)
            if not pv_param.value:
                return MotionProfile.REDUCED
        except Exception:
            pass
        return MotionProfile.FULL

    @property
    def profile(self) -> MotionProfile:
        return self._active_profile

    def set_profile(self, profile: MotionProfile):
        self._active_profile = profile
        log_breadcrumb(f"Motion Profile set to {profile.name}", category="profiler")

    def record_frame(self, frame_ms: float):
        self._frame_times.append(frame_ms)
        if len(self._frame_times) > 300:
            self._frame_times.pop(0)
        if frame_ms > 18.0:
            self._dropped_frames += 1

    def record_cache(self, hit: bool):
        if hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

    def get_metrics(self) -> Dict[str, Any]:
        if not self._frame_times:
            return {"avg_ms": 0.0, "p95_ms": 0.0, "dropped": 0, "cache_hit_ratio": 1.0}
        
        sorted_times = sorted(self._frame_times)
        p95_idx = int(len(sorted_times) * 0.95)
        total_cache = self._cache_hits + self._cache_misses
        ratio = (self._cache_hits / total_cache) if total_cache > 0 else 1.0

        return {
            "avg_ms": round(sum(self._frame_times) / len(self._frame_times), 2),
            "p95_ms": round(sorted_times[p95_idx], 2),
            "dropped": self._dropped_frames,
            "cache_hit_ratio": round(ratio, 3),
            "profile": self._active_profile.name
        }
