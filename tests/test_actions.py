from datetime import datetime

from fixel import actions


def test_slugify():
    assert actions.slugify("Why won't THIS build?!") == "why-won-t-this-build"
    assert actions.slugify("???") == "note"


def test_save_note_writes_markdown_and_copies_shots(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    notes = tmp_path / "notes"
    path = actions.save_note(
        notes, question="Fix numpy", answer="pip install numpy", mode="error",
        shots=[shot, tmp_path / "deleted.png"], when=datetime(2026, 9, 30, 14, 5),
    )
    assert path.name == "2026-09-30-fix-numpy.md"
    text = path.read_text()
    assert "# Fix numpy" in text and "pip install numpy" in text
    assert "](attachments/2026-09-30-fix-numpy-1.png)" in text
    assert (notes / "attachments" / "2026-09-30-fix-numpy-1.png").read_bytes() == b"png"


def test_save_note_never_overwrites(tmp_path):
    kwargs = dict(question="Same", answer="a", mode="doc", shots=[], when=datetime(2026, 9, 30))
    first = actions.save_note(tmp_path, **kwargs)
    second = actions.save_note(tmp_path, **kwargs)
    assert first != second and second.name == "2026-09-30-same-2.md"


async def test_run_command_captures_output(tmp_path):
    code, out = await actions.run_command("echo hi; echo err >&2", cwd=tmp_path)
    assert code == 0 and "hi" in out and "err" in out


async def test_run_command_times_out(tmp_path):
    code, out = await actions.run_command("sleep 5", timeout=0.2, cwd=tmp_path)
    assert code is None and "stopped after" in out
