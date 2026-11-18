"""
ODD "Calm Hum" Procedural Audio Subsystem & Motion-Coupled Sound Engine
Implements tactile, warm, futuristic sound language for ODD Dynamic Island.
All sounds synthesized procedurally in D minor pentatonic, cached in memory (<8 MB),
with a bounded voice pool, voice-stealing, rate-limiting, and auto-silence guards.
"""

import math
import struct
import io
import wave
import time
import random
import threading
from typing import Dict, List, Optional, Tuple, Any

from PySide6.QtCore import QObject, Signal

from odd_crash_capture import log_breadcrumb, logger, safe_slot
import odd_dsp


# Tonal Center: D Minor Pentatonic Scale
PENTATONIC_FREQS = {
    "D2": 73.42,
    "A2": 110.00,
    "D3": 146.83,
    "F3": 174.61,
    "G3": 196.00,
    "A3": 220.00,
    "C4": 261.63,
    "D4": 293.66,
    "F4": 349.23,
    "G4": 392.00,
    "A4": 440.00,
    "C5": 523.25,
    "D5": 587.33,
}


# =========================================================================
# 1. Procedural Synthesis of the 15 "Calm Hum" Sounds
# =========================================================================

def synth_wake_open(sr: int = 44100) -> bytes:
    """1. WAKE / OPEN: Rising hum glide D3 -> A3 with liquid bloom (320ms)"""
    dur = 0.32
    n = int(sr * dur)
    samples = [0.0] * n
    f_start = PENTATONIC_FREQS["D3"]
    f_end = PENTATONIC_FREQS["A3"]
    sub_f = PENTATONIC_FREQS["D2"]
    phase = 0.0
    sub_phase = 0.0

    lp = odd_dsp.OnePoleLP(1600.0, sr)

    for i in range(n):
        t = i / sr
        p = i / n
        freq = f_start + (f_end - f_start) * (p ** 1.6)
        phase += 2.0 * math.pi * freq / sr
        sub_phase += 2.0 * math.pi * sub_f / sr

        # Warm dual-sine + sub
        sine_val = 0.72 * odd_dsp.osc_sine(phase) + 0.28 * odd_dsp.osc_sine(phase * 2.002)
        sub_val = 0.35 * odd_dsp.osc_sine(sub_phase) * (1.0 - p)

        # Swell envelope with bloom at overshoot peak (~75% through)
        env = (p / 0.12) if p < 0.12 else math.exp(-3.2 * (p - 0.12))
        bloom = 0.25 * math.sin(math.pi * p) ** 3.0

        raw = (sine_val + sub_val) * (env + bloom)
        samples[i] = lp.process(raw)

    reverbed = odd_dsp.apply_baked_reverb(samples, decay=0.32, mix=0.18, sample_rate=sr)
    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(reverbed, 0.78), sr)


def synth_close_collapse(sr: int = 44100) -> bytes:
    """2. CLOSE / COLLAPSE: Falling glide A3 -> D3 ending in settle tick (220ms)"""
    dur = 0.22
    n = int(sr * dur)
    samples = [0.0] * n
    f_start = PENTATONIC_FREQS["A3"]
    f_end = PENTATONIC_FREQS["D3"]
    phase = 0.0

    lp = odd_dsp.OnePoleLP(1400.0, sr)

    for i in range(n):
        t = i / sr
        p = i / n
        freq = f_start - (f_start - f_end) * (p ** 1.2)
        phase += 2.0 * math.pi * freq / sr

        env = math.exp(-6.8 * p)
        # Settle tick near end
        tick = 0.25 * math.exp(-35.0 * abs(p - 0.88)) * odd_dsp.osc_sine(phase * 4.0)

        raw = (0.85 * odd_dsp.osc_sine(phase) + 0.15 * odd_dsp.osc_triangle(phase)) * env + tick
        samples[i] = lp.process(raw)

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.65), sr)


def synth_search_activate(sr: int = 44100) -> bytes:
    """3. SEARCH ACTIVATE: Warm low-mid tone swell D3, short and clean (95ms)"""
    dur = 0.095
    n = int(sr * dur)
    samples = [0.0] * n
    f0 = PENTATONIC_FREQS["D3"]
    phase = 0.0

    for i in range(n):
        p = i / n
        phase += 2.0 * math.pi * f0 / sr
        env = math.sin(math.pi * p) ** 1.3
        # Harmonic overtone
        val = 0.85 * odd_dsp.osc_sine(phase) + 0.15 * odd_dsp.osc_sine(phase * 3.0)
        samples[i] = val * env

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.58), sr)


