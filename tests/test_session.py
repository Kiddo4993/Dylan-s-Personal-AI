from fixel.parse import Header
from fixel.session import MAX_TRAY, Session


def shot(tmp_path, name="a", data=b"png"):
    path = tmp_path / f"{name}.png"
    path.write_bytes(data)
    return path


def answer(session, mode="error", key="k"):
    session.record_answer(Header(mode, key), f"MODE: {mode}\nKEY: {key}\n---\nbody", "body")


def test_first_question_uses_tray_and_default_prompt(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path, "a", b"A"))
    s.add_shot(shot(tmp_path, "b", b"B"))
    turn = s.build_user_turn("")
    assert turn.text == "Figure this out." and turn.images == [b"A", b"B"]
    assert s.tray == [] and s.case.question == "Figure this out."


def test_new_shot_after_answer_starts_new_case(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path))
    s.build_user_turn("why?")
    answer(s)
    first = s.case
    s.add_shot(shot(tmp_path, "c"))
    s.build_user_turn("")
    assert s.case is not first and len(s.case.turns) == 1


def test_follow_up_shot_stays_in_case(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path))
    s.build_user_turn("why?")
    answer(s)
    first = s.case
    s.add_shot(shot(tmp_path, "c"))
    s.follow_up = True
    s.build_user_turn("and this?")
    assert s.case is first and len(first.turns) == 3 and len(first.shots) == 2
    assert s.follow_up is False


def test_text_only_is_a_follow_up(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path))
    s.build_user_turn("why?")
    answer(s)
    first = s.case
    s.build_user_turn("explain more")
    assert s.case is first and first.turns[-1].text == "explain more"


def test_tray_limit(tmp_path):
    s = Session()
    assert all(s.add_shot(shot(tmp_path, str(i))) for i in range(MAX_TRAY))
    assert s.add_shot(shot(tmp_path, "x")) is False


def test_rollback_of_new_case_restores_everything(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path))
    s.build_user_turn("why?")
    answer(s)
    first = s.case
    pending = shot(tmp_path, "c")
    s.add_shot(pending)
    s.build_user_turn("new problem")
    s.rollback()
    assert s.case is first and len(first.turns) == 2 and s.tray == [pending]


def test_rollback_of_follow_up(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path))
    s.build_user_turn("why?")
    answer(s)
    s.build_user_turn("more")
    s.rollback()
    assert len(s.case.turns) == 2 and s.tray == []


def test_follow_up_header_keeps_original_key():
    s = Session()
    s.build_user_turn("q")
    answer(s, "error", "Boom")
    s.build_user_turn("more")
    s.record_answer(Header("error", ""), "raw", "b2")
    assert s.case.header == Header("error", "Boom") and s.case.answer == "b2"


def test_new_case_clears(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path))
    s.follow_up = True
    s.new_case()
    assert s.tray == [] and s.follow_up is False and s.case.turns == []


def test_retract_and_restore_answer():
    s = Session()
    s.build_user_turn("q")
    answer(s, "error", "Boom")
    assert s.retract_answer() is True
    assert [t.role for t in s.case.turns] == ["user"]
    s.restore_answer()
    assert [t.role for t in s.case.turns] == ["user", "assistant"] and s.case.answer == "body"


def test_retract_needs_an_answer():
    s = Session()
    assert s.retract_answer() is False
    s.build_user_turn("q")
    assert s.retract_answer() is False


def test_new_answer_after_retract_replaces_old_one():
    s = Session()
    s.build_user_turn("q")
    answer(s)
    s.retract_answer()
    s.record_answer(Header("error", ""), "raw2", "deeper body")
    s.restore_answer()  # no-op once a new answer is recorded
    assert len(s.case.turns) == 2 and s.case.answer == "deeper body"
