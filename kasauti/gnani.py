"""Thin client for the Gnani speech APIs. Request shapes copied from docs.gnani.ai (Nov 2026)."""
from __future__ import annotations

import json
import threading
import time

import requests


class ApiError(RuntimeError):
    def __init__(self, status, kind, message):
        super().__init__(f"[{status}] {kind}: {message}")
        self.status, self.kind, self.message = status, kind, message


class GnaniClient:
    mock = False

    def __init__(self, api_key: str, base_url: str = "https://api.vachana.ai",
                 timeout: float = 60, max_retries: int = 4, qps: float = 2.0):
        if not api_key:
            raise SystemExit("GNANI_API_KEY is not set. Copy .env.example to .env and add your key, "
                             "or run with --mock to try the pipeline offline.")
        self.base = base_url.rstrip("/")
        self.timeout, self.max_retries = timeout, max_retries
        self.s = requests.Session()
        self.s.headers["X-API-Key-ID"] = api_key
        self._lock = threading.Lock()
        self._next = 0.0
        self._gap = 1.0 / max(qps, 0.1)

    def _throttle(self):
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            if wait > 0:
                time.sleep(wait)
            self._next = max(now, self._next) + self._gap

    def _request(self, method, url, **kw):
        last = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                last = ApiError(None, "NETWORK", str(e))
                time.sleep(min(2 ** attempt, 20))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = ApiError(r.status_code, "RETRYABLE", r.text[:300])
                time.sleep(min(1.5 * 2 ** attempt, 30))
                continue
            return r
        raise last

    def tts(self, text: str, voice: str, model: str, language: str, audio_config: dict,
            speed: float = 1.0) -> bytes:
        payload = {"text": text, "voice": voice, "model": model, "language": language,
                   "speed": speed, "audio_config": audio_config}
        r = self._request("POST", f"{self.base}/api/v1/tts/inference", json=payload)
        if r.status_code != 200 or not r.content[:4] == b"RIFF":
            raise ApiError(r.status_code, "TTS_FAILED", r.text[:300])
        return r.content

    def stt(self, audio_path, params: dict, variant_id: str | None = None) -> dict:
        data = open(audio_path, "rb").read()
        t0 = time.monotonic()
        r = self._request("POST", f"{self.base}/stt/v3",
                          files={"audio_file": ("audio.wav", data, "audio/wav")}, data=params)
        wall = int((time.monotonic() - t0) * 1000)
        try:
            body = r.json()
        except ValueError:
            raise ApiError(r.status_code, "BAD_RESPONSE", r.text[:300])
        if r.status_code != 200 or not body.get("success", False):
            err = body.get("error") or {}
            raise ApiError(r.status_code, err.get("type", "ERROR"), err.get("message") or r.text[:300])
        return {"transcript": body.get("transcript", ""),
                "detected_language": body.get("detected_language_code"),
                "latency_ms": wall, "request_id": body.get("request_id")}


def keyterms_param(terms: list[str]) -> str:
    return json.dumps(terms, ensure_ascii=False)
