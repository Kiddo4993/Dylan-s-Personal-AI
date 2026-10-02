from pathlib import Path

from fixel.ocr import recognize_text, recognize_text_async

FIXTURE = Path(__file__).parent / "fixtures" / "pandas-error.png"


def test_reads_text_from_a_screenshot():
    text = recognize_text(FIXTURE)
    assert "ModuleNotFoundError: No module named 'pandas'" in text
    assert "import pandas as pd" in text


def test_unreadable_file_gives_empty_text(tmp_path):
    bogus = tmp_path / "not-an-image.png"
    bogus.write_bytes(b"nope")
    assert recognize_text(bogus) == ""
    assert recognize_text(tmp_path / "missing.png") == ""


async def test_async_wrapper():
    assert "pandas" in await recognize_text_async(FIXTURE)
