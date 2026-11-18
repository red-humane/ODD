"""
Comprehensive Test Suite for ODD Visual Tokens, Motion Intelligence, and Spatial Animation Architecture.
"""

import sys
import os
import math
import pytest
from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from odd_theme import Tokens, Fonts
from odd_motion_intelligence import (
    MotionType, PerceptualProperty, PERCEPTUAL_PRESETS,
    TransitionController, MotionIntelligence, motion,
    MotionNode, IslandLayout, TimerLayout, DownloadLayout, MediaLayout,
    NotificationLayout, MultiActivityLayout, SearchLayout, IslandLayoutResolver,
    OpticalGeometryController, MagneticSurface, OpticalLightResponse,
    SpatialContentTransfer, AdaptiveIdleMotion, PrecisionDismissal,
    MotionProfile, MotionQualityProfiler
)
import odd_animated_buttons
from odd_animated_buttons import ButtonType, ODDButton


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_visual_tokens_palette():
    """Verify refined visual tokens match solid black minimal specifications."""
    # Background: #050505 / #070708 Deep black
    assert Tokens.BACKGROUND.red() in (5, 7)
    assert Tokens.BACKGROUND.green() in (5, 7)
    assert Tokens.BACKGROUND.alpha() == 255

    # Island: Pure AMOLED black (#080808), 100% opaque
    assert Tokens.ISLAND.red() in (8, 16)
    assert Tokens.ISLAND.green() in (8, 16)
    assert Tokens.ISLAND.alpha() == 255

    # Elevated: Solid secondary surfaces
    assert Tokens.ELEVATED.red() in (14, 23)
    assert Tokens.ELEVATED.alpha() == 255

    # Hover: Interactive feedback
    assert Tokens.HOVER.red() in (24, 32)
    assert Tokens.HOVER.alpha() == 255

    # Border subtle: subtle grey #292929 (or white 7%)
    assert Tokens.BORDER_SUBTLE.alpha() in (18, 255)
    if Tokens.BORDER_SUBTLE.alpha() == 255:
        assert Tokens.BORDER_SUBTLE.red() == 41
    else:
        assert Tokens.BORDER_SUBTLE.red() == 255

    # Border active: accessible focus highlight
    assert Tokens.BORDER_ACTIVE.alpha() in (41, 255)

    # Primary text: White 94% (alpha ~ 240)
    assert Tokens.PRIMARY_TEXT.red() == 255
    assert Tokens.PRIMARY_TEXT.green() == 255
    assert Tokens.PRIMARY_TEXT.blue() == 255
    assert abs(Tokens.PRIMARY_TEXT.alpha() - int(255 * 0.94)) <= 1

    # Secondary text: White 58% (alpha ~ 148)
    assert Tokens.SECONDARY_TEXT.red() == 255
    assert Tokens.SECONDARY_TEXT.green() == 255
    assert Tokens.SECONDARY_TEXT.blue() == 255
    assert abs(Tokens.SECONDARY_TEXT.alpha() - int(255 * 0.58)) <= 1

    # Tertiary text: White 36% (alpha ~ 92)
    assert Tokens.TERTIARY_TEXT.red() == 255
    assert Tokens.TERTIARY_TEXT.green() == 255
    assert Tokens.TERTIARY_TEXT.blue() == 255
    assert abs(Tokens.TERTIARY_TEXT.alpha() - int(255 * 0.36)) <= 1

    # Backward compatibility aliases
    assert Tokens.SURFACE_0 == Tokens.ISLAND
    assert Tokens.SURFACE_1 == Tokens.ELEVATED
    assert Tokens.SURFACE_2 == Tokens.HOVER
    assert Tokens.TEXT_PRIMARY == Tokens.PRIMARY_TEXT
    assert Tokens.TEXT_SECONDARY == Tokens.SECONDARY_TEXT
    assert Tokens.TEXT_TERTIARY == Tokens.TERTIARY_TEXT


def test_typography_scale():
    """Verify refined typography hierarchy roles and font weights."""
    hero_font = Fonts.hero(40)
    assert hero_font.weight() == QFont.Weight.Medium
    assert "Display" in hero_font.family()

    heading_font = Fonts.section_heading(14)
    assert heading_font.weight() == QFont.Weight.DemiBold

    body_font = Fonts.body(12)
    assert body_font.weight() == QFont.Weight.Normal

    meta_font = Fonts.metadata(11)
    assert meta_font.weight() == QFont.Weight.Medium

    tab_font = Fonts.tabular(12)
    assert tab_font.weight() in (QFont.Weight.Normal, QFont.Weight.DemiBold)


