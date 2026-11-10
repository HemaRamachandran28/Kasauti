"""generate -> degrade -> transcribe -> score. Everything is cached in SQLite + audio files,
so interrupted runs resume without re-spending API credits."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from kasauti import degrade
from kasauti.config import ROOT, config_format
from kasauti.db import DB
from kasauti.gnani import GnaniClient, ApiError, keyterms_param
from kasauti.mock import MockClient
from kasauti.scoring import score_run

TAGS = {"plain": "{t}", "whisper": "<whispers> {t}", "shout": "<shouting> {t}"}


@dataclass
class Ctx:
    cfg: dict
    db: DB
    client: object
    audio_dir: Path
    report_dir: Path
    mock: bool

    @property
    def spec(self):
        return self.cfg["spec"]


def make_ctx(cfg: dict, mock: bool = False, db_path: str | None = None, need_client: bool = True) -> Ctx:
    p = cfg["paths"]
    key_db, key_audio, key_rep = ("db_mock", "audio_mock", "reports_mock") if mock else ("db", "audio", "reports")
    db = DB(ROOT / (db_path or p[key_db]))
    audio_dir = ROOT / p[key_audio]
    audio_dir.mkdir(parents=True, exist_ok=True)
    client = None
    if need_client:
        if mock:
            client = MockClient(db)
        else:
            a = cfg["api"]
            client = GnaniClient(os.environ.get("GNANI_API_KEY", ""), a["base_url"], a["timeout_s"],
                                 a["max_retries"], a["qps"])
    ctx = Ctx(cfg, db, client, audio_dir, ROOT / p[key_rep], mock)
    db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('mock',?)", ("1" if mock else "0",))
    return ctx


# ----------------------------------------------------------------------------- helpers
def _safe(vid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", vid)[:90] + "-" + hashlib.sha1(vid.encode()).hexdigest()[:6]


def clean_vid(script_id, voice, tts_variant) -> str:
    return f"{script_id}|{voice}|{tts_variant}|clean"


def cond_vid(clean_id: str, cond: str) -> str:
    return clean_id.rsplit("|", 1)[0] + "|" + cond


def _log_call(ctx: Ctx, kind: str, ok: bool, ms: int):
    ctx.db.execute("INSERT INTO api_calls(kind,ok,ms,mock) VALUES(?,?,?,?)", (kind, int(ok), ms, int(ctx.mock)))


def load_scripts(ctx: Ctx, path=None) -> int:
    p = Path(path) if path else ROOT / "data" / "scripts.json"
    data = json.loads(p.read_text(encoding="utf-8"))["scripts"]
    for s in data:
        ctx.db.execute("INSERT OR REPLACE INTO scripts VALUES(?,?,?,?,?,?)",
                       (s["id"], s["group"], s["lang"], s["text"],
                        json.dumps(s["entities"], ensure_ascii=False),
                        json.dumps(s.get("keyterms", []), ensure_ascii=False)))
    return len(data)


def selected_scripts(ctx: Ctx) -> list[dict]:
    spec = ctx.spec
    rows = []
    for g in spec["groups"]:
        r = ctx.db.query("SELECT * FROM scripts WHERE grp=? ORDER BY id", (g,))
        n = spec["scripts_per_group"]
        rows += r[:n] if n else r
    return rows


def selected_variants(ctx: Ctx) -> list[dict]:
    """Variants (clean + degraded, synthetic + human) that belong to the active profile."""
    spec = ctx.spec
    ids = [s["id"] for s in selected_scripts(ctx)]
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    rows = ctx.db.query(
        f"SELECT v.*, s.grp, s.lang, s.text, s.keyterms_json, s.entities_json FROM variants v "
        f"JOIN scripts s ON s.id=v.script_id WHERE v.script_id IN ({ph})", tuple(ids))
    out = []
    for v in rows:
        if v["condition"] not in set(spec["conditions"]) | {"clean"}:
            continue
        if v["condition"] != "clean" and v["condition"] not in spec["conditions"]:
            continue
        if v["condition"] == "clean" and "clean" not in spec["conditions"]:
            continue
        if v["source"] == "tts" and not (v["voice"] in spec["voices"] and v["tts_variant"] in spec["tts_variants"]):
            continue
        out.append(v)
    return out


def _progress(i, n, label):
    if i % 10 == 0 or i == n:
        print(f"  {label}: {i}/{n}", flush=True)


# ----------------------------------------------------------------------------- plan
def plan(ctx: Ctx) -> dict:
    spec, cfg = ctx.spec, ctx.cfg
    scripts = selected_scripts(ctx)
    n_clean = len(scripts) * len(spec["voices"]) * len(spec["tts_variants"])
    have_clean = ctx.db.one("SELECT COUNT(*) c FROM variants WHERE condition='clean' AND source='tts'")["c"]
    n_human = ctx.db.one("SELECT COUNT(*) c FROM variants WHERE condition='clean' AND source='human'")["c"]
    n_variants = (n_clean + n_human) * len(spec["conditions"])
    base_calls = n_variants
    full_calls = n_variants * len(spec["configs"])
    mode = cfg["sweep"]["mode"]
    done = ctx.db.one("SELECT COUNT(*) c FROM runs WHERE status='ok'")["c"]
    return {"scripts": len(scripts), "tts_calls_needed_upper_bound": max(0, n_clean - 0),
            "tts_clean_in_db": have_clean, "human_clean_in_db": n_human,
            "variants": n_variants, "stt_calls_baseline": base_calls,
            "stt_calls_max": full_calls if mode == "full" else base_calls * len(spec["configs"]),
            "stt_calls_expected": full_calls if mode == "full" else
            int(base_calls * (1 + 0.5 * (len(spec["configs"]) - 1))),
            "mode": mode, "stt_runs_already_done": done}


# ----------------------------------------------------------------------------- generate
def generate(ctx: Ctx) -> int:
    spec, tts = ctx.spec, ctx.cfg["tts"]
    todo = []
    for s in selected_scripts(ctx):
        for voice in spec["voices"]:
            for tv in spec["tts_variants"]:
                vid = clean_vid(s["id"], voice, tv)
                path = ctx.audio_dir / f"{_safe(vid)}.wav"
                if ctx.db.one("SELECT 1 x FROM variants WHERE id=?", (vid,)) and path.exists():
                    continue
                todo.append((s, voice, tv, vid, path))
    print(f"[generate] {len(todo)} TTS calls ({len(selected_scripts(ctx))} scripts)")

    def work(item):
        s, voice, tv, vid, path = item
        text = TAGS[tv].format(t=s["text"])
        t0 = time.monotonic()
        wav = ctx.client.tts(text, voice, tts["model"], s["lang"], tts["audio_config"], tts.get("speed", 1.0))
        ms = int((time.monotonic() - t0) * 1000)
        x, sr = degrade.read_audio(wav)
        x = degrade.resample(x, sr, degrade.TARGET_SR)
        degrade.write_wav(path, x, degrade.TARGET_SR)
        return item, len(x) / degrade.TARGET_SR, ms

    done = 0
    with ThreadPoolExecutor(max_workers=ctx.cfg["api"]["workers"]) as ex:
        futs = {ex.submit(work, it): it for it in todo}
        for i, f in enumerate(as_completed(futs), 1):
            it = futs[f]
            try:
                (s, voice, tv, vid, path), dur, ms = f.result()
            except Exception as e:
                _log_call(ctx, "tts", False, 0)
                print(f"  ! TTS failed for {it[3]}: {e}", file=sys.stderr)
                continue
            _log_call(ctx, "tts", True, ms)
            if dur > 30:
                print(f"  ! {vid} is {dur:.1f}s; REST STT accepts 30s max. Shorten the script.", file=sys.stderr)
            ctx.db.execute("INSERT OR REPLACE INTO variants VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (vid, s["id"], "tts", voice, tv, "clean", None, str(path),
                            degrade.TARGET_SR, int(ctx.mock)))
            done += 1
            _progress(i, len(todo), "TTS")
    return done


# ----------------------------------------------------------------------------- human clips
def ingest_human(ctx: Ctx, folder: str) -> int:
    """Files named <script_id>__<speaker>.<ext>, e.g. ta-003__hema.wav. Converted to 16 kHz mono WAV."""
    import subprocess
    n = 0
    for f in sorted(Path(folder).glob("*__*.*")):
        if f.suffix.lower() in (".md", ".txt", ".csv"):
            continue
        sid, speaker = f.stem.split("__", 1)
        if not ctx.db.one("SELECT 1 x FROM scripts WHERE id=?", (sid,)):
            print(f"  ! skipping {f.name}: unknown script id '{sid}'", file=sys.stderr)
            continue
        vid = clean_vid(sid, f"human:{speaker}", "plain")
        out = ctx.audio_dir / f"{_safe(vid)}.wav"
        try:
            x, sr = degrade.read_audio(f)
        except Exception:
            tmp = out.with_suffix(".tmp.wav")
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(f), "-ac", "1", "-ar", "16000", str(tmp)])
            if r.returncode != 0:
                print(f"  ! cannot decode {f.name} (install ffmpeg or export as WAV)", file=sys.stderr)
                continue
            x, sr = degrade.read_audio(tmp)
            tmp.unlink()
        x = degrade.resample(x, sr, degrade.TARGET_SR)
        if len(x) / degrade.TARGET_SR > 30:
            print(f"  ! {f.name} is longer than 30s; REST STT limit. Trim it.", file=sys.stderr)
        degrade.write_wav(out, x, degrade.TARGET_SR)
        ctx.db.execute("INSERT OR REPLACE INTO variants VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (vid, sid, "human", f"human:{speaker}", "plain", "clean", None, str(out),
                        degrade.TARGET_SR, int(ctx.mock)))
        n += 1
    print(f"[ingest-human] imported {n} clips")
    return n


# ----------------------------------------------------------------------------- degrade
def run_degrade(ctx: Ctx) -> int:
    conds = [c for c in ctx.spec["conditions"] if c != "clean"]
    ids = [s["id"] for s in selected_scripts(ctx)]
    cleans = ctx.db.query("SELECT * FROM variants WHERE condition='clean'")
    cleans = [v for v in cleans if v["script_id"] in ids]
    made = 0
    cache: dict[str, np.ndarray] = {}

    def load(path):
        if path not in cache:
            cache[path] = degrade.read_audio(path)[0]
        return cache[path]

    for v in cleans:
        for cond in conds:
            did = cond_vid(v["id"], cond)
            out = ctx.audio_dir / f"{_safe(did)}.wav"
            if ctx.db.one("SELECT 1 x FROM variants WHERE id=?", (did,)) and out.exists():
                continue
            x, sr = degrade.read_audio(v["path"])
            rng = np.random.default_rng(int(hashlib.sha1(did.encode()).hexdigest()[:8], 16))
            others = [o for o in cleans if o["script_id"] != v["script_id"]]
            pick = [others[i] for i in rng.permutation(len(others))[:6]] if others else []
            pool = [load(o["path"]) for o in pick]
            y, out_sr = degrade.apply_condition(x, sr, cond, rng, pool)
            degrade.write_wav(out, y, out_sr)
            ctx.db.execute("INSERT OR REPLACE INTO variants VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (did, v["script_id"], v["source"], v["voice"], v["tts_variant"], cond, v["id"],
                            str(out), out_sr, int(ctx.mock)))
            made += 1
    print(f"[degrade] created {made} degraded files")
    return made


# ----------------------------------------------------------------------------- transcribe
def stt_params(ctx: Ctx, cfgname: str, v: dict) -> dict:
    params = {}
    for k, val in ctx.cfg["stt_configs"][cfgname]["params"].items():
        if val == "@lang":
            val = v["lang"]
        elif val == "@keyterms":
            val = keyterms_param(json.loads(v["keyterms_json"]))
        params[k] = val
    return params


def _runs_done(ctx: Ctx, cfgname: str) -> set[str]:
    return {r["variant_id"] for r in ctx.db.query("SELECT variant_id FROM runs WHERE config=? AND status='ok'", (cfgname,))}


def _execute_runs(ctx: Ctx, jobs: list[tuple[dict, str]], label: str) -> int:
    if not jobs:
        return 0
    print(f"[transcribe] {label}: {len(jobs)} STT calls")

    def work(job):
        v, cfgname = job
        t0 = time.monotonic()
        res = ctx.client.stt(v["path"], stt_params(ctx, cfgname, v), variant_id=v["id"])
        return res, int((time.monotonic() - t0) * 1000)

    ok = 0
    with ThreadPoolExecutor(max_workers=ctx.cfg["api"]["workers"]) as ex:
        futs = {ex.submit(work, j): j for j in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            v, cfgname = futs[f]
            try:
                res, ms = f.result()
                _log_call(ctx, "stt", True, ms)
                ctx.db.execute(
                    "INSERT OR REPLACE INTO runs(variant_id,config,status,transcript,detected_language,"
                    "latency_ms,request_id,error,mock) VALUES(?,?,?,?,?,?,?,?,?)",
                    (v["id"], cfgname, "ok", res["transcript"], res["detected_language"],
                     res["latency_ms"], res["request_id"], None, int(ctx.mock)))
                ok += 1
            except ApiError as e:
                _log_call(ctx, "stt", False, 0)
                ctx.db.execute("INSERT OR REPLACE INTO runs(variant_id,config,status,error,mock) VALUES(?,?,?,?,?)",
                               (v["id"], cfgname, "error", str(e)[:500], int(ctx.mock)))
                print(f"  ! {v['id']} [{cfgname}]: {e}", file=sys.stderr)
            _progress(i, len(jobs), "STT")
    return ok


def score_runs(ctx: Ctx, rescore: bool = False) -> int:
    where = "" if rescore else "AND r.id NOT IN (SELECT run_id FROM scores)"
    rows = ctx.db.query(
        "SELECT r.id rid, r.config, r.transcript, r.detected_language, s.text, s.lang, s.entities_json "
        f"FROM runs r JOIN variants v ON v.id=r.variant_id JOIN scripts s ON s.id=v.script_id "
        f"WHERE r.status='ok' {where}")
    for r in rows:
        fmt = config_format(ctx.cfg["stt_configs"].get(r["config"], {"params": {}})["params"])
        sc = score_run(r, r["transcript"], fmt, r["detected_language"])
        ctx.db.execute("INSERT OR REPLACE INTO scores VALUES(?,?,?,?,?,?,?,?,?)",
                       (r["rid"], sc["wer"], sc["cer"], sc["digit_exact"], sc["digit_characc"],
                        sc["amount_exact"], sc["name_match"], sc["lang_match"], sc["entity_recall"]))
    return len(rows)


def transcribe(ctx: Ctx) -> int:
    spec, sweep = ctx.spec, ctx.cfg["sweep"]
    variants = selected_variants(ctx)
    base = sweep["baseline"]
    total = 0
    done = _runs_done(ctx, base)
    total += _execute_runs(ctx, [(v, base) for v in variants if v["id"] not in done], f"baseline '{base}'")
    score_runs(ctx)
    others = [c for c in spec["configs"] if c != base]
    if sweep["mode"] == "adaptive":
        hard = set()
        for r in ctx.db.query(
                "SELECT r.variant_id, sc.wer, sc.entity_recall FROM runs r JOIN scores sc ON sc.run_id=r.id "
                "WHERE r.config=? AND r.status='ok'", (base,)):
            if (r["wer"] is not None and r["wer"] > sweep["hard_wer"]) or \
               (r["entity_recall"] is not None and r["entity_recall"] < sweep["hard_entity_recall"]):
                hard.add(r["variant_id"])
        pool = [v for v in variants if v["id"] in hard]
        print(f"[transcribe] adaptive sweep: {len(pool)}/{len(variants)} variants are 'hard' for baseline")
    else:
        pool = variants
    for c in others:
        done = _runs_done(ctx, c)
        total += _execute_runs(ctx, [(v, c) for v in pool if v["id"] not in done], f"config '{c}'")
    score_runs(ctx)
    return total


def status(ctx: Ctx) -> dict:
    calls = ctx.db.query("SELECT kind, ok, COUNT(*) n FROM api_calls WHERE mock=? GROUP BY kind, ok", (int(ctx.mock),))
    return {"api_calls": calls,
            "scripts": ctx.db.one("SELECT COUNT(*) c FROM scripts")["c"],
            "variants": ctx.db.one("SELECT COUNT(*) c FROM variants")["c"],
            "runs_ok": ctx.db.one("SELECT COUNT(*) c FROM runs WHERE status='ok'")["c"],
            "runs_error": ctx.db.one("SELECT COUNT(*) c FROM runs WHERE status='error'")["c"],
            "mock": ctx.mock}
