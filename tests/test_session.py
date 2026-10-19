from fixel.parse import Header
from fixel.playground.attachment import CodeAttachment
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


def test_screen_text_follows_shots_into_the_case(tmp_path):
    s = Session()
    a = shot(tmp_path, "a")
    s.add_shot(a)
    s.set_shot_text(a, "Error one")
    s.add_shot(shot(tmp_path, "b"), "Error two")
    assert s.tray_text() == "Error one\nError two"
    s.build_user_turn("why?")
    assert s.case.screen_text == "Error one\nError two"


def test_memory_context_goes_to_the_model_not_the_question(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path))
    turn = s.build_user_turn("why?", context="[Fixel memory]\npast stuff\n[End of Fixel memory]")
    assert turn.text.startswith("[Fixel memory]") and turn.text.endswith("why?")
    assert s.case.question == "why?"


def test_starts_new_case(tmp_path):
    s = Session()
    assert s.starts_new_case() is True
    s.add_shot(shot(tmp_path))
    s.build_user_turn("q")
    answer(s)
    assert s.starts_new_case() is False  # typed follow-up
    s.add_shot(shot(tmp_path, "c"))
    assert s.starts_new_case() is True
    s.follow_up = True
    assert s.starts_new_case() is False


def test_rollback_restores_screen_text(tmp_path):
    s = Session()
    s.add_shot(shot(tmp_path), "Boom")
    s.build_user_turn("q")
    s.rollback()
    assert s.case.screen_text == "" and s.tray_text() == "Boom"


FAILED = CodeAttachment("python", "print(x)", output="NameError: x", exit_code=1, ran=True)


def test_code_attachment_is_sent_with_default_question():
    s = Session()
    s.attach_code(FAILED)
    assert s.starts_new_case()
    turn = s.build_user_turn("")
    assert turn.text.startswith("[Code from Fixel playground · python]")
    assert turn.text.endswith("NameError: x\n\nWhy doesn't this work?")
    assert s.code is None and s.case.question == "Why doesn't this work?"
    assert "NameError: x" in s.case.screen_text and "print(x)" in s.case.screen_text


def test_code_attachment_with_memory_and_typed_question():
    s = Session()
    s.attach_code(CodeAttachment("java", "class A {}"))
    turn = s.build_user_turn("is this ok?", context="[Fixel memory]")
    assert turn.text.startswith("[Fixel memory]\n\n[Code from Fixel playground · java]")
    assert turn.text.endswith("```\n\nis this ok?")


def test_code_after_an_answer_starts_a_new_case_and_rollback_restores_it():
    s = Session()
    s.build_user_turn("hi")
    answer(s)
    first = s.case
    s.attach_code(FAILED)
    assert s.starts_new_case()
    s.build_user_turn("")
    assert s.case is not first
    s.rollback()
    assert s.case is first and s.code == FAILED


def test_tray_text_includes_attached_code_and_new_case_clears_it(tmp_path):
    s = Session()
    s.attach_code(FAILED)
    assert "print(x)" in s.tray_text() and "NameError" in s.tray_text()
    s.new_case()
    assert s.code is None and s.tray_text() == ""


def test_rollback_keeps_code_and_shots_that_arrived_while_answering(tmp_path):
    s = Session()
    s.attach_code(FAILED)
    s.build_user_turn("")
    newer = CodeAttachment("java", "class B {}")
    s.attach_code(newer)  # "Ask Fixel" clicked in the browser while the answer streamed
    later = shot(tmp_path, "later")
    s.add_shot(later)  # ⌥⌥ while the answer streamed
    s.rollback()
    assert s.code == newer and s.tray == [later]


def test_rollback_restores_the_sent_code_when_nothing_newer_arrived():
    s = Session()
    s.attach_code(FAILED)
    s.build_user_turn("")
    s.rollback()
    assert s.code == FAILED
