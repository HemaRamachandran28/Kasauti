import json
from pathlib import Path

import pytest

from kasauti import pipeline as P
from kasauti.config import load_config
from kasauti.recommend import recommend
from kasauti.report import build_reports, diff_html, load_frame


@pytest.fixture()
def ctx(tmp_path):
    cfg = load_config(profile="smoke")
    cfg["paths"].update({"db_mock": str(tmp_path / "t.db"), "audio_mock": str(tmp_path / "audio"),
                         "reports_mock": str(tmp_path / "rep")})
    # make_ctx joins paths onto ROOT; absolute paths override that
    c = P.make_ctx(cfg, mock=True)
    P.load_scripts(c)
    return c


def test_scripts_are_valid():
    data = json.loads((Path(__file__).resolve().parent.parent / "data" / "scripts.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["scripts"]]
    assert len(ids) == len(set(ids)) == 40
    for s in data["scripts"]:
        for e in s["entities"]:
            if e["type"] == "digits":
                spaced = " ".join(e["value"])
                assert spaced in s["text"], (s["id"], e)       # digits are written digit-by-digit
            if e["type"] == "name":
                assert e["value"] in s["text"], (s["id"], e)


def test_end_to_end_smoke(ctx):
    assert P.generate(ctx) == 5
    assert P.generate(ctx) == 0                      # cached: no repeat API calls
    P.run_degrade(ctx)
    n = P.transcribe(ctx)
    assert n >= 10
    assert P.transcribe(ctx) == 0                    # resumable
    df = load_frame(ctx.db)
    assert len(df) >= 10 and df["wer"].notna().all() and df["mock"].all()
    out = build_reports(ctx, "baseline")
    assert (out / "summary.md").read_text(encoding="utf-8").startswith("> **MOCK DATA")
    st = P.status(ctx)
    assert st["runs_error"] == 0 and st["mock"] is True


def test_rescore_needs_no_calls(ctx):
    P.generate(ctx); P.run_degrade(ctx); P.transcribe(ctx)
    before = ctx.db.one("SELECT COUNT(*) c FROM api_calls")["c"]
    assert P.score_runs(ctx, rescore=True) > 0
    assert ctx.db.one("SELECT COUNT(*) c FROM api_calls")["c"] == before


def test_recommend_requires_pairs():
    import pandas as pd
    assert recommend(pd.DataFrame(), "baseline") == []


def test_diff_html_marks_errors():
    h = diff_html("pay 5000 today", "pay 5100 today")
    assert "background:#fdd" in h and "background:#dfd" in h
