"""Shared helper: record a real ember session in a pseudo-terminal and save it as an SVG.

Used by screenshot.py (a session with commands, in a window frame) and cover.py (the start
screen, frameless). The images are always the actual rendered terminal, never a mock-up.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pexpect
import pyte
from rich.console import CONSOLE_SVG_FORMAT, Console
from rich.style import Style
from rich.terminal_theme import TerminalTheme
from rich.text import Text

ROOT = Path(__file__).resolve().parent.parent

# ember's "void" theme, so the image matches what you see in the terminal
THEME = TerminalTheme(
    (18, 19, 22),
    (231, 231, 231),
    [(0, 0, 0), (255, 107, 107), (126, 226, 168), (242, 193, 78), (124, 196, 255), (201, 160, 255), (134, 199, 192), (231, 231, 231)],
    [(85, 85, 85), (255, 107, 107), (126, 226, 168), (242, 193, 78), (124, 196, 255), (201, 160, 255), (134, 199, 192), (255, 255, 255)],
)

# Rich's SVG template without the mac-window chrome, cropped to the terminal itself.
FRAMELESS_SVG_FORMAT = (
    CONSOLE_SVG_FORMAT.replace(
        '<svg class="rich-terminal" viewBox="0 0 {width} {height}"',
        '<svg class="rich-terminal" viewBox="0 0 {terminal_width} {terminal_height}"',
    )
    .replace("{chrome}", '<rect fill="#121316" x="0" y="0" width="{terminal_width}" height="{terminal_height}"/>')
    .replace("<g transform=\"translate({terminal_x}, {terminal_y})\"", '<g transform="translate(0, 0)"')
)

_NAMED = {"black", "red", "green", "brown", "blue", "magenta", "cyan", "white"}


def _color(value: str) -> str | None:
    if value == "default":
        return None
    if value in _NAMED:
        return {"brown": "yellow"}.get(value, value)
    return f"#{value}" if len(value) == 6 else None


def capture(steps: list[tuple[str, float]], cols: int, rows: int, args: str = "", cwd: Path | None = None,
            settle: float = 2.5) -> pyte.Screen:
    """Run ember in a pty, send `steps` (keys, seconds to wait) and return the rendered screen."""
    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)
    with tempfile.TemporaryDirectory() as home:
        env = dict(
            os.environ, TERM="xterm-256color", COLORTERM="truecolor", PROMPT_TOOLKIT_NO_CPR="1",
            XDG_CONFIG_HOME=f"{home}/config", XDG_DATA_HOME=f"{home}/data",
        )
        child = pexpect.spawn(sys.executable, ["-m", "ember", *args.split()], env=env,
                              dimensions=(rows, cols), cwd=str(cwd or Path.home()))

        def pump(seconds: float) -> None:
            end = time.time() + seconds
            while time.time() < end:
                try:
                    stream.feed(child.read_nonblocking(65536, timeout=0.05))
                except (pexpect.TIMEOUT, pexpect.EOF):
                    pass

        pump(settle)
        for keys, wait in steps:
            child.send(keys)
            pump(wait)
        child.terminate(force=True)
    return screen


def to_text(screen: pyte.Screen, trim_blank_lines: bool = True) -> Text:
    rows = [screen.buffer[y] for y in range(screen.lines)]

    def has_content(row) -> bool:
        return any(row[x].data.strip() or row[x].bg != "default" for x in range(screen.columns))

    last = max((y for y, row in enumerate(rows) if has_content(row)), default=0) if trim_blank_lines else screen.lines - 1
    text = Text()
    for y in range(last + 1):
        row = rows[y]
        for x in range(screen.columns):
            cell = row[x]
            style = Style(color=_color(cell.fg), bgcolor=_color(cell.bg), bold=cell.bold,
                          italic=cell.italics, underline=cell.underscore)
            text.append(cell.data or " ", style=style)
        text.append("\n")
    return text


def save_svg(text: Text, target: Path, cols: int, title: str | None, frameless: bool = False) -> None:
    console = Console(record=True, width=cols, force_terminal=True, color_system="truecolor",
                      file=open(os.devnull, "w"))
    console.print(text, end="", overflow="crop", no_wrap=True)
    options = {"theme": THEME}
    if frameless:
        options["code_format"] = FRAMELESS_SVG_FORMAT
    console.save_svg(str(target), title=title or "", **options)
    print(f"wrote {target}")
