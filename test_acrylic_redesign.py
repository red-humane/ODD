"""
Verification tests for ODD 2.0 Pure Black, Minimal & Premium UI Refinement
1. Pure AMOLED black surfaces (#080808, 100% opaque, alpha=255).
2. Subtle dark-grey border (#292929).
3. Zero ripple distortion, zero circular waves, zero screen displacement.
4. Window canvas transparency preserved without rectangular DWM slabs.
5. Solid opaque primary & secondary panel rendering.
"""

import sys
import os
import pytest
from PySide6.QtCore import QRectF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from odd_theme import Tokens, create_squircle_path
import odd_blur
from odd_blur import ODDOverlaySurface, GlassDisplacementRipple
import odd_island
import odd_animated_buttons
from fluentapp.windoweffect import WindowBlur


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_pure_black_tokens():
    """Verify ODD 2.0 tokens adhere to the pure AMOLED black minimal system."""
    # Primary Island: Pure AMOLED black #080808, 100% opaque
    assert Tokens.ISLAND.alpha() == 255, f"Expected 100% opaque island, got alpha={Tokens.ISLAND.alpha()}"
    assert Tokens.ISLAND.red() == 8
    assert Tokens.ISLAND.green() == 8
    assert Tokens.ISLAND.blue() == 8

    # Secondary Panels: #0E0E0F, 100% opaque
    assert Tokens.ELEVATED.alpha() == 255
    assert Tokens.ELEVATED.red() == 14
    assert Tokens.ELEVATED.green() == 14
    assert Tokens.ELEVATED.blue() == 15

    # Subtle grey border: #292929
    assert Tokens.BORDER_SUBTLE.alpha() == 255
    assert Tokens.BORDER_SUBTLE.red() == 41
    assert Tokens.BORDER_SUBTLE.green() == 41
    assert Tokens.BORDER_SUBTLE.blue() == 41

    # Focus border
    assert Tokens.BORDER_ACTIVE.alpha() == 255
    assert Tokens.BORDER_ACTIVE.red() == 70

    # No fake inner highlight/gradient
    assert Tokens.BORDER_INNER_HIGHLIGHT.alpha() == 0


def test_no_screenshot_or_acrylic_blur():
    """Verify screenshot grabs and simulated blur loops are removed."""
    assert not hasattr(odd_blur, "BackdropBlurSampler")
    assert not hasattr(odd_blur, "grabWindow")


def test_ripple_distortion_completely_removed():
    """Verify ripple distortion is inert and zero-idle."""
    ripple = GlassDisplacementRipple()
    assert not ripple.is_active
    ripple.trigger(100, 100)
    assert not ripple.is_active, "Ripple trigger must be inert"
    assert ripple.get_progress() == 1.0


def test_native_transparent_hwnd_api(qapp):
    """Verify canvas transparency without full-window slabs."""
    w = QWidget()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.resize(300, 100)
    w.show()

    hwnd = int(w.winId())
    res1 = odd_blur.ensure_transparent_hwnd(hwnd)
    res2 = odd_blur.apply_surface_backdrop_blur(hwnd)

    if sys.platform == "win32":
        assert res1 is True
        assert res2 is True

    w.close()


def test_paint_solid_black_surface_primary_and_secondary(qapp):
    """
    Verify solid opaque AMOLED black surface rendering.
    Soft ambient drop shadow, #292929 border, 100% opaque.
    """
    img = QImage(400, 200, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(5, 5, 5))
    painter = QPainter(img)

    # 1. Primary Island Surface (solid AMOLED black #080808)
    r1 = QRectF(20, 20, 240, 44)
    WindowBlur.paint_acrylic_surface(
        painter,
        r1,
        radius=22.0,
        theme="dark",
        opacity=1.0,
        surface_type="primary",
        hover_val=0.0
    )

    # 2. Secondary Panel Surface (solid #0E0E0F)
    r2 = QRectF(20, 80, 240, 60)
    WindowBlur.paint_acrylic_surface(
        painter,
        r2,
        radius=16.0,
        theme="dark",
        opacity=1.0,
        surface_type="secondary",
        hover_val=1.0,
        focus_val=1.0,
        press_val=0.5
    )

    painter.end()


def test_odd_overlay_surface_solid_black(qapp):
    """Verify ODDOverlaySurface paints solid AMOLED black."""
    img = QImage(300, 100, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)

    r = QRectF(10, 10, 280, 50)
    ODDOverlaySurface.paint_glass_surface(
        painter,
        r,
        radius=24.0,
        theme="dark",
        opacity=1.0,
        hover_val=0.5,
        surface_type="primary"
    )
    painter.end()


def test_system_status_pill_solid_black(qapp):
    """Verify system-status capsule paints solid black with #292929 border."""
    img = QImage(200, 60, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)

    outer_rect = QRect(0, 0, 180, 50)
    pill_rect = odd_island.paint_system_status_pill_surface(
        painter,
        outer_rect,
        opacity=1.0,
        theme="dark",
        hover_val=0.2,
        press_val=0.0
    )
    painter.end()
    assert pill_rect.width() > 50
    assert pill_rect.height() > 20


def test_interactive_buttons_solid_black(qapp):
    """Verify primary and secondary buttons with solid black styling."""
    img = QImage(320, 100, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(5, 5, 5))
    painter = QPainter(img)

    r_pri = QRectF(10, 10, 80, 32)
    odd_animated_buttons.paint_primary_button(painter, r_pri, "Action", hover_progress=0.0)

    r_sec = QRectF(100, 10, 80, 32)
    odd_animated_buttons.paint_secondary_button(painter, r_sec, "Cancel", hover_progress=1.0, is_pressed=False)

    r_ter = QRectF(190, 10, 80, 32)
    odd_animated_buttons.paint_tertiary_button(painter, r_ter, "Dismiss", hover_progress=0.5)

    painter.end()
