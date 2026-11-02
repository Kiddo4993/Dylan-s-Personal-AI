"""Draw docs/images/demo.gif from Fixel's real rendering code: `.venv/bin/pip install pillow && .venv/bin/python scripts/demo_gif.py`.

Each frame is what Fixel's UI prints (rich renders it to styled text), painted with Menlo into a Terminal-like
window. Nothing is mocked up by hand, so the GIF shows exactly what the app looks like.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console, Group
from rich.terminal_theme import MONOKAI
from rich.text import Text

from fixel.parse import split_header
from fixel.ui import UI, Thinking, toolbar_text, Status

OUT = Path(__file__).parents[1] / "docs" / "images" / "demo.gif"
COLS, ROWS = 92, 21
FONT_SIZE, PAD, BAR = 15, 18, 30
FONT = "/System/Library/Fonts/Menlo.ttc"
FALLBACK = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"  # Menlo has no ‿, which Pix smiles with

ANSWER = """MODE: error
KEY: ModuleNotFoundError: pandas
---
**Cause:** `pandas` isn't installed in the Python that ran `app.py`.

**Fix:**
```bash
python3 -m pip install pandas
```

Run it with the same `python3` you used for `app.py`, so it installs into the right environment.
"""


class Painter:
    def __init__(self) -> None:
        self.regular = ImageFont.truetype(FONT, FONT_SIZE, index=0)
        self.bold = ImageFont.truetype(FONT, FONT_SIZE, index=1)
        self.fallback = ImageFont.truetype(FALLBACK, FONT_SIZE)
        self._tofu = self._glyph(self.regular, "\ue000")
        self._has: dict[str, bool] = {}
        self.cw, self.ch = self.regular.getlength("M"), round(FONT_SIZE * 1.45)
        self.width = round(PAD * 2 + self.cw * COLS)
        self.height = PAD * 2 + BAR + self.ch * ROWS
        self.bg = MONOKAI.background_color
        self.fg = MONOKAI.foreground_color

    @staticmethod
    def _glyph(font, ch: str) -> bytes:
        image = Image.new("L", (FONT_SIZE * 2, FONT_SIZE * 2))
        ImageDraw.Draw(image).text((2, 2), ch, font=font, fill=255)
        return image.tobytes()

    def _in_menlo(self, ch: str) -> bool:
        if ch not in self._has:
            self._has[ch] = ch.isascii() or self._glyph(self.regular, ch) != self._tofu
        return self._has[ch]

    def _text(self, draw, x: float, y: int, text: str, font, fill) -> None:
        if all(self._in_menlo(ch) for ch in text):
            draw.text((x, y), text, font=font, fill=fill)
            return
        for i, ch in enumerate(text):  # one cell per character, missing glyphs from the fallback font
            face = font if self._in_menlo(ch) else self.fallback
            offset = (self.cw - face.getlength(ch)) / 2
            draw.text((x + i * self.cw + offset, y), ch, font=face, fill=fill)

    def _rgb(self, color, default):
        return tuple(color.get_truecolor(MONOKAI, foreground=True)) if color is not None else tuple(default)

    def frame(self, renderable, toolbar: str = "") -> Image.Image:
        console = Console(width=COLS, force_terminal=True, color_system="truecolor", record=False)
        lines = console.render_lines(renderable, console.options, pad=False)[: ROWS - 1]
        img = Image.new("RGB", (self.width, self.height), (40, 41, 35))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((0, 0, self.width - 1, self.height - 1), radius=10, fill=tuple(self.bg))
        draw.rectangle((0, BAR - 1, self.width, BAR), fill=(60, 61, 55))
        for i, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            draw.ellipse((14 + i * 20, 9, 26 + i * 20, 21), fill=color)
        title = "Fixel"
        draw.text(((self.width - self.regular.getlength(title)) / 2, 7), title, font=self.regular, fill=(200, 200, 195))
        for row, line in enumerate(lines):
            self._line(draw, line, PAD + BAR + row * self.ch)
        if toolbar:  # prompt_toolkit's bottom toolbar: reversed, on the last row
            y = PAD + BAR + (ROWS - 1) * self.ch
            draw.rectangle((PAD - 4, y - 2, self.width - PAD + 4, y + self.ch - 4), fill=(220, 220, 214))
            self._text(draw, PAD, y, toolbar[:COLS], self.regular, tuple(self.bg))
        return img

    def _line(self, draw, segments, y: int) -> None:
        x = PAD
        for segment in segments:
            if not segment.text:
                continue
            style = segment.style
            fg = self._rgb(style.color if style else None, self.fg)
            bg = style.bgcolor if style and style.bgcolor else None
            if style and style.dim:  # dim: halfway to whatever is behind the text
                behind = self._rgb(bg, self.bg) if bg is not None else tuple(self.bg)
                fg = tuple((a + b) // 2 for a, b in zip(fg, behind))
            width = self.cw * len(segment.text)
            if bg is not None:
                draw.rectangle((x, y - 2, x + width, y + self.ch - 4), fill=self._rgb(bg, self.bg))
            font = self.bold if style and style.bold else self.regular
            self._text(draw, x, y, segment.text, font, fg)
            x += width


def prompt(typed: str, cursor: bool = True) -> Text:
    line = Text("› ", style="bold cyan")
    line.append(typed)
    if cursor:
        line.append("▏", style="bold")
    return line


def frames(painter: Painter):
    """(image, milliseconds) pairs: type the question, Pix thinks, the answer streams in, then hold."""
    ui = UI(Console(), animations=True)
    tray = toolbar_text(Status(tray=1))
    question = "why won't this run?"
    yield painter.frame(prompt("", cursor=True), tray), 900
    for n in range(1, len(question) + 1, 2):
        yield painter.frame(prompt(question[:n]), tray), 70
    yield painter.frame(prompt(question), tray), 500
    asked = prompt(question, cursor=False)
    for tenth in range(0, 26, 2):  # 2.6 s of Pix's thinking loop, sampled
        thinking = Thinking(images=True)
        thinking.started -= tenth / 10
        yield painter.frame(Group(asked, thinking)), 200
    header, body = split_header(ANSWER, final=True)
    words = body.split(" ")
    for n in range(4, len(words) + 4, 4):  # the answer arrives a few words at a time, like a real stream
        yield painter.frame(Group(asked, ui.answer_view(header, " ".join(words[:n])))), 90
    done_console = Console(file=io.StringIO(), width=COLS, force_terminal=True, color_system="truecolor", record=True)
    done_ui = UI(done_console, animations=False)
    done_console.print(asked)
    done_console.print(done_ui.answer_view(header, body))
    done_ui.answer_footer("claude-sonnet-5-5", "claude-sonnet-5-5", 3.2, False)
    done_ui.action_bar()
    final = Text.from_ansi(done_console.export_text(styles=True))
    yield painter.frame(Group(final, prompt("")), toolbar_text(Status())), 4000


def main() -> None:
    painter = Painter()
    images, durations = zip(*frames(painter))
    palette = images[-1].quantize(colors=64, method=Image.Quantize.MEDIANCUT)  # the final frame has every colour used
    quantized = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    quantized[0].save(OUT, save_all=True, append_images=quantized[1:], duration=list(durations), loop=0, optimize=True, disposal=1)
    print(f"wrote {OUT.relative_to(Path.cwd()) if OUT.is_relative_to(Path.cwd()) else OUT} ({OUT.stat().st_size // 1024} KB, {len(images)} frames)")


if __name__ == "__main__":
    main()
