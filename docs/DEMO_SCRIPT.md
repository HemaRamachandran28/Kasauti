# 60-second demo script (screen recording + your voice)

Record the dashboard from REAL results (not mock). Keep it under 60 s. Captions on.

| Time | Screen | Say (adapt to your numbers) |
|---|---|---|
| 0-5 s | Title: "Kasauti: does your voice agent survive a real phone line?" | "Voice agents are demoed in quiet rooms and deployed on noisy phone lines. I built a touchstone for that." |
| 5-15 s | Terminal: `python -m kasauti run-all` scrolling, then script text in Tamil/Hindi | "Gnani Timbre generates test calls in Tamil, Hindi, Telugu, Hinglish and English. I degrade them to an 8 kHz phone line with noise." |
| 15-30 s | Failure explorer: one sentence, audio plays, diff turns red as you step clean -> tel -> tel+babble:10 | "Same sentence. Clean: perfect. Phone line plus background chatter: the account number breaks." |
| 30-45 s | Recommendations tab or config comparison | "Then I sweep Prisma v3.0 settings. <<keyterms / format>> recovered <<X>> points of entity recall on noisy telephony audio (95% CI <<..>>)." |
| 45-55 s | Human vs synthetic tab | "I also recorded real speakers: synthetic audio was <<optimistic/accurate>> by <<Y>> WER points." |
| 55-60 s | Repo/README + tags | "Built on Gnani Prisma and Timbre. Kasauti: measure before you ship." |

Rules: only claim numbers that are in YOUR reports. No mock data on screen (the red MOCK banner would show).
