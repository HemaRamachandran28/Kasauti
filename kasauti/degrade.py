"""Audio degradation: telephony channel + noise at a target SNR. Pure numpy/scipy."""
from __future__ import annotations

import io
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

TARGET_SR = 16000


def read_audio(src):
    """Read a path or WAV bytes -> (mono float32, sample_rate)."""
    handle = io.BytesIO(bytes(src)) if isinstance(src, (bytes, bytearray)) else str(src)
    data, sr = sf.read(handle, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data.astype(np.float32), int(sr)


def write_wav(path, x, sr) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(x, -1, 1), sr, subtype="PCM_16")


def resample(x, sr_in: int, sr_out: int):
    if sr_in == sr_out:
        return x.astype(np.float32)
    g = gcd(sr_in, sr_out)
    return signal.resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def rms(x) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)) + 1e-20))


def mulaw_roundtrip(x, mu: int = 255):
    x = np.clip(x, -1, 1)
    y = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    q = np.round((y + 1) / 2 * 255)            # 8-bit quantisation, as in G.711
    y2 = q / 255 * 2 - 1
    return (np.sign(y2) * (1 / mu) * ((1 + mu) ** np.abs(y2) - 1)).astype(np.float32)


def telephony(x, sr: int):
    """300-3400 Hz band-limit, 8 kHz sampling, mu-law companding."""
    sos = signal.butter(4, [300, 3400], btype="bandpass", fs=sr, output="sos")
    y = signal.sosfiltfilt(sos, x).astype(np.float32)
    peak = float(np.max(np.abs(y)) + 1e-9)
    y = y * (0.9 / peak)
    y = resample(y, sr, 8000)
    return mulaw_roundtrip(y), 8000


def mix_at_snr(x, noise, snr_db: float):
    """Return x + scaled(noise) such that 10*log10(P_x / P_noise) == snr_db (whole-signal power)."""
    reps = int(np.ceil(len(x) / max(len(noise), 1)))
    n = np.tile(noise, reps)[: len(x)]
    gain = rms(x) / (rms(n) * 10 ** (snr_db / 20))
    return (x + n * gain).astype(np.float32)


def speech_shaped_noise(length: int, rng, sr: int = TARGET_SR):
    w = rng.standard_normal(length)
    sos = signal.butter(2, 2500, btype="lowpass", fs=sr, output="sos")
    return signal.sosfilt(sos, w).astype(np.float32)


def babble(pool: list, length: int, rng, n_talkers: int = 4):
    """Sum of several other utterances = 'cafeteria' babble. Falls back to speech-shaped noise."""
    if not pool:
        return speech_shaped_noise(length, rng)
    out = np.zeros(length, dtype=np.float64)
    for _ in range(n_talkers):
        clip = pool[int(rng.integers(len(pool)))]
        clip = np.roll(np.tile(clip, int(np.ceil(length / len(clip))) + 1), int(rng.integers(len(clip))))[:length]
        out += clip / rms(clip)
    return out.astype(np.float32)


def parse_condition(cond: str) -> dict:
    spec = {"tel": False, "noise": []}
    if cond == "clean":
        return spec
    for part in cond.split("+"):
        if part == "tel":
            spec["tel"] = True
        elif ":" in part:
            kind, snr = part.split(":", 1)
            if kind not in ("babble", "white"):
                raise ValueError(f"Unknown noise kind '{kind}' in condition '{cond}'")
            spec["noise"].append((kind, float(snr)))
        else:
            raise ValueError(f"Cannot parse condition '{cond}'")
    return spec


def apply_condition(x, sr: int, cond: str, rng, pool: list | None = None):
    spec = parse_condition(cond)
    y = x
    for kind, snr in spec["noise"]:
        n = babble(pool or [], len(y), rng) if kind == "babble" else rng.standard_normal(len(y)).astype(np.float32)
        y = mix_at_snr(y, n, snr)
    peak = float(np.max(np.abs(y)) + 1e-9)
    if peak > 0.99:
        y = y * (0.99 / peak)
    out_sr = sr
    if spec["tel"]:
        y, out_sr = telephony(y, sr)
    return y.astype(np.float32), out_sr


def condition_meta(cond: str) -> dict:
    """Class label, minimum SNR and a severity score for ordering plots."""
    s = parse_condition(cond)
    snrs = [snr for _, snr in s["noise"]]
    if cond == "clean":
        cls = "clean"
    elif s["tel"] and snrs:
        cls = "telephony+noise"
    elif s["tel"]:
        cls = "telephony"
    else:
        cls = "noisy"
    severity = (0.5 if s["tel"] else 0.0) + sum((30 - v) / 30 for v in snrs)
    return {"cond_class": cls, "snr_db": min(snrs) if snrs else None, "severity": severity}
