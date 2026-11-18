"""
ODD Adaptive Performance Tier Engine
Automatically categorizes host hardware into HIGH, MEDIUM, or LOW tiers
and dynamically scales graphics, blurs, shadows, animation rates, and memory
caches so ODD runs buttery-smooth on dual-core 4GB RAM low-end PCs.
"""

import os
import time
import sys
from typing import Optional
from enum import IntEnum
from PySide6.QtCore import QObject, Signal

from odd_crash_capture import log_breadcrumb, logger, safe_slot


class QualityTier(IntEnum):
    LOW = 0       # Low-end PCs (<=4 GB RAM, dual-core, integrated GPU, HDD)
    MEDIUM = 1    # Mid-range systems (8 GB RAM, quad-core)
    HIGH = 2      # Modern PCs (16+ GB RAM, dedicated GPU / modern APU)


class TierManager(QObject):
    tier_changed = Signal(int, str)  # (tier_int, tier_name)

    _instance = None

    @classmethod
    def get_instance(cls, settings: Optional[dict] = None) -> "TierManager":
        if cls._instance is None:
            cls._instance = TierManager(settings or {})
        return cls._instance

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings or {}
        self._manual_override = self.settings.get("perf_tier", "auto").lower()  # "auto", "high", "medium", "low"
        self._reduce_motion = bool(self.settings.get("reduce_motion", False))

        # Hardware metrics
        self._cpu_count = os.cpu_count() or 2
        self._total_ram_gb = self._detect_ram_gb()

        # Benchmarked / detected tier
        self._detected_tier = self._detect_initial_tier()
        self._current_tier = self._resolve_active_tier()

        # Live frame time watchdog for automatic tier step-down
        self._slow_frames_count = 0
        self._recent_frame_times = []
        self._last_degrade_ts = 0.0

        log_breadcrumb(
            f"Hardware Tier Resolved: {self.get_tier_name()} (CPUs={self._cpu_count}, RAM={self._total_ram_gb:.1f}GB)",
            category="tier"
        )

    def _detect_ram_gb(self) -> float:
        try:
            import psutil
            return psutil.virtual_memory().total / (1024 ** 3)
        except Exception:
            return 8.0

    def _detect_initial_tier(self) -> QualityTier:
        """
        Calculates baseline performance tier from CPU count, RAM, and quick benchmark.
        Low tier: <= 4 GB RAM or <= 2 CPU cores.
        Medium tier: <= 8 GB RAM or <= 4 CPU cores.
        High tier: > 8 GB RAM and > 4 CPU cores.
        """
        # Quick benchmark: measure CPU clock jitter over 1500 iterations
        t0 = time.perf_counter()
        acc = 0.0
        for i in range(1500):
            acc += (i * 0.001) ** 0.5
        bench_time_ms = (time.perf_counter() - t0) * 1000.0

        if self._total_ram_gb <= 4.5 or self._cpu_count <= 2 or bench_time_ms > 4.5:
            return QualityTier.LOW
        elif self._total_ram_gb <= 8.5 or self._cpu_count <= 4 or bench_time_ms > 2.0:
            return QualityTier.MEDIUM
        return QualityTier.HIGH

    def _resolve_active_tier(self) -> QualityTier:
        if self._reduce_motion:
            return QualityTier.LOW

        if self._manual_override == "high":
            return QualityTier.HIGH
        elif self._manual_override == "medium":
            return QualityTier.MEDIUM
        elif self._manual_override == "low":
            return QualityTier.LOW
        return self._detected_tier

    def update_settings(self, new_settings: dict):
        self.settings = new_settings
        self._manual_override = self.settings.get("perf_tier", "auto").lower()
        self._reduce_motion = bool(self.settings.get("reduce_motion", False))
        resolved = self._resolve_active_tier()
        if resolved != self._current_tier:
            self._current_tier = resolved
            self.tier_changed.emit(int(self._current_tier), self.get_tier_name())

    def record_frame_time(self, frame_ms: float):
        """
        Live Adaptive Degradation:
        If measured animation frame time stays above 20 ms for > 1 second (approx 50 frames),
        automatically step down to protect UI responsiveness on low-end systems.
        """
        if self._manual_override != "auto":
            return

        self._recent_frame_times.append(frame_ms)
        if len(self._recent_frame_times) > 60:
            self._recent_frame_times.pop(0)

        if frame_ms > 20.0:
            self._slow_frames_count += 1
        else:
            self._slow_frames_count = max(0, self._slow_frames_count - 1)

        now = time.time()
        if self._slow_frames_count >= 50 and (now - self._last_degrade_ts > 15.0):
            if self._current_tier > QualityTier.LOW:
                self._current_tier = QualityTier(int(self._current_tier) - 1)
                self._last_degrade_ts = now
                self._slow_frames_count = 0
                log_breadcrumb(f"Auto-degraded performance tier to {self.get_tier_name()}", category="tier")
                self.tier_changed.emit(int(self._current_tier), self.get_tier_name())

    # --- Feature Queries for Rendering & Animations ---

    @property
    def tier(self) -> QualityTier:
        return self._current_tier

    @property
    def current_tier(self) -> QualityTier:
        return self._current_tier

    def get_tier_name(self) -> str:
        return self._current_tier.name

    @property
    def enable_dwm_blur(self) -> bool:
        """Only apply heavy DWM acrylic/blur on HIGH tier; disabled on weak/integrated GPUs."""
        return self._current_tier == QualityTier.HIGH

    @property
    def enable_gooey_effects(self) -> bool:
        """Liquid-goo droplet simulation enabled only on HIGH tier."""
        return self._current_tier == QualityTier.HIGH

    @property
    def enable_shadows(self) -> bool:
        return self._current_tier != QualityTier.LOW

    @property
    def enable_fluid_springs(self) -> bool:
        return not self._reduce_motion and self._current_tier != QualityTier.LOW

    @property
    def target_fps(self) -> int:
        if self._current_tier == QualityTier.LOW:
            return 30
        elif self._current_tier == QualityTier.MEDIUM:
            return 60
        return 60

    @property
    def max_search_results(self) -> int:
        if self._current_tier == QualityTier.LOW:
            return 6
        elif self._current_tier == QualityTier.MEDIUM:
            return 8
        return 10

    @property
    def icon_cache_limit(self) -> int:
        if self._current_tier == QualityTier.LOW:
            return 80
        elif self._current_tier == QualityTier.MEDIUM:
            return 200
        return 500

    @property
    def spring_substeps(self) -> int:
        if self._current_tier == QualityTier.LOW:
            return 1
        return 2
