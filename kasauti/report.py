"""Load scored runs into pandas and produce summaries, CSVs and markdown reports."""
from __future__ import annotations

import difflib
import html
from pathlib import Path

import numpy as np
import pandas as pd

from kasauti import textnorm as tn
from kasauti.degrade import condition_meta

SQL = """
SELECT r.id run_id, r.variant_id, r.config, r.transcript, r.detected_language, r.latency_ms, r.mock,
       v.script_id, v.source, v.voice, v.tts_variant, v.condition, v.path,
       s.grp, s.lang, s.text AS reference,
       sc.wer, sc.cer, sc.digit_exact, sc.digit_characc, sc.amount_exact, sc.name_match,
       sc.lang_match, sc.entity_recall
FROM runs r JOIN variants v ON v.id=r.variant_id JOIN scripts s ON s.id=v.script_id
LEFT JOIN scores sc ON sc.run_id=r.id WHERE r.status='ok'
"""


def load_frame(db) -> pd.DataFrame:
    df = pd.DataFrame(db.query(SQL))
    if df.empty:
        return df
    meta = df["condition"].map(condition_meta).apply(pd.Series)
    return pd.concat([df, meta], axis=1)


def condition_order(df: pd.DataFrame) -> list[str]:
    return list(df.drop_duplicates("condition").sort_values("severity")["condition"])


def df_to_md(df: pd.DataFrame, digits: int = 3) -> str:
    if df.empty:
        return "_no data_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in df.iterrows():
        cells = []
        for v in row:
            cells.append(f"{v:.{digits}f}" if isinstance(v, (float, np.floating)) and not pd.isna(v)
                         else ("" if (isinstance(v, float) and pd.isna(v)) else str(v)))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def diff_html(reference: str, hypothesis: str) -> str:
    """Word-level diff of normalised text: red = missing/wrong in transcript, green = extra."""
    r, h = tn.tokens(reference), tn.tokens(hypothesis)
    out = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(a=r, b=h, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(html.escape(" ".join(r[a0:a1])))
        else:
            if a1 > a0:
                out.append(f"<span style='background:#fdd;text-decoration:line-through'>{html.escape(' '.join(r[a0:a1]))}</span>")
            if b1 > b0:
                out.append(f"<span style='background:#dfd'>{html.escape(' '.join(h[b0:b1]))}</span>")
    return " ".join(out)


def by_condition(df: pd.DataFrame, config: str | None = None) -> pd.DataFrame:
    d = df if config is None else df[df["config"] == config]
    g = d.groupby(["grp", "source", "condition"], as_index=False).agg(
        n=("run_id", "count"), wer=("wer", "mean"), cer=("cer", "mean"),
        entity_recall=("entity_recall", "mean"), digit_exact=("digit_exact", "mean"),
        lang_match=("lang_match", "mean"))
    order = {c: i for i, c in enumerate(condition_order(df))}
    g["_o"] = g["condition"].map(order)
    return g.sort_values(["grp", "source", "_o"]).drop(columns="_o")


def by_config(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(["config", "cond_class"], as_index=False).agg(
        n=("run_id", "count"), wer=("wer", "mean"), entity_recall=("entity_recall", "mean"),
        digit_exact=("digit_exact", "mean"), lang_match=("lang_match", "mean"),
        latency_ms=("latency_ms", "mean"))


def human_gap(df: pd.DataFrame, config: str) -> pd.DataFrame:
    d = df[df["config"] == config]
    if d["source"].nunique() < 2:
        return pd.DataFrame()
    piv = d.pivot_table(index=["grp", "condition"], columns="source", values="wer", aggfunc="mean").reset_index()
    if "human" in piv and "tts" in piv:
        piv["gap_human_minus_tts"] = piv["human"] - piv["tts"]
    return piv


def build_reports(ctx, baseline: str) -> Path:
    from kasauti.recommend import recommend, recommendations_md
    df = load_frame(ctx.db)
    out = ctx.report_dir
    out.mkdir(parents=True, exist_ok=True)
    if df.empty:
        (out / "summary.md").write_text("No scored runs yet.\n", encoding="utf-8")
        return out
    banner = ("> **MOCK DATA: simulated transcripts, NOT real Gnani results. Do not publish.**\n\n"
              if df["mock"].any() else "")
    df.drop(columns=["path"]).to_csv(out / "runs_scored.csv", index=False)
    bc, cf = by_condition(df, baseline), by_config(df)
    bc.to_csv(out / "by_condition.csv", index=False)
    cf.to_csv(out / "by_config.csv", index=False)
    gap = human_gap(df, baseline)
    if not gap.empty:
        gap.to_csv(out / "human_gap.csv", index=False)
    recs = recommend(df, baseline)
    (out / "recommendations.md").write_text(banner + recommendations_md(recs), encoding="utf-8")
    parts = [banner, "# Kasauti summary\n",
             f"Runs scored: **{len(df)}**  |  scripts: {df['script_id'].nunique()}  |  "
             f"conditions: {df['condition'].nunique()}  |  configs: {df['config'].nunique()}\n",
             f"\n## Baseline (`{baseline}`) by group and condition\n", df_to_md(bc),
             "\n## Configs by condition class\n", df_to_md(cf)]
    if not gap.empty:
        parts += ["\n## Human vs synthetic (WER)\n", df_to_md(gap)]
    parts += ["\n## Recommendations\n", recommendations_md(recs)]
    (out / "summary.md").write_text("".join(parts), encoding="utf-8")
    print(f"[report] wrote {out}/summary.md and CSVs")
    return out
