"""Config + .env loading and profile resolution."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=None) -> None:
    p = Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path=None, profile: str = "core") -> dict:
    p = Path(path) if path else ROOT / "config.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    profiles = cfg.get("profiles") or {}
    if profile not in profiles:
        raise SystemExit(f"Unknown profile '{profile}'. Available: {', '.join(profiles)}")
    cfg["profile_name"] = profile
    cfg["spec"] = resolve_spec(cfg, profiles[profile])
    return cfg


def resolve_spec(cfg: dict, prof: dict) -> dict:
    enabled = [k for k, v in cfg["stt_configs"].items() if v.get("enabled", True)]
    configs = list(prof.get("configs", enabled))
    for c in configs:
        if c not in cfg["stt_configs"]:
            raise SystemExit(f"Profile references unknown stt config '{c}'")
    baseline = cfg["sweep"]["baseline"]
    if baseline not in configs:
        configs = [baseline] + configs
    return {
        "groups": prof.get("groups", cfg["groups"]),
        "scripts_per_group": prof.get("scripts_per_group"),
        "conditions": prof.get("conditions", cfg["conditions"]),
        "configs": configs,
        "voices": prof.get("voices", cfg["tts"]["voices"]),
        "tts_variants": prof.get("tts_variants", cfg["tts"]["variants"]),
    }


def config_format(params: dict) -> str:
    """Output style a config produces (decides which entities can be scored fairly)."""
    if params.get("format"):
        return params["format"]
    if str(params.get("enable_itn", "")).lower() == "true":
        return "transcribe"
    return "verbatim"
