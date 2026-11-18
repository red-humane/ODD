import sys
import os
import pytest
from PySide6.QtCore import QRectF, QRect, QPoint, QPointF, Qt
from PySide6.QtWidgets import QApplication

from odd_theme import (
    Tokens,
    create_squircle_path,
    create_top_anchored_squircle_path,
    calculate_dynamic_squircle_radius
)
from odd_search import WindowsSearchEngine, clipboard_mgr, SearchItem

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

def test_top_anchored_squircle_path():
    """Verify that top-anchored squircle path is shape-aware and excludes transparent corners."""
    rect = QRectF(100, 0, 400, 60)
    bottom_radius = 28.0
    top_radius = 4.0
    path = create_top_anchored_squircle_path(rect, bottom_radius, top_radius)

    # 1. Interior points must be inside
    assert path.contains(QPointF(300, 30)) is True
    assert path.contains(QPointF(200, 10)) is True

    # 2. Bottom corners outside the curved superellipse must be False (transparent pixels)
    # The extreme bottom-left corner of the bounding box is (100, 60)
    assert path.contains(QPointF(100.0, 60.0)) is False
    assert path.contains(QPointF(101.0, 59.0)) is False
    # Extreme bottom-right corner of the bounding box is (500, 60)
    assert path.contains(QPointF(500.0, 60.0)) is False
    assert path.contains(QPointF(499.0, 59.0)) is False

    # 3. Points completely outside the rectangle must be False
    assert path.contains(QPointF(50, 30)) is False
    assert path.contains(QPointF(550, 30)) is False
    assert path.contains(QPointF(300, 70)) is False

def test_smart_clipboard_pinning_and_links():
    """Verify Smart Clipboard links, pinning, and ordering."""
    clipboard_mgr.clear()

    # Add diverse items
    clipboard_mgr.add_clip("https://google.com", source="Browser")
    clipboard_mgr.add_clip("Important project notes", source="Editor")
    clipboard_mgr.add_clip("[Files] document.pdf", source="Explorer")

    assert len(clipboard_mgr.history) == 3
    assert clipboard_mgr.history[0]["is_files"] is True
    assert clipboard_mgr.history[2]["is_link"] is True

    # Test Pinning
    assert clipboard_mgr.toggle_pin("Important project notes") is True
    assert clipboard_mgr.history[1]["pinned"] is True

    # Search with clip:
    engine = WindowsSearchEngine()
    results = engine.search("clip:")
    assert len(results) >= 3

    # Pinned item must appear first
    assert "Pinned" in results[0].title or "Pinned" in results[0].subtitle
    assert "Important project notes" in results[0].title

def test_screen_intelligence_search_queries():
    """Verify Screen Intelligence queries (ocr:, snip:)."""
    engine = WindowsSearchEngine()
    results_ocr = engine.search("ocr:")
    assert len(results_ocr) >= 1
    assert any("OCR" in r.title for r in results_ocr)

    results_snip = engine.search("snip:")
    assert len(results_snip) >= 1
    assert any("SCREEN INTELLIGENCE" in r.category.upper() for r in results_snip)

def test_overlay_shape_aware_hit_test(qapp):
    """Verify that OddOverlay accurately returns HTTRANSPARENT outside visible surface."""
    from odd_overlay import OddOverlay, EdgeTriggerWindow

    settings = {
        "hotkey": "Win+Alt",
        "edge": "top",
        "edge_trigger_mode": "hover",
        "replace_windows_search": False,
        "adapt_to_browser_controls": True,
    }
    engine = WindowsSearchEngine()
    overlay = OddOverlay(engine, settings)

    # When not open: is_cursor_in_active_zone must always return False
    assert overlay.is_cursor_in_active_zone(QPoint(500, 20)) is False

    # When opened
    overlay.is_open = True
    overlay.show()
    overlay.pill_column.resize(400, 60)
    overlay.pill_column.move(100, 0)
    overlay.pill_column.show()

    # Global position inside pill
    global_pt_inside = overlay.mapToGlobal(QPoint(300, 30))
    assert overlay.is_cursor_in_active_zone(global_pt_inside) is True

    # Global position in empty space far below the island
    global_pt_empty = overlay.mapToGlobal(QPoint(300, 150))
    assert overlay.is_cursor_in_active_zone(global_pt_empty) is False

    overlay.hide()
    overlay.is_open = False

def test_edge_trigger_clickthrough(qapp):
    """Verify EdgeTriggerWindow resting pill click-through outside physical bar."""
    from odd_overlay import OddOverlay, EdgeTriggerWindow

    settings = {
        "hotkey": "Win+Alt",
        "edge": "top",
        "edge_bar_width": 75,
        "edge_bar_thickness": 4,
    }
    engine = WindowsSearchEngine()
    overlay = OddOverlay(engine, settings)
    trigger = EdgeTriggerWindow(overlay, settings)

    pill = trigger._resting_pill_rect()
    center_local = pill.center()
    center_global = trigger.mapToGlobal(center_local)

    # Over physical bar: True
    assert trigger._is_point_on_bar(center_global) is True

    # Far to the left of the physical bar (where Chrome tabs are): must be False!
    far_tab_global = trigger.mapToGlobal(QPoint(pill.left() - 60, pill.center().y()))
    assert trigger._is_point_on_bar(far_tab_global) is False

    trigger.hide()
