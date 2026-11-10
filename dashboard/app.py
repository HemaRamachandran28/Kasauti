"""Kasauti dashboard.  Run:  python -m kasauti dashboard   (add --mock for the offline demo data)"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import altair as alt
import pandas as pd
import streamlit as st

from kasauti.db import DB
from kasauti.recommend import recommend, recommendations_md
from kasauti.report import by_condition, condition_order, diff_html, human_gap, load_frame

st.set_page_config(page_title="Kasauti: Indic voice-AI stress test", layout="wide")

default_db = os.environ.get("KASAUTI_DB", str(ROOT / "data" / "kasauti.db"))
db_path = st.sidebar.text_input("Database", default_db)
if not Path(db_path).exists():
    st.error(f"No database at {db_path}. Run the pipeline first (see README), or use --mock for demo data.")
    st.stop()


@st.cache_data(show_spinner=False)
def get_frame(path: str, mtime: float) -> pd.DataFrame:
    return load_frame(DB(path))


df = get_frame(db_path, Path(db_path).stat().st_mtime)
st.title("Kasauti: a touchstone for Indic voice AI")
st.caption("Timbre v3.0 generates the calls, a telephony/noise lab degrades them, Prisma v3.0 transcribes them, "
           "and this dashboard shows where accuracy breaks and which settings fix it.")
if df.empty:
    st.warning("No scored runs yet.")
    st.stop()
if df["mock"].any():
    st.error("MOCK DATA: simulated transcripts, not real Gnani results. Do not publish.")

configs = sorted(df["config"].unique())
baseline = "baseline" if "baseline" in configs else configs[0]
order = condition_order(df)
groups = sorted(df["grp"].unique())
GROUP_NAMES = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish", "ta": "Tamil", "te": "Telugu"}

sel_cfg = st.sidebar.selectbox("Config", configs, index=configs.index(baseline))
sel_src = st.sidebar.multiselect("Audio source", sorted(df["source"].unique()), default=sorted(df["source"].unique()))
view = df[(df["config"] == sel_cfg) & (df["source"].isin(sel_src))]

tabs = st.tabs(["Overview", "Degradation curves", "Config comparison", "Human vs synthetic",
                "Failure explorer", "Recommendations"])

with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runs scored", len(view))
    c2.metric("Mean WER", f"{view['wer'].mean():.2f}" if view["wer"].notna().any() else "n/a")
    c3.metric("Entity recall", f"{view['entity_recall'].mean():.2f}" if view["entity_recall"].notna().any() else "n/a")
    c4.metric("Mean latency (ms)", f"{view['latency_ms'].mean():.0f}")
    st.write("Entity recall = digit strings (phone/OTP/PIN/account), amounts (digit-producing formats only) "
             "and names recovered exactly or near-exactly. Higher is better.")
    heat = view.groupby(["grp", "condition"], as_index=False)["entity_recall"].mean()
    st.altair_chart(alt.Chart(heat).mark_rect().encode(
        x=alt.X("condition:N", sort=order, title="condition"), y=alt.Y("grp:N", title="language group"),
        color=alt.Color("entity_recall:Q", scale=alt.Scale(domain=[0, 1], scheme="redyellowgreen")),
        tooltip=["grp", "condition", alt.Tooltip("entity_recall:Q", format=".2f")]).properties(height=240),
        width="stretch")

with tabs[1]:
    metric = st.radio("Metric", ["wer", "cer", "entity_recall", "digit_exact"], horizontal=True)
    g = view.groupby(["grp", "condition"], as_index=False)[metric].mean()
    st.altair_chart(alt.Chart(g).mark_line(point=True).encode(
        x=alt.X("condition:N", sort=order), y=alt.Y(f"{metric}:Q"), color="grp:N",
        tooltip=["grp", "condition", alt.Tooltip(f"{metric}:Q", format=".3f")]).properties(height=380),
        width="stretch")
    st.caption("Conditions are ordered from mildest to harshest. 'tel' = 300-3400 Hz, 8 kHz, mu-law; "
               "'babble:N' = other speakers mixed in at N dB SNR.")
    st.dataframe(by_condition(df, sel_cfg), width="stretch")

with tabs[2]:
    m2 = st.radio("Metric ", ["entity_recall", "wer", "digit_exact", "lang_match"], horizontal=True)
    g = df[df["source"].isin(sel_src)].groupby(["config", "cond_class"], as_index=False)[m2].mean()
    st.altair_chart(alt.Chart(g).mark_bar().encode(
        x=alt.X("cond_class:N", title="condition class"), y=alt.Y(f"{m2}:Q"), color="config:N",
        xOffset="config:N", tooltip=["config", "cond_class", alt.Tooltip(f"{m2}:Q", format=".3f")]).properties(height=380),
        width="stretch")
    st.caption("In adaptive sweeps non-baseline configs only ran on the baseline's hard cases, so use the "
               "Recommendations tab (paired comparison) for fair conclusions.")

with tabs[3]:
    gap = human_gap(df, sel_cfg)
    if gap.empty:
        st.info("Add your own recordings (see README step 8) to measure the synthetic-vs-human gap.")
    else:
        st.dataframe(gap, width="stretch")
        melted = gap.melt(id_vars=["grp", "condition"], value_vars=[c for c in ("tts", "human") if c in gap],
                          var_name="source", value_name="wer")
        st.altair_chart(alt.Chart(melted).mark_bar().encode(
            x=alt.X("condition:N", sort=order), y="wer:Q", color="source:N", xOffset="source:N",
            column="grp:N").properties(height=250), width="content")
        st.caption("TTS test audio is cleaner than real speakers; a large gap means synthetic-only tests are optimistic.")

with tabs[4]:
    st.write("Pick a failure and inspect it: red = reference words the model got wrong or dropped, green = extra words.")
    bad = view.sort_values("wer", ascending=False).head(200)
    if bad.empty:
        st.info("Nothing to show.")
    else:
        labels = [f"{r.script_id} | {r.voice} | {r.condition} | WER {r.wer:.2f}" for r in bad.itertuples()]
        pick = st.selectbox("Run", range(len(bad)), format_func=lambda i: labels[i])
        row = bad.iloc[pick]
        st.markdown(diff_html(row["reference"], row["transcript"]), unsafe_allow_html=True)
        st.code(f"reference: {row['reference']}\ntranscript: {row['transcript']}\ndetected: {row['detected_language']}")
        if row["path"] and Path(row["path"]).exists():
            st.audio(row["path"])

with tabs[5]:
    st.markdown(recommendations_md(recommend(df, baseline)))
