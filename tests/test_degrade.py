import numpy as np
import pytest

from kasauti import degrade as dg


def _tone(sr=16000, secs=2.0):
    t = np.arange(int(sr * secs)) / sr
    return (0.3 * np.sin(2 * np.pi * 440 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)


def test_snr_is_accurate():
    rng = np.random.default_rng(0)
    x = _tone()
    n = rng.standard_normal(len(x)).astype(np.float32)
    for snr in (20, 10, 5, 0):
        y = dg.mix_at_snr(x, n, snr)
        measured = 20 * np.log10(dg.rms(x) / dg.rms(y - x))
        assert abs(measured - snr) < 0.1


def test_telephony_output_rate_and_bandwidth():
    sr0 = 16000
    t = np.arange(sr0 * 2) / sr0
    x = (0.3 * np.sin(2 * np.pi * 100 * t) + 0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    y, sr = dg.telephony(x, sr0)
    assert sr == 8000 and len(y) == len(x) // 2
    spec = np.abs(np.fft.rfft(y))
    freqs = np.fft.rfftfreq(len(y), 1 / sr)
    low = spec[np.argmin(np.abs(freqs - 100))]
    mid = spec[np.argmin(np.abs(freqs - 1000))]
    assert low < 0.1 * mid          # 100 Hz is removed by the 300-3400 Hz band-pass


def test_mulaw_is_close_but_lossy():
    x = _tone()
    y = dg.mulaw_roundtrip(x)
    assert np.max(np.abs(x - y)) < 0.05 and not np.allclose(x, y)


def test_parse_and_meta():
    assert dg.parse_condition("tel+babble:10") == {"tel": True, "noise": [("babble", 10.0)]}
    assert dg.condition_meta("clean")["cond_class"] == "clean"
    assert dg.condition_meta("tel")["cond_class"] == "telephony"
    assert dg.condition_meta("babble:5")["cond_class"] == "noisy"
    assert dg.condition_meta("tel+white:10")["cond_class"] == "telephony+noise"
    assert dg.condition_meta("babble:5")["severity"] > dg.condition_meta("babble:20")["severity"]
    with pytest.raises(ValueError):
        dg.parse_condition("rain:10")


def test_apply_condition_is_deterministic():
    x = _tone()
    pool = [_tone(secs=1.5) * 0.5]
    a, _ = dg.apply_condition(x, 16000, "tel+babble:10", np.random.default_rng(1), pool)
    b, _ = dg.apply_condition(x, 16000, "tel+babble:10", np.random.default_rng(1), pool)
    assert np.allclose(a, b)
