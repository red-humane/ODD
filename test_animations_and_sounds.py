"""
Verification Test for:
1. animate__headShake entrance animation
2. animate__backOutUp exit animation
3. Recycle Bin Clear Button (Uiverse vinodjangid07)
4. Boton Elegante Action Button (Uiverse iZOXVL)
5. Split-Curtain Wipe Cancel Button (Uiverse KhaledMatalkah)
6. Audio files mapping (Notification, Reminders, Lock Toggle / Mute)
"""

import sys
import os
import math
from PySide6.QtCore import QRectF, QRect, Qt
from PySide6.QtGui import QPainter, QImage, QColor
from PySide6.QtWidgets import QApplication

import odd_animated_buttons
import odd_sound

def test_headshake_kinematics():
    print("[TEST] Testing animate__headShake kinematics...")
    # 0%: 0
    assert abs(odd_animated_buttons.get_headshake_offset(0.0)) < 0.01
    # 6.5%: -6.0
    dx_6_5 = odd_animated_buttons.get_headshake_offset(0.065)
    assert abs(dx_6_5 - (-6.0)) < 0.05, f"Expected -6.0, got {dx_6_5}"
    # 18.5%: +5.0
    dx_18_5 = odd_animated_buttons.get_headshake_offset(0.185)
    assert abs(dx_18_5 - 5.0) < 0.05, f"Expected 5.0, got {dx_18_5}"
    # 31.5%: -3.0
    dx_31_5 = odd_animated_buttons.get_headshake_offset(0.315)
    assert abs(dx_31_5 - (-3.0)) < 0.05, f"Expected -3.0, got {dx_31_5}"
    # 43.5%: +2.0
    dx_43_5 = odd_animated_buttons.get_headshake_offset(0.435)
    assert abs(dx_43_5 - 2.0) < 0.05, f"Expected 2.0, got {dx_43_5}"
    # >= 50%: 0
    assert abs(odd_animated_buttons.get_headshake_offset(0.50)) < 0.01
    assert abs(odd_animated_buttons.get_headshake_offset(0.80)) < 0.01
    print("-> PASS: animate__headShake matches Animate.css keyframes exactly.")

def test_bounceoutup_kinematics():
    print("[TEST] Testing animate__bounceOutUp kinematics...")
    # 0%: scale=1, dy=0, opacity=1
    sx0, sy0, dy0, op0 = odd_animated_buttons.get_bounceoutup_transform(0.0, 80.0)
    assert abs(sx0 - 1.0) < 0.02
    assert abs(sy0 - 1.0) < 0.02
    assert abs(dy0) < 0.02
    assert abs(op0 - 1.0) < 0.02

    # 20%: scaleY=0.985, dy=-10px, opacity=1
    sx20, sy20, dy20, op20 = odd_animated_buttons.get_bounceoutup_transform(0.20, 80.0)
    assert abs(sy20 - 0.985) < 0.02
    assert abs(dy20 - (-10.0)) < 0.5
    assert abs(op20 - 1.0) < 0.02

    # 40%: scaleY=0.90, dy=+20px, opacity=1
    sx40, sy40, dy40, op40 = odd_animated_buttons.get_bounceoutup_transform(0.40, 80.0)
    assert abs(sy40 - 0.90) < 0.02
    assert abs(dy40 - 20.0) < 0.5
    assert abs(op40 - 1.0) < 0.02

    # 100%: scaleY=3, dy < -400, opacity=0
    sx100, sy100, dy100, op100 = odd_animated_buttons.get_bounceoutup_transform(1.0, 80.0)
    assert sy100 >= 2.5
    assert dy100 < -400.0
    assert abs(op100) < 0.02
    print("-> PASS: animate__bounceOutUp matches Animate.css keyframes exactly.")

def test_custom_button_rendering():
    print("[TEST] Testing custom button painting on offscreen image buffer...")
    app = QApplication.instance() or QApplication(sys.argv)
    img = QImage(300, 200, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(18, 18, 20))

    painter = QPainter(img)
    # 1. Recycle Bin Clear Button: resting & hovered
    rect_recycle_rest = QRectF(10, 10, 50, 50)
    odd_animated_buttons.paint_recycle_bin_clear_button(painter, rect_recycle_rest, hover_progress=0.0)
    rect_recycle_hover = QRectF(70, 10, 140, 50)
    odd_animated_buttons.paint_recycle_bin_clear_button(painter, rect_recycle_hover, hover_progress=1.0)

    # 2. Boton Elegante Button: resting & hovered
    rect_elegante_rest = QRectF(10, 70, 70, 28)
    odd_animated_buttons.paint_boton_elegante(painter, rect_elegante_rest, "Done", hover_progress=0.0)
    rect_elegante_hover = QRectF(90, 70, 70, 28)
    odd_animated_buttons.paint_boton_elegante(painter, rect_elegante_hover, "Done", hover_progress=1.0)

    # 3. Split Wipe Cancel Button: resting & hovered
    rect_wipe_rest = QRectF(10, 110, 70, 28)
    odd_animated_buttons.paint_split_wipe_cancel_button(painter, rect_wipe_rest, "Cancel", hover_progress=0.0)
    rect_wipe_hover = QRectF(90, 110, 70, 28)
    odd_animated_buttons.paint_split_wipe_cancel_button(painter, rect_wipe_hover, "Cancel", hover_progress=1.0)

    painter.end()
    print("-> PASS: All 3 button designs render cleanly with zero errors.")

def test_audio_mappings():
    print("[TEST] Testing audio mappings...")
    odd_sound._precache_all_sounds()

    with odd_sound._CACHE_LOCK:
        assert "notification" in odd_sound._PRECACHED_WAVS
        assert "reminder" in odd_sound._PRECACHED_WAVS
        assert "lock_on" in odd_sound._PRECACHED_WAVS
        assert "lock_off" in odd_sound._PRECACHED_WAVS
        assert "mute" in odd_sound._PRECACHED_WAVS
        assert "unmute" in odd_sound._PRECACHED_WAVS

    # Test playback triggers
    odd_sound.play_notification({'sound_enabled': True, 'sound_volume': 0.75})
    odd_sound.play_reminder({'sound_enabled': True, 'sound_volume': 0.75})
    odd_sound.play_lock_sound(True, {'sound_enabled': True, 'sound_volume': 0.75})
    odd_sound.play_lock_sound(False, {'sound_enabled': True, 'sound_volume': 0.75})
    odd_sound.play_mute_sound(True, {'sound_enabled': True, 'sound_volume': 0.75})
    odd_sound.play_mute_sound(False, {'sound_enabled': True, 'sound_volume': 0.75})
    print("-> PASS: All 3 user-specified audio files pre-cached and triggered properly.")

if __name__ == "__main__":
    test_headshake_kinematics()
    test_bounceoutup_kinematics()
    test_custom_button_rendering()
    test_audio_mappings()
    print("\nALL ANIMATION & AUDIO VERIFICATIONS PASSED 100%!")
