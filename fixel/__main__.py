"""Entry point: `fixel`, `fixel --here`, `fixel setup`, `fixel ide [language]`, and the one-shot `shot`, `canvas`, `cases`."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixel", description="Double-tap Right Option, screenshot anything, get unstuck.")
    parser.add_argument(
        "command", nargs="?", choices=["setup", "ide", "shot", "canvas", "cases"],
        help="setup: keys and permissions · ide [language]: the terminal IDE · shot: drag-select a screenshot, print its path · "
        "canvas: your Canvas homework with AI plans · cases [words]: search your past fixes",
    )
    parser.add_argument("rest", nargs="*", help="ide: python, java, js or cpp · cases: words to search for")
    parser.add_argument("--json", action="store_true", help="canvas, cases: print JSON (for scripts and Claude Code)")
    parser.add_argument("--out", help="shot: where to save the PNG")
    parser.add_argument("--here", action="store_true", help="run in this terminal instead of opening a Terminal.app window")
    args = parser.parse_args(argv)

    from .config import load_config

    cfg = load_config()
    if args.command == "setup":
        from .setup import run_setup

        run_setup(cfg)
        return 0
    if args.command == "ide":
        from . import terminal
        from .playground.window import run_window

        terminal.set_title("Fixel IDE")
        return asyncio.run(run_window(cfg, args.rest[0] if args.rest else None))
    if args.command in ("shot", "canvas", "cases"):
        from . import cli

        if args.command == "shot":
            return asyncio.run(cli.shot(cfg, args.out))
        if args.command == "canvas":
            return asyncio.run(cli.canvas(cfg, args.json))
        return cli.cases(cfg, args.rest, args.json)

    from . import terminal

    if not args.here and os.environ.get("FIXEL_INSIDE") != "1":
        if terminal.open_in_terminal_app():
            print("Fixel opened in a new Terminal window.")
            return 0
        print("Couldn't open Terminal.app, so running here instead.")
    return asyncio.run(_run(cfg))


async def _run(cfg) -> int:
    from . import terminal
    from .app import FixelApp
    from .ui import UI

    terminal.set_title()
    window_id = terminal.front_window_id()
    await FixelApp(cfg, UI(), raise_window=lambda: terminal.raise_window(window_id)).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