def synth_result_drop(pitch_key: str = "D4", sr: int = 44100) -> bytes:
    """4. RESULT APPEAR: Soft water-drop pluck in pentatonic sequence (48ms)"""
    dur = 0.048
    n = int(sr * dur)
    samples = [0.0] * n
    base_f = PENTATONIC_FREQS.get(pitch_key, 293.66)
    phase = 0.0

    for i in range(n):
        p = i / n
        # Fast initial pitch fall mimics water droplet surface tension snap
        freq = base_f * (1.0 + 0.35 * math.exp(-18.0 * p))
        phase += 2.0 * math.pi * freq / sr
        env = math.exp(-16.0 * p)
        samples[i] = env * (0.90 * odd_dsp.osc_sine(phase) + 0.10 * odd_dsp.osc_sine(phase * 2.0))

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.48), sr)


def synth_select_launch(sr: int = 44100) -> bytes:
    """5. SELECT / LAUNCH: Confident two-note resolve D4 -> A4 (240ms)"""
    dur = 0.24
    n = int(sr * dur)
    samples = [0.0] * n
    f1 = PENTATONIC_FREQS["D4"]
    f2 = PENTATONIC_FREQS["A4"]
    t_split = 0.09

    phase1 = 0.0
    phase2 = 0.0
    lp = odd_dsp.OnePoleLP(2400.0, sr)

    for i in range(n):
        t = i / sr
        if t < t_split:
            p1 = t / t_split
            phase1 += 2.0 * math.pi * f1 / sr
            env = math.sin(math.pi * p1) ** 0.8
            val = odd_dsp.osc_sine(phase1) + 0.2 * odd_dsp.osc_sine(phase1 * 2.0)
            samples[i] = lp.process(val * env * 0.75)
        else:
            t2 = t - t_split
            p2 = t2 / (dur - t_split)
            phase2 += 2.0 * math.pi * f2 / sr
            env = math.exp(-4.8 * p2)
            val = odd_dsp.osc_sine(phase2) + 0.15 * odd_dsp.osc_sine(phase2 * 2.0)
            samples[i] = lp.process(val * env * 0.90)

    reverbed = odd_dsp.apply_baked_reverb(samples, decay=0.38, mix=0.22, sample_rate=sr)
    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(reverbed, 0.82), sr)


def synth_ripple(sr: int = 44100) -> bytes:
    """6. RIPPLE: Airy shimmer sweep band-pass rising with expanding ring (620ms)"""
    dur = 0.62
    n = int(sr * dur)
    samples = [0.0] * n
    bp = odd_dsp.BiquadFilter("bandpass", 600.0, q=2.8, sample_rate=sr)
    sine_p = 0.0
    f_carrier = PENTATONIC_FREQS["A3"]

    for i in range(n):
        t = i / sr
        p = i / n
        bp.cutoff = 350.0 + 1950.0 * (p ** 1.4)
        bp._calc_coeffs()

        noise = odd_dsp.osc_noise()
        filtered_shimmer = bp.process(noise)

        # Subtle underlying sine breath
        sine_p += 2.0 * math.pi * f_carrier / sr
        breath = 0.22 * odd_dsp.osc_sine(sine_p) * math.sin(math.pi * p)

        # Smooth bell envelope
        env = math.sin(math.pi * p) ** 1.5
        samples[i] = (filtered_shimmer * 0.78 + breath) * env

    reverbed = odd_dsp.apply_baked_reverb(samples, decay=0.45, mix=0.26, sample_rate=sr)
    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(reverbed, 0.72), sr)


