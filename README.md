# Kasauti (कसौटी): a touchstone for Indic voice AI

Stress-test lab for voice agents built on **Gnani Prisma v3.0 (STT)** and **Timbre v3.0 (TTS)**.

```
script bank (40 BFSI/support calls: en, hi, hinglish, ta, te)
   -> Timbre v3.0 synthesises the calls            (your own recordings can be added too)
   -> degradation lab: telephony channel (300-3400 Hz, 8 kHz, mu-law) + babble/white noise at 20/10/5 dB SNR
   -> Prisma v3.0 sweep: language hint vs indic-auto, format (transcribe/verbatim/codemix), keyterms
   -> scoring: WER, CER, digit-string / amount / name recovery, language-detection accuracy
   -> paired comparison with bootstrap CIs -> dashboard + recommendations
```

> **Honest status:** I could not reach `api.vachana.ai` from my build sandbox. Request shapes (endpoints, headers,
> fields) were copied from docs.gnani.ai, and everything else (audio lab, scoring, DB, reports, dashboard) is
> tested offline (`pytest`: 17 tests, plus a full mock run). Step 4 (`probe`) is the first live check; if it fails,
> the error message tells you what to change (see Troubleshooting).
> **Mock mode produces simulated transcripts. Never publish mock numbers.**

---

## 0. Requirements
* Python 3.10+ (tested on 3.12), internet access, a Gnani API key from https://app.gnani.ai
* Optional: `ffmpeg` (only to import non-WAV recordings of your own voice)

