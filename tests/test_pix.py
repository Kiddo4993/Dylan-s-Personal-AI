from rich.cells import cell_len

from fixel import pix


def times(until=8.0, step=0.05):
    return [i * step for i in range(int(until / step))]


def test_every_thinking_frame_is_the_same_width():
    assert {cell_len(pix.mini_frame(t)) for t in times()} == {7}


def test_pix_blinks_zooms_and_glances():
    frames = {pix.mini_frame(t) for t in times()}
    assert " ⌜-‿-⌝ " in frames  # blink
    assert "⌜ •‿• ⌝" in frames  # corners zoom out
    assert "⌜•‿•  ⌝" in frames and "⌜  •‿•⌝" in frames  # glances left and right
    assert pix.mini_frame(0) == " ⌜•‿•⌝ "


def test_the_status_says_what_fixel_is_doing():
    assert pix.verb(images=True, deep=False) == "Reading your screenshot"
    assert pix.verb(images=False, deep=False) == "Thinking"
    assert pix.verb(images=True, deep=True) == pix.verb(images=False, deep=True) == "Thinking hard"


def test_big_face_rows_line_up():
    for spread in range(4):
        rows = pix.big_face(spread=spread)
        assert len(rows) == 4 and len({cell_len(row) for row in rows}) == 1
    assert cell_len(pix.big_face(spread=3)[0]) > cell_len(pix.big_face()[0])
    assert "●   ●" in pix.big_face()[1]


def test_startup_moment_focuses_then_opens_eyes():
    frames = pix.startup_frames()
    assert frames[0] != frames[-1] and frames[-1] == pix.big_face()
    assert cell_len(frames[0][0]) > cell_len(frames[-1][0])  # starts zoomed out
    assert "●" not in frames[0][1]  # eyes closed at first
    assert len(frames) <= 12  # under a second at ~12 fps


def test_reaction_faces_are_one_cell_per_character():
    for face in (pix.HAPPY, pix.SAD, pix.mini_frame(0).strip()):
        assert cell_len(face) == len(face)
