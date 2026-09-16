"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys

from ember import __version__
from ember.theme import PALETTES


def _config_theme() -> str | None:
    if theme := os.environ.get("EMBER_THEME"):
        return theme
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, "ember", "config.toml")
    try:
        import tomllib

        with open(path, "rb") as f:
            return tomllib.load(f).get("theme")
    except (ImportError, OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ember", description="A modern interactive Python shell.")
    parser.add_argument("file", nargs="?", help="python file to run")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed to the file")
    parser.add_argument("-c", dest="command", help="run a command")
    parser.add_argument("-i", action="store_true", help="stay interactive after running a file or command")
    parser.add_argument("--theme", choices=list(PALETTES), help="color theme")
    parser.add_argument("--version", action="version", version=f"ember {__version__}")
    opts = parser.parse_args(argv)

    from ember.shell import Shell

    shell = Shell(theme=opts.theme or _config_theme())

    try:
        if opts.command is not None:
            shell.run_cell(opts.command)
        if opts.file:
            import shlex

            shell.run_cell(f"%run {shlex.join([opts.file, *opts.args])}")
        if (opts.command is not None or opts.file) and not opts.i:
            return 0 if shell.last_ok else 1
        if not sys.stdin.isatty():
            shell.run_cell(sys.stdin.read())
            return 0 if shell.last_ok else 1
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0

    from ember.ui import Repl

    return Repl(shell).run()
