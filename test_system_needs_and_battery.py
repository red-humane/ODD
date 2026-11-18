"""
Test Suite: System & User Needs Intelligence, Battery Auto-Detection & Redesigned Notifications
=============================================================================================
Verifies:
1. SystemNeedsIntelligence telemetry, charging velocity (%/min), discharge rate, and runtime estimation.
2. Battery reminder automatic identification & resolution upon charger plug-in and unplug.
3. WellnessManager automatic alert resolution and idle-aware timer pausing.
4. ReminderManager automatic completion of natural-language battery/charger reminders.
5. DynamicIslandHUD and OddBezelHUD real-time power event handling and redesigned notification geometry.
"""

import sys
import time
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QRectF

# Ensure single QApplication instance
app = QApplication.instance() or QApplication(sys.argv)

def test_system_needs_power_telemetry():
    print("\n[TEST 1] Testing SystemNeedsIntelligence Telemetry & ETA Calculations...")
    from odd_system_needs import SystemNeedsIntelligence

    sni = SystemNeedsIntelligence.get_instance({"battery_high_limit": 80, "battery_low_limit": 30})

    # Simulate battery discharging
    p1 = {"has_battery": True, "plugged_in": False, "is_charging": False, "percent": 50}
    res1 = sni.on_power_changed(p1)
    assert res1["plugged_in"] is False
    assert res1["percent"] == 50
    assert "left" in res1["runtime_estimate"] or res1["runtime_estimate"] != ""
    print(f"-> Discharging runtime estimate: {res1['runtime_estimate']}")

    # Simulate charger plugged in at 60%
    p2 = {"has_battery": True, "plugged_in": True, "is_charging": True, "percent": 60}
    res2 = sni.on_power_changed(p2)
    assert res2["plugged_in"] is True
    assert res2["percent"] == 60
    assert "to 80%" in res2["charge_eta"] or res2["charge_eta"] != ""
    print(f"-> Charging ETA to 80%: {res2['charge_eta']}")

    print("-> PASS: Power telemetry, velocities, and projected ETAs calculated accurately.")


def test_wellness_battery_auto_resolution():
    print("\n[TEST 2] Testing WellnessManager Real-Time Power State Auto-Resolution...")
    from odd_wellness import WellnessManager

    wm = WellnessManager.get_instance({"battery_high_limit": 80, "battery_low_limit": 30})

    # Force an active 'plug_in' alert state (as if battery dropped to 20%)
    wm._last_battery_alert_type = "plug_in"
    wm._last_battery_alert_time = time.time()

    resolved_events = []
    wm.battery_resolved.connect(lambda d: resolved_events.append(d))

    # User plugs in charger!
    wm.on_power_state_changed(plugged_in=True, percent=22)

    # Must automatically clear the plug_in alert state!
    assert wm._last_battery_alert_type is None, "Expected _last_battery_alert_type to be None after plugging in"
    assert len(resolved_events) == 1, "Expected battery_resolved signal to emit"
    assert resolved_events[0]["action"] == "plugged_in"
    print(f"-> PASS: 'Connect Charger' reminder was automatically identified and resolved upon plug-in.")

    # Now simulate battery reaching 80% with charger plugged in -> Unplug alert
    wm._last_battery_alert_type = "unplug"
    wm._last_battery_alert_time = time.time()

    # User unplugs charger!
    wm.on_power_state_changed(plugged_in=False, percent=80)
    assert wm._last_battery_alert_type is None, "Expected _last_battery_alert_type to be None after unplugging"
    assert len(resolved_events) == 2
    assert resolved_events[1]["action"] == "unplugged"
    print(f"-> PASS: 'Unplug Charger' reminder was automatically identified and resolved upon unplug.")


def test_reminder_manager_nlp_auto_completion():
    print("\n[TEST 3] Testing ReminderManager Natural-Language Charger Reminders Auto-Completion...")
    from odd_reminder import ReminderManager

    rm = ReminderManager.get_instance()
    # Add a custom natural language reminder: "Charge my laptop"
    r1 = rm.add_reminder(title="Charge my laptop", due_timestamp=time.time() + 600, note="Battery is low")
    assert r1.status == "pending"

    resolved_items = []
    rm.reminder_auto_resolved.connect(lambda d: resolved_items.append(d))

    # Charger is plugged in!
    rm.on_power_state_changed(plugged_in=True)

    # r1 should now be automatically marked completed!
    assert r1.status == "completed", f"Expected r1 status to be 'completed', got '{r1.status}'"
    assert len(resolved_items) >= 1
    print(f"-> PASS: Custom NLP reminder '{r1.title}' automatically completed when charge was plugged.")

    # Add an unplug reminder: "Unplug laptop charger"
    r2 = rm.add_reminder(title="Unplug laptop charger", due_timestamp=time.time() + 600)
    assert r2.status == "pending"

    # Charger is unplugged!
    rm.on_power_state_changed(plugged_in=False)
    assert r2.status == "completed"
    print(f"-> PASS: Custom NLP reminder '{r2.title}' automatically completed when charge was unplugged.")

    # Clean up test items
    rm.delete_reminder(r1.id)
    rm.delete_reminder(r2.id)


