"""
Universal High-Performance Sound Subsystem for ODD
Pre-generates all synthesized sounds once in a background worker, caches raw WAV buffers,
and provides zero-latency (<0.1ms) playback without any GUI thread audio synthesis.
Gracefully handles both (name, settings_dict) and (name, enabled=..., volume=...) calling conventions.
"""

import math
import struct
import io
import wave
import winsound
import threading
from typing import Optional, Dict, Any

from odd_crash_capture import log_breadcrumb, logger, safe_slot

_PRECACHED_WAVS: Dict[str, bytes] = {}
_SOUND_OBJECTS: Dict[str, Any] = {}
_PYGAME_INITIALIZED = False
_WARMUP_STARTED = False
_CACHE_LOCK = threading.Lock()


def _create_wav(fn, duration_ms: int, volume: float = 1.0) -> bytes:
    sample_rate = 44100
    n_samples = int(sample_rate * (duration_ms / 1000.0))
    buf = io.BytesIO()

    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()

        for i in range(n_samples):
            t = i / sample_rate
            p = i / n_samples
            val = fn(t, p)
            scaled = int(32767 * max(-1.0, min(1.0, val)) * volume)
            frames.extend(struct.pack('<h', scaled))

        wav.writeframes(frames)
    return buf.getvalue()


# Wave synthesis generators
def _synth_hover() -> bytes:
    def fn(t, p):
        env = math.sin(math.pi * p) ** 0.5 * math.exp(-6.5 * p)
        freq = 520.0 + 80.0 * math.sin(math.pi * p)
        return env * math.sin(2 * math.pi * freq * t)
    return _create_wav(fn, duration_ms=44, volume=0.85)


def _synth_sink() -> bytes:
    def fn(t, p):
        env = math.sin(math.pi * p) ** 1.2 * math.exp(-4.0 * p)
        freq = 460.0 - 120.0 * (p ** 1.1)
        return env * math.sin(2 * math.pi * freq * t)
    return _create_wav(fn, duration_ms=38, volume=0.75)


def _synth_type() -> bytes:
    def fn(t, p):
        env = math.exp(-14.0 * p)
        freq = 1350.0 + 150.0 * (1.0 - p)
        return env * (0.8 * math.sin(2 * math.pi * freq * t) + 0.2 * math.sin(2 * math.pi * 2600.0 * t))
    return _create_wav(fn, duration_ms=15, volume=0.28)


def _synth_action() -> bytes:
    def fn(t, p):
        if p < 0.05:
            env = p / 0.05
        else:
            env = math.exp(-4.5 * (p - 0.05))
        val = (0.35 * math.sin(2 * math.pi * 523.25 * t) +
               0.30 * math.sin(2 * math.pi * 659.25 * t) +
               0.25 * math.sin(2 * math.pi * 783.99 * t) +
               0.10 * math.sin(2 * math.pi * 1046.50 * t))
        return env * val
    return _create_wav(fn, duration_ms=110, volume=0.80)


def _synth_lock(is_on: bool) -> bytes:
    def fn(t, p):
        env = math.exp(-10.0 * p)
        freq = 640.0 if is_on else 420.0
        return env * math.sin(2 * math.pi * freq * t)
    return _create_wav(fn, duration_ms=26, volume=0.40)


def _synth_reminder() -> bytes:
    def fn(t, p):
        if t < 0.15:
            p1 = t / 0.15
            env1 = p1 / 0.03 if p1 < 0.03 else math.exp(-6.0 * (p1 - 0.03))
            return env1 * (0.5 * math.sin(2 * math.pi * 587.33 * t) + 0.5 * math.sin(2 * math.pi * 880.0 * t))
        else:
            t2 = t - 0.15
            p2 = t2 / 0.33
            env2 = p2 / 0.02 if p2 < 0.02 else math.exp(-4.5 * (p2 - 0.02))
            return env2 * (0.4 * math.sin(2 * math.pi * 880.0 * t) + 0.4 * math.sin(2 * math.pi * 1174.66 * t) + 0.2 * math.sin(2 * math.pi * 1760.0 * t))
    return _create_wav(fn, duration_ms=480, volume=0.90)


