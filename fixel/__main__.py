"""Entry point: `fixel`, `fixel --here`, `fixel setup`, `fixel ide [language]`."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixel", description="Double-tap Right Option, screenshot anything, get unstuck.")
    parser.add_argument("command", nargs="?", choices=["setup", "ide"], help="setup: save API keys and check permissions · ide: the terminal IDE (Fixel's /ide opens it in its own window)")
    parser.add_argument("lang", nargs="?", help="ide: python, java, js or cpp")
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
        return asyncio.run(run_window(cfg, args.lang))

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
