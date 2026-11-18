"""
Automated Unit & Integration Tests for Redesigned E2U ODD Radial Arc Menu
with Dedicated Dynamic-Island-Style Search UI and Liquid Morphing
"""

import sys
import os
import time
import pytest
from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui import QKeyEvent, QMouseEvent, QGuiApplication
from PySide6.QtWidgets import QApplication

from odd_radial_menu import (
    RadialHoldIndicator, OddRadialArcMenu, ArcMorphToOverlayAnimation,
    DedicatedRadialSearchPanel, ContextualSearchPanel, ContextualQuickSettingsPanel,
    ContextualPhoneMirrorPanel, RadialSummonController, is_caret_or_text_focused, is_mouse_dragging
)
from odd_settings import DEFAULT_SETTINGS
from odd_search import SearchItem


class MockSearchEngine:
    def search(self, query, max_results=6):
        return [
            SearchItem(
                id="calc",
                title=f"Result for {query}",
                subtitle="Calculated answer",
                category="math",
                target="42",
                action=lambda: None
            ),
            SearchItem(
                id="app_1",
                title=f"Application {query}",
                subtitle="C:\\Program Files\\App.exe",
                category="app",
                target="app",
                action=lambda: None
            )
        ]


class MockOverlay:
    def __init__(self):
        self.settings = DEFAULT_SETTINGS.copy()
        self.is_open = False
        self.is_animating = False
        self.lens_started = False
        self.phone_mirror_clicked = False
        self.settings_opened = False
        self.quick_settings_opened = False
        self.search_engine = MockSearchEngine()

    def surface(self, from_key=False):
        self.is_open = True

    def sink(self):
        self.is_open = False

    def ensure_focus(self):
        pass

    def start_google_lens_search(self):
        self.lens_started = True

    def toggle_android_mirror_panel(self, force_show_guide=False):
        self.phone_mirror_clicked = True

    def toggle_quick_settings_panel(self):
        self.quick_settings_opened = True

    def on_open_settings(self, origin=None):
        self.settings_opened = True

    def get_current_theme(self):
        return "dark"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app


def test_compact_arc_dimensions_and_no_center_circle(qapp):
    overlay = MockOverlay()
    menu = OddRadialArcMenu(overlay)

    # Verify compact size
    assert menu._canvas_size == 280
    assert menu._r_inner == 34.0
    assert menu._r_outer == 92.0
    assert menu._r_hover_pop == 98.0
    assert len(menu.actions) == 5

    # Center origin is hollow (no large center circle)
    # Cursor inside r_inner (e.g. dist = 10px) reports no hover index (-1)
    event_center = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPoint(140 + 10, 140 + 10),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier
    )
    menu.mouseMoveEvent(event_center)
    assert menu._hover_index == -1


def test_edge_aware_adaptive_positioning(qapp):
    overlay = MockOverlay()
    menu = OddRadialArcMenu(overlay)
    screen = QGuiApplication.primaryScreen()
    s_rect = screen.availableGeometry()

    # Top edge -> Arc opens downward (90°)
    menu.open_at_cursor(QPoint(s_rect.center().x(), s_rect.top() + 20))
    assert menu._center_angle == 90.0
    menu.dismiss(immediate=True)

    # Bottom edge -> Arc opens upward (270°)
    menu.open_at_cursor(QPoint(s_rect.center().x(), s_rect.bottom() - 20))
    assert menu._center_angle == 270.0
    menu.dismiss(immediate=True)

    # Left edge -> Arc opens rightward (0°)
    menu.open_at_cursor(QPoint(s_rect.left() + 20, s_rect.center().y()))
    assert menu._center_angle == 0.0
    menu.dismiss(immediate=True)

    # Right edge -> Arc opens leftward (180°)
    menu.open_at_cursor(QPoint(s_rect.right() - 20, s_rect.center().y()))
    assert menu._center_angle == 180.0
    menu.dismiss(immediate=True)


