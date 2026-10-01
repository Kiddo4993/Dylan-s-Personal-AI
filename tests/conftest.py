import io
import struct

import pytest
from rich.console import Console


def _make_png(width: int, height: int) -> bytes:
    """Just enough of a PNG for size sniffing (signature + IHDR)."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


@pytest.fixture
def png():
    return _make_png


@pytest.fixture
def console():
    return Console(file=io.StringIO(), width=100, force_terminal=False, color_system=None)
