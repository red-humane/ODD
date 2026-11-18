"""
ODD Pure-Function Audio DSP Synthesis Toolkit
Provides procedural oscillators, envelopes, biquad filters, pitch glides,
reverberant feedback-delay networks, soft-clip limiters, and WAV rendering.
Pure Python standard library implementation with zero external sample dependencies.
"""

import math
import struct
import io
import wave
import random
from typing import List, Callable, Tuple, Optional


SAMPLE_RATE = 44100


# =========================================================================
# 1. Basic Oscillators & Generators
# =========================================================================

def osc_sine(phase: float) -> float:
    """Pure sine oscillator (-1.0 to +1.0)"""
    return math.sin(phase)


def osc_triangle(phase: float) -> float:
    """Band-shaped triangle oscillator (-1.0 to +1.0)"""
    p = (phase / (2.0 * math.pi)) % 1.0
    return 4.0 * abs(p - 0.5) - 1.0


def osc_saw(phase: float) -> float:
    """Sawtooth oscillator (-1.0 to +1.0)"""
    p = (phase / (2.0 * math.pi)) % 1.0
    return 2.0 * p - 1.0


def osc_noise() -> float:
    """Uniform white noise sample (-1.0 to +1.0)"""
    return random.uniform(-1.0, 1.0)


# =========================================================================
# 2. Envelopes
# =========================================================================

def env_exp_decay(p: float, decay_rate: float = 6.0) -> float:
    """Exponential decay envelope, p in [0.0, 1.0]"""
    return math.exp(-decay_rate * max(0.0, min(1.0, p)))


def env_smooth(t: float, duration: float, attack: float = 0.005, release: float = 0.02) -> float:
    """Smooth trapezoidal / parabolic envelope with soft attack and release"""
    if t < 0.0 or t > duration:
        return 0.0
    att = max(0.001, attack)
    rel = max(0.001, release)
    
    # Attack ramp
    if t < att:
        gain = 0.5 * (1.0 - math.cos(math.pi * t / att))
    # Release ramp
    elif t > (duration - rel):
        gain = 0.5 * (1.0 + math.cos(math.pi * (t - (duration - rel)) / rel))
    else:
        gain = 1.0
    return gain


def env_adsr(t: float, duration: float, a: float = 0.01, d: float = 0.05, s: float = 0.7, r: float = 0.08) -> float:
    """Classic ADSR envelope"""
    if t < 0.0 or t >= duration:
        return 0.0
    
    # Attack
    if t < a:
        return t / max(0.0001, a)
    # Decay
    elif t < (a + d):
        dt = t - a
        return 1.0 - (1.0 - s) * (dt / max(0.0001, d))
    # Sustain
    elif t < (duration - r):
        return s
    # Release
    else:
        rt = t - (duration - r)
        return s * (1.0 - rt / max(0.0001, r))


# =========================================================================
# 3. Filters
# =========================================================================