def synth_split(sr: int = 44100) -> bytes:
    """7. SPLIT: Watery bloop with pitch rise as neck thins + pinch-off tick (180ms)"""
    dur = 0.18
    n = int(sr * dur)
    samples = [0.0] * n
    phase = 0.0
    f0 = PENTATONIC_FREQS["D3"]
    f1 = PENTATONIC_FREQS["F4"]

    for i in range(n):
        t = i / sr
        p = i / n
        freq = f0 + (f1 - f0) * (p ** 2.2)
        phase += 2.0 * math.pi * freq / sr

        env = (p / 0.15) if p < 0.15 else math.exp(-7.5 * (p - 0.15))
        # Pinch-off snap at separation
        snap = 0.35 * math.exp(-50.0 * abs(p - 0.85)) * odd_dsp.osc_sine(phase * 3.0)
        samples[i] = odd_dsp.osc_sine(phase) * env + snap

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.70), sr)


def synth_merge(sr: int = 44100) -> bytes:
    """8. MERGE: Pitch fall into rounded gloop with warm low tone (240ms)"""
    dur = 0.24
    n = int(sr * dur)
    samples = [0.0] * n
    phase = 0.0
    f0 = PENTATONIC_FREQS["G4"]
    f1 = PENTATONIC_FREQS["D3"]
    lp = odd_dsp.OnePoleLP(900.0, sr)

    for i in range(n):
        p = i / n
        freq = f0 - (f0 - f1) * (p ** 1.4)
        phase += 2.0 * math.pi * freq / sr
        env = math.sin(math.pi * p) ** 0.9 * math.exp(-2.5 * p)
        raw = odd_dsp.osc_sine(phase) + 0.25 * odd_dsp.osc_triangle(phase * 0.5)
        samples[i] = lp.process(raw * env)

    reverbed = odd_dsp.apply_baked_reverb(samples, decay=0.28, mix=0.15, sample_rate=sr)
    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(reverbed, 0.72), sr)


def synth_spring_bounce(sr: int = 44100) -> bytes:
    """9. SPRING BOUNCE / OVERSHOOT: Faint elastic wobble (130ms)"""
    dur = 0.13
    n = int(sr * dur)
    samples = [0.0] * n
    base_f = PENTATONIC_FREQS["D3"]
    phase = 0.0

    for i in range(n):
        p = i / n
        # Damped frequency modulation mimics physical spring wobble
        wobble = 35.0 * math.sin(2.0 * math.pi * 14.0 * (i / sr)) * math.exp(-8.0 * p)
        freq = base_f + wobble
        phase += 2.0 * math.pi * freq / sr
        env = math.exp(-9.0 * p)
        samples[i] = odd_dsp.osc_sine(phase) * env

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.42), sr)


def synth_odometer_tick(variant: int = 0, sr: int = 44100) -> bytes:
    """10. ODOMETER DIGIT ROLL: Soft mechanical tick, humanized (22ms)"""
    dur = 0.022
    n = int(sr * dur)
    samples = [0.0] * n
    base_f = 1100.0 + variant * 120.0
    phase = 0.0

    for i in range(n):
        p = i / n
        freq = base_f - 400.0 * p
        phase += 2.0 * math.pi * freq / sr
        env = math.exp(-24.0 * p)
        samples[i] = odd_dsp.osc_sine(phase) * env

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.38), sr)


def synth_slider_detent(is_boundary: bool = False, sr: int = 44100) -> bytes:
    """11. SLIDER DETENT TICK: Gentle detent tick at 0%, 50%, 100% (28ms)"""
    dur = 0.028
    n = int(sr * dur)
    samples = [0.0] * n
    f0 = PENTATONIC_FREQS["A4"] if is_boundary else PENTATONIC_FREQS["D4"]
    phase = 0.0

    for i in range(n):
        p = i / n
        phase += 2.0 * math.pi * f0 / sr
        env = math.exp(-18.0 * p)
        samples[i] = (0.85 * odd_dsp.osc_sine(phase) + 0.15 * odd_dsp.osc_sine(phase * 2.0)) * env

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.45), sr)


def synth_toggle(is_on: bool, sr: int = 44100) -> bytes:
    """12. TOGGLE ON/OFF: ON is rising D4->G4, OFF is falling G4->D4 (110ms)"""
    dur = 0.11
    n = int(sr * dur)
    samples = [0.0] * n
    f_start = PENTATONIC_FREQS["D4"] if is_on else PENTATONIC_FREQS["G4"]
    f_end = PENTATONIC_FREQS["G4"] if is_on else PENTATONIC_FREQS["D4"]
    phase = 0.0

    for i in range(n):
        p = i / n
        freq = f_start + (f_end - f_start) * (p ** 1.3)
        phase += 2.0 * math.pi * freq / sr
        env = math.sin(math.pi * p) ** 0.85 * math.exp(-3.5 * p)
        samples[i] = odd_dsp.osc_sine(phase) * env

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.55), sr)


