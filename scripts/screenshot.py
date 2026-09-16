"""Record a real ember session in a pseudo-terminal and save it as an SVG screenshot.

    python scripts/screenshot.py   # writes docs/assets/demo.svg

Needs the dev extras (pexpect, pyte). The image is the actual rendered terminal, not a mock-up.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pexpect
import pyte
from rich.console import Console
from rich.style import Style
from rich.terminal_theme import TerminalTheme
from rich.text import Text

ROOT = Path(__file__).resolve().parent.parent
COLS, ROWS = 96, 44

# (keys to send, seconds to wait afterwards)
SCRIPT = [
    ('def greet(name, times=1):\r', 0.4),
    ('return f"hi {name}! " * times\r', 0.4),
    ("\r", 0.8),
    ('greet("Arthur", times=2)\r', 0.8),
    ("%timeit -n 10000 greet('ember')\r", 2.5),
    ('greet("ember", ', 1.5),
]

THEME = TerminalTheme(
    (18, 19, 22),
    (231, 231, 231),
    [(0, 0, 0), (255, 107, 107), (126, 226, 168), (242, 193, 78), (124, 196, 255), (201, 160, 255), (134, 199, 192), (231, 231, 231)],
    [(85, 85, 85), (255, 107, 107), (126, 226, 168), (242, 193, 78), (124, 196, 255), (201, 160, 255), (134, 199, 192), (255, 255, 255)],
)
_NAMED = {"black", "red", "green", "brown", "blue", "magenta", "cyan", "white"}


def _color(value: str) -> str | None:
    if value == "default":
        return None
    if value in _NAMED:
        return {"brown": "yellow"}.get(value, value)
    return f"#{value}" if len(value) == 6 else None


def capture() -> pyte.Screen:
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)
    with tempfile.TemporaryDirectory() as home:
        env = dict(
            os.environ, TERM="xterm-256color", COLORTERM="truecolor", PROMPT_TOOLKIT_NO_CPR="1",
            XDG_CONFIG_HOME=f"{home}/config", XDG_DATA_HOME=f"{home}/data", VIRTUAL_ENV="",
        )
        child = pexpect.spawn(sys.executable, ["-m", "ember"], env=env, dimensions=(ROWS, COLS), cwd=str(Path.home()))

        def pump(seconds: float) -> None:
            end = time.time() + seconds
            while time.time() < end:
                try:
                    stream.feed(child.read_nonblocking(65536, timeout=0.05))
                except (pexpect.TIMEOUT, pexpect.EOF):
                    pass

        pump(2.5)
        for keys, wait in SCRIPT:
            child.send(keys)
            pump(wait)
        child.terminate(force=True)
    return screen


def to_text(screen: pyte.Screen) -> Text:
    lines = [screen.buffer[y] for y in range(screen.lines)]
    last = max((y for y, row in enumerate(lines) if any(row[x].data.strip() or row[x].bg != "default" for x in range(screen.columns))), default=0)
    text = Text()
    for y in range(last + 1):
        row = lines[y]
        for x in range(screen.columns):
            ch = row[x]
            style = Style(color=_color(ch.fg), bgcolor=_color(ch.bg), bold=ch.bold, italic=ch.italics, underline=ch.underscore)
            text.append(ch.data or " ", style=style)
        text.append("\n")
    return text


def main() -> None:
    console = Console(record=True, width=COLS, force_terminal=True, color_system="truecolor", file=open(os.devnull, "w"))
    console.print(to_text(capture()), end="", overflow="crop", no_wrap=True)
    target = ROOT / "docs" / "assets" / "demo.svg"
    console.save_svg(str(target), title="ember", theme=THEME)
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
