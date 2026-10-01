from fixel.hotkey import DoubleTapDetector


def tap(detector, t, hold=0.05):
    detector.option_down(t)
    return detector.option_up(t + hold)


def test_double_tap_triggers():
    d = DoubleTapDetector(window=0.4)
    assert tap(d, 0.0) is False
    assert tap(d, 0.2) is True


def test_slow_taps_do_not_trigger_but_start_a_new_pair():
    d = DoubleTapDetector(window=0.4)
    tap(d, 0.0)
    assert tap(d, 0.6) is False
    assert tap(d, 0.8) is True


def test_option_chord_is_not_a_tap():
    d = DoubleTapDetector()
    d.option_down(0.0)
    d.other_key(0.05)  # e.g. ⌥→ to jump a word
    assert d.option_up(0.1) is False
    assert tap(d, 0.2) is False  # the chord didn't count as a first tap


def test_other_key_between_taps_cancels():
    d = DoubleTapDetector()
    tap(d, 0.0)
    d.other_key(0.1)
    assert tap(d, 0.2) is False


def test_triple_tap_triggers_once():
    d = DoubleTapDetector()
    assert [tap(d, t) for t in (0.0, 0.15, 0.3)] == [False, True, False]


def test_release_without_press_is_ignored():
    assert DoubleTapDetector().option_up(1.0) is False