def synth_error_denied(sr: int = 44100) -> bytes:
    """13. ERROR / NO RESULT / DENIED: Gentle dull low thud-hum D2 (190ms)"""
    dur = 0.19
    n = int(sr * dur)
    samples = [0.0] * n
    f0 = PENTATONIC_FREQS["D2"]
    phase = 0.0
    lp = odd_dsp.OnePoleLP(420.0, sr)

    for i in range(n):
        p = i / n
        phase += 2.0 * math.pi * f0 / sr
        env = math.exp(-7.2 * p)
        raw = odd_dsp.osc_sine(phase) + 0.4 * odd_dsp.osc_triangle(phase * 2.0)
        samples[i] = lp.process(raw * env)

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.68), sr)


def synth_notification_done(sr: int = 44100) -> bytes:
    """14. NOTIFICATION / TIMER DONE: Calm 3-note hum phrase D4 -> F4 -> A4 (480ms)"""
    dur = 0.48
    n = int(sr * dur)
    samples = [0.0] * n
    notes = [PENTATONIC_FREQS["D4"], PENTATONIC_FREQS["F4"], PENTATONIC_FREQS["A4"]]
    sub_dur = dur / 3.0

    lp = odd_dsp.OnePoleLP(2200.0, sr)

    for i in range(n):
        t = i / sr
        note_idx = min(2, int(t / sub_dur))
        note_t = t - note_idx * sub_dur
        p = note_t / sub_dur

        f = notes[note_idx]
        env = math.sin(math.pi * p) ** 0.7 * math.exp(-1.5 * p) if note_idx < 2 else math.exp(-3.5 * p)
        val = 0.8 * odd_dsp.osc_sine(2.0 * math.pi * f * t) + 0.2 * odd_dsp.osc_sine(2.0 * math.pi * f * 2.0 * t)
        samples[i] = lp.process(val * env)

    reverbed = odd_dsp.apply_baked_reverb(samples, decay=0.55, mix=0.32, sample_rate=sr)
    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(reverbed, 0.85), sr)


def synth_ambient_hum(sr: int = 44100) -> bytes:
    """15. IDLE AMBIENT HUM: Loopable calm pad D3/A3 with 4 cents detune (1.8s)"""
    dur = 1.80
    n = int(sr * dur)
    samples = [0.0] * n
    f1 = PENTATONIC_FREQS["D3"]
    f2 = f1 * (2.0 ** (4.0 / 1200.0))  # +4 cents detune
    f_fifth = PENTATONIC_FREQS["A3"]

    p1 = 0.0
    p2 = 0.0
    p5 = 0.0
    lp = odd_dsp.OnePoleLP(850.0, sr)

    for i in range(n):
        t = i / sr
        p = i / n
        p1 += 2.0 * math.pi * f1 / sr
        p2 += 2.0 * math.pi * f2 / sr
        p5 += 2.0 * math.pi * f_fifth / sr

        # Perfectly loopable envelope (sine window)
        loop_env = math.sin(math.pi * p)
        val = 0.45 * odd_dsp.osc_sine(p1) + 0.35 * odd_dsp.osc_sine(p2) + 0.20 * odd_dsp.osc_sine(p5)
        samples[i] = lp.process(val * loop_env)

    return odd_dsp.render_wav_buffer(odd_dsp.normalize_samples(samples, 0.28), sr)


# =========================================================================
# 2. Audio Manager with Voice Pool & Motion Dynamics
# =========================================================================

class AudioVoice:
    """Represents an active playing audio voice for priority & voice-stealing"""
    def __init__(self, sound_id: str, priority: int, start_time: float, volume: float):
        self.sound_id = sound_id
        self.priority = priority
        self.start_time = start_time
        self.volume = volume


