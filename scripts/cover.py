"""Record ember's start screen for the top of the README.

    python scripts/cover.py   # writes docs/assets/cover.svg

A frameless capture of a fresh session — banner, environment, input bar and key bar — so the
cover always shows the current wordmark and version.
"""

from __future__ import annotations


from _termshot import ROOT, capture, save_svg, to_text

COLS, ROWS = 120, 20


def main() -> None:
    screen = capture([], COLS, ROWS, args="--vi", cwd=ROOT)
    target = ROOT / "docs" / "assets" / "cover.svg"
    save_svg(to_text(screen), target, COLS, title=None, frameless=True)


if __name__ == "__main__":
    main()