def test_type_to_search_emits_morph_search(qapp):
    overlay = MockOverlay()
    menu = OddRadialArcMenu(overlay)
    menu.open_at_cursor(QPoint(500, 500))

    received_morph = []
    menu.request_morph_search.connect(lambda pos, text: received_morph.append((pos, text)))

    # User types 'w'
    key_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_W, Qt.KeyboardModifier.NoModifier, "w")
    menu.keyPressEvent(key_event)

    # Arc should dismiss and emit request_morph_search with 'w'
    assert menu.isVisible() is False
    assert len(received_morph) == 1
    assert received_morph[0][1] == "w"


def test_click_search_emits_morph_search(qapp):
    overlay = MockOverlay()
    menu = OddRadialArcMenu(overlay)
    menu.open_at_cursor(QPoint(500, 500))

    received_morph = []
    menu.request_morph_search.connect(lambda pos, text: received_morph.append((pos, text)))

    # Action 2 is Search
    assert menu.actions[2].key == "search"
    menu._trigger_action(menu.actions[2])

    assert menu.isVisible() is False
    assert len(received_morph) == 1
    assert received_morph[0][1] == ""


def test_click_phone_mirror_emits_morph_phone_mirror(qapp):
    overlay = MockOverlay()
    menu = OddRadialArcMenu(overlay)
    menu.open_at_cursor(QPoint(500, 500))

    received_phone = []
    menu.request_morph_phone_mirror.connect(lambda pos: received_phone.append(pos))

    # Action 3 is Phone Mirror
    assert menu.actions[3].key == "phone_mirror"
    menu._trigger_action(menu.actions[3])

    assert menu.isVisible() is False
    assert len(received_phone) == 1


def test_click_quick_settings_emits_morph_quick_settings(qapp):
    overlay = MockOverlay()
    menu = OddRadialArcMenu(overlay)
    menu.open_at_cursor(QPoint(500, 500))

    received_qs = []
    menu.request_morph_quick_settings.connect(lambda pos: received_qs.append(pos))

    # Action 0 is Quick Settings
    assert menu.actions[0].key == "quick_settings"
    menu._trigger_action(menu.actions[0])

    assert menu.isVisible() is False
    assert len(received_qs) == 1


def test_click_odd_settings_opens_settings(qapp):
    overlay = MockOverlay()
    menu = OddRadialArcMenu(overlay)
    menu.open_at_cursor(QPoint(500, 500))

    # Action 4 is Settings (official ODD logo icon: white circle + red dot)
    assert menu.actions[4].key == "settings"
    menu._trigger_action(menu.actions[4])

    assert menu.isVisible() is False
    assert overlay.settings_opened is True


def test_dedicated_radial_search_panel_dynamic_island_style(qapp):
    overlay = MockOverlay()
    panel = DedicatedRadialSearchPanel(overlay)
    panel.open_at_cursor(QPoint(500, 500), initial_text="calc")

    assert panel.isVisible() is True
    assert panel.search_input.text() == "calc"
    assert panel.results_list.isVisible() is True
    assert panel.results_list.count() == 2

    # Verify arrow navigation & Esc dismissal
    key_down = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(key_down)
    assert panel.results_list.currentRow() == 1

    key_esc = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(key_esc)
    assert panel.isVisible() is False


def test_instant_shake_dismiss(qapp):
    overlay = MockOverlay()
    menu = OddRadialArcMenu(overlay, {"radial_shake_dismiss_enabled": True})
    menu.open_at_cursor(QPoint(500, 500))
    assert menu.isVisible() is True

    # Tight 2-reversal fast shake in < 200ms
    now = time.time()
    menu._shake_history = [
        (now - 0.16, 500, 500),
        (now - 0.11, 450, 500),  # dx = -50
        (now - 0.06, 510, 500),  # dx = +60 (reversal 1)
        (now - 0.01, 460, 500),  # dx = -50 (reversal 2)
    ]
    assert menu._check_is_shake() is True