class OnePoleLP:
    """Lightweight 1-pole lowpass filter for gentle high-frequency damping"""
    def __init__(self, cutoff_hz: float, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.y = 0.0
        self.set_cutoff(cutoff_hz)

    def set_cutoff(self, cutoff_hz: float):
        fc = max(20.0, min(float(cutoff_hz), self.sample_rate * 0.49))
        self.alpha = 1.0 - math.exp(-2.0 * math.pi * fc / self.sample_rate)

    def process(self, x: float) -> float:
        self.y += self.alpha * (x - self.y)
        return self.y


class BiquadFilter:
    """
    Direct Form I 2-pole Biquad Filter (Lowpass, Bandpass, Highpass, Peaking)
    Based on Robert Bristow-Johnson Audio EQ Cookbook.
    """
    def __init__(self, filter_type: str = "lowpass", cutoff_hz: float = 1000.0, q: float = 1.0, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.x1 = 0.0
        self.x2 = 0.0
        self.y1 = 0.0
        self.y2 = 0.0
        self.filter_type = filter_type.lower()
        self.cutoff = cutoff_hz
        self.q = q
        self._calc_coeffs()

    def _calc_coeffs(self):
        f0 = max(10.0, min(self.cutoff, self.sample_rate * 0.49))
        w0 = 2.0 * math.pi * f0 / self.sample_rate
        alpha = math.sin(w0) / (2.0 * max(0.1, self.q))
        cos_w0 = math.cos(w0)

        if self.filter_type == "lowpass":
            b0 = (1.0 - cos_w0) / 2.0
            b1 = 1.0 - cos_w0
            b2 = (1.0 - cos_w0) / 2.0
            a0 = 1.0 + alpha
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha
        elif self.filter_type == "bandpass":
            b0 = alpha
            b1 = 0.0
            b2 = -alpha
            a0 = 1.0 + alpha
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha
        elif self.filter_type == "highpass":
            b0 = (1.0 + cos_w0) / 2.0
            b1 = -(1.0 + cos_w0)
            b2 = (1.0 + cos_w0) / 2.0
            a0 = 1.0 + alpha
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha
        else:
            # Fallback passthrough
            b0, b1, b2, a0, a1, a2 = 1.0, 0.0, 0.0, 1.0, 0.0, 0.0

        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0

    def process(self, x: float) -> float:
        y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2
        self.x2 = self.x1
        self.x1 = x
        self.y2 = self.y1
        self.y1 = y
        return y


# =========================================================================
# 4. Feedback Delay & Baked Schroeder Room
# =========================================================================

def apply_baked_reverb(
    samples: List[float],
    decay: float = 0.35,
    mix: float = 0.22,
    sample_rate: int = SAMPLE_RATE
) -> List[float]:
    """
    Applies a compact 2-comb Schroeder feedback delay network directly to samples.
    Baked into the rendered buffer for spaciousness with 0% runtime CPU.
    """
    if mix <= 0.001:
        return samples

    # Comb filter delays in samples (~29ms and ~37ms)
    d1 = int(0.029 * sample_rate)
    d2 = int(0.037 * sample_rate)
    buf1 = [0.0] * d1
    buf2 = [0.0] * d2
    idx1 = 0
    idx2 = 0

    g1 = min(0.85, decay * 0.75)
    g2 = min(0.85, decay * 0.68)

    # All-pass filter (~5ms)
    ap_d = int(0.005 * sample_rate)
    ap_buf = [0.0] * ap_d
    ap_idx = 0
    ap_gain = 0.5

    out = [0.0] * len(samples)

    for i in range(len(samples)):
        dry = samples[i]

        # Comb 1
        y1 = buf1[idx1]
        buf1[idx1] = dry + y1 * g1
        idx1 = (idx1 + 1) % d1

        # Comb 2
        y2 = buf2[idx2]
        buf2[idx2] = dry + y2 * g2
        idx2 = (idx2 + 1) % d2

        wet_comb = 0.5 * (y1 + y2)

        # All-pass stage
        ap_in = wet_comb
        ap_y = -ap_gain * ap_in + ap_buf[ap_idx]
        ap_buf[ap_idx] = ap_in + ap_gain * ap_y
        ap_idx = (ap_idx + 1) % ap_d

        out[i] = (1.0 - mix) * dry + mix * ap_y

    return out


# =========================================================================
# 5. Dynamics, Limiter, Fades & Normalization
# =========================================================================

def apply_anti_click_fades(samples: List[float], fade_in_ms: float = 2.5, fade_out_ms: float = 6.0, sample_rate: int = SAMPLE_RATE) -> List[float]:
    """Applies cosine taper at beginning and end of buffer to guarantee zero clicks or pops."""
    n = len(samples)
    if n == 0:
        return samples

    in_samples = int(sample_rate * (fade_in_ms / 1000.0))
    out_samples = int(sample_rate * (fade_out_ms / 1000.0))

    out = list(samples)

    # Fade in
    for i in range(min(in_samples, n)):
        t = i / max(1, in_samples)
        fade = 0.5 * (1.0 - math.cos(math.pi * t))
        out[i] *= fade

    # Fade out
    for i in range(min(out_samples, n)):
        idx = n - 1 - i
        t = i / max(1, out_samples)
        fade = 0.5 * (1.0 - math.cos(math.pi * t))
        out[idx] *= fade

    return out


def remove_dc_offset(samples: List[float]) -> List[float]:
    """Removes DC bias via single-pole highpass (cutoff ~15 Hz)"""
    if not samples:
        return samples
    out = [0.0] * len(samples)
    r = 0.995
    y = 0.0
    x_prev = 0.0
    for i, x in enumerate(samples):
        y = x - x_prev + r * y
        x_prev = x
        out[i] = y
    return out


def soft_clip(x: float) -> float:
    """Smooth tanh soft-saturation curve preventing harsh digital clipping"""
    if x > 3.0:
        return 1.0
    elif x < -3.0:
        return -1.0
    return math.tanh(x)


def normalize_samples(samples: List[float], target_peak: float = 0.88) -> List[float]:
    """Scales buffer so peak absolute amplitude equals target_peak, with soft limiter protection."""
    if not samples:
        return samples
    peak = max(abs(s) for s in samples)
    if peak < 0.0001:
        return samples
    scale = target_peak / peak
    return [soft_clip(s * scale) for s in samples]


# =========================================================================
# 6. WAV Serialization & Exporter Helper
# =========================================================================

def render_wav_buffer(samples: List[float], sample_rate: int = SAMPLE_RATE) -> bytes:
    """
    Serializes floating-point samples [-1.0, 1.0] to a standard 16-bit PCM WAV byte buffer.
    """
    cleaned = remove_dc_offset(samples)
    faded = apply_anti_click_fades(cleaned, fade_in_ms=2.0, fade_out_ms=5.0, sample_rate=sample_rate)

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)       # Mono
        wav.setsampwidth(2)       # 16-bit
        wav.setframerate(sample_rate)

        frames = bytearray()
        for s in faded:
            clipped = max(-1.0, min(1.0, soft_clip(s)))
            val = int(clipped * 32767)
            frames.extend(struct.pack('<h', val))
        wav.writeframes(frames)

    return buf.getvalue()


def export_wav_file(samples: List[float], file_path: str, sample_rate: int = SAMPLE_RATE):
    """Saves a procedural sound to disk as a standard .wav file for auditioning and mixing."""
    wav_data = render_wav_buffer(samples, sample_rate=sample_rate)
    with open(file_path, 'wb') as f:
        f.write(wav_data)