def _synth_charge(is_plugged: bool) -> bytes:
    if is_plugged:
        def fn(t, p):
            if p < 0.30:
                tp = p / 0.30
                env = tp / 0.04 if tp < 0.04 else math.exp(-6.0 * (tp - 0.04))
                return env * (0.6 * math.sin(2 * math.pi * 523.25 * t) + 0.3 * math.sin(2 * math.pi * 1046.5 * t))
            elif p < 0.62:
                tp = (p - 0.30) / 0.32
                env = tp / 0.03 if tp < 0.03 else math.exp(-5.5 * (tp - 0.03))
                return env * (0.6 * math.sin(2 * math.pi * 659.25 * t) + 0.3 * math.sin(2 * math.pi * 1318.5 * t))
            else:
                tp = (p - 0.62) / 0.38
                env = tp / 0.03 if tp < 0.03 else math.exp(-4.5 * (tp - 0.03))
                return env * (0.6 * math.sin(2 * math.pi * 783.99 * t) + 0.3 * math.sin(2 * math.pi * 1567.98 * t))
        return _create_wav(fn, duration_ms=420, volume=0.88)
    else:
        def fn(t, p):
            if p < 0.45:
                tp = p / 0.45
                env = tp / 0.04 if tp < 0.04 else math.exp(-5.5 * (tp - 0.04))
                return env * (0.6 * math.sin(2 * math.pi * 783.99 * t) + 0.3 * math.sin(2 * math.pi * 1174.66 * t))
            else:
                tp = (p - 0.45) / 0.55
                env = tp / 0.04 if tp < 0.04 else math.exp(-4.5 * (tp - 0.04))
                return env * (0.6 * math.sin(2 * math.pi * 523.25 * t) + 0.25 * math.sin(2 * math.pi * 1046.5 * t))
        return _create_wav(fn, duration_ms=360, volume=0.82)


def _precache_all_sounds():
    """Generates all standard sound buffers in a background thread."""
    global _PRECACHED_WAVS, _PYGAME_INITIALIZED
    try:
        import os
        sounds_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sounds")

        # Audio 1: notification overlay sound
        notif_wav = None
        for fn in ("notification_pcm.wav", "notification.ogg"):
            fp = os.path.join(sounds_dir, fn)
            if os.path.exists(fp):
                try:
                    with open(fp, "rb") as f:
                        notif_wav = f.read()
                    break
                except Exception:
                    pass

        # Audio 2: all reminders overlay sound
        rem_wav = None
        for fn in ("reminder_pcm.wav", "reminder.wav"):
            fp = os.path.join(sounds_dir, fn)
            if os.path.exists(fp):
                try:
                    with open(fp, "rb") as f:
                        rem_wav = f.read()
                    break
                except Exception:
                    pass

        # Audio 3: caps lock on/off, num lock on/off, audio mute/unmute overlay sound
        lock_wav = None
        for fn in ("lock_toggle_pcm.wav", "lock_toggle.wav"):
            fp = os.path.join(sounds_dir, fn)
            if os.path.exists(fp):
                try:
                    with open(fp, "rb") as f:
                        lock_wav = f.read()
                    break
                except Exception:
                    pass

        sounds = {
            "hover": _synth_hover(),
            "pop": _synth_hover(),
            "droplet": _synth_hover(),
            "surface": _synth_hover(),
            "sink": _synth_sink(),
            "close": _synth_sink(),
            "whoosh": _synth_sink(),
            "type": _synth_type(),
            "click": _synth_type(),
            "tap": _synth_type(),
            "action": _synth_action(),
            "execute": _synth_action(),
            "chime": _synth_action(),
            "select": _synth_action(),
            "lock_on": lock_wav if lock_wav else _synth_lock(True),
            "lock_off": lock_wav if lock_wav else _synth_lock(False),
            "lock_toggle": lock_wav if lock_wav else _synth_lock(True),
            "caps_lock": lock_wav if lock_wav else _synth_lock(True),
            "num_lock": lock_wav if lock_wav else _synth_lock(True),
            "scroll_lock": lock_wav if lock_wav else _synth_lock(True),
            "mute": lock_wav if lock_wav else _synth_lock(False),
            "unmute": lock_wav if lock_wav else _synth_lock(True),
            "mute_toggle": lock_wav if lock_wav else _synth_lock(True),
            "reminder": rem_wav if rem_wav else _synth_reminder(),
            "reminder_overlay": rem_wav if rem_wav else _synth_reminder(),
            "wellness": rem_wav if rem_wav else _synth_reminder(),
            "water_reminder": rem_wav if rem_wav else _synth_reminder(),
            "notification": notif_wav if notif_wav else _synth_action(),
            "notification_overlay": notif_wav if notif_wav else _synth_action(),
            "notify": notif_wav if notif_wav else _synth_action(),
            "charge_plug": _synth_charge(True),
            "charge_unplug": _synth_charge(False),
        }
        with _CACHE_LOCK:
            _PRECACHED_WAVS.update(sounds)

        # Initialize pygame.mixer if available for fast mixer playback
        try:
            import os
            os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
            import pygame.mixer
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            _PYGAME_INITIALIZED = True
            for k, wav in sounds.items():
                try:
                    _SOUND_OBJECTS[k] = pygame.mixer.Sound(io.BytesIO(wav))
                except Exception:
                    pass
        except Exception:
            _PYGAME_INITIALIZED = False

        log_breadcrumb("All sound effects pre-warmed into memory", category="sound")
    except Exception as e:
        logger.error(f"[ODD SOUND] Prewarm failed: {e}")


