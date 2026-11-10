"""Paired comparison of each STT config against the baseline, with bootstrap confidence intervals."""
from __future__ import annotations

import numpy as np
import pandas as pd

METRICS = [("entity_recall", +1), ("wer", -1)]   # (column, direction where +1 = higher is better)


def _boot_ci(deltas: np.ndarray, n: int = 2000, seed: int = 7):
    if len(deltas) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = rng.choice(deltas, size=(n, len(deltas)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def recommend(df: pd.DataFrame, baseline: str, min_pairs: int = 5) -> list[dict]:
    out = []
    if df.empty:
        return out
    base = df[df["config"] == baseline].set_index("variant_id")
    for cfg in sorted(set(df["config"]) - {baseline}):
        alt = df[df["config"] == cfg].set_index("variant_id")
        common = base.index.intersection(alt.index)
        if len(common) < min_pairs:
            continue
        for cls in sorted(set(base.loc[common, "cond_class"])):
            ids = [i for i in common if base.loc[i, "cond_class"] == cls]
            if len(ids) < min_pairs:
                continue
            row = {"config": cfg, "cond_class": cls, "n_pairs": len(ids)}
            for metric, direction in METRICS:
                d = (alt.loc[ids, metric].astype(float) - base.loc[ids, metric].astype(float)).dropna().values
                if len(d) < min_pairs:
                    continue
                lo, hi = _boot_ci(d)
                row[metric] = {"delta": float(d.mean()) * direction, "lo": min(lo * direction, hi * direction),
                               "hi": max(lo * direction, hi * direction), "n": int(len(d))}
            out.append(row)
    return out


def recommendations_md(recs: list[dict]) -> str:
    if not recs:
        return ("_Not enough paired runs yet (need at least 5 per condition class and config). "
                "Run a larger profile._\n")
    lines = ["Positive numbers mean **better than baseline** (higher entity recall / lower WER). "
             "A result is only called an improvement when its 95% bootstrap CI excludes zero. "
             "CAUTION: in adaptive sweeps only the baseline's *hard cases* were re-run, which flatters every "
             "alternative (regression to the mean). Treat those numbers as an upper bound and confirm the "
             "finalists with `sweep.mode: full`.\n"]
    for r in recs:
        for metric, _ in METRICS:
            m = r.get(metric)
            if not m:
                continue
            verdict = ("improves" if m["lo"] > 0 else "hurts" if m["hi"] < 0 else "no clear effect on")
            lines.append(f"- `{r['config']}` {verdict} **{metric}** under *{r['cond_class']}* audio: "
                         f"{m['delta']:+.3f} (95% CI {m['lo']:+.3f} to {m['hi']:+.3f}, n={m['n']})")
    return "\n".join(lines) + "\n"