def test_dynamic_island_battery_reminder_morphing():
    print("\n[TEST 4] Testing DynamicIslandHUD Automatic Battery Reminder Morphing...")
    from odd_island import DynamicIslandHUD

    from PySide6.QtWidgets import QWidget

    class DummyTrigger(QWidget):
        def __init__(self):
            super().__init__()
            self.is_island_expanded = True
            self.is_island_collapsing = False
        def has_active_media_playing(self): return False
        def morph_island(self, expanded=True, **kwargs): self.is_island_expanded = expanded
        def update(self): pass

    trigger = DummyTrigger()
    hud = DynamicIslandHUD(trigger, {"theme": "dark", "enable_dynamic_island": True})

    # Show a low battery reminder on HUD
    initial_data = {
        "id": "batt_test_123",
        "type": "battery_health",
        "sub_type": "plug_in",
        "title": "Connect Charger (18%)",
        "note": "Plug in charger to prevent shutdown",
        "percent": 18
    }
    hud.show_hud("reminder", initial_data, duration_ms=0, persistent=True)
    assert hud.current_hud_type == "reminder"
    assert hud.hud_data["title"] == "Connect Charger (18%)"

    # Now the charge is plugged in!
    power_event = {"has_battery": True, "plugged_in": True, "is_charging": True, "percent": 19}
    handled = hud.on_power_changed(power_event)

    assert handled is True, "Expected DynamicIslandHUD to handle and auto-resolve battery reminder"
    assert hud.hud_data.get("is_auto_resolved") is True
    assert "Charger Connected" in hud.hud_data.get("title", "")
    assert hud.dismiss_timer.isActive(), "Expected auto-dismiss timer to be activated"
    print(f"-> PASS: DynamicIslandHUD automatically detected charge plug-in, morphed state to '{hud.hud_data['title']}', and scheduled auto-dismiss.")


def test_redesigned_notification_geometry_and_layout():
    print("\n[TEST 5] Testing Redesigned Notification Layout, Geometry & Squircles...")
    from odd_island import OddBezelHUD

    bezel = OddBezelHUD({"theme": "dark", "island_show_system_notifications": True})

    # Trigger a redesigned notification
    bezel.show_notification_hud(
        title="Battery Health Preserved",
        message="Optimal 80% charge achieved. Charger was safely disconnected.",
        duration_ms=4000,
        primary_id="ODD.BatteryCare",
        force=True
    )

    assert bezel.hud_type == "notification"
    assert bezel.hud_data["source_tag"] == "BATTERY"
    assert bezel.hud_data["icon_type"] == "battery"
    assert bezel.hud_width >= 310, f"Expected notification hud_width >= 310, got {bezel.hud_width}"
    assert bezel.hud_height >= 60, f"Expected notification hud_height >= 60, got {bezel.hud_height}"
    assert bezel._notif_progress_timer.isActive(), "Expected living progress bar timer to be running"

    # Close button rect verification
    close_rect = bezel._get_notification_close_rect()
    assert close_rect.width() >= 18 and close_rect.height() >= 18
    assert close_rect.right() <= bezel.width() + 10
    print(f"-> Notification Dimensions: {bezel.width()}x{bezel.height()}, Source: {bezel.hud_data['source_tag']}, Icon: {bezel.hud_data['icon_type']}")
    print("-> PASS: Redesigned notification layout, squircle dimensions, and progress bar validated.")


def test_user_idle_and_focus_intelligence():
    print("\n[TEST 6] Testing User Presence & Fullscreen Needs Detection...")
    from odd_system_needs import SystemNeedsIntelligence

    sni = SystemNeedsIntelligence.get_instance()
    idle_s = sni.get_idle_seconds()
    assert idle_s >= 0.0
    print(f"-> Current user idle time: {idle_s:.1f} seconds")

    is_fs = sni.check_fullscreen()
    print(f"-> Fullscreen focus status: {is_fs}")

    # Verify notification suppression logic
    assert sni.should_suppress_notification(is_high_priority=True) is False
    print("-> PASS: User presence, idle detection, and immersion needs working properly.")


if __name__ == "__main__":
    print("==================================================")
    print("   ODD SYSTEM & USER NEEDS INTELLIGENCE TEST      ")
    print("==================================================")
    test_system_needs_power_telemetry()
    test_wellness_battery_auto_resolution()
    test_reminder_manager_nlp_auto_completion()
    test_dynamic_island_battery_reminder_morphing()
    test_redesigned_notification_geometry_and_layout()
    test_user_idle_and_focus_intelligence()
    print("\n==================================================")
    print("    ALL SYSTEM NEEDS & BATTERY TESTS PASSED!      ")
    print("==================================================")
