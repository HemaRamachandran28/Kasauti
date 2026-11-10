# Kasauti: written project explanation (fill every <<...>> from your own results)

**Problem.** Enterprises deploy voice agents on 8 kHz phone lines with noise, code-mixing and regional languages,
but evaluate them on clean audio. Developers have no cheap way to learn where their configuration breaks.

**Users.** Developers and QA teams building collections/support voice agents for Indian customers.

**Gnani technology used and why.**
* Timbre v3.0 (TTS): generates multilingual test calls (13 voices x 10 languages; optional audio tags such as whispers/shouting).
* Prisma v3.0 (STT): system under test: language hint vs `indic-auto`, output formats, keyterms.
* Evon: not used. <<If you did use it, say exactly how; if not, keep this line.>>

**Method.** 40 scripts (<<n used>>), <<k>> degradation conditions (telephony, babble/white noise at 20/10/5 dB), <<m>> STT configs,
<<h>> real human clips. Metrics: normalised WER/CER, exact recovery of digit strings/amounts/names, language-detection accuracy,
paired bootstrap CIs for config comparisons.

**Results.** <<tables/figures from reports/summary.md; quote n and CIs>>

**Synthetic vs human.** <<gap from human_gap.csv>>

**Limitations.** Short formulaic scripts; synthetic noise; whole-signal SNR; small n per group; native-speaker review of texts <<done/not done>>;
adaptive sweep bias (final claims from `mode: full` <<yes/no>>); realtime streaming not covered.

**Credits used.** <<STT calls, TTS calls, credits>>.

**Contribution.** Solo project by <<name>>.