def test_perceptual_spring_presets():
    """Verify perceptual spring presets have distinct physical responses."""
    pos_preset = PERCEPTUAL_PRESETS[PerceptualProperty.POSITION]
    w_preset = PERCEPTUAL_PRESETS[PerceptualProperty.WIDTH]
    h_preset = PERCEPTUAL_PRESETS[PerceptualProperty.HEIGHT]
    r_preset = PERCEPTUAL_PRESETS[PerceptualProperty.CORNER_RADIUS]

    # Position is snappy
    assert pos_preset.response <= 0.22
    # Width is liquid
    assert w_preset.response >= 0.30
    # Height settles earlier than width (shorter response time and higher damping)
    assert h_preset.response < w_preset.response
    assert h_preset.damping_ratio > w_preset.damping_ratio
    # Corner radius is smooth
    assert r_preset.damping_ratio >= 0.85


def test_interruption_aware_transition_controller(qapp):
    """Verify velocity preservation across interrupted mid-flight transitions."""
    widget = QWidget()
    ctrl = TransitionController(widget)

    # 1. Start initial transition towards 360x120
    rect1 = QRectF(100, 10, 360, 120)
    ctrl.transition_to(rect1, motion_type=MotionType.TRANSFORM)

    # Step simulation slightly (dt = 0.05s) to accumulate momentum
    ctrl.step(0.05)
    snap1 = ctrl.get_snapshot()
    assert snap1.vw > 0.0, "Width velocity should be positive during expansion"
    initial_vel_w = snap1.vw

    # 2. User interrupts mid-flight with another action -> redirect to 220x40
    rect2 = QRectF(150, 10, 220, 40)
    ctrl.transition_to(rect2, motion_type=MotionType.TRANSFORM)

    # Check that width velocity was preserved across the retarget call
    snap2 = ctrl.get_snapshot()
    assert abs(snap2.vw - initial_vel_w) < 0.01, "Velocity must be preserved mid-flight (Anti-Jerk)"
    assert ctrl._interruption_count == 1, "Interruption counter should be incremented"


def test_semantic_motion_api(qapp):
    """Verify semantic motion methods: appear, settle, transform, transfer, dismiss, confirm, reject."""
    widget = QWidget()
    widget.resize(240, 40)

    # Appear
    origin = QPointF(120, 0)
    target_rect = QRectF(50, 10, 300, 50)
    motion.appear(widget, target_rect, origin=origin)
    ctrl = motion._get_controller(widget)
    assert ctrl.current_motion_type == MotionType.APPEAR

    # Transform
    motion.transform(widget, QRectF(30, 10, 360, 120), corner_radius=28.0)
    assert ctrl.current_motion_type == MotionType.TRANSFORM

    # Confirm
    motion.confirm(widget)
    assert ctrl.current_motion_type == MotionType.CONFIRM

    # Reject
    motion.reject(widget)
    assert ctrl.current_motion_type == MotionType.REJECT
    assert ctrl.spring_x.velocity < 0.0, "Reject must trigger negative x displacement kick"

    # Dismiss
    motion.dismiss(widget, destination_origin=origin)
    assert ctrl.current_motion_type == MotionType.DISMISS


def test_motion_inheritance():
    """Verify hierarchical MotionNode tree propagation."""
    parent_node = MotionNode(name="island_parent")
    parent_node.local_pos = QPointF(100.0, 50.0)
    parent_node.local_scale = 1.2

    child_node = MotionNode(name="timer_bubble", parent=parent_node)
    child_node.local_pos = QPointF(40.0, 10.0)
    child_node.local_scale = 0.9

    parent_node.update_world_transform()

    # World position: 100 + 40 * 1.2 = 148, 50 + 10 * 1.2 = 62
    assert abs(child_node.world_pos.x() - 148.0) < 0.01
    assert abs(child_node.world_pos.y() - 62.0) < 0.01
    # World scale: 1.2 * 0.9 = 1.08
    assert abs(child_node.world_scale - 1.08) < 0.01


def test_island_layout_resolver():
    """Verify content-aware expansion layout resolution."""
    class MockContent:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    # Timer
    timer_layout = IslandLayoutResolver.resolve(MockContent(is_timer=True))
    assert isinstance(timer_layout, TimerLayout)
    assert timer_layout.width == 160.0
    assert timer_layout.height == 38.0

    # Media
    media_layout = IslandLayoutResolver.resolve(MockContent(is_media=True))
    assert isinstance(media_layout, MediaLayout)
    assert media_layout.width == 360.0
    assert media_layout.height == 120.0

    # Multi-activity split
    split_layout = IslandLayoutResolver.resolve(MockContent(has_multiple_activities=True))
    assert isinstance(split_layout, MultiActivityLayout)
    assert split_layout.has_secondary_bubble is True

    # Search
    search_layout = IslandLayoutResolver.resolve(MockContent(is_search=True, has_results=True, result_count=4))
    assert isinstance(search_layout, SearchLayout)
    assert search_layout.height > 54.0


