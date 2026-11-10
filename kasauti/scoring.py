"""Per-run scoring."""
from __future__ import annotations

import json

from kasauti import textnorm as tn


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def score_run(script: dict, hyp: str, fmt: str, detected: str | None) -> dict:
    """script: row with text, lang, entities_json. fmt: transcribe|verbatim|codemix|transliterate."""
    ents = json.loads(script.get("entities_json") or "[]")
    hyp = hyp or ""
    res = {"wer": None, "cer": None, "digit_exact": None, "digit_characc": None,
           "amount_exact": None, "name_match": None, "lang_match": None, "entity_recall": None}
    if fmt != "transliterate":  # no romanised ground truth exists
        res["wer"] = tn.wer(script["text"], hyp)
        res["cer"] = tn.cer(script["text"], hyp)
    digits = [e["value"] for e in ents if e["type"] == "digits"]
    amounts = [e["value"] for e in ents if e["type"] == "amount"]
    names = [e["value"] for e in ents if e["type"] == "name"]
    if digits and fmt != "transliterate":
        pairs = [tn.check_digits(d, hyp) for d in digits]
        res["digit_exact"] = _mean([p[0] for p in pairs])
        res["digit_characc"] = _mean([p[1] for p in pairs])
    if amounts and fmt == "transcribe":   # other formats write amounts as words: not fairly scorable
        res["amount_exact"] = _mean([tn.check_amount(a, hyp) for a in amounts])
    if names and fmt != "transliterate":
        res["name_match"] = _mean([tn.check_name(n, hyp) for n in names])
    if detected:
        res["lang_match"] = 1.0 if detected == script["lang"] else 0.0
    res["entity_recall"] = _mean([res["digit_exact"], res["amount_exact"], res["name_match"]])
    return res
