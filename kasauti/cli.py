"""Command line interface:  python -m kasauti <command> [options]"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from kasauti import pipeline as P
from kasauti.config import ROOT, load_config, load_env
from kasauti.degrade import read_audio


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--config", default=None, help="path to config.yaml")
    p.add_argument("--profile", default="core", help="smoke | core | full (see config.yaml)")
    p.add_argument("--mock", action="store_true", help="offline simulation (NOT real results)")
    p.add_argument("--db", default=None, help="override database path")
    p.add_argument("--yes", action="store_true", help="skip confirmation prompts")
    return p


def _ctx(args, need_client=True):
    load_env()
    cfg = load_config(args.config, args.profile)
    ctx = P.make_ctx(cfg, mock=args.mock, db_path=args.db, need_client=need_client)
    if ctx.mock:
        print("*** MOCK MODE: simulated data, not real Gnani results ***")
    P.load_scripts(ctx)
    return ctx


def _confirm(args, msg: str):
    print(msg)
    if args.yes:
        return
    if input("Continue? [y/N] ").strip().lower() != "y":
        raise SystemExit("Aborted.")


def cmd_init(a):
    ctx = _ctx(a, need_client=False)
    print(f"Database ready at {ctx.db.path} with {len(P.selected_scripts(ctx))} scripts in profile '{a.profile}'.")


def cmd_plan(a):
    ctx = _ctx(a, need_client=False)
    print(json.dumps(P.plan(ctx), indent=2))
    print("\nNote: credits per call are not published in the docs I could read. Use `probe` and compare your "
          "balance in app.gnani.ai before/after to compute your own per-call cost.")


def cmd_probe(a):
    """One TTS + one STT call: verifies key, request shapes, 16 kHz audio and the 8 kHz telephony path."""
    ctx = _ctx(a)
    ctx.cfg["spec"]["groups"], ctx.cfg["spec"]["scripts_per_group"] = ["en"], 1
    ctx.cfg["spec"]["conditions"] = ["clean", "tel"]
    ctx.cfg["spec"]["configs"] = [ctx.cfg["sweep"]["baseline"]]
    P.generate(ctx)
    P.run_degrade(ctx)
    for v in P.selected_variants(ctx):
        r = ctx.client.stt(v["path"], P.stt_params(ctx, ctx.cfg["sweep"]["baseline"], v), variant_id=v["id"])
        dur = len(read_audio(v["path"])[0]) / v["sample_rate"]
        print(f"{v['condition']:>6} ({v['sample_rate']} Hz, {dur:.1f}s) -> {r['transcript']!r} "
              f"[{r['detected_language']}, {r['latency_ms']} ms]")
    print("\nListen to the WAVs in", ctx.audio_dir, "to confirm digits are read one by one.")
    print("Probe used 1 TTS + 2 STT calls. Compare your balance in app.gnani.ai to get credits/call.")


def cmd_generate(a):
    ctx = _ctx(a)
    pl = P.plan(ctx)
    _confirm(a, f"About to synthesise up to {pl['tts_calls_needed_upper_bound']} clips with Timbre (cached clips are skipped).")
    P.generate(ctx)


def cmd_degrade(a):
    P.run_degrade(_ctx(a, need_client=False))


def cmd_ingest(a):
    P.ingest_human(_ctx(a, need_client=False), a.dir)


def cmd_transcribe(a):
    ctx = _ctx(a)
    pl = P.plan(ctx)
    _confirm(a, f"About to make roughly {pl['stt_calls_expected']} Prisma calls "
                f"(max {pl['stt_calls_max']}, mode={pl['mode']}; finished runs are skipped).")
    P.transcribe(ctx)


def cmd_score(a):
    print("rescored", P.score_runs(_ctx(a, need_client=False), rescore=True), "runs (no API calls)")


def cmd_report(a):
    ctx = _ctx(a, need_client=False)
    from kasauti.report import build_reports
    build_reports(ctx, ctx.cfg["sweep"]["baseline"])


def cmd_run_all(a):
    ctx = _ctx(a)
    pl = P.plan(ctx)
    _confirm(a, f"Full run: ~{pl['tts_calls_needed_upper_bound']} TTS + ~{pl['stt_calls_expected']} STT calls "
                f"(profile={a.profile}, mock={a.mock}).")
    P.generate(ctx)
    P.run_degrade(ctx)
    P.transcribe(ctx)
    from kasauti.report import build_reports
    build_reports(ctx, ctx.cfg["sweep"]["baseline"])


def cmd_status(a):
    print(json.dumps(P.status(_ctx(a, need_client=False)), indent=2))


def cmd_record_sheet(a):
    ctx = _ctx(a, need_client=False)
    lines = ["# Record these clips (one WAV per script, 16 kHz mono ideal, < 30 s)\n",
             "Name files `<script_id>__<yourname>.wav`, put them in `data/human/`, then run `ingest-human`.\n"]
    for s in P.selected_scripts(ctx):
        lines.append(f"- **{s['id']}**: {s['text']}")
    out = ROOT / "data" / "human" / "RECORD_THESE.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", out)


def cmd_dashboard(a):
    db = ROOT / (a.db or ("data/kasauti_mock.db" if a.mock else "data/kasauti.db"))
    env = dict(**__import__("os").environ, KASAUTI_DB=str(db))
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py")], env=env, cwd=ROOT)


def main(argv=None):
    c = _common()
    ap = argparse.ArgumentParser(prog="kasauti", description="Stress-test lab for Indic voice AI (Gnani Prisma + Timbre)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, h in [
        ("init", cmd_init, "create database and load scripts"),
        ("plan", cmd_plan, "show how many API calls a profile will make"),
        ("probe", cmd_probe, "1 TTS + 2 STT calls to verify key and request shapes"),
        ("generate", cmd_generate, "synthesise test clips with Timbre"),
        ("degrade", cmd_degrade, "apply telephony / noise conditions (no API calls)"),
        ("transcribe", cmd_transcribe, "run the Prisma config sweep"),
        ("score", cmd_score, "re-score all runs (no API calls)"),
        ("report", cmd_report, "write reports/ summaries and CSVs"),
        ("run-all", cmd_run_all, "generate + degrade + transcribe + report"),
        ("status", cmd_status, "API calls made so far, rows in DB"),
        ("record-sheet", cmd_record_sheet, "list scripts to record yourself"),
        ("dashboard", cmd_dashboard, "open the Streamlit dashboard"),
    ]:
        sp = sub.add_parser(name, parents=[c], help=h)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("ingest-human", parents=[c], help="import your own recordings from a folder")
    sp.add_argument("--dir", default=str(ROOT / "data" / "human"))
    sp.set_defaults(fn=cmd_ingest)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