def test_optical_geometry_controller():
    """Verify continuous superellipse exponent and path generation."""
    # Compact pill has n = 2.0
    exp_pill = OpticalGeometryController.calculate_optical_exponent(width=200.0, height=36.0)
    assert abs(exp_pill - 2.0) < 0.01

    # Expanded card has softer squircle exponent (n > 2.5)
    exp_card = OpticalGeometryController.calculate_optical_exponent(width=360.0, height=140.0)
    assert exp_card >= 2.6

    # Verify path generation does not fail
    rect = QRectF(0, 0, 360, 140)
    path = OpticalGeometryController.build_optical_squircle_path(rect, radius=28.0, exponent=exp_card)
    assert not path.isEmpty()
    assert path.elementCount() > 8


def test_five_advanced_motion_features():
    """Verify the 5 new advanced motion features."""
    # 01. Magnetic Surface: Velocity-dependent tension
    t_slow = MagneticSurface.compute_dynamic_tension(0.65, relative_velocity=50.0)
    t_fast = MagneticSurface.compute_dynamic_tension(0.65, relative_velocity=500.0)
    assert t_fast > t_slow, "Dynamic tension must increase with relative velocity"

    # 02. Optical Light Response
    olr = OpticalLightResponse()
    alpha1 = olr.update(velocity=0.0, dt=0.016)
    alpha2 = olr.update(velocity=1500.0, dt=0.016)
    assert alpha2 > alpha1, "Rim highlight alpha must respond to surface velocity"

    # 03. Spatial Content Transfer
    sct = SpatialContentTransfer()
    p_src = QPointF(20.0, 10.0)
    p_dst = QPointF(180.0, 60.0)
    sct.start_transfer("album_art", p_src, p_dst)
    pos_mid = sct.get_interpolated_position("album_art", duration=0.5)
    assert pos_mid is not None
    assert p_src.x() < pos_mid.x() <= p_dst.x()

    # 04. Adaptive Idle Motion
    class MockActive:
        is_media = True
        is_playing = True
    class MockIdle:
        is_media = True
        is_playing = False

    assert AdaptiveIdleMotion.is_motion_required(MockActive()) is True
    assert AdaptiveIdleMotion.is_motion_required(MockIdle()) is False

    # 05. Precision Dismissal
    # Tested through motion.dismiss


def test_refined_button_system(qapp):
    """Verify rendering of Primary, Secondary, and Tertiary buttons."""
    img = QImage(300, 150, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(7, 7, 8))
    painter = QPainter(img)

    r_pri = QRectF(10, 10, 80, 32)
    odd_animated_buttons.paint_primary_button(painter, r_pri, "Open", hover_progress=0.0)
    odd_animated_buttons.paint_primary_button(painter, r_pri, "Open", hover_progress=1.0)

    r_sec = QRectF(100, 10, 80, 32)
    odd_animated_buttons.paint_secondary_button(painter, r_sec, "Settings", hover_progress=0.0)
    odd_animated_buttons.paint_secondary_button(painter, r_sec, "Settings", hover_progress=1.0)

    r_ter = QRectF(190, 10, 80, 32)
    odd_animated_buttons.paint_tertiary_button(painter, r_ter, "Cancel", hover_progress=0.0)
    odd_animated_buttons.paint_tertiary_button(painter, r_ter, "Cancel", hover_progress=1.0)

    painter.end()


def test_motion_quality_profiler():
    """Verify motion quality metrics and profile switching."""
    profiler = MotionQualityProfiler.get_instance()
    profiler.set_profile(MotionProfile.FULL)
    assert profiler.profile == MotionProfile.FULL

    profiler.record_frame(12.5)
    profiler.record_frame(15.0)
    profiler.record_frame(14.2)
    profiler.record_frame(22.0)  # dropped frame (> 18ms)

    profiler.record_cache(hit=True)
    profiler.record_cache(hit=True)
    profiler.record_cache(hit=False)

    metrics = profiler.get_metrics()
    assert metrics["dropped"] >= 1
    assert metrics["avg_ms"] > 0.0
    assert metrics["cache_hit_ratio"] > 0.5
    assert metrics["profile"] == "FULL"