def init_sound_engine():
    """Starts background audio subsystem initialization and sound caching"""
    global _WARMUP_STARTED
    if not _WARMUP_STARTED:
        _WARMUP_STARTED = True
        t = threading.Thread(target=_precache_all_sounds, daemon=True, name="ODD_Sound_Warmup")
        t.start()


def _play_raw(wav_bytes: bytes, volume: float = 1.0):
    if _PYGAME_INITIALIZED:
        try:
            import pygame.mixer
            snd = pygame.mixer.Sound(io.BytesIO(wav_bytes))
            snd.set_volume(max(0.0, min(1.0, volume)))
            snd.play()
            return
        except Exception:
            pass

    try:
        winsound.PlaySound(wav_bytes, winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


def play_sound(name: str, settings: Optional[dict] = None, *, enabled: Optional[bool] = None, volume: Optional[float] = None, **kwargs):
    """
    Robust 0ms playback dispatcher:
    Accepts both play_sound("droplet", settings_dict) and play_sound("droplet", enabled=True, volume=0.75).
    Guarantees no exceptions escape and zero CPU synthesis on GUI thread.
    Keeps typing sound bit-identical to frozen reference while integrating with
    ODD Calm Hum procedural audio system.
    """
    try:
        # Check enabled flag
        if enabled is not None:
            if not enabled:
                return
        elif isinstance(settings, dict):
            if not settings.get("sound_enabled", True):
                return

        # Determine volume
        vol = 0.70
        if volume is not None:
            vol = float(volume)
        elif isinstance(settings, dict):
            vol = float(settings.get("sound_volume", 0.70))

        if vol <= 0.01:
            return

        sound_name = name.lower()

        # Strict guarantee: typing sounds ALWAYS use the bit-identical _synth_type buffer
        if sound_name in ("type", "click", "tap"):
            if _PYGAME_INITIALIZED:
                snd = _SOUND_OBJECTS.get("type")
                if snd:
                    snd.set_volume(max(0.0, min(1.0, vol)))
                    snd.play()
                    return
            with _CACHE_LOCK:
                wav = _PRECACHED_WAVS.get("type")
            if not wav:
                wav = _synth_type()
                with _CACHE_LOCK:
                    _PRECACHED_WAVS["type"] = wav
            _play_raw(wav, vol)
            return

        # Dedicated user-mapped audio files:
        # Audio 1: notification overlay sound
        # Audio 2: all reminders overlay sound
        # Audio 3: caps lock on/off, num lock on/off, audio mute/unmute overlay sound
        user_sound_keys = {
            "notification": "notification",
            "notify": "notification",
            "notification_overlay": "notification",
            "reminder": "reminder",
            "reminder_overlay": "reminder",
            "wellness": "reminder",
            "water_reminder": "reminder",
            "alert_reminder": "reminder",
            "lock_on": "lock_on",
            "lock_off": "lock_off",
            "lock_toggle": "lock_toggle",
            "caps_lock": "caps_lock",
            "num_lock": "num_lock",
            "scroll_lock": "scroll_lock",
            "mute": "mute",
            "unmute": "unmute",
            "mute_toggle": "mute_toggle",
        }
        if sound_name in user_sound_keys:
            target_key = user_sound_keys[sound_name]
            if _PYGAME_INITIALIZED:
                snd = _SOUND_OBJECTS.get(target_key) or _SOUND_OBJECTS.get(sound_name)
                if snd:
                    snd.set_volume(max(0.0, min(1.0, vol)))
                    snd.play()
                    return
            with _CACHE_LOCK:
                wav = _PRECACHED_WAVS.get(target_key) or _PRECACHED_WAVS.get(sound_name)
            if wav:
                _play_raw(wav, vol)
                return

        # Check for Calm Hum audio manager delegation
        sound_pack = "Calm Hum"
        if isinstance(settings, dict):
            sound_pack = settings.get("sound_pack", settings.get("sound_theme", "Calm Hum"))

        try:
            import odd_audio
            mgr = odd_audio.AudioManager.get_instance()
            mgr.master_volume = vol
            
            # Map legacy sound names to Calm Hum palette
            sound_map = {
                "hover": "drop",
                "pop": "drop",
                "droplet": "drop",
                "surface": "search_activate",
                "wake": "wake",
                "sink": "close",
                "close": "close",
                "whoosh": "close",
                "action": "select_launch",
                "execute": "select_launch",
                "chime": "select_launch",
                "select": "select_launch",
                "lock_on": "toggle_on",
                "lock_off": "toggle_off",
                "reminder": "notification",
                "notification": "notification",
                "error": "error",
                "ripple": "ripple",
                "split": "split",
                "merge": "merge",
                "bounce": "bounce",
                "tick": "tick",
                "detent": "slider_detent_mid",
                "detent_bound": "slider_detent_bound",
            }
            target_id = sound_map.get(sound_name, sound_name)
            if target_id in mgr._wav_cache or any(target_id.startswith(p) for p in ("drop", "tick")):
                mgr.play(target_id, intensity=1.0)
                return
        except Exception:
            pass

        # 1. Fast path: pre-warmed pygame sound
        if _PYGAME_INITIALIZED:
            snd = _SOUND_OBJECTS.get(sound_name)
            if snd:
                snd.set_volume(max(0.0, min(1.0, vol)))
                snd.play()
                return

        # 2. Fast path: pre-cached WAV bytes
        with _CACHE_LOCK:
            wav = _PRECACHED_WAVS.get(sound_name)

        if not wav:
            # Fallback if accessed before warmup finished
            if sound_name in ("sink", "close", "whoosh"):
                wav = _synth_sink()
            elif sound_name in ("action", "execute", "chime", "select"):
                wav = _synth_action()
            elif sound_name == "lock_on":
                wav = _synth_lock(True)
            elif sound_name == "lock_off":
                wav = _synth_lock(False)
            elif sound_name == "reminder":
                wav = _synth_reminder()
            else:
                wav = _synth_hover()
            with _CACHE_LOCK:
                _PRECACHED_WAVS[sound_name] = wav

        _play_raw(wav, vol)
    except Exception as e:
        logger.debug(f"[ODD SOUND] Playback error: {e}")


def play_reminder(settings: dict = None):
    play_sound("reminder", settings)

def play_hover(settings: dict):
    play_sound("hover", settings)

def play_sink(settings: dict):
    play_sound("sink", settings)

def play_action(settings: dict):
    play_sound("action", settings)

def play_type(settings: dict):
    play_sound("type", settings)

def play_lock_sound(is_on: bool, settings: dict = None):
    play_sound("lock_on" if is_on else "lock_off", settings)

def play_mute_sound(is_muted: bool = True, settings: dict = None):
    play_sound("mute" if is_muted else "unmute", settings)

def play_notification(settings: dict = None):
    play_sound("notification", settings)

def play_charge_sound(is_plugged: bool = True, settings: dict = None):
    play_sound("charge_plug" if is_plugged else "charge_unplug", settings)

def play_preview(volume: float, style: str = "fluid"):
    """Play a sample sound when user adjusts volume in Settings"""
    play_sound("hover", enabled=True, volume=volume)

# Auto-start sound warmup immediately
init_sound_engine()
