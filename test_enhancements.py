import time
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication
from odd_overlay import OddOverlay
from odd_radial_menu import OddRadialArcMenu, DedicatedRadialSearchPanel, ContextualQuickSettingsPanel
from odd_island import OddBezelHUD
from odd_search import WindowsSearchEngine
import pytest

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

class DummySearchEngine:
    def __init__(self):
        pass
    def set_prefixes(self, p):
        pass

def test_media_overlay_only_when_playing(qapp):
    settings = {
        "enable_music_overlay": True,
        "music_overlay_mode": "auto",
        "paused_media_behavior": "button_only",
    }
    overlay = OddOverlay(DummySearchEngine(), settings)
    
    # When no media is playing
    overlay.media_state = {"is_playing": False, "title": "Some Song", "artist": "Artist"}
    assert overlay._should_show_minimal_music() is False

    # When media is actively playing
    overlay.media_state = {"is_playing": True, "title": "Some Song", "artist": "Artist"}
    assert overlay._should_show_minimal_music() is True

    # When paused again
    overlay.media_state = {"is_playing": False, "title": "Some Song", "artist": "Artist"}
    assert overlay._should_show_minimal_music() is False

def test_overlay_shake_detection(qapp):
    settings = {}
    overlay = OddOverlay(DummySearchEngine(), settings)
    now = time.time()
    overlay._shake_history = [
        (now - 0.16, 500, 500),
        (now - 0.11, 450, 500),  # dx = -50
        (now - 0.06, 510, 500),  # dx = +60 (reversal 1)
        (now - 0.01, 460, 500),  # dx = -50 (reversal 2)
    ]
    assert overlay._check_is_shake() is True

def test_search_pill_close_button_exists(qapp):
    settings = {"ui_theme_style": "classic"}
    overlay = OddOverlay(DummySearchEngine(), settings)
    assert hasattr(overlay.search_pill, "btn_close")
    assert overlay.search_pill.btn_close is not None
    assert overlay.search_pill.btn_close.icon_type == "close"

def test_notification_hud_redesign_sizing(qapp):
    hud = OddBezelHUD({"theme": "dark", "island_show_system_notifications": True})
    hud.show_notification_hud("Battery Alert", "Battery is at 20%", duration_ms=3000, force=True)
    assert hud.hud_type == "notification"
    assert hud.hud_data["title"] == "Battery Alert"
    assert hud.hud_data["icon_type"] == "battery"
    assert hud.width() >= 330
    assert hud.hud_data["full_height"] >= 68
    assert hud.hud_data["intro_height"] == 46