def test_radial_summon_controller_hold_and_morph_to_dedicated_search(qapp):
    overlay = MockOverlay()
    controller = RadialSummonController(overlay, {
        "radial_menu_enabled": True,
        "radial_summon_key": "Alt",
        "radial_summon_hold_ms": 750
    })

    # Hold Alt for 750ms -> Arc appears
    controller.on_global_key_down("alt_l")
    assert controller._is_holding is True

    controller._hold_start_time = time.time() - 0.80
    controller._on_tick()

    assert controller.radial_menu.isVisible() is True

    # User releases Alt -> Arc stays open
    controller.on_global_key_up("alt_l")
    assert controller.radial_menu.isVisible() is True

    # User types 't' -> Morphs Arc into DEDICATED Search Panel
    key_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_T, Qt.KeyboardModifier.NoModifier, "t")
    controller.radial_menu.keyPressEvent(key_event)

    assert controller.radial_menu.isVisible() is False
    assert controller.morph_anim.isVisible() is True

    # Fast forward morph anim
    controller.morph_anim._start_time = time.time() - 0.20
    controller.morph_anim._step()

    # Verify dedicated search panel is opened with 't' and search input has focus!
    assert controller.search_panel.isVisible() is True
    assert controller.search_panel.search_input.text() == "t"
    assert controller.search_panel.results_list.isVisible() is True

    # Clean up
    controller.search_panel.dismiss(immediate=True)
    assert controller.search_panel.isVisible() is False


def test_dedicated_phone_mirror_panel_and_category_search_isolation(qapp):
    overlay = MockOverlay()
    controller = RadialSummonController(overlay, {
        "radial_menu_enabled": True,
        "radial_summon_key": "Alt"
    })

    # 1. Test dedicated phone mirror panel opens without opening top overlay
    assert hasattr(controller, "phone_panel")
    controller._on_morph_phone_mirror(QPoint(400, 400))
    assert controller.phone_panel.isVisible() is True
    assert overlay.is_open is False  # Top search bar overlay was NOT opened!
    controller.phone_panel.dismiss(immediate=True)
    assert controller.phone_panel.isVisible() is False

    # 2. Test category search isolation: apps: must only return apps!
    panel = DedicatedRadialSearchPanel(overlay, {})
    panel.open_at_cursor(QPoint(300, 300))
    
    # Empty query should show shortcut buttons
    assert panel.empty_widget.isVisible() is True

    # Type "apps: test" -> search engine returns math and app, but math must be filtered out!
    panel._do_search("apps: test")
    assert len(panel._current_results) == 1
    assert panel._current_results[0].category == "app"
    assert panel.results_list.isVisible() is True

    # Clean up
    panel.dismiss(immediate=True)


def test_dedicated_search_panel_compact_empty_height(qapp):
    overlay = MockOverlay()
    panel = DedicatedRadialSearchPanel(overlay, {})
    panel.open_at_cursor(QPoint(300, 300))

    # Empty panel height should be snug (244px) instead of 380px, eliminating bottom void
    assert panel.height() == 244
    assert panel.card_frame.height() == 224
    assert hasattr(panel, "_anim_open")
    assert panel._anim_open.duration() == 140
    panel.dismiss(immediate=True)


def test_dedicated_search_panel_nonblocking_debounce(qapp):
    overlay = MockOverlay()
    panel = DedicatedRadialSearchPanel(overlay, {})
    panel.open_at_cursor(QPoint(300, 300))

    # Rapid typing starts the debounce timer without blocking GUI thread
    panel.search_input.setText("f")
    assert panel._search_debounce_timer.isActive() is True

    # Immediate category prefix provides instant defaults
    panel.search_input.setText("apps:")
    assert panel.results_list.isVisible() is True
    assert panel.results_list.count() > 0
    panel.dismiss(immediate=True)


def test_contextual_panels_subtle_animations(qapp):
    overlay = MockOverlay()
    qs = ContextualQuickSettingsPanel(overlay, {})
    qs.open_at_cursor(QPoint(300, 300))
    assert hasattr(qs, "_anim_open")
    assert qs._anim_open.duration() == 140
    qs.dismiss(immediate=True)

    pm = ContextualPhoneMirrorPanel(overlay, {})
    pm.open_at_cursor(QPoint(300, 300))
    assert hasattr(pm, "_anim_open")
    assert pm._anim_open.duration() == 140
    pm.dismiss(immediate=True)


