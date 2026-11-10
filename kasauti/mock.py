"""Offline stand-in for the Gnani API so the whole pipeline (and dashboard) can be tried
without a key. Mock transcripts are SIMULATED from the reference text: they are NOT real
results and every mock row is flagged in the database, dashboard and reports."""
from __future__ import annotations

import hashlib
import io
import json

import numpy as np
import soundfile as sf

from kasauti.degrade import parse_condition

_BASE_P = {"clean": 0.02, "tel": 0.06}


def _p_for(cond: str) -> float:
    if cond in _BASE_P:
        return _BASE_P[cond]
    s = parse_condition(cond)
    p = 0.06 if s["tel"] else 0.02
    for _, snr in s["noise"]:
        p += max(0.0, (30 - snr)) * 0.018
    return min(p, 0.85)


class MockClient:
    mock = True

    def __init__(self, db):
        self.db = db

    def tts(self, text, voice, model, language, audio_config, speed=1.0) -> bytes:
        seed = int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        dur = min(25.0, 0.07 * len(text) + 0.5)
        sr = 16000
        t = np.arange(int(dur * sr)) / sr
        f0 = 130 + 40 * np.sin(2 * np.pi * 0.3 * t)
        sig = sum(np.sin(2 * np.pi * k * np.cumsum(f0) / sr) / k for k in (1, 2, 3))
        sig = sig * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) * 0.3
        sig = sig + 0.01 * rng.standard_normal(len(t))
        buf = io.BytesIO()
        sf.write(buf, sig.astype(np.float32), sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    def stt(self, audio_path, params: dict, variant_id: str | None = None) -> dict:
        v = self.db.one("SELECT v.condition, s.text, s.lang, s.keyterms_json FROM variants v "
                        "JOIN scripts s ON s.id=v.script_id WHERE v.id=?", (variant_id,))
        rng = np.random.default_rng(int(hashlib.sha1(
            (variant_id + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:8], 16))
        p = _p_for(v["condition"])
        if params.get("model") != "prisma-v3.0":
            p *= 1.25
        keyterms = set()
        if params.get("keyterms"):
            keyterms = {w for k in json.loads(v["keyterms_json"]) for w in k.split()}
            p *= 0.7
        out = []
        for w in v["text"].split():
            r = rng.random()
            if w.strip("।,.") in keyterms:
                r *= 1.5
            if r < p * 0.4:
                continue                      # deletion
            if r < p:
                if w.isdigit() or any(c.isdigit() for c in w):
                    w = "".join(str((int(c) + 1) % 10) if c.isdigit() and rng.random() < 0.5 else c for c in w)
                else:
                    w = w[:-1] if len(w) > 2 else w + "x"
            out.append(w)
        lang = params.get("language_code", v["lang"])
        if lang == "indic-auto":
            lang = v["lang"] if rng.random() > p * 0.6 else "hi-IN"
        return {"transcript": " ".join(out), "detected_language": lang,
                "latency_ms": int(250 + 400 * rng.random()), "request_id": f"mock-{rng.integers(1e9)}"}
