from kasauti import textnorm as tn


def test_digit_run_merging_and_native_digits():
    assert tn.normalise("मेरा नंबर 9 8 7 6 5 है") == "मेरा नंबर 98765 है"
    assert tn.normalise("नंबर ९८७६५") == "नंबर 98765"
    assert tn.normalise("one two three four") == "1234"
    assert tn.normalise("ek do teen char") == "1234"


def test_short_digit_words_left_alone():
    assert tn.normalise("दो तीन लोग") == "दो तीन लोग"      # 'a few people', not '23'


def test_amount_and_punctuation():
    assert tn.normalise("₹1,25,000 का भुगतान।") == "125000 का भुगतान"


def test_zwnj_is_dropped():
    assert tn.normalise("కార్డ్\u200cపై") == tn.normalise("కార్డ్పై")


def test_wer_cer():
    assert tn.wer("a b c d", "a b c d") == 0
    assert tn.wer("a b c d", "a x c") == 0.5
    assert tn.wer("", "") == 0 and tn.wer("", "x") == 1
    assert 0 < tn.cer("hello", "hallo") < 0.3


def test_digit_formats_do_not_inflate_wer():
    ref = "my number is 9 8 4 0 1 2"
    assert tn.wer(ref, "my number is 984012") == 0
    assert tn.wer(ref, "my number is nine eight four zero one two") == 0


def test_entities():
    assert tn.check_digits("984012", "number 984012 ok") == (1.0, 1.0)
    assert tn.check_digits("984012", "number 98401 2 ok")[0] == 1.0      # split by the model
    exact, sim = tn.check_digits("984012", "number 984013 ok")
    assert exact == 0.0 and sim > 0.8
    assert tn.check_amount("12500", "pay ₹12,500 now") == 1.0
    assert tn.check_amount("12500", "pay 12,600 now") == 0.0
    assert tn.check_name("Suresh Iyer", "mister suresh ayer here") == 1.0
    assert tn.check_name("Suresh Iyer", "mister rakesh here") == 0.0
