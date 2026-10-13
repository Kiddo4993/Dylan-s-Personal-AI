from fixel.playground.attachment import OUTPUT_TAIL, CodeAttachment


def test_unrun_code_is_reviewed():
    att = CodeAttachment("python", "print(1)\n")
    assert not att.failed and att.default_question() == "Review this code."
    assert att.to_prompt_text() == "[Code from Fixel playground · python]\n```python\nprint(1)\n```"


def test_failed_run_includes_output_and_asks_why():
    att = CodeAttachment("java", "class A {}", output="error: boom\n", exit_code=1, ran=True)
    assert att.failed and att.default_question() == "Why doesn't this work?"
    assert att.to_prompt_text().endswith("[Run output · exit 1]\nerror: boom")


def test_timeout_counts_as_failed():
    att = CodeAttachment("python", "while True: pass", output="[stopped after 10s]", exit_code=None, ran=True)
    assert att.failed and "[Run output · timed out]" in att.to_prompt_text()


def test_empty_output_and_long_output_tail():
    assert "(no output)" in CodeAttachment("python", "", ran=True, exit_code=0).to_prompt_text()
    long = CodeAttachment("python", "", output="a" * 10 + "b" * OUTPUT_TAIL, ran=True, exit_code=0)
    text = long.to_prompt_text()
    assert text.endswith("…" + "b" * OUTPUT_TAIL) and "a" not in text.split("]")[-1]