## 1. Unzip and install
```bash
unzip kasauti.zip && cd kasauti
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Verify the install offline (no key needed)
```bash
python -m pytest -q                  # expect: 17 passed
python -m kasauti run-all --mock --profile smoke --yes
python -m kasauti dashboard --mock   # opens http://localhost:8501 with a red MOCK banner
```
Stop the dashboard with Ctrl+C. Mock data lives in separate files (`data/kasauti_mock.db`), so it can never mix with real results.

## 3. Add your API key
```bash
cp .env.example .env                 # Windows: copy .env.example .env
# edit .env and paste:  GNANI_API_KEY=your-key
```

## 4. Probe: one TTS call + two STT calls
Before running it, note your credit balance in the console (app.gnani.ai).
```bash
python -m kasauti probe
```
It prints the transcript for a clean clip and its telephony version. Then:
* **Listen** to the WAVs in `data/audio/`: the digits should be read one by one ("9 8 4 0 ..."). If Timbre reads them as one big number, change the digit spacing in `data/scripts.json`.
* **Check your balance again** and compute credits per TTS / STT call (the docs I read don't publish this).

## 5. Plan your budget
```bash
python -m kasauti plan --profile core
```
`core` = 20 scripts x 5 conditions = 100 variants. Baseline = 100 Prisma calls; with `sweep.mode: adaptive`
the other three configs only run on the baseline's hard cases (expect roughly 250 calls total). Multiply by the
per-call credits from step 4 and keep at least 40% of your 5,000 credits in reserve.

## 6. Smoke run on real audio (about 25 API calls)
```bash
python -m kasauti run-all --profile smoke --yes
python -m kasauti dashboard
```

## 7. Core run
```bash
python -m kasauti run-all --profile core
```
It is **resumable**: Ctrl+C or a network drop loses nothing, finished calls are never repeated. Check usage any time:
```bash
python -m kasauti status
```

## 8. Add real human recordings (do not skip, about 1 hour)
Synthetic audio is cleaner than real speakers and comes from the same vendor, so TTS-only tests are optimistic.
Recording 25-30 real clips lets you report the synthetic-vs-human gap, which is the most credible finding you will have.
```bash
python -m kasauti record-sheet       # writes data/human/RECORD_THESE.md
```
Record yourself (and friends/family) reading the listed scripts, one file each (phone voice recorder is fine),
named `<script_id>__<speaker>.wav`, e.g. `ta-003__hema.wav`, into `data/human/`. Then:
```bash
python -m kasauti ingest-human
python -m kasauti run-all --profile core --yes     # only the new human variants cost API calls
```
Clips must be under 30 s (REST limit). Say the digits one by one, like the script.

## 9. Final numbers (unbiased comparison)
Adaptive mode is cheap but flatters alternative configs (it only re-runs the baseline's failures). For the
configs you want to claim something about, set `sweep.mode: full` in `config.yaml` and re-run
`python -m kasauti transcribe --profile core --yes` if credits allow (about 400 calls for core).
Then:
```bash
python -m kasauti report
```
Outputs: `reports/summary.md`, `recommendations.md`, `by_condition.csv`, `by_config.csv`, `human_gap.csv`, `runs_scored.csv`.
Changing scoring code never costs credits: `python -m kasauti score && python -m kasauti report`.

## 10. Demo and submission
* `docs/DEMO_SCRIPT.md`: 60-second video script. Post the video on LinkedIn and/or X **early** (engagement is counted until the cutoff).
* `docs/POST_TEMPLATE.md`: post text with the required tags/hashtags.
* `docs/WRITEUP_TEMPLATE.md`: the written project explanation. Fill the `<<...>>` blanks from YOUR real results.
* Submit through the programme page by **Nov 10, 2026** (final, no extensions). Do it Nov 9 night, not Nov 10.
* Never buy or trade engagement; the terms prohibit it.

---

## What the scores mean
* **WER/CER**: after normalisation (native digits -> ASCII, digit-by-digit runs merged, punctuation and zero-width characters removed), so formatting choices don't masquerade as recognition errors.
* **digit_exact**: phone/OTP/PIN/account strings recovered exactly (formats: digits, digit words in en/hi/ta/te, romanised Hindi digit words).
* **amount_exact**: only scored for `format=transcribe` (other formats write amounts as words).
* **name_match**: fuzzy match (>= 0.75 similarity) of the name inside any window of the transcript.
* **lang_match**: `detected_language_code` equals the script language. This tag is derived from the transcript script, not the audio, and Hindi/Marathi can be confused on short utterances (Gnani's docs say so).
* `transliterate` (off by default) has no ground truth, so only language-independent checks apply; Gnani notes its accuracy is unmeasured.

## Known limitations (say these in your write-up; judges respect it)
* Scripts are short, formulaic BFSI/support calls, not open conversation. Have a native speaker review hi/ta/te/hinglish texts.
* The noise model is synthetic (babble from other TTS/human clips; white noise). Real call-centre noise differs.
* `verbatim` writes English words in native script, so WER for code-mixed scripts under `verbatim` is inflated by script choice; compare formats on entity metrics.
* Whole-signal SNR (silence included). Different from active-speech SNR.
* Small n: with 4 scripts per group, per-group differences are anecdotal. Use the bootstrap CIs, report n.
* Realtime (WebSocket) streaming is not covered. Gnani's quick-start and Prisma v3 page disagree on header names (`model` vs `x-model`), so I left it out rather than guess.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `GNANI_API_KEY is not set` | Step 3. The file must be named `.env` in the project root. |
| TTS 400 mentioning `audio_config`/`sample_rate` | In `config.yaml` set `tts.audio_config.sample_rate` to 44100 or 48000 (docs examples use those). Audio is resampled to 16 kHz locally anyway. |
| TTS 400 listing supported voices | Use a Timbre **v3.0** voice (Shivani, Lakshmi, Kalpana, Chetana, Vasudha, Riyaa, Tarika, Avinash, Shubham, Prakash, Devansh, Yashraj, Harshad). |
| STT 422 about `language_code` or `format` | Check `stt_configs` in `config.yaml` against https://docs.gnani.ai/api/STT/models/prisma-v3.md. |
| STT 400 `INVALID_CONTEXT` | A script's `keyterms` broke a limit (<=200 items). |
| 429 / rate limit | Lower `api.qps` and `api.workers` in `config.yaml`. |
| Clip longer than 30 s warning | Shorten the script text. |
| `no such table` / odd results after editing scripts | Scripts reload on every command; delete `data/kasauti.db` only if you want a full restart (it also forgets cached runs). |

## Project layout
```
config.yaml            all knobs (voices, conditions, STT configs, profiles, sweep mode)
data/scripts.json      40 scripts with entities and keyterms
kasauti/gnani.py       API client (retries, throttling)     kasauti/mock.py   offline simulator
kasauti/degrade.py     telephony + noise lab                kasauti/textnorm.py  normalisation, WER, entity checks
kasauti/pipeline.py    generate/degrade/transcribe/score    kasauti/recommend.py  paired bootstrap comparison
kasauti/report.py      CSV + markdown reports               dashboard/app.py  Streamlit dashboard
tests/                 17 unit + end-to-end (mock) tests
```
