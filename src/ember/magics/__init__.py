"""Magic registry. Built-in magics live in the submodules imported at the bottom."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from ember.utils import Struct


class MagicError(Exception):
    """An error raised by a magic, shown as a one-line message instead of a traceback."""


@dataclass
class MagicSpec:
    name: str
    fn: Callable[..., Any]
    doc: str
    kind: str  # "line" | "cell"
    category: str = "general"
    expand: bool = True  # expand $var / {expr} in the argument line
    usage: str = ""
    user: bool = False


LINE_MAGICS: dict[str, MagicSpec] = {}
CELL_MAGICS: dict[str, MagicSpec] = {}

CATEGORIES = {
    "core": "general",
    "namespace": "namespace & inspection",
    "execution": "running & timing",
    "history": "history & session",
    "osm": "shell & files",
    "gui": "gui & plotting",
}


def _category(fn: Callable) -> str:
    return CATEGORIES.get(fn.__module__.rsplit(".", 1)[-1], "general")


def line_magic(*names: str, doc: str, expand: bool = True, usage: str = ""):
    def deco(fn: Callable) -> Callable:
        for n in names:
            LINE_MAGICS[n] = MagicSpec(n, fn, doc, "line", _category(fn), expand, usage)
        return fn

    return deco


def cell_magic(*names: str, doc: str, expand: bool = True, usage: str = ""):
    def deco(fn: Callable) -> Callable:
        for n in names:
            CELL_MAGICS[n] = MagicSpec(n, fn, doc, "cell", _category(fn), expand, usage)
        return fn

    return deco


def register_user_magic(kind: str, name: str, func: Callable) -> None:
    """Register an IPython-style magic: `func(line)` for line magics, `func(line, cell)` for cell magics."""
    doc = (func.__doc__ or "").strip().split("\n")[0] or "user magic"
    expand = not getattr(func, "_ipython_bypass_var_expand", False)
    local_scope = getattr(func, "needs_local_scope", False)

    def as_line(shell, args):
        return func(args, local_ns=shell.ns) if local_scope else func(args)

    def as_cell(shell, args, body):
        return func(args, body, local_ns=shell.ns) if local_scope else func(args, body)

    if kind in ("line", "line_cell"):
        LINE_MAGICS[name] = MagicSpec(name, as_line, doc, "line", "user", expand, func.__doc__ or "", user=True)
    if kind in ("cell", "line_cell"):
        CELL_MAGICS[name] = MagicSpec(name, as_cell, doc, "cell", "user", expand, func.__doc__ or "", user=True)
    if kind not in ("line", "cell", "line_cell"):
        raise ValueError(f"magic_kind must be line, cell or line_cell, not {kind!r}")


def unregister_magic(name: str) -> bool:
    found = LINE_MAGICS.pop(name, None) is not None
    return CELL_MAGICS.pop(name, None) is not None or found


def magic_docs() -> dict[str, dict[str, str]]:
    """{category: {"%a, %b": doc}}, grouping aliases that share a function."""
    grouped: dict[str, dict[tuple, tuple[list[str], str]]] = {}
    for table, prefix in ((LINE_MAGICS, "%"), (CELL_MAGICS, "%%")):
        for name, spec in table.items():
            key = (spec.fn, prefix) if not spec.user else (name, prefix)
            grouped.setdefault(spec.category, {}).setdefault(key, ([], spec.doc))[0].append(prefix + name)
    return {cat: {", ".join(names): doc for names, doc in entries.values()} for cat, entries in grouped.items()}


# ── option parsing for built-in magics ─────────────────────────────────────

_TOKEN = re.compile(r"\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|\S+)")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def parse_args(args: str, spec: str = "", *long_opts: str) -> tuple[Struct, str]:
    """getopt-style parsing (`"n:r:qo"`, `"out="`) that returns the *untouched* remainder text.

    Parsing stops at the first token that isn't a known option, so code like `%timeit -1 + x`
    stays intact. Repeated options collect into lists."""
    takes = {c: spec[i + 1 : i + 2] == ":" for i, c in enumerate(spec) if c != ":"}
    long_takes = {o.rstrip("="): o.endswith("=") for o in long_opts}
    opts = Struct()

    def add(key: str, value: Any) -> None:
        if key in opts:
            opts[key] = [*opts[key], value] if isinstance(opts[key], list) else [opts[key], value]
        else:
            opts[key] = value

    def token(pos: int) -> tuple[str | None, int]:
        m = _TOKEN.match(args, pos)
        return (m.group(1), m.end()) if m else (None, pos)

    pos = 0
    while True:
        tok, end = token(pos)
        if tok is None or not tok.startswith("-") or tok == "-":
            break
        if tok == "--":
            pos = end
            break
        if tok.startswith("--"):
            name, eq, value = tok[2:].partition("=")
            if name not in long_takes:
                break
            if long_takes[name]:
                if not eq:
                    value, end = token(end)
                    if value is None:
                        raise MagicError(f"option --{name} needs a value")
                add(name, _unquote(value))
            else:
                add(name, True)
            pos = end
            continue
        letters = tok[1:]
        if letters[0] not in takes:
            break
        for i, c in enumerate(letters):
            if c not in takes:
                raise MagicError(f"unknown option -{c}")
            if takes[c]:
                value = letters[i + 1 :]
                if not value:
                    value, end = token(end)
                    if value is None:
                        raise MagicError(f"option -{c} needs a value")
                add(c, _unquote(value))
                break
            add(c, True)
        pos = end
    return opts, args[pos:].strip()


from ember.magics import core, execution, gui, history, namespace, osm  # noqa: E402

BUILTIN_MODULES = (core, execution, gui, history, namespace, osm)  # importing them registers the magics
