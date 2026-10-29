"""Pix, Fixel's mascot: a face made from its own screenshot-selection corners.

Everything here is plain functions of elapsed time, so the animation is easy to test.
Every glyph is one terminal cell wide, and frames of the same kind share one width,
so text next to Pix never jitters.
"""

from __future__ import annotations

HAPPY = "⌜^‿^⌝"
SAD = "⌜•⁀•⌝"

# What Fixel is actually doing, said once. Rotating cute verbs ("Connecting the dots…") say nothing.
SHOT_VERB = "Reading your screenshot"
TEXT_VERB = "Thinking"
DEEP_VERB = "Thinking hard"

# One 4-second loop: rest, blink, rest, zoom out and glance around, zoom back in.
_SNUG, _BLINK = " ⌜•‿•⌝ ", " ⌜-‿-⌝ "
_WIDE, _LEFT, _RIGHT = "⌜ •‿• ⌝", "⌜•‿•  ⌝", "⌜  •‿•⌝"
_LOOP = (
    (1.20, _SNUG),
    (1.35, _BLINK),
    (2.00, _SNUG),
    (2.20, _WIDE),
    (2.60, _LEFT),
    (3.00, _RIGHT),
    (3.20, _WIDE),
    (4.00, _SNUG),
)
_LOOP_SECONDS = _LOOP[-1][0]


def mini_frame(t: float) -> str:
    """Pix's 7-cell thinking face, `t` seconds into the wait."""
    moment = t % _LOOP_SECONDS
    for until, frame in _LOOP:
        if moment < until:
            return frame
    return _SNUG


def verb(*, images: bool, deep: bool) -> str:
    return DEEP_VERB if deep else SHOT_VERB if images else TEXT_VERB


def big_face(*, spread: int = 0, eyes: str = "●") -> list[str]:
    """Pix's homepage face. `spread` pushes the corners outward (zoomed out)."""
    pad = " " * spread
    return [
        f"⌜{' ' * (7 + 2 * spread)}⌝",
        f"{pad}  {eyes}   {eyes}  {pad}",
        f"{pad}    ‿    {pad}",
        f"⌞{' ' * (7 + 2 * spread)}⌟",
    ]


def startup_frames() -> list[list[str]]:
    """The once-per-launch moment: corners focus in, then Pix opens its eyes."""
    focusing = [big_face(spread=spread, eyes="─") for spread in (4, 3, 2, 1, 0, 0)]
    return [*focusing, big_face(eyes="─"), big_face()]
