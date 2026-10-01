from pathlib import Path

import pytest

import fixel.capture as capture


async def test_cancelled_capture_returns_none(tmp_path, monkeypatch):
    calls = []

    async def fake_run(*args):
        calls.append(args)
        return 1

    monkeypatch.setattr(capture, "_run", fake_run)
    assert await capture.capture_region(tmp_path / "s.png") is None
    assert calls[0][:3] == ("screencapture", "-i", "-x")


async def test_small_capture_is_returned_as_is(tmp_path, monkeypatch, png):
    data = png(800, 600)

    async def fake_run(*args):
        assert args[0] == "screencapture", "small shots must not be resized"
        Path(args[-1]).write_bytes(data)
        return 0

    monkeypatch.setattr(capture, "_run", fake_run)
    assert await capture.capture_region(tmp_path / "s.png") == data


async def test_large_capture_is_downscaled(tmp_path, monkeypatch, png):
    calls = []

    async def fake_run(*args):
        calls.append(args)
        size = (3024, 1964) if args[0] == "screencapture" else (1568, 1018)
        Path(args[-1]).write_bytes(png(*size))
        return 0

    monkeypatch.setattr(capture, "_run", fake_run)
    data = await capture.capture_region(tmp_path / "s.png")
    assert capture.png_size(data) == (1568, 1018)
    assert calls[1][:3] == ("sips", "-Z", "1568")


def test_png_size_rejects_non_png():
    with pytest.raises(ValueError):
        capture.png_size(b"GIF89a" + b"\x00" * 30)
