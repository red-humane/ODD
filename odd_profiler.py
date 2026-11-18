"""
ODD Performance Instrumentation Layer
- Main-thread Watchdog: detects any event-loop stall > 16ms with live stack trace
- Animation FPS Counter: measures true frame intervals and dropped frames
- Latency probes for Search keystroke-to-render and Slider drag handling
"""

import sys
import os
import time
import threading
import traceback
from typing import Optional

class MainThreadWatchdog:
    """
    Monitors the main Qt GUI thread. If the event loop is blocked for more than
    stall_threshold_ms (default: 16ms = 1 frame at 60 FPS), dumps the exact
    active call stack to stdout and a profile log.
    """
    def __init__(self, stall_threshold_ms: float = 16.0, check_interval_ms: float = 4.0):
        self.stall_threshold_sec = stall_threshold_ms / 1000.0
        self.check_interval_sec = check_interval_ms / 1000.0
        self._main_thread_id = threading.main_thread().ident
        self._last_ping_time = time.perf_counter()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stall_count = 0
        self._log_path = os.path.join(os.environ.get("APPDATA", ""), "ODD", "profiler_stalls.log")

    def ping(self):
        """Called regularly by a 0ms or short QTimer on the main thread."""
        self._last_ping_time = time.perf_counter()

    def start(self):
        if self._running:
            return
        self._running = True
        self._last_ping_time = time.perf_counter()
        self._monitor_thread = threading.Thread(target=self._run_watchdog, daemon=True, name="MainThreadWatchdog")
        self._monitor_thread.start()
        print(f"[PROFILER] Watchdog started (alert threshold: {self.stall_threshold_sec*1000:.1f}ms).")

    def stop(self):
        self._running = False

    def _run_watchdog(self):
        while self._running:
            time.sleep(self.check_interval_sec)
            now = time.perf_counter()
            elapsed = now - self._last_ping_time
            if elapsed > self.stall_threshold_sec:
                self._stall_count += 1
                # Capture the main thread stack
                frames = sys._current_frames()
                main_frame = frames.get(self._main_thread_id)
                stack_lines = traceback.format_stack(main_frame) if main_frame else ["<no stack available>"]
                stack_str = "".join(stack_lines[-6:])  # show top 6 frames for brevity
                
                msg = f"\n[WATCHDOG STALL #{self._stall_count}] Main thread frozen for {elapsed*1000:.1f} ms!\n{stack_str}"
                sys.stderr.write(msg + "\n")
                try:
                    with open(self._log_path, "a", encoding="utf-8") as f:
                        f.write(f"\n--- STALL #{self._stall_count} ({elapsed*1000:.1f}ms) at {time.strftime('%H:%M:%S')} ---\n")
                        f.write("".join(traceback.format_stack(main_frame)))
                except Exception:
                    pass
                # Reset to prevent spamming for the same continuous stall
                self._last_ping_time = now


class AnimationFPSCounter:
    """
    Measures frame-to-frame intervals and reports rolling FPS and dropped frames.
    """
    def __init__(self, name: str = "Animation"):
        self.name = name
        self.frame_times = []
        self._last_frame_ts = 0.0
        self.dropped_frames = 0
        self.total_frames = 0

    def tick(self):
        now = time.perf_counter()
        if self._last_frame_ts > 0.0:
            delta_ms = (now - self._last_frame_ts) * 1000.0
            self.frame_times.append(delta_ms)
            self.total_frames += 1
            if delta_ms > 19.0:  # took longer than ~52 FPS frame budget (16.6ms is 60fps)
                self.dropped_frames += 1
            if len(self.frame_times) > 60:
                self.frame_times.pop(0)
        self._last_frame_ts = now

    def reset(self):
        self.frame_times.clear()
        self._last_frame_ts = 0.0
        self.dropped_frames = 0
        self.total_frames = 0

    def report(self) -> str:
        if not self.frame_times:
            return f"[{self.name}] No frames recorded."
        avg_ms = sum(self.frame_times) / len(self.frame_times)
        fps = 1000.0 / avg_ms if avg_ms > 0 else 0
        max_ms = max(self.frame_times)
        return (f"[{self.name}] Average FPS: {fps:.1f} ({avg_ms:.2f}ms/frame) | "
                f"Peak Frame Time: {max_ms:.2f}ms | Dropped (>19ms): {self.dropped_frames}/{self.total_frames}")


_watchdog_instance: Optional[MainThreadWatchdog] = None
_fps_counter_instance = AnimationFPSCounter("CapsuleSpring")

def get_watchdog() -> MainThreadWatchdog:
    global _watchdog_instance
    if _watchdog_instance is None:
        _watchdog_instance = MainThreadWatchdog(stall_threshold_ms=16.0)
    return _watchdog_instance

def get_fps_counter() -> AnimationFPSCounter:
    return _fps_counter_instance

def record_search_latency(query: str, elapsed_ms: float, count: int):
    status = "OK" if elapsed_ms <= 16.0 else ("SLOW" if elapsed_ms <= 50.0 else "FREEZE")
    print(f"[PROFILER][SEARCH] '{query}' -> {count} items in {elapsed_ms:.2f} ms [{status}]")

def record_slider_latency(kind: str, val: int, elapsed_ms: float):
    status = "OK" if elapsed_ms <= 8.0 else "SLOW"
    print(f"[PROFILER][SLIDER] {kind}={val} dispatched in {elapsed_ms:.2f} ms [{status}]")