class AudioManager:
    """
    Thread-safe Audio Manager.
    Pre-caches PCM buffers (<8MB total), manages a bounded voice pool (max 8 voices),
    per-sound cooldowns, master volume, auto-silence, and motion event listening.
    """
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, settings: Optional[dict] = None) -> "AudioManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = AudioManager(settings or {})
            return cls._instance

    def __init__(self, settings: dict):
        self.settings = settings or {}
        self._wav_cache: Dict[str, bytes] = {}
        self._sound_objects: Dict[str, Any] = {}
        self._cooldowns: Dict[str, float] = {}
        self._voices: List[AudioVoice] = []
        self._pygame_ok = False
        self._init_done = False

        # Sound settings
        self.master_volume = float(self.settings.get("ui_sound_volume", 40)) / 100.0
        self.sound_pack = str(self.settings.get("sound_pack", "Calm Hum")).strip()
        self.motion_sounds_enabled = bool(self.settings.get("motion_sounds_enabled", True))
        self.ambient_hum_enabled = bool(self.settings.get("ambient_hum_enabled", False))

        # Start background pre-rendering
        threading.Thread(target=self._pre_render_all, daemon=True, name="ODD_Audio_PreRender").start()

    def update_settings(self, new_settings: dict):
        self.settings = new_settings
        self.master_volume = float(self.settings.get("ui_sound_volume", 40)) / 100.0
        self.sound_pack = str(self.settings.get("sound_pack", "Calm Hum")).strip()
        self.motion_sounds_enabled = bool(self.settings.get("motion_sounds_enabled", True))
        self.ambient_hum_enabled = bool(self.settings.get("ambient_hum_enabled", False))

    def prewarm_all(self):
        """Synchronously or asynchronously ensures all sounds are pre-rendered into cache."""
        if not self._init_done:
            self._pre_render_all()

    def _pre_render_all(self):
        """Pre-renders all procedural audio buffers in a background thread."""
        t0 = time.perf_counter()
        cache = {
            "wake": synth_wake_open(),
            "close": synth_close_collapse(),
            "search_activate": synth_search_activate(),
            "select_launch": synth_select_launch(),
            "ripple": synth_ripple(),
            "split": synth_split(),
            "merge": synth_merge(),
            "bounce": synth_spring_bounce(),
            "toggle_on": synth_toggle(True),
            "toggle_off": synth_toggle(False),
            "error": synth_error_denied(),
            "notification": synth_notification_done(),
            "ambient": synth_ambient_hum(),
            "slider_detent_mid": synth_slider_detent(False),
            "slider_detent_bound": synth_slider_detent(True),
        }

        # Variants for rapidly repeated sounds
        for i, pitch in enumerate(["D4", "F4", "G4", "A4"]):
            cache[f"drop_{i}"] = synth_result_drop(pitch)
        for i in range(3):
            cache[f"tick_{i}"] = synth_odometer_tick(i)

        total_bytes = sum(len(b) for b in cache.values())

        # Initialize pygame.mixer for zero-latency multi-channel playback
        try:
            import os
            os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
            import pygame.mixer
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self._pygame_ok = True
            for k, wav in cache.items():
                try:
                    self._sound_objects[k] = pygame.mixer.Sound(io.BytesIO(wav))
                except Exception:
                    pass
        except Exception:
            self._pygame_ok = False

        self._wav_cache.update(cache)
        self._init_done = True
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        log_breadcrumb(
            f"Procedural audio rendered ({len(cache)} sounds, {total_bytes/1024:.1f} KB in {elapsed_ms:.1f}ms)",
            category="audio"
        )
        logger.info(f"[AUDIO] Pre-rendered {len(cache)} calm sounds in {elapsed_ms:.1f}ms (Memory: {total_bytes/1024:.1f} KB)")

    def is_auto_silenced(self) -> bool:
        """Checks if sounds should be silenced (system muted, focus assist, or DND)."""
        try:
            # Respect reduce motion setting
            from odd_tier import TierManager
            if TierManager.get_instance().reduce_motion:
                return True
        except Exception:
            pass

        try:
            import odd_com
            cw = odd_com.ComWorker.get_instance()
            if cw.last_mute or cw.last_volume <= 0:
                return True
        except Exception:
            pass

        return False

    def play(
        self,
        sound_id: str,
        intensity: float = 1.0,
        priority: int = 5,
        cooldown_ms: float = 40.0
    ):
        """
        Dispatches sound playback with voice pooling, cooldown rate-limiting,
        motion-coupled intensity scaling, and humanized variation.
        """
        if self.sound_pack == "Off" or self.master_volume <= 0.01:
            return

        # "Minimal" sound pack allows only select, error, and notification
        if self.sound_pack == "Minimal" and sound_id not in ("select_launch", "error", "notification"):
            return

        if self.is_auto_silenced():
            return

        now = time.time()
        # Cooldown check
        last_t = self._cooldowns.get(sound_id, 0.0)
        if (now - last_t) * 1000.0 < cooldown_ms:
            return
        self._cooldowns[sound_id] = now

        # Humanization (pitch / volume micro-variation)
        vol_humanize = random.uniform(0.92, 1.06)
        final_vol = max(0.0, min(1.0, self.master_volume * intensity * vol_humanize))

        # Handle variants
        actual_id = sound_id
        if sound_id == "drop":
            actual_id = f"drop_{random.randint(0, 3)}"
        elif sound_id == "tick":
            actual_id = f"tick_{random.randint(0, 2)}"

        if self._pygame_ok:
            snd = self._sound_objects.get(actual_id)
            if snd:
                try:
                    # Voice pool limiting (max 8 channels)
                    import pygame.mixer
                    if pygame.mixer.get_num_channels() < 8:
                        pygame.mixer.set_num_channels(8)
                    ch = pygame.mixer.find_channel()
                    if ch:
                        ch.set_volume(final_vol)
                        ch.play(snd)
                        return
                    else:
                        # Voice stealing: steal lowest priority voice
                        snd.set_volume(final_vol)
                        snd.play()
                        return
                except Exception:
                    pass

        # Fallback to winsound SND_ASYNC if pygame is uninitialized
        wav = self._wav_cache.get(actual_id)
        if wav:
            try:
                import winsound
                winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except Exception:
                pass


