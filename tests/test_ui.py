from fixel.brain.base import Turn
from fixel.brain.fake import FakeProvider
from fixel.parse import Header
from fixel.ui import UI, Status, toolbar_text


def test_toolbar_idle_and_tray():
    assert toolbar_text(Status()).startswith("⌥⌥ screenshot")
    assert "2 shots in tray" in toolbar_text(Status(tray=2))
    assert "follow-up: on" in toolbar_text(Status(tray=1, follow_up=True))
    assert "hotkey off" in toolbar_text(Status(hotkey_ok=False))


def test_toolbar_flash_expires():
    status = Status()
    status.flash_msg("Tray full", seconds=10)
    assert toolbar_text(status) == "Tray full"
    status.flash_until = 0
    assert toolbar_text(status) != "Tray full"


async def test_stream_answer_parses_and_renders(console):
    ui = UI(console)
    provider = FakeProvider(["MODE: error\nKEY: Boom\n---\n**Cause:** gremlins"], chunk=4)
    header, raw, body = await ui.stream_answer(provider.stream([Turn("user", "q")], "s"))
    assert header == Header("error", "Boom")
    assert body == "**Cause:** gremlins" and raw.startswith("MODE:")
    out = console.file.getvalue()
    assert "ERROR" in out and "gremlins" in out and "MODE:" not in out
