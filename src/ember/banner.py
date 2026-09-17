"""The startup banner: a pixel wordmark drawn with half-block characters."""

from __future__ import annotations

from rich.text import Text

# 5×7 bitmap glyphs. Rendered with ▀ ▄ █, every terminal cell holds two square-ish pixels.
GLYPHS: dict[str, tuple[str, ...]] = {
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "_": (".....", ".....", ".....", ".....", ".....", ".....", "#####"),
    ":": ("...", ".##", ".##", "...", "...", ".##", ".##"),
}
_HALF = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}


def pixel_rows(word: str, spacing: int = 1) -> list[str]:
    """Render `word` as lines of half-block characters (7 pixel rows → 4 lines)."""
    height = 7
    bitmap = ["" for _ in range(height)]
    for i, ch in enumerate(word.upper()):
        glyph = GLYPHS[ch]
        for row in range(height):
            bitmap[row] += ("." * spacing if i else "") + glyph[row]
    width = len(bitmap[0])
    lines = []
    for top in range(0, height, 2):
        line = ""
        for col in range(width):
            upper = bitmap[top][col] == "#"
            lower = top + 1 < height and bitmap[top + 1][col] == "#"
            line += _HALF[(upper, lower)]
        lines.append(line.rstrip())
    return lines


def wordmark(word: str = "EMBER:", indent: int = 2) -> list[Text]:
    """The wordmark in the accent colour; a trailing underscore blinks like a cursor."""
    blink_from = None
    if word.endswith("_"):
        blink_from = (len(word) - 1) * 6  # 5px glyph + 1px spacing
    lines = []
    for row in pixel_rows(word):
        text = Text(" " * indent)
        if blink_from is None:
            text.append(row, style="ember.accent.bold")
        else:
            text.append(row[:blink_from], style="ember.accent.bold")
            text.append(row[blink_from:], style="ember.accent.blink")
        lines.append(text)
    return lines