def test_radial_menu_bottom_music_overlay_and_no_mouse_progress(qapp):
    overlay = MockOverlay()
    overlay.media_state = {
        "has_media": True,
        "title": "Starboy",
        "artist": "The Weeknd",
        "is_playing": True
    }

    # 1. Verify cursor hold indicator has no music progress running
    hold = RadialHoldIndicator()
    hold.set_music_state(True, 0.5)
    assert hold.isVisible() is False  # Cursor indicator does NOT show music progress!

    # 2. Verify radial menu hosts minimal bottom music bar
    menu = OddRadialArcMenu(overlay, {})
    menu.open_at_cursor(QPoint(500, 500))
    assert hasattr(menu, "music_bar")
    assert menu.music_bar.isVisible() is True
    assert "Starboy" in menu.music_bar.title_label.text()
    assert menu.music_bar.btn_play.toolTip() == "Pause"

    # Toggle play/pause button on bottom music bar
    menu.music_bar.btn_play.click()
    assert menu.music_bar.btn_play.toolTip() == "Play"

    menu.dismiss(immediate=True)


def test_top_hover_suppression_and_settings_radial_restructure(qapp):
    """
    Verifies that:
    1. In SearchOverlayWindow, calling surface(from_key=False) while radial_menu_enabled is True
       is suppressed and does NOT trigger the search panel.
    2. Settings dialog has 'Radial Arc & Cursor' as Index 0 in nav_defs and pages.
    3. All radial controls and contextual overlay toggles exist and are initialized.
    """
    from unittest.mock import MagicMock
    from odd_settings_dialog import SettingsDialog
    from odd_overlay import OddOverlay

    # 1. Test surface suppression when hovering (from_key=False)
    mock_overlay = MagicMock(spec=OddOverlay)
    mock_overlay.settings = {"radial_menu_enabled": True}
    rc = MagicMock()
    mock_overlay.radial_controller = rc

    # Calling original surface logic on mock
    OddOverlay.surface(mock_overlay, from_key=False)
    assert rc.search_panel.open_at_cursor.call_count == 0, "Top hover should not open search panel!"

    # Calling from key should open search panel
    OddOverlay.surface(mock_overlay, from_key=True)
    assert rc.search_panel.open_at_cursor.call_count == 1, "Hotkey should open search panel!"

    # 2. Test settings restructuring
    from odd_settings import DEFAULT_SETTINGS
    dlg = SettingsDialog(DEFAULT_SETTINGS.copy())
    assert dlg.nav_defs[0][0] == "Radial Arc & Cursor", f"Index 0 must be Radial Arc & Cursor, got {dlg.nav_defs[0][0]}"
    assert dlg.pages.count() == 6, f"Expected 6 pages, got {dlg.pages.count()}"

    # Verify all radial settings widgets are initialized
    assert hasattr(dlg, "chk_radial_menu")
    assert hasattr(dlg, "combo_radial_key")
    assert hasattr(dlg, "slider_radial_hold")
    assert hasattr(dlg, "chk_radial_magic")
    assert hasattr(dlg, "chk_radial_shake")
    assert hasattr(dlg, "chk_radial_search")
    assert hasattr(dlg, "chk_radial_qs")
    assert hasattr(dlg, "chk_radial_phone")
    assert hasattr(dlg, "chk_radial_bottom_music")

    assert dlg.chk_radial_menu.isChecked() is True
    assert dlg.chk_radial_bottom_music.isChecked() is True
    assert dlg.chk_radial_search.isChecked() is True

    # Check Homepage 3x2 grid has 6 cards
    assert len(dlg._home_cards) == 6
    dlg.close()


if __name__ == "__main__":
    pytest.main(["-v", __file__])