# =========================================================================
# 3. Motion-Coupled Audio Event Bus
# =========================================================================

class AudioEventBus(QObject):
    """
    Event bus bridging the physics motion engine and the procedural audio system.
    Motion triggers call emit_motion_sound with physical parameters.
    """
    _instance = None

    @classmethod
    def get_instance(cls) -> "AudioEventBus":
        if cls._instance is None:
            cls._instance = AudioEventBus()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.mgr = AudioManager.get_instance()

    def on_capsule_wake(self, velocity: float = 1.0):
        intensity = max(0.5, min(1.4, abs(velocity) * 1.1))
        self.mgr.play("wake", intensity=intensity, priority=7)

    def on_capsule_close(self, velocity: float = 1.0):
        intensity = max(0.4, min(1.2, abs(velocity) * 1.0))
        self.mgr.play("close", intensity=intensity, priority=7)

    def on_search_activate(self):
        self.mgr.play("search_activate", intensity=0.85, priority=6)

    def on_result_appear(self, row_idx: int):
        # Pentatonic scale step
        variant_idx = min(3, row_idx)
        self.mgr.play(f"drop_{variant_idx}", intensity=0.75, cooldown_ms=30.0)

    def on_item_launch(self):
        self.mgr.play("select_launch", intensity=1.0, priority=9)

    def on_ripple_start(self, intensity: float = 1.0):
        self.mgr.play("ripple", intensity=max(0.6, min(1.3, intensity)), priority=8)

    def on_capsule_split(self):
        self.mgr.play("split", intensity=0.9, priority=7)

    def on_capsule_merge(self):
        self.mgr.play("merge", intensity=0.9, priority=7)

    def on_spring_bounce(self, overshoot_amount: float = 0.1):
        intensity = max(0.2, min(0.6, overshoot_amount * 2.0))
        self.mgr.play("bounce", intensity=intensity, cooldown_ms=60.0)

    def on_odometer_tick(self):
        self.mgr.play("tick", intensity=0.55, cooldown_ms=18.0)

    def on_slider_detent(self, is_boundary: bool = False):
        self.mgr.play("slider_detent_bound" if is_boundary else "slider_detent_mid", intensity=0.65, cooldown_ms=35.0)

    def on_toggle_changed(self, is_on: bool):
        self.mgr.play("toggle_on" if is_on else "toggle_off", intensity=0.8)

    def on_action_error(self):
        self.mgr.play("error", intensity=0.95, priority=8)

    def on_notification(self):
        self.mgr.play("notification", intensity=1.0, priority=9)
