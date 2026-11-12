# Kasauti – Stress-Testing Indic Voice AI

### Problem
Voice AI systems are increasingly used in banking, customer support, and other enterprise applications. However, transcription errors involving names, phone numbers, OTPs, and financial amounts can lead to misunderstandings and operational risks. Performance may also vary across Indian languages, accents, and noisy audio conditions.

### Solution
Kasauti is an Indic Voice AI stress-testing platform that evaluates speech recognition performance across multiple Indian languages and challenging audio conditions. It helps developers identify transcription weaknesses and understand where critical information is being misrecognized.

### How It Works
- Uses **Gnani AI Timbre v3.0** for text-to-speech generation.
- Uses **Gnani AI Prisma v3.0** for speech-to-text transcription.
- Evaluates English, Hindi, Hinglish, Tamil, and Telugu samples.
- Applies audio degradation, including telephone-channel effects and background noise.
- Measures performance using Word Error Rate (WER), Character Error Rate (CER), and entity recall.
- Presents results through an interactive Streamlit dashboard.

### Preliminary Evaluation
Kasauti was evaluated using 20 self-recorded human audio samples across five language categories. The overall average WER was **25.69%**, and average CER was **18.12%**.

These are preliminary results from a small test set, not a representative benchmark. The Hindi and Telugu recordings used transliterated scripts and were not validated by native speakers.

### Impact
Kasauti aims to help AI developers and enterprise teams identify speech recognition failures before deploying voice AI systems in real-world environments, with particular attention to preserving critical information.

### Technology Stack
Python, Streamlit, SQLite, Pandas, Pytest, Gnani AI Timbre v3.0, and Gnani AI Prisma v3.0.

**GitHub:** https://github.com/HemaRamachandran28/Kasauti
