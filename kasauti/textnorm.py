"""Script-insensitive-ish text normalisation + WER/CER + entity matching.

Why this exists: Timbre reads "₹12,500" aloud, and Prisma may answer "₹12,500", "12500",
or words, depending on `format`. Digits read one-by-one ("9 8 4 0 ...") come back as one token
("9840...") or as digit words. We normalise both sides so we score recognition, not formatting.
"""
from __future__ import annotations

import re
import unicodedata

_NATIVE = {}
for _base in (0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66):
    for _i in range(10):
        _NATIVE[_base + _i] = ord("0") + _i

_WORDS = {
    # English
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    # Hindi (Devanagari)
    "शून्य": "0", "जीरो": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4",
    "पाँच": "5", "पांच": "5", "छह": "6", "छः": "6", "छे": "6", "सात": "7", "आठ": "8", "नौ": "9",
    # Hindi (romanised)
    "shunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5", "chhe": "6", "chhah": "6", "che": "6", "chah": "6",
    "saat": "7", "aath": "8", "nau": "9",
    # Tamil
    "பூஜ்யம்": "0", "ஜீரோ": "0", "ஒன்று": "1", "ஒண்ணு": "1", "இரண்டு": "2", "மூன்று": "3",
    "நான்கு": "4", "ஐந்து": "5", "ஆறு": "6", "ஏழு": "7", "எட்டு": "8", "ஒன்பது": "9",
    # Telugu
    "సున్న": "0", "సున్నా": "0", "ఒకటి": "1", "రెండు": "2", "మూడు": "3", "నాలుగు": "4",
    "ఐదు": "5", "ఆరు": "6", "ఏడు": "7", "ఎనిమిది": "8", "తొమ్మిది": "9",
}


def _tok_digit(tok: str):
    if tok in _WORDS:
        return _WORDS[tok]
    if len(tok) == 1 and tok in "0123456789":
        return tok
    return None


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").lower().translate(_NATIVE)
    t = re.sub(r"(?<=\d)[,\u060c](?=\d)", "", t)
    out = []
    for ch in t:
        cat = unicodedata.category(ch)
        if cat == "Cf":            # zero-width joiners etc.
            continue
        out.append(ch if (cat[0] in "LMN" or ch.isspace()) else " ")
    toks = "".join(out).split()
    res, i = [], 0
    while i < len(toks):
        j, digs = i, []
        while j < len(toks) and _tok_digit(toks[j]) is not None:
            digs.append(_tok_digit(toks[j]))
            j += 1
        if len(digs) >= 3:         # digit-by-digit reading (phone, OTP, PIN, account)
            res.append("".join(digs))
            i = j
        else:
            res.append(toks[i])
            i += 1
    return " ".join(res)


def tokens(text: str) -> list[str]:
    return normalise(text).split()


def edit_distance(a, b) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r, h = tokens(ref), tokens(hyp)
    if not r:
        return 0.0 if not h else 1.0
    return edit_distance(r, h) / len(r)


def cer(ref: str, hyp: str) -> float:
    r, h = "".join(tokens(ref)), "".join(tokens(hyp))
    if not r:
        return 0.0 if not h else 1.0
    return edit_distance(r, h) / len(r)


def _similarity(a: str, b: str) -> float:
    m = max(len(a), len(b))
    return 1.0 if m == 0 else 1 - edit_distance(a, b) / m


def numeric_candidates(hyp_tokens: list[str]) -> list[str]:
    nums = [t for t in hyp_tokens if t.isdigit()]
    cands = list(nums)
    for k in (2, 3):  # model may split "98401 23456"
        for i in range(len(hyp_tokens) - k + 1):
            window = hyp_tokens[i:i + k]
            if all(w.isdigit() for w in window):
                cands.append("".join(window))
    return cands


def check_digits(value: str, hyp: str) -> tuple[float, float]:
    """Return (exact 0/1, character-level similarity of best candidate)."""
    cands = numeric_candidates(tokens(hyp))
    if value in cands:
        return 1.0, 1.0
    close = [c for c in cands if abs(len(c) - len(value)) <= 3]
    return 0.0, max((_similarity(value, c) for c in close), default=0.0)


def check_amount(value: str, hyp: str) -> float:
    return 1.0 if value in numeric_candidates(tokens(hyp)) else 0.0


def check_name(value: str, hyp: str, threshold: float = 0.75) -> float:
    n = tokens(value)
    h = tokens(hyp)
    if not n or not h:
        return 0.0
    target = " ".join(n)
    best = 0.0
    for k in {max(1, len(n) - 1), len(n), len(n) + 1}:
        for i in range(0, max(1, len(h) - k + 1)):
            best = max(best, _similarity(target, " ".join(h[i:i + k])))
    return 1.0 if best >= threshold else 0.0
